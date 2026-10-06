"""
The web server's JSON API, end to end: every endpoint the interface uses
answers correctly, and bad inputs get a clear message instead of a crash.
Network-dependent endpoints (satellites, asteroids) are skipped offline.
"""

import json
import pathlib
import sys
import urllib.request

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import studio_server  # noqa: E402


@pytest.fixture(scope="module")
def api():
    server, url = studio_server.start_server(0)

    def call(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url.rstrip("/") + path, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.loads(r.read())       # strict JSON: fails on NaN/Infinity
    yield call
    server.shutdown()


def test_page_is_served(api):
    js = api("/api/planets")
    assert js["ok"] and len(js["data"]["order"]) == 8


def test_solve_assignment(api):
    js = api("/api/solve", {
        "mode": "observations", "prograde": True, "station": ["1344.143", "6068.601", "1429.311"],
        "obs1": {"date": "2023-04-02", "time": "00:30:00", "az": "132.67", "el": "32.44", "rng": "16945.450"},
        "obs2": {"date": "2023-04-02", "time": "03:00:00", "az": "123.08", "el": "50.06", "rng": "37350.340"}})
    assert js["ok"]
    assert js["data"]["elements"]["a"] == pytest.approx(28184.19, abs=0.01)
    assert js["data"]["elements"]["e"] == pytest.approx(0.768209, abs=1e-6)


@pytest.mark.parametrize("body, message", [
    ({"mode": "vectors", "r1": [0, 0, 0], "r2": [1, 2, 3], "tof": 10}, "zero vector"),
    ({"mode": "vectors", "r1": [5000, 10000, 2100], "r2": [-14600, 2500, 7000], "tof": -5}, "positive"),
    ({"mode": "vectors", "r1": ["x", 1, 1], "r2": [1, 2, 3], "tof": 10}, "number"),
])
def test_solve_rejects_bad_input(api, body, message):
    js = api("/api/solve", body)
    assert not js["ok"] and message in js["error"]


def test_transfer_and_explanation(api):
    js = api("/api/transfer", {"dep": "Earth", "arr": "Mars", "dep_date": "2026-11-01", "arr_date": "2027-08-20"})
    assert js["ok"]
    d = js["data"]
    assert 5 < d["c3"] < 40
    assert d["explain"]["synodic_days"] == pytest.approx(780, abs=5)


def test_porkchop(api):
    js = api("/api/porkchop", {"dep": "Earth", "arr": "Mars", "dep_start": "2026-08-01", "dep_end": "2027-03-01",
                               "arr_start": "2027-03-01", "arr_end": "2028-02-01", "n": 40})
    assert js["ok"] and js["data"]["best"]["c3"] < 12


def test_suggest_window_finds_2026_mars(api):
    js = api("/api/suggest_window", {"dep": "Earth", "arr": "Mars", "after": "2026-09-30"})
    assert js["ok"]
    assert js["data"]["departure_iso"].startswith("2026-1")      # Oct/Nov 2026 window


def test_route_voyager(api):
    js = api("/api/route", {"seq": ["Earth", "Jupiter", "Saturn"], "from": "1977-01-01", "to": "1978-06-30",
                            "max_years": 3.5, "capture": False})
    assert js["ok"]
    d = js["data"]
    assert d["total_dv"] < d["direct"]["total_dv"]
    assert len(d["track_au"]) == d["legs"][-1]["end"]


def test_route_suggestions_mars(api):
    """The suggestion search must find the late-2026 Mars window, with the
    optimum inside the recommended launch window."""
    js = api("/api/route_suggest", {"dep": "Earth", "arr": "Mars", "capture": True, "from_year": 2026, "years": 6})
    assert js["ok"]
    best = js["data"]["options"][0]
    assert best["seq"] == ["Earth", "Mars"]
    assert best["iso"][0].startswith("2026-1")
    assert best["window_iso"][0] <= best["iso"][0] <= best["window_iso"][1]


def test_route_suggestions_jupiter_prefer_flybys(api):
    """For Jupiter, a Venus/Earth flyby route must beat the direct flight."""
    js = api("/api/route_suggest", {"dep": "Earth", "arr": "Jupiter", "capture": True, "from_year": 2026, "years": 12})
    assert js["ok"]
    opts = js["data"]["options"]
    direct = min(o["total_dv"] for o in opts if len(o["seq"]) == 2)
    assert opts[0]["total_dv"] < direct and "Venus" in opts[0]["seq"]


@pytest.mark.parametrize("seq", [["Earth"], ["Earth", "Pluto"]])
def test_route_rejects_bad_input(api, seq):
    js = api("/api/route", {"seq": seq, "from": "2030-01-01", "to": "2031-01-01", "max_years": 5})
    assert not js["ok"] and js["error"]


def test_maneuver(api):
    m = api("/api/maneuver", {"kind": "hohmann", "mass": 1000, "isp": 320, "alt1": 300, "alt2": 35786,
                              "i1": 0, "i2": 0, "altb": 100000})
    assert m["ok"] and m["data"]["total_dv"] == pytest.approx(3.893, abs=0.002)


def test_satellites_online(api):
    js = api("/api/satellites?groups=stations")
    if not js["ok"] or not js["data"]["sats"]:
        pytest.skip("no network and no saved satellite data")
    assert any("ISS" in s[0] for s in js["data"]["sats"])


# ----------------------------------------------------------------------
# deep-space burns, launchers, uncertainty
# ----------------------------------------------------------------------

def test_launchers(api):
    js = api("/api/launchers")
    assert js["ok"] and "Atlas V 551" in js["data"]["curves"]


def test_route_dsm_juno(api):
    js = api("/api/route_dsm", {"target": "Jupiter", "from": "2011-08-05", "to": "2011-08-26", "capture": True})
    assert js["ok"]
    d = js["data"]
    kinds = [e["kind"] for e in d["events"]]
    assert kinds == ["launch", "dsm", "flyby", "arrival"]
    assert d["events"][2]["iso"].startswith("2013-")          # Earth flyby in 2013, like Juno
    assert len(d["track_au"]) == d["legs"][-1]["end"]


def test_uncertainty(api):
    js = api("/api/uncertainty", {
        "station": ["1344.143", "6068.601", "1429.311"],
        "obs1": {"date": "2023-04-02", "time": "00:30:00", "az": "132.67", "el": "32.44", "rng": "16945.450"},
        "obs2": {"date": "2023-04-02", "time": "03:00:00", "az": "123.08", "el": "50.06", "rng": "37350.340"},
        "sigma_angle": 0.01, "sigma_range": 0.015, "sigma_time": 0.001, "n": 2000})
    assert js["ok"]
    d = js["data"]
    assert d["elements"]["a"]["nominal"] == pytest.approx(28184.19, abs=0.01)
    assert d["sensitivity"]["angle"]["a_std"] > d["sensitivity"]["range"]["a_std"]


# ----------------------------------------------------------------------
# high-fidelity physics: full solar-system gravity
# ----------------------------------------------------------------------

def test_verify_route_mars(api):
    js = api("/api/verify_route", {"seq": ["Earth", "Mars"], "jds": [2461345.5, 2461637.5], "capture": True})
    assert js["ok"]
    d = js["data"]
    assert d["uncorrected"]["miss_km"] > 1e4
    assert abs(d["encounters"][-1]["alt_actual"] - d["encounters"][-1]["alt_planned"]) < 10
    assert abs(d["total_dv"] - d["design_total_dv"]) < 0.1


@pytest.mark.parametrize("body, message", [
    ({"seq": ["Earth"], "jds": [2461000]}, "one date per planet"),
    ({"seq": ["Earth", "Mars"], "jds": [2461000, 2460000]}, "increase"),
    ({"seq": ["Earth", "Pluto"], "jds": [2461000, 2461300]}, "Unknown planet"),
])
def test_verify_route_rejects_bad_input(api, body, message):
    js = api("/api/verify_route", body)
    assert not js["ok"] and message in js["error"]


# ----------------------------------------------------------------------
# robustness: rare values get a clear message, never an internal error
# (found by tests/fuzz_api.py; the full sweep runs outside pytest)
# ----------------------------------------------------------------------

_OBS = {"station": ["1344.143", "6068.601", "1429.311"],
        "obs1": {"date": "2023-04-02", "time": "00:30:00", "az": "132.67", "el": "32.44", "rng": "16945.450"},
        "obs2": {"date": "2023-04-02", "time": "03:00:00", "az": "123.08", "el": "50.06", "rng": "37350.340"}}


def _with(base, **changes):
    import copy
    req = copy.deepcopy(base)
    req.update(changes)
    return req


@pytest.mark.parametrize("path, body", [
    ("/api/solve", _with(_OBS, station=["nan", 6068, 1429])),
    ("/api/solve", _with(_OBS, station=[1e9, 0, 0])),
    ("/api/solve", _with(_OBS, station=None)),
    ("/api/solve", _with(_OBS, obs1="")),
    ("/api/solve", _with(_OBS, obs2={"date": "2023-02-30", "time": "99:99:99", "az": 1, "el": 1, "rng": 1})),
    ("/api/solve", {"mode": "vectors", "r1": [5000, 10000, 2100], "r2": [-14600, 2500, 7000], "tof": 1e-12}),
    ("/api/solve", {"mode": "vectors", "r1": "inf", "r2": [1, 2, 3], "tof": 10}),
    ("/api/solve", {"mode": "vectors", "r1": [1e308, 0, 0], "r2": [1, 2, 3], "tof": 10}),
    ("/api/uncertainty", _with(_OBS, sigma_angle=0.01, sigma_range=0.015, sigma_time=0.001, n=300,
                               obs1={**_OBS["obs1"], "az": 1e9})),
    ("/api/maneuver", {"kind": "circularize", "mass": 1000, "isp": 320, "r": [{}, 0, 0], "v": [0, 9, 0]}),
    ("/api/maneuver", {"kind": "hohmann", "mass": "inf", "isp": 320, "alt1": 300, "alt2": 35786, "i1": 0, "i2": 0}),
    ("/api/transfer", {"dep": [], "arr": "Mars", "dep_date": "2026-11-01", "arr_date": "2027-08-20"}),
    ("/api/porkchop", {"dep": "Earth", "arr": "Mars", "dep_start": "2026-08-01", "dep_end": "2027-03-01",
                       "arr_start": "2027-03-01", "arr_end": "2028-02-01", "n": None}),
    ("/api/route", {"seq": 5, "from": "2026-06-01", "to": "2027-03-01", "max_years": 2}),
    ("/api/verify_route", {"seq": ["Earth", "Mars"], "jds": [None, 2461637.5]}),
    ("/api/ephemeris", {"start": "nan", "step": 1, "n": 10}),
    ("/api/satellites", {"groups": None}),
    ("/api/flyby", {"des": {}, "jd": "inf"}),
])
def test_rare_values_get_a_clear_message(api, path, body):
    js = api(path, body)          # a result (e.g. an azimuth that wraps round) or a clear message
    if not js["ok"]:
        assert "Internal error" not in js["error"] and "could not be computed" not in js["error"]


@pytest.mark.parametrize("des, jd", [("99942", 2462240.4), ("2017 TE2", 2461312.869431261)])
def test_flyby_path_numbered_and_provisional(api, des, jd):
    """Horizons needs '99942;' for a numbered asteroid and 'DES=2017 TE2;'
    for a provisional one; both must give the close-approach path."""
    js = api(f"/api/flyby?des={urllib.request.quote(des)}&jd={jd}")
    if not js["ok"] and ("offline" in js["error"] or "download" in js["error"]):
        pytest.skip("no network and no saved copy")
    assert js["ok"] and len(js["data"]["r"]) > 100
    if des == "99942":                     # Apophis, 13 April 2029: about 38,000 km from the Earth's centre
        closest = min(sum(c * c for c in p) ** 0.5 for p in js["data"]["r"])
        assert 37000 < closest < 39500
