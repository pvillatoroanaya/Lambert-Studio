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

import math

import numpy as np


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


if __name__ == "__main__":
    from time_utils import julian_date, gmst_from_jd

    r_station = np.array([1344.143, 6068.601, 1429.311])
    lat, lon = station_latlon(r_station)
    print(f"Station lat = {math.degrees(lat):.4f} deg, lon = {math.degrees(lon):.4f} deg")

    jd1 = julian_date(2023, 4, 2, 0, 30, 0.0)
    jd2 = julian_date(2023, 4, 2, 3, 0, 0.0)
    r1 = topocentric_to_geocentric(132.67, 32.44, 16945.450, r_station, gmst_from_jd(jd1))
    r2 = topocentric_to_geocentric(123.08, 50.06, 37350.340, r_station, gmst_from_jd(jd2))
    print(f"r1 = {r1}  |r1| = {np.linalg.norm(r1):.3f} km")
    print(f"r2 = {r2}  |r2| = {np.linalg.norm(r2):.3f} km")
