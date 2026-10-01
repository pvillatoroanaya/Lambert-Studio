"""
High-fidelity force model for Earth orbits (used by perturb.py).

Everything a precise orbit propagator for low and high Earth orbits
normally includes, apart from the full high-degree gravity field:

  * Earth's gravity field: zonal harmonics J2..J6 (the equatorial bulge and
    the slight "pear" shape) and the C22/S22 sectoral term (the equator is
    slightly elliptical: this is what pulls geostationary satellites toward
    75 deg E and 105 deg W). Coefficients: EGM96.
  * Third bodies: the Sun and the Moon, positions from NASA/JPL DE440s.
  * Solar radiation pressure: cannon-ball model with Earth's shadow
    (conical model with penumbra, Montenbruck & Gill 3.4).
  * Atmospheric drag: NRLMSIS 2.1 (the US Naval Research Laboratory's
    empirical model, via the pymsis package), which responds to solar
    activity (F10.7 radio flux) and geomagnetic activity (Ap); or the
    simple exponential model as a fallback.

Frames: the state is in the app's ECI frame (Earth's equator of date,
rotated into the Earth-fixed frame by GMST). DE440s positions are in
ICRF (J2000); they are rotated to the equator of date with the IAU-1976
precession angles (Vallado eq. 3-88). Nutation (< 20") is neglected.

The acceleration is written with plain Python floats (no small numpy
arrays): it is evaluated hundreds of thousands of times per run.
"""

import math

import numpy as np

from constants import MU_EARTH, R_EARTH, OMEGA_EARTH, AU
from time_utils import gmst_from_jd

# EGM96 (unnormalised) zonal coefficients, J_n = -C_n0.
ZONALS = {2: 1.08262668e-3, 3: -2.53265649e-6, 4: -1.61962159e-6, 5: -2.27296083e-7, 6: 5.40681239e-7}
# EGM96 sectoral (2,2): normalised C22 = 2.43914352e-6, S22 = -1.40016684e-6,
# times the normalisation factor sqrt(10/24) = 0.645497.
C22, S22 = 1.57446037e-6, -9.03803806e-7
MU_MOON = 4902.800066
MU_SUN = 1.32712440018e11
R_SUN = 695700.0                 # km, IAU nominal solar radius
P_SUN = 4.56e-6                  # N/m^2, solar radiation pressure at 1 AU

SOLAR_ACTIVITY = {"low": (70.0, 4.0), "moderate": (150.0, 12.0), "high": (250.0, 30.0)}   # (F10.7, Ap)


def precession_matrix(jd):
    """IAU-1976 precession, mean J2000 equator -> mean equator of date (Vallado eq. 3-88)."""
    T = (jd - 2451545.0) / 36525.0
    arc = math.pi / 180 / 3600
    zeta = (2306.2181 * T + 0.30188 * T * T + 0.017998 * T ** 3) * arc
    z = (2306.2181 * T + 1.09468 * T * T + 0.018203 * T ** 3) * arc
    th = (2004.3109 * T - 0.42665 * T * T - 0.041833 * T ** 3) * arc
    cz, sz, ct, st, cZ, sZ = math.cos(zeta), math.sin(zeta), math.cos(th), math.sin(th), math.cos(z), math.sin(z)
    return np.array([
        [cZ * ct * cz - sZ * sz, -cZ * ct * sz - sZ * cz, -cZ * st],
        [sZ * ct * cz + cZ * sz, -sZ * ct * sz + cZ * cz, -sZ * st],
        [st * cz, -st * sz, ct],
    ])


class _Table:
    """A body's geocentric position on a regular time grid, linearly
    interpolated (hourly grid: < 5 km error for the Moon, far below what
    matters for a perturbation)."""

    def __init__(self, t, xyz):
        self.t0, self.dt = float(t[0]), float(t[1] - t[0])
        self.x, self.y, self.z = (xyz[:, k].tolist() for k in range(3))
        self.n = len(t)

    def __call__(self, t):
        f = (t - self.t0) / self.dt
        k = min(max(int(f), 0), self.n - 2)
        u = f - k
        x, y, z = self.x, self.y, self.z
        return (x[k] + (x[k + 1] - x[k]) * u, y[k] + (y[k + 1] - y[k]) * u, z[k] + (z[k + 1] - z[k]) * u)


