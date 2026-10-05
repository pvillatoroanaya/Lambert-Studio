"""
Approximate planetary ephemerides.

Uses Standish's low-precision Keplerian elements (JPL, "Keplerian
Elements for Approximate Positions of the Major Planets"): each planet's
elements are linear functions of time in Julian centuries from J2000.

Accuracy is of order arcminutes over 1800-2050 -- far more than enough
for trajectory design studies and visualisation, and the same class of
model used for preliminary mission analysis. It is NOT an ephemeris for
navigation.

Positions are returned in the J2000 ecliptic frame, in km.
"""

import math

import numpy as np

from constants import AU, JD_J2000, MU_SUN

# name: (a[AU], e, I[deg], L[deg], longitude of perihelion[deg],
#        longitude of ascending node[deg])  and their per-century rates.
_ELEMENTS = {
    "Mercury": (
        (0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593),
        (0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081),
    ),
    "Venus": (
        (0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255),
        (0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418),
    ),
    "Earth": (
        (1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
        (0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0),
    ),
    "Mars": (
        (1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
        (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343),
    ),
    "Jupiter": (
        (5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909),
        (-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106),
    ),
    "Saturn": (
        (9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448),
        (-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794),
    ),
    "Uranus": (
        (19.18916464, 0.04725744, 0.77263783, 313.23810451, 170.95427630, 74.01692503),
        (-0.00196176, -0.00004397, -0.00242939, 428.48202785, 0.40805281, 0.04240589),
    ),
    "Neptune": (
        (30.06992276, 0.00859048, 1.77004347, -55.12002969, 44.96476227, 131.78422574),
        (0.00026291, 0.00005105, 0.00035372, 218.45945325, -0.32241464, -0.00508664),
    ),
}

PLANET_ORDER = ["Mercury", "Venus", "Earth", "Mars",
                "Jupiter", "Saturn", "Uranus", "Neptune"]

# Display colour, and EQUATORIAL radius [km] (JPL Solar System Dynamics,
# "Planetary Physical Parameters"; 1-bar level for the giants). Used for
# parking / capture orbit altitudes and flyby distances; planets are
# never drawn to true scale against orbital distances.
PLANET_STYLE = {
    "Mercury": {"color": "#9c8e82", "radius": 2440.53},
    "Venus":   {"color": "#e3b76b", "radius": 6051.8},
    "Earth":   {"color": "#4a90d9", "radius": 6378.1366},
    "Mars":    {"color": "#d1603d", "radius": 3396.19},
    "Jupiter": {"color": "#d8a86d", "radius": 71492.0},
    "Saturn":  {"color": "#e0c88a", "radius": 60268.0},
    "Uranus":  {"color": "#8fd3df", "radius": 25559.0},
    "Neptune": {"color": "#4f6fd4", "radius": 24764.0},
}

# Gravitational parameter of each planet [km^3/s^2] (JPL; checked against
# JPL's masses x G), used for departure, capture and flyby calculations.
PLANET_MU = {
    "Mercury": 2.2032e4,
    "Venus": 3.24859e5,
    "Earth": 3.986004418e5,
    "Mars": 4.282837e4,
    "Jupiter": 1.26686534e8,
    "Saturn": 3.7931187e7,
    "Uranus": 5.793939e6,
    "Neptune": 6.836529e6,
}


def _kepler_E(M_rad, e, tol=1e-12, max_iter=100):
    """Solve Kepler's equation M = E - e sin E by Newton's method."""
    E = M_rad if e < 0.8 else math.pi
    for _ in range(max_iter):
        f = E - e * math.sin(E) - M_rad
        fp = 1 - e * math.cos(E)
        step = f / fp
        E -= step
        if abs(step) < tol:
            break
    return E


def planet_elements(name, jd):
    """Standish elements of a planet at a given Julian Date."""
    if name not in _ELEMENTS:
        raise KeyError(f"Unknown planet '{name}'. Known: {', '.join(PLANET_ORDER)}")
    base, rate = _ELEMENTS[name]
    T = (jd - JD_J2000) / 36525.0
    a, e, I, L, peri, node = (b + r * T for b, r in zip(base, rate))
    return dict(a_au=a, e=e, i_deg=I, L_deg=L, peri_deg=peri, node_deg=node)


def planet_state(name, jd):
    """
    Heliocentric position and velocity of a planet in the J2000 ecliptic
    frame.

    Returns (r [km], v [km/s]).
    """
    el = planet_elements(name, jd)
    a = el["a_au"] * AU                      # km
    e = el["e"]
    i = math.radians(el["i_deg"])
    node = math.radians(el["node_deg"])
    argp = math.radians(el["peri_deg"] - el["node_deg"])

    # Mean anomaly, wrapped to [-pi, pi).
    M = math.radians((el["L_deg"] - el["peri_deg"] + 180.0) % 360.0 - 180.0)
    E = _kepler_E(M, e)

    # Position and velocity in the orbital (perifocal) plane.
    x_p = a * (math.cos(E) - e)
    y_p = a * math.sqrt(1 - e * e) * math.sin(E)

    n = math.sqrt(MU_SUN / a ** 3)            # mean motion [rad/s]
    Edot = n / (1 - e * math.cos(E))
    vx_p = -a * math.sin(E) * Edot
    vy_p = a * math.sqrt(1 - e * e) * math.cos(E) * Edot

    # Perifocal -> ecliptic (3-1-3 rotation).
    cO, sO = math.cos(node), math.sin(node)
    ci, si = math.cos(i), math.sin(i)
    cw, sw = math.cos(argp), math.sin(argp)
    Q = np.array([
        [cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci, sO * si],
        [sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci, -cO * si],
        [sw * si, cw * si, ci],
    ])

    r = Q @ np.array([x_p, y_p, 0.0])
    v = Q @ np.array([vx_p, vy_p, 0.0])
    return r, v


def planet_orbit_path(name, jd, n=360):
    """
    One full orbit of a planet as a closed curve of ECLIPTIC positions
    [km], for drawing. Elements are frozen at `jd`, which is correct to
    the accuracy of this model over a single revolution.
    """
    el = planet_elements(name, jd)
    a = el["a_au"] * AU
    e = el["e"]
    i = math.radians(el["i_deg"])
    node = math.radians(el["node_deg"])
    argp = math.radians(el["peri_deg"] - el["node_deg"])

    nu = np.linspace(0.0, 2 * math.pi, n)
    p = a * (1 - e * e)
    r = p / (1 + e * np.cos(nu))
    xyz_p = np.vstack([r * np.cos(nu), r * np.sin(nu), np.zeros_like(nu)])

    cO, sO = math.cos(node), math.sin(node)
    ci, si = math.cos(i), math.sin(i)
    cw, sw = math.cos(argp), math.sin(argp)
    Q = np.array([
        [cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci, sO * si],
        [sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci, -cO * si],
        [sw * si, cw * si, ci],
    ])
    return (Q @ xyz_p).T


def orbital_period_days(name, jd=JD_J2000):
    """Sidereal period of a planet, in days."""
    a = planet_elements(name, jd)["a_au"] * AU
    return 2 * math.pi * math.sqrt(a ** 3 / MU_SUN) / 86400.0


if __name__ == "__main__":
    from time_utils import julian_date

    jd = julian_date(2026, 1, 1, 0, 0, 0.0)
    print(f"Heliocentric distances on JD {jd}")
    print(f"{'planet':<9}{'r [AU]':>10}{'v [km/s]':>11}{'period [yr]':>13}")
    for p in PLANET_ORDER:
        r, v = planet_state(p, jd)
        print(f"{p:<9}{np.linalg.norm(r)/AU:>10.4f}"
              f"{np.linalg.norm(v):>11.3f}{orbital_period_days(p)/365.25:>13.3f}")
