# Lambert's Problem Solver — and Lambert Studio

Orbit determination by solving **Lambert's problem**: two topocentric
observations of a satellite (azimuth, elevation, range from a ground
station at two known times) → two geocentric position vectors → the
orbit connecting them → its classical orbital elements.

The project has two parts:

1. **The assignment deliverable**: a single Python file,
   `lambert_problem_solver.py`, with a GUI, a text report, an interactive
   HTML dashboard and a validation suite.
2. **Lambert Studio**: an extended desktop application built on the
   same solver, with 3D visualisation, real satellite and asteroid data,
   interplanetary mission design, an orbital manoeuvre planner and
   perturbed-orbit prediction.

---

## 1. Assignment deliverable

```
python lambert_problem_solver.py              # GUI (pre-filled with the assignment data)
python lambert_problem_solver.py --report     # text report for the assignment data
python lambert_problem_solver.py --selftest   # validation suite
python lambert_problem_solver.py --dashboard  # interactive HTML dashboard
```

**Requirements:** Python 3.10+ and `numpy`. Optional: `plotly` (dashboard)
and `customtkinter` (modern GUI styling). If an optional package is
missing, only the feature that needs it is disabled.

The single file is **generated** from the modules by
`python build_single_file.py`. Edit the modules, not the generated file.

### Method

| Step | Module | What it does |
|---|---|---|
| Time | `time_utils.py` | Calendar UTC → Julian Date; Greenwich Mean Sidereal Time (IAU 1982) |
| Observations | `coord_utils.py` | Azimuth/elevation/range → SEZ → ECEF → ECI position vector |
| Lambert | `lambert_solver.py` | Universal-variable formulation (Curtis, Algorithm 5.2), Stumpff functions, bracketed root finding |
| Elements | `orbital_elements.py` | State vector → a, e, i, Ω, ω, ν and derived quantities |
| Frames | `frames.py` | Two-body propagation; ECI, ECEF, perifocal, ground track and sky-view transforms |
| Report | `report.py` | Formatted text results |
| GUI / dashboard | `app.py`, `dashboard.py`, `viz.py` | Tkinter GUI and self-contained Plotly dashboard |
| Interplanetary | `planets.py`, `interplanetary.py` | Same Lambert solver with μ☉: planet-to-planet transfers and porkchop plots |

### Result for the assignment data

| Element | Value |
|---|---|
| Semi-major axis a | 28,184.19 km |
| Eccentricity e | 0.768209 |
| Inclination i | 20.339° |
| RAAN Ω | 359.490° |
| Argument of perigee ω | 179.231° |
| True anomaly at r₁ | 126.010° |
| Period | 13 h 04 min |
| Perigee / apogee altitude | 155 km / 43,457 km |

### Assumptions

