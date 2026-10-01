"""
"How the answers change with time": five studies run with Lambert Studio's own
physics, written to report/img/study_*.png and report/study_results.json.

  1. the same orbit through the solar cycle (atmospheric drag, NRLMSIS)
  2. a geostationary satellite over one year (Sun, Moon, Earth's shape)
  3. the same Earth -> Mars trip in every launch window to 2042
  4. how far away Mars is, and the radio delay, through the years
  5. the simple route model vs the full solar system, flown for real

usage: python report/study_time.py [--es] [study numbers, default all]
  --es  Spanish chart labels, written to img/study_*_es.png (the numbers in
        study_results.json are left untouched)
"""
import datetime, json, pathlib, sys, time
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
import flyby, interplanetary, nbody, perturb                                 # noqa: E402
import studio_server as srv                                                  # noqa: E402
from time_utils import julian_date                                           # noqa: E402

INK, INK2, RULE = "#0f1a2b", "#4a586e", "#d5dbe4"
CYAN, ORANGE, GREEN, RED = "#0e7fb3", "#c55a12", "#1d8a5b", "#b23a3a"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": RULE, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "text.color": INK, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.grid": True, "grid.color": "#e6eaf0", "grid.linewidth": .8,
                     "figure.dpi": 100, "savefig.dpi": 200, "figure.facecolor": "white", "axes.facecolor": "white"})

OUT = ROOT / "study_results.json"
res = json.loads(OUT.read_text()) if OUT.exists() else {}
ES = "--es" in sys.argv[1:]
want = {int(a) for a in sys.argv[1:] if a != "--es"} or {1, 2, 3, 4, 5}


def L(en, es):
    """Chart text in the chosen language."""
    return es if ES else en


def comma(*axes):
    """Spanish charts use a decimal comma on linear axes."""
    if ES:
        fmt = matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:g}".replace(".", ","))
        for ax in axes:
            ax.yaxis.set_major_formatter(fmt)
            if ax.get_xscale() == "linear":
                ax.xaxis.set_major_formatter(fmt)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(ROOT / "img" / f"{name}{'_es' if ES else ''}.png", facecolor="white")
    plt.close(fig)
    if not ES:
        OUT.write_text(json.dumps(res, indent=1))
    print("saved", name, flush=True)


