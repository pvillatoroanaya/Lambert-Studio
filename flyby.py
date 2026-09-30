"""
Gravity-assist (flyby) route design, patched-conic method.

A route such as Earth -> Venus -> Earth -> Earth -> Jupiter is split into
legs. Each leg is one heliocentric Lambert problem (the same solver as
everywhere else, with mu = mu_Sun) between two planet positions on two
dates. A leg may also loop once around the Sun before arriving (a
multi-revolution Lambert solution); that is what makes it possible to
come back to the SAME planet for a second flyby, as Galileo and Cassini did.

At every flyby planet the spacecraft arrives with an excess velocity
v_inf_in and must leave with v_inf_out (both relative to the planet):

  * The planet's gravity can only ROTATE the relative velocity, not change
    its size. Seen from the Sun, rotating it adds (or removes) the
    planet's own orbital velocity -- that is the "free" speed change.
  * How far it can be rotated depends on how close the spacecraft passes:
        turn angle = asin(1/e_in) + asin(1/e_out),  e = 1 + r_p v_inf^2 / mu
    Passing closer (smaller r_p) turns the path more.
  * If |v_inf_in| != |v_inf_out|, an engine burn at closest approach
    makes up the difference ("powered flyby"); its delta-v is counted.
  * If the required turn is more than the planet can give without
    hitting it (or its atmosphere / radiation belts), the route is not
    physically possible and is rejected.

Search: a stage-by-stage ("beam") search. All launch dates x first-leg
flight times x lap options are solved at once with the batch Lambert
solver; the best few hundred partial routes are kept and extended leg by
leg. The best complete routes are then refined with Nelder-Mead.
The cost is the total delta-v: launch from a 200 km Earth parking orbit,
plus any powered-flyby burns, plus (optionally) capture at the target.
"""

import math
import time

import numpy as np

from constants import MU_SUN, AU
from lambert_solver import lambert_universal, lambert_batch
from frames import propagate
from planets import PLANET_MU, PLANET_STYLE, PLANET_ORDER, orbital_period_days, planet_elements
from interplanetary import best_planet_state, planet_states_array, _hyperbolic_dv, ephemeris_source, arrival_dv

# Closest allowed flyby altitude (km). Gas giants: stay out of the densest
# radiation / ring regions, like real missions do.
MIN_FLYBY_ALT = {
    "Mercury": 200.0, "Venus": 300.0, "Earth": 300.0, "Mars": 200.0,
    "Jupiter": 0.5 * 71492.0, "Saturn": 0.3 * 60268.0, "Uranus": 0.3 * 25559.0, "Neptune": 0.3 * 24764.0,
}
LEO_ALT = 200.0
INF = float("inf")
MAX_FLYBYS = 4
# Cost added for a flyby that needs more bending than the planet can give:
# larger than any real delta-v difference, so a possible route always wins,
# but still graded, so the optimiser can climb out of an impossible region.
IMPOSSIBLE = 50.0
# Samples used to bracket multi-revolution Lambert solutions before the
# bisection refines them to machine precision (48 is plenty for routes).
MULTIREV_GRID = 48
GIANTS = ("Jupiter", "Saturn", "Uranus", "Neptune")


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


def _flyby_vec(planet, vin, vout):
    """Array version of flyby_analysis for the search: (burn dv, penalty)."""
    mu = PLANET_MU[planet]
    rp_min = PLANET_STYLE[planet]["radius"] + MIN_FLYBY_ALT[planet]
    with np.errstate(all="ignore"):
        a = np.linalg.norm(vin, axis=1)
        b = np.linalg.norm(vout, axis=1)
        turn = np.arccos(np.clip(np.einsum("ij,ij->i", vin, vout) / (a * b), -1.0, 1.0))

        def turn_at(rp):
            return np.arcsin(1.0 / (1.0 + rp * a * a / mu)) + np.arcsin(1.0 / (1.0 + rp * b * b / mu))

        max_turn = turn_at(rp_min)
        feas = turn <= max_turn
        lo = np.full_like(a, math.log(rp_min))
        hi = np.full_like(a, math.log(1e10))
        for _ in range(50):
            mid = 0.5 * (lo + hi)
            more = turn_at(np.exp(mid)) > turn
            lo = np.where(more, mid, lo)
            hi = np.where(more, hi, mid)
        rp = np.where(feas, np.exp(0.5 * (lo + hi)), rp_min)
        dv = np.abs(np.sqrt(b * b + 2 * mu / rp) - np.sqrt(a * a + 2 * mu / rp))
        pen = np.where(feas, 0.0, IMPOSSIBLE + 0.5 * np.degrees(turn - max_turn))
    return dv, pen


def capture_dv(vinf, planet):
    """Burn to be captured at the target (shared with direct transfers,
    see interplanetary.arrival_dv)."""
    return arrival_dv(vinf, planet)


