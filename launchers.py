"""
Launch vehicles: how much mass each rocket can send away from Earth at a
given launch energy C3 (km^2/s^2).

Source: the high-energy performance dataset of A. P. Girija, "Launch
Vehicle High-Energy Performance Dataset" (arXiv:2310.05994, 2023),
distributed with the open-source AMAT package (launcher-data/*.csv). The
curves were compiled from the NASA Launch Services Program performance
website (elvperf.ksc.nasa.gov). They are planning curves and include NASA's
standard margins, so real launches often do a little better: Juno
(3,625 kg at C3 = 31.1 on an Atlas V 551) is ~10 % above the curve.

The data cover 0 <= C3 <= 100 km^2/s^2 (SLS Block 1 from 29). Above that
(New Horizons flew at C3 = 157.7 with a 478 kg spacecraft) the curves are
not extrapolated: capacity() returns None.
"""

import numpy as np

# (C3 [km^2/s^2], payload [kg]) sampled from the AMAT CSV files.
_CURVES = {
    "Atlas V 401": [(0.3, 3019.6), (5.8, 2676.7), (11.2, 2354.3), (18.6, 1946.2), (24.2, 1661.7), (29.8, 1395.2),
                    (35.1, 1172.3), (40.8, 946.6), (46.5, 737.4), (52.0, 562.3), (59.5, 347.9)],
    "Atlas V 551": [(0, 6114.5), (5, 5549.8), (10, 5051.1), (15, 4608.5), (20, 4160.8), (25, 3735.8), (30, 3347.7),
                    (35, 2994.2), (40, 2682.8), (45, 2392.5), (50, 2125.1), (55, 1896.9), (60, 1659.8), (65, 1432.4),
                    (70, 1237.9), (75, 1036.7), (80, 860.3), (85, 698.4), (90, 535.1), (95, 352.0), (100, 231.7)],
    "Atlas V 551 + Star 48": [(1, 5435.5), (10, 4735.2), (20, 4060.3), (30, 3506.8), (40, 2955.5), (50, 2510.1),
                              (60, 2112.7), (70, 1789.0), (80, 1490.1), (90, 1262.4), (100, 1050.2)],
    "Delta IV Heavy": [(-9.2, 12032.8), (0.2, 10137.1), (13.4, 7901.7), (25.5, 6286.1), (37.4, 4957.5),
                       (49.2, 3854.6), (60.7, 2956.5), (73.0, 2139.8), (84.8, 1460.3), (96.5, 875.5)],
    "Falcon Heavy (recoverable)": [(1, 6557.4), (5, 5901.8), (10, 5143.5), (15, 4436.9), (20, 3835.6), (25, 3260.3),
                                   (30, 2753.7), (35, 2263.6), (40, 1812.7), (45, 1398.1), (50, 1029.8),
                                   (55, 661.8), (60, 336.5), (64, 65.5)],
    "Falcon Heavy (expendable)": [(1, 14713.9), (5, 13681.5), (10, 12433.5), (15, 11242.2), (20, 10159.8),
                                  (25, 9173.0), (30, 8264.8), (35, 7407.6), (40, 6626.6), (45, 5905.6),
                                  (50, 5248.8), (55, 4660.0), (60, 4099.1), (65, 3544.9), (70, 3080.2),
                                  (75, 2647.1), (80, 2233.0), (85, 1840.6), (90, 1467.0), (95, 1093.0),
                                  (100, 730.6)],
    "Falcon Heavy (expendable) + Star 48": [(1, 12187.2), (10, 10585.8), (20, 9021.6), (30, 7641.3), (40, 6444.9),
                                            (50, 5430.3), (60, 4536.4), (70, 3777.2), (80, 3148.9), (90, 2608.7),
                                            (100, 2196.1)],
    "Vulcan Centaur VC6": [(1, 10529.6), (5, 9846.4), (10, 9059.1), (15, 8303.6), (20, 7578.3), (25, 6844.0),
                           (30, 6201.2), (35, 5638.6), (40, 5076.1), (45, 4565.6), (50, 4067.3), (55, 3595.0),
                           (60, 3157.9), (65, 2751.6), (70, 2379.8), (75, 2013.2), (80, 1653.5), (85, 1309.8),
                           (90, 983.8), (95, 673.2), (100, 388.1)],
    "Vulcan Centaur VC6 + Star 48": [(0, 10114.2), (10, 8695.8), (20, 7462.0), (30, 6385.2), (40, 5420.7),
                                     (50, 4551.0), (60, 3845.3), (70, 3224.9), (80, 2696.0), (90, 2268.6),
                                     (100, 1920.3)],
    "SLS Block 1": [(29, 14867.8), (30, 14596.1), (40, 12072.4), (50, 9940.2), (60, 8177.7), (70, 6691.1),
                    (80, 5414.8), (90, 4257.4), (100, 3196.3)],
}

# Status and the real missions each vehicle is known for (NASA/ULA/SpaceX).
INFO = {
    "Atlas V 401": {"status": "no longer sold (last flights under way)",
                    "flew": "MAVEN, InSight, Lucy, Mars Reconnaissance Orbiter"},
    "Atlas V 551": {"status": "no longer sold (last flights under way)", "flew": "Juno (2011)"},
    "Atlas V 551 + Star 48": {"status": "no longer sold", "flew": "New Horizons (2006, with a Star 48B stage)"},
    "Delta IV Heavy": {"status": "retired (last flight April 2024)", "flew": "Parker Solar Probe (with a Star 48BV stage)"},
    "Falcon Heavy (recoverable)": {"status": "in service", "flew": "Psyche (2023; centre core expended)"},
    "Falcon Heavy (expendable)": {"status": "in service", "flew": "Europa Clipper (2024)"},
    "Falcon Heavy (expendable) + Star 48": {"status": "studied (proposed for Uranus Orbiter and Probe)", "flew": ""},
    "Vulcan Centaur VC6": {"status": "in service", "flew": ""},
    "Vulcan Centaur VC6 + Star 48": {"status": "studied", "flew": ""},
    "SLS Block 1": {"status": "in service (NASA)", "flew": "Artemis I (2022)"},
}

ORDER = list(_CURVES)


def capacity(name, c3):
    """Mass [kg] the vehicle can launch at this C3, or None outside its data."""
    pts = np.array(_CURVES[name])
    if c3 < pts[0, 0] - 1.0 or c3 > pts[-1, 0]:
        return None
    return float(np.interp(c3, pts[:, 0], pts[:, 1]))


def options(c3, mass):
    """Every vehicle's capacity at this C3 and whether it can launch `mass` kg,
    smallest capable first."""
    rows = []
    for name in ORDER:
        cap = capacity(name, c3)
        rows.append({"name": name, "capacity": cap, "fits": cap is not None and cap >= mass,
                     "margin": None if cap is None else cap - mass, **INFO[name]})
    fitting = sorted((r for r in rows if r["fits"]), key=lambda r: r["capacity"])
    others = [r for r in rows if not r["fits"]]
    return fitting + others


def smallest(c3, mass):
    """Name of the least capable vehicle that can still do the job, or None."""
    opts = [r for r in options(c3, mass) if r["fits"]]
    return opts[0]["name"] if opts else None


def curves():
    return {"order": ORDER, "curves": {k: v for k, v in _CURVES.items()}, "info": INFO,
            "source": "A. P. Girija, Launch Vehicle High-Energy Performance Dataset (arXiv:2310.05994), "
                      "from NASA Launch Services Program performance data"}
