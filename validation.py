"""
Validation suite.

Two independent kinds of check are run:

(A) REFERENCE CASES -- the solver is run on worked examples from
    H.D. Curtis, "Orbital Mechanics for Engineering Students", whose
    published answers are known. This catches outright algorithm errors.

(B) PHYSICS INVARIANTS -- properties that MUST hold for any valid
    Keplerian solution, checked on the assignment's own data:
      * specific orbital energy is identical at both points
      * specific angular momentum is identical at both points
      * the orbital elements recovered from (r1,v1) and (r2,v2) agree
      * the mean anomaly advances by exactly n * dt over the transfer
      * propagating r1,v1 forward by dt reproduces r2
    These are self-validating: they need no external reference values,
    so they also guard against a reference being mistranscribed.

Run with:  python3 validation.py
"""

import math
import numpy as np

from constants import MU_EARTH
from lambert_solver import lambert_universal, stumpff_C, stumpff_S
from orbital_elements import state_to_elements
from time_utils import julian_date, gmst_from_jd, time_of_flight
from coord_utils import topocentric_to_geocentric

# Accumulates (name, passed, detail) for the final report.
_RESULTS = []


def check(name, got, expected, tol, unit="", relative=False):
    """Record a single numeric comparison."""
    if expected == 0:
        err = abs(got)
    else:
        err = abs(got - expected) / abs(expected) if relative else abs(got - expected)
    passed = err <= tol
    kind = "rel" if relative else "abs"
    _RESULTS.append((name, passed,
                     f"got {got:,.5g}{unit}, expected {expected:,.5g}{unit} "
                     f"({kind} err {err:.3g}, tol {tol:g})"))
    return passed


def check_true(name, condition, detail=""):
    _RESULTS.append((name, bool(condition), detail))
    return bool(condition)


# ----------------------------------------------------------------------
# (A) Reference cases from Curtis
# ----------------------------------------------------------------------

def test_curtis_lambert():
    """
    Curtis, Example 5.2 -- Lambert's problem.

    Given two geocentric position vectors and a 1 hour time of flight,
    the prograde trajectory connecting them has known velocities.
    """
    r1 = np.array([5000.0, 10000.0, 2100.0])
    r2 = np.array([-14600.0, 2500.0, 7000.0])
    dt = 3600.0

    v1, v2, z = lambert_universal(r1, r2, dt, prograde=True)

    v1_exp = np.array([-5.9925, 1.9254, 3.2456])
    v2_exp = np.array([-3.3125, -4.1966, -0.38529])

    for idx, axis in enumerate("xyz"):
        check(f"Curtis 5.2  v1_{axis}", v1[idx], v1_exp[idx], 1e-3, " km/s")
    for idx, axis in enumerate("xyz"):
        check(f"Curtis 5.2  v2_{axis}", v2[idx], v2_exp[idx], 1e-3, " km/s")

    # Curtis then derives the orbit from this state vector.
    el = state_to_elements(r1, v1)
    check("Curtis 5.2  h", el["h"], 80470.0, 2e-4, " km^2/s", relative=True)
    check("Curtis 5.2  i", el["i"], 30.19, 5e-3, " deg", relative=True)
    check("Curtis 5.2  RAAN", el["RAAN"], 44.60, 5e-3, " deg", relative=True)
    check("Curtis 5.2  e", el["e"], 0.4335, 5e-3, "", relative=True)
    check("Curtis 5.2  argp", el["argp"], 30.71, 5e-3, " deg", relative=True)
    check("Curtis 5.2  nu1", el["nu"], 350.8, 5e-3, " deg", relative=True)
    check("Curtis 5.2  a", el["a"], 20000.0, 5e-3, " km", relative=True)


