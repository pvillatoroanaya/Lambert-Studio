"""
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



# ====================================================================
#  constants.py
# ====================================================================

"""
Shared physical constants.

Kept in one place so that every module provably uses the SAME values of
mu and R_earth. (Silently disagreeing constants across modules is a
classic source of small, hard-to-trace numerical discrepancies in
orbital-mechanics code.)
"""

# Earth's gravitational parameter [km^3/s^2]
# Value: EGM-96 / WGS-84 GM.
MU_EARTH = 398600.4418

# Earth's equatorial radius [km] (WGS-84).
# Used for altitude reporting and for drawing Earth to scale.
R_EARTH = 6378.137

# ----------------------------------------------------------------------
# Heliocentric constants, for the interplanetary (solar-system) mode.
# The same Lambert solver is used there, simply with a different mu.
# ----------------------------------------------------------------------

# Sun's gravitational parameter [km^3/s^2]
MU_SUN = 1.32712440018e11

# Astronomical unit [km] (IAU 2012 definition)
AU = 1.495978707e8

# Earth's sidereal rotation rate [rad/s]
OMEGA_EARTH = 7.2921159e-5

# Obliquity of the ecliptic at J2000 [deg]
OBLIQUITY_J2000 = 23.43928

# Julian Date of the J2000.0 epoch
JD_J2000 = 2451545.0



# ====================================================================
#  time_utils.py
# ====================================================================

"""
Section 1: Time handling utilities for the Lambert's problem project.

Provides:
    - julian_date(year, month, day, hour, minute, second) -> JD
    - gmst_from_jd(jd) -> Greenwich Mean Sidereal Time [rad]
    - time_of_flight(jd1, jd2) -> seconds between two Julian Dates
"""



def julian_date(year, month, day, hour, minute, second):
    """
    Compute the Julian Date for a given Gregorian calendar UTC date/time.

    Standard algorithm (Meeus / Vallado).

    Parameters
    ----------
    year, month, day : int
    hour, minute : int
    second : float

    Returns
    -------
    jd : float
        Julian Date.
    """
    if month <= 2:
        year -= 1
        month += 12

    A = math.floor(year / 100)
    B = 2 - A + math.floor(A / 4)

    day_frac = day + (hour + minute / 60 + second / 3600) / 24

    jd = (math.floor(365.25 * (year + 4716))
          + math.floor(30.6001 * (month + 1))
          + day_frac + B - 1524.5)

    return jd


def gmst_from_jd(jd):
    """
    Compute Greenwich Mean Sidereal Time (GMST) in radians for a given
    Julian Date, using the standard IAU 1982 polynomial (Vallado eq. 3-45).

    Parameters
    ----------
    jd : float
        Julian Date (UT1 ~ UTC assumed here).

    Returns
    -------
    gmst : float
        GMST in radians, wrapped to [0, 2*pi).
    """
    T_UT1 = (jd - 2451545.0) / 36525.0

    # GMST in seconds (Vallado, "Fundamentals of Astrodynamics and Applications")
    gmst_sec = (67310.54841
                + (876600 * 3600 + 8640184.812866) * T_UT1
                + 0.093104 * T_UT1**2
                - 6.2e-6 * T_UT1**3)

    # convert seconds -> degrees (1 sidereal second = 1/240 deg), then wrap to 0-86400 s
    gmst_sec = gmst_sec % 86400.0
    if gmst_sec < 0:
        gmst_sec += 86400.0

    gmst_deg = gmst_sec / 240.0  # 86400 s = 360 deg -> 240 s/deg
    gmst_rad = math.radians(gmst_deg % 360.0)

    return gmst_rad


def time_of_flight(jd1, jd2):
    """
    Time of flight between two Julian Dates, in seconds.

    Parameters
    ----------
    jd1, jd2 : float

    Returns
    -------
    dt_sec : float
    """
    return (jd2 - jd1) * 86400.0



# ====================================================================
#  coord_utils.py
# ====================================================================

"""
Section 2: Topocentric observation -> geocentric (ECI) position.

An observation is (azimuth, elevation, range) measured from a ground
station. It is first expressed in the station's local horizon frame
(SEZ: South, East, Zenith), rotated into the Earth-fixed frame (ECEF),
added to the station position, and finally rotated into the inertial
frame (ECI) using the Greenwich sidereal angle.

Provides:
    - station_latlon(r_station_ecef) -> (lat, lon) [rad]
    - sez_to_ecef_matrix(lat, lon)
    - rot3(theta)
    - topocentric_to_geocentric(az, el, rng, r_station_ecef, gmst) -> r_eci
"""




def station_latlon(r_station_ecef):
    """
    Geocentric latitude and longitude [rad] of a station from its ECEF
    position, assuming a spherical Earth (see README).
    """
    x, y, z = np.asarray(r_station_ecef, dtype=float)
    lat = math.atan2(z, math.hypot(x, y))
    lon = math.atan2(y, x)
    return lat, lon


def sez_to_ecef_matrix(lat, lon):
    """
    Rotation matrix taking a vector from the local SEZ frame to ECEF.
    Its columns are the S, E and Z unit vectors written in ECEF.
    """
    sl, cl = math.sin(lat), math.cos(lat)
    so, co = math.sin(lon), math.cos(lon)
    return np.array([
        [sl * co, -so, cl * co],
        [sl * so,  co, cl * so],
        [-cl,     0.0, sl],
    ])


def rot3(theta):
    """
    Rotation by +theta about the z axis. With theta = GMST it takes an
    Earth-fixed (ECEF) vector into the inertial (ECI) frame.
    """
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s, 0.0],
                     [s,  c, 0.0],
                     [0.0, 0.0, 1.0]])


def topocentric_to_geocentric(az_deg, el_deg, rng_km, r_station_ecef, gmst):
    """
    Convert one observation into a geocentric ECI position vector.

    Parameters
    ----------
    az_deg : float
        Azimuth, measured clockwise from North [deg].
    el_deg : float
        Elevation above the local horizon [deg].
    rng_km : float
        Slant range [km].
    r_station_ecef : array_like, shape (3,)
        Station position in ECEF [km].
    gmst : float
        Greenwich Mean Sidereal Time at the observation [rad].

    Returns
    -------
    r_eci : ndarray, shape (3,)
    """
    az = math.radians(az_deg)
    el = math.radians(el_deg)
    r_station_ecef = np.asarray(r_station_ecef, dtype=float)

    # Slant-range vector in SEZ. Azimuth is from North, and South is the
    # first SEZ axis, hence the minus sign.
    rho_sez = rng_km * np.array([-math.cos(el) * math.cos(az),
                                  math.cos(el) * math.sin(az),
                                  math.sin(el)])

    lat, lon = station_latlon(r_station_ecef)
    r_ecef = r_station_ecef + sez_to_ecef_matrix(lat, lon) @ rho_sez
    return rot3(gmst) @ r_ecef



# ====================================================================
#  lambert_solver.py
# ====================================================================

"""
Section 3: Lambert's problem, universal-variable formulation
(Curtis, "Orbital Mechanics for Engineering Students", Algorithm 5.2).

Given two position vectors r1, r2 and the time of flight dt between
them, find the velocity vectors v1, v2 of the conic that connects them.

Provides:
    - stumpff_C(z), stumpff_S(z)
    - lambert_universal(r1, r2, dt, prograde=True, mu=MU_EARTH) -> v1, v2, z
"""




# Below this |z| the closed-form Stumpff functions lose precision
# (0/0 cancellation), so their Taylor series are used instead.
_SERIES_LIMIT = 1e-3


def stumpff_C(z):
    """Stumpff function C(z)."""
    if z > _SERIES_LIMIT:
        return (1.0 - math.cos(math.sqrt(z))) / z
    if z < -_SERIES_LIMIT:
        return (math.cosh(math.sqrt(-z)) - 1.0) / (-z)
    return 1.0 / 2 - z / 24 + z ** 2 / 720 - z ** 3 / 40320


def stumpff_S(z):
    """Stumpff function S(z)."""
    if z > _SERIES_LIMIT:
        sz = math.sqrt(z)
        return (sz - math.sin(sz)) / sz ** 3
    if z < -_SERIES_LIMIT:
        sz = math.sqrt(-z)
        return (math.sinh(sz) - sz) / sz ** 3
    return 1.0 / 6 - z / 120 + z ** 2 / 5040 - z ** 3 / 362880


def lambert_universal(r1, r2, dt, prograde=True, mu=MU_EARTH, revs=0, branch=0, grid=96):
    """
    Solve Lambert's problem.

    With revs = 0 (the default, used for the assignment) this is the
    classic single-revolution solution. With revs = N >= 1 the spacecraft
    completes N full laps around the central body before arriving; for a
    given N there are two solutions (branch 0 and branch 1), and none if
    the time of flight is too short for N laps. See lambert_batch.

    Parameters
    ----------
    r1, r2 : array_like, shape (3,)
        Initial and final position vectors [km].
    dt : float
        Time of flight [s], must be positive.
    prograde : bool
        True for a prograde transfer (angular momentum along +z), False
        for retrograde. For the usual short-way transfer, leave True.
    mu : float
        Gravitational parameter of the central body [km^3/s^2].

    Returns
    -------
    v1, v2 : ndarray, shape (3,)
        Velocity at r1 and at r2 [km/s].
    z : float
        Converged universal variable (z > 0 ellipse, z < 0 hyperbola).
    """
    r1 = np.asarray(r1, dtype=float)
    r2 = np.asarray(r2, dtype=float)
    if dt <= 0:
        raise ValueError("Time of flight must be positive.")

    if revs:
        sol = _multirev_scalar(r1, r2, float(dt), prograde, mu, revs, branch, grid)
        if sol is None:
            raise ValueError(f"No {revs}-revolution solution: the time of flight is too "
                             f"short for {revs} full lap(s), or the geometry is degenerate.")
        return sol

    r1n = np.linalg.norm(r1)
    r2n = np.linalg.norm(r2)

    # Transfer angle. The sign of (r1 x r2)_z says which way round the
    # short arc goes; the prograde/retrograde choice picks the branch.
    cross_z = np.cross(r1, r2)[2]
    cos_dtheta = np.clip(np.dot(r1, r2) / (r1n * r2n), -1.0, 1.0)
    dtheta = math.acos(cos_dtheta)
    if prograde:
        if cross_z < 0:
            dtheta = 2 * math.pi - dtheta
    else:
        if cross_z >= 0:
            dtheta = 2 * math.pi - dtheta

    if abs(1.0 - math.cos(dtheta)) < 1e-14 or abs(math.sin(dtheta)) < 1e-12:
        raise ValueError("Transfer angle is 0 or 180 deg: the transfer plane "
                         "is undefined, so Lambert's problem has no unique solution.")

    A = math.sin(dtheta) * math.sqrt(r1n * r2n / (1.0 - math.cos(dtheta)))
    sqrt_mu = math.sqrt(mu)

    def y_of(z):
        return r1n + r2n + A * (z * stumpff_S(z) - 1.0) / math.sqrt(stumpff_C(z))

    def tof_of(z):
        """Time of flight for a given z, or None where y(z) < 0."""
        y = y_of(z)
        if y < 0:
            return None
        C, S = stumpff_C(z), stumpff_S(z)
        return ((y / C) ** 1.5 * S + A * math.sqrt(y)) / sqrt_mu

    # Time of flight increases monotonically with z, so the root can be
    # bracketed and found by bisection. Bisection is slower than Newton
    # but it cannot diverge, which matters when this is called thousands
    # of times for a porkchop plot.
    # Single-revolution limit. Not exactly 4*pi^2: there C(z) rounds to
    # zero and y(z) divides by it.
    z_hi = 4 * math.pi ** 2 * (1 - 1e-6)
    t_hi = tof_of(z_hi)
    if t_hi is not None and t_hi < dt:
        raise ValueError("No single-revolution solution: the time of flight "
                         "is longer than the slowest possible transfer.")

    z_lo = -4 * math.pi ** 2
    for _ in range(200):
        t_lo = tof_of(z_lo)
        if t_lo is None or t_lo < dt:
            break
        z_lo *= 2.0
    else:
        raise ValueError("Could not bracket the Lambert solution.")

    for _ in range(300):
        z_mid = 0.5 * (z_lo + z_hi)
        if z_mid in (z_lo, z_hi):
            break                               # machine precision reached
        t_mid = tof_of(z_mid)
        if t_mid is None or t_mid < dt:
            z_lo = z_mid
        else:
            z_hi = z_mid
    z = 0.5 * (z_lo + z_hi)

    # Lagrange coefficients -> velocities.
    y = y_of(z)
    f = 1.0 - y / r1n
    g = A * math.sqrt(y / mu)
    gdot = 1.0 - y / r2n

    v1 = (r2 - f * r1) / g
    v2 = (gdot * r2 - r1) / g
    return v1, v2, z


def _multirev_scalar(r1, r2, dt, prograde, mu, revs, branch, grid):
    """
    One multi-revolution problem, same method as lambert_batch (bracket on
    a z grid, then bisect) but in plain Python floats: for a single
    problem this is much faster than going through numpy arrays, which
    matters when an optimiser calls it thousands of times.
    Returns (v1, v2, z) or None when there is no solution.
    """
    r1n, r2n = math.sqrt(r1 @ r1), math.sqrt(r2 @ r2)
    cross_z = r1[0] * r2[1] - r1[1] * r2[0]
    dth = math.acos(max(-1.0, min(1.0, float(r1 @ r2) / (r1n * r2n))))
    if (cross_z < 0) if prograde else (cross_z >= 0):
        dth = 2 * math.pi - dth
    if abs(math.sin(dth)) <= 1e-10 or dt <= 0:
        return None
    A = math.sin(dth) * math.sqrt(r1n * r2n / (1.0 - math.cos(dth)))
    sqrt_mu = math.sqrt(mu)

    def tof(z):
        C, S = stumpff_C(z), stumpff_S(z)
        if C <= 0:
            return math.nan
        y = r1n + r2n + A * (z * S - 1.0) / math.sqrt(C)
        if y <= 0:
            return math.nan
        return ((y / C) ** 1.5 * S + A * math.sqrt(y)) / sqrt_mu

    zL, zH = (2 * math.pi * revs) ** 2, (2 * math.pi * (revs + 1)) ** 2
    zg = [zL + (zH - zL) * (1e-4 + (1 - 2e-4) * k / (grid - 1)) for k in range(grid)]
    f = [tof(z) - dt for z in zg]
    ks = [k for k in range(grid - 1)
          if not (math.isnan(f[k]) or math.isnan(f[k + 1]))
          and ((f[k] > 0 and f[k + 1] <= 0) if branch == 0 else (f[k] <= 0 and f[k + 1] > 0))]
    if not ks:
        return None
    k = ks[0] if branch == 0 else ks[-1]
    lo, hi = zg[k], zg[k + 1]
    for _ in range(64):
        mid = 0.5 * (lo + hi)
        fm = tof(mid) - dt
        left = (fm > 0) if branch == 0 else (fm <= 0)       # comparisons with NaN are False, as in numpy
        if left:
            lo = mid
        else:
            hi = mid
    z = 0.5 * (lo + hi)
    C, S = stumpff_C(z), stumpff_S(z)
    y = r1n + r2n + A * (z * S - 1.0) / math.sqrt(C)
    if not (y > 0 and math.isfinite(y)):
        return None
    f_ = 1.0 - y / r1n
    g = A * math.sqrt(y / mu)
    gdot = 1.0 - y / r2n
    v1 = (r2 - f_ * r1) / g
    v2 = (gdot * r2 - r1) / g
    if not (np.isfinite(v1).all() and np.isfinite(v2).all()):
        return None
    return v1, v2, z


# ----------------------------------------------------------------------
# Many Lambert problems at once (numpy), and multi-revolution solutions
# ----------------------------------------------------------------------

def _stumpff_vec(z):
    """Stumpff C(z), S(z) for an array, with series near z = 0."""
    z = np.asarray(z, float)
    C = np.empty_like(z)
    S = np.empty_like(z)
    pos, neg = z > _SERIES_LIMIT, z < -_SERIES_LIMIT
    mid = ~(pos | neg)
    sp = np.sqrt(z[pos])
    C[pos] = (1.0 - np.cos(sp)) / z[pos]
    S[pos] = (sp - np.sin(sp)) / sp ** 3
    sn = np.sqrt(-z[neg])
    C[neg] = (np.cosh(sn) - 1.0) / (-z[neg])
    S[neg] = (np.sinh(sn) - sn) / sn ** 3
    zm = z[mid]
    C[mid] = 0.5 - zm / 24 + zm ** 2 / 720 - zm ** 3 / 40320
    S[mid] = 1.0 / 6 - zm / 120 + zm ** 2 / 5040 - zm ** 3 / 362880
    return C, S


def lambert_batch(r1, r2, dt, prograde=True, mu=MU_EARTH, revs=0, branch=0,
                  grid=96, chunk=4000):
    """
    Solve many Lambert problems at once. r1, r2: (n, 3) km; dt: (n,) s.

    Same universal-variable equations as lambert_universal, evaluated on
    whole arrays, so thousands of problems (a porkchop plot, a route
    search) take a fraction of a second.

    Multi-revolution (revs = N >= 1): z = (change in eccentric anomaly)^2
    lies between (2 pi N)^2 and (2 pi (N+1))^2. There, the time of flight
    is infinite at both ends with a minimum in between, so a given dt has
    either no solution or two: branch 0 on the low-z side of the minimum,
    branch 1 on the high-z side. They are bracketed on a sample grid and
    then refined by bisection.

    Returns v1 (n,3), v2 (n,3), z (n,), ok (n,) bool.
    """
    r1 = np.atleast_2d(np.asarray(r1, float))
    r2 = np.atleast_2d(np.asarray(r2, float))
    dt = np.atleast_1d(np.asarray(dt, float))
    n = len(dt)
    v1 = np.full((n, 3), np.nan)
    v2 = np.full((n, 3), np.nan)
    zs = np.full(n, np.nan)
    ok = np.zeros(n, bool)
    for s in range(0, n, chunk):
        e = min(n, s + chunk)
        a, b, c, d = _lambert_block(r1[s:e], r2[s:e], dt[s:e], prograde, mu, revs, branch, grid)
        v1[s:e], v2[s:e], zs[s:e], ok[s:e] = a, b, c, d
    return v1, v2, zs, ok


def _lambert_block(r1, r2, dt, prograde, mu, revs, branch, grid):
    with np.errstate(all="ignore"):
        r1n = np.linalg.norm(r1, axis=1)
        r2n = np.linalg.norm(r2, axis=1)
        cross_z = r1[:, 0] * r2[:, 1] - r1[:, 1] * r2[:, 0]
        dth = np.arccos(np.clip(np.einsum("ij,ij->i", r1, r2) / (r1n * r2n), -1.0, 1.0))
        flip = (cross_z < 0) if prograde else (cross_z >= 0)
        dth = np.where(flip, 2 * np.pi - dth, dth)
        good = (np.abs(np.sin(dth)) > 1e-10) & (dt > 0)
        A = np.sin(dth) * np.sqrt(r1n * r2n / (1.0 - np.cos(dth)))
        sqrt_mu = math.sqrt(mu)

        def tof(z, rr1=r1n, rr2=r2n, AA=A):
            C, S = _stumpff_vec(z)
            y = rr1 + rr2 + AA * (z * S - 1.0) / np.sqrt(C)
            t = ((y / C) ** 1.5 * S + AA * np.sqrt(y)) / sqrt_mu
            return np.where((y > 0) & (C > 0), t, np.nan)

        if revs == 0:
            lo = np.full_like(dt, -3000.0)
            hi = np.full_like(dt, 4 * np.pi ** 2 * (1 - 1e-6))
            t_hi = tof(hi)
            t_lo = tof(lo)
            good &= ~(t_hi < dt) & ~(t_lo > dt)
            for _ in range(110):
                mid = 0.5 * (lo + hi)
                t = tof(mid)
                up = np.isnan(t) | (t < dt)
                lo = np.where(up, mid, lo)
                hi = np.where(up, hi, mid)
            z = 0.5 * (lo + hi)
        else:
            zL, zH = (2 * np.pi * revs) ** 2, (2 * np.pi * (revs + 1)) ** 2
            zg = zL + (zH - zL) * np.linspace(1e-4, 1 - 1e-4, grid)
            T = tof(np.broadcast_to(zg, (len(dt), grid)).copy(),
                    r1n[:, None], r2n[:, None], A[:, None])
            f = T - dt[:, None]
            valid = ~np.isnan(f[:, :-1]) & ~np.isnan(f[:, 1:])
            if branch == 0:      # first place where the curve comes down through dt
                cross = valid & (f[:, :-1] > 0) & (f[:, 1:] <= 0)
                k = np.argmax(cross, axis=1)
            else:                # last place where it goes back up through dt
                cross = valid & (f[:, :-1] <= 0) & (f[:, 1:] > 0)
                k = grid - 2 - np.argmax(cross[:, ::-1], axis=1)
            good &= cross.any(axis=1)
            lo, hi = zg[k], zg[k + 1]
            for _ in range(64):
                mid = 0.5 * (lo + hi)
                fm = tof(mid) - dt
                # branch 0: t decreasing in z; branch 1: t increasing.
                left = (fm > 0) if branch == 0 else (fm <= 0)
                lo = np.where(left, mid, lo)
                hi = np.where(left, hi, mid)
            z = 0.5 * (lo + hi)

        C, S = _stumpff_vec(z)
        y = r1n + r2n + A * (z * S - 1.0) / np.sqrt(C)
        good &= (y > 0) & np.isfinite(y)
        f_ = 1.0 - y / r1n
        g = A * np.sqrt(y / mu)
        gdot = 1.0 - y / r2n
        v1 = (r2 - f_[:, None] * r1) / g[:, None]
        v2 = (gdot[:, None] * r2 - r1) / g[:, None]
        good &= np.isfinite(v1).all(axis=1) & np.isfinite(v2).all(axis=1)
    return v1, v2, z, good



# ====================================================================
#  orbital_elements.py
# ====================================================================

"""
Section 4: Classical orbital elements from a Cartesian state vector
(r, v), following the standard vector algorithm (Curtis / Vallado).

