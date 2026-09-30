"""
Arrival at a giant planet: orbit capture, then a "moon tour".

After a braking burn puts the spacecraft into a long, loose orbit around
the planet, repeated flybys of its large moons reshape that orbit for free.
This is how Galileo, Cassini, Juno and JUICE were flown.

Model (planar patched conics, as used for preliminary tour design):
- moons move on circular, coplanar orbits;
- at a flyby the velocity relative to the moon (v-infinity) keeps its size
  and only turns, by at most the angle the moon's gravity allows;
- after each flyby the spacecraft orbit is chosen to be RESONANT with the
  moon (N moon laps = M spacecraft laps), so the two meet again;
- a tour may pump with one moon (A) and then move to a second one (B)
  once the orbit crosses B's orbit; ending with an orbit insertion at B.

Geometry at a moon at radius r with circular speed V: the spacecraft's
velocity relative to the moon, v_inf, makes the "pump angle" alpha with the
moon's velocity. Then
    v^2 = V^2 + v_inf^2 + 2 V v_inf cos(alpha)      (energy -> period)
    h   = r (V + v_inf cos(alpha))                   (angular momentum)
so for a given v_inf the possible orbits form a one-parameter family: the
contours of the Tisserand graph.

Moon data: NASA/JPL Solar System Dynamics, planetary satellite physical
parameters (GM, mean radius) and mean orbital elements (semi-major axis).
"""

import math

import numpy as np

from planets import PLANET_MU, PLANET_STYLE

# name: (planet, GM [km^3/s^2], mean radius [km], orbit radius [km], min flyby altitude [km], colour)
MOONS = {
    "Io":        ("Jupiter", 5959.916, 1821.6, 421_800.0, 100.0, "#e8c35a"),
    "Europa":    ("Jupiter", 3202.739, 1560.8, 671_100.0, 100.0, "#d9cbb0"),
    "Ganymede":  ("Jupiter", 9887.834, 2631.2, 1_070_400.0, 100.0, "#a39585"),
    "Callisto":  ("Jupiter", 7179.289, 2410.3, 1_882_700.0, 100.0, "#6f6558"),
    "Enceladus": ("Saturn", 7.211, 252.1, 238_040.0, 25.0, "#f2f4f5"),
    "Dione":     ("Saturn", 73.116, 561.4, 377_400.0, 50.0, "#c7c4bd"),
    "Rhea":      ("Saturn", 153.94, 763.8, 527_070.0, 50.0, "#bdb8ae"),
    "Titan":     ("Saturn", 8978.14, 2574.7, 1_221_870.0, 950.0, "#d9a441"),   # atmosphere: Cassini stayed above ~880 km
    "Titania":   ("Uranus", 228.2, 788.9, 435_910.0, 50.0, "#b9aea2"),
    "Oberon":    ("Uranus", 192.4, 761.4, 583_520.0, 50.0, "#a0948a"),
    "Moon":      ("Earth", 4902.80, 1737.4, 384_400.0, 50.0, "#bdbdbd"),
}

DAY = 86400.0


def moons_of(planet):
    return [m for m, d in MOONS.items() if d[0] == planet]


class Moon:
    def __init__(self, name):
        planet, gm, R, a, hmin, color = MOONS[name]
        self.name, self.planet, self.gm, self.R, self.r, self.hmin, self.color = name, planet, gm, R, a, hmin, color
        self.mu_p = PLANET_MU[planet]
        self.V = math.sqrt(self.mu_p / a)
        self.T = 2 * math.pi * math.sqrt(a ** 3 / self.mu_p)          # [s]

    def max_turn(self, vinf):
        """Largest bend of v_inf in one flyby (closest pass at the minimum altitude)."""
        rp = self.R + self.hmin
        return 2 * math.asin(1.0 / (1.0 + rp * vinf * vinf / self.gm))

    def flyby_altitude(self, vinf, turn):
        """Closest-approach altitude that bends v_inf by `turn` radians."""
        if turn < 1e-9:
            return math.inf
        rp = self.gm / vinf ** 2 * (1.0 / math.sin(turn / 2) - 1.0)
        return rp - self.R


# ----------------------------------------------------------------------
# orbit <-> (v_inf, pump angle) at a moon
# ----------------------------------------------------------------------

