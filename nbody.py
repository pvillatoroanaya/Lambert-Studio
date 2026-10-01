"""
Full solar-system gravity: checking a patched-conic route the way mission
navigators do.

The route designs in this app use PATCHED CONICS: at any moment only one
body pulls on the spacecraft (the Sun between planets, a planet during a
flyby). Real trajectories feel everything at once. This module flies the
designed route in a full N-body model and corrects it:

  * Forces: the Sun plus Mercury, Venus, Earth, the Moon, Mars and the
    giant-planet systems, all at their real positions (NASA/JPL DE440s),
    as point masses (heliocentric equations with the indirect terms).
    Integrator: SciPy DOP853 with tight tolerances.
  * Launch: the spacecraft starts 1 million km from Earth on the designed
    departure asymptote.
  * Trajectory correction manoeuvres (TCMs): some days into each leg a
    small burn is computed so that the spacecraft reaches the next planet
    at the planned point and time. The aim point is expressed in the
    B-plane (the plane through the planet perpendicular to the incoming
    direction): B.T, B.R and the time of closest approach, solved by
    Newton's method with a finite-difference Jacobian and Broyden updates,
    as in real flight-dynamics software.
  * Flybys are then flown for real in the N-body model (powered flybys fire
    their planned burn at closest approach), and the next TCM cleans up.

Results: the miss distance without corrections, every TCM, the achieved
flyby altitudes and dates against the plan, and the true total delta-v.
"""

import math
import time

import numpy as np
from scipy.integrate import solve_ivp

from constants import AU, MU_SUN
from planets import PLANET_STYLE

DAY = 86400.0

# GM [km^3/s^2], NASA/JPL DE440 (planetary systems for the barycentres of
# Mars and the giants, as in the ephemeris).
GM = {"Mercury": 22031.868, "Venus": 324858.592, "Earth": 398600.435, "Moon": 4902.800,
      "Mars": 42828.375, "Jupiter": 126712764.1, "Saturn": 37940584.8, "Uranus": 5794556.4,
      "Neptune": 6836527.1}
BODIES = list(GM)
A_AU = {"Mercury": 0.387, "Venus": 0.723, "Earth": 1.0, "Mars": 1.524, "Jupiter": 5.203, "Saturn": 9.537,
        "Uranus": 19.19, "Neptune": 30.07}


RADII = np.array([PLANET_STYLE[b]["radius"] if b != "Moon" else 1737.4 for b in BODIES])


def soi(planet):
    """Laplace sphere of influence [km]."""
    return A_AU[planet] * AU * (GM[planet] / MU_SUN) ** 0.4


class Ephemeris:
    """Heliocentric ecliptic positions of all bodies on a 6-hour grid,
    Hermite-interpolated with the velocities (errors of metres)."""

    STEP = 0.25

    def __init__(self, jd0, jd1):
        from interplanetary import planet_states_array
        self.t0 = math.floor(jd0) - 1.0
        t = self.t0 + self.STEP * np.arange(int((jd1 - self.t0) / self.STEP) + 8)
        R, V = [], []
        for b in BODIES:
            try:
                r, v = planet_states_array(b, t)
            except (KeyError, TypeError):
                raise ValueError("The full-gravity check needs the DE440s ephemeris (for the Moon).")
            R.append(r)
            V.append(v * DAY * self.STEP)          # velocity per grid step (for Hermite)
        self.R = np.stack(R, axis=1)                # (n, bodies, 3)
        self.V = np.stack(V, axis=1)
        self.gm = np.array([GM[b] for b in BODIES])
        self.index = {b: k for k, b in enumerate(BODIES)}
        self.n = len(t)
        self._cache = {}

    def at(self, jd):
        # The integrator and its event checks ask for the same instant many
        # times: keep the last few answers.
        hit = self._cache.get(jd)
        if hit is not None:
            return hit
        if len(self._cache) > 32:
            self._cache.clear()
        out = self._at(jd)
        self._cache[jd] = out
        return out

    def _at(self, jd):
        f = (jd - self.t0) / self.STEP
        k = min(max(int(f), 0), self.n - 2)
        s = f - k
        s2, s3 = s * s, s * s * s
        h00, h10, h01, h11 = 2 * s3 - 3 * s2 + 1, s3 - 2 * s2 + s, -2 * s3 + 3 * s2, s3 - s2
        P = h00 * self.R[k] + h10 * self.V[k] + h01 * self.R[k + 1] + h11 * self.V[k + 1]
        dP = ((6 * s2 - 6 * s) * self.R[k] + (3 * s2 - 4 * s + 1) * self.V[k] + (-6 * s2 + 6 * s) * self.R[k + 1]
              + (3 * s2 - 2 * s) * self.V[k + 1]) / (self.STEP * DAY)
        return P, dP

    def body(self, name, jd):
        P, V = self.at(jd)
        k = self.index[name]
        return P[k], V[k]


