"""
Gravity-assist (flyby) route design, patched-conic method.

A route such as Earth -> Jupiter -> Saturn is split into legs. Each leg
is one heliocentric Lambert problem (the same solver as everywhere else,
with mu = mu_Sun) between two planet positions on two dates. At every
flyby planet the spacecraft arrives with an excess velocity v_inf_in and
must leave with v_inf_out (both relative to the planet):

  * The planet's gravity can only ROTATE the relative velocity, not change
    its size. Seen from the Sun, rotating it adds (or removes) the
    planet's own orbital velocity -- that is the "free" speed change.
  * How far it can be rotated depends on how close the spacecraft passes:
        turn angle = asin(1/e_in) + asin(1/e_out),  e = 1 + r_p v_inf^2 / mu
    Passing closer (smaller r_p) turns the path more.
  * If |v_inf_in| != |v_inf_out|, a small engine burn at closest approach
    makes up the difference ("powered flyby"); its delta-v is counted.
  * If the required turn is more than the planet can give without
    hitting it (or its atmosphere / radiation belts), the route is not
    physically possible and is rejected.

The dates are optimised: a coarse grid search over launch date and leg
flight times, then a Nelder-Mead refinement of the best candidates.
The cost is the total delta-v: launch from a 200 km Earth parking orbit,
plus any powered-flyby burns, plus (optionally) capture at the target.
"""

import math
import time

import numpy as np

from constants import MU_SUN, AU
from lambert_solver import lambert_universal
from frames import propagate
from planets import PLANET_MU, PLANET_STYLE, PLANET_ORDER, orbital_period_days, planet_elements
from interplanetary import best_planet_state, _planet_states, _hyperbolic_dv, ephemeris_source

# Closest allowed flyby altitude (km). Gas giants: stay out of the densest
# radiation / ring regions, like real missions do.
MIN_FLYBY_ALT = {
    "Mercury": 200.0, "Venus": 300.0, "Earth": 300.0, "Mars": 200.0,
    "Jupiter": 0.5 * 69911.0, "Saturn": 0.3 * 58232.0, "Uranus": 0.3 * 25362.0, "Neptune": 0.3 * 24622.0,
}
LEO_ALT = 200.0
INF = float("inf")


# ----------------------------------------------------------------------
# single flyby
# ----------------------------------------------------------------------

def flyby_analysis(planet, vinf_in, vinf_out):
    """
    What the planet must do to turn v_inf_in into v_inf_out.
    Returns turn angle, closest approach, and the extra burn needed.
    """
    mu = PLANET_MU[planet]
    R = PLANET_STYLE[planet]["radius"]
    a, b = float(np.linalg.norm(vinf_in)), float(np.linalg.norm(vinf_out))
    cosd = np.clip(np.dot(vinf_in, vinf_out) / (a * b), -1.0, 1.0)
    turn = math.acos(cosd)
    rp_min = R + MIN_FLYBY_ALT[planet]

    def turn_at(rp):
        return math.asin(1.0 / (1.0 + rp * a * a / mu)) + math.asin(1.0 / (1.0 + rp * b * b / mu))

    max_turn = turn_at(rp_min)
    feasible = turn <= max_turn
    if feasible:
        # turn_at decreases with rp: bisect for the pass distance that gives exactly `turn`.
        lo, hi = rp_min, rp_min
        while turn_at(hi) > turn and hi < 1e10:
            hi *= 2.0
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if turn_at(mid) > turn:
                lo = mid
            else:
                hi = mid
        rp = 0.5 * (lo + hi)
    else:
        rp = rp_min
    dv = abs(math.sqrt(b * b + 2 * mu / rp) - math.sqrt(a * a + 2 * mu / rp))
    return {"planet": planet, "vinf_in": a, "vinf_out": b, "turn_deg": math.degrees(turn),
            "max_turn_deg": math.degrees(max_turn), "rp": rp, "altitude": rp - R,
            "altitude_radii": rp / R, "dv": dv, "feasible": feasible}


def capture_dv(vinf, planet):
    """
    Burn to be captured at the target. Rocky planets: into a 400 km
    circular orbit. Gas giants: into a long ellipse (periapsis 1.2 R,
    apoapsis 100 R) -- how Galileo, Cassini and Juno were captured.
    """
    mu, R = PLANET_MU[planet], PLANET_STYLE[planet]["radius"]
    if planet in ("Jupiter", "Saturn", "Uranus", "Neptune"):
        rp, ra = 1.2 * R, 100 * R
        v_orbit = math.sqrt(2 * mu / rp - 2 * mu / (rp + ra))
        return math.sqrt(vinf ** 2 + 2 * mu / rp) - v_orbit
    return _hyperbolic_dv(vinf, planet, 400.0)


