"""
Lambert Studio -- desktop application.

Starts the local server (studio_server.py) and shows its interface in a
window of its own. Three ways to show it, best first:

    python lambert_studio.py            # Edge "app mode" window (default)
    python lambert_studio.py --qt       # embedded Qt (PySide6) window
    python lambert_studio.py --browser  # a tab in the default web browser

Edge app mode is the default because Edge's engine is kept up to date by
Windows, is the most stable of the three, and uses the dedicated graphics
card when the page asks for it. If Edge is not installed, the Qt window
is used; if that is not installed either, the default browser.

Logs (including native crashes) go to %USERPROFILE%\\.lambert_studio\\logs
(see app_paths.py for why not AppData).
"""

import argparse
import datetime
import faulthandler
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
import traceback
import webbrowser

from app_paths import LOG_DIR, EDGE_PROFILE_DIR


import studio_server
from studio_server import start_server


def relaunch_with_output_files(argv):
    """
    run_studio.bat starts pythonw (and the stand-alone .exe is windowed), so
    the process starts without stdout/stderr. The Fortran NRLMSIS atmosphere
    model checks for them when the process starts and aborts the whole
    process on its first calculation if they are missing (exit code
    0xC0000409) -- which killed the server the moment Orbit prediction
    opened. Patching the streams later does not help, so in that case the
    app starts itself again with real output files attached from the first
    moment, and waits for that copy. Returns the exit code, or None when the
    streams are already there and this process should simply carry on.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return None
    if os.environ.get("LAMBERT_STUDIO_CHILD"):
        return None                                     # never relaunch twice
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable] + ([] if getattr(sys, "frozen", False) else [os.path.abspath(__file__)]) + list(argv)
    env = dict(os.environ, LAMBERT_STUDIO_CHILD="1")
    with open(LOG_DIR / "native_output.log", "ab") as sink:
        return subprocess.call(cmd, stdin=subprocess.DEVNULL, stdout=sink, stderr=sink, env=env)

log = logging.getLogger("studio")

# The app's own address: http://lambert-studio.localhost:8765/
HOME_HOST = "lambert-studio.localhost"
HOME_PORT = 8765


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_DIR / "studio.log", level=logging.INFO, encoding="utf-8",
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # A native crash (like the Qt WebEngine one) kills the process before
    # Python can log anything; faulthandler still writes the Python stack.
    crash = open(LOG_DIR / "crash.log", "a", encoding="utf-8")
    crash.write(f"\n=== session {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
    crash.flush()
    faulthandler.enable(crash)
    sys.excepthook = lambda *exc: log.error("Uncaught:\n%s", "".join(traceback.format_exception(*exc)))


def show_error(message):
    """Message box that works even when started without a console."""
    log.error(message)
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, "Lambert Studio", 0x10)
    except Exception:
        print(message, file=sys.stderr)


# ----------------------------------------------------------------------
# Edge app mode
# ----------------------------------------------------------------------

def find_edge():
    candidates = [
        shutil.which("msedge"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
    ]
    return next((c for c in candidates if c and os.path.exists(c)), None)


def window_size(want_w=1480, want_h=920):
    """The preferred window size, shrunk to fit the usable part of the screen
    (the screen minus the taskbar and the window's own title bar)."""
    try:
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)   # SPI_GETWORKAREA
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w > 400 and h > 300:
            return min(want_w, w - 24), min(want_h, h - 24)
    except Exception:                                   # not Windows, or no screen information
        pass
    return want_w, want_h


def prepare_profile(profile):
    """
    Edge remembers where an app window was and which pages it offered to
    translate, and those memories override the launch options. A window
    saved bigger than today's screen (another monitor, another scaling)
    would open cut off, and a Spanish system asks "translate this page?"
    over every English page. Forget both before each start. Edge is not
    running yet, so it will not overwrite the file.
    """
    import json
    path = pathlib.Path(profile) / "Default" / "Preferences"
    try:
        prefs = json.loads(path.read_text(encoding="utf-8"))
        prefs.get("browser", {}).pop("app_window_placement", None)
        prefs["translate"] = {**prefs.get("translate", {}), "enabled": False}
        blocked = prefs.setdefault("translate_blocked_languages", [])
        if "en" not in blocked:
            blocked.append("en")
        path.write_text(json.dumps(prefs, separators=(",", ":")), encoding="utf-8")
    except (OSError, ValueError):
        pass                                            # first run: no profile yet