def moving(x, n):
    k = np.ones(n) / n
    return np.convolve(np.pad(x, (n // 2, n - 1 - n // 2), mode="edge"), k, mode="valid")


# ---------------------------------------------------------------- 1 solar cycle
if 1 in want:
    t0 = time.time()
    req = {"source": "preset", "alt_p": 415, "alt_a": 425, "i": 51.6, "raan": 0, "argp": 0, "days": 90,
           "drag": True, "cd": 2.2, "area": 1600, "mass": 420000, "date": "2026-10-01"}
    fig, ax = plt.subplots(figsize=(7.4, 3.9))
    rows = {}
    for act, col, lab in (("low", CYAN, L("Solar minimum (F10.7 = 70)", "Mínimo solar (F10.7 = 70)")),
                          ("moderate", INK2, L("Moderate (F10.7 = 150)", "Moderada (F10.7 = 150)")),
                          ("high", ORANGE, L("Solar maximum (F10.7 = 250)", "Máximo solar (F10.7 = 250)"))):
        o = srv.api_perturb({**req, "model": {"zonal_degree": 6, "tesseral": True, "sun": True, "moon": True,
                                              "srp": False, "drag": "msis", "activity": act}})
        d = np.asarray(o["days"]); alt = (np.asarray(o["alt_p"]) + np.asarray(o["alt_a"])) / 2
        dd = np.linspace(0, d[-1], 90 * 24 * 4)                            # uniform grid, 15 min
        alt = moving(moving(np.interp(dd, d, alt), 96), 96)                          # one-day average removes the orbit wobble
        d, alt = dd[192:-192], alt[192:-192]
        ax.plot(d, alt, color=col, lw=2, label=lab)
        fit = np.polyfit(d, alt, 1)
        rows[act] = {"decay_m_per_day": float(-fit[0] * 1000), "alt_end_km": float(alt[-1]), "alt_start_km": float(alt[0])}
    ax.set_xlabel(L("days after 1 Oct 2026", "días desde el 1 oct 2026")); ax.set_ylabel(L("mean altitude (km)", "altitud media (km)"))
    comma(ax)
    ax.legend(frameon=False, loc="lower left")
    ax.set_title(L("The same 420 km orbit, three Sun conditions", "La misma órbita de 420 km, tres condiciones del Sol"), loc="left", fontsize=11, fontweight="bold", color=INK)
    save(fig, "study_solar")
    res["solar"] = {"rows": rows, "seconds": time.time() - t0}

# ---------------------------------------------------------------- 2 GEO year
if 2 in want:
    t0 = time.time()
    pr = perturb.PRESETS["geo"]
    o = srv.api_perturb({"source": "preset", "alt_p": pr["alt_p"], "alt_a": pr["alt_a"], "i": pr["i"], "raan": 0, "argp": 0,
                         "days": 365, "cd": pr["cd"], "area": pr["area"], "mass": pr["mass"], "cr": pr["cr"],
                         "lon": pr["lon"], "date": "2026-01-01", "model": pr["model"]})
    d = np.asarray(o["days"]); lon = np.asarray(o["lon"]); inc = np.asarray(o["i"])
    lon = (lon + 180) % 360 - 180
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.6, 3.5))
    a1.plot(d, lon, color=CYAN, lw=1.6); a1.axhline(75.07, color=ORANGE, lw=1, ls="--")
    a1.text(4, 75.07 + 1.5, L("stable point 75.1°E", "punto estable 75,1°E"), color=ORANGE, fontsize=8.5)
    a1.set_xlabel(L("days after 1 Jan 2026", "días desde el 1 ene 2026")); a1.set_ylabel(L("longitude (°E)", "longitud (°E)"))
    a1.set_title(L("Drifts toward the gravity well", "Deriva hacia el pozo gravitatorio"), loc="left", fontsize=10, fontweight="bold")
    a2.plot(d, inc, color=ORANGE, lw=1.6)
    a2.set_xlabel(L("days after 1 Jan 2026", "días desde el 1 ene 2026")); a2.set_ylabel(L("inclination (°)", "inclinación (°)"))
    a2.set_title(L("Tilts away from the equator", "Se inclina respecto al ecuador"), loc="left", fontsize=10, fontweight="bold")
    comma(a1, a2)
    save(fig, "study_geo")
    res["geo"] = {"lon_start": float(lon[0]), "lon_end": float(lon[-1]), "lon_max": float(lon.max()),
                  "inc_end": float(inc[-1]), "inc_max": float(inc.max()), "seconds": time.time() - t0}

# ---------------------------------------------------------------- 3 launch windows
if 3 in want:
    t0 = time.time()
    first = julian_date(2026, 11, 15, 0, 0, 0.0)
    rows = []
    for k in range(9):
        c = first + k * 779.94
        dep = (c - 130, c + 130); arr = (c + 150, c + 150 + 420)
        dg, ag, Z = interplanetary.porkchop("Earth", "Mars", dep, arr, n_dep=46, n_arr=46)
        b = interplanetary.best_transfer(dg, ag, Z)
        if not b:
            continue
        t = interplanetary.transfer("Earth", "Mars", b["jd_departure"], b["jd_arrival"])
        rows.append({"dep": srv.jd_to_iso(b["jd_departure"])[:10], "arr": srv.jd_to_iso(b["jd_arrival"])[:10],
                     "tof": b["tof_days"], "c3": b["c3"], "vinf_arr": t["vinf_arrival"],
                     "dv_dep": t["dv_departure"], "dv_cap": t["dv_arrival"]})
        print(rows[-1], flush=True)
    yrs = [datetime.date.fromisoformat(r["dep"]).year + datetime.date.fromisoformat(r["dep"]).timetuple().tm_yday / 365 for r in rows]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(7.6, 3.6))
    a1.bar(yrs, [r["c3"] for r in rows], width=.9, color=CYAN)
    a1.set_ylabel(L("launch energy C3 (km²/s²)", "energía de lanzamiento C3 (km²/s²)")); a1.set_xlabel(L("best departure date", "mejor fecha de salida"))
    a1.set_title(L("Cost of leaving Earth", "Coste de salir de la Tierra"), loc="left", fontsize=10, fontweight="bold")
    a2.bar(yrs, [r["vinf_arr"] for r in rows], width=.9, color=ORANGE)
    a2.set_ylabel(L("arrival speed at Mars v∞ (km/s)", "velocidad de llegada a Marte v∞ (km/s)")); a2.set_xlabel(L("best departure date", "mejor fecha de salida"))
    a2.set_title(L("Cost of stopping at Mars", "Coste de frenar en Marte"), loc="left", fontsize=10, fontweight="bold")
    comma(a1, a2)
    save(fig, "study_windows")
    res["windows"] = {"rows": rows, "seconds": time.time() - t0}

