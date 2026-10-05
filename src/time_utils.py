"""
Section 1: Time handling utilities for the Lambert's problem project.

Provides:
    - julian_date(year, month, day, hour, minute, second) -> JD
    - gmst_from_jd(jd) -> Greenwich Mean Sidereal Time [rad]
    - time_of_flight(jd1, jd2) -> seconds between two Julian Dates
"""

import math


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


if __name__ == "__main__":
    # --- Quick check against the assignment's data ---
    # Observation 1: 02/04/2023 00:30:00.0 UTC  (DD/MM/YYYY -> 2 April 2023)
    # Observation 2: 02/04/2023 03:00:00.0 UTC
    jd1 = julian_date(2023, 4, 2, 0, 30, 0.0)
    jd2 = julian_date(2023, 4, 2, 3, 0, 0.0)

    gmst1 = gmst_from_jd(jd1)
    gmst2 = gmst_from_jd(jd2)

    dt = time_of_flight(jd1, jd2)

    print(f"JD1   = {jd1:.6f}")
    print(f"JD2   = {jd2:.6f}")
    print(f"GMST1 = {math.degrees(gmst1):.6f} deg  ({gmst1:.6f} rad)")
    print(f"GMST2 = {math.degrees(gmst2):.6f} deg  ({gmst2:.6f} rad)")
    print(f"Time of flight = {dt:.1f} s  ({dt/3600:.4f} h)")
