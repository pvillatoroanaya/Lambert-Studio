"""
Plain-text results report, shown in the GUI and saved by "Save report".
"""

import datetime

import numpy as np

from constants import MU_EARTH
from orbital_elements import format_duration


def _vec(v, fmt="{:>14,.4f}"):
    return "".join(fmt.format(c) for c in v)


def build_report(sol):
    """Format a solved case (the GUI's solution dict) as text."""
    el = sol["elems"]
    r1, r2 = np.asarray(sol["r1"]), np.asarray(sol["r2"])
    v1, v2 = np.asarray(sol["v1"]), np.asarray(sol["v2"])
    line = "=" * 72
    thin = "-" * 72

    out = [line,
           "LAMBERT'S PROBLEM - RESULTS",
           f"Generated {datetime.datetime.now():%Y-%m-%d %H:%M}",
           line,
           f"Input mode        : {sol.get('mode', 'observations')}",
           f"Transfer          : {'prograde' if sol.get('prograde', True) else 'retrograde'}",
           f"Time of flight    : {format_duration(sol['dt'])}",
           ""]

    if sol.get("r_station") is not None:
        out.append(f"Station (ECEF) km : {_vec(sol['r_station'])}")
        out.append("")

    out += ["STATE VECTORS (ECI)", thin,
            f"r1 [km]   {_vec(r1)}    |r1| = {np.linalg.norm(r1):,.3f}",
            f"r2 [km]   {_vec(r2)}    |r2| = {np.linalg.norm(r2):,.3f}",
            f"v1 [km/s] {_vec(v1)}    |v1| = {np.linalg.norm(v1):.4f}",
            f"v2 [km/s] {_vec(v2)}    |v2| = {np.linalg.norm(v2):.4f}",
            "",
            "CLASSICAL ORBITAL ELEMENTS", thin,
            f"Orbit type                 {el['orbit_type']}",
            f"a   semi-major axis        {el['a']:,.4f} km",
            f"e   eccentricity           {el['e']:.6f}",
            f"i   inclination            {el['i']:.4f} deg",
            f"RAAN                       {el['RAAN']:.4f} deg",
            f"w   argument of perigee    {el['argp']:.4f} deg",
            f"nu  true anomaly at r1     {el['nu']:.4f} deg",
            "",
            "DERIVED PARAMETERS", thin,
            f"h   angular momentum       {el['h']:,.4f} km^2/s",
            f"p   semi-latus rectum      {el['p']:,.4f} km",
            f"Specific energy            {el['energy']:.6f} km^2/s^2",
            f"Perigee radius / altitude  {el['r_p']:,.3f} / {el['alt_p']:,.3f} km"]
    if el["r_a"] is not None:
        out.append(f"Apogee radius / altitude   {el['r_a']:,.3f} / {el['alt_a']:,.3f} km")
    out.append(f"Period                     {format_duration(el['period'])}")
    out.append(f"Flight path angle at r1    {el['gamma']:.4f} deg")

    e1 = float(np.dot(v1, v1) / 2 - MU_EARTH / np.linalg.norm(r1))
    e2 = float(np.dot(v2, v2) / 2 - MU_EARTH / np.linalg.norm(r2))
    out += ["",
            "CONSISTENCY CHECKS", thin,
            f"Converged universal variable z   {sol['z']:.6f}",
            f"Energy at r1 / r2                {e1:.9f} / {e2:.9f} km^2/s^2",
            f"Difference (should be ~0)        {abs(e1 - e2):.3e} km^2/s^2"]

    if el["notes"]:
        out += ["", "NOTES", thin] + [f"- {n}" for n in el["notes"]]
    out.append(line)
    return "\n".join(out)
