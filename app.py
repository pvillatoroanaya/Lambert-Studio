"""
Application shell (CustomTkinter).

The GUI is a control panel, not a renderer: it collects inputs, runs the
solvers, shows the numbers, and hands the visualisation off to the
Plotly dashboard, which opens in the browser. That split is deliberate --
it is why the 3D is GPU-accelerated and texture-mapped instead of being
limited by a desktop toolkit's drawing canvas.

Falls back to plain tkinter styling if customtkinter is not installed, so
the program still runs on a bare Python + numpy + plotly install.
"""

import datetime
import math
import os
import pathlib
import queue
import threading
import traceback
import webbrowser

import numpy as np

try:
    import customtkinter as ctk
    _HAS_CTK = True
except Exception:                                   # pragma: no cover
    _HAS_CTK = False

import tkinter as tk
from tkinter import messagebox, filedialog

from constants import R_EARTH, AU
from time_utils import julian_date, gmst_from_jd, time_of_flight
from coord_utils import topocentric_to_geocentric
from lambert_solver import lambert_universal
from orbital_elements import state_to_elements, format_duration
from report import build_report
from interplanetary import transfer, porkchop, best_transfer
# NOTE: `dashboard` (and therefore plotly) is imported lazily inside the
# worker, so the application still starts and solves on a machine where
# plotly is not installed -- only the dashboard button is unavailable.
from planets import PLANET_ORDER

if _HAS_CTK:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
    Base = ctk.CTk
else:                                               # pragma: no cover
    Base = tk.Tk

# Palette, matched to the dashboard so the two read as one product.
BG = "#0b1020"
PANEL = "#121a2f"
CARD = "#16203a"
FG = "#e6edf7"
MUTED = "#8fa3c8"
ACCENT = "#5ac8fa"
ACCENT_DK = "#2b93c4"
OK = "#7bed9f"
WARN = "#ffb454"
ERR = "#ff5a5f"

MODE_OBS = "observations"
MODE_VEC = "vectors"