def _launch_dv(vinf, planet):
    mu = PLANET_MU[planet]
    rp = PLANET_STYLE[planet]["radius"] + LEO_ALT
    return np.sqrt(vinf ** 2 + 2 * mu / rp) - math.sqrt(mu / rp)


# ----------------------------------------------------------------------
# legs: flight-time ranges and lap options
# ----------------------------------------------------------------------

def _hohmann_days(p1, p2, jd):
    a1 = planet_elements(p1, jd)["a_au"] * AU
    a2 = planet_elements(p2, jd)["a_au"] * AU
    return math.pi * math.sqrt(((a1 + a2) / 2) ** 3 / MU_SUN) / 86400.0


def _leg_plan(seq, jd, max_days):
    """
    For every leg: (min days, max days, lap options). A lap option is
    (revs, branch). Returning to the same planet needs at least one full
    loop around the Sun, so those legs get longer times and multi-rev options.
    Short inner-planet legs may also loop once (Cassini's Venus-Venus leg).
    """
    plan = []
    for k in range(len(seq) - 1):
        p1, p2 = seq[k], seq[k + 1]
        if p1 == p2:
            T = orbital_period_days(p1, jd)
            lo, hi = 0.45 * T, 3.2 * T
            opts = [(0, 0), (1, 0), (1, 1)]
        else:
            th = _hohmann_days(p1, p2, jd)
            lo, hi = (0.3 if k == 0 else 0.12) * th, 1.6 * th
            opts = [(0, 0)]
            inner_T = min(orbital_period_days(p1, jd), orbital_period_days(p2, jd))
            if p1 not in GIANTS and p2 not in GIANTS and inner_T < 800:
                hi = max(hi, 1.6 * th + 1.2 * inner_T)
                opts += [(1, 0), (1, 1)]
        lo = max(lo, 30.0)
        if max_days is not None:
            hi = min(hi, max_days)
        if lo >= hi:
            raise ValueError(f"A trip of at most {max_days / 365.25:.1f} years is too short for this route.")
        plan.append((lo, hi, opts))
    return plan


# ----------------------------------------------------------------------
# evaluating one fully specified route (used for refinement and details)
# ----------------------------------------------------------------------

class _StateCache:
    """
    Planet states for the refinement step, which asks for thousands of
    slightly different dates. Each planet's states are computed once on a
    1-day grid (one vectorised ephemeris call) and interpolated with cubic
    Hermite polynomials using the velocities -- the same scheme the 3D view
    uses; the interpolation error is far below the model's accuracy.
    """

    STEP = 1.0

    def __init__(self):
        self.grids = {}

    def _grid(self, planet, jd):
        g = self.grids.get(planet)
        if g is None or not (g["t0"] + 1 <= jd <= g["t1"] - 1):
            t0 = np.floor(jd) - 400.0
            t = t0 + self.STEP * np.arange(int(12000 / self.STEP) + 1)
            R, V = planet_states_array(planet, t)
            g = {"t0": t[0], "t1": t[-1], "R": R, "V": V * 86400.0}   # velocity per day
            self.grids[planet] = g
        return g

    def get(self, planet, jd):
        jd = float(jd)
        g = self._grid(planet, jd)
        f = (jd - g["t0"]) / self.STEP
        k = int(f)
        s = f - k
        h = self.STEP
        p0, p1, v0, v1 = g["R"][k], g["R"][k + 1], g["V"][k], g["V"][k + 1]
        s2, s3 = s * s, s * s * s
        r = (2 * s3 - 3 * s2 + 1) * p0 + (s3 - 2 * s2 + s) * h * v0 + (-2 * s3 + 3 * s2) * p1 + (s3 - s2) * h * v1
        dr = ((6 * s2 - 6 * s) * p0 + (3 * s2 - 4 * s + 1) * h * v0 + (-6 * s2 + 6 * s) * p1 + (3 * s2 - 2 * s) * h * v1) / h
        return r, dr / 86400.0


def _leg(cache, p1, p2, jd1, jd2, opt):
    if jd2 - jd1 < 10:
        return None
    r1, vp1 = cache.get(p1, jd1)
    r2, vp2 = cache.get(p2, jd2)
    try:
        v1, v2, _ = lambert_universal(r1, r2, (jd2 - jd1) * 86400.0, mu=MU_SUN, revs=opt[0], branch=opt[1],
                                      grid=MULTIREV_GRID)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    if not (np.all(np.isfinite(v1)) and np.all(np.isfinite(v2))):
        return None
    return {"r1": r1, "r2": r2, "v1": v1, "v2": v2, "vp1": vp1, "vp2": vp2, "revs": opt[0], "branch": opt[1]}