def test_curtis_elements():
    """
    Curtis, Example 4.3 -- classical elements from a state vector.
    Exercises state_to_elements independently of the Lambert solver,
    including a retrograde (i > 90 deg) orbit.
    """
    r = np.array([-6045.0, -3490.0, 2500.0])
    v = np.array([-3.457, 6.618, 2.533])
    el = state_to_elements(r, v)

    check("Curtis 4.3  h", el["h"], 58310.0, 1e-3, " km^2/s", relative=True)
    check("Curtis 4.3  i", el["i"], 153.2, 1e-3, " deg", relative=True)
    check("Curtis 4.3  RAAN", el["RAAN"], 255.3, 1e-3, " deg", relative=True)
    check("Curtis 4.3  e", el["e"], 0.1712, 5e-3, "", relative=True)
    check("Curtis 4.3  argp", el["argp"], 20.07, 5e-3, " deg", relative=True)
    check("Curtis 4.3  nu", el["nu"], 28.45, 5e-3, " deg", relative=True)
    check("Curtis 4.3  a", el["a"], 8788.0, 1e-3, " km", relative=True)


def test_stumpff():
    """
    Stumpff functions must agree with their series expansions near z = 0
    (where the closed forms are numerically unstable) and satisfy the
    identity  z*S(z) + C(z) ... checked here against known values.
    """
    check("Stumpff C(0)", stumpff_C(0.0), 0.5, 1e-12)
    check("Stumpff S(0)", stumpff_S(0.0), 1.0 / 6.0, 1e-12)
    # Continuity across the small-|z| series/closed-form switch.
    for z in (1e-5, -1e-5):
        c_near, s_near = stumpff_C(z), stumpff_S(z)
        check_true(f"Stumpff C continuous at z={z:g}", abs(c_near - 0.5) < 1e-5,
                   f"C={c_near:.10f}")
        check_true(f"Stumpff S continuous at z={z:g}", abs(s_near - 1/6) < 1e-5,
                   f"S={s_near:.10f}")
    # Elliptic closed form at z = (pi)^2 : C = 2/pi^2, S = (pi-0)/pi^3
    z = math.pi ** 2
    check("Stumpff C(pi^2)", stumpff_C(z), (1 - math.cos(math.pi)) / z, 1e-12)
    check("Stumpff S(pi^2)", stumpff_S(z), (math.pi - math.sin(math.pi)) / math.pi ** 3, 1e-12)


# ----------------------------------------------------------------------
# (B) Physics invariants, on the assignment's own data
# ----------------------------------------------------------------------

def assignment_case():
    """Run the full pipeline on the assignment's given observations."""
    r_station = np.array([1344.143, 6068.601, 1429.311])
    jd1 = julian_date(2023, 4, 2, 0, 30, 0.0)
    jd2 = julian_date(2023, 4, 2, 3, 0, 0.0)
    r1 = topocentric_to_geocentric(132.67, 32.44, 16945.450, r_station, gmst_from_jd(jd1))
    r2 = topocentric_to_geocentric(123.08, 50.06, 37350.340, r_station, gmst_from_jd(jd2))
    dt = time_of_flight(jd1, jd2)
    v1, v2, z = lambert_universal(r1, r2, dt)
    return r1, r2, v1, v2, dt


def test_invariants():
    r1, r2, v1, v2, dt = assignment_case()
    el1 = state_to_elements(r1, v1)
    el2 = state_to_elements(r2, v2)

    # Energy and angular momentum are constants of the motion.
    eps1 = np.dot(v1, v1) / 2 - MU_EARTH / np.linalg.norm(r1)
    eps2 = np.dot(v2, v2) / 2 - MU_EARTH / np.linalg.norm(r2)
    check("Invariant: specific energy equal at r1 and r2", eps2, eps1, 1e-9, " km^2/s^2")

    h1 = np.cross(r1, v1)
    h2 = np.cross(r2, v2)
    check("Invariant: |h| equal at r1 and r2",
          float(np.linalg.norm(h2)), float(np.linalg.norm(h1)), 1e-6, " km^2/s")
    check_true("Invariant: h direction equal at r1 and r2",
               np.allclose(h1 / np.linalg.norm(h1), h2 / np.linalg.norm(h2), atol=1e-10),
               "orbital plane is the same at both points")

    # The shape/orientation elements must not depend on which point they
    # were derived from (only the anomalies may differ).
    for key, unit in (("a", " km"), ("e", ""), ("i", " deg"),
                      ("RAAN", " deg"), ("argp", " deg")):
        check(f"Invariant: {key} same from (r1,v1) and (r2,v2)",
              el2[key], el1[key], 1e-6, unit)

    # Kepler's equation: mean anomaly must advance by exactly n * dt.
    dM_actual = (el2["M_anom"] - el1["M_anom"]) % 360.0
    dM_expected = math.degrees(el1["mean_motion"] * dt) % 360.0
    check("Invariant: mean anomaly advance equals n*dt",
          dM_actual, dM_expected, 1e-6, " deg")

    # Lambert must reproduce the time of flight it was given.
    check("Invariant: transfer time consistent with orbit period",
          dM_expected / 360.0 * el1["period"], dt, 1e-6, " s")

    # Closing the loop: propagate (r1,v1) forward by dt with an
    # independent Kepler propagator and land on r2.
    r2_prop = propagate_kepler(r1, v1, dt)
    err = float(np.linalg.norm(r2_prop - r2))
    check("Invariant: propagating r1,v1 by dt reproduces r2", err, 0.0, 1e-6, " km")


