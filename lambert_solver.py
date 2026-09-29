"""
Section 3: Lambert's problem, universal-variable formulation
(Curtis, "Orbital Mechanics for Engineering Students", Algorithm 5.2).

Given two position vectors r1, r2 and the time of flight dt between
them, find the velocity vectors v1, v2 of the conic that connects them.

Provides:
    - stumpff_C(z), stumpff_S(z)
    - lambert_universal(r1, r2, dt, prograde=True, mu=MU_EARTH) -> v1, v2, z
"""

import math

import numpy as np

from constants import MU_EARTH

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


def lambert_universal(r1, r2, dt, prograde=True, mu=MU_EARTH):
    """
    Solve Lambert's problem (single revolution).

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


if __name__ == "__main__":
    # Curtis Example 5.2
    r1 = np.array([5000.0, 10000.0, 2100.0])
    r2 = np.array([-14600.0, 2500.0, 7000.0])
    v1, v2, z = lambert_universal(r1, r2, 3600.0)
    print("Curtis Example 5.2")
    print(f"v1 = {v1}  km/s   (expected [-5.9925  1.9254  3.2456])")
    print(f"v2 = {v2}  km/s   (expected [-3.3125 -4.1966 -0.38529])")
    print(f"z  = {z:.6f}")
