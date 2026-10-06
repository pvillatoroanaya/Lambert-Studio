"""
Local web server behind Lambert Studio.

The interface is a web page (web/index.html) drawn with Three.js and
Plotly; the physics stays in Python. This module serves that page and a
small JSON API on 127.0.0.1 (this computer only, never the network):

    POST /api/solve        Lambert solution + everything needed to draw it
    GET  /api/planets      planetary element table (animated in the browser)
    POST /api/transfer     interplanetary transfer between two planets
    POST /api/porkchop     C3 over a grid of departure / arrival dates
    GET  /api/satellites   CelesTrak element sets for the chosen groups
    GET  /api/neo          potentially hazardous asteroids + close approaches
    GET  /api/flyby        JPL Horizons path of one close approach
"""

import datetime
import json
import logging
import math
import os
import pathlib
import threading
import time
import traceback
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

import numpy as np

from constants import AU, MU_EARTH, JD_J2000
from time_utils import julian_date, gmst_from_jd, time_of_flight
from coord_utils import topocentric_to_geocentric
from lambert_solver import lambert_universal
from orbital_elements import state_to_elements
from report import build_report
import frames
import planets
import interplanetary
import satellites
import asteroids
import ephemeris
import maneuvers
import flyby
import launchers
import dsm
import uncertainty
import nbody

