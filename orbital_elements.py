"""
Section 4: Classical orbital elements from a Cartesian state vector
(r, v), following the standard vector algorithm (Curtis / Vallado).

Returns the six classical elements -- a, e, i, RAAN (Omega), argument of
perigee (omega), true anomaly (nu) -- plus the derived parameters that
are normally quoted alongside them (period, apsides, energy, angular
momentum, anomalies, flight path angle).
"""

import math
import numpy as np

from constants import MU_EARTH, R_EARTH


def state_to_elements(r, v, mu=MU_EARTH, tol=1e-10):
    """
    Convert a Cartesian state vector (r, v) into classical orbital
    elements.

    Parameters
    ----------
    r, v : array_like, shape (3,)
        Position [km] and velocity [km/s] vectors, same frame (ECI).
    mu : float
        Gravitational parameter [km^3/s^2].
    tol : float
        Tolerance for detecting near-zero eccentricity / inclination
        (special-case orbits).

    Returns
    -------
    dict with keys:
        'a'     semi-major axis [km]
        'e'     eccentricity [-]
        'i'     inclination [deg]
        'RAAN'  right ascension of ascending node [deg]
        'argp'  argument of perigee [deg]
        'nu'    true anomaly [deg]
        'h'     specific angular momentum vector [km^2/s]
        'notes' list of strings flagging any special-case orbit
    """
    r = np.asarray(r, dtype=float)
    v = np.asarray(v, dtype=float)
    rn = np.linalg.norm(r)
    vn = np.linalg.norm(v)
    notes = []

    # 1. Specific angular momentum
    h_vec = np.cross(r, v)
    hn = np.linalg.norm(h_vec)

    # 2. Node vector
    k_hat = np.array([0.0, 0.0, 1.0])
    n_vec = np.cross(k_hat, h_vec)
    nn = np.linalg.norm(n_vec)

    # 3. Eccentricity vector
    e_vec = ((vn**2 - mu / rn) * r - np.dot(r, v) * v) / mu
    e = np.linalg.norm(e_vec)

    # 4. Specific mechanical energy -> semi-major axis
    energy = vn**2 / 2 - mu / rn
    if abs(e - 1.0) < tol:
        a = math.inf  # parabolic
        notes.append("Orbit is (near-)parabolic: e ~ 1, a is undefined/infinite.")
    else:
        a = -mu / (2 * energy)

    # 5. Inclination
    i = math.acos(np.clip(h_vec[2] / hn, -1.0, 1.0))

    # 6. RAAN
    if nn < tol:
        notes.append("Orbit is equatorial (i ~ 0 or 180 deg): RAAN is undefined, set to 0.")
        RAAN = 0.0
    else:
        RAAN = math.acos(np.clip(n_vec[0] / nn, -1.0, 1.0))
        if n_vec[1] < 0:
            RAAN = 2 * math.pi - RAAN

    # 7. Argument of perigee
    if e < tol:
        notes.append("Orbit is (near-)circular: e ~ 0, argument of perigee is undefined, set to 0.")
        argp = 0.0
    elif nn < tol:
        # equatorial + eccentric: use "true longitude of periapsis" convention instead
        argp = math.acos(np.clip(e_vec[0] / e, -1.0, 1.0))
        if e_vec[1] < 0:
            argp = 2 * math.pi - argp
        notes.append("Equatorial orbit: 'argp' reported is actually the longitude of periapsis.")
    else:
        argp = math.acos(np.clip(np.dot(n_vec, e_vec) / (nn * e), -1.0, 1.0))
        if e_vec[2] < 0:
            argp = 2 * math.pi - argp

    # 8. True anomaly
    if e < tol:
        # circular: use argument of latitude from node (or r itself if equatorial too)
        if nn < tol:
            nu = math.acos(np.clip(r[0] / rn, -1.0, 1.0))
            if r[1] < 0:
                nu = 2 * math.pi - nu
        else:
            nu = math.acos(np.clip(np.dot(n_vec, r) / (nn * rn), -1.0, 1.0))
            if r[2] < 0:
                nu = 2 * math.pi - nu
        notes.append("Circular orbit: 'nu' reported is the angle from the reference direction, not from perigee.")
    else:
        nu = math.acos(np.clip(np.dot(e_vec, r) / (e * rn), -1.0, 1.0))
        if np.dot(r, v) < 0:
            nu = 2 * math.pi - nu

    # ------------------------------------------------------------------
    # 9. Derived parameters normally quoted alongside the six elements.
    #    These are all consequences of (a, e, nu) + mu -- no new physics,
    #    but they are what actually describes the orbit in practical
    #    terms (how high, how long, how fast).
    # ------------------------------------------------------------------
    p = hn ** 2 / mu                      # semi-latus rectum [km]
    nu_rad = nu                            # keep the radian value before conversion

    # Apsides. r_p = a(1-e) holds for ellipse AND hyperbola (a < 0 there,
    # and 1-e < 0, so the product stays positive). The parabola is the
    # only case needing p/2 instead, since a is infinite.
    if math.isinf(a):
        r_p = p / 2.0
    else:
        r_p = a * (1 - e)

    # Apoapsis only exists for a closed (elliptical) orbit.
    r_a = a * (1 + e) if e < 1.0 and not math.isinf(a) else None

    # Orbital period and mean motion: closed orbits only.
    if e < 1.0 and not math.isinf(a) and a > 0:
        period = 2 * math.pi * math.sqrt(a ** 3 / mu)      # [s]
        mean_motion = math.sqrt(mu / a ** 3)               # [rad/s]
    else:
        period = None
        mean_motion = None

    # Speeds at the apsides, from vis-viva: v^2 = mu(2/r - 1/a).
    def _vis_viva(radius):
        if radius is None:
            return None
        if math.isinf(a):
            return math.sqrt(2 * mu / radius)   # parabolic escape speed
        return math.sqrt(max(0.0, mu * (2.0 / radius - 1.0 / a)))

    v_p = _vis_viva(r_p)
    v_a = _vis_viva(r_a)

    # Flight path angle at the current point: angle between the velocity
    # vector and the local horizon. Zero at the apsides.
    if e < tol:
        gamma = 0.0
    else:
        gamma = math.atan2(e * math.sin(nu_rad), 1 + e * math.cos(nu_rad))

    # Eccentric / hyperbolic anomaly and mean anomaly at the current point.
    E_anom = None
    M_anom = None
    if e < 1.0 - tol:
        # Elliptical: E from the half-angle relation, then Kepler's equation.
        E_anom = 2 * math.atan2(math.sqrt(1 - e) * math.sin(nu_rad / 2),
                                 math.sqrt(1 + e) * math.cos(nu_rad / 2))
        E_anom = E_anom % (2 * math.pi)
        M_anom = (E_anom - e * math.sin(E_anom)) % (2 * math.pi)
    elif e > 1.0 + tol:
        # Hyperbolic: H, then the hyperbolic form of Kepler's equation.
        arg = math.sqrt((e - 1) / (e + 1)) * math.tan(nu_rad / 2)
        if abs(arg) < 1.0:
            H_anom = 2 * math.atanh(arg)
            E_anom = H_anom
            M_anom = e * math.sinh(H_anom) - H_anom

    return {
        # --- the six classical elements ---
        "a": a,
        "e": e,
        "i": math.degrees(i),
        "RAAN": math.degrees(RAAN),
        "argp": math.degrees(argp),
        "nu": math.degrees(nu),
        # --- vectors / magnitudes ---
        "h_vec": h_vec,
        "h": hn,
        "e_vec": e_vec,
        "r_mag": rn,
        "v_mag": vn,
        # --- derived geometry ---
        "p": p,
        "r_p": r_p,
        "r_a": r_a,
        "alt_p": r_p - R_EARTH,
        "alt_a": (r_a - R_EARTH) if r_a is not None else None,
        # --- derived dynamics ---
        "energy": energy,
        "period": period,
        "mean_motion": mean_motion,
        "v_p": v_p,
        "v_a": v_a,
        "gamma": math.degrees(gamma),
        "E_anom": math.degrees(E_anom) if E_anom is not None else None,
        "M_anom": math.degrees(M_anom) if M_anom is not None else None,
        "orbit_type": _orbit_type(e, tol),
        "notes": notes,
    }