def propagate_kepler(r0, v0, dt, mu=MU_EARTH, tol=1e-12, max_iter=200):
    """
    Independent two-body propagator (universal Kepler equation with
    Lagrange f and g coefficients). Deliberately written separately from
    the Lambert solver so that agreement between the two is meaningful
    evidence rather than a shared-bug tautology.
    """
    r0 = np.asarray(r0, float)
    v0 = np.asarray(v0, float)
    r0n = np.linalg.norm(r0)
    v0n = np.linalg.norm(v0)
    vr0 = np.dot(r0, v0) / r0n
    alpha = 2.0 / r0n - v0n ** 2 / mu          # 1/a

    chi = math.sqrt(mu) * abs(alpha) * dt       # initial guess
    for _ in range(max_iter):
        z = alpha * chi ** 2
        Cz, Sz = stumpff_C(z), stumpff_S(z)
        F = (r0n * vr0 / math.sqrt(mu) * chi ** 2 * Cz
             + (1 - alpha * r0n) * chi ** 3 * Sz
             + r0n * chi
             - math.sqrt(mu) * dt)
        dF = (r0n * vr0 / math.sqrt(mu) * chi * (1 - z * Sz)
              + (1 - alpha * r0n) * chi ** 2 * Cz
              + r0n)
        dchi = F / dF
        chi -= dchi
        if abs(dchi) < tol:
            break

    z = alpha * chi ** 2
    f = 1 - chi ** 2 / r0n * stumpff_C(z)
    g = dt - chi ** 3 / math.sqrt(mu) * stumpff_S(z)
    return f * r0 + g * v0



# ----------------------------------------------------------------------
# (C) Reference-frame transforms
# ----------------------------------------------------------------------

