"""
Robustness sweep of the interface, in a real (headless) Edge window.

For every view it:
  * zooms all the way in and all the way out, flies at extreme speed and
    double-clicks around, then checks that the camera is still valid;
  * puts rare values (empty, text, huge, tiny, negative) into every input,
    one at a time, and presses the view's buttons;
  * records every JavaScript error, every error the page reports to the
    server log, and every camera that ended up invalid.

    python tests/ui_sweep.py                 # all views
    python tests/ui_sweep.py orbit maneuver  # only these
    python tests/ui_sweep.py --quick         # fewer values per input

Needs:  pip install playwright   (uses the installed Microsoft Edge).
Not part of the pytest run: a full sweep takes several minutes.
"""

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import studio_server  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

VIEWS = ["landing", "orbit", "ground", "maneuver", "near", "flybys", "solar", "mission", "learn"]
RARE = ["", "abc", "-1e308", "1e308", "0", "-5", "1e-9"]
QUICK = ["", "abc", "1e308", "-5"]
HEAVY = {"btn-route", "btn-suggest", "btn-pork", "btn-mc"}      # long searches: defaults + one bad round only

CHECK_CAMERAS = """() => {
  const bad = [];
  for (const s of (LS.scenes || [])) {
    const p = s.camera.position, t = s.controls.target;
    if (![p.x, p.y, p.z, t.x, t.y, t.z].every(Number.isFinite)) bad.push(s.container.id);
  }
  return bad;
}"""

SET_VALUE = """([id, v]) => {
  const el = document.getElementById(id);
  if (!el) return false;
  el.value = v;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
}"""