def _orbit_type(e, tol=1e-10):
    """Name the conic section implied by the eccentricity."""
    if e < tol:
        return "Circular"
    if e < 1.0 - tol:
        return "Elliptical"
    if abs(e - 1.0) <= tol:
        return "Parabolic"
    return "Hyperbolic"


def format_duration(seconds):
    """Format a duration in seconds as a readable h/min/s string."""
    if seconds is None:
        return "n/a (open orbit)"
    # Round to the displayed precision FIRST, otherwise a value such as
    # 9000 s can render as "2h 29m 60.0s" when the seconds field rounds
    # up to 60 independently of the minutes field.
    total = round(seconds, 1)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{seconds:,.1f} s  ({int(hours)}h {int(minutes)}m {secs:04.1f}s)"


def print_elements(elems, label=""):
    print(f"--- Orbital elements {label} ---")
    print(f"Orbit type          = {elems['orbit_type']}")
    print(f"a (semi-major axis) = {elems['a']:.4f} km")
    print(f"e (eccentricity)    = {elems['e']:.6f}")
    print(f"i (inclination)     = {elems['i']:.4f} deg")
    print(f"RAAN                = {elems['RAAN']:.4f} deg")
    print(f"argp (arg. perigee) = {elems['argp']:.4f} deg")
    print(f"nu (true anomaly)   = {elems['nu']:.4f} deg")
    print("--- Derived parameters ---")
    print(f"h (ang. momentum)   = {elems['h']:.4f} km^2/s")
    print(f"p (semi-latus rect.)= {elems['p']:.4f} km")
    print(f"Specific energy     = {elems['energy']:.6f} km^2/s^2")
    print(f"Perigee radius      = {elems['r_p']:.4f} km  (altitude {elems['alt_p']:.4f} km)")
    if elems["r_a"] is not None:
        print(f"Apogee radius       = {elems['r_a']:.4f} km  (altitude {elems['alt_a']:.4f} km)")
    else:
        print("Apogee radius       = n/a (open orbit)")
    print(f"Period              = {format_duration(elems['period'])}")
    print(f"Speed at perigee    = {elems['v_p']:.4f} km/s")
    if elems["v_a"] is not None:
        print(f"Speed at apogee     = {elems['v_a']:.4f} km/s")
    print(f"Flight path angle   = {elems['gamma']:.4f} deg")
    if elems["M_anom"] is not None:
        print(f"Mean anomaly        = {elems['M_anom']:.4f} deg")
    if elems["notes"]:
        print("Notes:")
        for note in elems["notes"]:
            print(f"  - {note}")


