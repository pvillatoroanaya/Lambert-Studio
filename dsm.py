"""
Deep-space maneuvers: the "Delta-V Earth Gravity Assist" (dV-EGA) flown by
Juno, and the general idea of firing the engine far from any planet.

Route: launch from Earth -> coast -> engine burn in deep space (DSM) ->
coast back to Earth -> Earth flyby -> destination.

Why it works: launching straight to Jupiter needs a very high launch energy.
Instead the spacecraft is launched into a ~2-year orbit that goes out
beyond Mars. Near its far point a modest burn (Juno: two burns in Aug/Sep
2012, about 0.8 km/s together) re-aims it so that it comes back past Earth
much faster than it left; the Earth flyby then turns that speed toward
Jupiter. The rocket needed is much smaller.

Model (the "MGA-1DSM" formulation used in ESA's trajectory benchmarks):
    x = [launch date, v_inf at launch, its two direction angles,
         eta (fraction of leg 1 before the burn), T1, T2]
Leg 1a is pure Keplerian coasting from Earth; leg 1b is a Lambert arc from
the burn point back to Earth; leg 2 is a Lambert arc from Earth to the
target. The Earth flyby may need a small powered burn (the same model as
flyby.py). Global search: SciPy differential evolution (vectorised),
then a Nelder-Mead polish.
"""

import math
import time

import numpy as np
from scipy.optimize import differential_evolution, minimize

from constants import MU_SUN, AU
from frames import propagate
from interplanetary import best_planet_state, planet_states_array, ephemeris_source
from lambert_solver import lambert_batch, lambert_universal, _stumpff_vec
from flyby import flyby_analysis, capture_dv, _launch_dv, _flyby_vec, IMPOSSIBLE, optimise

DAY = 86400.0


# ----------------------------------------------------------------------
# vectorised universal-variable Kepler propagation (many states at once)
# ----------------------------------------------------------------------

def propagate_batch(r0, v0, dt, mu=MU_SUN, iters=60):
    """Propagate (n,3) states by dt (n,) seconds; universal variables, Newton."""
    r0n = np.linalg.norm(r0, axis=1)
    v0n2 = np.einsum("ij,ij->i", v0, v0)
    rv = np.einsum("ij,ij->i", r0, v0) / np.sqrt(mu)
    alpha = 2.0 / r0n - v0n2 / mu
    sq = np.sqrt(mu)
    x = sq * np.abs(alpha) * dt                      # good start for ellipses
    x = np.where(alpha > 1e-12, x, sq * dt / r0n)
    for _ in range(iters):
        z = alpha * x * x
        C, S = _stumpff_vec(z)
        F = rv * x * x * C + (1 - alpha * r0n) * x ** 3 * S + r0n * x - sq * dt
        dF = rv * x * (1 - z * S) + (1 - alpha * r0n) * x * x * C + r0n
        step = F / dF
        x = x - step
        if np.all(np.abs(step) < 1e-9 * (1 + np.abs(x))):
            break
    z = alpha * x * x
    C, S = _stumpff_vec(z)
    f = 1 - x * x / r0n * C
    g = dt - x ** 3 / sq * S
    r = f[:, None] * r0 + g[:, None] * v0
    rn = np.linalg.norm(r, axis=1)
    fd = sq / (rn * r0n) * (alpha * x ** 3 * S - x)
    gd = 1 - x * x / rn * C
    v = fd[:, None] * r0 + gd[:, None] * v0
    return r, v


def _launch_frame(r, v):
    """Unit vectors: along Earth's velocity, sideways (in plane), normal."""
    i = v / np.linalg.norm(v, axis=-1, keepdims=True)
    k = np.cross(r, v)
    k /= np.linalg.norm(k, axis=-1, keepdims=True)
    j = np.cross(k, i)
    return i, j, k


class _States:
    """Planet states on a daily grid, Hermite-interpolated (vectorised)."""

    def __init__(self, planet, jd0, jd1):
        self.t0 = math.floor(jd0) - 2
        t = self.t0 + np.arange(int(jd1 - self.t0) + 4)
        R, V = planet_states_array(planet, t)
        self.R, self.V = R, V * DAY

    def __call__(self, jd):
        jd = np.atleast_1d(jd)
        f = jd - self.t0
        k = np.clip(f.astype(int), 0, len(self.R) - 2)
        s = (f - k)[:, None]
        p0, p1, v0, v1 = self.R[k], self.R[k + 1], self.V[k], self.V[k + 1]
        s2, s3 = s * s, s * s * s
        r = (2 * s3 - 3 * s2 + 1) * p0 + (s3 - 2 * s2 + s) * v0 + (-2 * s3 + 3 * s2) * p1 + (s3 - s2) * v1
        dr = (6 * s2 - 6 * s) * p0 + (3 * s2 - 4 * s + 1) * v0 + (-6 * s2 + 6 * s) * p1 + (3 * s2 - 2 * s) * v1
        return r, dr / DAY


# ----------------------------------------------------------------------
# the route model
# ----------------------------------------------------------------------

