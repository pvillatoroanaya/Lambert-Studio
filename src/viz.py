"""
Plotly figures for the dashboard. Each function returns a go.Figure and
does no file I/O; dashboard.py decides where they go.

Colours match the app palette so the dashboard and GUI read as one
product.
"""

import datetime
import math

import numpy as np
import plotly.graph_objects as go

from constants import R_EARTH, AU
from coord_utils import rot3
from planets import PLANET_ORDER, PLANET_STYLE, planet_state, planet_orbit_path

BG = "#0b1020"
PANEL = "#121a2f"
FG = "#e6edf7"
MUTED = "#8fa3c8"
ACCENT = "#5ac8fa"
ACCENT2 = "#ffb454"
OBS = "#ff5a5f"
GRID = "rgba(140,165,210,0.18)"


def _base_layout(fig, title, three_d=True):
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=FG), x=0.01),
        paper_bgcolor=BG, plot_bgcolor=BG,
        font=dict(color=FG, family="Inter, Segoe UI, Helvetica, Arial"),
        margin=dict(l=10, r=10, t=48, b=10),
        legend=dict(bgcolor="rgba(18,26,47,0.8)", bordercolor=GRID, borderwidth=1),
    )
    if three_d:
        axis = dict(backgroundcolor=BG, gridcolor=GRID, zerolinecolor=GRID,
                    color=MUTED, showspikes=False)
        fig.update_layout(scene=dict(xaxis=dict(axis, title="x [km]"),
                                     yaxis=dict(axis, title="y [km]"),
                                     zaxis=dict(axis, title="z [km]"),
                                     aspectmode="data"))
    return fig