def evaluate(seq, jds, capture, cache, opts, detail=False, max_days=None):
    """Total delta-v [km/s] of a route flown on the given dates (inf if impossible)."""
    if max_days is not None and jds[-1] - jds[0] > max_days * 1.02 and not detail:
        return INF
    legs = []
    for k in range(len(seq) - 1):
        L = _leg(cache, seq[k], seq[k + 1], jds[k], jds[k + 1], opts[k])
        if L is None:
            return (INF, None) if detail else INF
        legs.append(L)

    vinf_launch = float(np.linalg.norm(legs[0]["v1"] - legs[0]["vp1"]))
    total = float(_launch_dv(vinf_launch, seq[0]))
    flybys = []
    penalty = 0.0
    for k in range(1, len(seq) - 1):
        vin = legs[k - 1]["v2"] - legs[k - 1]["vp2"]
        vout = legs[k]["v1"] - legs[k]["vp1"]
        fb = flyby_analysis(seq[k], vin, vout)
        total += fb["dv"]
        if not fb["feasible"]:
            penalty += IMPOSSIBLE + 0.5 * (fb["turn_deg"] - fb["max_turn_deg"])
        flybys.append(fb)
    vinf_arrive = float(np.linalg.norm(legs[-1]["v2"] - legs[-1]["vp2"]))
    if capture:
        total += float(capture_dv(vinf_arrive, seq[-1]))
    cost = total + penalty
    if not detail:
        return cost
    return cost, {"legs": legs, "flybys": flybys, "vinf_launch": vinf_launch,
                  "vinf_arrive": vinf_arrive, "total_dv": total, "feasible": penalty == 0.0}


# ----------------------------------------------------------------------
# the search
# ----------------------------------------------------------------------

def _keep_best(cost, key_a, key_b, beam):
    """Indices of the best `beam` states, at most one per (key_a, key_b)
    bucket, so the beam holds many different dates, not near-copies."""
    order = np.argsort(cost)
    order = order[np.isfinite(cost[order])]
    seen, keep = set(), []
    for i in order:
        k = (int(key_a[i]), int(key_b[i]))
        if k in seen:
            continue
        seen.add(k)
        keep.append(i)
        if len(keep) >= beam:
            break
    return np.array(keep, int)


def _beam_search(seq, window, capture, max_days, plan, n_launch, n_tof, beam, n_cands=12):
    n_legs = len(seq) - 1
    evaluated = 0

    # ---- leg 1: launch dates x flight times x lap options ------------------
    t0s = np.linspace(window[0], window[1], n_launch)
    lo, hi, opts = plan[0]
    tofs = np.linspace(lo, hi, n_tof)
    R0, V0 = planet_states_array(seq[0], t0s)
    I, J = np.meshgrid(np.arange(n_launch), np.arange(n_tof), indexing="ij")
    I, J = I.ravel(), J.ravel()
    jd1 = np.round(t0s[I] + tofs[J], 6)
    u1, inv1 = np.unique(jd1, return_inverse=True)
    R1u, V1u = planet_states_array(seq[1], u1)

    st = {k: [] for k in ("t0", "jd", "cost", "v2", "vp", "r", "hist_jd", "hist_opt")}
    for oi, opt in enumerate(opts):
        v1, v2, _, ok = lambert_batch(R0[I], R1u[inv1], tofs[J] * 86400.0, mu=MU_SUN, revs=opt[0], branch=opt[1],
                                      grid=MULTIREV_GRID)
        evaluated += len(I)
        vinf = np.linalg.norm(v1 - V0[I], axis=1)
        cost = np.where(ok, _launch_dv(vinf, seq[0]), np.inf)
        st["t0"].append(t0s[I]); st["jd"].append(jd1); st["cost"].append(cost)
        st["v2"].append(v2); st["vp"].append(V1u[inv1]); st["r"].append(R1u[inv1])
        st["hist_jd"].append(np.stack([t0s[I], jd1], axis=1))
        st["hist_opt"].append(np.full((len(I), 1), oi))
    S = {k: np.concatenate(v) for k, v in st.items()}

    # ---- remaining legs ----------------------------------------------------
    for k in range(1, n_legs):
        if n_legs > 1 and max_days is not None:
            S["cost"] = np.where(S["jd"] - S["t0"] > max_days, np.inf, S["cost"])
        keep = _keep_best(S["cost"], np.round(S["t0"] / 8), np.round(S["jd"] / 8), beam)
        if len(keep) == 0:
            return [], evaluated, None
        S = {key: val[keep] for key, val in S.items()}

        lo, hi, opts = plan[k]
        tofs = np.linspace(lo, hi, n_tof)
        m = len(S["jd"])
        I, J = np.meshgrid(np.arange(m), np.arange(n_tof), indexing="ij")
        I, J = I.ravel(), J.ravel()
        jdn = np.round(S["jd"][I] + tofs[J], 6)
        un, invn = np.unique(jdn, return_inverse=True)
        Rn, Vn = planet_states_array(seq[k + 1], un)
        vin = S["v2"][I] - S["vp"][I]

        st = {key: [] for key in S}
        for oi, opt in enumerate(opts):
            v1, v2, _, ok = lambert_batch(S["r"][I], Rn[invn], tofs[J] * 86400.0, mu=MU_SUN,
                                          revs=opt[0], branch=opt[1], grid=MULTIREV_GRID)
            evaluated += len(I)
            vout = v1 - S["vp"][I]
            dv, pen = _flyby_vec(seq[k], vin, vout)
            cost = np.where(ok, S["cost"][I] + dv + pen, np.inf)
            st["t0"].append(S["t0"][I]); st["jd"].append(jdn); st["cost"].append(cost)
            st["v2"].append(v2); st["vp"].append(Vn[invn]); st["r"].append(Rn[invn])
            st["hist_jd"].append(np.concatenate([S["hist_jd"][I], jdn[:, None]], axis=1))
            st["hist_opt"].append(np.concatenate([S["hist_opt"][I], np.full((len(I), 1), oi)], axis=1))
        S = {key: np.concatenate(v) for key, v in st.items()}

    # ---- arrival -----------------------------------------------------------
    if capture:
        vinf = np.linalg.norm(S["v2"] - S["vp"], axis=1)
        S["cost"] = S["cost"] + np.nan_to_num(capture_dv(vinf, seq[-1]), nan=np.inf)
    if max_days is not None:
        S["cost"] = np.where(S["jd"] - S["t0"] > max_days, np.inf, S["cost"])
    keep = _keep_best(S["cost"], np.round(S["t0"] / 15), np.round(S["jd"] / 15), n_cands)
    cands = []
    for i in keep:
        opts_used = [plan[k][2][int(S["hist_opt"][i, k])] for k in range(n_legs)]
        cands.append((float(S["cost"][i]), list(map(float, S["hist_jd"][i])), opts_used))
    # How the best cost varies with launch date: this is what defines a
    # launch window (see launch_window below).
    return cands, evaluated, (S["t0"], S["cost"])


