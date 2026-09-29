"""
Interplanetary mode: the SAME Lambert solver, with mu = mu_Sun and two
planet positions instead of two observations.

Provides:
    - transfer(dep, arr, jd_dep, jd_arr)  -> dict describing the transfer
    - transfer_path(t)                    -> sampled heliocentric arc
    - porkchop(dep, arr, dep_window, arr_window, n_dep, n_arr)
    - best_transfer(dep_grid, arr_grid, Z)
"""

import math

import numpy as np

from constants import MU_SUN
from lambert_solver import lambert_universal
from orbital_elements import state_to_elements
import planets
from planets import PLANET_MU, PLANET_STYLE
from frames import sample_orbit_in_time
from constants import AU

try:                                   # JPL DE440s when available
    import ephemeris
except ImportError:                    # pragma: no cover
    ephemeris = None


# NOTE: deliberately not called `planet_state`. build_single_file.py merges
# every module into one namespace and strips the `planets.` prefix, so a
# function of that name here would end up calling itself.
def best_planet_state(name, jd):
    """Heliocentric ecliptic r [km], v [km/s]: DE440s if present, else Standish."""
    if ephemeris is not None:
        out = ephemeris.planet_state(name, jd)
        if out is not None:
            return out
    return planets.planet_state(name, jd)


def _planet_states(name, jds):
    """States for many dates at once (vectorised when DE440s is used)."""
    if ephemeris is not None:
        out = ephemeris.planet_states(name, np.asarray(jds, float))
        if out is not None:
            r, v = out
            return [(r[k] * AU, v[k] * AU / 86400.0) for k in range(len(jds))]
    return [planets.planet_state(name, jd) for jd in jds]


def ephemeris_source():
    if ephemeris is not None and ephemeris.available():
        return "NASA/JPL DE440s"
    return "Standish approximate elements"

PARKING_ALT_DEPARTURE = 200.0   # km, circular parking orbit before injection
PARKING_ALT_ARRIVAL = 400.0     # km, circular capture orbit on arrival


def _hyperbolic_dv(vinf, planet, alt):
    """
    Delta-v between a circular orbit of altitude `alt` and a hyperbola
    with excess speed vinf, performed at periapsis (Oberth burn).
    """
    mu = PLANET_MU[planet]
    rp = PLANET_STYLE[planet]["radius"] + alt
    return math.sqrt(vinf ** 2 + 2 * mu / rp) - math.sqrt(mu / rp)


def transfer(dep, arr, jd_dep, jd_arr, prograde=True):
    """Solve one planet-to-planet transfer and derive its mission numbers."""
    if jd_arr <= jd_dep:
        raise ValueError("Arrival must be after departure.")
    r1, vp1 = best_planet_state(dep, jd_dep)
    r2, vp2 = best_planet_state(arr, jd_arr)
    dt = (jd_arr - jd_dep) * 86400.0

    v1, v2, z = lambert_universal(r1, r2, dt, prograde=prograde, mu=MU_SUN)

    vinf_dep = float(np.linalg.norm(v1 - vp1))
    vinf_arr = float(np.linalg.norm(v2 - vp2))

    cos_a = np.dot(r1, r2) / (np.linalg.norm(r1) * np.linalg.norm(r2))
    angle = math.degrees(math.acos(np.clip(cos_a, -1.0, 1.0)))
    if np.cross(r1, r2)[2] < 0:
        angle = 360.0 - angle

    return {
        "departure": dep, "arrival": arr,
        "jd_departure": jd_dep, "jd_arrival": jd_arr,
        "tof_days": jd_arr - jd_dep,
        "r1": r1, "r2": r2, "v1": v1, "v2": v2, "z": z,
        "v_planet_departure": vp1, "v_planet_arrival": vp2,
        "transfer_angle_deg": angle,
        "type": "Type I" if angle < 180.0 else "Type II",
        "vinf_departure": vinf_dep,
        "vinf_arrival": vinf_arr,
        "c3": vinf_dep ** 2,
        "dv_departure": _hyperbolic_dv(vinf_dep, dep, PARKING_ALT_DEPARTURE),
        "dv_arrival": _hyperbolic_dv(vinf_arr, arr, PARKING_ALT_ARRIVAL),
        "elements": state_to_elements(r1, v1, mu=MU_SUN),
        "ephemeris": ephemeris_source(),
    }


def transfer_path(t, n=300):
    """Heliocentric positions [km] along the transfer arc, shape (n, 3)."""
    dt = t["tof_days"] * 86400.0
    _, R, _ = sample_orbit_in_time(t["r1"], t["v1"], 0.0, dt, n=n, mu=MU_SUN)
    return R


def porkchop(dep, arr, dep_window, arr_window, n_dep=40, n_arr=40):
    """
    Departure C3 [km^2/s^2] over a grid of departure and arrival dates.

    Returns (dep_grid, arr_grid, Z) where dep_grid and arr_grid are 1-D
    arrays of Julian Dates and Z has shape (n_arr, n_dep). Cells with no
    valid transfer (arrival before departure, solver failure) are NaN.
    """
    dep_grid = np.linspace(dep_window[0], dep_window[1], n_dep)
    arr_grid = np.linspace(arr_window[0], arr_window[1], n_arr)
    Z = np.full((n_arr, n_dep), np.nan)

    # Planet states only depend on one date each, so compute them once.
    dep_states = _planet_states(dep, dep_grid)
    arr_states = _planet_states(arr, arr_grid)

    for j, jd_a in enumerate(arr_grid):
        r2, _ = arr_states[j]
        for i, jd_d in enumerate(dep_grid):
            if jd_a - jd_d < 30.0:          # too short to be meaningful
                continue
            r1, vp1 = dep_states[i]
            try:
                v1, _, _ = lambert_universal(r1, r2, (jd_a - jd_d) * 86400.0,
                                             mu=MU_SUN)
            except (ValueError, ZeroDivisionError, OverflowError):
                continue
            Z[j, i] = float(np.dot(v1 - vp1, v1 - vp1))
    return dep_grid, arr_grid, Z


def best_transfer(dep_grid, arr_grid, Z):
    """Grid cell with the lowest C3, as a dict (or None if all NaN)."""
    if np.all(np.isnan(Z)):
        return None
    j, i = np.unravel_index(np.nanargmin(Z), Z.shape)
    return {"jd_departure": float(dep_grid[i]),
            "jd_arrival": float(arr_grid[j]),
            "c3": float(Z[j, i]),
            "tof_days": float(arr_grid[j] - dep_grid[i])}


if __name__ == "__main__":
    from time_utils import julian_date

    t = transfer("Earth", "Mars",
                 julian_date(2026, 11, 1, 0, 0, 0.0),
                 julian_date(2027, 8, 20, 0, 0, 0.0))
    print(f"Earth -> Mars, {t['tof_days']:.0f} days, {t['type']}")
    print(f"  C3           = {t['c3']:.2f} km^2/s^2")
    print(f"  v_inf arrive = {t['vinf_arrival']:.3f} km/s")
    print(f"  dv inject    = {t['dv_departure']:.3f} km/s")
    print(f"  dv capture   = {t['dv_arrival']:.3f} km/s")