def _sphere(radius, center=(0.0, 0.0, 0.0), n=40):
    u = np.linspace(0, 2 * np.pi, n)
    v = np.linspace(0, np.pi, n // 2)
    x = center[0] + radius * np.outer(np.cos(u), np.sin(v))
    y = center[1] + radius * np.outer(np.sin(u), np.sin(v))
    z = center[2] + radius * np.outer(np.ones_like(u), np.cos(v))
    return x, y, z


def _earth_traces(gmst=0.0):
    """Earth to scale, with a lat/lon graticule rotated to the epoch."""
    x, y, z = _sphere(R_EARTH, n=60)
    traces = [go.Surface(x=x, y=y, z=z, surfacecolor=z,
                         colorscale=[[0, "#0d3a66"], [0.5, "#1c5f9e"], [1, "#0d3a66"]],
                         showscale=False, opacity=1.0, hoverinfo="skip",
                         name="Earth", lighting=dict(ambient=0.7, diffuse=0.5))]
    Rz = rot3(gmst)
    r = R_EARTH * 1.002
    lines_x, lines_y, lines_z = [], [], []
    for lon in range(0, 360, 30):                       # meridians
        t = np.radians(np.linspace(-90, 90, 50))
        l = math.radians(lon)
        P = Rz @ np.vstack([r * np.cos(t) * math.cos(l), r * np.cos(t) * math.sin(l), r * np.sin(t)])
        lines_x += list(P[0]) + [None]
        lines_y += list(P[1]) + [None]
        lines_z += list(P[2]) + [None]
    for lat in range(-60, 90, 30):                      # parallels
        t = np.radians(np.linspace(0, 360, 90))
        b = math.radians(lat)
        P = Rz @ np.vstack([r * math.cos(b) * np.cos(t), r * math.cos(b) * np.sin(t),
                            np.full_like(t, r * math.sin(b))])
        lines_x += list(P[0]) + [None]
        lines_y += list(P[1]) + [None]
        lines_z += list(P[2]) + [None]
    traces.append(go.Scatter3d(x=lines_x, y=lines_y, z=lines_z, mode="lines",
                               line=dict(color="rgba(200,220,255,0.25)", width=1),
                               hoverinfo="skip", showlegend=False))
    return traces


def _track3d(R, name, color, width=4, dash=None):
    return go.Scatter3d(x=R[:, 0], y=R[:, 1], z=R[:, 2], mode="lines", name=name,
                        line=dict(color=color, width=width, dash=dash))


def _point3d(r, name, color, size=6, symbol="circle"):
    return go.Scatter3d(x=[r[0]], y=[r[1]], z=[r[2]], mode="markers+text",
                        name=name, text=[name], textposition="top center",
                        marker=dict(color=color, size=size, symbol=symbol))


def _vector3d(r, name, color):
    return go.Scatter3d(x=[0, r[0]], y=[0, r[1]], z=[0, r[2]], mode="lines",
                        name=name, line=dict(color=color, width=3, dash="dot"))


# ----------------------------------------------------------------------
# Earth-centred views
# ----------------------------------------------------------------------

def fig_orbit_eci(R, r1, r2, el, gmst=0.0, r_station_eci=None):
    fig = go.Figure(_earth_traces(gmst))
    fig.add_trace(_track3d(R, "Orbit", ACCENT))
    fig.add_trace(_vector3d(r1, "r₁", ACCENT2))
    fig.add_trace(_vector3d(r2, "r₂", ACCENT2))
    fig.add_trace(_point3d(r1, "r₁", OBS))
    fig.add_trace(_point3d(r2, "r₂", OBS))
    if r_station_eci is not None:
        fig.add_trace(_point3d(r_station_eci, "Station", "#7bed9f", size=4, symbol="diamond"))
    return _base_layout(fig, f"Orbit in the inertial frame (ECI) — "
                             f"{el['orbit_type'].lower()}, a = {el['a']:,.0f} km")


def fig_orbit_ecef(R_ecef):
    fig = go.Figure(_earth_traces(0.0))
    fig.add_trace(_track3d(R_ecef, "Track (Earth-fixed)", ACCENT))
    return _base_layout(fig, "Same trajectory in the Earth-fixed frame (ECEF)")


def fig_ground_track(lat, lon, alt, station_latlon=None):
    fig = go.Figure(go.Scattergeo(
        lat=lat, lon=lon, mode="lines", name="Ground track",
        line=dict(color=ACCENT, width=2),
        customdata=alt, hovertemplate="lat %{lat:.2f}°<br>lon %{lon:.2f}°"
                                      "<br>alt %{customdata:,.0f} km<extra></extra>"))
    if station_latlon is not None:
        fig.add_trace(go.Scattergeo(lat=[station_latlon[0]], lon=[station_latlon[1]],
                                    mode="markers+text", text=["Station"],
                                    textposition="top center", name="Station",
                                    marker=dict(color="#7bed9f", size=9, symbol="diamond")))
    fig.update_geos(projection_type="equirectangular", showland=True,
                    landcolor="#1d2a47", showocean=True, oceancolor="#0d1a33",
                    coastlinecolor="#5b6f95", showcountries=True, countrycolor=GRID,
                    lataxis=dict(showgrid=True, gridcolor=GRID),
                    lonaxis=dict(showgrid=True, gridcolor=GRID), bgcolor=BG)
    return _base_layout(fig, "Ground track", three_d=False)


def fig_sky_view(az, elev, rng, obs_marks=()):
    """Polar sky plot: zenith at the centre, horizon at the rim, North up."""
    up = elev >= 0
    az_v = np.where(up, az, np.nan)
    r_v = np.where(up, 90.0 - elev, np.nan)
    fig = go.Figure(go.Scatterpolar(
        theta=az_v, r=r_v, mode="lines", name="Pass", line=dict(color=ACCENT, width=3),
        customdata=np.vstack([elev, rng]).T,
        hovertemplate="az %{theta:.1f}°<br>el %{customdata[0]:.1f}°"
                      "<br>range %{customdata[1]:,.0f} km<extra></extra>"))
    for label, a, e in obs_marks:
        fig.add_trace(go.Scatterpolar(theta=[a], r=[90.0 - e], mode="markers+text",
                                      text=[label], textposition="top center", name=label,
                                      marker=dict(color=OBS, size=11)))
    fig.update_layout(polar=dict(
        bgcolor=PANEL,
        radialaxis=dict(range=[0, 90], tickvals=[0, 30, 60, 90],
                        ticktext=["90°", "60°", "30°", "0°"], gridcolor=GRID, color=MUTED),
        angularaxis=dict(rotation=90, direction="clockwise", gridcolor=GRID, color=MUTED)))
    return _base_layout(fig, "Sky view from the station", three_d=False)


def fig_perifocal(P, el, p1, p2):
    fig = go.Figure()
    t = np.linspace(0, 2 * np.pi, 200)
    fig.add_trace(go.Scatter(x=R_EARTH * np.cos(t), y=R_EARTH * np.sin(t), fill="toself",
                             fillcolor="#1c5f9e", line=dict(color="#1c5f9e"),
                             name="Earth", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=P[:, 0], y=P[:, 1], mode="lines", name="Orbit",
                             line=dict(color=ACCENT, width=3)))
    for p, name in ((p1, "r₁"), (p2, "r₂")):
        fig.add_trace(go.Scatter(x=[p[0]], y=[p[1]], mode="markers+text", text=[name],
                                 textposition="top center", name=name,
                                 marker=dict(color=OBS, size=10)))
    fig.add_trace(go.Scatter(x=[el["r_p"]], y=[0], mode="markers+text", text=["perigee"],
                             textposition="bottom center", name="Perigee",
                             marker=dict(color=ACCENT2, size=9, symbol="x")))
    if el["r_a"] is not None:
        fig.add_trace(go.Scatter(x=[-el["r_a"]], y=[0], mode="markers+text", text=["apogee"],
                                 textposition="bottom center", name="Apogee",
                                 marker=dict(color=ACCENT2, size=9, symbol="x")))
    _base_layout(fig, "Perifocal frame (orbit seen face-on)", three_d=False)
    fig.update_xaxes(title="p [km]", gridcolor=GRID, zerolinecolor=GRID, color=MUTED)
    fig.update_yaxes(title="q [km]", gridcolor=GRID, zerolinecolor=GRID, color=MUTED,
                     scaleanchor="x", scaleratio=1)
    return fig


# ----------------------------------------------------------------------
# Heliocentric views
# ----------------------------------------------------------------------

def fig_solar_system(jd, transfer_result=None, transfer_track=None,
                     max_planet="Mars", title="Solar system"):
    """Planet orbits and positions at `jd`, in AU, ecliptic frame."""
    fig = go.Figure()
    fig.add_trace(go.Scatter3d(x=[0], y=[0], z=[0], mode="markers", name="Sun",
                               marker=dict(color="#ffd166", size=12)))
    last = PLANET_ORDER.index(max_planet)
    for name in PLANET_ORDER[:last + 1]:
        color = PLANET_STYLE[name]["color"]
        path = planet_orbit_path(name, jd) / AU
        fig.add_trace(go.Scatter3d(x=path[:, 0], y=path[:, 1], z=path[:, 2],
                                   mode="lines", line=dict(color=color, width=2),
                                   name=f"{name} orbit", showlegend=False,
                                   hoverinfo="skip", opacity=0.6))
        r, _ = planet_state(name, jd)
        r = r / AU
        fig.add_trace(go.Scatter3d(x=[r[0]], y=[r[1]], z=[r[2]], mode="markers+text",
                                   text=[name], textposition="top center", name=name,
                                   marker=dict(color=color, size=6)))

    if transfer_track is not None:
        T = np.asarray(transfer_track) / AU
        fig.add_trace(go.Scatter3d(x=T[:, 0], y=T[:, 1], z=T[:, 2], mode="lines",
                                   name="Transfer", line=dict(color=ACCENT, width=5)))
    if transfer_result is not None:
        r2 = transfer_result["r2"] / AU
        fig.add_trace(go.Scatter3d(x=[r2[0]], y=[r2[1]], z=[r2[2]], mode="markers",
                                   name=f"{transfer_result['arrival']} at arrival",
                                   marker=dict(color=OBS, size=6, symbol="diamond")))

    _base_layout(fig, title)
    axis = dict(backgroundcolor=BG, gridcolor=GRID, zerolinecolor=GRID, color=MUTED)
    fig.update_layout(scene=dict(xaxis=dict(axis, title="x [AU]"),
                                 yaxis=dict(axis, title="y [AU]"),
                                 zaxis=dict(axis, title="z [AU]"),
                                 aspectmode="data"))
    return fig


def _jd_to_datetime(jd):
    return datetime.datetime(2000, 1, 1, 12) + datetime.timedelta(days=float(jd) - 2451545.0)


def fig_porkchop(dep, arr, Z, dep_name, arr_name, best=None):
    x = [_jd_to_datetime(j) for j in dep]
    y = [_jd_to_datetime(j) for j in arr]
    zmax = float(np.nanpercentile(Z, 60)) if np.isfinite(Z).any() else None
    fig = go.Figure(go.Contour(
        x=x, y=y, z=Z, colorscale="Viridis_r", zmin=float(np.nanmin(Z)) if zmax else None,
        zmax=zmax, contours=dict(showlabels=True, labelfont=dict(color="white", size=10)),
        colorbar=dict(title="C₃ [km²/s²]"),
        hovertemplate="depart %{x|%Y-%m-%d}<br>arrive %{y|%Y-%m-%d}"
                      "<br>C₃ %{z:.1f} km²/s²<extra></extra>"))
    if best is not None:
        fig.add_trace(go.Scatter(
            x=[_jd_to_datetime(best["jd_departure"])], y=[_jd_to_datetime(best["jd_arrival"])],
            mode="markers+text", text=[f"min C₃ {best['c3']:.1f}"], textposition="top right",
            marker=dict(color=OBS, size=12, symbol="star"), name="Best"))
    _base_layout(fig, f"Porkchop plot — {dep_name} → {arr_name}", three_d=False)
    fig.update_xaxes(title="Departure date", gridcolor=GRID, color=MUTED)
    fig.update_yaxes(title="Arrival date", gridcolor=GRID, color=MUTED)
    return fig
