"""
Orbital manoeuvres: Hohmann and bi-elliptic transfers, plane changes,
and circularising the orbit found by the Lambert solver.

Every manoeuvre is built the same way, so the numbers can be trusted:
the spacecraft's state vector is propagated with the two-body
propagator (frames.propagate), each burn replaces the velocity vector,
and the delta-v of a burn is |v_after - v_before|. A plane change is
therefore not a special formula here -- it falls out of the vectors,
and so does the saving from combining it with another burn.

Geometry: the initial circular orbit has RAAN = 0, so the line of nodes
is the ECI x axis; burns happen on that line (u = 0 or 180 deg), which
is where a plane change has to be done.

Returned plans contain the burns, the trajectory segments (sampled in
time, for animation) and a propellant budget from the rocket equation.
"""

import math

import numpy as np

from constants import MU_EARTH, R_EARTH
from frames import propagate
from orbital_elements import state_to_elements

G0 = 9.80665e-3          # standard gravity [km/s^2]


# ----------------------------------------------------------------------
# building blocks
# ----------------------------------------------------------------------

def circ_speed(r, mu=MU_EARTH):
    return math.sqrt(mu / r)


def vis_viva(r, a, mu=MU_EARTH):
    return math.sqrt(mu * (2.0 / r - 1.0 / a))


def on_node_line(r, u_deg, i_deg):
    """Position and prograde-horizontal unit vector at argument of
    latitude u on an orbit with RAAN = 0 and inclination i."""
    u, i = math.radians(u_deg), math.radians(i_deg)
    pos = r * np.array([math.cos(u), math.sin(u) * math.cos(i), math.sin(u) * math.sin(i)])
    tangent = np.array([-math.sin(u), math.cos(u) * math.cos(i), math.cos(u) * math.sin(i)])
    return pos, tangent


def period(a, mu=MU_EARTH):
    return 2 * math.pi * math.sqrt(a ** 3 / mu)


class _Plan:
    """Accumulates coasting segments and burns along one timeline."""

    def __init__(self, r0, v0, mass, isp):
        self.r = np.asarray(r0, float)
        self.v = np.asarray(v0, float)
        self.t = 0.0
        self.mass = mass
        self.isp = isp
        self.burns = []
        self.segments = []

    def coast(self, duration, kind, label, n=None):
        n = n or max(60, min(400, int(duration / 60)))
        ts = np.linspace(0.0, duration, n)
        pts = [propagate(self.r, self.v, float(t))[0] for t in ts]
        self.segments.append({"kind": kind, "label": label, "t": (self.t + ts).tolist(),
                              "r": np.array(pts).tolist()})
        self.r, self.v = propagate(self.r, self.v, float(duration))
        self.t += duration

    def burn(self, v_new, label):
        dv_vec = np.asarray(v_new, float) - self.v
        dv = float(np.linalg.norm(dv_vec))
        m_after = self.mass * math.exp(-dv / (self.isp * G0))
        self.burns.append({
            "label": label, "t": self.t, "r": self.r.tolist(), "dv": dv,
            "dir": (dv_vec / dv).tolist() if dv > 0 else [0, 0, 0],
            "v_before": float(np.linalg.norm(self.v)), "v_after": float(np.linalg.norm(v_new)),
            "mass_before": self.mass, "propellant": self.mass - m_after,
        })
        self.mass = m_after
        self.v = np.asarray(v_new, float)

    def result(self, title, notes=()):
        total = sum(b["dv"] for b in self.burns)
        first = self.burns[0]["t"] if self.burns else 0.0
        last = self.burns[-1]["t"] if self.burns else 0.0
        return {
            "title": title, "burns": self.burns, "segments": self.segments,
            "total_dv": total, "transfer_time": last - first, "duration": self.t,
            "final_mass": self.mass, "propellant": self.burns[0]["mass_before"] - self.mass if self.burns else 0.0,
            "notes": list(notes),
        }


def _check_alt(alt, label):
    if not (100.0 <= alt <= 1.0e6):
        raise ValueError(f"{label} must be between 100 and 1,000,000 km.")


# ----------------------------------------------------------------------
# manoeuvres
# ----------------------------------------------------------------------

def hohmann(alt1, alt2, i1=0.0, i2=0.0, mass=1000.0, isp=320.0):
    """
    Hohmann transfer between circular orbits, with any inclination
    change done in the second burn (combined burn: cheapest when the
    target orbit is higher, because the spacecraft is slowest there).
    """
    _check_alt(alt1, "Initial altitude"); _check_alt(alt2, "Final altitude")
    r1, r2 = R_EARTH + alt1, R_EARTH + alt2
    pos, tan = on_node_line(r1, 180.0, i1)
    p = _Plan(pos, circ_speed(r1) * tan, mass, isp)
    p.coast(period(r1) / 2, "initial", "Initial orbit")

    a_t = (r1 + r2) / 2
    _, tan = on_node_line(r1, 0.0, i1)
    p.burn(vis_viva(r1, a_t) * tan, "Δv₁ · enter transfer")
    p.coast(period(a_t) / 2, "transfer", "Transfer orbit")

    _, tan2 = on_node_line(r2, 180.0, i2)
    p.burn(circ_speed(r2) * tan2, "Δv₂ · circularise" + (" + plane change" if i1 != i2 else ""))
    p.coast(period(r2), "final", "Final orbit")
    return p.result("Hohmann transfer")