class Flight:
    """N-body propagation with events near one target planet."""

    def __init__(self, eph, jd_ref):
        self.eph, self.jd_ref = eph, jd_ref
        self.evals = 0
        self.gm = eph.gm.copy()

    def rhs(self, t, y):
        self.evals += 1
        r = y[:3]
        P, _ = self.eph.at(self.jd_ref + t / DAY)
        d = P - r
        dn3 = np.einsum("ij,ij->i", d, d) ** 1.5
        pn3 = np.einsum("ij,ij->i", P, P) ** 1.5
        a = -MU_SUN * r / (r @ r) ** 1.5 + (self.gm[:, None] * (d / dn3[:, None] - P / pn3[:, None])).sum(axis=0)
        return np.concatenate([y[3:], a])

    def run(self, jd0, y0, jd1, target=None, until=None, dense=False, rtol=1e-10, r_in=None, without=None):
        """Propagate from jd0 to jd1 (JD). `until`: 'soi_in', 'peri' or
        'soi_out' of `target` stops the flight at that event. 'soi_in'
        uses the radius r_in when given (a closer targeting sphere).
        `without`: a body whose gravity is left out (coarse aiming only)."""
        self.gm = self.eph.gm.copy()
        live = np.ones(len(BODIES), bool)
        if without:
            self.gm[self.eph.index[without]] = 0.0
            live[self.eph.index[without]] = False
        t0, t1 = (jd0 - self.jd_ref) * DAY, (jd1 - self.jd_ref) * DAY
        events = []
        if target:
            k = self.eph.index[target]
            r_soi, R = soi(target), PLANET_STYLE[target]["radius"]

            def rel(t, y):
                P, V = self.eph.at(self.jd_ref + t / DAY)
                return y[:3] - P[k], y[3:] - V[k]

            r_enter = r_in or r_soi

            def soi_in(t, y):
                return np.linalg.norm(rel(t, y)[0]) - r_enter
            soi_in.terminal, soi_in.direction = until == "soi_in", -1

            def soi_out(t, y):
                return np.linalg.norm(rel(t, y)[0]) - r_soi
            soi_out.terminal, soi_out.direction = until == "soi_out", 1

            def peri(t, y):
                dr, dv = rel(t, y)
                return float(dr @ dv)
            peri.terminal, peri.direction = until == "peri", 1

            def impact(t, y):
                return np.linalg.norm(rel(t, y)[0]) - R
            impact.terminal, impact.direction = True, -1
            events = [soi_in, soi_out, peri, impact]
        # Any body's surface stops the flight (trial paths of the aiming
        # search can pass through a planet, where the integrator would crawl).
        def crash(t, y):
            P, _ = self.eph.at(self.jd_ref + t / DAY)
            return float(np.min((np.linalg.norm(P - y[:3], axis=1) - RADII)[live]))
        crash.terminal, crash.direction = True, -1
        events = events + [crash]
        atol = np.array([1e-4] * 3 + [1e-10] * 3)
        sol = solve_ivp(self.rhs, (t0, t1), y0, method="DOP853", rtol=rtol, atol=atol, events=events,
                        dense_output=dense)
        sol.crashed = bool(sol.t_events[-1].size)
        if sol.status == -1:
            raise ValueError(f"The N-body integration failed: {sol.message}")
        hit = None
        if len(events) > 1:
            names = ["soi_in", "soi_out", "peri", "impact"]
            for name, te in zip(names, sol.t_events):
                if te.size and (name == until or name == "impact"):
                    if hit is None or te[0] < hit[1]:
                        hit = (name, te[0])
        return sol, hit


