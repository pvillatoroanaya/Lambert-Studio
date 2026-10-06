"""
Robustness sweep of the JSON API: every field of every endpoint is replaced,
one at a time, by a rare value (empty, text, NaN, infinity, huge, tiny,
negative, wrong type...). For each call the result must be either a normal
answer or a clear user-facing error -- never an internal error, never
non-JSON output (NaN/Infinity), never a hang.

    python tests/fuzz_api.py            # all endpoints
    python tests/fuzz_api.py solve maneuver   # only these

Each endpoint runs in its own worker process with a watchdog, so a hang is
reported (and the worker restarted) instead of freezing the sweep.
Not part of the pytest run: a full sweep takes several minutes.
"""

import copy
import json
import multiprocessing as mp
import pathlib
import sys
import time

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"

RARE = ["", None, "abc", "nan", "inf", "-inf", float("nan"), float("inf"), 0, -1, -1e9,
        1e9, 1e308, 1e-12, "1e400", [], {}, True, "  ", "2023-02-30", "99:99:99"]

OBS = {
    "station": ["1344.143", "6068.601", "1429.311"],
    "obs1": {"date": "2023-04-02", "time": "00:30:00", "az": "132.67", "el": "32.44", "rng": "16945.450"},
    "obs2": {"date": "2023-04-02", "time": "03:00:00", "az": "123.08", "el": "50.06", "rng": "37350.340"},
}

BASE = {
    "solve": dict(OBS, mode="observations", prograde=True),
    "solve_vectors": {"mode": "vectors", "r1": [5000, 10000, 2100], "r2": [-14600, 2500, 7000], "tof": 3600},
    "maneuver": {"kind": "hohmann", "mass": 1000, "isp": 320, "alt1": 300, "alt2": 35786, "i1": 0, "i2": 0, "altb": 100000},
    "maneuver_bi": {"kind": "bielliptic", "mass": 1000, "isp": 320, "alt1": 300, "alt2": 35786, "i1": 0, "i2": 0, "altb": 100000},
    "maneuver_plane": {"kind": "plane", "mass": 1000, "isp": 320, "alt1": 300, "i1": 0, "i2": 28.5},
    "maneuver_circ": {"kind": "circularize", "mass": 1000, "isp": 320, "where": "apogee",
                      "r": [7000, 0, 0], "v": [0, 9.0, 0.5]},
    "transfer": {"dep": "Earth", "arr": "Mars", "dep_date": "2026-11-01", "arr_date": "2027-08-20"},
    "porkchop": {"dep": "Earth", "arr": "Mars", "dep_start": "2026-08-01", "dep_end": "2027-03-01",
                 "arr_start": "2027-03-01", "arr_end": "2028-02-01", "n": 20},
    "suggest_window": {"dep": "Earth", "arr": "Mars", "after": "2026-09-30"},
    "route": {"seq": ["Earth", "Mars"], "from": "2026-06-01", "to": "2027-03-01", "max_years": 2, "capture": True},
    "route_suggest": {"dep": "Earth", "arr": "Mars", "capture": True, "from_year": 2026, "years": 2},
    "route_dsm": {"target": "Jupiter", "from": "2011-08-05", "to": "2011-08-26", "capture": True},
    "verify_route": {"seq": ["Earth", "Mars"], "jds": [2461345.5, 2461637.5], "capture": True},
    "uncertainty": dict(OBS, sigma_angle=0.01, sigma_range=0.015, sigma_time=0.001, n=300),
    "ephemeris": {"start": 2461000, "step": 1, "n": 10},
    "moon": {"start": 2461000, "step": 0.5, "n": 10},
    "satellites": {"groups": "stations"},
    "neo": {"group": "pha"},
    "flyby": {"des": "99942", "jd": 2462240.4},
    "log": {"message": "fuzz"},
}
ROUTE_OF = {k: "/api/" + k.split("_vectors")[0].split("_bi")[0].split("_plane")[0].split("_circ")[0]
            for k in BASE}
