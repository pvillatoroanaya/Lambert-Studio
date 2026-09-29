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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
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


@pytest.mark.parametrize("seq", [["Earth"], ["Earth", "Pluto"]])
def test_route_rejects_bad_input(api, seq):
    js = api("/api/route", {"seq": seq, "from": "2030-01-01", "to": "2031-01-01", "max_years": 5})
    assert not js["ok"] and js["error"]


def test_maneuver_and_perturbation(api):
    m = api("/api/maneuver", {"kind": "hohmann", "mass": 1000, "isp": 320, "alt1": 300, "alt2": 35786,
                              "i1": 0, "i2": 0, "altb": 100000})
    assert m["ok"] and m["data"]["total_dv"] == pytest.approx(3.893, abs=0.002)
    p = api("/api/perturb", {"source": "elements", "days": 2, "j2": True, "drag": False, "cd": 2.2, "area": 10,
                             "mass": 1000, "alt_p": 700, "alt_a": 700, "i": 98.19, "raan": 0, "argp": 0})
    assert p["ok"] and p["data"]["summary"]["raan_rate_analytic"] == pytest.approx(0.9856, rel=0.01)


def test_satellites_online(api):
    js = api("/api/satellites?groups=stations")
    if not js["ok"] or not js["data"]["sats"]:
        pytest.skip("no network and no saved satellite data")
    assert any("ISS" in s[0] for s in js["data"]["sats"])