# ----------------------------------------------------------------------
# a whole route
# ----------------------------------------------------------------------

class _StateCache:
    """Planet states are reused heavily by the grid search; cache them."""

    def __init__(self):
        self.store = {}

    def prime(self, planet, jds):
        jds = [j for j in np.round(np.asarray(jds, float), 6) if (planet, j) not in self.store]
        if jds:
            for j, st in zip(jds, _planet_states(planet, np.array(jds))):
                self.store[(planet, j)] = st

    def get(self, planet, jd):
        key = (planet, round(float(jd), 6))
        if key not in self.store:
            self.store[key] = best_planet_state(planet, key[1])
        return self.store[key]


def _leg(cache, p1, p2, jd1, jd2):
    if jd2 - jd1 < 10:
        return None
    r1, vp1 = cache.get(p1, jd1)
    r2, vp2 = cache.get(p2, jd2)
    try:
        v1, v2, _ = lambert_universal(r1, r2, (jd2 - jd1) * 86400.0, mu=MU_SUN)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return {"r1": r1, "r2": r2, "v1": v1, "v2": v2, "vp1": vp1, "vp2": vp2}


def evaluate(seq, jds, capture, cache, detail=False, max_days=None):
    """Total delta-v [km/s] of a route flown on the given dates (inf if impossible)."""
    if max_days is not None and jds[-1] - jds[0] > max_days * 1.02 and not detail:
        return INF
    legs = []
    for k in range(len(seq) - 1):
        L = _leg(cache, seq[k], seq[k + 1], jds[k], jds[k + 1])
        if L is None:
            return (INF, None) if detail else INF
        legs.append(L)

    vinf_launch = float(np.linalg.norm(legs[0]["v1"] - legs[0]["vp1"]))
    total = _hyperbolic_dv(vinf_launch, seq[0], LEO_ALT)
    flybys = []
    penalty = 0.0
    for k in range(1, len(seq) - 1):
        vin = legs[k - 1]["v2"] - legs[k - 1]["vp2"]
        vout = legs[k]["v1"] - legs[k]["vp1"]
        fb = flyby_analysis(seq[k], vin, vout)
        total += fb["dv"]
        if not fb["feasible"]:
            # Impossible turn: steer the optimiser away, in proportion to how far off it is.
            penalty += 2.0 + 0.1 * (fb["turn_deg"] - fb["max_turn_deg"])
        flybys.append(fb)
    vinf_arrive = float(np.linalg.norm(legs[-1]["v2"] - legs[-1]["vp2"]))
    if capture:
        total += capture_dv(vinf_arrive, seq[-1])
    cost = total + penalty
    if not detail:
        return cost
    return cost, {"legs": legs, "flybys": flybys, "vinf_launch": vinf_launch,
                  "vinf_arrive": vinf_arrive, "total_dv": total, "feasible": penalty == 0.0}


def _hohmann_days(p1, p2, jd):
    a1 = planet_elements(p1, jd)["a_au"] * AU
    a2 = planet_elements(p2, jd)["a_au"] * AU
    return math.pi * math.sqrt(((a1 + a2) / 2) ** 3 / MU_SUN) / 86400.0


def _tof_bounds(seq, jd):
    """Plausible flight-time range for each leg, scaled from its Hohmann time.
    Legs after a flyby can be much faster than Hohmann (the spacecraft has
    been sped up), so their lower bound is lower."""
    out = []
    for k in range(len(seq) - 1):
        th = _hohmann_days(seq[k], seq[k + 1], jd)
        lo = (0.3 if k == 0 else 0.12) * th
        out.append((max(lo, 30.0), 1.6 * th))
    return out