if __name__ == "__main__":
    from time_utils import julian_date, gmst_from_jd, time_of_flight
    from coord_utils import topocentric_to_geocentric
    from lambert_solver import lambert_universal

    r_station = np.array([1344.143, 6068.601, 1429.311])  # km

    jd1 = julian_date(2023, 4, 2, 0, 30, 0.0)
    jd2 = julian_date(2023, 4, 2, 3, 0, 0.0)
    gmst1 = gmst_from_jd(jd1)
    gmst2 = gmst_from_jd(jd2)

    r1 = topocentric_to_geocentric(132.67, 32.44, 16945.450, r_station, gmst1)
    r2 = topocentric_to_geocentric(123.08, 50.06, 37350.340, r_station, gmst2)
    dt = time_of_flight(jd1, jd2)

    v1, v2, z = lambert_universal(r1, r2, dt)

    elems1 = state_to_elements(r1, v1)
    elems2 = state_to_elements(r2, v2)

    print_elements(elems1, "(from r1, v1)")
    print()
    print_elements(elems2, "(from r2, v2)")

    # Consistency check: elements from either point on the same orbit
    # should match (nu will differ, everything else should be ~equal).
    print()
    print("Consistency check (a, e, i, RAAN, argp should match between the two):")
    print(f"  da    = {abs(elems1['a'] - elems2['a']):.6e} km")
    print(f"  de    = {abs(elems1['e'] - elems2['e']):.6e}")
    print(f"  di    = {abs(elems1['i'] - elems2['i']):.6e} deg")
    print(f"  dRAAN = {abs(elems1['RAAN'] - elems2['RAAN']):.6e} deg")
    print(f"  dargp = {abs(elems1['argp'] - elems2['argp']):.6e} deg")
