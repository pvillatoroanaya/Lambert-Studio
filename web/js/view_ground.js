/* Ground track (map) and sky view (what the station sees), both
   following the same clock as the Orbit view. */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const view = {
    id: 'ground',
    title: 'Ground track & sky view',
    subtitle: 'Sub-satellite point over one orbit · station sky: zenith at centre, north up',
  };
  LS.views.ground = view;

  let drawn = null, timer = 0;

  view.init = function () {
    view.clock = LS.views.orbit.clock;           // one shared timeline
    LS.on('solved', () => { drawn = null; if (LS.activeView === view) draw(); });
  };

  view.show = function () {
    if (LS.solution && drawn !== LS.solution) draw();
    ['ch-ground', 'ch-sky'].forEach((id) => { const el = $(id); if (el.data) Plotly.Plots.resize(el); });
  };

  function draw() {
    const sol = LS.solution;
    drawn = sol;
    $('empty-ground').hidden = true;
    const g = sol.ground;

    const traces = [{
      type: 'scattergl', mode: 'lines', x: g.lon, y: g.lat, name: 'Ground track',
      line: { color: '#5eb3e6', width: 2.5 }, customdata: g.alt, connectgaps: false,
      hovertemplate: 'lat %{y:.2f}°<br>lon %{x:.2f}°<br>alt %{customdata:,.0f} km<extra></extra>',
    }, {
      type: 'scatter', mode: 'markers', x: [g.lon[0]], y: [g.lat[0]], name: 'Obs 1 epoch',
      marker: { color: '#eea55a', size: 9, line: { color: '#070b16', width: 1.5 } },
    }, {
      type: 'scatter', mode: 'markers', x: [null], y: [null], name: 'Satellite now',
      marker: { color: '#ffffff', size: 12, line: { color: '#5eb3e6', width: 3 } },
    }];
    if (sol.station_latlon) {
      traces.push({ type: 'scatter', mode: 'markers+text', x: [sol.station_latlon[1]], y: [sol.station_latlon[0]],
        name: 'Station', text: ['Station'], textposition: 'top center', textfont: { color: '#7fcf9f' },
        marker: { color: '#7fcf9f', size: 11, symbol: 'diamond', line: { color: '#070b16', width: 1.5 } } });
    }
    const layout = LS.plotLayout({
      title: { text: 'Ground track', x: 0.02, font: { size: 14 } },
      xaxis: { range: [-180, 180], dtick: 30, ticksuffix: '°', gridcolor: 'rgba(255,255,255,0.12)', color: '#8d95a8',
        zeroline: false, constrain: 'domain' },
      yaxis: { range: [-90, 90], dtick: 30, ticksuffix: '°', gridcolor: 'rgba(255,255,255,0.12)', color: '#8d95a8',
        scaleanchor: 'x', scaleratio: 1, zeroline: false, constrain: 'domain' },
      images: [{ source: 'textures/earth_day_hd.jpg', xref: 'x', yref: 'y', x: -180, y: 90, sizex: 360, sizey: 180,
        sizing: 'stretch', layer: 'below', opacity: 0.85 }],
      margin: { l: 50, r: 16, t: 66, b: 36 },
    });
    Plotly.react('ch-ground', traces, layout, LS.plotConfig);

    const sky = sol.sky;
    const sTraces = [];
    if (sky) {
      const r = sky.el.map((e) => (e >= 0 ? 90 - e : null));
      sTraces.push({ type: 'scatterpolar', mode: 'lines', theta: sky.az, r, name: 'Pass',
        line: { color: '#5eb3e6', width: 3 }, connectgaps: false,
        customdata: sky.el.map((e, k) => [e, sky.rng[k]]),
        hovertemplate: 'az %{theta:.1f}°<br>el %{customdata[0]:.1f}°<br>range %{customdata[1]:,.0f} km<extra></extra>' });
      if (sol.mode === 'observations') {
        sTraces.push({ type: 'scatterpolar', mode: 'markers+text', theta: sky.marks.map((m) => m.az),
          r: sky.marks.map((m) => 90 - m.el), text: sky.marks.map((m) => m.label), textposition: 'top center',
          name: 'Observations', marker: { color: '#e56f6f', size: 11 }, textfont: { color: '#eea55a' } });
      }
      sTraces.push({ type: 'scatterpolar', mode: 'markers', theta: [null], r: [null], name: 'Satellite now',
        marker: { color: '#ffffff', size: 12, line: { color: '#5eb3e6', width: 3 } } });
    }
    Plotly.react('ch-sky', sTraces, LS.plotLayout({
      title: { text: sky ? 'Sky from the station' : 'Sky view needs observation mode', x: 0.03, font: { size: 14 } },
      showlegend: false, margin: { l: 30, r: 30, t: 56, b: 30 },
      polar: { bgcolor: '#0c1322',
        radialaxis: { range: [0, 90], tickvals: [0, 30, 60, 90], ticktext: ['90°', '60°', '30°', '0°'],
          gridcolor: 'rgba(255,255,255,0.08)', color: '#8d95a8', angle: 90, tickangle: 90 },
        angularaxis: { rotation: 90, direction: 'clockwise', gridcolor: 'rgba(255,255,255,0.08)', color: '#8d95a8',
          tickvals: [0, 90, 180, 270], ticktext: ['N', 'E', 'S', 'W'] } },
    }), LS.plotConfig);

    renderInfo(sol);
  }

  function renderInfo(sol) {
    const rows = [];
    if (sol.station_latlon) {
      rows.push(['Station latitude', `${LS.fmt(sol.station_latlon[0], 3)}°`]);
      rows.push(['Station longitude', `${LS.fmt(sol.station_latlon[1], 3)}°`]);
    }
    const lats = sol.ground.lat.filter((x) => x !== null);
    rows.push(['Max |latitude|', `${LS.fmt(Math.max(...lats.map(Math.abs)), 2)}° (≤ i = ${LS.fmt(sol.elements.i, 2)}°)`]);
    let vis = '';
    if (sol.sky) {
      const spans = sol.sky.visible;
      const maxEl = Math.max(...sol.sky.el);
      rows.push(['Highest elevation', `${LS.fmt(maxEl, 1)}°`]);
      vis = spans.length
        ? '<h3>Visible from the station</h3>' + spans.map(([a, b]) =>
          `<p>${LS.fmtUTC(LS.jdToDate(sol.jd0 + a / 86400)).slice(11, 16)} → ${LS.fmtUTC(LS.jdToDate(sol.jd0 + b / 86400)).slice(11)}</p>`).join('')
        : '<p class="muted">Never above the horizon during this orbit.</p>';
    }
    $('ground-info').innerHTML = LS.kv(rows) + vis;
  }

  /* Current sub-satellite point and sky position, from the shared clock. */
  view.update = function (dt) {
    if (!drawn) return;
    timer -= dt;
    if (timer > 0) return;
    timer = 0.25;
    const sol = drawn, tr = sol.track, n = tr.t.length;
    const f = Math.min(Math.max((view.clock.t - tr.t[0]) / (tr.t[n - 1] - tr.t[0]) * (n - 1), 0), n - 1);
    const k = Math.min(Math.floor(f), n - 2), u = f - k;
    const p = [0, 1, 2].map((i) => tr.r[k][i] + (tr.r[k + 1][i] - tr.r[k][i]) * u);
    const jd = sol.jd0 + view.clock.t / 86400;
    const g = LS.gmst(jd), c = Math.cos(g), s = Math.sin(g);
    const x = c * p[0] + s * p[1], y = -s * p[0] + c * p[1], z = p[2];
    const lat = Math.atan2(z, Math.hypot(x, y)) / LS.DEG, lon = Math.atan2(y, x) / LS.DEG;
    Plotly.restyle('ch-ground', { x: [[lon]], y: [[lat]] }, [2]);

    if (sol.sky && sol.station_latlon) {
      const [la, lo] = sol.station_latlon.map((v) => v * LS.DEG);
      const st = sol.station_ecef;
      const rho = [x - st[0], y - st[1], z - st[2]];
      const S_ = Math.sin(la) * Math.cos(lo) * rho[0] + Math.sin(la) * Math.sin(lo) * rho[1] - Math.cos(la) * rho[2];
      const E_ = -Math.sin(lo) * rho[0] + Math.cos(lo) * rho[1];
      const Z_ = Math.cos(la) * Math.cos(lo) * rho[0] + Math.cos(la) * Math.sin(lo) * rho[1] + Math.sin(la) * rho[2];
      const el = Math.asin(Z_ / Math.hypot(S_, E_, Z_)) / LS.DEG;
      const az = ((Math.atan2(E_, -S_) / LS.DEG) + 360) % 360;
      const idx = document.getElementById('ch-sky').data.length - 1;
      Plotly.restyle('ch-sky', { theta: [[el >= 0 ? az : null]], r: [[el >= 0 ? 90 - el : null]] }, [idx]);
    }
  };

  view.clockLabel = (t) => LS.views.orbit.clockLabel(t);
  view.nowLabel = 'Back to obs 1';
  view.onNow = () => LS.views.orbit.onNow();
})();