def optimise(seq, window, capture=True, grid=None, max_days=None):
    """
    Cheapest dates for a route. window = (earliest, latest) launch JD;
    max_days optionally limits the total trip time (real missions trade
    fuel against time: the cheapest route is often very slow).
    Returns the detailed best solution, or None if nothing feasible.
    """
    from scipy.optimize import minimize

    for p in seq:
        if p not in PLANET_ORDER:
            raise ValueError(f"Unknown planet '{p}'.")
    for a, b in zip(seq, seq[1:]):
        if a == b:
            raise ValueError("Two consecutive stops cannot be the same planet "
                             "(a return flyby needs a multi-revolution solver).")
    if window[1] <= window[0]:
        raise ValueError("The launch window must end after it starts.")

    n_legs = len(seq) - 1
    bounds = _tof_bounds(seq, window[0])
    if max_days is not None:
        # No single leg can be longer than the whole trip allowed.
        bounds = [(lo, min(hi, max_days)) for lo, hi in bounds]
        if any(lo >= hi for lo, hi in bounds):
            raise ValueError(f"A trip of at most {max_days / 365.25:.1f} years is too short for this route.")
    if grid is None:
        grid = {1: (70, 40), 2: (48, 16), 3: (30, 10)}[n_legs]
    n_launch, n_tof = grid
    t0s = np.linspace(window[0], window[1], n_launch)
    tofs = [np.linspace(lo, hi, n_tof) for lo, hi in bounds]
    cache = _StateCache()
    start = time.perf_counter()

    # Coarse grid. Planet states for every date that can occur are fetched
    # in vectorised batches first.
    dates = [t0s]
    for k in range(n_legs):
        dates.append(np.unique(np.round((dates[-1][:, None] + tofs[k][None, :]).ravel(), 6)))
    for k, p in enumerate(seq):
        cache.prime(p, dates[k])

    candidates = []

    def search(k, jds, partial):
        # Depth-first over legs; prune early when the launch alone is too costly.
        if k == n_legs:
            c = evaluate(seq, jds, capture, cache, max_days=max_days)
            if c < INF:
                candidates.append((c, list(jds)))
            return
        for T in tofs[k]:
            search(k + 1, jds + [round(jds[-1] + T, 6)], partial)

    for t0 in t0s:
        search(0, [round(float(t0), 6)], 0.0)
    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])

    # Local refinement of the best few, in (launch date, leg durations).
    def cost_x(x):
        t0 = min(max(x[0], window[0]), window[1])
        jds = [t0]
        for k in range(n_legs):
            lo, hi = bounds[k]
            jds.append(jds[-1] + min(max(x[k + 1], lo * 0.8), hi * 1.2))
        return evaluate(seq, jds, capture, cache, max_days=max_days)

    best_x, best_c = None, INF
    seen = []
    for c, jds in candidates[:40]:
        if any(abs(jds[0] - s) < 20 for s in seen):
            continue                                      # keep candidates diverse
        seen.append(jds[0])
        x0 = [jds[0]] + [jds[k + 1] - jds[k] for k in range(n_legs)]
        res = minimize(cost_x, x0, method="Nelder-Mead",
                       options={"xatol": 0.05, "fatol": 1e-5, "maxiter": 600})
        if res.fun < best_c:
            best_c, best_x = res.fun, res.x
        if len(seen) >= 4:
            break

    x = best_x
    jds = [min(max(x[0], window[0]), window[1])]
    for k in range(n_legs):
        lo, hi = bounds[k]
        jds.append(jds[-1] + min(max(x[k + 1], lo * 0.8), hi * 1.2))
    cost, det = evaluate(seq, jds, capture, cache, detail=True)
    if det is None:
        return None
    det["jds"] = jds
    det["seq"] = list(seq)
    det["capture"] = capture
    det["search"] = {"evaluated": len(candidates), "seconds": time.perf_counter() - start}
    return det


# ----------------------------------------------------------------------
# presentation: tracks, speed profile, comparison with going direct
# ----------------------------------------------------------------------

def describe(det, n_per_leg=160):
    """Everything the interface needs to draw and explain a route."""
    seq, jds, legs = det["seq"], det["jds"], det["legs"]
    track, t_days, speed, escape = [], [], [], []
    for k, L in enumerate(legs):
        dt = (jds[k + 1] - jds[k]) * 86400.0
        for s in np.linspace(0.0, dt, n_per_leg):
            r, v = propagate(L["r1"], L["v1"], float(s), mu=MU_SUN)
            rn = float(np.linalg.norm(r))
            track.append((r / AU).tolist())
            t_days.append(jds[k] - jds[0] + s / 86400.0)
            speed.append(float(np.linalg.norm(v)))
            escape.append(math.sqrt(2 * MU_SUN / rn))

    events = [{"kind": "launch", "planet": seq[0], "jd": jds[0], "vinf": det["vinf_launch"],
               "c3": det["vinf_launch"] ** 2,
               "dv": _hyperbolic_dv(det["vinf_launch"], seq[0], LEO_ALT),
               "v_helio_after": float(np.linalg.norm(legs[0]["v1"])),
               "v_planet": float(np.linalg.norm(legs[0]["vp1"]))}]
    for k, fb in enumerate(det["flybys"], start=1):
        v_before = float(np.linalg.norm(legs[k - 1]["v2"]))
        v_after = float(np.linalg.norm(legs[k]["v1"]))
        events.append({"kind": "flyby", "planet": seq[k], "jd": jds[k], **fb,
                       "v_helio_before": v_before, "v_helio_after": v_after,
                       "gain": v_after - v_before,
                       "v_planet": float(np.linalg.norm(legs[k]["vp1"])),
                       "r_au": float(np.linalg.norm(legs[k]["r1"])) / AU})
    arrive = {"kind": "arrival", "planet": seq[-1], "jd": jds[-1], "vinf": det["vinf_arrive"],
              "v_helio_before": float(np.linalg.norm(legs[-1]["v2"])),
              "capture_dv": capture_dv(det["vinf_arrive"], seq[-1]) if det["capture"] else None}
    events.append(arrive)
    return {"seq": seq, "jds": jds, "track_au": track, "t_days": t_days, "speed": speed,
            "escape_speed": escape, "events": events, "total_dv": det["total_dv"],
            "feasible": det["feasible"], "capture": det["capture"],
            "tof_days": jds[-1] - jds[0], "search": det["search"],
            "ephemeris": ephemeris_source()}


