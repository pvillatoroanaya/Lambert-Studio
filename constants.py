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
