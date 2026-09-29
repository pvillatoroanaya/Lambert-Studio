"""
Small download cache for the online data sources (CelesTrak, NASA/JPL).

Every download is saved to disk. A saved copy younger than `ttl` seconds
is reused without touching the network, which keeps the app fast and
respects the data providers' request limits. If the network is down, the
last saved copy is used however old it is, so the app keeps working
offline once it has been run online once.
"""

import json
import os
import pathlib
import time
import urllib.request

CACHE_DIR = pathlib.Path(os.environ.get("LOCALAPPDATA", pathlib.Path.home())) \
    / "LambertStudio" / "cache"

_USER_AGENT = "LambertStudio/1.0 (educational orbital mechanics project)"


def _path(name):
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    return CACHE_DIR / f"{safe}.json"


def get_json(url, name, ttl, refresh=False, timeout=30, parse=json.loads):
    """
    Return (data, info) for `url`, using the cache when possible.

    info is a dict: {"source": "cache" | "live" | "stale-cache",
                     "fetched": unix time of the data}.
    `parse` turns the downloaded text into the object to cache (JSON by
    default); it runs before anything is written, so a bad response
    never overwrites a good cached copy.
    """
    path = _path(name)
    cached = None
    if path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cached = None

    if cached is not None and not refresh and time.time() - cached["fetched"] < ttl:
        return cached["data"], {"source": "cache", "fetched": cached["fetched"]}

    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
        data = parse(text)
    except Exception as exc:
        if cached is not None:
            return cached["data"], {"source": "stale-cache", "fetched": cached["fetched"]}
        raise RuntimeError(f"Could not download {name} and no saved copy exists "
                           f"(are you offline?): {exc}") from exc

    now = time.time()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched": now, "data": data}), encoding="utf-8")
    return data, {"source": "live", "fetched": now}
