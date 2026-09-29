"""
Near-Earth asteroids and comets, from NASA/JPL's public APIs.

  * Small-Body Database query API -> orbital elements of the potentially
    hazardous asteroids (PHAs) or of all near-Earth objects, drawn in
    the solar-system view.
  * Close-Approach Data API      -> upcoming close approaches to Earth.
  * Horizons API                 -> the precise geocentric path of one
    object through its close approach (JPL's own integrated ephemeris,
    including Earth's and the Moon's gravity), for the flyby view.
"""

import datetime
import math
import urllib.parse

from netcache import get_json

_SBDB = ("https://ssd-api.jpl.nasa.gov/sbdb_query.api?"
         "fields=full_name,pdes,a,e,i,om,w,ma,epoch,H,pha&sb-group={}")
_CAD = ("https://ssd-api.jpl.nasa.gov/cad.api?date-min={}&date-max={}"
        "&dist-max={}&fullname=true&sort=date")
_HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api?"

AU_KM = 1.495978707e8
LD_KM = 384400.0          # lunar distance


def diameter_range_m(H):
    """
    Size estimate [m] from absolute magnitude H. The albedo of most
    asteroids is unknown, so a plausible range (0.25 bright .. 0.05 dark)
    is given rather than one number.
    """
    if H is None:
        return None
    d = lambda p: 1329.0 / math.sqrt(p) * 10 ** (-H / 5.0) * 1000.0
    return [round(d(0.25)), round(d(0.05))]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def neo_elements(group="pha", refresh=False):
    """
    Heliocentric ecliptic J2000 elements of a group of small bodies.
    group: "pha" (potentially hazardous, ~2.5k) or "neo" (all, ~40k).

    Rows: [name, a_AU, e, i_deg, node_deg, argp_deg, M_deg, epoch_jd, H, is_pha]
    """
    if group not in ("pha", "neo"):
        raise ValueError("group must be 'pha' or 'neo'")
    raw, info = get_json(_SBDB.format(group), f"sbdb_{group}", 7 * 86400,
                         refresh=refresh, timeout=90)
    rows = []
    for full_name, pdes, a, e, i, om, w, ma, epoch, H, pha in raw["data"]:
        vals = [_f(v) for v in (a, e, i, om, w, ma, epoch)]
        if None in vals or vals[1] >= 1.0 or vals[0] <= 0:
            continue                      # need a closed orbit to draw
        rows.append([full_name.strip(), *vals, _f(H), pha == "Y"])
    return {"rows": rows, "source": info["source"], "fetched": info["fetched"]}


def close_approaches(days_back=7, days_ahead=60, dist_max_au=0.05, refresh=False):
    """Close approaches to Earth in a window around today, soonest first."""
    today = datetime.date.today()
    d0 = (today - datetime.timedelta(days=days_back)).isoformat()
    d1 = (today + datetime.timedelta(days=days_ahead)).isoformat()
    raw, info = get_json(_CAD.format(d0, d1, dist_max_au),
                         f"cad_{d0}_{d1}_{dist_max_au}", 12 * 3600, refresh=refresh)
    idx = {f: k for k, f in enumerate(raw["fields"])}
    out = []
    for row in raw.get("data", []):
        dist_au = float(row[idx["dist"]])
        H = _f(row[idx["h"]])
        out.append({
            "des": row[idx["des"]],
            "name": (row[idx["fullname"]] or row[idx["des"]]).strip(),
            "jd": float(row[idx["jd"]]),
            "date": row[idx["cd"]],
            "dist_km": dist_au * AU_KM,
            "dist_ld": dist_au * AU_KM / LD_KM,
            "v_rel": _f(row[idx["v_rel"]]),
            "H": H,
            "diameter_m": diameter_range_m(H),
        })
    return {"approaches": out, "source": info["source"], "fetched": info["fetched"]}


def _jd_to_str(jd):
    d = datetime.datetime(2000, 1, 1, 12) + datetime.timedelta(days=jd - 2451545.0)
    return d.strftime("%Y-%m-%d %H:%M")


def _parse_horizons(text):
    import json
    result = json.loads(text)["result"]
    if "$$SOE" not in result:
        raise ValueError("Horizons returned no ephemeris: "
                         + result.strip().splitlines()[-1][:200])
    body = result.split("$$SOE")[1].split("$$EOE")[0]
    t, r = [], []
    for line in body.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        t.append(float(parts[0]))
        r.append([float(parts[2]), float(parts[3]), float(parts[4])])
    return {"jd": t, "r": r}


def flyby_path(des, jd_ca, half_width_days=3.0, step_min=30, refresh=False):
    """
    Geocentric path [km] of one object around its close approach, in
    Earth's equatorial J2000 frame (the same frame as ECI in this app).
    """
    params = {
        "format": "json",
        "COMMAND": f"'DES={des};'",
        "EPHEM_TYPE": "VECTORS",
        "CENTER": "'500@399'",
        "START_TIME": f"'{_jd_to_str(jd_ca - half_width_days)}'",
        "STOP_TIME": f"'{_jd_to_str(jd_ca + half_width_days)}'",
        "STEP_SIZE": f"'{step_min} m'",
        "VEC_TABLE": "1",
        "REF_PLANE": "FRAME",
        "OUT_UNITS": "KM-S",
        "CSV_FORMAT": "YES",
        "OBJ_DATA": "NO",
    }
    url = _HORIZONS + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    data, info = get_json(url, f"horizons_{des}_{jd_ca:.2f}", 30 * 86400,
                          refresh=refresh, timeout=60, parse=_parse_horizons)
    return {**data, "source": info["source"]}


if __name__ == "__main__":
    ca = close_approaches()
    print(f"{len(ca['approaches'])} close approaches ({ca['source']})")
    for a in ca["approaches"][:5]:
        print(f"  {a['name']:<30} {a['date']}  {a['dist_ld']:.2f} LD  "
              f"{a['v_rel']:.1f} km/s  ~{a['diameter_m']} m")
