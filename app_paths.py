"""
Where Lambert Studio keeps its data (downloads, logs, the ephemeris file).

One folder in the user's home directory: C:\\Users\\<name>\\.lambert_studio

Not under AppData\\Local on purpose: when Python comes from the Microsoft
Store, Windows silently redirects everything Python writes there into a
hidden per-app folder, while other programs (PowerShell, Edge) see the
real one -- so files would end up split across two places.
"""

import pathlib

DATA_DIR = pathlib.Path.home() / ".lambert_studio"
CACHE_DIR = DATA_DIR / "cache"
LOG_DIR = DATA_DIR / "logs"
EPHEMERIS_DIR = DATA_DIR / "ephemeris"
EDGE_PROFILE_DIR = DATA_DIR / "edge-profile"