def orbit_from_pump(moon, vinf, alpha):
    """Spacecraft orbit (a, e) after leaving `moon` with v_inf at pump angle alpha."""
    mu, r, V = moon.mu_p, moon.r, moon.V
    v2 = V * V + vinf * vinf + 2 * V * vinf * math.cos(alpha)
    energy = v2 / 2 - mu / r
    if energy >= 0:
        return None                                    # escapes the planet
    a = -mu / (2 * energy)
    h = r * (V + vinf * math.cos(alpha))
    e2 = 1 - h * h / (mu * a)
    return a, math.sqrt(max(e2, 0.0))


def pump_from_orbit(moon, a, e):
    """(v_inf, alpha) where an orbit (a, e) crosses the moon's orbit, or None
    if it does not reach that radius."""
    mu, r, V = moon.mu_p, moon.r, moon.V
    rp, ra = a * (1 - e), a * (1 + e)
    if not (rp <= r * (1 + 1e-9) and ra >= r * (1 - 1e-9)):
        return None
    v2 = mu * (2 / r - 1 / a)
    vt = math.sqrt(mu * a * (1 - e * e)) / r
    vr = math.sqrt(max(v2 - vt * vt, 0.0))
    vinf = math.hypot(vt - V, vr)
    alpha = math.atan2(vr, vt - V)
    return vinf, alpha


def alpha_for_period(moon, vinf, period):
    """Pump angle that gives an orbit of this period, or None if impossible."""
    mu, r, V = moon.mu_p, moon.r, moon.V
    a = (mu * (period / (2 * math.pi)) ** 2) ** (1 / 3)
    v2 = mu * (2 / r - 1 / a)
    c = (v2 - V * V - vinf * vinf) / (2 * V * vinf)
    if abs(c) > 1:
        return None
    return math.acos(c)


def period_of(a, mu):
    return 2 * math.pi * math.sqrt(a ** 3 / mu)


def true_anomaly_at(a, e, r, outbound=True):
    if e < 1e-9:
        return 0.0
    p = a * (1 - e * e)
    c = max(-1.0, min(1.0, (p / r - 1) / e))
    nu = math.acos(c)
    return nu if outbound else 2 * math.pi - nu


def time_between(a, e, mu, nu1, nu2):
    """Time [s] to fly forward from true anomaly nu1 to nu2 on an ellipse."""
    def M(nu):
        E = 2 * math.atan2(math.sqrt(1 - e) * math.sin(nu / 2), math.sqrt(1 + e) * math.cos(nu / 2))
        return E - e * math.sin(E)
    n = math.sqrt(mu / a ** 3)
    dM = (M(nu2) - M(nu1)) % (2 * math.pi)
    return dM / n


# ----------------------------------------------------------------------
# capture
# ----------------------------------------------------------------------

def capture(planet, vinf, rp, period):
    """Braking burn at periapsis rp [km] that turns an arrival at v_inf into
    an orbit of the given period [s]. Returns (dv, a, e)."""
    mu = PLANET_MU[planet]
    a = (mu * (period / (2 * math.pi)) ** 2) ** (1 / 3)
    if a * 2 <= rp:
        raise ValueError("The capture orbit is too small for this periapsis.")
    e = 1 - rp / a
    v_hyp = math.sqrt(vinf * vinf + 2 * mu / rp)
    v_ell = math.sqrt(mu * (2 / rp - 1 / a))
    return v_hyp - v_ell, a, e


def insertion_dv(moon, vinf, altitude):
    """Braking burn to go from v_inf into a circular orbit at `altitude` above the moon."""
    r = moon.R + altitude
    return math.sqrt(vinf * vinf + 2 * moon.gm / r) - math.sqrt(moon.gm / r)


# ----------------------------------------------------------------------
# the tour search
# ----------------------------------------------------------------------

_CACHE = {}


def get_moon(name):
    if name not in MOONS:
        raise ValueError(f"Unknown moon '{name}'.")
    if name not in _CACHE:
        _CACHE[name] = Moon(name)
    return _CACHE[name]


def _resonances(moon, max_days):
    """Candidate resonant periods N/M * T (N moon laps = M spacecraft laps)."""
    out = []
    for M in range(1, 5):
        for N in range(1, 80):
            if N / M * moon.T / DAY <= max_days and math.gcd(N, M) == 1:
                out.append((N, M))
    return out