def optimise(seq, window, capture=True, max_days=None, n_launch=None, n_tof=None, beam=None,
             n_results=None, min_sep=None):
    """
    Cheapest dates (and lap choices) for a route. window = (earliest,
    latest) launch JD; max_days optionally limits the total trip time.
    Returns the detailed best solution, or None if nothing works.

    With n_results = k it instead returns a list of up to k solutions whose
    launch dates are at least `min_sep` days apart (distinct launch
    opportunities), each with its launch window (see launch_window).
    """
    from scipy.optimize import minimize

    for p in seq:
        if p not in PLANET_ORDER:
            raise ValueError(f"Unknown planet '{p}'.")
    if len(seq) < 2:
        raise ValueError("A route needs a start and a destination.")
    if len(seq) - 2 > MAX_FLYBYS:
        raise ValueError(f"At most {MAX_FLYBYS} flybys are supported.")
    if seq[0] == seq[-1] and len(seq) == 2:
        raise ValueError("Start and destination must differ.")
    if window[1] <= window[0]:
        raise ValueError("The launch window must end after it starts.")

    n_legs = len(seq) - 1
    plan = _leg_plan(seq, window[0], max_days)
    n_launch = n_launch or {1: 90, 2: 70, 3: 60, 4: 50, 5: 45}[n_legs]
    n_tof = n_tof or {1: 60, 2: 40, 3: 36, 4: 40, 5: 44}[n_legs]
    # Longer routes need a wider beam: judged leg by leg, a route that looks
    # expensive early can turn out best later (tested on Cassini: beam 300
    # gave 9.7 km/s, beam 3000 gave 6.9 km/s with the historical dates).
    beam = beam or {1: 300, 2: 800, 3: 1200, 4: 2000, 5: 3000}[n_legs]
    start = time.perf_counter()
    many = n_results is not None
    cands, evaluated, profile = _beam_search(seq, window, capture, max_days, plan, n_launch, n_tof, beam,
                                             n_cands=60 if many else 12)
    if not cands:
        return [] if many else None
    if many:
        return _distinct_opportunities(seq, window, capture, max_days, plan, cands, profile,
                                       n_results, min_sep, evaluated, start)

    cache = _StateCache()
    best = (INF, None, None)
    for cost0, jds0, opts in cands[:5]:
        def cost_x(x, opts=opts):
            t0 = min(max(x[0], window[0]), window[1])
            jds = [t0]
            for k in range(n_legs):
                lo, hi, _ = plan[k]
                jds.append(jds[-1] + min(max(x[k + 1], lo * 0.9), hi * 1.1))
            return evaluate(seq, jds, capture, cache, opts, max_days=max_days)
        x0 = [jds0[0]] + [jds0[k + 1] - jds0[k] for k in range(n_legs)]
        res = minimize(cost_x, x0, method="Nelder-Mead",
                       options={"xatol": 0.05, "fatol": 1e-5, "maxiter": 250 * (n_legs + 1)})
        if res.fun < best[0]:
            best = (res.fun, res.x, opts)

    _, x, opts = best
    if x is None:
        return None
    jds = [min(max(x[0], window[0]), window[1])]
    for k in range(n_legs):
        lo, hi, _ = plan[k]
        jds.append(jds[-1] + min(max(x[k + 1], lo * 0.9), hi * 1.1))
    cost, det = evaluate(seq, jds, capture, cache, opts, detail=True)
    if det is None:
        return None
    det.update(jds=jds, seq=list(seq), capture=capture,
               search={"evaluated": int(evaluated), "seconds": time.perf_counter() - start})
    return det


