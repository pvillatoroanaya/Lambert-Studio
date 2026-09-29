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
from lambert_solver import lambert_universal, lambert_batch
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


def planet_states_array(name, jds):
    """Positions (n,3) km and velocities (n,3) km/s of a planet at many dates."""
    jds = np.atleast_1d(np.asarray(jds, float))
    if ephemeris is not None:
        out = ephemeris.planet_states(name, jds)
        if out is not None:
            r, v = out
            return np.atleast_2d(r) * AU, np.atleast_2d(v) * AU / 86400.0
    st = [planets.planet_state(name, jd) for jd in jds]
    return np.array([s[0] for s in st]), np.array([s[1] for s in st])


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


def explain_transfer(t):
    """
    The numbers behind a plain-language explanation of a direct transfer:
    where the target was at launch, the ideal (Hohmann) comparison, and
    how often a launch window comes back.
    """
    dep, arr = t["departure"], t["arrival"]
    jd = t["jd_departure"]
    # Heliocentric longitude of each planet at launch (ecliptic).
    lon = lambda r: math.degrees(math.atan2(r[1], r[0]))
    r_arr_at_launch, _ = best_planet_state(arr, jd)
    phase = (lon(r_arr_at_launch) - lon(t["r1"]) + 180.0) % 360.0 - 180.0

    T1 = planets.orbital_period_days(dep, jd)
    T2 = planets.orbital_period_days(arr, jd)
    synodic = 1.0 / abs(1.0 / T1 - 1.0 / T2)
    a1 = planets.planet_elements(dep, jd)["a_au"] * AU
    a2 = planets.planet_elements(arr, jd)["a_au"] * AU
    t_h = math.pi * math.sqrt(((a1 + a2) / 2) ** 3 / MU_SUN) / 86400.0
    phase_h = (180.0 - 360.0 * t_h / T2 + 180.0) % 360.0 - 180.0      # target lead angle for Hohmann
    vinf_h = abs(math.sqrt(MU_SUN / a1) * (math.sqrt(2 * a2 / (a1 + a2)) - 1))
    return {
        "phase_deg": phase,
        "target_moves_deg": 360.0 * t["tof_days"] / T2,
        "hohmann_days": t_h, "hohmann_phase_deg": phase_h,
        "hohmann_c3": vinf_h ** 2,
        "hohmann_dv_departure": _hyperbolic_dv(vinf_h, dep, PARKING_ALT_DEPARTURE),
        "synodic_days": synodic,
        "outward": a2 > a1,
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

    # Planet states only depend on one date each, so compute them once;
    # then solve every (departure, arrival) pair in one batch.
    R1, VP1 = planet_states_array(dep, dep_grid)
    R2, _ = planet_states_array(arr, arr_grid)
    J, I = np.meshgrid(np.arange(n_arr), np.arange(n_dep), indexing="ij")
    J, I = J.ravel(), I.ravel()
    tof = arr_grid[J] - dep_grid[I]
    use = tof >= 30.0                        # too short to be meaningful
    v1, _, _, ok = lambert_batch(R1[I[use]], R2[J[use]], tof[use] * 86400.0, mu=MU_SUN)
    vinf = v1 - VP1[I[use]]
    c3 = np.where(ok, np.einsum("ij,ij->i", vinf, vinf), np.nan)
    Z[J[use], I[use]] = c3
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