def bplane(eph, planet, jd, r, v):
    """Osculating planet-centred hyperbola: B.T, B.R [km], closest
    approach radius [km], time of closest approach (JD) and v-infinity."""
    P, V = eph.body(planet, jd)
    dr, dv = r - P, v - V
    mu = GM[planet]
    rn, vn2 = np.linalg.norm(dr), dv @ dv
    energy = vn2 / 2 - mu / rn
    if energy <= 0:
        return None
    vinf = math.sqrt(2 * energy)
    a = mu / vinf ** 2
    h = np.cross(dr, dv)
    hn = np.linalg.norm(h)
    evec = np.cross(dv, h) / mu - dr / rn
    e = np.linalg.norm(evec)
    phat, hhat = evec / e, h / hn
    qhat = np.cross(hhat, phat)
    s = phat / e + math.sqrt(1 - 1 / e ** 2) * qhat              # incoming asymptote direction
    b = a * math.sqrt(e * e - 1)
    B = b * np.cross(s, hhat)
    T = np.cross(s, [0.0, 0.0, 1.0])
    T /= np.linalg.norm(T)
    Rh = np.cross(s, T)
    coshF = (rn / a + 1) / e
    F = math.acosh(max(coshF, 1.0)) * (1 if dr @ dv > 0 else -1)
    t_from_peri = (e * math.sinh(F) - F) / math.sqrt(mu / a ** 3)
    return {"BT": float(B @ T), "BR": float(B @ Rh), "rp": a * (e - 1), "tp": jd - t_from_peri / DAY,
            "vinf": vinf, "s": s}


def _target_B(planet, vin, vout, rp):
    """Designed aim point: B vector from the patched-conic flyby."""
    mu = GM[planet]
    vi = np.linalg.norm(vin)
    s = vin / vi
    h = np.cross(vin, vout)
    if np.linalg.norm(h) < 1e-9:
        h = np.cross(s, [0.0, 0.0, 1.0])
    h /= np.linalg.norm(h)
    b = rp * math.sqrt(1 + 2 * mu / (rp * vi * vi))
    B = b * np.cross(s, h)
    T = np.cross(s, [0.0, 0.0, 1.0])
    T /= np.linalg.norm(T)
    return float(B @ T), float(B @ np.cross(s, T))


def _hyper_state(planet, vinf_vec, rp, r_out):
    """Departure hyperbola: distance along the asymptote [km], speed there, and time from periapsis [s]."""
    mu = GM[planet]
    v = np.linalg.norm(vinf_vec)
    a, e = mu / v ** 2, 1 + rp * v * v / mu
    F = math.acosh((r_out / a + 1) / e)
    t = (e * math.sinh(F) - F) / math.sqrt(mu / a ** 3)
    return math.sqrt(v * v + 2 * mu / r_out), t


class _Aim:
    """What a correction aims for at one planet: B-plane coordinates of the
    designed flyby (or arrival) and its time of closest approach."""

    def __init__(self, det, k):
        seq, legs, jds = det["seq"], det["legs"], det["jds"]
        self.planet = planet = seq[k]
        self.k = k
        self.final = k == len(seq) - 1
        self.R = R = PLANET_STYLE[planet]["radius"]
        self.vin = legs[k - 1]["v2"] - legs[k - 1]["vp2"]
        self.vi = float(np.linalg.norm(self.vin))
        self.s = self.vin / self.vi
        if self.final:
            self.rp = 1.2 * R if planet in ("Jupiter", "Saturn", "Uranus", "Neptune") else R + 400.0
            self.vout = None
            self.burn = 0.0
            T = np.cross(self.s, [0.0, 0.0, 1.0])
            self.B = _b_len(planet, self.vi, self.rp) * T / np.linalg.norm(T)
        else:
            fb = det["flybys"][k - 1]
            self.rp = fb["rp"]
            self.vout = legs[k]["v1"] - legs[k]["vp1"]
            self.burn = float(fb["dv"])
            h = np.cross(self.vin, self.vout)
            if np.linalg.norm(h) < 1e-9:
                h = np.cross(self.s, [0.0, 0.0, 1.0])
            h /= np.linalg.norm(h)
            self.B = _b_len(planet, self.vi, self.rp) * np.cross(self.s, h)
        T = np.cross(self.s, [0.0, 0.0, 1.0])
        T /= np.linalg.norm(T)
        self.BT, self.BR = float(self.B @ T), float(self.B @ np.cross(self.s, T))
        self.tp = jds[k]
        # Aim measured on a sphere close enough that the Sun barely bends the
        # planet-centred hyperbola any more.
        self.r_t = min(soi(planet), max(100 * R, 3 * self.rp))
        self.tol = 1.0 if R < 1e4 else 50.0