def _refine(seq, window, capture, max_days, plan, jds0, opts, cache, quick=False):
    """Nelder-Mead polish of one candidate; returns (cost, jds)."""
    from scipy.optimize import minimize
    n_legs = len(seq) - 1

    def to_jds(x):
        jds = [min(max(x[0], window[0]), window[1])]
        for k in range(n_legs):
            lo, hi, _ = plan[k]
            jds.append(jds[-1] + min(max(x[k + 1], lo * 0.9), hi * 1.1))
        return jds
    x0 = [jds0[0]] + [jds0[k + 1] - jds0[k] for k in range(n_legs)]
    tol = {"xatol": 0.05, "fatol": 1e-4, "maxiter": 150 * (n_legs + 1)} if quick else \
        {"xatol": 0.05, "fatol": 1e-5, "maxiter": 250 * (n_legs + 1)}
    res = minimize(lambda x: evaluate(seq, to_jds(x), capture, cache, opts, max_days=max_days), x0,
                   method="Nelder-Mead", options=tol)
    return res.fun, to_jds(res.x)


WINDOW_MAX_DAYS = 90.0


def launch_window(profile, t0_best, span, margin=0.3):
    """
    The recommended launch window around a launch date: the continuous run
    of launch dates (from the search grid) whose cheapest route costs at
    most `margin` km/s more than the best one nearby. Returns (start, end) JD.
    """
    t0s, costs = profile
    ok = np.isfinite(costs)
    t0s, costs = t0s[ok], costs[ok]
    if len(t0s) == 0:
        return t0_best, t0_best
    grid = np.unique(t0s)
    best_per = np.full(len(grid), np.inf)
    np.minimum.at(best_per, np.searchsorted(grid, t0s), costs)
    near = np.abs(grid - t0_best) <= span
    if not near.any() or not np.isfinite(best_per[near]).any():
        return t0_best, t0_best
    thr = np.min(best_per[near]) + margin
    i = int(np.argmin(np.abs(grid - t0_best)))
    lo = hi = i
    # Never reach into the next opportunity, and never more than about three
    # months either side: when the cost changes very slowly (Jupiter to
    # Saturn line up only every 20 years) the run could otherwise span years.
    reach = min(span, WINDOW_MAX_DAYS)
    while lo > 0 and best_per[lo - 1] <= thr and t0_best - grid[lo - 1] <= reach:
        lo -= 1
    while hi < len(grid) - 1 and best_per[hi + 1] <= thr and grid[hi + 1] - t0_best <= reach:
        hi += 1
    # The grid only resolves launch dates to its spacing: pad by half a
    # step, and make sure the optimised date itself is inside.
    step = float(np.median(np.diff(grid))) if len(grid) > 1 else 0.0
    return min(float(grid[lo]) - step / 2, t0_best), max(float(grid[hi]) + step / 2, t0_best)


def _distinct_opportunities(seq, window, capture, max_days, plan, cands, profile, k, min_sep, evaluated, start):
    """Refine the best candidate of up to k launch opportunities that are at
    least min_sep days apart, and attach each one's launch window."""
    seeds = []
    for c in cands:                                  # cands are sorted by cost
        if all(abs(c[1][0] - s[1][0]) >= min_sep for s in seeds):
            seeds.append(c)
        if len(seeds) >= k:
            break
    cache = _StateCache()
    out = []
    for cost0, jds0, opts in seeds:
        cost, jds = _refine(seq, window, capture, max_days, plan, jds0, opts, cache, quick=True)
        if not np.isfinite(cost):
            continue
        c2, det = evaluate(seq, jds, capture, cache, opts, detail=True)
        if det is None or not det["feasible"]:
            continue
        det.update(jds=jds, seq=list(seq), capture=capture,
                   launch_window=launch_window(profile, jds[0], min_sep / 2),
                   search={"evaluated": int(evaluated), "seconds": time.perf_counter() - start})
        out.append(det)
    out.sort(key=lambda d: d["total_dv"])
    return out


# ----------------------------------------------------------------------
# route suggestions: which route, when to launch, how long it takes
# ----------------------------------------------------------------------