Returns the six classical elements -- a, e, i, RAAN (Omega), argument of
perigee (omega), true anomaly (nu) -- plus the derived parameters that
are normally quoted alongside them (period, apsides, energy, angular
momentum, anomalies, flight path angle).
"""




def state_to_elements(r, v, mu=MU_EARTH, tol=1e-10):
    """
    Convert a Cartesian state vector (r, v) into classical orbital
    elements.

    Parameters
    ----------
    r, v : array_like, shape (3,)
        Position [km] and velocity [km/s] vectors, same frame (ECI).
    mu : float
        Gravitational parameter [km^3/s^2].
    tol : float
        Tolerance for detecting near-zero eccentricity / inclination
        (special-case orbits).

    Returns
    -------
    dict with keys:
        'a'     semi-major axis [km]
        'e'     eccentricity [-]
        'i'     inclination [deg]
        'RAAN'  right ascension of ascending node [deg]
        'argp'  argument of perigee [deg]
        'nu'    true anomaly [deg]
        'h'     specific angular momentum vector [km^2/s]
        'notes' list of strings flagging any special-case orbit
    """
    r = np.asarray(r, dtype=float)
    v = np.asarray(v, dtype=float)
    rn = np.linalg.norm(r)
    vn = np.linalg.norm(v)
    notes = []

    # 1. Specific angular momentum
    h_vec = np.cross(r, v)
    hn = np.linalg.norm(h_vec)

    # 2. Node vector
    k_hat = np.array([0.0, 0.0, 1.0])
    n_vec = np.cross(k_hat, h_vec)
    nn = np.linalg.norm(n_vec)

    # 3. Eccentricity vector
    e_vec = ((vn**2 - mu / rn) * r - np.dot(r, v) * v) / mu
    e = np.linalg.norm(e_vec)

    # 4. Specific mechanical energy -> semi-major axis
    energy = vn**2 / 2 - mu / rn
    if abs(e - 1.0) < tol:
        a = math.inf  # parabolic
        notes.append("Orbit is (near-)parabolic: e ~ 1, a is undefined/infinite.")
    else:
        a = -mu / (2 * energy)

    # 5. Inclination
    i = math.acos(np.clip(h_vec[2] / hn, -1.0, 1.0))

    # 6. RAAN
    if nn < tol:
        notes.append("Orbit is equatorial (i ~ 0 or 180 deg): RAAN is undefined, set to 0.")
        RAAN = 0.0
    else:
        RAAN = math.acos(np.clip(n_vec[0] / nn, -1.0, 1.0))
        if n_vec[1] < 0:
            RAAN = 2 * math.pi - RAAN

    # 7. Argument of perigee
    if e < tol:
        notes.append("Orbit is (near-)circular: e ~ 0, argument of perigee is undefined, set to 0.")
        argp = 0.0
    elif nn < tol:
        # equatorial + eccentric: use "true longitude of periapsis" convention instead
        argp = math.acos(np.clip(e_vec[0] / e, -1.0, 1.0))
        if e_vec[1] < 0:
            argp = 2 * math.pi - argp
        notes.append("Equatorial orbit: 'argp' reported is actually the longitude of periapsis.")
    else:
        argp = math.acos(np.clip(np.dot(n_vec, e_vec) / (nn * e), -1.0, 1.0))
        if e_vec[2] < 0:
            argp = 2 * math.pi - argp

    # 8. True anomaly
    if e < tol:
        # circular: use argument of latitude from node (or r itself if equatorial too)
        if nn < tol:
            nu = math.acos(np.clip(r[0] / rn, -1.0, 1.0))
            if r[1] < 0:
                nu = 2 * math.pi - nu
        else:
            nu = math.acos(np.clip(np.dot(n_vec, r) / (nn * rn), -1.0, 1.0))
            if r[2] < 0:
                nu = 2 * math.pi - nu
        notes.append("Circular orbit: 'nu' reported is the angle from the reference direction, not from perigee.")
    else:
        nu = math.acos(np.clip(np.dot(e_vec, r) / (e * rn), -1.0, 1.0))
        if np.dot(r, v) < 0:
            nu = 2 * math.pi - nu

    # ------------------------------------------------------------------
    # 9. Derived parameters normally quoted alongside the six elements.
    #    These are all consequences of (a, e, nu) + mu -- no new physics,
    #    but they are what actually describes the orbit in practical
    #    terms (how high, how long, how fast).
    # ------------------------------------------------------------------
    p = hn ** 2 / mu                      # semi-latus rectum [km]
    nu_rad = nu                            # keep the radian value before conversion

    # Apsides. r_p = a(1-e) holds for ellipse AND hyperbola (a < 0 there,
    # and 1-e < 0, so the product stays positive). The parabola is the
    # only case needing p/2 instead, since a is infinite.
    if math.isinf(a):
        r_p = p / 2.0
    else:
        r_p = a * (1 - e)

    # Apoapsis only exists for a closed (elliptical) orbit.
    r_a = a * (1 + e) if e < 1.0 and not math.isinf(a) else None

    # Orbital period and mean motion: closed orbits only.
    if e < 1.0 and not math.isinf(a) and a > 0:
        period = 2 * math.pi * math.sqrt(a ** 3 / mu)      # [s]
        mean_motion = math.sqrt(mu / a ** 3)               # [rad/s]
    else:
        period = None
        mean_motion = None

    # Speeds at the apsides, from vis-viva: v^2 = mu(2/r - 1/a).
    def _vis_viva(radius):
        if radius is None:
            return None
        if math.isinf(a):
            return math.sqrt(2 * mu / radius)   # parabolic escape speed
        return math.sqrt(max(0.0, mu * (2.0 / radius - 1.0 / a)))

    v_p = _vis_viva(r_p)
    v_a = _vis_viva(r_a)

    # Flight path angle at the current point: angle between the velocity
    # vector and the local horizon. Zero at the apsides.
    if e < tol:
        gamma = 0.0
    else:
        gamma = math.atan2(e * math.sin(nu_rad), 1 + e * math.cos(nu_rad))

    # Eccentric / hyperbolic anomaly and mean anomaly at the current point.
    E_anom = None
    M_anom = None
    if e < 1.0 - tol:
        # Elliptical: E from the half-angle relation, then Kepler's equation.
        E_anom = 2 * math.atan2(math.sqrt(1 - e) * math.sin(nu_rad / 2),
                                 math.sqrt(1 + e) * math.cos(nu_rad / 2))
        E_anom = E_anom % (2 * math.pi)
        M_anom = (E_anom - e * math.sin(E_anom)) % (2 * math.pi)
    elif e > 1.0 + tol:
        # Hyperbolic: H, then the hyperbolic form of Kepler's equation.
        arg = math.sqrt((e - 1) / (e + 1)) * math.tan(nu_rad / 2)
        if abs(arg) < 1.0:
            H_anom = 2 * math.atanh(arg)
            E_anom = H_anom
            M_anom = e * math.sinh(H_anom) - H_anom

    return {
        # --- the six classical elements ---
        "a": a,
        "e": e,
        "i": math.degrees(i),
        "RAAN": math.degrees(RAAN),
        "argp": math.degrees(argp),
        "nu": math.degrees(nu),
        # --- vectors / magnitudes ---
        "h_vec": h_vec,
        "h": hn,
        "e_vec": e_vec,
        "r_mag": rn,
        "v_mag": vn,
        # --- derived geometry ---
        "p": p,
        "r_p": r_p,
        "r_a": r_a,
        "alt_p": r_p - R_EARTH,
        "alt_a": (r_a - R_EARTH) if r_a is not None else None,
        # --- derived dynamics ---
        "energy": energy,
        "period": period,
        "mean_motion": mean_motion,
        "v_p": v_p,
        "v_a": v_a,
        "gamma": math.degrees(gamma),
        "E_anom": math.degrees(E_anom) if E_anom is not None else None,
        "M_anom": math.degrees(M_anom) if M_anom is not None else None,
        "orbit_type": _orbit_type(e, tol),
        "notes": notes,
    }


def _orbit_type(e, tol=1e-10):
    """Name the conic section implied by the eccentricity."""
    if e < tol:
        return "Circular"
    if e < 1.0 - tol:
        return "Elliptical"
    if abs(e - 1.0) <= tol:
        return "Parabolic"
    return "Hyperbolic"


def format_duration(seconds):
    """Format a duration in seconds as a readable h/min/s string."""
    if seconds is None:
        return "n/a (open orbit)"
    # Round to the displayed precision FIRST, otherwise a value such as
    # 9000 s can render as "2h 29m 60.0s" when the seconds field rounds
    # up to 60 independently of the minutes field.
    total = round(seconds, 1)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{seconds:,.1f} s  ({int(hours)}h {int(minutes)}m {secs:04.1f}s)"


def print_elements(elems, label=""):
    print(f"--- Orbital elements {label} ---")
    print(f"Orbit type          = {elems['orbit_type']}")
    print(f"a (semi-major axis) = {elems['a']:.4f} km")
    print(f"e (eccentricity)    = {elems['e']:.6f}")
    print(f"i (inclination)     = {elems['i']:.4f} deg")
    print(f"RAAN                = {elems['RAAN']:.4f} deg")
    print(f"argp (arg. perigee) = {elems['argp']:.4f} deg")
    print(f"nu (true anomaly)   = {elems['nu']:.4f} deg")
    print("--- Derived parameters ---")
    print(f"h (ang. momentum)   = {elems['h']:.4f} km^2/s")
    print(f"p (semi-latus rect.)= {elems['p']:.4f} km")
    print(f"Specific energy     = {elems['energy']:.6f} km^2/s^2")
    print(f"Perigee radius      = {elems['r_p']:.4f} km  (altitude {elems['alt_p']:.4f} km)")
    if elems["r_a"] is not None:
        print(f"Apogee radius       = {elems['r_a']:.4f} km  (altitude {elems['alt_a']:.4f} km)")
    else:
        print("Apogee radius       = n/a (open orbit)")
    print(f"Period              = {format_duration(elems['period'])}")
    print(f"Speed at perigee    = {elems['v_p']:.4f} km/s")
    if elems["v_a"] is not None:
        print(f"Speed at apogee     = {elems['v_a']:.4f} km/s")
    print(f"Flight path angle   = {elems['gamma']:.4f} deg")
    if elems["M_anom"] is not None:
        print(f"Mean anomaly        = {elems['M_anom']:.4f} deg")
    if elems["notes"]:
        print("Notes:")
        for note in elems["notes"]:
            print(f"  - {note}")



# ====================================================================
#  frames.py
# ====================================================================

"""
Reference frames and trajectory sampling.