def plan_tour(planet, moons, target, vinf_arrival, rp_capture, period_capture_days, rp_raise=None,
              goal="orbit", goal_period_days=None, insertion_alt=500.0, max_years=4.0,
              max_flybys=30, beam=250):
    """
    Search a moon tour.

    planet               the planet (Jupiter, Saturn, Uranus, Earth)
    moons                moons that may be used for flybys
    target               goal="orbit": the moon to orbit at the end
    vinf_arrival         speed relative to the planet on arrival [km/s]
    rp_capture           closest approach of the capture burn [km]
    period_capture_days  period of the first, loose orbit
    rp_raise             optional burn at the first far point that raises the
                         closest approach to this radius [km] (Galileo,
                         Cassini and JUICE all did this)
    goal                 "orbit" (end in orbit around `target`) or "period"
                         (shrink the orbit period below goal_period_days)
    """
    names = list(dict.fromkeys(list(moons) + ([target] if goal == "orbit" and target else [])))
    ms = [get_moon(m) for m in names]
    for m in ms:
        if m.planet != planet:
            raise ValueError(f"{m.name} is not a moon of {planet}.")
    if not ms:
        raise ValueError("Choose at least one moon for the flybys.")
    T = get_moon(target) if goal == "orbit" else None
    if goal == "period" and not goal_period_days:
        raise ValueError("Give the orbit period to reach.")
    mu = PLANET_MU[planet]
    R_pl = PLANET_STYLE[planet]["radius"]
    if rp_capture < R_pl * 1.01:
        raise ValueError("The capture closest approach is inside the planet.")
    dv_cap, a0, e0 = capture(planet, vinf_arrival, rp_capture, period_capture_days * DAY)
    ra0 = a0 * (1 + e0)
    pre = [{"kind": "capture", "t": 0.0, "dv": dv_cap, "rp": rp_capture, "ra": ra0, "vinf": vinf_arrival,
            "period_days": period_of(a0, mu) / DAY}]
    if rp_raise:
        if not (rp_capture < rp_raise < ra0):
            raise ValueError("The raised closest approach must lie between the capture closest approach and the "
                             "far point of the capture orbit.")
        a1 = (rp_raise + ra0) / 2
        e1 = (ra0 - rp_raise) / (ra0 + rp_raise)
        dv_raise = math.sqrt(mu * (2 / ra0 - 1 / a1)) - math.sqrt(mu * (2 / ra0 - 1 / a0))
        t_apo = period_of(a0, mu) / 2
        pre.append({"kind": "raise", "t": t_apo, "dv": dv_raise, "rp": rp_raise, "ra": ra0,
                    "period_days": period_of(a1, mu) / DAY})
        base = (a1, e1, math.pi, t_apo)
    else:
        dv_raise = 0.0
        base = (a0, e0, 0.0, 0.0)
    a_b, e_b, nu_b, t_b = base

    # First encounter: each moon whose orbit is crossed, at its first crossing.
    frontier = []
    for m in ms:
        p = pump_from_orbit(m, a_b, e_b)
        if p is None:
            continue
        dt, ob = min((time_between(a_b, e_b, mu, nu_b, true_anomaly_at(a_b, e_b, m.r, o)), o) for o in (True, False))
        frontier.append({"moon": m, "a": a_b, "e": e_b, "vinf": p[0], "alpha": p[1], "outbound": ob,
                         "t": t_b + dt, "n": 0, "steps": [], "first": (m.name, ob, t_b + dt)})
    if not frontier:
        raise ValueError("After capture the orbit does not reach any of the chosen moons. Use a longer capture "
                         "period or a closest approach inside the moons' orbits.")
    max_t = max_years * 365.25 * DAY
    lam = 0.0015 / DAY          # tie-breaker: prefer shorter tours (km/s per second)

    def goal_cost(s):
        if goal == "orbit":
            return insertion_dv(T, s["vinf"], insertion_alt) if s["moon"] is T else None
        return 0.0 if period_of(s["a"], mu) / DAY <= goal_period_days * 1.0001 else None

    def heuristic(s):
        if goal == "orbit":
            if s["moon"] is T:
                v = s["vinf"]
            else:
                p = pump_from_orbit(T, s["a"], s["e"])
                v = p[0] if p else 15.0
            h = insertion_dv(T, v, insertion_alt)
        else:
            h = max(period_of(s["a"], mu) / DAY / goal_period_days - 1.0, 0.0)
        return h + lam * s["t"] + 0.004 * s["n"]

    finished = []
    for s in frontier:
        c = goal_cost(s)
        if c is not None:
            finished.append((c + lam * s["t"], c, s))
    res_cache = {m.name: _resonances(m, 450) for m in ms}

    for _ in range(max_flybys):
        children = []
        for s in frontier:
            m = s["moon"]
            dmax = m.max_turn(s["vinf"])
            lo, hi = max(0.0, s["alpha"] - dmax), min(math.pi, s["alpha"] + dmax)

            def child(al, orb, nxt, vinf2, alpha2, outbound2, dt, kind, res=None, s=s, m=m):
                step = {"moon": m.name, "t": s["t"], "vinf": s["vinf"], "alpha0": s["alpha"], "alpha1": al,
                        "a": orb[0], "e": orb[1], "kind": kind, "res": res, "to": nxt.name, "arc_time": dt,
                        "out_dep": s["outbound"], "out_arr": outbound2,
                        "altitude": m.flyby_altitude(s["vinf"], abs(al - s["alpha"]))}
                return {"moon": nxt, "a": orb[0], "e": orb[1], "vinf": vinf2, "alpha": alpha2,
                        "outbound": outbound2, "t": s["t"] + dt, "n": s["n"] + 1, "steps": s["steps"] + [step],
                        "first": s["first"]}

            # resonant: meet the same moon again at the same place
            for N, M in res_cache[m.name]:
                al = alpha_for_period(m, s["vinf"], N / M * m.T)
                if al is None or not (lo <= al <= hi) or abs(al - s["alpha"]) < 1e-5:
                    continue
                orb = orbit_from_pump(m, s["vinf"], al)
                if orb is None or s["t"] + N * m.T > max_t:
                    continue
                children.append(child(al, orb, m, s["vinf"], al, s["outbound"], N * m.T, "resonant", [N, M]))
            # transfer: fly on to the next crossing of another moon's orbit
            for al in np.linspace(lo, hi, 9):
                al = float(al)
                # A real flyby must bend the path (a 0-degree bend would mean
                # the spacecraft never met the moon).
                if abs(al - s["alpha"]) < math.radians(0.5):
                    continue
                orb = orbit_from_pump(m, s["vinf"], al)
                if orb is None:
                    continue
                nu_d = true_anomaly_at(orb[0], orb[1], m.r, s["outbound"])
                for m2 in ms:
                    if m2 is m:
                        continue
                    p2 = pump_from_orbit(m2, *orb)
                    if p2 is None:
                        continue
                    dt, ob = min((time_between(orb[0], orb[1], mu, nu_d, true_anomaly_at(orb[0], orb[1], m2.r, o)), o)
                                 for o in (True, False))
                    if dt < 3600 or s["t"] + dt > max_t:
                        continue
                    children.append(child(al, orb, m2, p2[0], p2[1], ob, dt, "transfer"))
        if not children:
            break
        for c in children:
            gc = goal_cost(c)
            if gc is not None:
                finished.append((gc + lam * c["t"] + 0.004 * c["n"], gc, c))
        children.sort(key=heuristic)
        seen, frontier = set(), []
        for c in children:
            key = (c["moon"].name, round(period_of(c["a"], mu) / DAY, 0), round(c["vinf"], 1))
            if key in seen:
                continue
            seen.add(key)
            frontier.append(c)
            if len(frontier) >= beam:
                break
    if not finished:
        raise ValueError("No tour reaches the goal within these limits. Try more years, other moons, "
                         "or a different capture orbit.")
    finished.sort(key=lambda x: x[0])
    _, final_cost, best = finished[0]

    direct = None
    if goal == "orbit":
        p = pump_from_orbit(T, a_b, e_b)
        if p is not None:
            direct = {"vinf": p[0], "dv": insertion_dv(T, p[0], insertion_alt)}
    return _describe(planet, ms, T, pre, base, best, final_cost, goal, goal_period_days, insertion_alt,
                     direct, dv_cap, dv_raise, vinf_arrival, a0, e0)


