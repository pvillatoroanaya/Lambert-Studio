"""
Build the single-file deliverable.

The assignment asks for "a single .m or .py file". Developing a project
this size in one file is unworkable, and hand-copying a merged copy
guarantees it drifts out of sync -- so the single file is GENERATED from
the modules.

    python3 tools/build_single_file.py   ->   course/lambert_problem_solver.py

The generated script:
    * launches the GUI when run with no arguments
    * --selftest   runs the full validation suite
    * --report     prints a text report for the assignment data
    * --dashboard  writes the interactive HTML dashboard

Optional dependencies degrade gracefully: without plotly the dashboard
is unavailable but everything else works; without tkinter the GUI is
unavailable but --selftest, --report and --dashboard still work.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "src"                      # the modules that are merged
OUTPUT = ROOT / "course" / "lambert_problem_solver.py"

# Dependency order: every name a later module needs must already exist.
MODULES = [
    "constants",
    "time_utils",
    "coord_utils",
    "lambert_solver",
    "orbital_elements",
    "frames",
    "planets",
    "interplanetary",
    "viz",
    "report",
    "dashboard",
    "validation",
    "app",
]
LOCAL_NAMES = set(MODULES) | {"make_dashboard"}

# Sections that must not be executed when an optional dependency is
# absent, because they reference it at module level.
GUARDED = {
    "viz": "_HAS_PLOTLY",
    "dashboard": "_HAS_PLOTLY",
    "app": "_HAS_TK",
}

# Modules referenced elsewhere with a `module.` prefix. Once merged there
# are no module objects, so the prefix is stripped.
PREFIXED = ("viz", "frames", "planets")

HOISTED = {
    "import argparse", "import datetime", "import html", "import math",
    "import os", "import pathlib", "import queue", "import sys",
    "import threading", "import traceback", "import webbrowser",
    "import numpy as np",
    "import plotly.graph_objects as go",
    "from plotly.offline import get_plotlyjs",
}
HOISTED_PREFIXES = (
    "import tkinter as tk",
    "from tkinter import",
    "import customtkinter",
)

BANNER = '''"""
Lambert Studio -- single-file edition
=====================================

Orbit determination by solving Lambert's problem, from either

  (a) two topocentric observations (azimuth, elevation, range) taken
      from a ground station at two known times, or
  (b) two geocentric position vectors and the time of flight,