# Inside a packaged .exe (PyInstaller) the files live in sys._MEIPASS.
import sys as _sys
WEB_DIR = pathlib.Path(getattr(_sys, "_MEIPASS", pathlib.Path(__file__).resolve().parent.parent)) / "web"


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _clean(x):
    """numpy -> plain Python, NaN/inf -> None (JSON has no NaN)."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, np.ndarray):
        return _clean(x.tolist())
    if isinstance(x, (np.floating, float)):
        x = float(x)
        return x if math.isfinite(x) else None
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def _num(value, label):
    """A finite number. Text such as 'nan' or 'inf', True/False, lists and
    absurdly large values are refused with a clear message."""
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number (got '{value}').")
    try:
        x = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label} must be a number (got '{value}').")
    if not math.isfinite(x):
        raise ValueError(f"{label} must be a finite number (got '{value}').")
    if abs(x) > 1e12:
        raise ValueError(f"{label} is far too large (got '{value}').")
    return x


def _vec3(value, label):
    """Three numbers [x, y, z]."""
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"{label} must be three numbers (x, y, z).")
    return np.array([_num(v, f"{label} {a}") for v, a in zip(value, "XYZ")])


def _obj(req, key, label):
    """A nested group of fields (one observation, for example)."""
    o = req.get(key)
    if not isinstance(o, dict):
        raise ValueError(f"{label} is missing.")
    return o


def _planet_list(value, label="Route"):
    """A route: a list of planet names (empty slots are skipped)."""
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label}: give the planets as a list.")
    return [_planet(p, f"{label} planet") for p in value if p]


def _planet(name, label):
    if not isinstance(name, str) or name not in planets.PLANET_ORDER:
        raise ValueError(f"{label}: choose one of the eight planets.")
    return name


def _parse_date(text, label):
    """Accepts YYYY-MM-DD (date picker) or DD/MM/YYYY (the assignment)."""
    text = str(text).strip()
    try:
        if "-" in text:
            y, m, d = (int(p) for p in text.split("-"))
        else:
            d, m, y = (int(p) for p in text.split("/"))
        datetime.date(y, m, d)
    except (ValueError, TypeError):
        raise ValueError(f"{label} is not a valid date ('{text}').")
    return y, m, d


def _parse_time(text, label):
    parts = str(text).strip().split(":")
    try:
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
        ss = float(parts[2]) if len(parts) > 2 else 0.0
    except (ValueError, IndexError):
        raise ValueError(f"{label} must be HH:MM:SS (got '{text}').")
    if not (0 <= hh < 24 and 0 <= mm < 60 and 0 <= ss < 60):
        raise ValueError(f"{label} is out of range.")
    return hh, mm, ss


def _jd(date_text, time_text, label):
    y, m, d = _parse_date(date_text, f"{label} date")
    hh, mm, ss = _parse_time(time_text, f"{label} time")
    return julian_date(y, m, d, hh, mm, ss)


def jd_to_iso(jd):
    d = datetime.datetime(2000, 1, 1, 12) + datetime.timedelta(days=jd - JD_J2000)
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------

def _observations(req):
    """Station + two observations, checked: [(jd, az, el, rng), ...]."""
    station = _vec3(req.get("station"), "Station")
    if not 6000 <= np.linalg.norm(station) <= 6600:
        raise ValueError("The station must be on the Earth's surface: its distance from the "
                         "Earth's centre must be about 6,378 km (6,000 to 6,600 km).")
    obs = []
    for k, key in enumerate(("obs1", "obs2"), 1):
        label = f"Observation {k}"
        o = _obj(req, key, label)
        jd = _jd(o.get("date"), o.get("time"), label)
        az = _num(o.get("az"), f"{label} azimuth") % 360.0
        el = _num(o.get("el"), f"{label} elevation")
        rng = _num(o.get("rng"), f"{label} range")
        if not -90 <= el <= 90:
            raise ValueError(f"{label} elevation must be between -90 and 90 deg.")
        if not 0 < rng <= 1e7:
            raise ValueError(f"{label} range must be between 0 and 10,000,000 km.")
        obs.append((jd, az, el, rng))
    if obs[1][0] <= obs[0][0]:
        raise ValueError("Observation 2 must be later than Observation 1.")
    return station, obs


def api_solve(req):
    mode = req.get("mode", "observations")
    prograde = bool(req.get("prograde", True))

    if mode == "observations":
        station, obs = _observations(req)
        (jd1, az1, el1, rg1), (jd2, az2, el2, rg2) = obs
        dt = time_of_flight(jd1, jd2)
        if dt <= 0:
            raise ValueError("Observation 2 must be later than Observation 1.")
        r1 = topocentric_to_geocentric(az1, el1, rg1, station, gmst_from_jd(jd1))
        r2 = topocentric_to_geocentric(az2, el2, rg2, station, gmst_from_jd(jd2))
        jd0 = jd1
    else:
        r1 = _vec3(req.get("r1"), "r1")
        r2 = _vec3(req.get("r2"), "r2")
        for v, n in ((r1, "r1"), (r2, "r2")):
            if np.linalg.norm(v) < 1e-6:
                raise ValueError(f"{n} cannot be the zero vector.")
        dt = _num(req.get("tof"), "Time of flight")
        if dt <= 0:
            raise ValueError("Time of flight must be positive.")
        if not 1 <= dt <= 1e9:
            raise ValueError("Time of flight must be between 1 s and 1,000,000,000 s (about 30 years).")
        station = None
        jd0 = JD_J2000       # no epoch in this mode; Earth drawn at J2000

    v1, v2, z = lambert_universal(r1, r2, dt, prograde=prograde)
    el = state_to_elements(r1, v1)
    sol = dict(r1=r1, r2=r2, v1=v1, v2=v2, dt=dt, z=z, elems=el,
               r_station=station, mode=mode, prograde=prograde)

    # One full period for closed orbits; for open ones, the observed arc
    # extended on both sides.
    if el["period"] is not None:
        t0, t1 = 0.0, el["period"]
    else:
        t0, t1 = -dt, 2 * dt
    times, R, _ = frames.sample_orbit_in_time(r1, v1, t0, t1, n=720)
    _, arc, _ = frames.sample_orbit_in_time(r1, v1, 0.0, dt, n=160)

    R_ecef = frames.eci_track_to_ecef(R, times, jd0)
    lat, lon, alt = frames.ground_track(R_ecef)

    out = {
        "elements": {k: v for k, v in el.items() if k not in ("h_vec", "e_vec")},
        "r1": r1, "r2": r2, "v1": v1, "v2": v2, "z": z, "dt": dt,
        "jd0": jd0, "epoch_iso": jd_to_iso(jd0), "mode": mode,
        "station_ecef": station,
        "track": {"t": times, "r": R, "closed": el["period"] is not None},
        "arc": arc,
        "ground": {"lat": lat, "lon": lon, "alt": alt},
        "report": build_report(sol),
        "energy": [float(np.dot(v1, v1) / 2 - MU_EARTH / np.linalg.norm(r1)),
                   float(np.dot(v2, v2) / 2 - MU_EARTH / np.linalg.norm(r2))],
    }

    if station is not None:
        s_lat, s_lon, _ = frames.ecef_to_geodetic(station)
        az, elev, rng = frames.sky_track(R, times, jd0, station)
        marks = []
        for label, r, jd in (("Obs 1", r1, jd0), ("Obs 2", r2, jd0 + dt / 86400.0)):
            a, e, _ = frames.sez_to_azelrange(frames.eci_to_sez(r, station, gmst_from_jd(jd)))
            marks.append({"label": label, "az": a, "el": e})
        out["station_latlon"] = [s_lat, s_lon]
        out["sky"] = {"t": times, "az": az, "el": elev, "rng": rng, "marks": marks,
                      "visible": frames.visibility_intervals(times, elev)}
    return out


def api_planets(_req=None):
    table = {}
    for name in planets.PLANET_ORDER:
        base, rate = planets._ELEMENTS[name]
        table[name] = {"base": base, "rate": rate, **planets.PLANET_STYLE[name]}
    return {"order": planets.PLANET_ORDER, "elements": table, "au_km": AU,
            "ephemeris": ephemeris.status()}


def _float_arg(req, key, label, lo=None, hi=None):
    v = _num(req.get(key), label)
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        raise ValueError(f"{label} must be between {lo} and {hi}.")
    return v


def api_ephemeris(req):
    """
    Planet states from DE440s on a regular grid, for the browser to
    interpolate (Hermite, with the velocities) while animating.
    """
    start = _float_arg(req, "start", "start", 2396760, 2506340)
    step = _float_arg(req, "step", "step", 0.01, 30)
    n = int(_float_arg(req, "n", "n", 2, 2000))
    jd = start + step * np.arange(n)
    out = {"jd": jd, "step": step, "planets": {}}
    for name in planets.PLANET_ORDER:
        st = ephemeris.planet_states(name, jd)
        if st is None:
            raise RuntimeError("The DE440s ephemeris is not available.")
        out["planets"][name] = {"r": np.round(st[0], 10), "v": np.round(st[1], 12)}
    return out


def api_moon(req):
    """Geocentric Moon (and Sun) on a regular grid, ICRF km."""
    start = _float_arg(req, "start", "start", 2396760, 2506340)
    step = _float_arg(req, "step", "step", 0.001, 5)
    n = int(_float_arg(req, "n", "n", 2, 5000))
    jd = start + step * np.arange(n)
    moon = ephemeris.moon_geocentric(jd)
    if moon is None:
        raise RuntimeError("The DE440s ephemeris is not available.")
    return {"jd": jd, "step": step, "r": np.round(moon[0], 3), "v": np.round(moon[1], 6),
            "sun": np.round(ephemeris.sun_geocentric(jd), 0)}


def api_maneuver(req):
    kind = req.get("kind", "hohmann")
    mass = _float_arg(req, "mass", "Spacecraft mass", 1, 1e7)
    isp = _float_arg(req, "isp", "Engine Isp", 50, 10000)
    comparison = None
    if kind == "circularize":
        if not req.get("r") or not req.get("v"):
            raise ValueError("Solve an orbit in the Orbit tab first.")
        plan = maneuvers.circularize(_vec3(req["r"], "Position"), _vec3(req["v"], "Velocity"),
                                     req.get("where", "apogee"), mass, isp)
    else:
        alt1 = _num(req.get("alt1"), "Initial altitude")
        i1 = _float_arg(req, "i1", "Initial inclination", 0, 180)
        i2 = _float_arg(req, "i2", "Final inclination", 0, 180)
        if kind == "plane":
            plan = maneuvers.plane_change(alt1, i1, i2, mass, isp)
        else:
            alt2 = _num(req.get("alt2"), "Final altitude")
            alt_b = _num(req.get("altb", 100000), "Intermediate apoapsis altitude")
            if kind == "bielliptic":
                plan = maneuvers.bielliptic(alt1, alt2, alt_b, i1, i2, mass, isp)
            else:
                plan = maneuvers.hohmann(alt1, alt2, i1, i2, mass, isp)
            if alt_b >= max(alt1, alt2):
                comparison = maneuvers.compare(alt1, alt2, i1, i2, alt_b)
    plan["comparison"] = comparison
    return plan


def _jd_from_date(text, label):
    y, m, d = _parse_date(text, label)
    return julian_date(y, m, d, 0, 0, 0.0)


def api_transfer(req):
    dep, arr = _planet(req.get("dep"), "Departure"), _planet(req.get("arr"), "Arrival")
    if dep == arr:
        raise ValueError("Departure and arrival planets must be different.")
    jd_d = _jd_from_date(req["dep_date"], "Departure date")
    jd_a = _jd_from_date(req["arr_date"], "Arrival date")
    if jd_a <= jd_d:
        raise ValueError("Arrival must be after departure.")
    t = interplanetary.transfer(dep, arr, jd_d, jd_a)
    track = interplanetary.transfer_path(t, n=400)
    keep = ("departure", "arrival", "jd_departure", "jd_arrival", "tof_days",
            "transfer_angle_deg", "type", "vinf_departure", "vinf_arrival",
            "c3", "dv_departure", "dv_arrival", "ephemeris")
    out = {k: t[k] for k in keep}
    out["a_au"] = t["elements"]["a"] / AU
    out["e"] = t["elements"]["e"]
    out["track_au"] = np.asarray(track) / AU
    out["dep_iso"] = jd_to_iso(jd_d)
    out["arr_iso"] = jd_to_iso(jd_a)
    out["explain"] = interplanetary.explain_transfer(t)
    return out


def api_suggest_window(req):
    after = _jd_from_date(req.get("after") or datetime.date.today().isoformat(), "Search start date")
    dep, arr = _planet(req.get("dep"), "Departure"), _planet(req.get("arr"), "Arrival")
    if dep == arr:
        raise ValueError("Departure and arrival planets must be different.")
    s = interplanetary.suggest_window(dep, arr, after)
    for k in ("jd_departure", "jd_arrival"):
        s[k.replace("jd_", "") + "_iso"] = jd_to_iso(s[k])
    s["window_iso"] = {k: jd_to_iso(v)[:10] for k, v in s["window"].items()}
    return s


def api_route_suggest(req):
    """Recommended routes, launch windows and trip times for a trip."""
    dep, arr = req.get("dep"), req.get("arr")
    if dep not in planets.PLANET_ORDER or arr not in planets.PLANET_ORDER:
        raise ValueError("Choose a start and a destination planet.")
    year = int(_float_arg(req, "from_year", "Search from year", 1900, 2130))
    years = _float_arg(req, "years", "Search length (years)", 2, 20)
    start = julian_date(year, 1, 1, 0, 0, 0.0)
    today = julian_date(*datetime.date.today().timetuple()[:3], 0, 0, 0.0)
    if year == datetime.date.today().year:
        start = max(start, today)             # no launches in the past this year
    out = flyby.suggest_routes(dep, arr, start, years=years, capture=bool(req.get("capture", True)))
    for o in out["options"]:
        o["iso"] = [jd_to_iso(j)[:10] for j in o["jds"]]
        o["window_iso"] = [jd_to_iso(o["window"][0])[:10], jd_to_iso(o["window"][1])[:10]]
    out["start_iso"] = jd_to_iso(start)[:10]
    return out


def api_route_presets(_req=None):
    return {"presets": flyby.PRESETS, "dsm_presets": dsm.PRESETS, "planets": planets.PLANET_ORDER}


def api_route(req):
    seq = _planet_list(req.get("seq", []))
    if len(seq) < 2:
        raise ValueError("Choose at least a start and a destination.")
    if len(seq) > 2 + flyby.MAX_FLYBYS:
        raise ValueError(f"At most {flyby.MAX_FLYBYS} flybys are supported.")
    w0 = _jd_from_date(req.get("from"), "Launch window start")
    w1 = _jd_from_date(req.get("to"), "Launch window end")
    if w1 - w0 > 15 * 365.25:
        raise ValueError("Keep the launch window under 15 years (the search would take too long).")
    max_years = _float_arg(req, "max_years", "Maximum trip time (years)", 0.1, 40)
    out = flyby.plan_route(seq, (w0, w1), bool(req.get("capture", True)), max_years * 365.25)

    def iso(r):
        if r is None:
            return None
        for e in r["events"]:
            e["iso"] = jd_to_iso(e["jd"])
        return r
    iso(out)
    iso(out["direct"])
    return out


def api_porkchop(req):
    dep, arr = _planet(req.get("dep"), "Departure"), _planet(req.get("arr"), "Arrival")
    if dep == arr:
        raise ValueError("Departure and arrival planets must be different.")
    w_dep = (_jd_from_date(req["dep_start"], "Departure window start"),
             _jd_from_date(req["dep_end"], "Departure window end"))
    w_arr = (_jd_from_date(req["arr_start"], "Arrival window start"),
             _jd_from_date(req["arr_end"], "Arrival window end"))
    if w_dep[1] <= w_dep[0] or w_arr[1] <= w_arr[0]:
        raise ValueError("Each window must end after it starts.")
    n = int(min(max(_num(req.get("n", 60), "Grid size"), 10), 120))
    dg, ag, Z = interplanetary.porkchop(dep, arr, w_dep, w_arr, n_dep=n, n_arr=n)
    best = interplanetary.best_transfer(dg, ag, Z)
    if best:
        best["dep_iso"] = jd_to_iso(best["jd_departure"])
        best["arr_iso"] = jd_to_iso(best["jd_arrival"])
    return {"dep": [jd_to_iso(j) for j in dg], "arr": [jd_to_iso(j) for j in ag],
            "Z": Z, "best": best, "count": int(np.isfinite(Z).sum())}


def api_satellites(req):
    groups = req.get("groups", ",".join(satellites.DEFAULT_GROUPS))
    if not isinstance(groups, str):
        raise ValueError("Choose the satellite groups to show.")
    groups = [g for g in groups.split(",") if g in satellites.GROUPS]
    return satellites.satellite_table(groups, refresh=req.get("refresh") == "1")


def api_satellite_groups(_req=None):
    return {"groups": [{"key": k, "label": v[0], "color": v[1],
                        "default": k in satellites.DEFAULT_GROUPS}
                       for k, v in satellites.GROUPS.items()]}


_SOURCES = {"time": 0.0, "data": None}
_SOURCE_SITES = (("celestrak", "https://celestrak.org/"), ("jpl", "https://ssd-api.jpl.nasa.gov/"))


def _reachable(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LambertStudio"})
        with urllib.request.urlopen(req, timeout=3):
            return True
    except urllib.error.HTTPError:
        return True                      # the server answered
    except Exception:
        return False


def api_sources(_req=None):
    """What the start page shows: which data sources are available right
    now (checked in parallel, remembered for five minutes) and a few counts."""
    if _SOURCES["data"] is None or time.time() - _SOURCES["time"] > 300:
        found = {}
        threads = [threading.Thread(target=lambda k=k, u=u: found.__setitem__(k, _reachable(u)))
                   for k, u in _SOURCE_SITES]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        _SOURCES.update(time=time.time(), data=found)
    return {"online": _SOURCES["data"], "ephemeris": ephemeris.status(),
            "planets": len(planets.PLANET_ORDER), "satellite_groups": len(satellites.GROUPS)}


def api_neo(req):
    group = req.get("group", "pha")
    out = {"elements": None, "approaches": None, "errors": []}
    try:
        out["elements"] = asteroids.neo_elements(group, refresh=req.get("refresh") == "1")
    except RuntimeError as exc:
        out["errors"].append(str(exc))
    try:
        out["approaches"] = asteroids.close_approaches(refresh=req.get("refresh") == "1")
    except RuntimeError as exc:
        out["errors"].append(str(exc))
    return out


def api_flyby(req):
    des = req.get("des")
    if not isinstance(des, str) or not des.strip() or len(des) > 40 or not all(c.isalnum() or c in " -_()/" for c in des):
        raise ValueError("Choose an asteroid from the list.")
    jd = _float_arg(req, "jd", "Close-approach date", 2396760, 2506340)
    return asteroids.flyby_path(des.strip(), jd)


# The page pings while it is open and says "bye" when it closes; the
# desktop launcher uses this to know when to shut the server down.
HEARTBEAT = {"ping": 0.0, "bye": 0.0}


def api_ping(_req=None):
    HEARTBEAT["ping"] = time.time()
    return {}


def api_bye(_req=None):
    HEARTBEAT["bye"] = time.time()
    return {}


_page_log = logging.getLogger("page")


def api_log(req):
    """Errors from the page's JavaScript, written to the app log."""
    _page_log.error("%s", str(req.get("message", ""))[:4000])
    return {}