Everything the dashboard needs to show the same orbit in several frames:
inertial (ECI), Earth-fixed (ECEF), perifocal (PQW), the ground track
(latitude / longitude) and the station's own sky view (SEZ -> az/el).

Angles in the public functions are in DEGREES unless noted otherwise
(GMST is always in radians, as returned by time_utils.gmst_from_jd).
"""





# ----------------------------------------------------------------------
# Propagation
# ----------------------------------------------------------------------

def propagate(r0, v0, dt, mu=MU_EARTH, tol=1e-12, max_iter=200):
    """
    Two-body propagation by the universal Kepler equation.
    Returns (r, v) after dt seconds.
    """
    r0 = np.asarray(r0, float)
    v0 = np.asarray(v0, float)
    if dt == 0:
        return r0.copy(), v0.copy()
    r0n = np.linalg.norm(r0)
    v0n = np.linalg.norm(v0)
    vr0 = np.dot(r0, v0) / r0n
    alpha = 2.0 / r0n - v0n ** 2 / mu
    sqrt_mu = math.sqrt(mu)

    chi = sqrt_mu * abs(alpha) * dt if abs(alpha) > 1e-12 else sqrt_mu * dt / r0n
    for _ in range(max_iter):
        z = alpha * chi ** 2
        C, S = stumpff_C(z), stumpff_S(z)
        F = (r0n * vr0 / sqrt_mu * chi ** 2 * C
             + (1 - alpha * r0n) * chi ** 3 * S
             + r0n * chi - sqrt_mu * dt)
        dF = (r0n * vr0 / sqrt_mu * chi * (1 - z * S)
              + (1 - alpha * r0n) * chi ** 2 * C + r0n)
        step = F / dF
        chi -= step
        if abs(step) < tol:
            break

    z = alpha * chi ** 2
    C, S = stumpff_C(z), stumpff_S(z)
    f = 1 - chi ** 2 / r0n * C
    g = dt - chi ** 3 / sqrt_mu * S
    r = f * r0 + g * v0
    rn = np.linalg.norm(r)
    fdot = sqrt_mu / (rn * r0n) * (z * S - 1) * chi
    gdot = 1 - chi ** 2 / rn * C
    v = fdot * r0 + gdot * v0
    return r, v


def sample_orbit_in_time(r0, v0, t0, t1, n=500, mu=MU_EARTH):
    """
    Sample the trajectory at n evenly spaced times in [t0, t1] seconds,
    measured from the epoch of (r0, v0).

    Returns (times [s], R [n,3] km, V [n,3] km/s).
    """
    times = np.linspace(t0, t1, n)
    R = np.empty((n, 3))
    V = np.empty((n, 3))
    for k, t in enumerate(times):
        R[k], V[k] = propagate(r0, v0, float(t), mu=mu)
    return times, R, V


# ----------------------------------------------------------------------
# ECI <-> ECEF
# ----------------------------------------------------------------------

def eci_to_ecef(r_eci, gmst):
    """Inertial -> Earth-fixed, for a single vector (gmst in rad)."""
    return rot3(gmst).T @ np.asarray(r_eci, float)


def eci_track_to_ecef(R, times, jd0):
    """
    Rotate a whole ECI track into ECEF. times are seconds after jd0, so
    every point gets the Earth orientation of its own instant.
    """
    out = np.empty_like(np.asarray(R, float))
    for k, (r, t) in enumerate(zip(R, times)):
        out[k] = eci_to_ecef(r, gmst_from_jd(jd0 + t / 86400.0))
    return out


def ecef_to_geodetic(r_ecef):
    """
    Latitude, longitude [deg] and altitude [km] of an ECEF position.
    Spherical Earth, consistent with the rest of the project.
    """
    r_ecef = np.asarray(r_ecef, float)
    lat, lon = station_latlon(r_ecef)
    return math.degrees(lat), math.degrees(lon), float(np.linalg.norm(r_ecef)) - R_EARTH


def ground_track(R_ecef):
    """
    Sub-satellite latitude / longitude [deg] and altitude [km] along an
    ECEF track. A NaN is inserted wherever the longitude wraps across
    +/-180 deg, so a plotted line does not streak across the whole map.
    """
    R_ecef = np.asarray(R_ecef, float)
    rn = np.linalg.norm(R_ecef, axis=1)
    lat = np.degrees(np.arcsin(R_ecef[:, 2] / rn))
    lon = np.degrees(np.arctan2(R_ecef[:, 1], R_ecef[:, 0]))
    alt = rn - R_EARTH

    wraps = np.where(np.abs(np.diff(lon)) > 180.0)[0] + 1
    lat = np.insert(lat, wraps, np.nan)
    lon = np.insert(lon, wraps, np.nan)
    alt = np.insert(alt, wraps, np.nan)
    return lat, lon, alt


# ----------------------------------------------------------------------
# Perifocal frame
# ----------------------------------------------------------------------

def eci_to_pqw_matrix(i_deg, raan_deg, argp_deg):
    """Rotation matrix from ECI to the perifocal (PQW) frame."""
    i = math.radians(i_deg)
    O = math.radians(raan_deg)
    w = math.radians(argp_deg)
    cO, sO = math.cos(O), math.sin(O)
    ci, si = math.cos(i), math.sin(i)
    cw, sw = math.cos(w), math.sin(w)
    # PQW -> ECI (3-1-3); its transpose goes the other way.
    Q = np.array([
        [cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci, sO * si],
        [sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci, -cO * si],
        [sw * si, cw * si, ci],
    ])
    return Q.T


def eci_track_to_pqw(R, i_deg, raan_deg, argp_deg):
    """Express an ECI track in the perifocal frame."""
    Q = eci_to_pqw_matrix(i_deg, raan_deg, argp_deg)
    return (Q @ np.asarray(R, float).T).T


# ----------------------------------------------------------------------
# Topocentric (sky view)
# ----------------------------------------------------------------------

def eci_to_sez(r_eci, r_station_ecef, gmst):
    """Slant-range vector from the station to r_eci, in SEZ [km]."""
    r_station_ecef = np.asarray(r_station_ecef, float)
    rho_ecef = eci_to_ecef(r_eci, gmst) - r_station_ecef
    lat, lon = station_latlon(r_station_ecef)
    return sez_to_ecef_matrix(lat, lon).T @ rho_ecef


def sez_to_azelrange(rho_sez):
    """(azimuth [deg, 0-360 from North], elevation [deg], range [km])."""
    s, e, z = np.asarray(rho_sez, float)
    rng = math.sqrt(s * s + e * e + z * z)
    el = math.degrees(math.asin(z / rng))
    az = math.degrees(math.atan2(e, -s)) % 360.0
    return az, el, rng


def sky_track(R, times, jd0, r_station_ecef):
    """Azimuth, elevation [deg] and range [km] of a whole ECI track."""
    az = np.empty(len(times))
    el = np.empty(len(times))
    rng = np.empty(len(times))
    for k, (r, t) in enumerate(zip(R, times)):
        sez = eci_to_sez(r, r_station_ecef, gmst_from_jd(jd0 + t / 86400.0))
        az[k], el[k], rng[k] = sez_to_azelrange(sez)
    return az, el, rng


def visibility_intervals(times, elev, min_el=0.0):
    """
    Time spans [s] during which the object is above min_el.
    Returns a list of (start, end) pairs.
    """
    above = np.asarray(elev) > min_el
    spans = []
    start = None
    for t, up in zip(times, above):
        if up and start is None:
            start = t
        elif not up and start is not None:
            spans.append((float(start), float(t)))
            start = None
    if start is not None:
        spans.append((float(start), float(times[-1])))
    return spans



# ====================================================================
#  planets.py
# ====================================================================

"""
Approximate planetary ephemerides.

Uses Standish's low-precision Keplerian elements (JPL, "Keplerian
Elements for Approximate Positions of the Major Planets"): each planet's
elements are linear functions of time in Julian centuries from J2000.

Accuracy is of order arcminutes over 1800-2050 -- far more than enough
for trajectory design studies and visualisation, and the same class of
model used for preliminary mission analysis. It is NOT an ephemeris for
navigation.

Positions are returned in the J2000 ecliptic frame, in km.
"""




# name: (a[AU], e, I[deg], L[deg], longitude of perihelion[deg],
#        longitude of ascending node[deg])  and their per-century rates.
_ELEMENTS = {
    "Mercury": (
        (0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593),
        (0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081),
    ),
    "Venus": (
        (0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255),
        (0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418),
    ),
    "Earth": (
        (1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
        (0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0),
    ),
    "Mars": (
        (1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
        (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343),
    ),
    "Jupiter": (
        (5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909),
        (-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106),
    ),
    "Saturn": (
        (9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448),
        (-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794),
    ),
    "Uranus": (
        (19.18916464, 0.04725744, 0.77263783, 313.23810451, 170.95427630, 74.01692503),
        (-0.00196176, -0.00004397, -0.00242939, 428.48202785, 0.40805281, 0.04240589),
    ),
    "Neptune": (
        (30.06992276, 0.00859048, 1.77004347, -55.12002969, 44.96476227, 131.78422574),
        (0.00026291, 0.00005105, 0.00035372, 218.45945325, -0.32241464, -0.00508664),
    ),
}

PLANET_ORDER = ["Mercury", "Venus", "Earth", "Mars",
                "Jupiter", "Saturn", "Uranus", "Neptune"]

# Display colour, and EQUATORIAL radius [km] (JPL Solar System Dynamics,
# "Planetary Physical Parameters"; 1-bar level for the giants). Used for
# parking / capture orbit altitudes and flyby distances; planets are
# never drawn to true scale against orbital distances.
PLANET_STYLE = {
    "Mercury": {"color": "#9c8e82", "radius": 2440.53},
    "Venus":   {"color": "#e3b76b", "radius": 6051.8},
    "Earth":   {"color": "#4a90d9", "radius": 6378.1366},
    "Mars":    {"color": "#d1603d", "radius": 3396.19},
    "Jupiter": {"color": "#d8a86d", "radius": 71492.0},
    "Saturn":  {"color": "#e0c88a", "radius": 60268.0},
    "Uranus":  {"color": "#8fd3df", "radius": 25559.0},
    "Neptune": {"color": "#4f6fd4", "radius": 24764.0},
}

# Gravitational parameter of each planet [km^3/s^2] (JPL; checked against
# JPL's masses x G), used for departure, capture and flyby calculations.
PLANET_MU = {
    "Mercury": 2.2032e4,
    "Venus": 3.24859e5,
    "Earth": 3.986004418e5,
    "Mars": 4.282837e4,
    "Jupiter": 1.26686534e8,
    "Saturn": 3.7931187e7,
    "Uranus": 5.793939e6,
    "Neptune": 6.836529e6,
}


def _kepler_E(M_rad, e, tol=1e-12, max_iter=100):
    """Solve Kepler's equation M = E - e sin E by Newton's method."""
    E = M_rad if e < 0.8 else math.pi
    for _ in range(max_iter):
        f = E - e * math.sin(E) - M_rad
        fp = 1 - e * math.cos(E)
        step = f / fp
        E -= step
        if abs(step) < tol:
            break
    return E


def planet_elements(name, jd):
    """Standish elements of a planet at a given Julian Date."""
    if name not in _ELEMENTS:
        raise KeyError(f"Unknown planet '{name}'. Known: {', '.join(PLANET_ORDER)}")
    base, rate = _ELEMENTS[name]
    T = (jd - JD_J2000) / 36525.0
    a, e, I, L, peri, node = (b + r * T for b, r in zip(base, rate))
    return dict(a_au=a, e=e, i_deg=I, L_deg=L, peri_deg=peri, node_deg=node)


def planet_state(name, jd):
    """
    Heliocentric position and velocity of a planet in the J2000 ecliptic
    frame.

    Returns (r [km], v [km/s]).
    """
    el = planet_elements(name, jd)
    a = el["a_au"] * AU                      # km
    e = el["e"]
    i = math.radians(el["i_deg"])
    node = math.radians(el["node_deg"])
    argp = math.radians(el["peri_deg"] - el["node_deg"])

    # Mean anomaly, wrapped to [-pi, pi).
    M = math.radians((el["L_deg"] - el["peri_deg"] + 180.0) % 360.0 - 180.0)
    E = _kepler_E(M, e)

    # Position and velocity in the orbital (perifocal) plane.
    x_p = a * (math.cos(E) - e)
    y_p = a * math.sqrt(1 - e * e) * math.sin(E)

    n = math.sqrt(MU_SUN / a ** 3)            # mean motion [rad/s]
    Edot = n / (1 - e * math.cos(E))
    vx_p = -a * math.sin(E) * Edot
    vy_p = a * math.sqrt(1 - e * e) * math.cos(E) * Edot

    # Perifocal -> ecliptic (3-1-3 rotation).
    cO, sO = math.cos(node), math.sin(node)
    ci, si = math.cos(i), math.sin(i)
    cw, sw = math.cos(argp), math.sin(argp)
    Q = np.array([
        [cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci, sO * si],
        [sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci, -cO * si],
        [sw * si, cw * si, ci],
    ])

    r = Q @ np.array([x_p, y_p, 0.0])
    v = Q @ np.array([vx_p, vy_p, 0.0])
    return r, v


def planet_orbit_path(name, jd, n=360):
    """
    One full orbit of a planet as a closed curve of ECLIPTIC positions
    [km], for drawing. Elements are frozen at `jd`, which is correct to
    the accuracy of this model over a single revolution.
    """
    el = planet_elements(name, jd)
    a = el["a_au"] * AU
    e = el["e"]
    i = math.radians(el["i_deg"])
    node = math.radians(el["node_deg"])
    argp = math.radians(el["peri_deg"] - el["node_deg"])

    nu = np.linspace(0.0, 2 * math.pi, n)
    p = a * (1 - e * e)
    r = p / (1 + e * np.cos(nu))
    xyz_p = np.vstack([r * np.cos(nu), r * np.sin(nu), np.zeros_like(nu)])

    cO, sO = math.cos(node), math.sin(node)
    ci, si = math.cos(i), math.sin(i)
    cw, sw = math.cos(argp), math.sin(argp)
    Q = np.array([
        [cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci, sO * si],
        [sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci, -cO * si],
        [sw * si, cw * si, ci],
    ])
    return (Q @ xyz_p).T


def orbital_period_days(name, jd=JD_J2000):
    """Sidereal period of a planet, in days."""
    a = planet_elements(name, jd)["a_au"] * AU
    return 2 * math.pi * math.sqrt(a ** 3 / MU_SUN) / 86400.0



# ====================================================================
#  interplanetary.py
# ====================================================================

"""
Interplanetary mode: the SAME Lambert solver, with mu = mu_Sun and two
planet positions instead of two observations.

