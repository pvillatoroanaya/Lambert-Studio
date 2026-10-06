"""
How certain is an orbit determined from two observations?

Every measurement has errors. A Monte Carlo study repeats the whole orbit
determination thousands of times, each time with the measured azimuth,
elevation, range and time disturbed by random errors of a realistic size
(normally distributed), and looks at how much the resulting orbits differ.

It answers three questions:
  1. how uncertain are the orbital elements (a, e, i, perigee height)?
  2. which measurement matters most (angles, range or timing)?
  3. how fast does the uncertainty of the predicted position grow?
     (it grows mostly ALONG the orbit, because a small error in the
     period makes the spacecraft drift ahead or behind: this is why
     tracking stations keep measuring.)

Vectorised: the same equations as coord_utils.topocentric_to_geocentric
and lambert_solver, on arrays of samples.
"""

import math

import numpy as np

from constants import MU_EARTH, R_EARTH
from coord_utils import station_latlon, sez_to_ecef_matrix
from lambert_solver import lambert_batch
from time_utils import gmst_from_jd
from dsm import propagate_batch

OMEGA_EARTH = 7.292115e-5        # rad/s, Earth's rotation rate (for timing errors in GMST)


def _topo_batch(az_deg, el_deg, rng, station, gmst):
    az, el = np.radians(az_deg), np.radians(el_deg)
    rho = np.stack([-np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)], axis=1) * rng[:, None]
    lat, lon = station_latlon(station)
    r_ecef = station[None, :] + rho @ sez_to_ecef_matrix(lat, lon).T
    c, s = np.cos(gmst), np.sin(gmst)
    return np.stack([c * r_ecef[:, 0] - s * r_ecef[:, 1], s * r_ecef[:, 0] + c * r_ecef[:, 1], r_ecef[:, 2]], axis=1)


def _elements(r, v, mu=MU_EARTH):
    rn = np.linalg.norm(r, axis=1)
    v2 = np.einsum("ij,ij->i", v, v)
    h = np.cross(r, v)
    hn = np.linalg.norm(h, axis=1)
    evec = np.cross(v, h) / mu - r / rn[:, None]
    e = np.linalg.norm(evec, axis=1)
    energy = v2 / 2 - mu / rn
    with np.errstate(divide="ignore", invalid="ignore"):
        a = -mu / (2 * energy)
        period = np.where(a > 0, 2 * np.pi * np.sqrt(np.abs(a) ** 3 / mu), np.nan)
    i = np.degrees(np.arccos(np.clip(h[:, 2] / hn, -1, 1)))
    rp = hn ** 2 / mu / (1 + e)
    return {"a": a, "e": e, "i": i, "perigee_alt": rp - R_EARTH, "period": period}


def _solve(station, obs, sig, n, rng, prograde):
    (jd1, az1, el1, r1_), (jd2, az2, el2, r2_) = obs
    g = lambda s: rng.normal(0.0, s, n) if s > 0 else np.zeros(n)
    dt1, dt2 = g(sig["time"]), g(sig["time"])
    r1 = _topo_batch(az1 + g(sig["angle"]), el1 + g(sig["angle"]), r1_ + g(sig["range"]), station,
                     gmst_from_jd(jd1) + OMEGA_EARTH * dt1)
    r2 = _topo_batch(az2 + g(sig["angle"]), el2 + g(sig["angle"]), r2_ + g(sig["range"]), station,
                     gmst_from_jd(jd2) + OMEGA_EARTH * dt2)
    tof = (jd2 - jd1) * 86400.0 + dt2 - dt1
    v1, _, _, ok = lambert_batch(r1, r2, tof, prograde=prograde, mu=MU_EARTH)
    return r1[ok], v1[ok]