# ----------------------------------------------------------------------
# geometry for drawing, and the Tisserand graph
# ----------------------------------------------------------------------

def _mean_anomaly(e, nu):
    E = 2 * math.atan2(math.sqrt(1 - e) * math.sin(nu / 2), math.sqrt(1 + e) * math.cos(nu / 2))
    return E - e * math.sin(E)


def _pos(a, e, w, M):
    E = M
    for _ in range(40):
        E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    nu = 2 * math.atan2(math.sqrt(1 + e) * math.sin(E / 2), math.sqrt(1 - e) * math.cos(E / 2))
    r = a * (1 - e * math.cos(E))
    return r * math.cos(nu + w), r * math.sin(nu + w)


def _describe(planet, ms, T, pre, base, best, final_cost, goal, goal_P, ins_alt, direct,
              dv_cap, dv_raise, vinf_arr, a0, e0):
    mu = PLANET_MU[planet]
    R = PLANET_STYLE[planet]["radius"]
    arcs = []

    def add_arc(a, e, w, nu0, t0, t1, kind):
        n = math.sqrt(mu / a ** 3)
        arc = {"a": a, "e": e, "w": w, "M0": _mean_anomaly(e, nu0), "t0": t0, "t1": t1, "kind": kind, "n": n}
        ts = np.linspace(0, min(t1 - t0, 2 * math.pi / n), 240)
        arc["samples"] = [list(_pos(a, e, w, arc["M0"] + n * t)) for t in ts]
        arcs.append(arc)

    # The capture orbit's closest approach points along +x.
    w = 0.0
    a_b, e_b, nu_b, t_b = base
    first_moon, first_out, t_first = best["first"]
    if len(pre) == 2:                                   # capture, then the raise burn at the far point
        add_arc(a0, e0, w, 0.0, 0.0, t_b, "capture")
    m0 = get_moon(first_moon)
    add_arc(a_b, e_b, w, nu_b, t_b, t_first, "capture" if len(pre) == 1 else "raised")
    theta = w + true_anomaly_at(a_b, e_b, m0.r, first_out)     # direction of the first encounter
    knots = {m.name: [] for m in ms}
    knots[first_moon].append((t_first, theta))

    events = list(pre)
    for st in best["steps"]:
        m = get_moon(st["moon"])
        a, e = st["a"], st["e"]
        nu_d = true_anomaly_at(a, e, m.r, st["out_dep"])
        wk = theta - nu_d
        t0, t1 = st["t"], st["t"] + st["arc_time"]
        add_arc(a, e, wk, nu_d, t0, t1, st["kind"])
        if st["kind"] == "resonant":
            theta_next = theta
        else:
            theta_next = wk + true_anomaly_at(a, e, get_moon(st["to"]).r, st["out_arr"])
        turn = abs(st["alpha1"] - st["alpha0"])
        events.append({"kind": "flyby", "moon": m.name, "t": t0, "vinf": st["vinf"],
                       "turn_deg": math.degrees(turn), "max_turn_deg": math.degrees(m.max_turn(st["vinf"])),
                       "altitude": st["altitude"], "period_days": period_of(a, mu) / DAY,
                       "rp": a * (1 - e), "ra": a * (1 + e), "res": st["res"], "to": st["to"],
                       "alpha0_deg": math.degrees(st["alpha0"]), "alpha1_deg": math.degrees(st["alpha1"]),
                       "theta": theta, "move": st["kind"]})
        theta = theta_next
        knots[st["to"]].append((t1, theta))
    t_end = best["t"]
    if goal == "orbit":
        events.append({"kind": "insertion", "moon": T.name, "t": t_end, "vinf": best["vinf"], "dv": final_cost,
                       "altitude": ins_alt, "theta": theta})
    else:
        events.append({"kind": "end", "t": t_end, "period_days": period_of(best["a"], mu) / DAY, "theta": theta})

    # Moon motion: each moon must be exactly where the spacecraft meets it.
    # Between two encounters with the same moon it moves at a nearly
    # constant rate with the right number of laps (exact for resonances).
    moon_out = {}
    for m in ms:
        n_nom = 2 * math.pi / m.T
        ks = knots[m.name] or [(0.0, 0.0)]
        segs = []
        for (ta, tha), (tb, thb) in zip(ks, ks[1:]):
            laps = round(((tb - ta) * n_nom - (thb - tha)) / (2 * math.pi))
            segs.append([ta, tb, tha, (thb - tha + 2 * math.pi * laps) / (tb - ta) if tb > ta else n_nom])
        moon_out[m.name] = {"r": m.r, "R": m.R, "T_days": m.T / DAY, "V": m.V, "color": m.color,
                            "knots": ks, "segs": segs, "rate": n_nom}

    # Tisserand graph: closest approach (planet radii) vs period (days).
    tis = []
    for m in ms:
        for v in (0.5, 1, 1.5, 2, 3, 4, 5, 6, 8, 10):
            pts = []
            for al in np.linspace(0, math.pi, 120):
                o = orbit_from_pump(m, v, al)
                if o is None:
                    continue
                P = period_of(o[0], mu) / DAY
                if P <= 450:
                    pts.append([o[0] * (1 - o[1]) / R, P])
            if len(pts) > 1:
                tis.append({"moon": m.name, "vinf": v, "pts": pts})
    path = [{"rp": ev["rp"] / R, "P": ev["period_days"], "label": ev["kind"]} for ev in pre]
    path += [{"rp": ev["rp"] / R, "P": ev["period_days"], "label": ev["moon"]} for ev in events if ev["kind"] == "flyby"]

    total = dv_cap + dv_raise + (final_cost if goal == "orbit" else 0.0)
    return {
        "planet": planet, "radius": R, "mu": mu, "target": T.name if T else None, "goal": goal,
        "goal_period_days": goal_P, "insertion_alt": ins_alt, "moons": moon_out,
        "arcs": arcs, "events": events, "duration_days": t_end / DAY,
        "capture_dv": dv_cap, "raise_dv": dv_raise, "insertion_dv": final_cost if goal == "orbit" else None,
        "total_dv": total, "direct": direct, "n_flybys": best["n"], "vinf_arrival": vinf_arr,
        "tisserand": tis, "path": path, "final_period_days": period_of(arcs[-1]["a"], mu) / DAY,
    }