def _b_len(planet, vinf, rp):
    return rp * math.sqrt(1 + 2 * GM[planet] / (rp * vinf * vinf))


def verify(det, max_iter=8):
    """
    Fly a patched-conic route (flyby.evaluate(..., detail=True) output,
    with seq/jds/capture/launch_dv added) in full solar-system gravity.
    """
    t_start = time.perf_counter()
    seq, jds, legs = det["seq"], det["jds"], det["legs"]
    eph = Ephemeris(jds[0], jds[-1] + 60)
    fl = Flight(eph, jds[0])
    notes = []
    aims = {k: _Aim(det, k) for k in range(1, len(seq))}

    # Launch: 1 million km out on the designed departure asymptote.
    vinf0 = legs[0]["v1"] - legs[0]["vp1"]
    r_out = 1.0e6
    mu0 = GM[seq[0]]
    speed, t_hyp = _hyper_state(seq[0], vinf0, PLANET_STYLE[seq[0]]["radius"] + 200.0, r_out)
    jd = jds[0] + t_hyp / DAY
    PE, VE = eph.body(seq[0], jd)
    s0 = vinf0 / np.linalg.norm(vinf0)
    y = np.concatenate([PE + r_out * s0, VE + speed * s0])
    jd_launch_state = jd

    # 1. The design as it is, without corrections: how close to the first target?
    a1 = aims[1]
    sol, _ = fl.run(jd, y.copy(), jds[1] + 40, dense=True, rtol=1e-10)
    if sol.crashed:
        P, _ = eph.at(jds[0] + sol.t[-1] / DAY)
        hit = BODIES[int(np.argmin(np.linalg.norm(P - sol.y[:3, -1], axis=1) - RADII))]
        uncorrected = {"planet": hit, "miss_km": 0.0, "impact": True, "jd": float(jds[0] + sol.t[-1] / DAY)}
    else:
        ts = np.linspace(sol.t[0], sol.t[-1], 40000)
        Y = sol.sol(ts)
        Pp = np.array([eph.body(a1.planet, jds[0] + x / DAY)[0] for x in ts])
        dists = np.linalg.norm(Y[:3].T - Pp, axis=1)
        i_min = int(np.argmin(dists))
        uncorrected = {"planet": a1.planet, "miss_km": float(dists[i_min]), "impact": False,
                       "jd": float(jds[0] + ts[i_min] / DAY)}

    track, tcms, encounters = [], [], []

    def sample(sol_obj, n):
        tt = np.linspace(sol_obj.t[0], sol_obj.t[-1], n)
        track.extend((sol_obj.sol(tt)[:3].T / AU).tolist())

    def bplane_error(aim, s_, hit):
        if not hit or hit[0] != "soi_in":
            return None
        bp = bplane(eph, aim.planet, jds[0] + hit[1] / DAY, s_.y[:3, -1], s_.y[3:, -1])
        if bp is None:
            return None
        return np.array([bp["BT"] - aim.BT, bp["BR"] - aim.BR, (bp["tp"] - aim.tp) * DAY])

    def solve(err_fn, dv0, tol_km, h=1e-6, time_free=False):
        """Newton / Broyden on a 3-vector error; returns (dv, err, sol, ok).
        time_free: only the aim point (B.T, B.R) is enforced and each step is
        the smallest burn that achieves it (the encounter time may drift a
        little), which is how navigators keep corrections cheap."""
        dv = dv0.copy()
        err, s_best = err_fn(dv)
        if err is None:
            return dv, None, s_best, False
        J = np.zeros((3, 3))
        for c in range(3):
            e_c = np.zeros(3)
            e_c[c] = h
            ec, _ = err_fn(dv + e_c)
            if ec is None:
                return dv, err, s_best, False
            J[:, c] = (ec - err) / h
        scale = np.array([1.0, 1.0, 0.0 if time_free else 1.0 / 20.0])   # 20 s of timing ~ 1 km of aim

        def done(e):
            return abs(e[0]) < tol_km and abs(e[1]) < tol_km and (time_free or abs(e[2]) < 60.0)

        for _ in range(max_iter):
            if done(err):
                return dv, err, s_best, True
            try:
                if time_free:
                    J2 = J[:2]
                    step = -J2.T @ np.linalg.solve(J2 @ J2.T, err[:2])     # minimum-norm step
                else:
                    step = -np.linalg.solve(J, err)
            except np.linalg.LinAlgError:
                break
            lam, e_new = 1.0, None
            for _ in range(8):
                e_new, s_new = err_fn(dv + lam * step)
                if e_new is not None and np.linalg.norm(e_new * scale) < np.linalg.norm(err * scale):
                    break
                lam *= 0.5
            else:
                break
            ds = lam * step
            J = J + np.outer((e_new - err) - J @ ds, ds) / (ds @ ds)
            dv, err, s_best = dv + ds, e_new, s_new
        return dv, err, s_best, done(err)

    launch_change = 0.0
    total_tcm = 0.0
    k = 1
    while k < len(seq):
        aim = aims[k]
        first = k == 1
        # Where the correction is made: at launch for the first leg (the
        # rocket is aimed with the full model), otherwise some days out.
        if not first:
            leg_days = aim.tp - jd
            jd_tcm = jd + min(10.0, 0.25 * leg_days)
            s_c, _ = fl.run(jd, y, jd_tcm, dense=True)
            sample(s_c, 12)
            y = s_c.y[:, -1].copy()
            jd = jd_tcm

        y_here, jd_here = y.copy(), jd

        def coarse(target, dv, h=1e-5, stop=2000.0, ignore=False):
            """Aim at a point on the target's designed approach line, a little
            before its targeting sphere. ignore=True leaves the target's own
            gravity out (needed when trial paths would hit it)."""
            lead = 1.5 * target.r_t / target.vi / DAY
            jd_aim = target.tp - lead

            def miss_pos(dv3):
                yy = y_here.copy()
                yy[3:] += dv3
                s_, _ = fl.run(jd_here, yy, jd_aim, rtol=1e-10, without=target.planet if ignore else None)
                if s_.crashed:                      # a trial path through a planet: a very bad guess
                    return np.full(3, 1e9)
                P_, _v = eph.body(target.planet, jd_aim)
                return s_.y[:3, -1] - (P_ - target.s * target.vi * lead * DAY + target.B)

            e0 = miss_pos(dv)
            for _ in range(8):
                if np.linalg.norm(e0) < stop:
                    break
                Jp = np.zeros((3, 3))
                for c in range(3):
                    e_c = np.zeros(3)
                    e_c[c] = h
                    Jp[:, c] = (miss_pos(dv + e_c) - e0) / h
                step = -np.linalg.solve(Jp, e0)          # LinAlgError when every trial crashes
                lam = 1.0
                for _ in range(8):
                    e1 = miss_pos(dv + lam * step)
                    if np.linalg.norm(e1) < np.linalg.norm(e0):
                        break
                    lam *= 0.5
                dv, e0 = dv + lam * step, e1
            return dv, float(np.linalg.norm(e0))

        def coarse_any(target, dv, **kw):
            """With the target's gravity first; without it if that fails."""
            try:
                out, miss_km = coarse(target, dv.copy(), **kw)
                if miss_km < 1e6:
                    return out
            except np.linalg.LinAlgError:
                pass
            return coarse(target, dv.copy(), ignore=True, **kw)[0]

        # Stage 1: coarse aim at this planet.
        dv = coarse_any(aim, np.zeros(3))

        # Stage 2: B-plane aim at this planet.
        def local(dv3, aim=aim):
            yy = y_here.copy()
            yy[3:] += dv3
            s_, hit = fl.run(jd_here, yy, aim.tp + 60, target=aim.planet, until="soi_in", dense=True, r_in=aim.r_t)
            return bplane_error(aim, s_, hit), s_

        dv, err, s_best, ok = solve(local, dv, aim.tol, time_free=aim.final)
        if err is None:
            raise ValueError(f"The spacecraft could not be steered to {aim.planet}; "
                             "the full-gravity check cannot continue from this design.")

        # Stage 3: for an unpowered flyby, aim THROUGH it at the next planet,
        # so the flyby bends the path exactly as needed (the flyby altitude
        # adjusts itself slightly). Not for a planet met twice in a row.
        # Only for distant flybys: through a close pass (Galileo's 300 km over
        # Earth) the sensitivity is enormous, and navigators aim such flybys
        # at their own aim point, then clean up afterwards.
        through = (not aim.final and aim.burn < 0.05 and seq[k + 1] != aim.planet and aim.rp > 5 * aim.R)
        if through:
            nxt = aims[k + 1]

            def via(dv3, nxt=nxt):
                yy = y_here.copy()
                yy[3:] += dv3
                s_, hit = fl.run(jd_here, yy, nxt.tp + 60, target=nxt.planet, until="soi_in", dense=True, r_in=nxt.r_t)
                # Reject paths that would clip the flyby planet.
                tt = np.linspace(max(s_.t[0], (aim.tp - 3 - jds[0]) * DAY), min(s_.t[-1], (aim.tp + 3 - jds[0]) * DAY), 400)
                if tt.size and tt[-1] > tt[0]:
                    Pk = np.array([eph.body(aim.planet, jds[0] + x / DAY)[0] for x in tt])
                    if np.min(np.linalg.norm(s_.sol(tt)[:3].T - Pk, axis=1)) < aim.R * 1.02:
                        return None, s_
                return bplane_error(nxt, s_, hit), s_

            dv_c = coarse_any(nxt, dv, h=1e-7, stop=20000.0)
            dv2, err2, s2, ok2 = solve(via, dv_c, nxt.tol, h=1e-7)
            if err2 is not None and (ok2 or np.linalg.norm(err2[:2]) < 1e4):
                dv, ok = dv2, ok2
                # Re-fly to this planet's sphere with the final correction.
                err, s_best = local(dv)
                if err is None:
                    err, s_best = np.zeros(3), s2
            else:
                through = False
                notes.append(f"Aiming through {aim.planet} at {nxt.planet} did not converge; "
                             f"the flyby was aimed at its designed point instead.")

        if first:
            v_new = y[3:] + dv
            P0, V0 = eph.body(seq[0], jd)
            vrel = np.linalg.norm(v_new - V0)
            vinf_new = math.sqrt(max(vrel ** 2 - 2 * mu0 / np.linalg.norm(y[:3] - P0), 0.0))
            from flyby import _launch_dv
            launch_change = float(_launch_dv(vinf_new, seq[0]) - det.get("launch_dv", 0.0))
            tcms.append({"jd": jd, "dv": float(np.linalg.norm(dv)), "to": aim.planet, "leg": k, "converged": ok,
                         "kind": "launch aim", "launch_change": launch_change, "vinf": vinf_new})
        else:
            tcm = float(np.linalg.norm(dv))
            total_tcm += tcm
            tcms.append({"jd": jd, "dv": tcm, "to": seq[k + 1] if through else aim.planet, "leg": k,
                         "converged": ok, "kind": "TCM"})
        if not ok and aim.final:
            notes.append(f"The correction toward {aim.planet} did not fully converge.")
        sample(s_best, 140)
        y = s_best.y[:, -1].copy()
        jd = jds[0] + s_best.t[-1] / DAY

        # Approach correction: near the planet the Sun's (and for Earth the
        # Moon's) pull still shifts the closest approach a little; a small burn
        # along the aim direction puts it at the planned height, as real
        # missions do days before an encounter. (Not for a flyby aimed through
        # to the next planet: its height is free.)
        if not through:
            P0, V0 = eph.body(aim.planet, jd)
            bdir = aim.B / np.linalg.norm(aim.B)
            y_app, jd_app = y.copy(), jd

            # Time to closest approach from here (straight-line estimate) bounds each run.
            reach = 3.0 * np.linalg.norm(y_app[:3] - P0) / aim.vi / DAY + 5.0

            def rp_err(x):
                yy = y_app.copy()
                yy[3:] += x * bdir
                s_, hit = fl.run(jd_app, yy, jd_app + reach, target=aim.planet, until="peri")
                P_, _ = eph.body(aim.planet, jds[0] + s_.t[-1] / DAY)
                return float(np.linalg.norm(s_.y[:3, -1] - P_)) - aim.rp

            x0, f0 = 0.0, rp_err(0.0)
            x1 = -1e-5 * np.sign(f0) if f0 else 0.0
            f1 = f0
            if abs(f0) > 1.0:
                f1 = rp_err(x1)
                for _ in range(12):
                    if abs(f1) < 1.0 or f1 == f0:
                        break
                    x2 = x1 - f1 * (x1 - x0) / (f1 - f0)
                    x2 = max(min(x2, x1 + 0.05), x1 - 0.05)          # never more than 50 m/s per step
                    x0, f0, x1 = x1, f1, x2
                    f1 = rp_err(x1)
                y[3:] += x1 * bdir
                total_tcm += abs(x1)
                tcms.append({"jd": jd, "dv": abs(x1), "to": aim.planet, "leg": k, "converged": abs(f1) < 5.0,
                             "kind": "approach TCM"})

        # Fly through the encounter: to closest approach...
        s_p, hit = fl.run(jd, y, jd + 400, target=aim.planet, until="peri", dense=True)
        if hit and hit[0] == "impact":
            raise ValueError(f"The corrected trajectory hits {aim.planet}.")
        sample(s_p, 60)
        y = s_p.y[:, -1].copy()
        jd = jds[0] + s_p.t[-1] / DAY
        P, V = eph.body(aim.planet, jd)
        rp_act = float(np.linalg.norm(y[:3] - P))
        vp_act = float(np.linalg.norm(y[3:] - V))
        enc = {"planet": aim.planet, "kind": "arrival" if aim.final else "flyby",
               "jd_planned": aim.tp, "jd_actual": jd, "alt_planned": aim.rp - aim.R, "alt_actual": rp_act - aim.R,
               "vinf_planned": aim.vi,
               "vinf_actual": float(math.sqrt(max(vp_act ** 2 - 2 * GM[aim.planet] / rp_act, 0.0)))}
        if aim.final:
            if det.get("capture"):
                if aim.planet in ("Jupiter", "Saturn", "Uranus", "Neptune"):
                    ra = 100 * aim.R
                    v_ell = math.sqrt(GM[aim.planet] * (2 / rp_act - 2 / (rp_act + ra)))
                else:
                    v_ell = math.sqrt(GM[aim.planet] / rp_act)
                enc["capture_dv"] = vp_act - v_ell
            encounters.append(enc)
            break
        # ...a powered flyby fires its planned burn there...
        if aim.burn > 1e-4:
            vo = float(np.linalg.norm(aim.vout))
            mu = GM[aim.planet]
            dvp = math.sqrt(vo ** 2 + 2 * mu / rp_act) - math.sqrt(aim.vi ** 2 + 2 * mu / rp_act)
            rel = y[3:] - V
            y[3:] += dvp * rel / np.linalg.norm(rel)
            enc["burn"] = abs(dvp)
        encounters.append(enc)
        # ...and on out of its sphere of influence.
        s_o, hit = fl.run(jd, y, jd + 800, target=aim.planet, until="soi_out", dense=True)
        sample(s_o, 60)
        y = s_o.y[:, -1].copy()
        jd = jds[0] + s_o.t[-1] / DAY
        k += 1

    powered = [(e["planet"], e["burn"]) for e in encounters if e.get("burn", 0) > 0.3]
    if powered:
        notes.append("This design fires the engine during a flyby ("
                     + ", ".join(f"{b:.2f} km/s at {p_}" for p_, b in powered)
                     + "). The simple model uses such burns as a shortcut; in real gravity they are the least accurate "
                       "part, which is why the corrections are larger. Real missions move them into deep space.")
    launch_dv = float(det.get("launch_dv", 0.0)) + launch_change
    burns = sum(e.get("burn", 0.0) for e in encounters)
    cap = encounters[-1].get("capture_dv", 0.0) if encounters else 0.0
    return {
        "track_au": track, "tcms": tcms, "encounters": encounters, "uncorrected": uncorrected,
        "launch_dv": launch_dv, "launch_change": launch_change, "tcm_total": total_tcm, "flyby_burns": burns,
        "capture_dv": cap, "total_dv": launch_dv + total_tcm + burns + cap, "design_total_dv": det["total_dv"],
        "bodies": BODIES, "notes": notes, "evaluations": fl.evals, "seconds": time.perf_counter() - t_start,
        "start_jd": jd_launch_state,
    }
