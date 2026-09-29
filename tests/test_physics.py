"""
The validation suite (validation.py) as pytest tests: one test per group
of checks, so a failure points straight at the area that broke.

    python -m pytest            # everything
    python -m pytest -k lambert # just the Lambert tests
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import validation as V  # noqa: E402

GROUPS = [
    V.test_stumpff, V.test_curtis_elements, V.test_curtis_lambert, V.test_invariants,
    V.test_multirev_lambert, V.test_frames, V.test_planets, V.test_interplanetary,
    V.test_ephemeris, V.test_maneuvers, V.test_perturbations, V.test_gravity_assists,
    V.test_repeat_flybys, V.test_satellite_model,
]


@pytest.mark.parametrize("group", GROUPS, ids=lambda f: f.__name__.removeprefix("test_"))
def test_validation_group(group):
    V._RESULTS.clear()
    try:
        group()
    except ImportError as exc:
        pytest.skip(f"optional package not installed: {exc.name}")
    failed = [f"{name}: {detail}" for name, ok, detail in V._RESULTS if not ok]
    assert V._RESULTS, "the group ran no checks"
    assert not failed, "\n".join(failed)
