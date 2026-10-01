"""
Low-thrust (electric) propulsion: spiralling between two circular orbits.

An ion or Hall thruster pushes with a tiny force (a fraction of a newton)
but uses its propellant ten times more efficiently than a chemical engine
(specific impulse Isp ~ 1,500-4,000 s instead of ~320 s). Firing
continuously along the direction of motion, the spacecraft spirals slowly
outward (or, firing backwards, inward).

Equations of motion in polar coordinates (planar), thrust along velocity:
    r'' = r th'^2 - mu / r^2 + (T/m) v_r / v
    (r^2 th')' / r = (T/m) v_th / v
    m' = -T / (Isp g0)
integrated with SciPy's DOP853 until the orbit's semi-major axis reaches
the target. For comparison: the chemical Hohmann transfer between the same
orbits, and Edelbaum's analytic estimate for a slow circle-to-circle
spiral, dv = |v1 - v2|.

Simplifications (stated in the interface): only the central body's gravity
(no escape spiral from the departure planet, no capture at the target),
coplanar circular orbits, no rendezvous phasing, constant thrust (real
solar-electric thrust drops as the spacecraft moves away from the Sun).
"""

import math

import numpy as np
from scipy.integrate import solve_ivp

from constants import MU_EARTH, R_EARTH, MU_SUN, AU

G0 = 9.80665e-3          # km/s^2

BODIES = {"Sun": MU_SUN, "Earth": MU_EARTH}

# Published values (NASA / ESA / JPL fact sheets), rounded.
PRESETS = [
    {"key": "dawn", "label": "Dawn: Earth's orbit to Vesta's", "body": "Sun", "r1": 1.0, "r2": 2.362,
     "unit": "AU", "mass": 1217.7, "thrust_mN": 91.0, "isp": 3100.0, "power": [10.3, 2.6],
     "history": "Dawn (launched 2007) carried 425 kg of xenon for its NSTAR ion engines (one firing at a time, "
                "up to 91 mN, Isp up to 3,100 s). It changed its speed by about 11 km/s in total, more than any "
                "other spacecraft's engines at the time, and became the first to orbit two bodies: Vesta and Ceres. "
                "The real flight also used a Mars flyby."},
    {"key": "bepi", "label": "BepiColombo: inward toward Mercury", "body": "Sun", "r1": 1.0, "r2": 0.387,
     "unit": "AU", "mass": 4100.0, "thrust_mN": 290.0, "isp": 4000.0,
     "history": "ESA/JAXA's BepiColombo (launched 2018) uses two T6 gridded ion engines (up to 145 mN each, Isp "
                "around 4,000 s) together with nine planetary flybys to shed speed and fall toward Mercury, "
                "arriving in 2026."},
    {"key": "geo", "label": "All-electric satellite: raise to GEO", "body": "Earth", "r1": R_EARTH + 1000.0,
     "r2": 42164.0, "unit": "km", "mass": 2000.0, "thrust_mN": 330.0, "isp": 3500.0,
     "history": "Since 2015 some communication satellites (starting with Boeing's all-electric 702SP) climb to "
                "geostationary orbit on xenon thrusters alone. They save about half their launch mass, at the "
                "price of months of spiralling instead of a few hours."},
    {"key": "mars", "label": "An ion spacecraft to Mars' orbit", "body": "Sun", "r1": 1.0, "r2": 1.524,
     "unit": "AU", "mass": 1500.0, "thrust_mN": 180.0, "isp": 3000.0, "power": [10.0, 4.5],
     "history": "Electric propulsion is studied for Mars cargo missions: slower than a chemical transfer, but "
                "able to deliver much more mass for the same launch."},
]


def _hohmann(mu, r1, r2):
    a = (r1 + r2) / 2
    v1, v2 = math.sqrt(mu / r1), math.sqrt(mu / r2)
    dv1 = abs(math.sqrt(mu * (2 / r1 - 1 / a)) - v1)
    dv2 = abs(v2 - math.sqrt(mu * (2 / r2 - 1 / a)))
    return dv1 + dv2, math.pi * math.sqrt(a ** 3 / mu)