def plan_route(seq, window, capture=True, max_days=None):
    """Optimise a route AND the direct flight to the same target (same
    launch window, same trip-time limit), and describe both, so the
    benefit of the flybys is visible."""
    best = optimise(seq, window, capture, max_days=max_days)
    if best is None:
        raise ValueError("No workable trajectory was found for this route in that launch window. "
                         "Try a wider window, a longer trip time or a different year.")
    out = describe(best)
    out["max_days"] = max_days
    direct = None
    if len(seq) > 2:
        try:
            direct = optimise([seq[0], seq[-1]], window, capture, max_days=max_days)
        except ValueError:
            direct = None
    out["direct"] = describe(direct) if direct else None
    return out


# Real missions, to check the method against history.
PRESETS = [
    {"key": "voyager", "label": "Voyager: Earth → Jupiter → Saturn", "seq": ["Earth", "Jupiter", "Saturn"],
     "from": "1977-01-01", "to": "1978-06-30", "capture": False, "max_years": 3.5,
     "history": "Voyager 1 launched 5 Sep 1977, passed Jupiter 5 Mar 1979 and Saturn 12 Nov 1980."},
    {"key": "mariner10", "label": "Mariner 10: Earth → Venus → Mercury", "seq": ["Earth", "Venus", "Mercury"],
     "from": "1973-06-01", "to": "1974-03-01", "capture": False, "max_years": 0.6,
     "history": "Mariner 10 launched 3 Nov 1973, passed Venus 5 Feb 1974 and Mercury 29 Mar 1974 — the first gravity assist ever flown."},
    {"key": "grandtour", "label": "Voyager 2 Grand Tour: Earth → Jupiter → Saturn → Uranus",
     "seq": ["Earth", "Jupiter", "Saturn", "Uranus"],
     "from": "1977-01-01", "to": "1978-06-30", "capture": False, "max_years": 10,
     "history": "Voyager 2 launched 20 Aug 1977: Jupiter Jul 1979, Saturn Aug 1981, Uranus 24 Jan 1986 "
                "(and Neptune 1989). The planets line up like this only once every ~175 years."},
    {"key": "emj", "label": "Does Mars help reach Jupiter? (2030s)", "seq": ["Earth", "Mars", "Jupiter"],
     "from": "2030-01-01", "to": "2036-12-31", "capture": True, "max_years": 6,
     "history": "Mars is small: its gravity can only bend the path a little. Compare with flying direct."},
    {"key": "evj", "label": "Why one Venus flyby isn't enough for Jupiter", "seq": ["Earth", "Venus", "Jupiter"],
     "from": "2027-01-01", "to": "2031-12-31", "capture": True, "max_years": 6,
     "history": "Galileo (1989) needed Venus AND two Earth flybys to reach Jupiter. With Venus alone, "
                "the engine has to make up the difference."},
    {"key": "ejs2", "label": "Earth → Jupiter → Saturn (next chance)", "seq": ["Earth", "Jupiter", "Saturn"],
     "from": "2033-01-01", "to": "2040-12-31", "capture": True, "max_years": 7,
     "history": "Jupiter and Saturn line up roughly every 20 years; this searches the next alignment."},
]


if __name__ == "__main__":
    from time_utils import julian_date
    r = plan_route(["Earth", "Jupiter", "Saturn"],
                   (julian_date(1977, 1, 1, 0, 0, 0), julian_date(1978, 6, 30, 0, 0, 0)), capture=False)
    for e in r["events"]:
        d = (e["jd"] - 2451545.0)
        print(e["kind"], e["planet"], f"JD {e['jd']:.1f}", {k: round(v, 3) for k, v in e.items()
                                                             if isinstance(v, float) and k != "jd"})
    print(f"total dv {r['total_dv']:.3f} km/s; direct {r['direct']['total_dv']:.3f} km/s; "
          f"search {r['search']}")