# Longest trip the suggestions will consider, per destination [years].
# Based on real missions: Mars 7-10 months (Perseverance 7 months),
# Jupiter 5-6 y (Juno, Galileo), Saturn 6.7 y (Cassini), Uranus 8.4 y and
# Neptune 12 y (Voyager 2), Mercury: MESSENGER 6.6 y with six flybys.
TRIP_LIMIT_YEARS = {"Mercury": 3.0, "Venus": 1.2, "Earth": 2.0, "Mars": 1.6,
                    "Jupiter": 7.0, "Saturn": 8.0, "Uranus": 12.0, "Neptune": 14.0}


def candidate_routes(dep, arr):
    """
    The route families mission designers actually consider for a trip.
    From Earth these follow real missions; from elsewhere, one flyby of
    each planet whose orbit lies between the start and the destination.
    """
    routes = [[dep, arr]]
    if dep == "Earth":
        routes += {
            "Mercury": [["Earth", "Venus", "Mercury"], ["Earth", "Venus", "Venus", "Mercury"]],
            "Mars": [["Earth", "Venus", "Mars"]],
            "Jupiter": [["Earth", "Mars", "Jupiter"], ["Earth", "Venus", "Earth", "Jupiter"],
                        ["Earth", "Venus", "Earth", "Earth", "Jupiter"]],
            "Saturn": [["Earth", "Jupiter", "Saturn"], ["Earth", "Venus", "Earth", "Saturn"]],
            "Uranus": [["Earth", "Jupiter", "Uranus"], ["Earth", "Saturn", "Uranus"],
                       ["Earth", "Jupiter", "Saturn", "Uranus"]],
            "Neptune": [["Earth", "Jupiter", "Neptune"], ["Earth", "Saturn", "Neptune"],
                        ["Earth", "Jupiter", "Saturn", "Neptune"]],
        }.get(arr, [])
    else:
        i, j = PLANET_ORDER.index(dep), PLANET_ORDER.index(arr)
        lo, hi = min(i, j), max(i, j)
        routes += [[dep, q, arr] for q in PLANET_ORDER[lo + 1:hi]]
    return routes


def _synodic_days(a, b, jd):
    if a == b:
        return orbital_period_days(a, jd)
    return 1.0 / abs(1.0 / orbital_period_days(a, jd) - 1.0 / orbital_period_days(b, jd))


def suggest_routes(dep, arr, start_jd, years=12.0, capture=True, max_years=None, per_route=3, progress=None):
    """
    Search every candidate route family over the next `years` years and
    return the launch opportunities found, cheapest first, each with its
    launch window, trip time and flyby details.
    """
    if dep == arr:
        raise ValueError("Start and destination must be different planets.")
    if not max_years:
        max_years = TRIP_LIMIT_YEARS[arr]
        if dep != "Earth":
            # The limits above are for trips from Earth. From elsewhere, allow
            # at least 1.25x the Hohmann time (Jupiter -> Saturn takes ~10
            # years even on the most efficient path). Transfer period from
            # Kepler's third law: a is proportional to T^(2/3).
            T1, T2 = orbital_period_days(dep, start_jd), orbital_period_days(arr, start_jd)
            hohmann_days = 0.5 * ((T1 ** (2 / 3) + T2 ** (2 / 3)) / 2) ** 1.5
            max_years = max(max_years, math.ceil(1.25 * hohmann_days / 365.25))
    max_days = max_years * 365.25
    window = (start_jd, start_jd + years * 365.25)
    t_start = time.perf_counter()
    options, tried = [], []
    routes = candidate_routes(dep, arr)

    def search(seq):
        # Launch opportunities repeat with the synodic period of the first leg.
        syn = _synodic_days(seq[0], seq[1], start_jd)
        n_launch = int(min(max(years * 365.25 / 8.0, 90), 560))
        try:
            return optimise(seq, window, capture, max_days=max_days, n_launch=n_launch,
                            n_results=per_route, min_sep=max(0.6 * syn, 60.0)), None
        except ValueError as exc:
            return None, str(exc)

    # The families are independent, and numpy releases the interpreter lock
    # during the big array operations, so they are searched in parallel.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(4, len(routes))) as pool:
        results = list(pool.map(search, routes))
    if progress:
        progress(len(routes), len(routes), None)
    for seq, (found, note) in zip(routes, results):
        if found is None:
            tried.append({"seq": seq, "found": 0, "note": note})
            continue
        # Sanity filter: the optimiser allows 2% slack on the trip time, but
        # a suggestion must respect the limit it is shown with; and a launch
        # pinned to the first or last day of the search period is not a real
        # opportunity (the true optimum lies outside the period).
        found = [d for d in found
                 if d["jds"][-1] - d["jds"][0] <= max_days + 1.0
                 and window[0] + 2.0 < d["jds"][0] < window[1] - 2.0]
        if not found:
            tried.append({"seq": seq, "found": 0, "note": "no workable trajectory"})
            continue
        tried.append({"seq": seq, "found": len(found),
                      "best_dv": min((f["total_dv"] for f in found), default=None),
                      "tof_days": (found[0]["jds"][-1] - found[0]["jds"][0]) if found else None,
                      "max_burn": max((fb["dv"] for fb in found[0]["flybys"]), default=0.0) if found else None})
        for det in found:
            legs = det["legs"]
            options.append({
                "seq": seq, "jds": det["jds"], "total_dv": det["total_dv"],
                "tof_days": det["jds"][-1] - det["jds"][0],
                "c3": det["vinf_launch"] ** 2, "vinf_arrive": det["vinf_arrive"],
                "launch_dv": float(_launch_dv(det["vinf_launch"], seq[0])),
                "capture_dv": float(capture_dv(det["vinf_arrive"], seq[-1])) if capture else None,
                "window": det["launch_window"],
                # What each flyby does, for the plain-language explanation:
                # the change in speed around the Sun it gives for free.
                "flybys": [{"planet": f["planet"], "dv": f["dv"], "altitude_radii": f["altitude_radii"],
                            "turn_deg": f["turn_deg"],
                            "gain": float(np.linalg.norm(legs[k + 1]["v1"]) - np.linalg.norm(legs[k]["v2"]))}
                           for k, f in enumerate(det["flybys"])],
                "legs": [{"revs": L["revs"], "days": det["jds"][k + 1] - det["jds"][k]} for k, L in enumerate(legs)],
            })
    if not options:
        raise ValueError("No workable route was found in this period. Try a later start year or a longer search.")
    options.sort(key=lambda o: o["total_dv"])
    # Timing facts for the explanation: how often the planets line up, and
    # how long each planet's year is.
    return {"options": options, "tried": tried, "max_years": max_years, "years": years,
            "capture": capture, "seconds": time.perf_counter() - t_start,
            "synodic_days": _synodic_days(dep, arr, start_jd),
            "period_days": {p: orbital_period_days(p, start_jd) for p in {dep, arr, "Earth"}}}


