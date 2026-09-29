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


def lambert_universal(r1, r2, dt, prograde=True, mu=MU_EARTH, revs=0, branch=0):
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
        v1, v2, z, ok = lambert_batch(r1[None, :], r2[None, :], np.array([float(dt)]),
                                      prograde=prograde, mu=mu, revs=revs, branch=branch)
        if not ok[0]:
            raise ValueError(f"No {revs}-revolution solution: the time of flight is too "
                             f"short for {revs} full lap(s), or the geometry is degenerate.")
        return v1[0], v2[0], float(z[0])

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


if __name__ == "__main__":
    # Curtis Example 5.2
    r1 = np.array([5000.0, 10000.0, 2100.0])
    r2 = np.array([-14600.0, 2500.0, 7000.0])
    v1, v2, z = lambert_universal(r1, r2, 3600.0)
    print("Curtis Example 5.2")
    print(f"v1 = {v1}  km/s   (expected [-5.9925  1.9254  3.2456])")
    print(f"v2 = {v2}  km/s   (expected [-3.3125 -4.1966 -0.38529])")
    print(f"z  = {z:.6f}")