def run_edge(edge, url):
    """
    Open the interface as a standalone Edge window and keep the server
    alive until that window is closed. The page tells the server when it
    closes (and pings it while open), which is more reliable than waiting
    on the Edge process: Edge may hand the window to another process.
    """
    profile = EDGE_PROFILE_DIR
    prepare_profile(profile)
    width, height = window_size()
    proc = subprocess.Popen([
        edge, f"--app={url}", f"--user-data-dir={profile}",
        f"--window-size={width},{height}", "--window-position=8,8",
        "--no-first-run", "--no-default-browser-check",
        "--disable-extensions", "--disable-sync",
        # Laptops with two graphics chips give a browser the weak integrated one
        # by default; ask for the dedicated card (a no-op if there is only one).
        "--force_high_performance_gpu", "--ignore-gpu-blocklist",
        # no "translate this page?" bubble on systems that are not set to English
        "--disable-features=msEdgeStartupBoost,Translate,TranslateUI,msEdgeTranslate",
    ])
    log.info("Edge app window started (pid %s)", proc.pid)

    start = time.time()
    while True:
        time.sleep(1.0)
        now = time.time()
        hb = studio_server.HEARTBEAT
        # The page said goodbye and has not come back (a reload would ping again).
        if hb["bye"] and hb["bye"] > hb["ping"] and now - hb["bye"] > 3:
            break
        # The page never connected: Edge failed to open it.
        if not hb["ping"] and now - start > 45:
            show_error("The Lambert Studio window did not open.\n\n"
                       "Try:  run_studio.bat --qt   or   run_studio.bat --browser")
            break
        # Last resort: no sign of life for a long time. (Long, because a
        # minimised window is throttled to about one ping per minute.)
        if hb["ping"] and now - hb["ping"] > 240:
            break
    log.info("Window closed; shutting down")
    return 0


# ----------------------------------------------------------------------
# Qt window
# ----------------------------------------------------------------------

def run_qt(url):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEnginePage

    app = QApplication(sys.argv)
    app.setApplicationName("Lambert Studio")

    win = QMainWindow()
    win.setWindowTitle("Lambert Studio")
    win.resize(1480, 920)
    win.setMinimumSize(1100, 700)

    view = QWebEngineView()
    page = view.page()
    page.setBackgroundColor(QColor("#070b16"))       # no white flash on load
    s = view.settings()
    s.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
    s.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)

    # If the page's renderer dies, log it and reload instead of showing a
    # dead grey window.
    def on_render_dead(status, code):
        log.error("Qt page renderer terminated: status=%s exit=%s; reloading", status, code)
        view.reload()
    page.renderProcessTerminated.connect(on_render_dead)

    def on_download(item):
        path, _ = QFileDialog.getSaveFileName(win, "Save file", item.downloadFileName())
        if path:
            item.setDownloadDirectory(str(pathlib.Path(path).parent))
            item.setDownloadFileName(pathlib.Path(path).name)
            item.accept()
        else:
            item.cancel()
    page.profile().downloadRequested.connect(on_download)

    view.setUrl(QUrl(url))
    win.setCentralWidget(view)
    win.show()
    code = app.exec()
    # Destroy the web view before the application object: letting Python
    # tear them down in arbitrary order at exit is a known crash source.
    win.takeCentralWidget()
    view.setPage(QWebEnginePage())
    view.deleteLater()
    del view, page
    return code


def say(*args):
    """print() that is safe in a windowed .exe, where there is no console."""
    if sys.stdout is not None:
        print(*args, flush=True)
    log.info(" ".join(str(a) for a in args))


def run_in_browser(url, open_browser=True):
    say(f"Lambert Studio is running at {url}")
    say("Close this window (or press Ctrl+C) to stop it.")
    if not open_browser:
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return 0
    webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0


def main(argv=None):
    code = relaunch_with_output_files(sys.argv[1:] if argv is None else argv)
    if code is not None:
        return code
    parser = argparse.ArgumentParser(description="Lambert Studio")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--qt", action="store_true", help="use the embedded Qt window")
    g.add_argument("--browser", action="store_true", help="open in the default web browser")
    g.add_argument("--no-window", action="store_true",
                   help="only start the server (open the printed address yourself)")
    parser.add_argument("--port", type=int, default=0, help="server port (default: any free)")
    args = parser.parse_args(argv)

    setup_logging()
    log.info("Starting (python %s)", sys.version.split()[0])
    try:
        _, url = start_server(args.port or HOME_PORT)
    except OSError:
        # The usual port is taken (another copy is running): use any free one.
        try:
            _, url = start_server(0)
        except Exception as exc:
            show_error(f"Could not start the Lambert Studio server:\n{exc}")
            return 1
    except Exception as exc:
        show_error(f"Could not start the Lambert Studio server:\n{exc}")
        return 1
    # Browsers send every *.localhost name to this computer, so the app gets a
    # readable address of its own; the server still listens on 127.0.0.1 only.
    url = url.replace("127.0.0.1", HOME_HOST)

    if args.no_window:
        return run_in_browser(url, open_browser=False)
    if args.browser:
        return run_in_browser(url)
    if not args.qt:
        edge = find_edge()
        if edge:
            return run_edge(edge, url)
        log.info("Edge not found; falling back to Qt")
    try:
        import PySide6.QtWebEngineWidgets  # noqa: F401
    except ImportError:
        return run_in_browser(url)
    return run_qt(url)


if __name__ == "__main__":
    raise SystemExit(main())