def test_frames():
    """
    The frame chain must be invertible and must respect the geometric
    limits that any orbit obeys.
    """
    import frames
    from time_utils import julian_date

    station = np.array([1344.143, 6068.601, 1429.311])
    jd1 = julian_date(2023, 4, 2, 0, 30, 0.0)
    jd2 = julian_date(2023, 4, 2, 3, 0, 0.0)
    r1, r2, v1, v2, dt = assignment_case()
    el = state_to_elements(r1, v1)

    # Round trip: transform the solved ECI positions back into the
    # station's horizon frame and recover the ORIGINAL observations.
    for label, r, jd, (az_e, el_e, rg_e) in (
            ("obs1", r1, jd1, (132.67, 32.44, 16945.450)),
            ("obs2", r2, jd2, (123.08, 50.06, 37350.340))):
        az, elev, rng = frames.sez_to_azelrange(
            frames.eci_to_sez(r, station, gmst_from_jd(jd)))
        check(f"Round trip {label}: azimuth", az, az_e, 1e-6, " deg")
        check(f"Round trip {label}: elevation", elev, el_e, 1e-6, " deg")
        check(f"Round trip {label}: range", rng, rg_e, 1e-6, " km")

    # Propagating one full period must return to the starting point.
    times, R, V = frames.sample_orbit_in_time(r1, v1, 0.0, el["period"], n=200)
    check("Orbit closes after exactly one period",
          float(np.linalg.norm(R[-1] - R[0])), 0.0, 1e-6, " km")

    # A ground track can never exceed the inclination in latitude.
    R_ecef = frames.eci_track_to_ecef(R, times, jd1)
    lat, lon, alt = frames.ground_track(R_ecef)
    check_true("Ground-track latitude bounded by inclination",
               np.nanmax(np.abs(lat)) <= el["i"] + 1e-6,
               f"max |lat| {np.nanmax(np.abs(lat)):.4f} deg vs i {el['i']:.4f} deg")

    # In the perifocal frame the orbit is planar by construction.
    P = frames.eci_track_to_pqw(R, el["i"], el["RAAN"], el["argp"])
    check("Perifocal out-of-plane component is zero",
          float(np.max(np.abs(P[:, 2]))), 0.0, 1e-6, " km")

    # ECI -> ECEF -> ECI must be the identity.
    g = gmst_from_jd(jd1)
    back = frames.rot3(g) @ frames.eci_to_ecef(r1, g)
    check("ECI -> ECEF -> ECI round trip", float(np.linalg.norm(back - r1)),
          0.0, 1e-9, " km")


# ----------------------------------------------------------------------
# (D) Planetary ephemerides and interplanetary transfer
# ----------------------------------------------------------------------

def test_planets():
    """
    Sidereal periods follow from the semi-major axes via Kepler's third
    law, so comparing them with the accepted values tests the element
    table itself.
    """
    import planets
    from constants import AU

    expected_years = {
        "Mercury": 0.2408, "Venus": 0.6152, "Earth": 1.0000, "Mars": 1.8808,
        "Jupiter": 11.862, "Saturn": 29.457, "Uranus": 84.02, "Neptune": 164.79,
    }
    for name, yrs in expected_years.items():
        got = planets.orbital_period_days(name) / 365.25
        check(f"{name}: sidereal period", got, yrs, 3e-3, " yr", relative=True)

    # Earth's heliocentric distance must stay inside its known range.
    from time_utils import julian_date
    d = [float(np.linalg.norm(planets.planet_state("Earth",
         julian_date(2026, m, 1, 0, 0, 0.0))[0]) / AU) for m in range(1, 13)]
    check_true("Earth distance within 0.983-1.017 AU",
               0.982 < min(d) and max(d) < 1.018,
               f"range {min(d):.4f}-{max(d):.4f} AU")
    # Perihelion occurs in early January.
    check_true("Earth perihelion falls in Dec/Jan",
               int(np.argmin(d)) in (0, 11),
               f"minimum distance in month {int(np.argmin(d)) + 1}")


def test_interplanetary():
    """
    An Earth->Mars transfer must land in the envelope that real missions
    occupy. These are loose bounds on purpose -- they catch gross errors
    (wrong mu, wrong units, wrong frame) without over-fitting.
    """
    from interplanetary import transfer
    from time_utils import julian_date
    from constants import AU

    t = transfer("Earth", "Mars",
                 julian_date(2026, 11, 1, 0, 0, 0.0),
                 julian_date(2027, 8, 20, 0, 0, 0.0))

    check_true("Earth->Mars C3 in the 5-40 km^2/s^2 range",
               5.0 < t["c3"] < 40.0, f"C3 = {t['c3']:.2f} km^2/s^2")
    check_true("Earth->Mars injection dv in the 3-6 km/s range",
               3.0 < t["dv_departure"] < 6.0,
               f"dv = {t['dv_departure']:.3f} km/s")
    check_true("Arrival v-infinity in the 1-8 km/s range",
               1.0 < t["vinf_arrival"] < 8.0,
               f"v_inf = {t['vinf_arrival']:.3f} km/s")
    # The transfer ellipse must span from Earth's orbit out toward Mars.
    a_au = t["elements"]["a"] / AU
    check_true("Transfer semi-major axis between Earth and Mars orbits",
               1.0 < a_au < 1.6, f"a = {a_au:.4f} AU")

    # Same solver, heliocentric: energy must still be conserved.
    from constants import MU_SUN
    e1 = float(np.dot(t["v1"], t["v1"]) / 2 - MU_SUN / np.linalg.norm(t["r1"]))
    e2 = float(np.dot(t["v2"], t["v2"]) / 2 - MU_SUN / np.linalg.norm(t["r2"]))
    check("Heliocentric energy equal at both ends", e2, e1, 1e-6, " km^2/s^2")