# Starting points inspired by real missions. Arrival speeds and capture
# orbits are round numbers of the right size, not exact flight values.
PRESETS = [
    {"key": "juice", "label": "JUICE: into orbit around Ganymede", "planet": "Jupiter",
     "moons": ["Callisto", "Ganymede"], "target": "Ganymede", "vinf": 5.5, "rp_radii": 8.0, "period_days": 250,
     "raise_radii": 13.0, "goal": "orbit", "years": 4.0,
     "history": "ESA's JUICE arrives at Jupiter in July 2031. After a burn that raises its closest approach, it "
                "tours for about 3.5 years with flybys of Ganymede and Callisto (and two of Europa), then enters "
                "orbit around Ganymede in December 2034: the first spacecraft to orbit a moon other than ours."},
    {"key": "galileo", "label": "Galileo-style tour with Ganymede", "planet": "Jupiter", "moons": ["Ganymede"],
     "target": None, "vinf": 5.5, "rp_radii": 4.0, "period_days": 200, "raise_radii": 10.0, "goal": "period",
     "goal_period": 40, "years": 2.0,
     "history": "Galileo entered orbit on 7 December 1995, passing 4 Jupiter radii from the centre, into a first "
                "orbit of about 7 months. A burn at the far point in March 1996 raised its closest approach, and "
                "Ganymede flybys from June 1996 shrank the orbit to 1–2 months."},
    {"key": "europa", "label": "A Europa orbiter", "planet": "Jupiter", "moons": ["Ganymede", "Europa", "Callisto"],
     "target": "Europa", "vinf": 5.5, "rp_radii": 6.0, "period_days": 200, "raise_radii": 8.5, "goal": "orbit",
     "years": 4.0,
     "history": "Europa Clipper (arriving 2030) will fly past Europa about 50 times instead of orbiting it: "
                "entering orbit there is expensive and Jupiter's radiation is intense. An orbiter would first tour "
                "with Ganymede and Europa to slow down relative to Europa, as this example does."},
    {"key": "cassini", "label": "Cassini-style tour with Titan", "planet": "Saturn", "moons": ["Titan"],
     "target": None, "vinf": 5.5, "rp_radii": 1.3, "period_days": 150, "raise_radii": 10.0, "goal": "period",
     "goal_period": 16, "years": 3.0,
     "history": "Cassini entered orbit around Saturn on 1 July 2004, 1.3 Saturn radii from the centre, and raised "
                "its closest approach with a burn in August 2004. Titan, the only moon massive enough to steer it, "
                "then shaped every orbit of its 13-year mission, with 127 flybys."},
    {"key": "titan", "label": "A Titan orbiter", "planet": "Saturn", "moons": ["Titan", "Rhea"], "target": "Titan",
     "vinf": 5.5, "rp_radii": 3.0, "period_days": 120, "raise_radii": 15.0, "goal": "orbit", "years": 3.0,
     "history": "No spacecraft has orbited Titan yet (NASA's Dragonfly will land there in the 2030s). An orbiter "
                "would use Titan's own gravity, flyby after flyby, to slow down before the final braking burn."},
]


def plan_preset(key, **override):
    p = dict(next(x for x in PRESETS if x["key"] == key), **override)
    R = PLANET_STYLE[p["planet"]]["radius"]
    out = plan_tour(p["planet"], p["moons"], p["target"], p["vinf"], p["rp_radii"] * R, p["period_days"],
                    rp_raise=p["raise_radii"] * R if p.get("raise_radii") else None, goal=p["goal"],
                    goal_period_days=p.get("goal_period"), max_years=p["years"])
    out["preset"] = p
    return out