def spiral(body, r1, r2, mass, thrust_N, isp, n_out=1500, chem_isp=320.0, power=None):
    """Spiral from a circular orbit of radius r1 to r2 [km].

    power = (array power at 1 AU, maximum engine input power) in kW makes
    the thrust solar-limited around the Sun: the arrays give P/r^2, and the
    engine runs at full thrust only while that covers its maximum input
    (thrust proportional to power at constant Isp). Dawn: 10.3 kW arrays
    at 1 AU, NSTAR maximum input about 2.6 kW, so thrust falls beyond ~2 AU.
    """
    if body not in BODIES:
        raise ValueError(f"Unknown central body '{body}'.")
    mu = BODIES[body]
    if r1 <= 0 or r2 <= 0 or abs(r2 - r1) < 1e-6 * r1:
        raise ValueError("Start and target orbits must be different and positive.")
    if body == "Earth" and min(r1, r2) < R_EARTH + 150:
        raise ValueError("Orbits must be above 150 km altitude.")
    if not (mass > 0 and thrust_N > 0 and isp > 0):
        raise ValueError("Mass, thrust and Isp must be positive.")
    ve = isp * G0                                   # exhaust speed [km/s]
    sign = 1.0 if r2 > r1 else -1.0
    solar = power is not None and body == "Sun"
    if solar and not (power[0] > 0 and power[1] > 0):
        raise ValueError("Solar array and engine power must be positive.")

    def thrust_at(r):
        if not solar:
            return thrust_N
        return thrust_N * min(1.0, power[0] / (r / AU) ** 2 / power[1])

    def rhs(t, y):
        r, th, vr, vt, m = y
        v = math.hypot(vr, vt)
        T = thrust_at(r)
        acc = sign * T / m / 1000.0                 # km/s^2
        return [vr, vt / r, vt * vt / r - mu / (r * r) + acc * vr / v,
                -vr * vt / r + acc * vt / v, -T / (isp * 9.80665)]

    def reached(t, y):
        r, _, vr, vt, _ = y
        energy = (vr * vr + vt * vt) / 2 - mu / r
        a = -mu / (2 * energy)
        return (a - r2) * sign
    reached.terminal = True

    def empty(t, y):
        return y[4] - 0.02 * mass                   # never burn more than 98 % of the mass
    empty.terminal = True

    v1 = math.sqrt(mu / r1)
    # Upper bound on time: Edelbaum dv at the initial acceleration, doubled.
    dv_e = abs(v1 - math.sqrt(mu / r2))
    # Refuse spirals that would take absurdly long (or would take a long
    # time to compute): estimate the time and the number of laps first.
    t_est = dv_e / (min(thrust_at(r1), thrust_at(r2)) / mass / 1000.0)
    laps_est = t_est / (2 * math.pi * math.sqrt(math.sqrt(r1 * r2) ** 3 / mu))
    if t_est > 40 * 365.25 * 86400:
        raise ValueError(f"With this thrust the spiral would take about {t_est / 3.156e7:.0f} years. "
                         "Increase the thrust or reduce the mass.")
    if laps_est > 20000:
        raise ValueError(f"With this thrust the spacecraft would circle about {laps_est:,.0f} times "
                         f"({t_est / 3.156e7:.1f} years). Increase the thrust.")
    t_max = 3 * t_est + 10 * 2 * math.pi * math.sqrt(r1 ** 3 / mu)
    sol = solve_ivp(rhs, (0.0, t_max), [r1, 0.0, 0.0, v1, mass], method="DOP853",
                    rtol=1e-9, atol=1e-9, events=(reached, empty), dense_output=True)
    if sol.status == -1:
        raise ValueError("The integration failed.")
    if sol.t_events[1].size and not sol.t_events[0].size:
        raise ValueError("The spacecraft runs out of propellant before reaching the target orbit.")
    if not sol.t_events[0].size:
        raise ValueError("The target orbit was not reached; try more thrust.")
    t_end = float(sol.t_events[0][0])
    y_end = sol.sol(t_end)
    m_end = float(y_end[4])
    # Enough samples to draw every lap smoothly (the GEO spiral has ~1,600).
    n_out = int(min(max(n_out, 40 * float(y_end[1]) / (2 * math.pi)), 70000))
    ts = np.linspace(0.0, t_end, n_out)
    Y = sol.sol(ts)
    r, th, vr, vt, m = Y
    xy = np.stack([r * np.cos(th), r * np.sin(th)], axis=1)
    revs = float(y_end[1]) / (2 * math.pi)

    dv_low = ve * math.log(mass / m_end)
    dv_h, t_h = _hohmann(mu, r1, r2)
    m_chem_final = mass * math.exp(-dv_h / (chem_isp * G0))
    return {
        "body": body, "mu": mu, "r1": r1, "r2": r2, "mass": mass, "thrust": thrust_N, "isp": isp,
        "t": ts.tolist(), "xy": (xy / (AU if body == "Sun" else 1.0)).round(6 if body == "Sun" else 1).tolist(),
        "r": r.tolist(), "m": m.tolist(), "speed": np.hypot(vr, vt).tolist(),
        "duration": t_end, "revs": revs, "propellant": mass - m_end, "final_mass": m_end,
        "dv": dv_low, "edelbaum_dv": dv_e, "accel0": thrust_at(r1) / mass,
        "thrust_hist": [thrust_at(x) for x in r], "power": list(power) if solar else None,
        "chem": {"dv": dv_h, "time": t_h, "isp": chem_isp, "propellant": mass - m_chem_final,
                 "final_mass": m_chem_final},
        "unit": "AU" if body == "Sun" else "km", "scale": AU if body == "Sun" else 1.0,
    }


def run_preset(key, **override):
    p = dict(next(x for x in PRESETS if x["key"] == key), **override)
    s = AU if p["unit"] == "AU" else 1.0
    out = spiral(p["body"], p["r1"] * s, p["r2"] * s, p["mass"], p["thrust_mN"] / 1000.0, p["isp"],
                 power=p.get("power"))
    out["preset"] = p
    return out
