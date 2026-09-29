"""
Realistic orbit prediction: numerical integration of the equations of
motion with the two main perturbations for Earth orbits,

  * J2 -- Earth's equatorial bulge. Makes the orbital plane precess
    (RAAN drift) and the perigee rotate (argument-of-perigee drift).
  * Atmospheric drag -- exponential atmosphere (Vallado, Table 8-4) in
    a co-rotating atmosphere. Lowers the orbit until re-entry.

and a comparison with the ideal two-body (Kepler) orbit from the same
starting state. The integrator is SciPy's DOP853 (8th-order
Runge-Kutta), with tight tolerances.

The measured drift rates are checked against the analytic J2 formulas:
    dRAAN/dt = -3/2 n J2 (R/p)^2 cos i
    dw/dt    =  3/4 n J2 (R/p)^2 (5 cos^2 i - 1)
"""

import math
import time

import numpy as np

from constants import MU_EARTH, R_EARTH, OMEGA_EARTH
from frames import propagate
from orbital_elements import state_to_elements

J2 = 1.08262668e-3
REENTRY_ALT = 100.0      # km: below this the orbit is considered to have decayed

# Vallado, "Fundamentals of Astrodynamics", Table 8-4:
# (base altitude [km], nominal density [kg/m^3], scale height [km])
_ATMOSPHERE = [
    (0, 1.225, 7.249), (25, 3.899e-2, 6.349), (30, 1.774e-2, 6.682),
    (40, 3.972e-3, 7.554), (50, 1.057e-3, 8.382), (60, 3.206e-4, 7.714),
    (70, 8.770e-5, 6.549), (80, 1.905e-5, 5.799), (90, 3.396e-6, 5.382),
    (100, 5.297e-7, 5.877), (110, 9.661e-8, 7.263), (120, 2.438e-8, 9.473),
    (130, 8.484e-9, 12.636), (140, 3.845e-9, 16.149), (150, 2.070e-9, 22.523),
    (180, 5.464e-10, 29.740), (200, 2.789e-10, 37.105), (250, 7.248e-11, 45.546),
    (300, 2.418e-11, 53.628), (350, 9.518e-12, 53.298), (400, 3.725e-12, 58.515),
    (450, 1.585e-12, 60.828), (500, 6.967e-13, 63.822), (600, 1.454e-13, 71.835),
    (700, 3.614e-14, 88.667), (800, 1.170e-14, 124.64), (900, 5.245e-15, 181.05),
    (1000, 3.019e-15, 268.00),
]
_ATM_BASE = np.array([row[0] for row in _ATMOSPHERE], float)


def density(alt_km):
    """Atmospheric density [kg/m^3] at an altitude, exponential model."""
    if alt_km < 0:
        alt_km = 0.0
    k = int(np.searchsorted(_ATM_BASE, alt_km, side="right")) - 1
    h0, rho0, H = _ATMOSPHERE[k]
    return rho0 * math.exp(-(alt_km - h0) / H)


def acceleration(r, v, use_j2=True, use_drag=False, bc=None):
    """
    Total acceleration [km/s^2]. bc = Cd * A / m in km^2/kg.
    """
    x, y, z = r
    rn2 = x * x + y * y + z * z
    rn = math.sqrt(rn2)
    a = -MU_EARTH / (rn2 * rn) * r

    if use_j2:
        k = 1.5 * J2 * MU_EARTH * R_EARTH ** 2 / rn2 ** 2.5
        z2 = 5.0 * z * z / rn2
        a = a + k * np.array([x * (z2 - 1.0), y * (z2 - 1.0), z * (z2 - 3.0)])

    if use_drag:
        alt = rn - R_EARTH
        if alt < 1000.0:
            v_rel = v - np.array([-OMEGA_EARTH * y, OMEGA_EARTH * x, 0.0])
            rho = density(alt) * 1e9                        # kg/m^3 -> kg/km^3
            a = a - 0.5 * rho * bc * np.linalg.norm(v_rel) * v_rel
    return a