def monte_carlo(station, obs, sigma_angle_deg=0.01, sigma_range_km=0.015, sigma_time_s=0.001, n=3000,
                prograde=True, seed=7, horizons_h=(0, 1, 3, 6, 12, 24, 48, 72, 120, 168)):
    """obs = [(jd, az, el, range), (jd, az, el, range)]."""
    station = np.asarray(station, float)
    if n < 100 or n > 20000:
        raise ValueError("Use between 100 and 20,000 samples.")
    if min(sigma_angle_deg, sigma_range_km, sigma_time_s) < 0:
        raise ValueError("Measurement errors cannot be negative.")
    rng = np.random.default_rng(seed)
    sig = {"angle": sigma_angle_deg, "range": sigma_range_km, "time": sigma_time_s}
    nominal_r, nominal_v = _solve(station, obs, {"angle": 0, "range": 0, "time": 0}, 1, rng, prograde)
    if len(nominal_r) == 0:
        raise ValueError("No orbit connects these two observations, so there is nothing to analyse.")
    r, v = _solve(station, obs, sig, n, rng, prograde)
    if len(r) < n * 0.9:
        raise ValueError("Many samples had no solution; the errors are too large for this geometry.")
    el = _elements(r, v)
    el0 = {k: float(x[0]) for k, x in _elements(nominal_r, nominal_v).items()}

    def stats(x):
        x = x[np.isfinite(x)]
        if len(x) == 0:                     # e.g. the period of an escape orbit
            return {"mean": None, "std": None, "p05": None, "p95": None}
        return {"mean": float(x.mean()), "std": float(x.std()), "p05": float(np.percentile(x, 5)),
                "p95": float(np.percentile(x, 95))}

    elements = {k: {"nominal": el0[k], **stats(el[k])} for k in el}
    samples = {k: el[k][:2000].tolist() for k in ("a", "e", "i", "perigee_alt", "period")}

    # Which measurement matters most: each error source alone.
    sens = {}
    for name in ("angle", "range", "time"):
        only = {k: (sig[k] if k == name else 0.0) for k in sig}
        rr, vv = _solve(station, obs, only, 1500, rng, prograde)
        e1 = _elements(rr, vv)
        sens[name] = {"a_std": float(np.nanstd(e1["a"])), "i_std": float(np.nanstd(e1["i"]))}

    # Growth of the position uncertainty, split into radial / along-track /
    # cross-track directions of the nominal orbit.
    growth = []
    r0 = np.repeat(nominal_r, len(r), axis=0)
    v0 = np.repeat(nominal_v, len(r), axis=0)
    for hrs in horizons_h:
        dt = np.full(len(r), hrs * 3600.0)
        if hrs == 0:
            rs, rn_ = r, r0
            vn_ = v0
        else:
            rs, _ = propagate_batch(r, v, dt, mu=MU_EARTH)
            rn_, vn_ = propagate_batch(r0[:1], v0[:1], dt[:1], mu=MU_EARTH)
        d = rs - rn_[:1]
        R_ = rn_[0] / np.linalg.norm(rn_[0])
        W_ = np.cross(rn_[0], vn_[0]); W_ /= np.linalg.norm(W_)
        S_ = np.cross(W_, R_)
        comp = np.stack([d @ R_, d @ S_, d @ W_], axis=1)
        growth.append({"hours": hrs, "radial": float(comp[:, 0].std()), "along": float(comp[:, 1].std()),
                       "cross": float(comp[:, 2].std()), "total": float(np.sqrt((comp ** 2).sum(1)).mean())})

    # The same, once per orbit (always at the same point of the nominal
    # orbit), which shows the steady drift without the in-orbit wiggles.
    P0 = el0["period"] if math.isfinite(el0["period"]) else 86400.0
    per_orbit = []
    for kk in range(0, 15):
        dt = np.full(len(r), kk * P0)
        rs = propagate_batch(r, v, dt, mu=MU_EARTH)[0] if kk else r
        dvec = rs - nominal_r
        S_ = nominal_v[0] / np.linalg.norm(nominal_v[0])
        along = dvec @ S_
        per_orbit.append({"orbits": kk, "hours": kk * P0 / 3600, "along_std": float(along.std()),
                          "total": float(np.linalg.norm(dvec, axis=1).mean())})

    # A few sample orbits (one period each) to draw the "cloud" of possibilities.
    k = min(120, len(r))
    P = np.nan_to_num(el["period"][:k], nan=86400.0)
    orbits = []
    for j in range(k):
        ts = np.linspace(0, min(P[j], 7 * 86400.0), 90)
        rr, _ = propagate_batch(np.repeat(r[j:j + 1], 90, 0), np.repeat(v[j:j + 1], 90, 0), ts, mu=MU_EARTH)
        orbits.append(rr.round(1).tolist())
    return {"n": int(len(r)), "sigma": sig, "elements": elements, "samples": samples, "sensitivity": sens,
            "growth": growth, "per_orbit": per_orbit, "orbits": orbits, "nominal": {"r": nominal_r[0].tolist(), "v": nominal_v[0].tolist()}}