then presented in five reference frames (inertial, Earth-fixed,
perifocal, ground track and the observer's sky view), plus an
interplanetary mode in which the SAME solver designs planet-to-planet
transfers and porkchop plots.

USAGE
-----
    python3 lambert_problem_solver.py             # GUI
    python3 lambert_problem_solver.py --selftest  # validation suite
    python3 lambert_problem_solver.py --report    # text report
    python3 lambert_problem_solver.py --dashboard # interactive HTML

DEPENDENCIES
------------
    required : numpy
    dashboard: plotly            (pip install plotly)
    globe map: global-land-mask  (pip install global-land-mask, optional)
    GUI      : tkinter + customtkinter
               (tkinter ships with Python; on some Linux distributions
                install it with: sudo apt install python3-tk)

Everything degrades gracefully: a missing optional package disables
only the feature that needs it.

NOTE
----
This file is GENERATED from the modular sources by build_single_file.py.
Edit the modules, not this file.
"""
'''

HEADER = '''
import argparse
import datetime
import html
import math
import os
import pathlib
import queue
import sys
import threading
import traceback
import webbrowser

import numpy as np

try:
    import plotly.graph_objects as go
    from plotly.offline import get_plotlyjs
    _HAS_PLOTLY = True
except Exception:
    _HAS_PLOTLY = False

try:
    import tkinter as tk
    from tkinter import messagebox, filedialog
    _HAS_TK = True
except Exception:
    _HAS_TK = False

try:
    import customtkinter as ctk
    _HAS_CTK = True
except Exception:
    _HAS_CTK = False
'''

MAIN_BLOCK = '''

# ======================================================================
#  Entry point
# ======================================================================

STATION_DEFAULT = np.array([1344.143, 6068.601, 1429.311])


def _assignment_solution():
    """Solve the assignment's own case and return (solution, epoch JD)."""
    jd1 = julian_date(2023, 4, 2, 0, 30, 0.0)
    jd2 = julian_date(2023, 4, 2, 3, 0, 0.0)
    r1 = topocentric_to_geocentric(132.67, 32.44, 16945.450,
                                   STATION_DEFAULT, gmst_from_jd(jd1))
    r2 = topocentric_to_geocentric(123.08, 50.06, 37350.340,
                                   STATION_DEFAULT, gmst_from_jd(jd2))
    dt = time_of_flight(jd1, jd2)
    v1, v2, z = lambert_universal(r1, r2, dt)
    sol = dict(r1=r1, r2=r2, v1=v1, v2=v2, dt=dt, z=z,
               elems=state_to_elements(r1, v1), r_station=STATION_DEFAULT,
               mode="observations", prograde=True)
    return sol, jd1


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Lambert Studio -- orbit determination from two observations.")
    parser.add_argument("--selftest", action="store_true",
                        help="run the validation suite and exit")
    parser.add_argument("--report", action="store_true",
                        help="print a text report for the assignment data and exit")
    parser.add_argument("--dashboard", action="store_true",
                        help="write the interactive HTML dashboard and exit")
    parser.add_argument("-o", "--output", default="lambert_dashboard.html",
                        help="output path for --dashboard")
    args = parser.parse_args(argv)

    if args.selftest:
        return run_validation()

    if args.report:
        sol, _ = _assignment_solution()
        print(build_report(sol))
        return 0

    if args.dashboard:
        if not _HAS_PLOTLY:
            print("The dashboard needs plotly.  Install it with:\\n"
                  "    pip install plotly", file=sys.stderr)
            return 2
        sol, jd1 = _assignment_solution()
        tr = transfer("Earth", "Mars",
                      julian_date(2026, 11, 1, 0, 0, 0.0),
                      julian_date(2027, 8, 20, 0, 0, 0.0))
        dg, ag, Z = porkchop("Earth", "Mars",
                             (julian_date(2026, 8, 1, 0, 0, 0.0),
                              julian_date(2027, 3, 1, 0, 0, 0.0)),
                             (julian_date(2027, 3, 1, 0, 0, 0.0),
                              julian_date(2028, 2, 1, 0, 0, 0.0)),
                             n_dep=45, n_arr=45)
        pork = (dg, ag, Z, best_transfer(dg, ag, Z), "Earth", "Mars")
        path = build_dashboard(sol, args.output, jd0=jd1,
                               interplanetary=tr, porkchop_data=pork)
        print(f"Dashboard written to {os.path.abspath(path)}")
        return 0

    if not _HAS_TK:
        print("tkinter is not available, so the GUI cannot start.\\n"
              "Install it (e.g. 'sudo apt install python3-tk'), or use:\\n"
              "    python3 lambert_problem_solver.py --dashboard\\n"
              "    python3 lambert_problem_solver.py --report\\n"
              "    python3 lambert_problem_solver.py --selftest",
              file=sys.stderr)
        return 2

    LambertStudio().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


_PROBE_BLOCK = re.compile(
    # The `except` line may carry a trailing comment, so it is matched to
    # end-of-line rather than to a colon.
    r'^try:\n(?:[ \t]+.*\n|\n)+?except[^\n]*\n(?:[ \t]+.*\n|\n)+?(?=\S|\Z)',
    re.M)


def _drop_probe_blocks(src):
    """
    Remove whole `try: import X; _HAS_X = True / except: _HAS_X = False`
    blocks. The header performs these probes once, and deleting only the
    inner lines would leave an empty `try:` that will not parse.
    """
    def repl(m):
        return "" if "_HAS_" in m.group(0) else m.group(0)
    return _PROBE_BLOCK.sub(repl, src)


def strip_module(name, src):
    """Remove project-local imports, the module demo block, and imports
    that the generated header already provides."""
    src = re.split(r'^if __name__ == ["\']__main__["\']:', src, flags=re.M)[0]
    src = _drop_probe_blocks(src)

    lines = src.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        m = re.match(r'(?:from|import)\s+([A-Za-z_][\w]*)', stripped)
        drop = bool(m and m.group(1) in LOCAL_NAMES)
        if not drop and (stripped in HOISTED or stripped.startswith(HOISTED_PREFIXES)):
            drop = True

        if drop:
            indent = line[:len(line) - len(line.lstrip())]
            # A parenthesised import spans several lines; consume them
            # all, or the continuation lines are left orphaned and the
            # generated file will not parse.
            depth = line.count("(") - line.count(")")
            i += 1
            while depth > 0 and i < len(lines):
                depth += lines[i].count("(") - lines[i].count(")")
                i += 1
            # An indented import may have been the entire body of a
            # `try:` or `if:` block (the project imports some optional
            # modules lazily). Leaving a `pass` keeps the block valid;
            # a stray `pass` anywhere else is harmless.
            if indent:
                out.append(indent + "pass")
            continue

        # The optional-dependency probes are handled once, in the header.
        if re.match(r'_HAS_(CTK|TK|PLOTLY)\s*=', stripped):
            i += 1
            continue

        out.append(line)
        i += 1

    body = "\n".join(out)
    # Drop try/except scaffolding left empty by removing those probes,
    # and strip `module.` prefixes that no longer resolve once merged.
    body = re.sub(r'\btry:\s*\n\s*\n(\s*)except Exception:.*?\n', '', body)
    body = re.sub(r'\b(' + "|".join(PREFIXED) + r')\.(?=[A-Za-z_])', '', body)
    return body.rstrip() + "\n"


def build():
    parts = [BANNER, HEADER]

    for name in MODULES:
        src = (HERE / f"{name}.py").read_text(encoding="utf-8")
        body = strip_module(name, src)

        guard = GUARDED.get(name)
        if guard:
            indented = "\n".join(("    " + ln) if ln.strip() else ln
                                  for ln in body.splitlines())
            body = (f"if {guard}:\n"
                    f"    # Defined only when the optional dependency is present.\n"
                    + indented)

        parts.append(
            "\n\n"
            "# " + "=" * 68 + "\n"
            f"#  {name}.py\n"
            "# " + "=" * 68 + "\n\n"
            + body
        )

    parts.append(MAIN_BLOCK)
    OUTPUT.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes, "
          f"{len(OUTPUT.read_text(encoding='utf-8').splitlines()):,} lines)")


if __name__ == "__main__":
    build()
