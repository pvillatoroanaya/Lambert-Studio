"""Rebuild the dashboard for the assignment case (used by tests and the GUI)."""
import numpy as np

from time_utils import julian_date, gmst_from_jd, time_of_flight
from coord_utils import topocentric_to_geocentric
from lambert_solver import lambert_universal
from orbital_elements import state_to_elements
from interplanetary import transfer, porkchop, best_transfer
from dashboard import build_dashboard

STATION = np.array([1344.143, 6068.601, 1429.311])


def assignment_solution():
    jd1 = julian_date(2023, 4, 2, 0, 30, 0.0)
    jd2 = julian_date(2023, 4, 2, 3, 0, 0.0)
    r1 = topocentric_to_geocentric(132.67, 32.44, 16945.450, STATION, gmst_from_jd(jd1))
    r2 = topocentric_to_geocentric(123.08, 50.06, 37350.340, STATION, gmst_from_jd(jd2))
    dt = time_of_flight(jd1, jd2)
    v1, v2, z = lambert_universal(r1, r2, dt)
    sol = dict(r1=r1, r2=r2, v1=v1, v2=v2, dt=dt, z=z,
               elems=state_to_elements(r1, v1), r_station=STATION,
               mode="observations", prograde=True)
    return sol, jd1


def build(path="lambert_dashboard.html", with_interplanetary=True, n=45):
    sol, jd1 = assignment_solution()
    tr = pork = None
    if with_interplanetary:
        tr = transfer("Earth", "Mars",
                       julian_date(2026, 11, 1, 0, 0, 0.0),
                       julian_date(2027, 8, 20, 0, 0, 0.0))
        dep, arr, Z = porkchop("Earth", "Mars",
                                (julian_date(2026, 8, 1, 0, 0, 0.0),
                                 julian_date(2027, 3, 1, 0, 0, 0.0)),
                                (julian_date(2027, 3, 1, 0, 0, 0.0),
                                 julian_date(2028, 2, 1, 0, 0, 0.0)),
                                n_dep=n, n_arr=n)
        pork = (dep, arr, Z, best_transfer(dep, arr, Z), "Earth", "Mars")
    return build_dashboard(sol, path, jd0=jd1, interplanetary=tr, porkchop_data=pork)


if __name__ == "__main__":
    print("wrote", build())