def bielliptic(alt1, alt2, alt_b, i1=0.0, i2=0.0, mass=1000.0, isp=320.0):
    """
    Bi-elliptic transfer: out to an intermediate apoapsis rb, then down
    to the target. Any plane change is done at rb, where it is cheapest.
    """
    _check_alt(alt1, "Initial altitude"); _check_alt(alt2, "Final altitude")
    _check_alt(alt_b, "Intermediate altitude")
    r1, r2, rb = R_EARTH + alt1, R_EARTH + alt2, R_EARTH + alt_b
    if rb < max(r1, r2):
        raise ValueError("The intermediate apoapsis must be above both orbits.")

    pos, tan = on_node_line(r1, 180.0, i1)
    p = _Plan(pos, circ_speed(r1) * tan, mass, isp)
    p.coast(period(r1) / 2, "initial", "Initial orbit")

    a1 = (r1 + rb) / 2
    _, tan = on_node_line(r1, 0.0, i1)
    p.burn(vis_viva(r1, a1) * tan, "Δv₁ · first ellipse")
    p.coast(period(a1) / 2, "transfer", "First transfer ellipse")

    a2 = (r2 + rb) / 2
    _, tan = on_node_line(rb, 180.0, i2)
    p.burn(vis_viva(rb, a2) * tan, "Δv₂ · at apoapsis" + (" + plane change" if i1 != i2 else ""))
    p.coast(period(a2) / 2, "transfer", "Second transfer ellipse")

    _, tan = on_node_line(r2, 0.0, i2)
    p.burn(circ_speed(r2) * tan, "Δv₃ · circularise")
    p.coast(period(r2), "final", "Final orbit")
    return p.result("Bi-elliptic transfer")


def plane_change(alt, i1, i2, mass=1000.0, isp=320.0):
    """Pure inclination change of a circular orbit, at the node."""
    _check_alt(alt, "Altitude")
    r = R_EARTH + alt
    pos, tan = on_node_line(r, 180.0, i1)
    p = _Plan(pos, circ_speed(r) * tan, mass, isp)
    p.coast(period(r) / 2, "initial", "Initial orbit")
    _, tan = on_node_line(r, 0.0, i2)
    p.burn(circ_speed(r) * tan, "Δv · plane change")
    p.coast(period(r), "final", "Final orbit")
    return p.result("Plane change", [f"Δv = 2 v sin(Δi/2) = {2 * circ_speed(r) * math.sin(math.radians(abs(i2 - i1)) / 2):.4f} km/s"])


def circularize(r0, v0, where="apogee", mass=1000.0, isp=320.0):
    """
    Circularise a closed orbit (e.g. the Lambert solution) at its apogee
    (raising the perigee) or at its perigee (lowering the apogee).
    """
    r0, v0 = np.asarray(r0, float), np.asarray(v0, float)
    el = state_to_elements(r0, v0)
    if el["period"] is None:
        raise ValueError("Only a closed (elliptical) orbit can be circularised.")
    if el["alt_p"] < 100.0 and where == "perigee":
        raise ValueError("The perigee is inside the atmosphere; circularise at apogee instead.")

    # Time from r0 to the chosen apsis, from the mean anomaly.
    n = el["mean_motion"]
    M0 = math.radians(el["M_anom"])
    target = math.pi if where == "apogee" else 0.0
    dt = ((target - M0) % (2 * math.pi)) / n

    p = _Plan(r0, v0, mass, isp)
    p.coast(dt, "initial", "Original orbit (from observation 1)")
    rn = float(np.linalg.norm(p.r))
    h = np.cross(p.r, p.v)
    tangent = np.cross(h, p.r)
    tangent /= np.linalg.norm(tangent)
    p.burn(circ_speed(rn) * tangent, f"Δv · circularise at {where}")
    p.coast(period(rn), "final", "Circular orbit")
    return p.result(f"Circularise at {where}", [f"Circular orbit altitude: {rn - R_EARTH:,.0f} km"])


def compare(alt1, alt2, i1, i2, alt_b):
    """Total delta-v of the alternatives for the same start and target."""
    rows = []
    for name, fn in (("Hohmann, plane change combined at apoapsis", lambda: hohmann(alt1, alt2, i1, i2)),
                     ("Plane change first, then Hohmann",
                      lambda: {"total_dv": plane_change(alt1, i1, i2)["total_dv"] + hohmann(alt1, alt2, i2, i2)["total_dv"],
                               "transfer_time": hohmann(alt1, alt2, i2, i2)["transfer_time"]}),
                     ("Bi-elliptic, plane change at far apoapsis", lambda: bielliptic(alt1, alt2, alt_b, i1, i2))):
        try:
            r = fn()
            rows.append({"name": name, "total_dv": r["total_dv"], "time": r["transfer_time"]})
        except ValueError as exc:
            rows.append({"name": name, "total_dv": None, "time": None, "error": str(exc)})
    best = min((r for r in rows if r["total_dv"] is not None), key=lambda r: r["total_dv"], default=None)
    for r in rows:
        r["best"] = r is best
    return rows


if __name__ == "__main__":
    h = hohmann(300, 35786, 28.5, 0.0)
    print(f"LEO (28.5°) -> GEO: {[round(b['dv'], 4) for b in h['burns']]}  total {h['total_dv']:.4f} km/s")
    h = hohmann(300, 35786)
    print(f"LEO -> GEO (coplanar): total {h['total_dv']:.4f} km/s")
    for row in compare(300, 35786, 28.5, 0.0, 100000):
        print(f"  {row['name']:<45} {row['total_dv']:.4f} km/s{'  <- best' if row['best'] else ''}")