class ForceModel:
    """
    Acceleration of a satellite in Earth orbit. Options:
      zonal_degree  2..6 (2 = J2 only), or 0 for none
      tesseral      include C22/S22
      sun, moon     third-body gravity
      srp           solar radiation pressure (needs cr, area_m2, mass_kg)
      drag          None, "exponential" or "msis"
      activity      "low" | "moderate" | "high" | "actual" (MSIS only)
    """

    def __init__(self, jd0, days, zonal_degree=2, tesseral=False, sun=False, moon=False, srp=False,
                 drag=None, cd=2.2, cr=1.3, area_m2=10.0, mass_kg=1000.0, activity="moderate"):
        self.jd0 = jd0
        self.zonal_degree = zonal_degree
        self.tesseral, self.use_sun, self.use_moon, self.srp = tesseral, sun, moon, srp
        self.drag = drag
        self.bc = cd * area_m2 * 1e-6 / mass_kg                  # km^2/kg
        self.srp_k = cr * area_m2 / mass_kg * P_SUN / 1000.0     # km/s^2 at 1 AU
        self.gmst0 = gmst_from_jd(jd0)
        self.notes = []
        self.sun_tab = self.moon_tab = None
        if sun or moon or srp or drag == "msis":
            self._build_tables(days)
        self.msis = None
        if drag == "msis":
            self._build_msis(days, activity)

    # -------------------------------------------------------------- tables

    def _build_tables(self, days):
        import ephemeris
        t = np.arange(0.0, days * 86400.0 + 7200.0, 3600.0)
        jd = self.jd0 + t / 86400.0
        sun = ephemeris.sun_geocentric(jd)
        moon = ephemeris.moon_geocentric(jd)
        if sun is None or moon is None:
            raise ValueError("Sun and Moon forces need the DE440s ephemeris, which is not installed.")
        P = precession_matrix(self.jd0 + days / 2)
        self.sun_tab = _Table(t, np.atleast_2d(sun) @ P.T)
        self.moon_tab = _Table(t, np.atleast_2d(moon[0]) @ P.T)

    def _build_msis(self, days, activity):
        """NRLMSIS 2.1 density on a (local solar time x latitude x altitude)
        grid, one grid per 15-day block of the run."""
        try:
            from pymsis import msis
        except ImportError:
            self.notes.append("NRLMSIS (pymsis) is not installed: the exponential atmosphere was used instead.")
            self.drag = "exponential"
            return
        self.alts = np.arange(100.0, 1001.0, 10.0)
        self.lats = np.arange(-90.0, 91.0, 10.0)
        self.lsts = np.arange(0.0, 25.0, 1.0)
        self.block = 15.0
        grids, self.solar = [], []
        for b in range(int(days // self.block) + 1):
            jd = self.jd0 + b * self.block
            ut_h = ((jd + 0.5) % 1.0) * 24.0
            lons = ((self.lsts - ut_h) * 15.0) % 360.0
            date = np.datetime64("2000-01-01T12:00") + np.timedelta64(int(round((jd - 2451545.0) * 86400)), "s")
            kw = {}
            if activity == "actual":
                kw = {}
            else:
                f107, ap = SOLAR_ACTIVITY[activity]
                kw = {"f107s": [f107], "f107as": [f107], "aps": [[ap] * 7]}
            try:
                out = msis.calculate([date], lons, self.lats, self.alts, **kw)
            except Exception as exc:          # no space-weather data for that date, etc.
                f107, ap = SOLAR_ACTIVITY["moderate"]
                self.notes.append(f"No measured solar activity for this date ({exc.__class__.__name__}); "
                                  "moderate activity was assumed.")
                out = msis.calculate([date], lons, self.lats, self.alts,
                                     f107s=[f107], f107as=[f107], aps=[[ap] * 7])
                activity = "moderate"
            rho = np.squeeze(out[..., 0])            # (lst, lat, alt), kg/m^3
            grids.append(np.log(np.maximum(rho, 1e-30)).tolist())
        self.msis = grids
        self.activity = activity

    def msis_density(self, t, alt, lat_deg, lst_h):
        g = self.msis[min(int(t / 86400.0 / self.block), len(self.msis) - 1)]
        fa = (alt - 100.0) / 10.0
        ia = min(max(int(fa), 0), len(self.alts) - 2)
        ua = min(max(fa - ia, 0.0), 1.0)
        fl = (lat_deg + 90.0) / 10.0
        il = min(max(int(fl), 0), len(self.lats) - 2)
        ul = fl - il
        fs = lst_h % 24.0
        js = min(int(fs), 23)
        us = fs - js

        def at(s, l):
            row = g[s][l]
            return row[ia] + (row[ia + 1] - row[ia]) * ua
        v = ((at(js, il) * (1 - ul) + at(js, il + 1) * ul) * (1 - us)
             + (at(js + 1, il) * (1 - ul) + at(js + 1, il + 1) * ul) * us)
        return math.exp(v)

    # -------------------------------------------------------- the forces

    def accel(self, t, x, y, z, vx, vy, vz):
        r2 = x * x + y * y + z * z
        r = math.sqrt(r2)
        k = -MU_EARTH / (r2 * r)
        ax, ay, az = k * x, k * y, k * z

        # Zonal harmonics: a_n = -mu Jn R^n / r^(n+2) [ -(n+1) Pn r_hat + Pn' (z_hat - u r_hat) ]
        n_max = self.zonal_degree
        if n_max >= 2:
            u = z / r
            p_prev, p = 1.0, u            # P0, P1
            d_prev, d = 0.0, 1.0          # P0', P1'
            Rr = R_EARTH / r
            fac = Rr
            sx = sy = sz = 0.0            # sum along r_hat, and along z_hat
            zc = 0.0
            for n in range(2, n_max + 1):
                p_new = ((2 * n - 1) * u * p - (n - 1) * p_prev) / n
                d_new = u * d + n * p          # P_n' = u P_{n-1}' + n P_{n-1}
                p_prev, p, d_prev, d = p, p_new, d, d_new
                fac *= Rr
                c = -ZONALS[n] * fac
                sx += c * (-(n + 1) * p - d * u)
                zc += c * d
            g = MU_EARTH / r2
            ax += g * sx * x / r
            ay += g * sx * y / r
            az += g * (sx * z / r + zc)

        # Sectoral C22/S22 in the Earth-fixed frame.
        if self.tesseral:
            th = self.gmst0 + OMEGA_EARTH * t
            c, s = math.cos(th), math.sin(th)
            xe, ye = c * x + s * y, -s * x + c * y
            f = C22 * (xe * xe - ye * ye) + 2 * S22 * xe * ye
            k3 = 3 * MU_EARTH * R_EARTH ** 2
            r5 = r2 * r2 * r
            gxe = k3 * ((2 * C22 * xe + 2 * S22 * ye) / r5 - 5 * f * xe / (r5 * r2))
            gye = k3 * ((-2 * C22 * ye + 2 * S22 * xe) / r5 - 5 * f * ye / (r5 * r2))
            gze = k3 * (-5 * f * z / (r5 * r2))
            ax += c * gxe - s * gye
            ay += s * gxe + c * gye
            az += gze

        sun = None
        if self.sun_tab is not None:
            sun = self.sun_tab(t)
        if self.use_sun:
            ax, ay, az = _third(ax, ay, az, x, y, z, sun, MU_SUN)
        if self.use_moon:
            ax, ay, az = _third(ax, ay, az, x, y, z, self.moon_tab(t), MU_MOON)

        if self.srp:
            dx, dy, dz = x - sun[0], y - sun[1], z - sun[2]           # Sun -> satellite
            d = math.sqrt(dx * dx + dy * dy + dz * dz)
            nu = shadow(x, y, z, r, sun)
            if nu > 0:
                a_srp = nu * self.srp_k * (AU / d) ** 2
                ax += a_srp * dx / d
                ay += a_srp * dy / d
                az += a_srp * dz / d

        if self.drag:
            alt = r - R_EARTH
            if alt < 1000.0:
                if self.drag == "msis":
                    lat = math.degrees(math.asin(z / r))
                    ra = math.atan2(y, x)
                    ra_sun = math.atan2(sun[1], sun[0])
                    lst = 12.0 + math.degrees(ra - ra_sun) / 15.0
                    rho = self.msis_density(t, alt, lat, lst)
                else:
                    from perturb import density
                    rho = density(alt)
                rho *= 1e9                                              # kg/km^3
                wx, wy = vx + OMEGA_EARTH * y, vy - OMEGA_EARTH * x       # velocity relative to the air
                vr = math.sqrt(wx * wx + wy * wy + vz * vz)
                k = -0.5 * rho * self.bc * vr
                ax += k * wx
                ay += k * wy
                az += k * vz
        return ax, ay, az

    def rhs(self, t, y):
        ax, ay, az = self.accel(t, y[0], y[1], y[2], y[3], y[4], y[5])
        return [y[3], y[4], y[5], ax, ay, az]


def _third(ax, ay, az, x, y, z, s, mu):
    """Third-body acceleration: mu [ (s - r)/|s - r|^3 - s/|s|^3 ]."""
    dx, dy, dz = s[0] - x, s[1] - y, s[2] - z
    d3 = (dx * dx + dy * dy + dz * dz) ** 1.5
    s3 = (s[0] * s[0] + s[1] * s[1] + s[2] * s[2]) ** 1.5
    return (ax + mu * (dx / d3 - s[0] / s3), ay + mu * (dy / d3 - s[1] / s3), az + mu * (dz / d3 - s[2] / s3))


def shadow(x, y, z, r, sun):
    """Fraction of the Sun's disc visible from the satellite (1 = full sun,
    0 = umbra), conical model with penumbra (Montenbruck & Gill, 3.4.2)."""
    sx, sy, sz = sun[0] - x, sun[1] - y, sun[2] - z               # satellite -> Sun
    ds = math.sqrt(sx * sx + sy * sy + sz * sz)
    a = math.asin(min(R_SUN / ds, 1.0))                           # apparent radius of the Sun
    b = math.asin(min(R_EARTH / r, 1.0))                          # apparent radius of the Earth
    c = math.acos(max(-1.0, min(1.0, (-x * sx - y * sy - z * sz) / (r * ds))))   # separation of the centres
    if c >= a + b:
        return 1.0
    if c <= b - a:
        return 0.0
    if c < a - b:
        return 1.0 - (b * b) / (a * a)                            # annular (not possible for Earth orbits)
    xx = (c * c + a * a - b * b) / (2 * c)
    yy = math.sqrt(max(a * a - xx * xx, 0.0))
    area = a * a * math.acos(max(-1.0, min(1.0, xx / a))) + b * b * math.acos(max(-1.0, min(1.0, (c - xx) / b))) - c * yy
    return 1.0 - area / (math.pi * a * a)


def potential_zonal(x, y, z, n_max):
    """Zonal disturbing potential (for checking the acceleration numerically)."""
    r = math.sqrt(x * x + y * y + z * z)
    u = z / r
    p_prev, p = 1.0, u
    total = 0.0
    for n in range(2, n_max + 1):
        p_prev, p = p, ((2 * n - 1) * u * p - (n - 1) * p_prev) / n
        total += -ZONALS[n] * (R_EARTH / r) ** n * p
    return MU_EARTH / r * total
