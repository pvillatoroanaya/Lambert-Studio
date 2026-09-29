# Lambert's Problem Solver

Solves Lambert's problem from two topocentric (Azimuth, Elevation, Range)
observations of a satellite, including a GUI and 3D orbit plot.

## What it does

1. **Time handling** (`time_utils.py`) — converts calendar date/UTC time
   to Julian Date and Greenwich Mean Sidereal Time (GMST).
2. **Coordinate conversion** (`coord_utils.py`) — converts topocentric
   Azimuth/Elevation/Range observations (plus the observing station's
   ECEF position) into geocentric equatorial (ECI) position vectors.
3. **Lambert's problem solver** (`lambert_solver.py`) — universal
   variable formulation; given two ECI position vectors and the time of
   flight between them, solves for the velocity vectors.
4. **Orbital elements** (`orbital_elements.py`) — converts a Cartesian
   state vector (r, v) into classical orbital elements
   (a, e, i, RAAN, argument of perigee, true anomaly).
5. **Plotting** (`plot_orbit.py`) — 3D plot of the resulting orbit,
   Earth (to scale), and the two observation points.
6. **GUI** (`gui_app.py`) — tkinter interface to enter both observations
   and the station position, solve, and see the results + plot.

## Requirements

```
pip install -r requirements.txt
```

On some Linux distributions, `tkinter` must be installed separately:

```
sudo apt install python3-tk
```

## Running

**GUI (recommended):**

```
python3 gui_app.py

```

The GUI comes pre-filled with the assignment's example data (station
position and both observations) — press "Solve" to see it work
immediately, then edit the fields for other cases.

**Individual modules** can also each be run directly to see their
output for the example data, e.g.:

```
python3 time_utils.py
python3 coord_utils.py
python3 lambert_solver.py
python3 orbital_elements.py
python3 plot_orbit.py      # saves orbit_plot.png
```

## Assumptions / notes

- Dates are interpreted as **DD/MM/YYYY** by default (matches the
  assignment's `02/04/2023` = 2 April 2023). This can be switched to
  MM/DD/YYYY in the GUI's Options panel.
- UTC is treated as equal to UT1 (the UT1-UTC offset, generally under
  ~1 second, is neglected) when computing GMST.
- The station's latitude/longitude are derived from its given ECEF
  coordinates assuming a **spherical Earth** (no ellipsoid/flattening
  was specified in the assignment data).
- Earth's rotation from ECEF to ECI uses GMST only (no precession,
  nutation, or polar motion) — standard simplification for this scope.
- The Lambert solver defaults to a **prograde, short-way** transfer.
  This can be switched to retrograde/long-way via the `prograde`
  parameter (exposed as a checkbox in the GUI) if the expected answer
  requires the other branch.
- Gravitational parameter used: mu = 398600.4418 km^3/s^2 (Earth).

## Verification performed

- Orbital elements computed independently from (r1, v1) and (r2, v2)
  agree to machine precision (see `orbital_elements.py` output).
- Specific mechanical energy (v^2/2 - mu/r) matches at both points
  (~-7.07 km^2/s^2 for the example data), confirming a physically
  consistent orbit.
- Both observation points lie exactly on the plotted orbit ellipse.
- Full pipeline (parsing -> conversion -> Lambert -> elements -> plot)
  was exercised through the GUI end-to-end with the example data and
  matches the standalone module outputs exactly.