# ---------------------------------------------------------------- 4 distance & radio delay
if 4 in want:
    jd = julian_date(2026, 1, 1, 0, 0, 0.0) + np.arange(0, 16 * 365.25, 4.0)
    re, _ = interplanetary.planet_states_array("Earth", jd)
    rm, _ = interplanetary.planet_states_array("Mars", jd)
    dist = np.linalg.norm(rm - re, axis=1)
    delay = dist / 299792.458 / 60
    yr = 2026 + (jd - jd[0]) / 365.25
    fig, ax = plt.subplots(figsize=(7.4, 3.4))
    ax.fill_between(yr, delay, color=CYAN, alpha=.12); ax.plot(yr, delay, color=CYAN, lw=1.8)
    ax.set_ylabel(L("one-way radio delay (minutes)", "retardo de radio de ida (minutos)")); ax.set_xlabel(L("year", "año"))
    comma(ax)
    ax.set_title(L("A message to Mars takes 3 to 22 minutes, depending on the date", "Un mensaje a Marte tarda de 3 a 22 minutos, según la fecha"), loc="left", fontsize=11, fontweight="bold")
    save(fig, "study_delay")
    res["delay"] = {"min_min": float(delay.min()), "max_min": float(delay.max()),
                    "min_km": float(dist.min()), "max_km": float(dist.max())}

# ---------------------------------------------------------------- 5 simple vs full gravity
if 5 in want:
    t0 = time.time()
    rows = []
    for key in ("mars_dir", "voyager", "cassini"):
        if key == "mars_dir":
            seq, jds, cap, name = ["Earth", "Mars"], [julian_date(2026, 11, 1, 0, 0, 0.0), julian_date(2027, 8, 20, 0, 0, 0.0)], True, "Earth → Mars (direct, 2026)"
            out = srv.api_verify_route({"seq": seq, "jds": jds, "capture": cap})
        else:
            pr = next(p for p in flyby.PRESETS if p["key"] == key)
            w = (srv._jd_from_date(pr["from"], "a"), srv._jd_from_date(pr["to"], "b"))
            d = flyby.optimise(pr["seq"], w, pr["capture"], max_days=pr["max_years"] * 365.25)
            d["launch_dv"] = float(flyby._launch_dv(d["vinf_launch"], pr["seq"][0]))
            out = nbody.verify(d); name = pr.get("label", key)
        u = out["uncorrected"]
        rows.append({"name": name, "uncorrected_miss_km": u["miss_km"], "impact": u["impact"], "target": u["planet"],
                     "tcm_ms": out["tcm_total"] * 1000, "dv_design": out["design_total_dv"], "dv_full": out["total_dv"],
                     "notes": out["notes"], "seconds": out["seconds"]})
        print(rows[-1], flush=True)
    fig, ax = plt.subplots(figsize=(7.6, 3.4))
    short = {"Earth → Mars (direct, 2026)": L("Earth → Mars", "Tierra → Marte"),
             "Voyager: Earth → Jupiter → Saturn": L("Voyager (Jupiter, Saturn)", "Voyager (Júpiter, Saturno)")}
    es_name = {"Mars": "Marte", "Jupiter": "Júpiter", "Venus": "Venus", "Saturn": "Saturno", "Earth": "la Tierra"}
    names = []
    for r in rows:
        nm = short.get(r["name"], L("Cassini (4 flybys)", "Cassini (4 sobrevuelos)"))
        tgt = es_name.get(r["target"], r["target"]) if ES else r["target"]
        miss = f"{r['uncorrected_miss_km'] / 1000:,.0f}".replace(",", " ")
        fate = (L(f"hits {tgt}", f"choca contra {tgt}") if r["impact"]
                else L(f"misses {tgt} by {r['uncorrected_miss_km'] / 1000:,.0f} thousand km", f"pasa a {miss} mil km de {tgt}"))
        names.append(nm + chr(10) + L("uncorrected: ", "sin corregir: ") + fate)
    tcm = [max(float(r["tcm_ms"]), 0.1) for r in rows]
    ax.axvspan(10, 100, color=GREEN, alpha=.12, lw=0)
    ax.text(10.6, -0.55, L("typical real mission budget", "presupuesto típico de una misión real"), color=GREEN, fontsize=8, va="center")
    ax.barh(range(3), tcm, color=[CYAN, CYAN, ORANGE], height=.5)
    ax.set_yticks(range(3)); ax.set_yticklabels(names, fontsize=8.5)
    ax.set_xscale("log"); ax.set_xlim(0.1, 4000); ax.set_ylim(2.6, -0.85)
    ax.set_xlabel(L("course corrections needed in full gravity (m/s, log scale)", "correcciones necesarias con gravedad completa (m/s, escala log.)"))
    for i, r in enumerate(rows):
        v = float(r["tcm_ms"])
        lab = f"{v:.2f} m/s" if v < 1 else f"{v:.1f} m/s"
        ax.text(tcm[i] * 1.2, i, lab.replace(".", ",") if ES else lab, va="center", fontsize=9, color=INK, fontweight="bold")
    ax.set_title(L("Simple model vs the real solar system", "Modelo simple frente al sistema solar real"), loc="left", fontsize=11, fontweight="bold")
    save(fig, "study_nbody")
    res["nbody"] = {"rows": rows, "seconds": time.time() - t0}
if not ES:
    OUT.write_text(json.dumps(res, indent=1))