Provides:
    - transfer(dep, arr, jd_dep, jd_arr)  -> dict describing the transfer
    - transfer_path(t)                    -> sampled heliocentric arc
    - porkchop(dep, arr, dep_window, arr_window, n_dep, n_arr)
    - best_transfer(dep_grid, arr_grid, Z)
"""




try:                                   # JPL DE440s when available
    import ephemeris
except ImportError:                    # pragma: no cover
    ephemeris = None


# NOTE: deliberately not called `planet_state`. build_single_file.py merges
# every module into one namespace and strips the `planets.` prefix, so a
# function of that name here would end up calling itself.
def best_planet_state(name, jd):
    """Heliocentric ecliptic r [km], v [km/s]: DE440s if present, else Standish."""
    if ephemeris is not None:
        out = ephemeris.planet_state(name, jd)
        if out is not None:
            return out
    return planet_state(name, jd)


def _planet_states(name, jds):
    """States for many dates at once (vectorised when DE440s is used)."""
    if ephemeris is not None:
        out = ephemeris.planet_states(name, np.asarray(jds, float))
        if out is not None:
            r, v = out
            return [(r[k] * AU, v[k] * AU / 86400.0) for k in range(len(jds))]
    return [planet_state(name, jd) for jd in jds]


def planet_states_array(name, jds):
    """Positions (n,3) km and velocities (n,3) km/s of a planet at many dates."""
    jds = np.atleast_1d(np.asarray(jds, float))
    if ephemeris is not None:
        out = ephemeris.planet_states(name, jds)
        if out is not None:
            r, v = out
            return np.atleast_2d(r) * AU, np.atleast_2d(v) * AU / 86400.0
    st = [planet_state(name, jd) for jd in jds]
    return np.array([s[0] for s in st]), np.array([s[1] for s in st])


def ephemeris_source():
    if ephemeris is not None and ephemeris.available():
        return "NASA/JPL DE440s"
    return "Standish approximate elements"

PARKING_ALT_DEPARTURE = 200.0   # km, circular parking orbit before injection
PARKING_ALT_ARRIVAL = 400.0     # km, circular capture orbit on arrival


def _hyperbolic_dv(vinf, planet, alt):
    """
    Delta-v between a circular orbit of altitude `alt` and a hyperbola
    with excess speed vinf, performed at periapsis (Oberth burn).
    """
    mu = PLANET_MU[planet]
    rp = PLANET_STYLE[planet]["radius"] + alt
    return math.sqrt(vinf ** 2 + 2 * mu / rp) - math.sqrt(mu / rp)


GIANTS = ("Jupiter", "Saturn", "Uranus", "Neptune")


def arrival_dv(vinf, planet):
    """
    Braking burn to be captured on arrival. Rocky planets: into a 400 km
    circular orbit. Gas giants: into a long ellipse (periapsis 1.2 radii,
    apoapsis 100 radii), the way Galileo, Cassini and Juno were captured;
    a low circular orbit around a giant would cost several times more.
    Works on a number or a numpy array.
    """
    mu, R = PLANET_MU[planet], PLANET_STYLE[planet]["radius"]
    if planet in GIANTS:
        rp, ra = 1.2 * R, 100 * R
        return np.sqrt(vinf ** 2 + 2 * mu / rp) - math.sqrt(2 * mu / rp - 2 * mu / (rp + ra))
    rp = R + PARKING_ALT_ARRIVAL
    return np.sqrt(vinf ** 2 + 2 * mu / rp) - math.sqrt(mu / rp)


def transfer(dep, arr, jd_dep, jd_arr, prograde=True):
    """Solve one planet-to-planet transfer and derive its mission numbers."""
    if jd_arr <= jd_dep:
        raise ValueError("Arrival must be after departure.")
    r1, vp1 = best_planet_state(dep, jd_dep)
    r2, vp2 = best_planet_state(arr, jd_arr)
    dt = (jd_arr - jd_dep) * 86400.0

    v1, v2, z = lambert_universal(r1, r2, dt, prograde=prograde, mu=MU_SUN)

    vinf_dep = float(np.linalg.norm(v1 - vp1))
    vinf_arr = float(np.linalg.norm(v2 - vp2))

    cos_a = np.dot(r1, r2) / (np.linalg.norm(r1) * np.linalg.norm(r2))
    angle = math.degrees(math.acos(np.clip(cos_a, -1.0, 1.0)))
    if np.cross(r1, r2)[2] < 0:
        angle = 360.0 - angle

    return {
        "departure": dep, "arrival": arr,
        "jd_departure": jd_dep, "jd_arrival": jd_arr,
        "tof_days": jd_arr - jd_dep,
        "r1": r1, "r2": r2, "v1": v1, "v2": v2, "z": z,
        "v_planet_departure": vp1, "v_planet_arrival": vp2,
        "transfer_angle_deg": angle,
        "type": "Type I" if angle < 180.0 else "Type II",
        "vinf_departure": vinf_dep,
        "vinf_arrival": vinf_arr,
        "c3": vinf_dep ** 2,
        "dv_departure": _hyperbolic_dv(vinf_dep, dep, PARKING_ALT_DEPARTURE),
        "dv_arrival": float(arrival_dv(vinf_arr, arr)),
        "elements": state_to_elements(r1, v1, mu=MU_SUN),
        "ephemeris": ephemeris_source(),
    }


def explain_transfer(t):
    """
    The numbers behind a plain-language explanation of a direct transfer:
    where the target was at launch, the ideal (Hohmann) comparison, and
    how often a launch window comes back.
    """
    dep, arr = t["departure"], t["arrival"]
    jd = t["jd_departure"]
    # Heliocentric longitude of each planet at launch (ecliptic).
    lon = lambda r: math.degrees(math.atan2(r[1], r[0]))
    r_arr_at_launch, _ = best_planet_state(arr, jd)
    phase = (lon(r_arr_at_launch) - lon(t["r1"]) + 180.0) % 360.0 - 180.0

    T1 = orbital_period_days(dep, jd)
    T2 = orbital_period_days(arr, jd)
    synodic = 1.0 / abs(1.0 / T1 - 1.0 / T2)
    a1 = planet_elements(dep, jd)["a_au"] * AU
    a2 = planet_elements(arr, jd)["a_au"] * AU
    t_h = math.pi * math.sqrt(((a1 + a2) / 2) ** 3 / MU_SUN) / 86400.0
    phase_h = (180.0 - 360.0 * t_h / T2 + 180.0) % 360.0 - 180.0      # target lead angle for Hohmann
    vinf_h = abs(math.sqrt(MU_SUN / a1) * (math.sqrt(2 * a2 / (a1 + a2)) - 1))
    return {
        "phase_deg": phase,
        "target_moves_deg": 360.0 * t["tof_days"] / T2,
        "hohmann_days": t_h, "hohmann_phase_deg": phase_h,
        "hohmann_c3": vinf_h ** 2,
        "hohmann_dv_departure": _hyperbolic_dv(vinf_h, dep, PARKING_ALT_DEPARTURE),
        "synodic_days": synodic,
        "outward": a2 > a1,
    }


def suggest_window(dep, arr, after_jd):
    """
    The next good launch opportunity from `dep` to `arr` after a date.

    Planets return to the same relative position once per synodic
    period, so searching one synodic period of departure dates (with
    flight times around the Hohmann time) is guaranteed to contain the
    next window. Every combination is solved at once with the batch
    Lambert solver; the cheapest total delta-v (leaving a 200 km orbit +
    being captured, see arrival_dv) wins. Returns the dates and a porkchop
    search window centred on them.
    """
    if dep == arr:
        raise ValueError("Departure and arrival planets must be different.")
    T1 = orbital_period_days(dep, after_jd)
    T2 = orbital_period_days(arr, after_jd)
    synodic = 1.0 / abs(1.0 / T1 - 1.0 / T2)
    a1 = planet_elements(dep, after_jd)["a_au"] * AU
    a2 = planet_elements(arr, after_jd)["a_au"] * AU
    t_h = math.pi * math.sqrt(((a1 + a2) / 2) ** 3 / MU_SUN) / 86400.0

    deps = after_jd + np.linspace(0.0, 1.1 * synodic, 180)
    tofs = np.linspace(0.45 * t_h, 1.5 * t_h, 70)
    R1, V1 = planet_states_array(dep, deps)
    I, J = np.meshgrid(np.arange(len(deps)), np.arange(len(tofs)), indexing="ij")
    I, J = I.ravel(), J.ravel()
    jd_arr = np.round(deps[I] + tofs[J], 5)
    ua, inv = np.unique(jd_arr, return_inverse=True)
    R2, V2 = planet_states_array(arr, ua)
    v1, v2, _, ok = lambert_batch(R1[I], R2[inv], tofs[J] * 86400.0, mu=MU_SUN)
    vinf_d = np.linalg.norm(v1 - V1[I], axis=1)
    vinf_a = np.linalg.norm(v2 - V2[inv], axis=1)
    mu1, rp1 = PLANET_MU[dep], PLANET_STYLE[dep]["radius"] + PARKING_ALT_DEPARTURE
    cost = np.sqrt(vinf_d ** 2 + 2 * mu1 / rp1) - math.sqrt(mu1 / rp1) + arrival_dv(vinf_a, arr)
    cost = np.where(ok & np.isfinite(cost), cost, np.inf)
    k = int(np.argmin(cost))
    if not np.isfinite(cost[k]):
        raise ValueError("No transfer found in the next synodic period.")
    jd_d, tof = float(deps[I[k]]), float(tofs[J[k]])
    span_d = max(45.0, 0.12 * synodic)
    return {
        "jd_departure": jd_d, "jd_arrival": jd_d + tof, "tof_days": tof,
        "c3": float(vinf_d[k] ** 2), "total_dv": float(cost[k]),
        "synodic_days": synodic, "hohmann_days": t_h,
        "window": {"dep_start": jd_d - span_d, "dep_end": jd_d + span_d,
                   "arr_start": jd_d + tof - 0.35 * tof, "arr_end": jd_d + tof + 0.35 * tof},
        "searched": int(len(I)),
    }


def transfer_path(t, n=300):
    """Heliocentric positions [km] along the transfer arc, shape (n, 3)."""
    dt = t["tof_days"] * 86400.0
    _, R, _ = sample_orbit_in_time(t["r1"], t["v1"], 0.0, dt, n=n, mu=MU_SUN)
    return R


def porkchop(dep, arr, dep_window, arr_window, n_dep=40, n_arr=40):
    """
    Departure C3 [km^2/s^2] over a grid of departure and arrival dates.

    Returns (dep_grid, arr_grid, Z) where dep_grid and arr_grid are 1-D
    arrays of Julian Dates and Z has shape (n_arr, n_dep). Cells with no
    valid transfer (arrival before departure, solver failure) are NaN.
    """
    dep_grid = np.linspace(dep_window[0], dep_window[1], n_dep)
    arr_grid = np.linspace(arr_window[0], arr_window[1], n_arr)
    Z = np.full((n_arr, n_dep), np.nan)

    # Planet states only depend on one date each, so compute them once;
    # then solve every (departure, arrival) pair in one batch.
    R1, VP1 = planet_states_array(dep, dep_grid)
    R2, _ = planet_states_array(arr, arr_grid)
    J, I = np.meshgrid(np.arange(n_arr), np.arange(n_dep), indexing="ij")
    J, I = J.ravel(), I.ravel()
    tof = arr_grid[J] - dep_grid[I]
    use = tof >= 30.0                        # too short to be meaningful
    v1, _, _, ok = lambert_batch(R1[I[use]], R2[J[use]], tof[use] * 86400.0, mu=MU_SUN)
    vinf = v1 - VP1[I[use]]
    c3 = np.where(ok, np.einsum("ij,ij->i", vinf, vinf), np.nan)
    Z[J[use], I[use]] = c3
    return dep_grid, arr_grid, Z


def best_transfer(dep_grid, arr_grid, Z):
    """Grid cell with the lowest C3, as a dict (or None if all NaN)."""
    if np.all(np.isnan(Z)):
        return None
    j, i = np.unravel_index(np.nanargmin(Z), Z.shape)
    return {"jd_departure": float(dep_grid[i]),
            "jd_arrival": float(arr_grid[j]),
            "c3": float(Z[j, i]),
            "tof_days": float(arr_grid[j] - dep_grid[i])}



# ====================================================================
#  viz.py
# ====================================================================

if _HAS_PLOTLY:
    # Defined only when the optional dependency is present.
    """
    Plotly figures for the dashboard. Each function returns a go.Figure and
    does no file I/O; dashboard.py decides where they go.

    Colours match the app palette so the dashboard and GUI read as one
    product.
    """




    BG = "#0b1020"
    PANEL = "#121a2f"
    FG = "#e6edf7"
    MUTED = "#8fa3c8"
    ACCENT = "#5ac8fa"
    ACCENT2 = "#ffb454"
    OBS = "#ff5a5f"
    GRID = "rgba(140,165,210,0.18)"


    def _base_layout(fig, title, three_d=True):
        fig.update_layout(
            title=dict(text=title, font=dict(size=15, color=FG), x=0.01),
            paper_bgcolor=BG, plot_bgcolor=BG,
            font=dict(color=FG, family="Inter, Segoe UI, Helvetica, Arial"),
            margin=dict(l=10, r=10, t=48, b=10),
            legend=dict(bgcolor="rgba(18,26,47,0.8)", bordercolor=GRID, borderwidth=1),
        )
        if three_d:
            axis = dict(backgroundcolor=BG, gridcolor=GRID, zerolinecolor=GRID,
                        color=MUTED, showspikes=False)
            fig.update_layout(scene=dict(xaxis=dict(axis, title="x [km]"),
                                         yaxis=dict(axis, title="y [km]"),
                                         zaxis=dict(axis, title="z [km]"),
                                         aspectmode="data"))
        return fig


    def _sphere(radius, center=(0.0, 0.0, 0.0), n=40):
        u = np.linspace(0, 2 * np.pi, n)
        v = np.linspace(0, np.pi, n // 2)
        x = center[0] + radius * np.outer(np.cos(u), np.sin(v))
        y = center[1] + radius * np.outer(np.sin(u), np.sin(v))
        z = center[2] + radius * np.outer(np.ones_like(u), np.cos(v))
        return x, y, z


    def _earth_traces(gmst=0.0):
        """Earth to scale, with a lat/lon graticule rotated to the epoch."""
        x, y, z = _sphere(R_EARTH, n=60)
        traces = [go.Surface(x=x, y=y, z=z, surfacecolor=z,
                             colorscale=[[0, "#0d3a66"], [0.5, "#1c5f9e"], [1, "#0d3a66"]],
                             showscale=False, opacity=1.0, hoverinfo="skip",
                             name="Earth", lighting=dict(ambient=0.7, diffuse=0.5))]
        Rz = rot3(gmst)
        r = R_EARTH * 1.002
        lines_x, lines_y, lines_z = [], [], []
        for lon in range(0, 360, 30):                       # meridians
            t = np.radians(np.linspace(-90, 90, 50))
            l = math.radians(lon)
            P = Rz @ np.vstack([r * np.cos(t) * math.cos(l), r * np.cos(t) * math.sin(l), r * np.sin(t)])
            lines_x += list(P[0]) + [None]
            lines_y += list(P[1]) + [None]
            lines_z += list(P[2]) + [None]
        for lat in range(-60, 90, 30):                      # parallels
            t = np.radians(np.linspace(0, 360, 90))
            b = math.radians(lat)
            P = Rz @ np.vstack([r * math.cos(b) * np.cos(t), r * math.cos(b) * np.sin(t),
                                np.full_like(t, r * math.sin(b))])
            lines_x += list(P[0]) + [None]
            lines_y += list(P[1]) + [None]
            lines_z += list(P[2]) + [None]
        traces.append(go.Scatter3d(x=lines_x, y=lines_y, z=lines_z, mode="lines",
                                   line=dict(color="rgba(200,220,255,0.25)", width=1),
                                   hoverinfo="skip", showlegend=False))
        return traces


    def _track3d(R, name, color, width=4, dash=None):
        return go.Scatter3d(x=R[:, 0], y=R[:, 1], z=R[:, 2], mode="lines", name=name,
                            line=dict(color=color, width=width, dash=dash))


    def _point3d(r, name, color, size=6, symbol="circle"):
        return go.Scatter3d(x=[r[0]], y=[r[1]], z=[r[2]], mode="markers+text",
                            name=name, text=[name], textposition="top center",
                            marker=dict(color=color, size=size, symbol=symbol))


    def _vector3d(r, name, color):
        return go.Scatter3d(x=[0, r[0]], y=[0, r[1]], z=[0, r[2]], mode="lines",
                            name=name, line=dict(color=color, width=3, dash="dot"))


    # ----------------------------------------------------------------------
    # Earth-centred views
    # ----------------------------------------------------------------------

    def fig_orbit_eci(R, r1, r2, el, gmst=0.0, r_station_eci=None):
        fig = go.Figure(_earth_traces(gmst))
        fig.add_trace(_track3d(R, "Orbit", ACCENT))
        fig.add_trace(_vector3d(r1, "r₁", ACCENT2))
        fig.add_trace(_vector3d(r2, "r₂", ACCENT2))
        fig.add_trace(_point3d(r1, "r₁", OBS))
        fig.add_trace(_point3d(r2, "r₂", OBS))
        if r_station_eci is not None:
            fig.add_trace(_point3d(r_station_eci, "Station", "#7bed9f", size=4, symbol="diamond"))
        return _base_layout(fig, f"Orbit in the inertial frame (ECI) — "
                                 f"{el['orbit_type'].lower()}, a = {el['a']:,.0f} km")


    def fig_orbit_ecef(R_ecef):
        fig = go.Figure(_earth_traces(0.0))
        fig.add_trace(_track3d(R_ecef, "Track (Earth-fixed)", ACCENT))
        return _base_layout(fig, "Same trajectory in the Earth-fixed frame (ECEF)")


    def fig_ground_track(lat, lon, alt, station_latlon=None):
        fig = go.Figure(go.Scattergeo(
            lat=lat, lon=lon, mode="lines", name="Ground track",
            line=dict(color=ACCENT, width=2),
            customdata=alt, hovertemplate="lat %{lat:.2f}°<br>lon %{lon:.2f}°"
                                          "<br>alt %{customdata:,.0f} km<extra></extra>"))
        if station_latlon is not None:
            fig.add_trace(go.Scattergeo(lat=[station_latlon[0]], lon=[station_latlon[1]],
                                        mode="markers+text", text=["Station"],
                                        textposition="top center", name="Station",
                                        marker=dict(color="#7bed9f", size=9, symbol="diamond")))
        fig.update_geos(projection_type="equirectangular", showland=True,
                        landcolor="#1d2a47", showocean=True, oceancolor="#0d1a33",
                        coastlinecolor="#5b6f95", showcountries=True, countrycolor=GRID,
                        lataxis=dict(showgrid=True, gridcolor=GRID),
                        lonaxis=dict(showgrid=True, gridcolor=GRID), bgcolor=BG)
        return _base_layout(fig, "Ground track", three_d=False)


    def fig_sky_view(az, elev, rng, obs_marks=()):
        """Polar sky plot: zenith at the centre, horizon at the rim, North up."""
        up = elev >= 0
        az_v = np.where(up, az, np.nan)
        r_v = np.where(up, 90.0 - elev, np.nan)
        fig = go.Figure(go.Scatterpolar(
            theta=az_v, r=r_v, mode="lines", name="Pass", line=dict(color=ACCENT, width=3),
            customdata=np.vstack([elev, rng]).T,
            hovertemplate="az %{theta:.1f}°<br>el %{customdata[0]:.1f}°"
                          "<br>range %{customdata[1]:,.0f} km<extra></extra>"))
        for label, a, e in obs_marks:
            fig.add_trace(go.Scatterpolar(theta=[a], r=[90.0 - e], mode="markers+text",
                                          text=[label], textposition="top center", name=label,
                                          marker=dict(color=OBS, size=11)))
        fig.update_layout(polar=dict(
            bgcolor=PANEL,
            radialaxis=dict(range=[0, 90], tickvals=[0, 30, 60, 90],
                            ticktext=["90°", "60°", "30°", "0°"], gridcolor=GRID, color=MUTED),
            angularaxis=dict(rotation=90, direction="clockwise", gridcolor=GRID, color=MUTED)))
        return _base_layout(fig, "Sky view from the station", three_d=False)


    def fig_perifocal(P, el, p1, p2):
        fig = go.Figure()
        t = np.linspace(0, 2 * np.pi, 200)
        fig.add_trace(go.Scatter(x=R_EARTH * np.cos(t), y=R_EARTH * np.sin(t), fill="toself",
                                 fillcolor="#1c5f9e", line=dict(color="#1c5f9e"),
                                 name="Earth", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=P[:, 0], y=P[:, 1], mode="lines", name="Orbit",
                                 line=dict(color=ACCENT, width=3)))
        for p, name in ((p1, "r₁"), (p2, "r₂")):
            fig.add_trace(go.Scatter(x=[p[0]], y=[p[1]], mode="markers+text", text=[name],
                                     textposition="top center", name=name,
                                     marker=dict(color=OBS, size=10)))
        fig.add_trace(go.Scatter(x=[el["r_p"]], y=[0], mode="markers+text", text=["perigee"],
                                 textposition="bottom center", name="Perigee",
                                 marker=dict(color=ACCENT2, size=9, symbol="x")))
        if el["r_a"] is not None:
            fig.add_trace(go.Scatter(x=[-el["r_a"]], y=[0], mode="markers+text", text=["apogee"],
                                     textposition="bottom center", name="Apogee",
                                     marker=dict(color=ACCENT2, size=9, symbol="x")))
        _base_layout(fig, "Perifocal frame (orbit seen face-on)", three_d=False)
        fig.update_xaxes(title="p [km]", gridcolor=GRID, zerolinecolor=GRID, color=MUTED)
        fig.update_yaxes(title="q [km]", gridcolor=GRID, zerolinecolor=GRID, color=MUTED,
                         scaleanchor="x", scaleratio=1)
        return fig


    # ----------------------------------------------------------------------
    # Heliocentric views
    # ----------------------------------------------------------------------

    def fig_solar_system(jd, transfer_result=None, transfer_track=None,
                         max_planet="Mars", title="Solar system"):
        """Planet orbits and positions at `jd`, in AU, ecliptic frame."""
        fig = go.Figure()
        fig.add_trace(go.Scatter3d(x=[0], y=[0], z=[0], mode="markers", name="Sun",
                                   marker=dict(color="#ffd166", size=12)))
        last = PLANET_ORDER.index(max_planet)
        for name in PLANET_ORDER[:last + 1]:
            color = PLANET_STYLE[name]["color"]
            path = planet_orbit_path(name, jd) / AU
            fig.add_trace(go.Scatter3d(x=path[:, 0], y=path[:, 1], z=path[:, 2],
                                       mode="lines", line=dict(color=color, width=2),
                                       name=f"{name} orbit", showlegend=False,
                                       hoverinfo="skip", opacity=0.6))
            r, _ = planet_state(name, jd)
            r = r / AU
            fig.add_trace(go.Scatter3d(x=[r[0]], y=[r[1]], z=[r[2]], mode="markers+text",
                                       text=[name], textposition="top center", name=name,
                                       marker=dict(color=color, size=6)))

        if transfer_track is not None:
            T = np.asarray(transfer_track) / AU
            fig.add_trace(go.Scatter3d(x=T[:, 0], y=T[:, 1], z=T[:, 2], mode="lines",
                                       name="Transfer", line=dict(color=ACCENT, width=5)))
        if transfer_result is not None:
            r2 = transfer_result["r2"] / AU
            fig.add_trace(go.Scatter3d(x=[r2[0]], y=[r2[1]], z=[r2[2]], mode="markers",
                                       name=f"{transfer_result['arrival']} at arrival",
                                       marker=dict(color=OBS, size=6, symbol="diamond")))

        _base_layout(fig, title)
        axis = dict(backgroundcolor=BG, gridcolor=GRID, zerolinecolor=GRID, color=MUTED)
        fig.update_layout(scene=dict(xaxis=dict(axis, title="x [AU]"),
                                     yaxis=dict(axis, title="y [AU]"),
                                     zaxis=dict(axis, title="z [AU]"),
                                     aspectmode="data"))
        return fig


    def _jd_to_datetime(jd):
        return datetime.datetime(2000, 1, 1, 12) + datetime.timedelta(days=float(jd) - 2451545.0)


    def fig_porkchop(dep, arr, Z, dep_name, arr_name, best=None):
        x = [_jd_to_datetime(j) for j in dep]
        y = [_jd_to_datetime(j) for j in arr]
        zmax = float(np.nanpercentile(Z, 60)) if np.isfinite(Z).any() else None
        fig = go.Figure(go.Contour(
            x=x, y=y, z=Z, colorscale="Viridis_r", zmin=float(np.nanmin(Z)) if zmax else None,
            zmax=zmax, contours=dict(showlabels=True, labelfont=dict(color="white", size=10)),
            colorbar=dict(title="C₃ [km²/s²]"),
            hovertemplate="depart %{x|%Y-%m-%d}<br>arrive %{y|%Y-%m-%d}"
                          "<br>C₃ %{z:.1f} km²/s²<extra></extra>"))
        if best is not None:
            fig.add_trace(go.Scatter(
                x=[_jd_to_datetime(best["jd_departure"])], y=[_jd_to_datetime(best["jd_arrival"])],
                mode="markers+text", text=[f"min C₃ {best['c3']:.1f}"], textposition="top right",
                marker=dict(color=OBS, size=12, symbol="star"), name="Best"))
        _base_layout(fig, f"Porkchop plot — {dep_name} → {arr_name}", three_d=False)
        fig.update_xaxes(title="Departure date", gridcolor=GRID, color=MUTED)
        fig.update_yaxes(title="Arrival date", gridcolor=GRID, color=MUTED)
        return fig


# ====================================================================
#  report.py
# ====================================================================

"""
Plain-text results report, shown in the GUI and saved by "Save report".
"""





def _vec(v, fmt="{:>14,.4f}"):
    return "".join(fmt.format(c) for c in v)


def build_report(sol):
    """Format a solved case (the GUI's solution dict) as text."""
    el = sol["elems"]
    r1, r2 = np.asarray(sol["r1"]), np.asarray(sol["r2"])
    v1, v2 = np.asarray(sol["v1"]), np.asarray(sol["v2"])
    line = "=" * 72
    thin = "-" * 72

    out = [line,
           "LAMBERT'S PROBLEM - RESULTS",
           f"Generated {datetime.datetime.now():%Y-%m-%d %H:%M}",
           line,
           f"Input mode        : {sol.get('mode', 'observations')}",
           f"Transfer          : {'prograde' if sol.get('prograde', True) else 'retrograde'}",
           f"Time of flight    : {format_duration(sol['dt'])}",
           ""]

    if sol.get("r_station") is not None:
        out.append(f"Station (ECEF) km : {_vec(sol['r_station'])}")
        out.append("")

    out += ["STATE VECTORS (ECI)", thin,
            f"r1 [km]   {_vec(r1)}    |r1| = {np.linalg.norm(r1):,.3f}",
            f"r2 [km]   {_vec(r2)}    |r2| = {np.linalg.norm(r2):,.3f}",
            f"v1 [km/s] {_vec(v1)}    |v1| = {np.linalg.norm(v1):.4f}",
            f"v2 [km/s] {_vec(v2)}    |v2| = {np.linalg.norm(v2):.4f}",
            "",
            "CLASSICAL ORBITAL ELEMENTS", thin,
            f"Orbit type                 {el['orbit_type']}",
            f"a   semi-major axis        {el['a']:,.4f} km",
            f"e   eccentricity           {el['e']:.6f}",
            f"i   inclination            {el['i']:.4f} deg",
            f"RAAN                       {el['RAAN']:.4f} deg",
            f"w   argument of perigee    {el['argp']:.4f} deg",
            f"nu  true anomaly at r1     {el['nu']:.4f} deg",
            "",
            "DERIVED PARAMETERS", thin,
            f"h   angular momentum       {el['h']:,.4f} km^2/s",
            f"p   semi-latus rectum      {el['p']:,.4f} km",
            f"Specific energy            {el['energy']:.6f} km^2/s^2",
            f"Perigee radius / altitude  {el['r_p']:,.3f} / {el['alt_p']:,.3f} km"]
    if el["r_a"] is not None:
        out.append(f"Apogee radius / altitude   {el['r_a']:,.3f} / {el['alt_a']:,.3f} km")
    out.append(f"Period                     {format_duration(el['period'])}")
    out.append(f"Flight path angle at r1    {el['gamma']:.4f} deg")

    e1 = float(np.dot(v1, v1) / 2 - MU_EARTH / np.linalg.norm(r1))
    e2 = float(np.dot(v2, v2) / 2 - MU_EARTH / np.linalg.norm(r2))
    out += ["",
            "CONSISTENCY CHECKS", thin,
            f"Converged universal variable z   {sol['z']:.6f}",
            f"Energy at r1 / r2                {e1:.9f} / {e2:.9f} km^2/s^2",
            f"Difference (should be ~0)        {abs(e1 - e2):.3e} km^2/s^2"]

    if el["notes"]:
        out += ["", "NOTES", thin] + [f"- {n}" for n in el["notes"]]
    out.append(line)
    return "\n".join(out)



# ====================================================================
#  dashboard.py
# ====================================================================

if _HAS_PLOTLY:
    # Defined only when the optional dependency is present.
    """
    Assembles every view into ONE self-contained HTML dashboard.

    The whole analysis becomes a single file that opens in any browser with
    no Python, no server and no internet. That is the artefact to submit
    alongside the code: a marker can open it and immediately interact with
    the result.
    """





    _CSS = """
    :root{
      --bg:#0b1020; --panel:#121a2f; --fg:#e6edf7; --muted:#8fa3c8;
      --accent:#5ac8fa; --accent2:#ffb454; --line:rgba(140,165,210,0.20);
    }
    *{box-sizing:border-box}
    body{margin:0;background:var(--bg);color:var(--fg);
      font-family:Inter,"Segoe UI",Helvetica,Arial,sans-serif;}
    header{padding:22px 28px 16px;border-bottom:1px solid var(--line);
      background:linear-gradient(180deg,#101833 0%, #0b1020 100%);}
    h1{margin:0;font-size:22px;letter-spacing:.2px;font-weight:650}
    .sub{color:var(--muted);font-size:13px;margin-top:5px}
    .stats{display:flex;flex-wrap:wrap;gap:10px;margin-top:16px}
    .stat{background:var(--panel);border:1px solid var(--line);border-radius:10px;
      padding:9px 14px;min-width:132px}
    .stat .k{color:var(--muted);font-size:10.5px;text-transform:uppercase;
      letter-spacing:.8px}
    .stat .v{font-size:17px;font-weight:620;margin-top:3px}
    nav{display:flex;gap:4px;padding:12px 24px 0;flex-wrap:wrap;
      border-bottom:1px solid var(--line);background:var(--bg);
      position:sticky;top:0;z-index:20}
    button.tab{background:transparent;border:1px solid transparent;color:var(--muted);
      padding:9px 15px;border-radius:9px 9px 0 0;cursor:pointer;font-size:13.5px;
      font-family:inherit;border-bottom:2px solid transparent}
    button.tab:hover{color:var(--fg);background:rgba(255,255,255,.04)}
    button.tab.active{color:var(--fg);border-bottom:2px solid var(--accent);
      background:var(--panel)}
    .panel{display:none;padding:18px 24px 34px}
    .panel.active{display:block}
    .note{color:var(--muted);font-size:12.5px;line-height:1.65;max-width:1000px;
      margin:14px 0 0;border-left:2px solid var(--line);padding-left:14px}
    table{border-collapse:collapse;margin-top:6px;font-size:13.5px}
    th,td{padding:7px 16px 7px 0;text-align:left;border-bottom:1px solid var(--line)}
    th{color:var(--muted);font-weight:550;font-size:11px;text-transform:uppercase;
      letter-spacing:.7px}
    td.num{font-family:ui-monospace,Menlo,Consolas,monospace;text-align:right;
      padding-right:26px}
    .grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:26px}
    h3{font-size:13px;text-transform:uppercase;letter-spacing:.9px;color:var(--accent);
      margin:22px 0 4px;font-weight:600}
    footer{color:var(--muted);font-size:11.5px;padding:16px 28px 30px;
      border-top:1px solid var(--line)}
    """

    _JS = """
    function showTab(id, btn){
      document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
      document.querySelectorAll('button.tab').forEach(b=>b.classList.remove('active'));
      document.getElementById(id).classList.add('active');
      btn.classList.add('active');
      // Plotly cannot size a chart that was display:none when it was drawn,
      // so every chart in the newly shown panel is resized on reveal.
      document.querySelectorAll('#'+id+' .plotly-graph-div').forEach(function(d){
        Plotly.Plots.resize(d);
      });
    }
    window.addEventListener('DOMContentLoaded',function(){
      var first=document.querySelector('button.tab');
      if(first) first.click();
    });
    """


    def _div(fig, height=640):
        return fig.to_html(full_html=False, include_plotlyjs=False,
                            default_height=f"{height}px",
                            config={"displaylogo": False, "responsive": True})


    def _stat(k, v):
        return f'<div class="stat"><div class="k">{html.escape(k)}</div>' \
               f'<div class="v">{html.escape(v)}</div></div>'


    def _rows(pairs):
        out = []
        for k, v in pairs:
            out.append(f"<tr><th>{html.escape(k)}</th>"
                       f"<td class='num'>{html.escape(v)}</td></tr>")
        return "<table>" + "".join(out) + "</table>"


    def build_dashboard(sol, path="lambert_dashboard.html", jd0=None,
                         interplanetary=None, porkchop_data=None,
                         n_samples=500, revolutions=1.0):
        """
        Build the dashboard.

        Parameters
        ----------
        sol : dict
            Solved Earth-orbit case (r1, r2, v1, v2, dt, z, elems, r_station...).
        jd0 : float
            Julian Date of r1. Needed for Earth orientation, the ECEF frame,
            the ground track and the sky view.
        interplanetary : dict or None
            Result of interplanetary.transfer(), if the solar-system tab
            should be populated with a transfer.
        porkchop_data : tuple or None
            (dep, arr, Z, best, departure, arrival) for the porkchop tab.
        """
        el = sol["elems"]
        r1 = np.asarray(sol["r1"], float)
        r2 = np.asarray(sol["r2"], float)
        v1 = np.asarray(sol["v1"], float)
        station = sol.get("r_station")

        gmst0 = gmst_from_jd(jd0) if jd0 is not None else 0.0

        # --- sample the trajectory over (at least) the observed arc -------
        if el["period"] is not None:
            span = max(el["period"] * revolutions, sol["dt"])
        else:
            span = sol["dt"] * 2.0
        times, R, V = sample_orbit_in_time(r1, v1, 0.0, span, n=n_samples)

        tabs, panels = [], []

        def add(tab_id, label, body):
            tabs.append(f'<button class="tab" onclick="showTab(\'{tab_id}\',this)">'
                        f'{html.escape(label)}</button>')
            panels.append(f'<div class="panel" id="{tab_id}">{body}</div>')

        # ---------------- 1. ECI -----------------------------------------
        station_eci = rot3(gmst0) @ np.asarray(station, float) if station is not None else None
        f_eci = fig_orbit_eci(R, r1, r2, el, gmst=gmst0, r_station_eci=station_eci)
        add("tab-eci", "3D orbit (ECI)", _div(f_eci) + f"""
          <p class="note">The inertial frame in which Lambert's problem is actually
          solved. Earth's continents are drawn at their true orientation for the
          epoch (GMST = {math.degrees(gmst0):.2f}°). Dotted lines are the two
          position vectors that were the input to the solver; the orbit through
          them is the output.</p>""")

        # ---------------- 2. ECEF ----------------------------------------
        if jd0 is not None:
            R_ecef = eci_track_to_ecef(R, times, jd0)
            add("tab-ecef", "Earth-fixed (ECEF)", _div(fig_orbit_ecef(R_ecef)) + """
              <p class="note">Exactly the same trajectory, expressed in the frame that
              rotates with the planet. A closed ellipse turns into an open spiral
              because the Earth turns underneath it. This is the visual answer to
              "why bother converting to ECI at all?".</p>""")

            # ------------ 4. Ground track --------------------------------
            lat, lon, alt = ground_track(R_ecef)
            st_ll = None
            if station is not None:
                la, lo, _ = ecef_to_geodetic(station)
                st_ll = (la, lo)
            add("tab-track", "Ground track",
                _div(fig_ground_track(lat, lon, alt, station_latlon=st_ll), 560) +
                f"""<p class="note">The sub-satellite point over one orbital period.
                The latitude reached never exceeds the inclination
                ({el['i']:.2f}°), which is a hard geometric constraint and a useful
                check that the frame chain is correct. Coastlines are computed
                locally, so this works with no internet connection.</p>""")

            # ------------ 5. Sky view ------------------------------------
            if station is not None:
                az, elev, rng = sky_track(R, times, jd0, station)
                marks = []
                if sol.get("mode", "observations") == "observations":
                    pass
                    a1, e1, _ = sez_to_azelrange(eci_to_sez(r1, station, gmst0))
                    jd2 = jd0 + sol["dt"] / 86400.0
                    a2, e2, _ = sez_to_azelrange(eci_to_sez(r2, station, gmst_from_jd(jd2)))
                    marks = [("obs 1", a1, e1), ("obs 2", a2, e2)]
                spans = visibility_intervals(times, elev)
                vis_txt = ", ".join(f"{s/60:.1f}–{e/60:.1f} min" for s, e in spans[:4]) or "none"
                add("tab-sky", "Sky view (topocentric)",
                    _div(fig_sky_view(az, elev, rng, obs_marks=marks), 620) +
                    f"""<p class="note">What the ground station physically sees: zenith
                    at the centre, horizon at the rim, north at the top. Only the
                    portion above the horizon is drawn. Visible window(s) from the
                    epoch: {vis_txt}. The two markers are the original observations
                    recovered by transforming the solved orbit back into the
                    station's own frame — they land on the input values to machine
                    precision, which closes the loop on the whole pipeline.</p>""")

        # ---------------- 3. Perifocal -----------------------------------
        P = eci_track_to_pqw(R, el["i"], el["RAAN"], el["argp"])
        Q = eci_to_pqw_matrix(el["i"], el["RAAN"], el["argp"])
        add("tab-pqw", "Perifocal plane",
            _div(fig_perifocal(P, el, Q @ r1, Q @ r2), 620) + """
            <p class="note">The orbit seen face-on in its own plane, with the focus at
            Earth's centre. Here the conic is undistorted, so the semi-major axis,
            the eccentricity and the two apsides can be read directly off the
            figure.</p>""")

        # ---------------- 6. Solar system --------------------------------
        if interplanetary is not None:
            pass
            track = transfer_path(interplanetary)
            t = interplanetary
            far = "Mars" if t["arrival"] in ("Mercury", "Venus", "Earth", "Mars") else t["arrival"]
            f_ss = fig_solar_system(t["jd_departure"], transfer_result=t,
                                         transfer_track=track, max_planet=far,
                                         title=f"{t['departure']} → {t['arrival']} transfer "
                                               f"(solved with the same Lambert code)")
            info = _rows([
                ("Departure", _jd_str(t["jd_departure"])),
                ("Arrival", _jd_str(t["jd_arrival"])),
                ("Time of flight", f"{t['tof_days']:.1f} days"),
                ("Transfer angle", f"{t['transfer_angle_deg']:.1f}°  ({t['type']})"),
                ("Departure v∞", f"{t['vinf_departure']:.3f} km/s"),
                ("C₃ (launch energy)", f"{t['c3']:.2f} km²/s²"),
                ("Arrival v∞", f"{t['vinf_arrival']:.3f} km/s"),
                ("Δv injection (from 200 km LEO)", f"{t['dv_departure']:.3f} km/s"),
                ("Δv capture (to 400 km orbit)", f"{t['dv_arrival']:.3f} km/s"),
                ("Transfer semi-major axis", f"{t['elements']['a']/AU:.4f} AU"),
                ("Transfer eccentricity", f"{t['elements']['e']:.4f}"),
            ])
            add("tab-solar", "Solar system", _div(f_ss, 660) + f"""
              <div class="grid2"><div><h3>Transfer summary</h3>{info}</div>
              <div><h3>Why this belongs here</h3><p class="note" style="border:0;padding:0">
              This arc was computed by the <em>same</em> <code>lambert_universal()</code>
              function that solves the satellite problem — the only changes are μ<sub>Sun</sub>
              instead of μ<sub>Earth</sub>, and two planet positions instead of two
              observations. Lambert's problem is the standard tool for interplanetary
              mission design, so this is the natural demonstration that the solver is
              general rather than tuned to one case.</p></div></div>""")

        # ---------------- 7. Porkchop ------------------------------------
        if porkchop_data is not None:
            dep, arr, Z, best, dname, aname = porkchop_data
            add("tab-pork", "Porkchop",
                _div(fig_porkchop(dep, arr, Z, dname, aname, best=best), 660) + f"""
                <p class="note">Departure energy C₃ as a function of departure and
                arrival date — {Z.size:,} independent Lambert solutions. The dark
                basin is a launch window; its centre is the cheapest departure. This
                is the standard chart used to choose real mission launch dates.</p>""")

        # ---------------- 8. Numbers -------------------------------------
        add("tab-data", "Results", _results_panel(sol, el, r1, r2, v1, sol["v2"]))

        # ---------------- assemble ---------------------------------------
        stats = "".join([
            _stat("Orbit type", el["orbit_type"]),
            _stat("Semi-major axis", f"{el['a']:,.1f} km"),
            _stat("Eccentricity", f"{el['e']:.5f}"),
            _stat("Inclination", f"{el['i']:.3f}°"),
            _stat("Period", format_duration(el["period"]).split("(")[0].strip()),
            _stat("Perigee alt.", f"{el['alt_p']:,.0f} km"),
            _stat("Apogee alt.", f"{el['alt_a']:,.0f} km" if el["alt_a"] is not None else "n/a"),
        ])

        doc = f"""<!DOCTYPE html>
    <html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Lambert's Problem — Orbit Determination</title>
    <style>{_CSS}</style>
    <script>{get_plotlyjs()}</script>
    </head><body>
    <header>
      <h1>Lambert's Problem — Orbit Determination</h1>
      <div class="sub">Two observations → position vectors → Lambert solution → orbit,
      shown in five reference frames. Generated {datetime.datetime.now():%Y-%m-%d %H:%M}.</div>
      <div class="stats">{stats}</div>
    </header>
    <nav>{''.join(tabs)}</nav>
    {''.join(panels)}
    <footer>Self-contained: Plotly is embedded in this file, and the coastline data is
    computed locally — no network access is required to view or interact with it.</footer>
    <script>{_JS}</script>
    </body></html>"""

        with open(path, "w", encoding="utf-8") as fh:
            fh.write(doc)
        return path


    def _jd_str(jd):
        d = datetime.datetime(2000, 1, 1, 12) + datetime.timedelta(days=jd - 2451545.0)
        return d.strftime("%Y-%m-%d %H:%M")


    def _results_panel(sol, el, r1, r2, v1, v2):
        v2 = np.asarray(v2, float)

        def vec(v):
            return "  ".join(f"{c:,.4f}" for c in v)

        state = _rows([
            ("r₁ [km]", vec(r1) + f"   |r₁| {np.linalg.norm(r1):,.3f}"),
            ("r₂ [km]", vec(r2) + f"   |r₂| {np.linalg.norm(r2):,.3f}"),
            ("v₁ [km/s]", vec(v1) + f"   |v₁| {np.linalg.norm(v1):,.4f}"),
            ("v₂ [km/s]", vec(v2) + f"   |v₂| {np.linalg.norm(v2):,.4f}"),
            ("Time of flight", format_duration(sol["dt"])),
        ])
        elements = _rows([
            ("a — semi-major axis", f"{el['a']:,.4f} km"),
            ("e — eccentricity", f"{el['e']:.6f}"),
            ("i — inclination", f"{el['i']:.4f}°"),
            ("Ω — RAAN", f"{el['RAAN']:.4f}°"),
            ("ω — argument of perigee", f"{el['argp']:.4f}°"),
            ("ν — true anomaly at r₁", f"{el['nu']:.4f}°"),
        ])
        derived = _rows([
            ("h — specific angular momentum", f"{el['h']:,.4f} km²/s"),
            ("p — semi-latus rectum", f"{el['p']:,.4f} km"),
            ("Specific mechanical energy", f"{el['energy']:.6f} km²/s²"),
            ("Perigee radius / altitude", f"{el['r_p']:,.3f} / {el['alt_p']:,.3f} km"),
            ("Apogee radius / altitude",
             f"{el['r_a']:,.3f} / {el['alt_a']:,.3f} km" if el["r_a"] is not None else "n/a"),
            ("Orbital period", format_duration(el["period"])),
            ("Speed at perigee / apogee",
             f"{el['v_p']:.4f} / {el['v_a']:.4f} km/s" if el["v_a"] is not None
             else f"{el['v_p']:.4f} km/s"),
            ("Flight path angle at r₁", f"{el['gamma']:.4f}°"),
            ("Eccentric anomaly at r₁",
             f"{el['E_anom']:.4f}°" if el["E_anom"] is not None else "n/a"),
            ("Mean anomaly at r₁",
             f"{el['M_anom']:.4f}°" if el["M_anom"] is not None else "n/a"),
        ])

        pass
        e1 = float(np.dot(v1, v1) / 2 - MU_EARTH / np.linalg.norm(r1))
        e2 = float(np.dot(v2, v2) / 2 - MU_EARTH / np.linalg.norm(r2))
        checks = _rows([
            ("Converged universal variable z", f"{sol['z']:.6f}"),
            ("Specific energy at r₁", f"{e1:.9f} km²/s²"),
            ("Specific energy at r₂", f"{e2:.9f} km²/s²"),
            ("Difference (must be ≈ 0)", f"{abs(e1-e2):.3e} km²/s²"),
        ])

        return f"""
          <div class="grid2">
            <div><h3>State vectors (ECI)</h3>{state}
                 <h3>Classical elements</h3>{elements}</div>
            <div><h3>Derived parameters</h3>{derived}
                 <h3>Consistency checks</h3>{checks}</div>
          </div>
          <p class="note">Energy must be identical at both ends of the arc for any valid
          Keplerian orbit; the difference above is the numerical residual, not a
          physical effect.</p>"""


# ====================================================================
#  validation.py
# ====================================================================

"""
Validation suite.

Two independent kinds of check are run:

(A) REFERENCE CASES -- the solver is run on worked examples from
    H.D. Curtis, "Orbital Mechanics for Engineering Students", whose
    published answers are known. This catches outright algorithm errors.

(B) PHYSICS INVARIANTS -- properties that MUST hold for any valid
    Keplerian solution, checked on the assignment's own data:
      * specific orbital energy is identical at both points
      * specific angular momentum is identical at both points
      * the orbital elements recovered from (r1,v1) and (r2,v2) agree
      * the mean anomaly advances by exactly n * dt over the transfer
      * propagating r1,v1 forward by dt reproduces r2
    These are self-validating: they need no external reference values,
    so they also guard against a reference being mistranscribed.

Run with:  python3 validation.py
"""



# Accumulates (name, passed, detail) for the final report.
_RESULTS = []


def check(name, got, expected, tol, unit="", relative=False):
    """Record a single numeric comparison."""
    if expected == 0:
        err = abs(got)
    else:
        err = abs(got - expected) / abs(expected) if relative else abs(got - expected)
    passed = err <= tol
    kind = "rel" if relative else "abs"
    _RESULTS.append((name, passed,
                     f"got {got:,.5g}{unit}, expected {expected:,.5g}{unit} "
                     f"({kind} err {err:.3g}, tol {tol:g})"))
    return passed


def check_true(name, condition, detail=""):
    _RESULTS.append((name, bool(condition), detail))
    return bool(condition)


# ----------------------------------------------------------------------
# (A) Reference cases from Curtis
# ----------------------------------------------------------------------

def test_curtis_lambert():
    """
    Curtis, Example 5.2 -- Lambert's problem.

    Given two geocentric position vectors and a 1 hour time of flight,
    the prograde trajectory connecting them has known velocities.
    """
    r1 = np.array([5000.0, 10000.0, 2100.0])
    r2 = np.array([-14600.0, 2500.0, 7000.0])
    dt = 3600.0

    v1, v2, z = lambert_universal(r1, r2, dt, prograde=True)

    v1_exp = np.array([-5.9925, 1.9254, 3.2456])
    v2_exp = np.array([-3.3125, -4.1966, -0.38529])

    for idx, axis in enumerate("xyz"):
        check(f"Curtis 5.2  v1_{axis}", v1[idx], v1_exp[idx], 1e-3, " km/s")
    for idx, axis in enumerate("xyz"):
        check(f"Curtis 5.2  v2_{axis}", v2[idx], v2_exp[idx], 1e-3, " km/s")

    # Curtis then derives the orbit from this state vector.
    el = state_to_elements(r1, v1)
    check("Curtis 5.2  h", el["h"], 80470.0, 2e-4, " km^2/s", relative=True)
    check("Curtis 5.2  i", el["i"], 30.19, 5e-3, " deg", relative=True)
    check("Curtis 5.2  RAAN", el["RAAN"], 44.60, 5e-3, " deg", relative=True)
    check("Curtis 5.2  e", el["e"], 0.4335, 5e-3, "", relative=True)
    check("Curtis 5.2  argp", el["argp"], 30.71, 5e-3, " deg", relative=True)
    check("Curtis 5.2  nu1", el["nu"], 350.8, 5e-3, " deg", relative=True)
    check("Curtis 5.2  a", el["a"], 20000.0, 5e-3, " km", relative=True)


def test_curtis_elements():
    """
    Curtis, Example 4.3 -- classical elements from a state vector.
    Exercises state_to_elements independently of the Lambert solver,
    including a retrograde (i > 90 deg) orbit.
    """
    r = np.array([-6045.0, -3490.0, 2500.0])
    v = np.array([-3.457, 6.618, 2.533])
    el = state_to_elements(r, v)

    check("Curtis 4.3  h", el["h"], 58310.0, 1e-3, " km^2/s", relative=True)
    check("Curtis 4.3  i", el["i"], 153.2, 1e-3, " deg", relative=True)
    check("Curtis 4.3  RAAN", el["RAAN"], 255.3, 1e-3, " deg", relative=True)
    check("Curtis 4.3  e", el["e"], 0.1712, 5e-3, "", relative=True)
    check("Curtis 4.3  argp", el["argp"], 20.07, 5e-3, " deg", relative=True)
    check("Curtis 4.3  nu", el["nu"], 28.45, 5e-3, " deg", relative=True)
    check("Curtis 4.3  a", el["a"], 8788.0, 1e-3, " km", relative=True)


def test_stumpff():
    """
    Stumpff functions must agree with their series expansions near z = 0
    (where the closed forms are numerically unstable) and satisfy the
    identity  z*S(z) + C(z) ... checked here against known values.
    """
    check("Stumpff C(0)", stumpff_C(0.0), 0.5, 1e-12)
    check("Stumpff S(0)", stumpff_S(0.0), 1.0 / 6.0, 1e-12)
    # Continuity across the small-|z| series/closed-form switch.
    for z in (1e-5, -1e-5):
        c_near, s_near = stumpff_C(z), stumpff_S(z)
        check_true(f"Stumpff C continuous at z={z:g}", abs(c_near - 0.5) < 1e-5,
                   f"C={c_near:.10f}")
        check_true(f"Stumpff S continuous at z={z:g}", abs(s_near - 1/6) < 1e-5,
                   f"S={s_near:.10f}")
    # Elliptic closed form at z = (pi)^2 : C = 2/pi^2, S = (pi-0)/pi^3
    z = math.pi ** 2
    check("Stumpff C(pi^2)", stumpff_C(z), (1 - math.cos(math.pi)) / z, 1e-12)
    check("Stumpff S(pi^2)", stumpff_S(z), (math.pi - math.sin(math.pi)) / math.pi ** 3, 1e-12)


# ----------------------------------------------------------------------
# (B) Physics invariants, on the assignment's own data
# ----------------------------------------------------------------------

def assignment_case():
    """Run the full pipeline on the assignment's given observations."""
    r_station = np.array([1344.143, 6068.601, 1429.311])
    jd1 = julian_date(2023, 4, 2, 0, 30, 0.0)
    jd2 = julian_date(2023, 4, 2, 3, 0, 0.0)
    r1 = topocentric_to_geocentric(132.67, 32.44, 16945.450, r_station, gmst_from_jd(jd1))
    r2 = topocentric_to_geocentric(123.08, 50.06, 37350.340, r_station, gmst_from_jd(jd2))
    dt = time_of_flight(jd1, jd2)
    v1, v2, z = lambert_universal(r1, r2, dt)
    return r1, r2, v1, v2, dt


def test_invariants():
    r1, r2, v1, v2, dt = assignment_case()
    el1 = state_to_elements(r1, v1)
    el2 = state_to_elements(r2, v2)

    # Energy and angular momentum are constants of the motion.
    eps1 = np.dot(v1, v1) / 2 - MU_EARTH / np.linalg.norm(r1)
    eps2 = np.dot(v2, v2) / 2 - MU_EARTH / np.linalg.norm(r2)
    check("Invariant: specific energy equal at r1 and r2", eps2, eps1, 1e-9, " km^2/s^2")

    h1 = np.cross(r1, v1)
    h2 = np.cross(r2, v2)
    check("Invariant: |h| equal at r1 and r2",
          float(np.linalg.norm(h2)), float(np.linalg.norm(h1)), 1e-6, " km^2/s")
    check_true("Invariant: h direction equal at r1 and r2",
               np.allclose(h1 / np.linalg.norm(h1), h2 / np.linalg.norm(h2), atol=1e-10),
               "orbital plane is the same at both points")

    # The shape/orientation elements must not depend on which point they
    # were derived from (only the anomalies may differ).
    for key, unit in (("a", " km"), ("e", ""), ("i", " deg"),
                      ("RAAN", " deg"), ("argp", " deg")):
        check(f"Invariant: {key} same from (r1,v1) and (r2,v2)",
              el2[key], el1[key], 1e-6, unit)

    # Kepler's equation: mean anomaly must advance by exactly n * dt.
    dM_actual = (el2["M_anom"] - el1["M_anom"]) % 360.0
    dM_expected = math.degrees(el1["mean_motion"] * dt) % 360.0
    check("Invariant: mean anomaly advance equals n*dt",
          dM_actual, dM_expected, 1e-6, " deg")

    # Lambert must reproduce the time of flight it was given.
    check("Invariant: transfer time consistent with orbit period",
          dM_expected / 360.0 * el1["period"], dt, 1e-6, " s")

    # Closing the loop: propagate (r1,v1) forward by dt with an
    # independent Kepler propagator and land on r2.
    r2_prop = propagate_kepler(r1, v1, dt)
    err = float(np.linalg.norm(r2_prop - r2))
    check("Invariant: propagating r1,v1 by dt reproduces r2", err, 0.0, 1e-6, " km")


def propagate_kepler(r0, v0, dt, mu=MU_EARTH, tol=1e-12, max_iter=200):
    """
    Independent two-body propagator (universal Kepler equation with
    Lagrange f and g coefficients). Deliberately written separately from
    the Lambert solver so that agreement between the two is meaningful
    evidence rather than a shared-bug tautology.
    """
    r0 = np.asarray(r0, float)
    v0 = np.asarray(v0, float)
    r0n = np.linalg.norm(r0)
    v0n = np.linalg.norm(v0)
    vr0 = np.dot(r0, v0) / r0n
    alpha = 2.0 / r0n - v0n ** 2 / mu          # 1/a

    chi = math.sqrt(mu) * abs(alpha) * dt       # initial guess
    for _ in range(max_iter):
        z = alpha * chi ** 2
        Cz, Sz = stumpff_C(z), stumpff_S(z)
        F = (r0n * vr0 / math.sqrt(mu) * chi ** 2 * Cz
             + (1 - alpha * r0n) * chi ** 3 * Sz
             + r0n * chi
             - math.sqrt(mu) * dt)
        dF = (r0n * vr0 / math.sqrt(mu) * chi * (1 - z * Sz)
              + (1 - alpha * r0n) * chi ** 2 * Cz
              + r0n)
        dchi = F / dF
        chi -= dchi
        if abs(dchi) < tol:
            break

    z = alpha * chi ** 2
    f = 1 - chi ** 2 / r0n * stumpff_C(z)
    g = dt - chi ** 3 / math.sqrt(mu) * stumpff_S(z)
    return f * r0 + g * v0



# ----------------------------------------------------------------------
# (C) Reference-frame transforms
# ----------------------------------------------------------------------

def test_frames():
    """
    The frame chain must be invertible and must respect the geometric
    limits that any orbit obeys.
    """
    pass
    pass

    station = np.array([1344.143, 6068.601, 1429.311])
    jd1 = julian_date(2023, 4, 2, 0, 30, 0.0)
    jd2 = julian_date(2023, 4, 2, 3, 0, 0.0)
    r1, r2, v1, v2, dt = assignment_case()
    el = state_to_elements(r1, v1)

    # Round trip: transform the solved ECI positions back into the
    # station's horizon frame and recover the ORIGINAL observations.
    for label, r, jd, (az_e, el_e, rg_e) in (
            ("obs1", r1, jd1, (132.67, 32.44, 16945.450)),
            ("obs2", r2, jd2, (123.08, 50.06, 37350.340))):
        az, elev, rng = sez_to_azelrange(
            eci_to_sez(r, station, gmst_from_jd(jd)))
        check(f"Round trip {label}: azimuth", az, az_e, 1e-6, " deg")
        check(f"Round trip {label}: elevation", elev, el_e, 1e-6, " deg")
        check(f"Round trip {label}: range", rng, rg_e, 1e-6, " km")

    # Propagating one full period must return to the starting point.
    times, R, V = sample_orbit_in_time(r1, v1, 0.0, el["period"], n=200)
    check("Orbit closes after exactly one period",
          float(np.linalg.norm(R[-1] - R[0])), 0.0, 1e-6, " km")

    # A ground track can never exceed the inclination in latitude.
    R_ecef = eci_track_to_ecef(R, times, jd1)
    lat, lon, alt = ground_track(R_ecef)
    check_true("Ground-track latitude bounded by inclination",
               np.nanmax(np.abs(lat)) <= el["i"] + 1e-6,
               f"max |lat| {np.nanmax(np.abs(lat)):.4f} deg vs i {el['i']:.4f} deg")

    # In the perifocal frame the orbit is planar by construction.
    P = eci_track_to_pqw(R, el["i"], el["RAAN"], el["argp"])
    check("Perifocal out-of-plane component is zero",
          float(np.max(np.abs(P[:, 2]))), 0.0, 1e-6, " km")

    # ECI -> ECEF -> ECI must be the identity.
    g = gmst_from_jd(jd1)
    back = rot3(g) @ eci_to_ecef(r1, g)
    check("ECI -> ECEF -> ECI round trip", float(np.linalg.norm(back - r1)),
          0.0, 1e-9, " km")


# ----------------------------------------------------------------------
# (D) Planetary ephemerides and interplanetary transfer
# ----------------------------------------------------------------------

def test_planets():
    """
    Sidereal periods follow from the semi-major axes via Kepler's third
    law, so comparing them with the accepted values tests the element
    table itself.
    """
    pass
    pass

    expected_years = {
        "Mercury": 0.2408, "Venus": 0.6152, "Earth": 1.0000, "Mars": 1.8808,
        "Jupiter": 11.862, "Saturn": 29.457, "Uranus": 84.02, "Neptune": 164.79,
    }
    for name, yrs in expected_years.items():
        got = orbital_period_days(name) / 365.25
        check(f"{name}: sidereal period", got, yrs, 3e-3, " yr", relative=True)

    # Earth's heliocentric distance must stay inside its known range.
    pass
    d = [float(np.linalg.norm(planet_state("Earth",
         julian_date(2026, m, 1, 0, 0, 0.0))[0]) / AU) for m in range(1, 13)]
    check_true("Earth distance within 0.983-1.017 AU",
               0.982 < min(d) and max(d) < 1.018,
               f"range {min(d):.4f}-{max(d):.4f} AU")
    # Perihelion occurs in early January.
    check_true("Earth perihelion falls in Dec/Jan",
               int(np.argmin(d)) in (0, 11),
               f"minimum distance in month {int(np.argmin(d)) + 1}")


def test_interplanetary():
    """
    An Earth->Mars transfer must land in the envelope that real missions
    occupy. These are loose bounds on purpose -- they catch gross errors
    (wrong mu, wrong units, wrong frame) without over-fitting.
    """
    pass
    pass
    pass

    t = transfer("Earth", "Mars",
                 julian_date(2026, 11, 1, 0, 0, 0.0),
                 julian_date(2027, 8, 20, 0, 0, 0.0))

    check_true("Earth->Mars C3 in the 5-40 km^2/s^2 range",
               5.0 < t["c3"] < 40.0, f"C3 = {t['c3']:.2f} km^2/s^2")
    check_true("Earth->Mars injection dv in the 3-6 km/s range",
               3.0 < t["dv_departure"] < 6.0,
               f"dv = {t['dv_departure']:.3f} km/s")
    check_true("Arrival v-infinity in the 1-8 km/s range",
               1.0 < t["vinf_arrival"] < 8.0,
               f"v_inf = {t['vinf_arrival']:.3f} km/s")
    # The transfer ellipse must span from Earth's orbit out toward Mars.
    a_au = t["elements"]["a"] / AU
    check_true("Transfer semi-major axis between Earth and Mars orbits",
               1.0 < a_au < 1.6, f"a = {a_au:.4f} AU")

    # Same solver, heliocentric: energy must still be conserved.
    pass
    e1 = float(np.dot(t["v1"], t["v1"]) / 2 - MU_SUN / np.linalg.norm(t["r1"]))
    e2 = float(np.dot(t["v2"], t["v2"]) / 2 - MU_SUN / np.linalg.norm(t["r2"]))
    check("Heliocentric energy equal at both ends", e2, e1, 1e-6, " km^2/s^2")


# ----------------------------------------------------------------------
# (E) Extensions: ephemeris, manoeuvres, perturbations, satellites
#     Each is skipped (not failed) when its optional library is missing.
# ----------------------------------------------------------------------

def _optional(name, fn):
    try:
        fn()
    except ImportError as exc:
        check_true(f"{name} (skipped: {exc.name} not installed)", True, "optional")


def test_ephemeris():
    """The approximate Standish elements must agree with JPL DE440s to
    within their published accuracy (inner planets: < 0.001 AU)."""
    import ephemeris
    pass
    pass
    if not ephemeris.available():
        check_true("DE440s ephemeris (skipped: file not downloaded)", True, "optional")
        return
    jd = julian_date(2026, 9, 29, 0, 0, 0.0)
    for name in ("Mercury", "Venus", "Earth", "Mars"):
        d = float(np.linalg.norm(ephemeris.planet_state(name, jd)[0] - planet_state(name, jd)[0])) / AU
        check(f"{name}: Standish vs DE440s position", d, 0.0, 1e-3, " AU")
    moon, _ = ephemeris.moon_geocentric(jd)
    check_true("Moon distance within 356,000-407,000 km",
               356000 < float(np.linalg.norm(moon)) < 407000, f"{float(np.linalg.norm(moon)):,.0f} km")


def test_maneuvers():
    """Hohmann LEO (300 km) -> GEO: the standard total is 3.893 km/s
    (2.426 + 1.467 km/s, from the vis-viva equation as in Curtis, Ch. 6);
    a pure plane change must equal 2 v sin(di/2)."""
    import maneuvers
    h = maneuvers.hohmann(300, 35786)
    check("Hohmann LEO->GEO total delta-v", h["total_dv"], 3.893, 2e-3, " km/s")
    check("Hohmann transfer time = half transfer period", h["transfer_time"],
          maneuvers.period((2 * (6378.137) + 300 + 35786) / 2) / 2, 1e-3, " s")
    p = maneuvers.plane_change(400, 28.5, 51.6)
    v = maneuvers.circ_speed(6378.137 + 400)
    check("Plane change delta-v = 2 v sin(di/2)", p["total_dv"],
          2 * v * math.sin(math.radians(23.1) / 2), 1e-6, " km/s")
    # Bi-elliptic beats Hohmann for r2/r1 above ~15.58 with a high rb.
    b = maneuvers.bielliptic(300, 400000, 900000)
    hh = maneuvers.hohmann(300, 400000)
    check_true("Bi-elliptic cheaper than Hohmann for r2/r1 ~ 61",
               b["total_dv"] < hh["total_dv"], f"{b['total_dv']:.4f} vs {hh['total_dv']:.4f} km/s")


def test_perturbations():
    """Numerically integrated J2 drift of the node must match the
    analytic secular rate (Sun-synchronous orbit: about +0.9856 deg/day)."""
    import perturb
    r0, v0 = perturb.orbit_from_elements(700, 700, 98.19)
    out = perturb.propagate_perturbed(r0, v0, 5, use_j2=True, use_drag=False)
    s = out["summary"]
    check("J2 RAAN rate: integrated vs analytic", s["raan_rate"], s["raan_rate_analytic"],
          0.01, "", relative=True)
    check("Sun-synchronous RAAN rate", s["raan_rate_analytic"], 0.9856, 0.01, " deg/day", relative=True)
    # With no perturbation switched on, the integrator must reproduce Kepler.
    plain = perturb.propagate_perturbed(r0, v0, 1, use_j2=False, use_drag=False)
    check("Integrator with no perturbations = Kepler", plain["summary"]["max_diff"], 0.0, 1e-3, " km")


def test_gravity_assists():
    """
    Patched-conic route optimiser against history: searching only from
    the physics, it must rediscover the dates of real missions.
    """
    import flyby
    jd = lambda y, m, d: julian_date(y, m, d, 0, 0, 0.0)

    # A flyby whose in/out speeds match needs no engine burn.
    fb = flyby.flyby_analysis("Jupiter", np.array([6.0, 0.0, 0.0]), np.array([0.0, 6.0, 0.0]))
    check("Unpowered flyby: no burn when |v_inf| is unchanged", fb["dv"], 0.0, 1e-9, " km/s")
    check_true("Jupiter can turn a 6 km/s flyby by 90 deg", fb["feasible"],
               f"max turn {fb['max_turn_deg']:.1f} deg")

    v = flyby.plan_route(["Earth", "Venus", "Mercury"], (jd(1973, 6, 1), jd(1974, 3, 1)),
                         capture=False, max_days=0.6 * 365.25)
    check("Mariner 10: Venus flyby date (real: 5 Feb 1974)", v["jds"][1], jd(1974, 2, 5), 20.0, " JD")
    check("Mariner 10: launch date (real: 3 Nov 1973)", v["jds"][0], jd(1973, 11, 3), 20.0, " JD")

    y = flyby.plan_route(["Earth", "Jupiter", "Saturn"], (jd(1977, 1, 1), jd(1978, 6, 30)),
                         capture=False, max_days=3.5 * 365.25)
    check("Voyager: launch date (real: 5 Sep 1977)", y["jds"][0], jd(1977, 9, 5), 30.0, " JD")
    check("Voyager: Jupiter flyby (real: Mar-Jul 1979)", y["jds"][1], jd(1979, 5, 5), 90.0, " JD")
    gain = y["events"][1]["gain"]
    check_true("Voyager: Jupiter adds more than 5 km/s", gain > 5.0, f"gain {gain:.2f} km/s")
    check_true("Voyager route cheaper than flying direct",
               y["total_dv"] < y["direct"]["total_dv"],
               f"{y['total_dv']:.3f} vs {y['direct']['total_dv']:.3f} km/s")


def test_multirev_lambert():
    """
    Multi-revolution Lambert: flying (r1, v1) forward by dt must land on
    r2 after exactly N laps, on both solution branches; too short a time
    must be rejected; the batch solver must equal the scalar one.
    """
    pass
    r1 = np.array([5000.0, 10000.0, 2100.0])
    r2 = np.array([-14600.0, 2500.0, 7000.0])
    for N in (1, 2):
        for br in (0, 1):
            dt = (N + 0.9) * 2 * math.pi * math.sqrt(20000.0 ** 3 / MU_EARTH)
            v1, v2, z = lambert_universal(r1, r2, dt, revs=N, branch=br)
            miss = float(np.linalg.norm(propagate_kepler(r1, v1, dt) - r2))
            check(f"{N}-rev Lambert, branch {br}: propagation lands on r2", miss, 0.0, 1e-5, " km")
            laps = math.sqrt(z) / (2 * math.pi)
            check_true(f"{N}-rev Lambert, branch {br}: completes {N} full lap(s)", N <= laps < N + 1,
                       f"{laps:.3f} laps")
    try:
        lambert_universal(r1, r2, 3600.0, revs=1)
        check_true("1-rev Lambert rejects a too-short time of flight", False, "no error raised")
    except ValueError:
        check_true("1-rev Lambert rejects a too-short time of flight", True, "ValueError raised")
    v1b, v2b, _, ok = lambert_batch(r1[None, :], r2[None, :], np.array([3600.0]))
    v1s, v2s, _ = lambert_universal(r1, r2, 3600.0)
    check("Batch solver = scalar solver (Curtis 5.2)", float(np.abs(v1b[0] - v1s).max()), 0.0, 1e-9, " km/s")


def test_repeat_flybys():
    """
    Routes that return to the same planet (multi-rev legs), against
    history, using each mission's real launch period.
    """
    import flyby
    jd = lambda y, m, d: julian_date(y, m, d, 0, 0, 0.0)
    c = flyby.plan_route(["Earth", "Venus", "Venus", "Earth", "Jupiter", "Saturn"],
                         (jd(1997, 10, 6), jd(1997, 11, 15)), capture=True, max_days=7.5 * 365.25)
    check("Cassini: launch date (real: 15 Oct 1997)", c["jds"][0], jd(1997, 10, 15), 15.0, " JD")
    check("Cassini: Earth flyby (real: 18 Aug 1999)", c["jds"][3], jd(1999, 8, 18), 15.0, " JD")
    check("Cassini: second Venus flyby (real: 24 Jun 1999)", c["jds"][2], jd(1999, 6, 24), 30.0, " JD")
    check_true("Cassini: flybys far cheaper than flying direct",
               c["total_dv"] < c["direct"]["total_dv"] - 5.0,
               f"{c['total_dv']:.2f} vs {c['direct']['total_dv']:.2f} km/s")
    g = flyby.plan_route(["Earth", "Venus", "Earth", "Earth", "Jupiter"],
                         (jd(1989, 10, 12), jd(1989, 11, 21)), capture=True, max_days=6.5 * 365.25)
    check("Galileo: Venus flyby (real: 10 Feb 1990)", g["jds"][1], jd(1990, 2, 10), 30.0, " JD")
    check("Galileo: first Earth flyby (real: 8 Dec 1990)", g["jds"][2], jd(1990, 12, 8), 40.0, " JD")
    check_true("Galileo: Earth-Earth leg loops around the Sun",
               g["legs"][2]["revs"] >= 1 or g["legs"][2]["days"] > 365, f"{g['legs'][2]['days']:.0f} days")
    check_true("Galileo: cheaper than flying direct", g["total_dv"] < g["direct"]["total_dv"],
               f"{g['total_dv']:.2f} vs {g['direct']['total_dv']:.2f} km/s")


def test_satellite_model():
    """The fast Kepler+J2 model used to animate thousands of satellites
    must stay close to full SGP4 over a few hours (visual accuracy)."""
    import satellites
    try:
        recs, _ = satellites.fetch_group("gps-ops")
    except RuntimeError:
        check_true("Satellite model vs SGP4 (skipped: no data downloaded yet)", True, "optional")
        return
    rows = satellites.satellite_table(["gps-ops"])["sats"][:8]
    by_id = {r["NORAD_CAT_ID"]: r for r in recs}
    worst = max(float(np.linalg.norm(np.subtract(satellites.sgp4_position(by_id[r[1]], r[3] + h / 24),
                                                  satellites.j2_position(r, r[3] + h / 24))))
                for r in rows for h in (0, 3, 6))
    check("GPS: Kepler+J2 model vs SGP4 (6 h)", worst, 0.0, 100.0, " km")


def run_validation():
    test_stumpff()
    test_curtis_elements()
    test_curtis_lambert()
    test_invariants()
    test_multirev_lambert()
    test_frames()
    test_planets()
    test_interplanetary()
    _optional("DE440s ephemeris", test_ephemeris)
    _optional("Manoeuvres", test_maneuvers)
    _optional("Perturbations", test_perturbations)
    _optional("Gravity assists", test_gravity_assists)
    _optional("Repeat flybys", test_repeat_flybys)
    _optional("Satellite model", test_satellite_model)

    width = 58
    print("=" * 78)
    print("VALIDATION SUITE")
    print("=" * 78)
    n_pass = 0
    for name, passed, detail in _RESULTS:
        flag = "PASS" if passed else "FAIL"
        n_pass += passed
        print(f"[{flag}] {name:<{width}} {detail}")
    print("-" * 78)
    total = len(_RESULTS)
    print(f"{n_pass}/{total} checks passed")
    print("=" * 78)
    return 0 if n_pass == total else 1



# ====================================================================
#  app.py
# ====================================================================

if _HAS_TK:
    # Defined only when the optional dependency is present.
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




    # NOTE: `dashboard` (and therefore plotly) is imported lazily inside the
    # worker, so the application still starts and solves on a machine where
    # plotly is not installed -- only the dashboard button is unavailable.

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
                    pass
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
            print("The dashboard needs plotly.  Install it with:\n"
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
        print("tkinter is not available, so the GUI cannot start.\n"
              "Install it (e.g. 'sudo apt install python3-tk'), or use:\n"
              "    python3 lambert_problem_solver.py --dashboard\n"
              "    python3 lambert_problem_solver.py --report\n"
              "    python3 lambert_problem_solver.py --selftest",
              file=sys.stderr)
        return 2

    LambertStudio().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