class Sweep:
    def __init__(self, page):
        self.page = page
        self.errors = []
        self.pending = 0
        self.where = ""
        page.on("pageerror", lambda e: self.errors.append((self.where, "JS error", str(e)[:300])))
        page.on("console", self._console)
        page.on("request", self._request)
        page.on("requestfinished", self._done)
        page.on("requestfailed", self._done)

    def _console(self, msg):
        if msg.type == "error" and "favicon" not in msg.text:
            self.errors.append((self.where, "console", msg.text[:300]))

    def _request(self, req):
        if "/api/" in req.url and "/api/ping" not in req.url:
            self.pending += 1
            if "/api/log" in req.url:
                self.errors.append((self.where, "page log", (req.post_data or "")[:300]))

    def _done(self, req):
        if "/api/" in req.url and "/api/ping" not in req.url:
            self.pending = max(0, self.pending - 1)

    def settle(self, limit=30.0, minimum=0.25):
        """Wait until the page has no API call in flight (or `limit` s)."""
        t0 = time.time()
        self.page.wait_for_timeout(int(minimum * 1000))
        while self.pending and time.time() - t0 < limit:
            self.page.wait_for_timeout(100)
        if self.pending:
            self.errors.append((self.where, "slow", f"API call still running after {limit:.0f} s"))
            self.pending = 0

    def cameras_ok(self):
        bad = self.page.evaluate(CHECK_CAMERAS)
        for c in bad:
            self.errors.append((self.where, "camera", f"invalid camera in {c}"))

    def go(self, view):
        self.where = view
        self.page.evaluate(f"location.hash = '{view}'")
        self.page.wait_for_timeout(1500)
        self.settle(60)

    def stress_camera(self, view):
        canvas = self.page.locator(f'.view[data-view="{view}"] .canvas')
        if not canvas.count() or not canvas.first.is_visible():
            return
        self.where = f"{view} / camera"
        # Events are sent from inside the page in batches: one round trip per
        # wheel step would wait for a software-rendered frame each time.
        wheel = """async ([n, dy]) => {
            const el = LS.Scene3D.shared.domElement, r = el.getBoundingClientRect();
            for (let k = 0; k < n; k++) {
              el.dispatchEvent(new WheelEvent('wheel', { deltaY: dy, clientX: r.x + r.width / 2,
                clientY: r.y + r.height / 2, bubbles: true, cancelable: true }));
              if (k % 25 === 24) await new Promise(requestAnimationFrame);
            }
            await new Promise(requestAnimationFrame);
        }"""
        key = """([type, code, key]) => window.dispatchEvent(new KeyboardEvent(type, { code, key, bubbles: true }))"""
        p = self.page
        p.evaluate(wheel, [200, -2000])            # zoom all the way in
        p.wait_for_timeout(500)
        self.cameras_ok()
        p.evaluate(wheel, [200, 4000])             # ... and all the way out
        p.wait_for_timeout(500)
        self.cameras_ok()
        box = canvas.first.bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        p.mouse.dblclick(cx, cy)                   # fly to whatever is in the middle
        p.mouse.dblclick(box["x"] + 20, box["y"] + 20)   # ... and to empty space
        p.wait_for_timeout(1500)
        self.cameras_ok()
        p.evaluate(key, ["keydown", "KeyF", "f"])  # fly mode at absurd speed
        p.evaluate(wheel, [300, -1000])
        p.evaluate(key, ["keydown", "ShiftLeft", "Shift"])
        p.evaluate(key, ["keydown", "KeyW", "w"])
        p.wait_for_timeout(1500)
        p.evaluate(key, ["keyup", "KeyW", "w"])
        p.evaluate(key, ["keyup", "ShiftLeft", "Shift"])
        self.cameras_ok()
        p.evaluate(wheel, [500, 1000])             # ... and absurdly slow
        p.evaluate(key, ["keydown", "KeyS", "s"])
        p.wait_for_timeout(500)
        p.evaluate(key, ["keyup", "KeyS", "s"])
        p.evaluate(key, ["keydown", "Escape", "Escape"])
        p.wait_for_timeout(300)
        self.cameras_ok()
        reset = p.locator(f'.view[data-view="{view}"] .cam-reset')
        if reset.count():
            reset.first.click(force=True)
            p.wait_for_timeout(1200)
        self.cameras_ok()

    def inputs_and_buttons(self, view, values):
        sec = f'section.ctl[data-for="{view}"]'
        ids = self.page.evaluate(f"""() => [...document.querySelectorAll('{sec} input, {sec} select')]
            .filter(e => e.id && !['checkbox', 'radio', 'button'].includes(e.type)).map(e => [e.id, e.value, e.type])""")
        buttons = self.page.evaluate(f"""() => [...document.querySelectorAll('{sec} button[id]')]
            .map(b => b.id).filter(i => i.startsWith('btn-'))""")
        light = [b for b in buttons if b not in HEAVY]
        heavy = [b for b in buttons if b in HEAVY]

        def press(bs, limit):
            for b in bs:
                ok = self.page.evaluate(f"""() => {{ const b = document.getElementById('{b}');
                    if (!b || b.disabled) return false; b.click(); return true; }}""")
                if ok:
                    self.settle(limit)

        self.where = f"{view} / defaults"
        press(buttons, 180)
        self.cameras_ok()
        for el_id, original, typ in ids:
            for v in (values if typ != "select-one" else ["", "nonsense"]):
                self.where = f"{view} / {el_id} = {v!r}"
                self.page.evaluate(SET_VALUE, [el_id, v])
                press(light, 30)
            self.page.evaluate(SET_VALUE, [el_id, original])
        for v in ("", "1e308"):                     # every field bad at once, long searches too
            self.where = f"{view} / all fields = {v!r}"
            for el_id, _, typ in ids:
                if typ != "select-one":
                    self.page.evaluate(SET_VALUE, [el_id, v])
            press(light + heavy, 180)
        for el_id, original, _ in ids:
            self.page.evaluate(SET_VALUE, [el_id, original])
        self.cameras_ok()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    values = QUICK if "--quick" in sys.argv else RARE
    views = args or VIEWS
    server, url = studio_server.start_server(0)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge", headless=True,
                                     args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.on("crash", lambda _p: print("  !! the page CRASHED", flush=True))
        sweep = Sweep(page)
        page.goto(url)
        page.wait_for_timeout(4000)
        for view in views:
            t = time.time()
            n0 = len(sweep.errors)
            sweep.go(view)
            sweep.stress_camera(view)
            sweep.inputs_and_buttons(view, values)
            sweep.where = f"{view} / camera again"
            sweep.stress_camera(view)
            print(f"{view:10s} {len(sweep.errors) - n0:3d} problems  ({time.time() - t:.0f} s)", flush=True)
        browser.close()
    server.shutdown()
    seen = set()
    for where, kind, msg in sweep.errors:
        key = (kind, msg[:120])
        if key in seen:
            continue
        seen.add(key)
        print(f"  [{kind}] {where}: {msg}")
    print(f"\n{len(sweep.errors)} problems ({len(seen)} distinct)")
    return 1 if sweep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