def _evaluate_batch(X, E, P, target, capture):
    """Total delta-v for a population X (n, 7)."""
    t0, vinf, u, w, eta, T1, T2 = X.T
    rE0, vE0 = E(t0)
    i, j, k = _launch_frame(rE0, vE0)
    d = (np.cos(w) * np.cos(u))[:, None] * i + (np.cos(w) * np.sin(u))[:, None] * j + np.sin(w)[:, None] * k
    v0 = vE0 + vinf[:, None] * d
    r_dsm, v_minus = propagate_batch(rE0, v0, eta * T1 * DAY)
    t1 = t0 + T1
    rE1, vE1 = E(t1)
    vb1, vb2, _, ok1 = lambert_batch(r_dsm, rE1, (1 - eta) * T1 * DAY, mu=MU_SUN)
    t2 = t1 + T2
    rP2, vP2 = P(t2)
    vc1, vc2, _, ok2 = lambert_batch(rE1, rP2, T2 * DAY, mu=MU_SUN)
    dsm = np.linalg.norm(vb1 - v_minus, axis=1)
    fb_dv, pen = _flyby_vec("Earth", vb2 - vE1, vc1 - vE1)
    v_arr = np.linalg.norm(vc2 - vP2, axis=1)
    cost = _launch_dv(vinf, "Earth") + dsm + fb_dv + pen
    if capture:
        cost = cost + capture_dv(v_arr, target)
    return np.where(ok1 & ok2 & np.isfinite(cost), cost, 1e3)


def _detail(x, target, capture):
    """Full, scalar evaluation of one solution (for the result and the polish)."""
    t0, vinf, u, w, eta, T1, T2 = x
    rE0, vE0 = best_planet_state("Earth", t0)
    i, j, k = _launch_frame(rE0, vE0)
    d = math.cos(w) * math.cos(u) * i + math.cos(w) * math.sin(u) * j + math.sin(w) * k
    v0 = vE0 + vinf * d
    r_dsm, v_minus = propagate(rE0, v0, eta * T1 * DAY, mu=MU_SUN)
    t1, t2 = t0 + T1, t0 + T1 + T2
    rE1, vE1 = best_planet_state("Earth", t1)
    vb1, vb2, _ = lambert_universal(r_dsm, rE1, (1 - eta) * T1 * DAY, mu=MU_SUN)
    rP2, vP2 = best_planet_state(target, t2)
    vc1, vc2, _ = lambert_universal(rE1, rP2, T2 * DAY, mu=MU_SUN)
    fb = flyby_analysis("Earth", vb2 - vE1, vc1 - vE1)
    v_arr = float(np.linalg.norm(vc2 - vP2))
    dsm = float(np.linalg.norm(vb1 - v_minus))
    launch = float(_launch_dv(vinf, "Earth"))
    cap = float(capture_dv(v_arr, target)) if capture else 0.0
    total = launch + dsm + fb["dv"] + cap
    return {"x": list(map(float, x)), "jds": [t0, t0 + eta * T1, t1, t2], "vinf_launch": vinf, "launch_dv": launch,
            "dsm_dv": dsm, "flyby": fb, "vinf_arrive": v_arr, "capture_dv": cap if capture else None,
            "total_dv": total, "feasible": fb["feasible"],
            "legs": [
                {"r1": rE0, "v1": v0, "r2": r_dsm, "v2": v_minus, "vp1": vE0, "kind": "coast"},
                {"r1": r_dsm, "v1": vb1, "r2": rE1, "v2": vb2, "vp1": None, "kind": "coast"},
                {"r1": rE1, "v1": vc1, "r2": rP2, "v2": vc2, "vp1": vE1, "vp2": vP2, "kind": "coast"},
            ], "vE1": vE1, "vP2": vP2}


def optimise_dsm(window, target="Jupiter", capture=True, T1=(500, 900), T2=(600, 1300), seed=1,
                 popsize=24, maxiter=250):
    """Best Earth-DSM-Earth-target trajectory for launches within `window` (JDs)."""
    t_start = time.perf_counter()
    E = _States("Earth", window[0] - 5, window[1] + T1[1] + 5)
    P = _States(target, window[0] + T1[0] - 5, window[1] + T1[1] + T2[1] + 5)
    bounds = [window, (3.0, 9.0), (-math.pi, math.pi), (-0.6, 0.6), (0.1, 0.9), T1, T2]
    evals = [0]

    def f(X):
        X = np.asarray(X).T                      # scipy passes (7, S)
        evals[0] += len(X)
        return _evaluate_batch(X, E, P, target, capture)

    with np.errstate(all="ignore"):
        res = differential_evolution(f, bounds, seed=seed, popsize=popsize, maxiter=maxiter, tol=1e-7,
                                     vectorized=True, updating="deferred", polish=False)

        def g(x):
            if any(not (lo - 1e-9 <= xi <= hi + 1e-9) for xi, (lo, hi) in zip(x, bounds)):
                return 1e3
            try:
                d = _detail(x, target, capture)
            except ValueError:
                return 1e3
            return d["total_dv"] + (0 if d["feasible"] else IMPOSSIBLE)

        pol = minimize(g, res.x, method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-6, "maxiter": 2500})
    best = _detail(pol.x if pol.fun <= g(res.x) else res.x, target, capture)
    best["search"] = {"evaluated": int(evals[0] + pol.nfev), "seconds": time.perf_counter() - t_start}
    best["target"] = target
    best["capture"] = capture
    return best