# ----------------------------------------------------------------------
# presentation: tracks, speed profile, comparison with going direct
# ----------------------------------------------------------------------

def describe(det, n_per_leg=180):
    """Everything the interface needs to draw and explain a route."""
    seq, jds, legs = det["seq"], det["jds"], det["legs"]
    track, t_days, speed, escape = [], [], [], []
    for k, L in enumerate(legs):
        dt = (jds[k + 1] - jds[k]) * 86400.0
        n = n_per_leg * (1 + L["revs"])
        for s in np.linspace(0.0, dt, n):
            r, v = propagate(L["r1"], L["v1"], float(s), mu=MU_SUN)
            rn = float(np.linalg.norm(r))
            track.append((r / AU).tolist())
            t_days.append(jds[k] - jds[0] + s / 86400.0)
            speed.append(float(np.linalg.norm(v)))
            escape.append(math.sqrt(2 * MU_SUN / rn))

    leg_info = []
    idx = 0
    for k, L in enumerate(legs):
        n = n_per_leg * (1 + L["revs"])
        v1 = L["v1"]
        a = 1.0 / (2.0 / np.linalg.norm(L["r1"]) - v1 @ v1 / MU_SUN)
        leg_info.append({"from": seq[k], "to": seq[k + 1], "days": jds[k + 1] - jds[k],
                         "revs": L["revs"], "branch": L["branch"], "start": idx, "end": idx + n,
                         "period_days": 2 * math.pi * math.sqrt(a ** 3 / MU_SUN) / 86400.0 if a > 0 else None,
                         "same_planet": seq[k] == seq[k + 1]})
        idx += n

    events = [{"kind": "launch", "planet": seq[0], "jd": jds[0], "vinf": det["vinf_launch"],
               "c3": det["vinf_launch"] ** 2,
               "dv": float(_launch_dv(det["vinf_launch"], seq[0])),
               "v_helio_after": float(np.linalg.norm(legs[0]["v1"])),
               "v_planet": float(np.linalg.norm(legs[0]["vp1"]))}]
    for k, fb in enumerate(det["flybys"], start=1):
        v_before = float(np.linalg.norm(legs[k - 1]["v2"]))
        v_after = float(np.linalg.norm(legs[k]["v1"]))
        events.append({"kind": "flyby", "planet": seq[k], "jd": jds[k], **fb,
                       "v_helio_before": v_before, "v_helio_after": v_after,
                       "gain": v_after - v_before,
                       "v_planet": float(np.linalg.norm(legs[k]["vp1"])),
                       "r_au": float(np.linalg.norm(legs[k]["r1"])) / AU,
                       # Vectors for the close-up animation (km/s, ecliptic
                       # frame): the hyperbola is drawn from these.
                       "v_planet_vec": legs[k]["vp1"].tolist(),
                       "vinf_in_vec": (legs[k - 1]["v2"] - legs[k]["vp1"]).tolist(),
                       "vinf_out_vec": (legs[k]["v1"] - legs[k]["vp1"]).tolist(),
                       "sun_dir": (-legs[k]["r1"] / np.linalg.norm(legs[k]["r1"])).tolist(),
                       "mu": PLANET_MU[seq[k]], "radius": PLANET_STYLE[seq[k]]["radius"],
                       "repeat": seq[k] == seq[k - 1] or (k + 1 < len(seq) and seq[k] == seq[k + 1])})
    events.append({"kind": "arrival", "planet": seq[-1], "jd": jds[-1], "vinf": det["vinf_arrive"],
                   "v_helio_before": float(np.linalg.norm(legs[-1]["v2"])),
                   "capture_dv": float(capture_dv(det["vinf_arrive"], seq[-1])) if det["capture"] else None})
    return {"seq": seq, "jds": jds, "track_au": track, "t_days": t_days, "speed": speed,
            "escape_speed": escape, "events": events, "legs": leg_info, "total_dv": det["total_dv"],
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
    if not best["feasible"]:
        bad = [f["planet"] for f in best["flybys"] if not f["feasible"]]
        raise ValueError(f"No physically possible route was found: {', '.join(bad)} would have to bend the path "
                         "more than its gravity can. Try other dates, a longer trip, or a different flyby planet.")
    out = describe(best)
    out["max_days"] = max_days
    direct = None
    if len(seq) > 2 and seq[0] != seq[-1]:
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
    {"key": "galileo", "label": "Galileo: Earth → Venus → Earth → Earth → Jupiter",
     "seq": ["Earth", "Venus", "Earth", "Earth", "Jupiter"],
     "from": "1989-10-12", "to": "1989-11-21", "capture": True, "max_years": 6.5,
     "history": "The launch window here is Galileo's real launch period (12 Oct - 21 Nov 1989). "
                "Galileo launched 18 Oct 1989 from the Space Shuttle, with too little launch energy to reach Jupiter "
                "directly. It passed Venus 10 Feb 1990, Earth 8 Dec 1990, looped around the Sun, passed Earth again "
                "8 Dec 1992, and reached Jupiter 7 Dec 1995. Its Earth-to-Earth loop took exactly 2 years, so Earth was "
                "at the same spot both times; that exact case is degenerate for Lambert's problem (start and end "
                "points coincide), so this model flies a nearby, slightly longer loop instead."},
    {"key": "cassini", "label": "Cassini: Earth → Venus → Venus → Earth → Jupiter → Saturn",
     "seq": ["Earth", "Venus", "Venus", "Earth", "Jupiter", "Saturn"],
     "from": "1997-10-06", "to": "1997-11-15", "capture": True, "max_years": 7.5,
     "history": "The launch window here is Cassini's real launch period (6 Oct - 15 Nov 1997, "
                "including the contingency days after 4 Nov). "
                "Cassini launched 15 Oct 1997: Venus 26 Apr 1998, Venus 24 Jun 1999, Earth 18 Aug 1999, "
                "Jupiter 30 Dec 2000, Saturn 1 Jul 2004. (The real mission also fired its engine once in deep space, "
                "in Dec 1998; this model has no deep-space burns, so any such need shows up as a powered flyby.)"},
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
     "history": "Galileo needed Venus AND two Earth flybys to reach Jupiter (see the Galileo example). With Venus alone, "
                "the engine has to make up the difference."},
    {"key": "ejs2", "label": "Earth → Jupiter → Saturn (next chance)", "seq": ["Earth", "Jupiter", "Saturn"],
     "from": "2033-01-01", "to": "2040-12-31", "capture": True, "max_years": 7,
     "history": "Jupiter and Saturn line up roughly every 20 years; this searches the next alignment."},
]


if __name__ == "__main__":
    import datetime
    from time_utils import julian_date

    def d(jd):
        return (datetime.datetime(2000, 1, 1, 12) + datetime.timedelta(days=jd - 2451545)).strftime("%Y-%m-%d")

    for key in ("galileo",):
        p = next(p for p in PRESETS if p["key"] == key)
        fr = [int(x) for x in p["from"].split("-")]
        to = [int(x) for x in p["to"].split("-")]
        r = plan_route(p["seq"], (julian_date(*fr, 0, 0, 0), julian_date(*to, 0, 0, 0)),
                       p["capture"], p["max_years"] * 365.25)
        print(p["label"], f"dv {r['total_dv']:.3f} km/s (direct {r['direct']['total_dv']:.3f}); {r['search']}")
        print("  ", " -> ".join(f"{e['planet']} {d(e['jd'])}" for e in r["events"]))
        print("  laps per leg:", [(L["from"], L["to"], L["revs"], L["branch"], round(L["days"])) for L in r["legs"]])