- Dates are **DD/MM/YYYY** (the assignment's `02/04/2023` = 2 April 2023).
- UTC is used in place of UT1 when computing GMST (difference < 1 s).
- The station's latitude and longitude come from its ECEF position on a
  **spherical Earth** (no ellipsoid was specified).
- ECEF → ECI uses GMST only (no precession, nutation or polar motion).
- The Lambert solver defaults to the **prograde, short-way**, single-revolution solution.
- μ⊕ = 398,600.4418 km³/s², R⊕ = 6,378.137 km.

### Validation

`validation.py` (also `--selftest`) runs 74 core checks, all passing:

- **Textbook reference cases.** Curtis Example 5.2 (Lambert) and
  Example 4.3 (elements from a state vector) match the published answers.
- **Physics invariants on the assignment data.** Energy and angular
  momentum are equal at both points, and the elements agree from either
  point. The mean anomaly advances by exactly n·Δt, and propagating
  (r₁, v₁) forward by Δt lands on r₂ to within 10⁻¹¹ km.
- **Multi-revolution Lambert.** For 1 and 2 laps, on both solution
  branches, propagating the solution lands on r₂ (to within 10⁻⁸ km)
  after exactly N laps. Too-short times are rejected, and the batch
  solver equals the scalar one.
- **Round trip.** Converting the solved orbit back into the station's
  sky recovers the original azimuth, elevation and range to machine
  precision.
- **Frames.** The orbit closes after one period, the ground-track
  latitude never exceeds the inclination, and the perifocal track is planar.
- **Planets and transfers.** Sidereal periods match accepted values, and
  an Earth→Mars 2026 transfer lands in the realistic range for C₃ and Δv.

With the Lambert Studio packages installed, 29 more checks cover the
extensions (103 in total; without them, those checks are listed as skipped):

- the JPL DE440s ephemeris, compared with the approximate elements;
- Hohmann LEO→GEO Δv = 3.893 km/s;
- the plane-change formula;
- bi-elliptic beating Hohmann when r₂/r₁ is large;
- the numerically integrated J2 node drift, compared with the analytic
  rate (Sun-synchronous ≈ 0.9856°/day);
- the fast satellite model, compared with SGP4;
- the gravity-assist optimiser against history. Searching from physics
  alone, it finds Mariner 10's Venus flyby within 2 days of the real date
  (5 Feb 1974) and Voyager's launch within 3 days (5 Sep 1977), with
  Jupiter adding about 10 km/s;
- routes that return to the same planet (multi-revolution legs), within
  each mission's real launch period. Cassini's Earth flyby comes within a
  day of the real date (18 Aug 1999) and its launch within 2 days. Galileo's
  Venus and first Earth flybys come within 12 and 22 days.

---

## 2. Lambert Studio (extended application)

Double-click **`run_studio.bat`** (or run `python lambert_studio.py`).

| Tab | Contents |
|---|---|
| Orbit | Lambert solution in 3D around a rotating, textured Earth; live altitude, speed and visibility from the station |
| Track | Ground track on a world map and the station's sky view, on the same timeline |
| Maneuver | Hohmann, bi-elliptic, plane change and circularisation: Δv per burn, propellant (rocket equation), animated transfer, comparison of options |
| Perturb | Numerical integration with J2 and atmospheric drag (SciPy DOP853): drift of the node and perigee against the analytic J2 rates, orbital decay and re-entry |
| Satellites | Real satellites from CelesTrak at their current positions; search, details and orbits |
| Flybys | Upcoming asteroid close approaches (NASA/JPL CNEOS), with precise geocentric paths from JPL Horizons |
| Solar | Planets from the JPL DE440s ephemeris, and potentially hazardous asteroids from the JPL Small-Body Database |
| Mission | **Direct transfer:** porkchop plot and a plain-language explanation of the route (Type I/II, how far ahead to aim, comparison with Hohmann, how often launch windows return). **Gravity-assist route:** routes with up to 4 flybys, optimised with patched conics (`flyby.py`), where a leg may loop around the Sun (multi-revolution Lambert), so the same planet can be used twice. Shown in 3D with a speed-gain chart and a step-by-step story. Examples: Voyager, Mariner 10, Galileo (VEEGA), Cassini (VVEJGA) and the Voyager 2 Grand Tour |

**Mission playback:** every route or transfer can be played full-screen
(▶ Play mission): a cinematic camera follows the spacecraft and swings to
each planet as it is reached, time slows down around each event, cards
explain each flyby, and a telemetry panel shows date, distance from the
Sun, speed and Δv used, with a clickable timeline.

**Recommended values:** the input panels suggest real-world values with a
short sourced note: NASA Deep Space Network / ESA / KSC ground stations
(converted from WGS-84 to Earth-fixed coordinates), reference orbits,
launch-site inclinations, flown engines (Isp), real spacecraft masses and
drag areas, and a *Suggest the next launch window* search for any pair of
planets.

**Scale:** solar-system views compress distances (√r) by default so all
eight planets fit on screen; a *True-scale distances* switch shows real
distances.

**Camera (every 3D view):** *Orbit* mode (drag to rotate, right-drag to pan,
scroll to zoom) or *Fly* mode (key F; W/A/S/D to move, Q/E down/up, drag to look,
Shift for 5× speed, scroll to change speed, Esc to return). Double-click any
object to fly to it; *Follow* keeps the camera with a moving object (spacecraft,
planet, Moon…); *Reset* returns to the starting view.

**Requirements:** `pip install -r requirements.txt`. The first run needs
internet for satellite and asteroid data; afterwards saved copies are
used offline. All app data lives in `%USERPROFILE%\.lambert_studio`:
`cache\` (downloads), `logs\`, and `ephemeris\` (DE440s, 31 MB — without it,
the approximate planetary elements are used automatically).

Options: `run_studio.bat --qt` (embedded Qt window instead of Edge app
mode), `--browser` (normal browser tab). `run_studio_debug.bat` keeps a
console open.

**Architecture:** the physics stays in Python; `studio_server.py` serves
a JSON API on 127.0.0.1 only, and the interface in `web/` draws it with
Three.js (3D) and Plotly (charts).

### Data and credits

- Earth imagery: NASA Blue Marble and Black Marble (public domain)
- Planet textures: Solar System Scope (CC BY 4.0)
- Planet and Moon positions: NASA/JPL DE440s, via Skyfield
- Satellites: CelesTrak GP data, with SGP4 used for validation
- Asteroids: NASA/JPL SBDB, CNEOS close-approach data and Horizons
- Atmosphere model: Vallado, *Fundamentals of Astrodynamics and Applications*, Table 8-4
- Reference method: H. D. Curtis, *Orbital Mechanics for Engineering Students*

---

## 3. Development

| Task | Command |
|---|---|
| Run the whole test suite (physics groups + server API) | `python -m pytest` |
| Run the classic validation report | `python validation.py` |
| Rebuild the single-file hand-in | `python build_single_file.py` |
| Build the stand-alone Windows app (no Python needed) | `python build_exe.py` → `%USERPROFILE%\LambertStudioBuild` |
| Start only the server (open the address yourself) | `python lambert_studio.py --no-window` |

Each 3D view also has a 📷 button that saves the current view as a PNG.

### Project layout

| Part | Files |
|---|---|
| Core astrodynamics | `constants.py`, `time_utils.py`, `coord_utils.py`, `lambert_solver.py`, `orbital_elements.py`, `frames.py` |
| Planets & missions | `planets.py`, `ephemeris.py`, `interplanetary.py`, `flyby.py`, `maneuvers.py`, `perturb.py` |
| Live data | `satellites.py`, `asteroids.py`, `netcache.py` |
| Application | `studio_server.py` (JSON API), `lambert_studio.py` (window), `web/` (Three.js + Plotly interface) |
| Course deliverable | `app.py`, `dashboard.py`, `viz.py`, `report.py`, `build_single_file.py` → `lambert_problem_solver.py` |
| Quality | `validation.py`, `tests/`, `pyproject.toml`, `build_exe.py` |