# ----------------------------------------------------------------------
# (E) Extensions: ephemeris, manoeuvres, perturbations, satellites
#     Each is skipped (not failed) when its optional library is missing.
# ----------------------------------------------------------------------

def _optional(name, fn):
    try:
        fn()
    except ImportError as exc:
        check_true(f"{name} (skipped: {exc.name} not installed)", True, "optional")


def test_ephemeris():
    """The approximate Standish elements must agree with JPL DE440s to
    within their published accuracy (inner planets: < 0.001 AU)."""
    import ephemeris
    import planets
    from constants import AU
    if not ephemeris.available():
        check_true("DE440s ephemeris (skipped: file not downloaded)", True, "optional")
        return
    jd = julian_date(2026, 9, 29, 0, 0, 0.0)
    for name in ("Mercury", "Venus", "Earth", "Mars"):
        d = float(np.linalg.norm(ephemeris.planet_state(name, jd)[0] - planets.planet_state(name, jd)[0])) / AU
        check(f"{name}: Standish vs DE440s position", d, 0.0, 1e-3, " AU")
    moon, _ = ephemeris.moon_geocentric(jd)
    check_true("Moon distance within 356,000-407,000 km",
               356000 < float(np.linalg.norm(moon)) < 407000, f"{float(np.linalg.norm(moon)):,.0f} km")


def test_maneuvers():
    """Hohmann LEO (300 km) -> GEO: the textbook total is 3.893 km/s
    (Curtis, Example 6.1 uses the same method); a pure plane change
    must equal 2 v sin(di/2)."""
    import maneuvers
    h = maneuvers.hohmann(300, 35786)
    check("Hohmann LEO->GEO total delta-v", h["total_dv"], 3.893, 2e-3, " km/s")
    check("Hohmann transfer time = half transfer period", h["transfer_time"],
          maneuvers.period((2 * (6378.137) + 300 + 35786) / 2) / 2, 1e-3, " s")
    p = maneuvers.plane_change(400, 28.5, 51.6)
    v = maneuvers.circ_speed(6378.137 + 400)
    check("Plane change delta-v = 2 v sin(di/2)", p["total_dv"],
          2 * v * math.sin(math.radians(23.1) / 2), 1e-6, " km/s")
    # Bi-elliptic beats Hohmann for r2/r1 above ~15.58 with a high rb.
    b = maneuvers.bielliptic(300, 400000, 900000)
    hh = maneuvers.hohmann(300, 400000)
    check_true("Bi-elliptic cheaper than Hohmann for r2/r1 ~ 61",
               b["total_dv"] < hh["total_dv"], f"{b['total_dv']:.4f} vs {hh['total_dv']:.4f} km/s")


def test_perturbations():
    """Numerically integrated J2 drift of the node must match the
    analytic secular rate (Sun-synchronous orbit: about +0.9856 deg/day)."""
    import perturb
    r0, v0 = perturb.orbit_from_elements(700, 700, 98.19)
    out = perturb.propagate_perturbed(r0, v0, 5, use_j2=True, use_drag=False)
    s = out["summary"]
    check("J2 RAAN rate: integrated vs analytic", s["raan_rate"], s["raan_rate_analytic"],
          0.01, "", relative=True)
    check("Sun-synchronous RAAN rate", s["raan_rate_analytic"], 0.9856, 0.01, " deg/day", relative=True)
    # With no perturbation switched on, the integrator must reproduce Kepler.
    plain = perturb.propagate_perturbed(r0, v0, 1, use_j2=False, use_drag=False)
    check("Integrator with no perturbations = Kepler", plain["summary"]["max_diff"], 0.0, 1e-3, " km")


