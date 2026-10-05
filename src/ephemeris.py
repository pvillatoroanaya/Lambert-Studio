"""
High-accuracy positions of the planets, Sun and Moon from NASA/JPL's
DE440s ephemeris (the numerical integration JPL uses for mission design),
read with the Skyfield library.

This replaces the approximate Keplerian formulas of planets.py wherever
it is available. If Skyfield or the DE440s file is missing, every
function here returns None and callers fall back to planets.py, so the
project still runs on a bare install.

Frames:
  * planets: heliocentric, ecliptic J2000, AU and AU/day (as planets.py)
  * Moon, Sun: geocentric, ICRF (= the app's ECI J2000 frame), km, km/s
"""

import os
import pathlib
import threading

import numpy as np

from app_paths import EPHEMERIS_DIR as EPH_DIR
EPH_FILE = "de440s.bsp"
EPH_URL = "https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de440s.bsp"

# DE440s holds Mercury and Venus themselves, and barycentres for the
# other systems (the planet-barycentre offset is at most a few km for
# Mars and irrelevant at AU scale for the giants).
TARGETS = {
    "Mercury": "mercury", "Venus": "venus", "Earth": "earth",
    "Mars": "mars barycenter", "Jupiter": "jupiter barycenter",
    "Saturn": "saturn barycenter", "Uranus": "uranus barycenter",
    "Neptune": "neptune barycenter",
}

# UTC -> TT offset (TAI-UTC = 37 s since 2017, TT-TAI = 32.184 s).
_TT_MINUS_UTC_DAYS = (37.0 + 32.184) / 86400.0

_lock = threading.Lock()
# The web server answers requests on several threads at once. Skyfield /
# jplephem read the ephemeris file lazily and do not promise to be safe
# for simultaneous reads, so reads are serialised (each takes ~1 ms).
_read_lock = threading.Lock()
_state = {"loaded": False, "eph": None, "ts": None, "frame": None, "error": None}


def _load(download=False):
    with _lock:
        if _state["loaded"]:
            return _state["eph"]
        try:
            from skyfield.api import Loader
            from skyfield.framelib import ecliptic_J2000_frame
            import sys
            folder = EPH_DIR
            bundled = pathlib.Path(getattr(sys, "_MEIPASS", "")) / "ephemeris"
            if not (folder / EPH_FILE).exists() and (bundled / EPH_FILE).exists():
                folder = bundled                     # copy packaged inside the .exe
            if not (folder / EPH_FILE).exists() and not download:
                raise FileNotFoundError(f"{folder / EPH_FILE} not found")
            folder.mkdir(parents=True, exist_ok=True)
            loader = Loader(str(folder), verbose=False)
            _state["eph"] = loader(EPH_FILE)
            _state["ts"] = loader.timescale(builtin=True)
            _state["frame"] = ecliptic_J2000_frame
        except Exception as exc:              # no skyfield, no file, bad file
            _state["error"] = str(exc)
            _state["eph"] = None
        _state["loaded"] = True
        return _state["eph"]


def available():
    return _load() is not None


def status():
    _load()
    return {"available": _state["eph"] is not None, "source": "NASA/JPL DE440s",
            "error": _state["error"]}


def _t(jd):
    return _state["ts"].tt_jd(np.asarray(jd, float) + _TT_MINUS_UTC_DAYS)


def planet_states(name, jd):
    """
    Heliocentric ecliptic J2000 position [AU] and velocity [AU/day] of a
    planet at one or many UTC Julian Dates. Returns (r, v) shaped (3,)
    or (n, 3), or None if the ephemeris is unavailable.
    """
    eph = _load()
    if eph is None:
        return None
    with _read_lock:
        t = _t(jd)
        target = TARGETS.get(name) or {"Moon": "moon"}[name]     # the Moon too (full-gravity simulations)
        rel = (eph[target] - eph["sun"]).at(t)
        r, v = rel.frame_xyz_and_velocity(_state["frame"])
    return r.au.T, v.au_per_d.T


def planet_state(name, jd):
    """Single-date state in planets.py's units: r [km], v [km/s]."""
    from constants import AU
    out = planet_states(name, float(jd))
    if out is None:
        return None
    r, v = out
    return r * AU, v * AU / 86400.0


def moon_geocentric(jd):
    """Moon position [km] and velocity [km/s] relative to Earth, ICRF."""
    eph = _load()
    if eph is None:
        return None
    with _read_lock:
        rel = (eph["moon"] - eph["earth"]).at(_t(jd))
        return rel.position.km.T, rel.velocity.km_per_s.T


def sun_geocentric(jd):
    """Sun position [km] relative to Earth, ICRF."""
    eph = _load()
    if eph is None:
        return None
    with _read_lock:
        return (eph["sun"] - eph["earth"]).at(_t(jd)).position.km.T


if __name__ == "__main__":
    from time_utils import julian_date
    import planets
    from constants import AU
    jd = julian_date(2026, 9, 29, 0, 0, 0.0)
    print(status())
    for name in planets.PLANET_ORDER:
        r_de, _ = planet_state(name, jd)
        r_st, _ = planets.planet_state(name, jd)
        print(f"{name:<8} DE440s vs Standish: {np.linalg.norm(r_de - r_st) / AU:.5f} AU apart")
    m, _ = moon_geocentric(jd)
    print(f"Moon distance {np.linalg.norm(m):,.0f} km")
