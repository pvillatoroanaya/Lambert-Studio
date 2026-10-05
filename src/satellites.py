"""
Earth satellites from CelesTrak.

CelesTrak publishes the US Space Force's orbital data as "general
perturbations" (GP) element sets: mean elements meant for the SGP4
propagator. This module downloads them by group and turns them into a
compact table for the 3D view.

In the browser, thousands of satellites are moved every frame with a
Kepler + J2 secular model (the two largest effects: two-body motion and
the drift of the node and perigee caused by Earth's oblateness). For a
single satellite, `sgp4_position` gives the full SGP4 answer; the
validation suite compares the two.
"""

import datetime
import math

from netcache import get_json

# key: (label, colour). Order matters: a satellite listed in several
# groups is shown in the first one.
GROUPS = {
    "stations": ("Space stations", "#ff5a5f"),
    "visual":   ("Brightest", "#ffd166"),
    "gps-ops":  ("GPS", "#7bed9f"),
    "galileo":  ("Galileo", "#5ac8fa"),
    "glo-ops":  ("GLONASS", "#c792ea"),
    "beidou":   ("BeiDou", "#f78c6c"),
    "geo":      ("Geostationary", "#ffb454"),
    "weather":  ("Weather", "#89ddff"),
    "science":  ("Science", "#b2ccd6"),
    "oneweb":   ("OneWeb", "#e6a0c4"),
    "starlink": ("Starlink", "#8fa3c8"),
}
DEFAULT_GROUPS = ["stations", "visual", "gps-ops", "galileo", "geo", "weather", "science"]

_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP={}&FORMAT=json"
_TTL = 6 * 3600          # CelesTrak asks clients not to re-download more often


def _epoch_jd(text):
    dt = datetime.datetime.fromisoformat(text.replace("Z", ""))
    dt = dt.replace(tzinfo=datetime.timezone.utc)
    return 2440587.5 + dt.timestamp() / 86400.0


def fetch_group(group, refresh=False):
    """Raw OMM records of one CelesTrak group, and cache info."""
    if group not in GROUPS:
        raise ValueError(f"Unknown satellite group '{group}'.")
    return get_json(_URL.format(group), f"celestrak_{group}", _TTL, refresh=refresh)


def satellite_table(groups, refresh=False):
    """
    Compact element table for the 3D view.

    Returns a dict with
      groups: [{key, label, color, count, source, fetched, error}]
      sats:   [[name, norad_id, group_index, epoch_jd, mean_motion_rev_day,
                e, i_deg, raan_deg, argp_deg, M_deg], ...]
    """
    seen = set()
    sats = []
    out_groups = []
    for gi, key in enumerate(groups):
        label, color = GROUPS[key]
        info = {"key": key, "label": label, "color": color, "count": 0,
                "source": None, "fetched": None, "error": None}
        try:
            records, meta = fetch_group(key, refresh=refresh)
            info.update(source=meta["source"], fetched=meta["fetched"])
        except RuntimeError as exc:
            info["error"] = str(exc)
            out_groups.append(info)
            continue
        for r in records:
            sid = r.get("NORAD_CAT_ID")
            if sid in seen:
                continue
            try:
                row = [r["OBJECT_NAME"].strip(), sid, gi, _epoch_jd(r["EPOCH"]),
                       float(r["MEAN_MOTION"]), float(r["ECCENTRICITY"]),
                       float(r["INCLINATION"]), float(r["RA_OF_ASC_NODE"]),
                       float(r["ARG_OF_PERICENTER"]), float(r["MEAN_ANOMALY"])]
            except (KeyError, TypeError, ValueError):
                continue                      # skip malformed records
            if row[4] <= 0:
                continue
            seen.add(sid)
            sats.append(row)
            info["count"] += 1
        out_groups.append(info)
    return {"groups": out_groups, "sats": sats}


def sgp4_position(record, jd):
    """
    Full SGP4 position [km] (TEME frame) of one OMM record at a Julian
    Date. Used for validation and for precise single-object queries.
    """
    from sgp4.api import Satrec, WGS72
    from sgp4 import omm

    sat = Satrec()
    omm.initialize(sat, record)
    whole = math.floor(jd - 0.5) + 0.5
    err, r, _ = sat.sgp4(whole, jd - whole)
    if err:
        raise ValueError(f"SGP4 error code {err} for {record.get('OBJECT_NAME')}")
    return r


def j2_position(row, jd):
    """
    Python twin of the browser's Kepler + J2 secular model, so that the
    model can be tested against SGP4 (see validation.py).
    """
    from constants import MU_EARTH, R_EARTH
    J2 = 1.08262668e-3
    _, _, _, epoch, mm, e, i, raan, argp, M0 = row
    n = mm * 2 * math.pi / 86400.0
    a = (MU_EARTH / n ** 2) ** (1 / 3)
    p = a * (1 - e * e)
    i = math.radians(i)
    k = 1.5 * n * J2 * (R_EARTH / p) ** 2
    dt = (jd - epoch) * 86400.0
    raan = math.radians(raan) - k * math.cos(i) * dt
    argp = math.radians(argp) + 0.5 * k * (5 * math.cos(i) ** 2 - 1) * dt
    M = math.radians(M0) + n * dt

    E = M + e * math.sin(M)
    for _ in range(8):
        E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    xp = a * (math.cos(E) - e)
    yp = a * math.sqrt(1 - e * e) * math.sin(E)

    cO, sO = math.cos(raan), math.sin(raan)
    ci, si = math.cos(i), math.sin(i)
    cw, sw = math.cos(argp), math.sin(argp)
    return [
        (cO * cw - sO * sw * ci) * xp + (-cO * sw - sO * cw * ci) * yp,
        (sO * cw + cO * sw * ci) * xp + (-sO * sw + cO * cw * ci) * yp,
        (sw * si) * xp + (cw * si) * yp,
    ]


if __name__ == "__main__":
    t = satellite_table(["stations"])
    for g in t["groups"]:
        print(f"{g['label']}: {g['count']} satellites ({g['source']})")
    print("first:", t["sats"][0][:2])