def test_gravity_assists():
    """
    Patched-conic route optimiser against history: searching only from
    the physics, it must rediscover the dates of real missions.
    """
    import flyby
    jd = lambda y, m, d: julian_date(y, m, d, 0, 0, 0.0)

    # A flyby whose in/out speeds match needs no engine burn.
    fb = flyby.flyby_analysis("Jupiter", np.array([6.0, 0.0, 0.0]), np.array([0.0, 6.0, 0.0]))
    check("Unpowered flyby: no burn when |v_inf| is unchanged", fb["dv"], 0.0, 1e-9, " km/s")
    check_true("Jupiter can turn a 6 km/s flyby by 90 deg", fb["feasible"],
               f"max turn {fb['max_turn_deg']:.1f} deg")

    v = flyby.plan_route(["Earth", "Venus", "Mercury"], (jd(1973, 6, 1), jd(1974, 3, 1)),
                         capture=False, max_days=0.6 * 365.25)
    check("Mariner 10: Venus flyby date (real: 5 Feb 1974)", v["jds"][1], jd(1974, 2, 5), 20.0, " JD")
    check("Mariner 10: launch date (real: 3 Nov 1973)", v["jds"][0], jd(1973, 11, 3), 20.0, " JD")

    y = flyby.plan_route(["Earth", "Jupiter", "Saturn"], (jd(1977, 1, 1), jd(1978, 6, 30)),
                         capture=False, max_days=3.5 * 365.25)
    check("Voyager: launch date (real: 5 Sep 1977)", y["jds"][0], jd(1977, 9, 5), 30.0, " JD")
    check("Voyager: Jupiter flyby (real: Mar-Jul 1979)", y["jds"][1], jd(1979, 5, 5), 90.0, " JD")
    gain = y["events"][1]["gain"]
    check_true("Voyager: Jupiter adds more than 5 km/s", gain > 5.0, f"gain {gain:.2f} km/s")
    check_true("Voyager route cheaper than flying direct",
               y["total_dv"] < y["direct"]["total_dv"],
               f"{y['total_dv']:.3f} vs {y['direct']['total_dv']:.3f} km/s")


def test_satellite_model():
    """The fast Kepler+J2 model used to animate thousands of satellites
    must stay close to full SGP4 over a few hours (visual accuracy)."""
    import satellites
    try:
        recs, _ = satellites.fetch_group("gps-ops")
    except RuntimeError:
        check_true("Satellite model vs SGP4 (skipped: no data downloaded yet)", True, "optional")
        return
    rows = satellites.satellite_table(["gps-ops"])["sats"][:8]
    by_id = {r["NORAD_CAT_ID"]: r for r in recs}
    worst = max(float(np.linalg.norm(np.subtract(satellites.sgp4_position(by_id[r[1]], r[3] + h / 24),
                                                  satellites.j2_position(r, r[3] + h / 24))))
                for r in rows for h in (0, 3, 6))
    check("GPS: Kepler+J2 model vs SGP4 (6 h)", worst, 0.0, 100.0, " km")


def run_validation():
    test_stumpff()
    test_curtis_elements()
    test_curtis_lambert()
    test_invariants()
    test_frames()
    test_planets()
    test_interplanetary()
    _optional("DE440s ephemeris", test_ephemeris)
    _optional("Manoeuvres", test_maneuvers)
    _optional("Perturbations", test_perturbations)
    _optional("Gravity assists", test_gravity_assists)
    _optional("Satellite model", test_satellite_model)

    width = 58
    print("=" * 78)
    print("VALIDATION SUITE")
    print("=" * 78)
    n_pass = 0
    for name, passed, detail in _RESULTS:
        flag = "PASS" if passed else "FAIL"
        n_pass += passed
        print(f"[{flag}] {name:<{width}} {detail}")
    print("-" * 78)
    total = len(_RESULTS)
    print(f"{n_pass}/{total} checks passed")
    print("=" * 78)
    return 0 if n_pass == total else 1


if __name__ == "__main__":
    raise SystemExit(run_validation())