ROUTE_OF["route_suggest"] = "/api/route_suggest"
ROUTE_OF["route_dsm"] = "/api/route_dsm"
ROUTE_OF["verify_route"] = "/api/verify_route"
ROUTE_OF["suggest_window"] = "/api/suggest_window"

TIMEOUT = {"route_suggest": 120, "route": 90, "route_dsm": 120, "verify_route": 120, "porkchop": 60}


def leaves(obj, path=()):
    """Every replaceable position: dict values and list items, recursively."""
    yield path                                    # the container itself too
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from leaves(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from leaves(v, path + (i,))


def mutate(base, path, value):
    req = copy.deepcopy(base)
    if not path:
        return value
    cur = req
    for p in path[:-1]:
        cur = cur[p]
    cur[path[-1]] = value
    return req


def cases(name):
    base = BASE[name]
    yield ("baseline", base)
    for path in leaves(base):
        for v in RARE:
            yield ("/".join(map(str, path)) + " = " + repr(v), mutate(base, path, v))
    if isinstance(base, dict):
        for k in base:                            # a missing field
            req = copy.deepcopy(base)
            del req[k]
            yield (f"{k} missing", req)


def worker(name, start, q):
    sys.path.insert(0, str(SRC))
    import logging
    logging.disable(logging.CRITICAL)
    import studio_server as s
    fn = s.ROUTES[ROUTE_OF[name]]
    for i, (label, req) in enumerate(cases(name)):
        if i < start:
            continue
        q.put(("start", i, label))
        t = time.time()
        try:
            if not isinstance(req, dict):
                raise ValueError("not an object")    # the server turns non-objects into {}
            out = s._clean(fn(req))
            json.dumps(out, allow_nan=False)
            kind = "ok"
            msg = ""
        except (ValueError, KeyError, RuntimeError) as e:
            kind, msg = "user-error", str(e)[:120]
        except ArithmeticError as e:                # the server answers "too extreme to compute"
            kind, msg = "extreme", f"{type(e).__name__}: {str(e)[:120]}"
        except Exception as e:                      # what the server reports as Internal error
            kind, msg = "INTERNAL", f"{type(e).__name__}: {str(e)[:150]}"
        q.put(("done", i, label, kind, msg, time.time() - t))
    q.put(("end",))


def run(name):
    limit = TIMEOUT.get(name, 30)
    total = sum(1 for _ in cases(name))
    results, start = [], 0
    while start < total:
        q = mp.Queue()
        p = mp.Process(target=worker, args=(name, start, q), daemon=True)
        p.start()
        current = None
        while True:
            try:
                msg = q.get(timeout=limit + 60 if current is None else limit)
            except Exception:
                label = current[2] if current else "?"
                results.append((label, "HANG", f"no answer after {limit} s", limit))
                p.kill()
                start = (current[1] + 1) if current else total
                break
            if msg[0] == "start":
                current = msg
            elif msg[0] == "done":
                results.append((msg[2], msg[3], msg[4], msg[5]))
                current = None
            else:
                start = total
                break
        p.join(timeout=5)
    return results


def main():
    names = sys.argv[1:] or list(BASE)
    bad_total = 0
    for name in names:
        t = time.time()
        res = run(name)
        bad = [r for r in res if r[1] in ("INTERNAL", "HANG")]
        slow = [r for r in res if r[1] != "HANG" and r[3] > 10]
        extreme = sum(1 for r in res if r[1] == "extreme")
        base_kind = res[0][1] if res else "?"
        print(f"{name:16s} {len(res):4d} calls  baseline={base_kind:10s} problems={len(bad):3d}  "
              f"slow={len(slow):2d}  extreme={extreme:3d}  ({time.time() - t:.0f} s)", flush=True)
        for label, kind, msg, dt in bad + slow:
            print(f"    {kind:10s} {dt:6.1f}s  {label:40s} {msg}", flush=True)
        bad_total += len(bad)
    print(f"\n{bad_total} problems")
    return 1 if bad_total else 0


if __name__ == "__main__":
    sys.exit(main())