# ----------------------------------------------------------------------
# presentation (same shape as flyby.describe, so the same views can show it)
# ----------------------------------------------------------------------

def describe_dsm(det, n_per_leg=200):
    jds, legs = det["jds"], det["legs"]
    target = det["target"]
    track, t_days, speed, escape = [], [], [], []
    leg_info, idx = [], 0
    names = [("Earth", "deep-space burn"), ("deep-space burn", "Earth"), ("Earth", target)]
    for k, L in enumerate(legs):
        dt = (jds[k + 1] - jds[k]) * DAY
        for s in np.linspace(0.0, dt, n_per_leg):
            r, v = propagate(L["r1"], L["v1"], float(s), mu=MU_SUN)
            rn = float(np.linalg.norm(r))
            track.append((r / AU).tolist())
            t_days.append(jds[k] - jds[0] + s / DAY)
            speed.append(float(np.linalg.norm(v)))
            escape.append(math.sqrt(2 * MU_SUN / rn))
        v1 = L["v1"]
        a = 1.0 / (2.0 / np.linalg.norm(L["r1"]) - v1 @ v1 / MU_SUN)
        leg_info.append({"from": names[k][0], "to": names[k][1], "days": jds[k + 1] - jds[k], "revs": 0, "branch": 0,
                         "start": idx, "end": idx + n_per_leg, "same_planet": False,
                         "period_days": 2 * math.pi * math.sqrt(a ** 3 / MU_SUN) / DAY if a > 0 else None})
        idx += n_per_leg
    fb = det["flyby"]
    L0, L1, L2 = legs
    vE1, vP2 = det["vE1"], det["vP2"]
    v_before = float(np.linalg.norm(L1["v2"]))
    v_after = float(np.linalg.norm(L2["v1"]))
    events = [
        {"kind": "launch", "planet": "Earth", "jd": jds[0], "vinf": det["vinf_launch"], "c3": det["vinf_launch"] ** 2,
         "dv": det["launch_dv"], "v_helio_after": float(np.linalg.norm(L0["v1"])),
         "v_planet": float(np.linalg.norm(L0["vp1"]))},
        {"kind": "dsm", "planet": "deep space", "jd": jds[1], "dv": det["dsm_dv"],
         "r_au": float(np.linalg.norm(L0["r2"])) / AU,
         "v_helio_before": float(np.linalg.norm(L0["v2"])), "v_helio_after": float(np.linalg.norm(L1["v1"]))},
        {"kind": "flyby", "planet": "Earth", "jd": jds[2], **fb,
         "v_helio_before": v_before, "v_helio_after": v_after, "gain": v_after - v_before,
         "v_planet": float(np.linalg.norm(vE1)), "r_au": float(np.linalg.norm(L2["r1"])) / AU,
         "v_planet_vec": vE1.tolist(), "vinf_in_vec": (L1["v2"] - vE1).tolist(),
         "vinf_out_vec": (L2["v1"] - vE1).tolist(),
         "sun_dir": (-L2["r1"] / np.linalg.norm(L2["r1"])).tolist(),
         "mu": 398600.4418, "radius": 6378.1366, "repeat": False},
        {"kind": "arrival", "planet": target, "jd": jds[3], "vinf": det["vinf_arrive"],
         "v_helio_before": float(np.linalg.norm(L2["v2"])), "capture_dv": det["capture_dv"]},
    ]
    return {"seq": ["Earth", "Earth", target], "jds": jds, "track_au": track, "t_days": t_days, "speed": speed,
            "escape_speed": escape, "events": events, "legs": leg_info, "total_dv": det["total_dv"],
            "feasible": det["feasible"], "capture": det["capture"], "tof_days": jds[-1] - jds[0],
            "search": det["search"], "ephemeris": ephemeris_source(), "dsm": True}


def plan_dsm(window, target="Jupiter", capture=True, max_days=None):
    best = optimise_dsm(window, target, capture)
    out = describe_dsm(best)
    out["max_days"] = max_days
    try:
        direct = optimise(["Earth", target], window, capture, max_days=max_days or 4000)
        from flyby import describe
        out["direct"] = describe(direct) if direct else None
    except ValueError:
        out["direct"] = None
    return out


PRESETS = [
    {"key": "juno", "label": "Juno: Earth → deep-space burn → Earth → Jupiter", "target": "Jupiter",
     "from": "2011-08-05", "to": "2011-08-26", "capture": True, "max_years": 6,
     "history": "The launch window here is Juno's real launch period (5-26 Aug 2011). Juno launched on 5 Aug 2011 "
                "on an Atlas V 551 into a 2-year loop beyond Mars; two main-engine burns on 30 Aug and 14 Sep 2012 "
                "re-aimed it; it flew past Earth on 9 Oct 2013 at 559 km altitude and entered orbit around Jupiter "
                "on 5 Jul 2016 (4 Jul in US time zones)."},
]