# ----------------------------------------------------------------------
# deep-space maneuvers, launchers, uncertainty
# ----------------------------------------------------------------------

def api_launchers(_req=None):
    return launchers.curves()


def api_route_dsm(req):
    target = req.get("target", "Jupiter")
    if target not in ("Mars", "Jupiter", "Saturn"):
        raise ValueError("Deep-space-burn routes are available to Mars, Jupiter and Saturn.")
    w0 = _jd_from_date(req.get("from"), "Launch window start")
    w1 = _jd_from_date(req.get("to"), "Launch window end")
    if w1 <= w0:
        raise ValueError("The launch window must end after it starts.")
    if w1 - w0 > 3 * 365.25:
        raise ValueError("Keep the launch window under 3 years for this route type.")
    max_years = _float_arg(req, "max_years", "Maximum trip time (years)", 1, 20) if req.get("max_years") else 8
    out = dsm.plan_dsm((w0, w1), target, bool(req.get("capture", True)), max_years * 365.25)
    for r in (out, out.get("direct")):
        if r:
            for e in r["events"]:
                e["iso"] = jd_to_iso(e["jd"])
    return out


def api_verify_route(req):
    """Fly a designed route (or a direct transfer) in full solar-system
    gravity, with trajectory-correction manoeuvres (nbody.py)."""
    raw = req.get("seq", [])
    if isinstance(raw, (list, tuple)):
        for p_ in raw:
            if p_ and (not isinstance(p_, str) or p_ not in planets.PLANET_ORDER):
                raise ValueError(f"Unknown planet '{p_}'.")
    seq = _planet_list(raw)
    jds_raw = req.get("jds", [])
    if not isinstance(jds_raw, (list, tuple)):
        raise ValueError("Give the route's planets and one date per planet.")
    jds = [_num(j, "Route date") for j in jds_raw]
    if len(seq) < 2 or len(jds) != len(seq):
        raise ValueError("Give the route's planets and one date per planet.")
    if not all(2396760 <= j <= 2506340 for j in jds):
        raise ValueError("Route dates must be between 1850 and 2150.")
    if any(b <= a for a, b in zip(jds, jds[1:])):
        raise ValueError("The dates must increase along the route.")
    legs = req.get("legs") or [{"revs": 0, "branch": 0}] * (len(seq) - 1)
    if not isinstance(legs, list) or len(legs) != len(seq) - 1 or not all(isinstance(L, dict) for L in legs):
        raise ValueError("The route's legs do not match its planets.")
    opts = [(int(_num(L.get("revs", 0), "Laps")), int(_num(L.get("branch", 0), "Branch"))) for L in legs]
    if any(not 0 <= r <= 3 or b not in (0, 1) for r, b in opts):
        raise ValueError("Each leg may loop the Sun 0 to 3 times, on branch 0 or 1.")
    capture = bool(req.get("capture", True))
    cost, det = flyby.evaluate(seq, jds, capture, flyby._StateCache(), opts, detail=True)
    if det is None:
        raise ValueError("This route could not be rebuilt for the check.")
    det.update(seq=seq, jds=jds, capture=capture,
               launch_dv=float(flyby._launch_dv(det["vinf_launch"], seq[0])))
    out = nbody.verify(det)
    for c in out["tcms"]:
        c["iso"] = jd_to_iso(c["jd"])
    for e in out["encounters"]:
        e["iso_planned"], e["iso_actual"] = jd_to_iso(e["jd_planned"]), jd_to_iso(e["jd_actual"])
    out["uncorrected"]["iso"] = jd_to_iso(out["uncorrected"]["jd"])
    return out


