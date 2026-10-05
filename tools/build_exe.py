"""
Build a stand-alone Windows version of Lambert Studio (no Python needed).

    python tools/build_exe.py

Output: %USERPROFILE%\\LambertStudioBuild\\dist\\LambertStudio\\LambertStudio.exe
and a zip of that folder, ready to share. Built with PyInstaller.

What goes in: the Python physics and server, the web interface (web/),
the Skyfield timescale data, and the NASA/JPL DE440s ephemeris if it has
been downloaded. What stays out: the Qt window (PySide6), Tk and Plotly's
Python package, which the packaged app does not use -- it opens in Edge.
"""

import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
HERE = ROOT / "src"
OUT = pathlib.Path.home() / "LambertStudioBuild"


def main():
    try:
        import PyInstaller.__main__ as pyinstaller
    except ImportError:
        sys.exit("PyInstaller is not installed:  python -m pip install pyinstaller")
    sys.path.insert(0, str(HERE))
    from app_paths import EPHEMERIS_DIR

    args = [
        str(HERE / "lambert_studio.py"),
        "--name", "LambertStudio",
        "--paths", str(HERE),
        "--icon", str(ROOT / "tools" / "icon.ico"),
        "--noconfirm", "--clean", "--windowed",
        "--distpath", str(OUT / "dist"),
        "--workpath", str(OUT / "build"),
        "--specpath", str(OUT),
        "--add-data", f"{ROOT / 'web'};web",
        "--collect-data", "skyfield",
        "--hidden-import", "scipy.integrate",
        "--exclude-module", "PySide6",
        "--exclude-module", "tkinter",
        "--exclude-module", "customtkinter",
        "--exclude-module", "plotly",
        "--exclude-module", "matplotlib",
        "--exclude-module", "pytest",
    ]
    eph = EPHEMERIS_DIR / "de440s.bsp"
    if eph.exists():
        args += ["--add-data", f"{eph};ephemeris"]
    else:
        print("Note: DE440s not found, the .exe will use the approximate planet formulas.")
    pyinstaller.run(args)

    folder = OUT / "dist" / "LambertStudio"
    archive = shutil.make_archive(str(OUT / "LambertStudio-windows"), "zip", folder)
    size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) / 1e6
    print(f"\nBuilt {folder / 'LambertStudio.exe'}  ({size:.0f} MB)\nZip:  {archive}")


if __name__ == "__main__":
    main()