def secular_rates(a, e, i_deg):
    """Analytic J2 drift rates [deg/day] of RAAN and argument of perigee."""
    n = math.sqrt(MU_EARTH / a ** 3)
    p = a * (1 - e * e)
    k = n * J2 * (R_EARTH / p) ** 2
    ci = math.cos(math.radians(i_deg))
    raan = -1.5 * k * ci
    argp = 0.75 * k * (5 * ci * ci - 1)
    return math.degrees(raan) * 86400, math.degrees(argp) * 86400


def propagate_perturbed(r0, v0, days, use_j2=True, use_drag=False,
                        cd=2.2, area_m2=10.0, mass_kg=1000.0, max_points=24000):
    """
    Integrate the perturbed motion and the ideal Kepler motion side by side.

    Returns a dict with the sampled perturbed track (for drawing), the
    osculating elements over time, the Kepler track at the same times,
    and a summary comparing measured and analytic drift rates.
    """
    from scipy.integrate import solve_ivp

    r0, v0 = np.asarray(r0, float), np.asarray(v0, float)
    if not (0 < days <= 365):
        raise ValueError("Duration must be between 0 and 365 days.")
    if mass_kg <= 0 or area_m2 <= 0 or cd <= 0:
        raise ValueError("Cd, area and mass must be positive.")
    el0 = state_to_elements(r0, v0)
    if el0["period"] is None:
        raise ValueError("The orbit must be closed (elliptical) to propagate it for days.")
    if el0["alt_p"] < REENTRY_ALT:
        raise ValueError(f"The perigee ({el0['alt_p']:.0f} km) is already below {REENTRY_ALT:.0f} km.")

    bc = cd * area_m2 * 1e-6 / mass_kg                         # km^2/kg
    t_end = days * 86400.0

    def rhs(t, y):
        return np.concatenate([y[3:], acceleration(y[:3], y[3:], use_j2, use_drag, bc)])

    def reentry(t, y):
        return np.linalg.norm(y[:3]) - (R_EARTH + REENTRY_ALT)
    reentry.terminal = True
    reentry.direction = -1

    t0 = time.perf_counter()
    sol = solve_ivp(rhs, (0.0, t_end), np.concatenate([r0, v0]), method="DOP853",
                    rtol=1e-10, atol=1e-8, dense_output=True, events=reentry)
    elapsed = time.perf_counter() - t0
    t_stop = float(sol.t[-1])
    reentered = sol.status == 1

    # Enough samples to draw every revolution smoothly (~64 per orbit).
    revs = t_stop / el0["period"]
    n = int(min(max(revs * 64, 600), max_points))
    ts = np.linspace(0.0, t_stop, n)
    Y = sol.sol(ts).T
    R = Y[:, :3]

    # Kepler reference at the same instants, and the growing difference.
    K = np.array([propagate(r0, v0, float(t))[0] for t in ts])
    diff = np.linalg.norm(R - K, axis=1)

    # Osculating elements on a thinner grid (for the charts).
    step = max(1, n // 1500)
    idx = np.arange(0, n, step)
    rows = [state_to_elements(Y[k, :3], Y[k, 3:]) for k in idx]
    raan = np.degrees(np.unwrap(np.radians([r["RAAN"] for r in rows])))
    argp = np.degrees(np.unwrap(np.radians([r["argp"] for r in rows])))
    days_axis = ts[idx] / 86400.0

    # Measured secular rates: straight-line fit through the drifting angle.
    def slope(y):
        return float(np.polyfit(days_axis, y, 1)[0]) if len(days_axis) > 2 else None
    raan_rate_an, argp_rate_an = secular_rates(el0["a"], el0["e"], el0["i"])
    circular = el0["e"] < 1e-3

    el_end = rows[-1]
    return {
        "t": ts, "r": R, "kepler_r": K[:: max(1, n // 4000)],
        "days": days_axis,
        "alt_p": [r["alt_p"] for r in rows], "alt_a": [r["alt_a"] for r in rows],
        "a": [r["a"] for r in rows], "e": [r["e"] for r in rows], "i": [r["i"] for r in rows],
        "raan": raan, "argp": argp,
        "diff_days": ts[idx] / 86400.0, "diff": diff[idx],
        "summary": {
            "initial": {k: el0[k] for k in ("a", "e", "i", "RAAN", "argp", "alt_p", "alt_a", "period")},
            "final": {k: el_end[k] for k in ("a", "e", "i", "RAAN", "argp", "alt_p", "alt_a", "period")},
            "raan_rate": slope(raan), "raan_rate_analytic": raan_rate_an,
            "argp_rate": None if circular else slope(argp),
            "argp_rate_analytic": None if circular else argp_rate_an,
            "days_run": t_stop / 86400.0, "reentered": bool(reentered),
            "max_diff": float(diff.max()), "revolutions": revs,
            "compute_s": elapsed, "steps": int(sol.t.size),
            "forces": {"j2": use_j2, "drag": use_drag},
            "ballistic_coefficient": mass_kg / (cd * area_m2),   # kg/m^2, the usual convention
        },
    }


def orbit_from_elements(alt_p, alt_a, i_deg, raan_deg=0.0, argp_deg=0.0, nu_deg=0.0):
    """State vector [km, km/s] at true anomaly nu of the given orbit."""
    if alt_a < alt_p:
        raise ValueError("Apogee altitude must be at least the perigee altitude.")
    rp, ra = R_EARTH + alt_p, R_EARTH + alt_a
    a, e = (rp + ra) / 2, (ra - rp) / (ra + rp)
    p = a * (1 - e * e)
    nu = math.radians(nu_deg)
    r_pqw = p / (1 + e * math.cos(nu)) * np.array([math.cos(nu), math.sin(nu), 0.0])
    v_pqw = math.sqrt(MU_EARTH / p) * np.array([-math.sin(nu), e + math.cos(nu), 0.0])
    O, i, w = (math.radians(x) for x in (raan_deg, i_deg, argp_deg))
    cO, sO, ci, si, cw, sw = math.cos(O), math.sin(O), math.cos(i), math.sin(i), math.cos(w), math.sin(w)
    Q = np.array([[cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci, sO * si],
                  [sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci, -cO * si],
                  [sw * si, cw * si, ci]])
    return Q @ r_pqw, Q @ v_pqw


# Teaching cases: each one shows a different effect clearly.
PRESETS = {
    "iss": {"label": "ISS-like (420 km, 51.6°)", "alt_p": 415, "alt_a": 425, "i": 51.6, "days": 10,
            "drag": True, "cd": 2.2, "area": 1600, "mass": 420000},
    "sso": {"label": "Sun-synchronous (700 km, 98.2°)", "alt_p": 700, "alt_a": 700, "i": 98.19, "days": 30,
            "drag": False},
    "molniya": {"label": "Molniya (63.4°, frozen perigee)", "alt_p": 600, "alt_a": 39750, "i": 63.4,
                "argp": 270, "days": 30, "drag": False},
    "decay": {"label": "Low CubeSat (250 km, decays)", "alt_p": 250, "alt_a": 260, "i": 51.6, "days": 60,
              "drag": True, "cd": 2.2, "area": 0.03, "mass": 4},
    "gto": {"label": "GTO (250 × 35,786 km, 27°)", "alt_p": 250, "alt_a": 35786, "i": 27, "days": 20,
            "drag": True, "cd": 2.2, "area": 20, "mass": 3000},
}


if __name__ == "__main__":
    for key in ("sso", "iss"):
        pr = PRESETS[key]
        r0, v0 = orbit_from_elements(pr["alt_p"], pr["alt_a"], pr["i"], 0, pr.get("argp", 0))
        out = propagate_perturbed(r0, v0, pr["days"], True, pr["drag"],
                                  pr.get("cd", 2.2), pr.get("area", 10), pr.get("mass", 1000))
        s = out["summary"]
        print(f"{pr['label']}: RAAN rate {s['raan_rate']:.4f} deg/day "
              f"(analytic {s['raan_rate_analytic']:.4f}); perigee {s['initial']['alt_p']:.1f} -> "
              f"{s['final']['alt_p']:.1f} km; {s['steps']} steps in {s['compute_s']:.2f} s")