class LambertStudio(Base):
    def __init__(self):
        super().__init__()
        self.title("Lambert Studio — Orbit Determination")
        self.geometry("1180x880")
        self.minsize(1000, 720)
        if _HAS_CTK:
            self.configure(fg_color=BG)
        else:                                       # pragma: no cover
            self.configure(bg=BG)

        self.solution = None
        self.jd0 = None
        self.dashboard_path = None
        self._busy = False
        self._queue = queue.Queue()

        self._build()
        self._on_mode_change()

    # ------------------------------------------------------------------
    # small styled constructors (keep the build method readable)
    # ------------------------------------------------------------------
    def _frame(self, parent, **kw):
        if _HAS_CTK:
            return ctk.CTkFrame(parent, fg_color=kw.pop("fg", CARD),
                                 corner_radius=kw.pop("radius", 12), **kw)
        return tk.Frame(parent, bg=CARD)             # pragma: no cover

    def _label(self, parent, text, size=13, color=FG, weight="normal", **kw):
        if _HAS_CTK:
            return ctk.CTkLabel(parent, text=text, text_color=color,
                                 font=ctk.CTkFont(size=size, weight=weight), **kw)
        return tk.Label(parent, text=text, bg=CARD, fg=color)   # pragma: no cover

    def _entry(self, parent, default="", width=120):
        if _HAS_CTK:
            e = ctk.CTkEntry(parent, width=width, height=30,
                              fg_color=PANEL, border_color="#2a3654",
                              text_color=FG, corner_radius=7)
        else:                                       # pragma: no cover
            e = tk.Entry(parent, width=14)
        e.insert(0, default)
        return e

    def _button(self, parent, text, cmd, primary=False, width=150):
        if _HAS_CTK:
            return ctk.CTkButton(
                parent, text=text, command=cmd, width=width, height=36,
                corner_radius=9,
                fg_color=ACCENT_DK if primary else "#22304f",
                hover_color=ACCENT if primary else "#2d3e64",
                text_color="#ffffff",
                font=ctk.CTkFont(size=13, weight="bold" if primary else "normal"))
        return tk.Button(parent, text=text, command=cmd)        # pragma: no cover

    # ------------------------------------------------------------------
    def _build(self):
        self.grid_columnconfigure(0, weight=0, minsize=430)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ---------------- header -------------------------------------
        head = self._frame(self, fg=PANEL, radius=0)
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        self._label(head, "Lambert Studio", size=21, weight="bold").pack(
            anchor="w", padx=22, pady=(16, 0))
        self._label(head,
                    "Orbit determination from two observations  ·  "
                    "five reference frames  ·  interplanetary transfers",
                    size=12, color=MUTED).pack(anchor="w", padx=22, pady=(2, 14))

        # ---------------- left: inputs -------------------------------
        if _HAS_CTK:
            left = ctk.CTkScrollableFrame(self, fg_color=BG, width=420)
        else:                                       # pragma: no cover
            left = tk.Frame(self, bg=BG)
        left.grid(row=1, column=0, sticky="nsew", padx=(14, 7), pady=14)

        self._card_mode(left)
        # Both input cards live in a dedicated slot, so switching modes is
        # just pack/pack_forget inside it. (Using `before=` against a
        # sibling fails as soon as that sibling is itself unpacked.)
        self.mode_slot = self._frame(left, fg=BG, radius=0)
        self.mode_slot.pack(fill="x")
        self._card_obs(self.mode_slot)
        self._card_vec(self.mode_slot)
        self._card_options(left)
        self._card_interplanetary(left)

        # ---------------- right: results -----------------------------
        right = self._frame(self, fg=BG, radius=0)
        right.grid(row=1, column=1, sticky="nsew", padx=(7, 14), pady=14)
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        actions = self._frame(right, fg=BG, radius=0)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self._button(actions, "Solve", self.on_solve, primary=True, width=120
                      ).pack(side="left")
        self._button(actions, "Open dashboard", self.on_dashboard, width=160
                      ).pack(side="left", padx=(8, 0))
        self._button(actions, "Save report", self.on_save_report, width=130
                      ).pack(side="left", padx=(8, 0))
        self.status = self._label(actions, "Ready", size=12, color=MUTED)
        self.status.pack(side="left", padx=(14, 0))

        out = self._frame(right)
        out.grid(row=1, column=0, sticky="nsew")
        if _HAS_CTK:
            self.output = ctk.CTkTextbox(
                out, fg_color=PANEL, text_color=FG, corner_radius=10,
                font=ctk.CTkFont(family="Consolas", size=12), wrap="none")
        else:                                       # pragma: no cover
            self.output = tk.Text(out, bg=PANEL, fg=FG)
        self.output.pack(fill="both", expand=True, padx=10, pady=10)
        self._write("Enter the observations on the left and press Solve.\n\n"
                    "The defaults are the assignment's own data.")

    # ---------------- cards ------------------------------------------
    def _card(self, parent, title):
        c = self._frame(parent)
        c.pack(fill="x", pady=(0, 12))
        self._label(c, title.upper(), size=11, color=ACCENT, weight="bold").pack(
            anchor="w", padx=16, pady=(13, 8))
        inner = self._frame(c, fg=CARD, radius=0)
        inner.pack(fill="x", padx=16, pady=(0, 14))
        return c, inner

    def _row(self, parent, label, default, width=130, row=0, unit=""):
        self._label(parent, label, size=12, color=MUTED, anchor="w").grid(
            row=row, column=0, sticky="w", pady=4)
        e = self._entry(parent, default, width)
        e.grid(row=row, column=1, sticky="w", padx=(10, 6), pady=4)
        if unit:
            self._label(parent, unit, size=11, color=MUTED).grid(
                row=row, column=2, sticky="w", pady=4)
        parent.grid_columnconfigure(1, weight=1)
        return e

    def _card_mode(self, parent):
        _, inner = self._card(parent, "Input type")
        self.mode = tk.StringVar(value=MODE_OBS)
        for text, val in (("Observations  (azimuth / elevation / range)", MODE_OBS),
                           ("Position vectors  (r₁, r₂ and time of flight)", MODE_VEC)):
            if _HAS_CTK:
                ctk.CTkRadioButton(inner, text=text, variable=self.mode, value=val,
                                    command=self._on_mode_change,
                                    text_color=FG, fg_color=ACCENT,
                                    hover_color=ACCENT,
                                    font=ctk.CTkFont(size=12)).pack(anchor="w", pady=3)
            else:                                   # pragma: no cover
                tk.Radiobutton(inner, text=text, variable=self.mode, value=val,
                                command=self._on_mode_change).pack(anchor="w")

    def _card_obs(self, parent):
        self.obs_card, inner = self._card(parent, "Ground station & observations")
        self.station = [
            self._row(inner, "Station X", "1344.143", row=0, unit="km"),
            self._row(inner, "Station Y", "6068.601", row=1, unit="km"),
            self._row(inner, "Station Z", "1429.311", row=2, unit="km"),
        ]
        self._label(inner, "", size=6).grid(row=3, column=0)
        self.obs1, self.obs2 = {}, {}
        specs = [("Date  (DD/MM/YYYY)", "date", "02/04/2023", ""),
                 ("UTC time", "utc", "00:30:00.0", ""),
                 ("Azimuth", "az", "132.67", "deg"),
                 ("Elevation", "el", "32.44", "deg"),
                 ("Range", "rng", "16945.450", "km")]
        self._label(inner, "Observation 1", size=12, color=FG, weight="bold").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(6, 2))
        for i, (lab, key, dflt, unit) in enumerate(specs):
            self.obs1[key] = self._row(inner, lab, dflt, row=5 + i, unit=unit)

        specs2 = [("Date  (DD/MM/YYYY)", "date", "02/04/2023", ""),
                  ("UTC time", "utc", "03:00:00.0", ""),
                  ("Azimuth", "az", "123.08", "deg"),
                  ("Elevation", "el", "50.06", "deg"),
                  ("Range", "rng", "37350.340", "km")]
        self._label(inner, "Observation 2", size=12, color=FG, weight="bold").grid(
            row=11, column=0, columnspan=3, sticky="w", pady=(10, 2))
        for i, (lab, key, dflt, unit) in enumerate(specs2):
            self.obs2[key] = self._row(inner, lab, dflt, row=12 + i, unit=unit)

    def _card_vec(self, parent):
        self.vec_card, inner = self._card(parent, "Position vectors")
        self.r1e = [self._row(inner, "r₁ X", "5000.0", row=0, unit="km"),
                    self._row(inner, "r₁ Y", "10000.0", row=1, unit="km"),
                    self._row(inner, "r₁ Z", "2100.0", row=2, unit="km")]
        self.r2e = [self._row(inner, "r₂ X", "-14600.0", row=3, unit="km"),
                    self._row(inner, "r₂ Y", "2500.0", row=4, unit="km"),
                    self._row(inner, "r₂ Z", "7000.0", row=5, unit="km")]
        self.tof = self._row(inner, "Time of flight", "3600.0", row=6, unit="s")
        self._label(inner, "Defaults are Curtis Example 5.2 (a published reference case).",
                    size=10, color=MUTED, wraplength=330, justify="left").grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def _card_options(self, parent):
        _, inner = self._card(parent, "Solver options")
        self.prograde = tk.BooleanVar(value=True)
        if _HAS_CTK:
            ctk.CTkSwitch(inner, text="Prograde transfer (short way)",
                           variable=self.prograde, text_color=FG,
                           progress_color=ACCENT_DK,
                           font=ctk.CTkFont(size=12)).pack(anchor="w", pady=2)
        else:                                       # pragma: no cover
            tk.Checkbutton(inner, text="Prograde", variable=self.prograde).pack(anchor="w")

    def _card_interplanetary(self, parent):
        _, inner = self._card(parent, "Interplanetary mode (same solver, μ☉)")
        self.do_interp = tk.BooleanVar(value=True)
        if _HAS_CTK:
            ctk.CTkSwitch(inner, text="Include solar-system transfer & porkchop",
                           variable=self.do_interp, text_color=FG,
                           progress_color=ACCENT_DK,
                           font=ctk.CTkFont(size=12)).grid(
                row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
            self.dep_planet = ctk.CTkOptionMenu(
                inner, values=PLANET_ORDER, width=130, fg_color=PANEL,
                button_color=ACCENT_DK, text_color=FG)
            self.dep_planet.set("Earth")
            self.arr_planet = ctk.CTkOptionMenu(
                inner, values=PLANET_ORDER, width=130, fg_color=PANEL,
                button_color=ACCENT_DK, text_color=FG)
            self.arr_planet.set("Mars")
        else:                                       # pragma: no cover
            tk.Checkbutton(inner, text="Interplanetary",
                            variable=self.do_interp).grid(row=0, column=0)
            self.dep_planet = tk.StringVar(value="Earth")
            self.arr_planet = tk.StringVar(value="Mars")

        self._label(inner, "From", size=12, color=MUTED).grid(row=1, column=0, sticky="w")
        self.dep_planet.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=3)
        self._label(inner, "To", size=12, color=MUTED).grid(row=2, column=0, sticky="w")
        self.arr_planet.grid(row=2, column=1, sticky="w", padx=(10, 0), pady=3)
        self.dep_date = self._row(inner, "Departure", "01/11/2026", row=3)
        self.arr_date = self._row(inner, "Arrival", "20/08/2027", row=4)
        self._label(inner,
                    "A porkchop plot is built by solving Lambert's problem "
                    "~2000 times across a grid of dates.",
                    size=10, color=MUTED, wraplength=330, justify="left").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))

    # ------------------------------------------------------------------
    def _on_mode_change(self):
        self.obs_card.pack_forget()
        self.vec_card.pack_forget()
        card = self.obs_card if self.mode.get() == MODE_OBS else self.vec_card
        card.pack(fill="x", pady=(0, 12))

    def _write(self, text):
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)

    def _set_status(self, text, color=MUTED):
        if _HAS_CTK:
            self.status.configure(text=text, text_color=color)
        else:                                       # pragma: no cover
            self.status.configure(text=text)
        self.update_idletasks()

    # ------------------------------------------------------------------
    # parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _num(entry, label):
        raw = entry.get().strip()
        try:
            return float(raw)
        except ValueError:
            raise ValueError(f"{label} must be a number (got '{raw}').")

    def _parse_date(self, entry, label):
        raw = entry.get().strip()
        parts = raw.split("/")
        if len(parts) != 3:
            raise ValueError(f"{label} must be DD/MM/YYYY (got '{raw}').")
        try:
            d, m, y = (int(p) for p in parts)
        except ValueError:
            raise ValueError(f"{label} contains non-numeric fields ('{raw}').")
        if not (1 <= m <= 12 and 1 <= d <= 31):
            raise ValueError(f"{label} is not a valid date ('{raw}').")
        return d, m, y

    def _parse_obs(self, obs, label):
        d, m, y = self._parse_date(obs["date"], f"{label} date")
        tparts = obs["utc"].get().strip().split(":")
        if len(tparts) != 3:
            raise ValueError(f"{label} UTC time must be HH:MM:SS.s.")
        try:
            hh, mm, ss = int(tparts[0]), int(tparts[1]), float(tparts[2])
        except ValueError:
            raise ValueError(f"{label} UTC time contains non-numeric fields.")
        if not (0 <= hh < 24 and 0 <= mm < 60 and 0 <= ss < 60):
            raise ValueError(f"{label} UTC time is out of range.")

        az = self._num(obs["az"], f"{label} azimuth")
        el = self._num(obs["el"], f"{label} elevation")
        rng = self._num(obs["rng"], f"{label} range")
        if not -90.0 <= el <= 90.0:
            raise ValueError(f"{label} elevation must be between -90 and +90 deg.")
        if rng <= 0:
            raise ValueError(f"{label} range must be positive.")
        return julian_date(y, m, d, hh, mm, ss), az, el, rng

    def _gather(self):
        if self.mode.get() == MODE_OBS:
            st = np.array([self._num(e, f"Station {ax}")
                           for e, ax in zip(self.station, "XYZ")])
            if np.linalg.norm(st) < 1.0:
                raise ValueError("Station position cannot be the zero vector.")
            jd1, az1, el1, rg1 = self._parse_obs(self.obs1, "Observation 1")
            jd2, az2, el2, rg2 = self._parse_obs(self.obs2, "Observation 2")
            dt = time_of_flight(jd1, jd2)
            if dt <= 0:
                raise ValueError("Observation 2 must be later than Observation 1.")
            r1 = topocentric_to_geocentric(az1, el1, rg1, st, gmst_from_jd(jd1))
            r2 = topocentric_to_geocentric(az2, el2, rg2, st, gmst_from_jd(jd2))
            return r1, r2, dt, st, jd1

        r1 = np.array([self._num(e, f"r1 {ax}") for e, ax in zip(self.r1e, "XYZ")])
        r2 = np.array([self._num(e, f"r2 {ax}") for e, ax in zip(self.r2e, "XYZ")])
        for v, n in ((r1, "r₁"), (r2, "r₂")):
            if np.linalg.norm(v) < 1e-6:
                raise ValueError(f"{n} cannot be the zero vector.")
        dt = self._num(self.tof, "Time of flight")
        if dt <= 0:
            raise ValueError("Time of flight must be positive.")
        # No epoch is supplied in this mode, so the Earth-fixed views are
        # referenced to J2000 and labelled as such in the dashboard.
        return r1, r2, dt, None, 2451545.0

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def on_solve(self):
        try:
            r1, r2, dt, station, jd0 = self._gather()
            v1, v2, z = lambert_universal(r1, r2, dt, prograde=self.prograde.get())
            elems = state_to_elements(r1, v1)
            self.solution = dict(r1=r1, r2=r2, v1=v1, v2=v2, dt=dt, z=z,
                                  elems=elems, r_station=station,
                                  mode=self.mode.get(),
                                  prograde=self.prograde.get())
            self.jd0 = jd0
            self.dashboard_path = None
            self._write(build_report(self.solution))
            self._set_status("Solved", OK)
        except Exception as exc:
            self._set_status("Error", ERR)
            messagebox.showerror("Could not solve", str(exc))

    def on_dashboard(self):
        if self.solution is None:
            messagebox.showinfo("Solve first",
                                 "Press Solve, then open the dashboard.")
            return
        if self._busy:
            return

        # Every widget read happens HERE, on the main thread. Tk is not
        # thread-safe, and touching a widget from the worker raises
        # "main thread is not in main loop".
        try:
            params = None
            if self.do_interp.get():
                dep = self.dep_planet.get()
                arr = self.arr_planet.get()
                if dep == arr:
                    raise ValueError("Departure and arrival planets must differ.")
                d1 = self._parse_date(self.dep_date, "Departure date")
                d2 = self._parse_date(self.arr_date, "Arrival date")
                jd_d = julian_date(d1[2], d1[1], d1[0], 0, 0, 0.0)
                jd_a = julian_date(d2[2], d2[1], d2[0], 0, 0, 0.0)
                if jd_a <= jd_d:
                    raise ValueError("Arrival date must be after departure date.")
                params = (dep, arr, jd_d, jd_a)
        except Exception as exc:
            messagebox.showerror("Could not build dashboard", str(exc))
            return

        self._busy = True
        self._set_status("Building dashboard…", WARN)
        threading.Thread(target=self._build_dashboard_worker,
                          args=(params,), daemon=True).start()
        # Poll for the result from the MAIN thread. Scheduling the
        # callback here (rather than calling self.after from inside the
        # worker) keeps every Tk interaction on the main thread.
        self.after(200, self._poll_dashboard)

    def _poll_dashboard(self):
        try:
            kind, payload = self._queue.get_nowait()
        except queue.Empty:
            if self._busy:
                self.after(200, self._poll_dashboard)
            return
        self._busy = False
        if kind == "ok":
            self.dashboard_path = payload
            self._set_status(f"Dashboard → {payload}", OK)
            try:
                webbrowser.open("file://" + os.path.abspath(payload))
            except Exception:                        # pragma: no cover
                pass
        else:
            self._set_status("Dashboard failed", ERR)
            messagebox.showerror("Could not build dashboard", payload)

    def _build_dashboard_worker(self, params):
        """Runs off the main thread: pure computation and file output only."""
        try:
            try:
                from dashboard import build_dashboard
            except ImportError as exc:
                raise RuntimeError(
                    "The dashboard needs plotly.  Install it with:\n"
                    "    pip install plotly\n\n"
                    f"(import error: {exc})")

            tr = pork = None
            if params is not None:
                dep, arr, jd_d, jd_a = params
                tr = transfer(dep, arr, jd_d, jd_a)

                # Scan a window around the chosen dates.
                span = jd_a - jd_d
                dg, ag, Z = porkchop(
                    dep, arr,
                    (jd_d - 0.45 * span, jd_d + 0.45 * span),
                    (jd_a - 0.55 * span, jd_a + 0.55 * span),
                    n_dep=42, n_arr=42)
                pork = (dg, ag, Z, best_transfer(dg, ag, Z), dep, arr)

            out = pathlib.Path.home() / "lambert_dashboard.html"
            build_dashboard(self.solution, str(out), jd0=self.jd0,
                             interplanetary=tr, porkchop_data=pork)
            self._queue.put(("ok", str(out)))
        except Exception as exc:
            traceback.print_exc()
            self._queue.put(("err", str(exc)))

    def on_save_report(self):
        if self.solution is None:
            messagebox.showinfo("Solve first", "Press Solve, then save the report.")
            return
        path = filedialog.asksaveasfilename(
            title="Save results report", defaultextension=".txt",
            initialfile="lambert_results.txt",
            filetypes=[("Text file", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(build_report(self.solution))
            self._set_status(f"Report → {path}", OK)
        except OSError as exc:
            messagebox.showerror("Could not save", str(exc))


def main():
    LambertStudio().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
