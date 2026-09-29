"""
Reference frames and trajectory sampling.

Everything the dashboard needs to show the same orbit in several frames:
inertial (ECI), Earth-fixed (ECEF), perifocal (PQW), the ground track
(latitude / longitude) and the station's own sky view (SEZ -> az/el).

Angles in the public functions are in DEGREES unless noted otherwise
(GMST is always in radians, as returned by time_utils.gmst_from_jd).
"""

import math

import numpy as np

from constants import MU_EARTH, R_EARTH
from time_utils import gmst_from_jd
from coord_utils import rot3, station_latlon, sez_to_ecef_matrix
from lambert_solver import stumpff_C, stumpff_S


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