def api_uncertainty(req):
    station, obs = _observations(req)
    return uncertainty.monte_carlo(
        station, obs,
        sigma_angle_deg=_float_arg(req, "sigma_angle", "Angle error (deg)", 0, 5),
        sigma_range_km=_float_arg(req, "sigma_range", "Range error (km)", 0, 100),
        sigma_time_s=_float_arg(req, "sigma_time", "Timing error (s)", 0, 60),
        n=int(_float_arg(req, "n", "Number of samples", 100, 20000)),
        prograde=bool(req.get("prograde", True)))


ROUTES = {
    "/api/launchers": api_launchers,
    "/api/route_dsm": api_route_dsm,
    "/api/uncertainty": api_uncertainty,
    "/api/verify_route": api_verify_route,
    "/api/solve": api_solve,
    "/api/planets": api_planets,
    "/api/sources": api_sources,
    "/api/transfer": api_transfer,
    "/api/porkchop": api_porkchop,
    "/api/satellites": api_satellites,
    "/api/satellite_groups": api_satellite_groups,
    "/api/neo": api_neo,
    "/api/flyby": api_flyby,
    "/api/ephemeris": api_ephemeris,
    "/api/moon": api_moon,
    "/api/maneuver": api_maneuver,
    "/api/route": api_route,
    "/api/route_suggest": api_route_suggest,
    "/api/suggest_window": api_suggest_window,
    "/api/route_presets": api_route_presets,
    "/api/ping": api_ping,
    "/api/bye": api_bye,
    "/api/log": api_log,
}


# ----------------------------------------------------------------------
# HTTP plumbing
# ----------------------------------------------------------------------

class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kw):
        super().__init__(*args, directory=str(WEB_DIR), **kw)

    def log_message(self, fmt, *args):          # keep the terminal quiet
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _api(self, path, req):
        try:
            payload = {"ok": True, "data": _clean(ROUTES[path](req))}
            status = 200
        except (ValueError, KeyError, RuntimeError) as exc:
            msg = str(exc) if not isinstance(exc, KeyError) else f"Missing field {exc}"
            payload, status = {"ok": False, "error": msg}, 200
            # User-facing errors are normal, but log them so any unexpected
            # one can be traced afterwards.
            logging.getLogger("server").warning("%s -> %s (request: %s)", path, msg, str(req)[:300])
        except ArithmeticError:                   # overflow / division by zero in the maths
            logging.getLogger("server").warning("%s overflow:\n%s", path, traceback.format_exc())
            payload, status = {"ok": False, "error": "These values are too extreme to compute. "
                                                      "Try values closer to a real orbit or mission."}, 200
        except Exception as exc:                  # a bug, not a user error
            logging.getLogger("server").error("%s failed:\n%s", path, traceback.format_exc())
            payload, status = {"ok": False, "error": "Something in these inputs could not be computed "
                                                      f"({type(exc).__name__}). Check the values and try again."}, 500
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path in ROUTES:
            q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            return self._api(url.path, q)
        return super().do_GET()

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if url.path not in ROUTES:
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            req = {}
        if not isinstance(req, dict):
            req = {}
        return self._api(url.path, req)


class _Server(ThreadingHTTPServer):
    # On Windows, SO_REUSEADDR would let a second copy of the app bind the
    # same port and silently share it; without it, a busy port is an error
    # and the launcher picks another one.
    allow_reuse_address = os.name != "nt"


def start_server(port=0):
    """Start the server in a background thread; returns (server, url)."""
    server = _Server(("127.0.0.1", port), _Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


if __name__ == "__main__":
    srv, url = start_server(8765)
    print(f"Lambert Studio server running at {url}  (Ctrl+C to stop)")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
