/* Mission design. Two modes:
     Direct transfer  - one Lambert arc between two planets, the porkchop
                        plot to pick dates, and a plain-language
                        explanation of the route.
     Gravity assist   - multi-planet routes (view_route.js). */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const view = {
    id: 'mission',
    title: 'Mission design',
    subtitle: 'Porkchop plot: departure energy C₃ for every pair of dates · click the plot to pick dates',
    clock: null,
  };
  LS.views.mission = view;

  let pork = null, mode = 'direct', directStarted = false;

  view.init = async function () {
    await LS.loadPlanets();
    const opts = LS.planetTable.order.map((p) => `<option>${p}</option>`).join('');
    $('m-dep').innerHTML = opts; $('m-arr').innerHTML = opts;
    $('m-dep').value = 'Earth'; $('m-arr').value = 'Mars';
    $('btn-transfer').addEventListener('click', () => computeTransfer(true));
    $('btn-pork').addEventListener('click', computePorkchop);
    document.querySelectorAll('#m-mode button').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.m)));
    await LS.route.init();
    setMode('direct');
  };

  async function setMode(m) {
    mode = m;
    document.querySelectorAll('#m-mode button').forEach((x) => x.classList.toggle('on', x.dataset.m === m));
    $('m-direct').hidden = m !== 'direct';
    $('m-route').hidden = m !== 'route';
    $('direct-area').hidden = m !== 'direct';
    $('route-area').hidden = m !== 'route';
    view.subtitle = m === 'direct'
      ? 'Porkchop plot: departure energy C₃ for every pair of dates · click the plot to pick dates'
      : 'Gravity assists: using the planets\' own motion to change the spacecraft\'s speed';
    $('view-sub').textContent = view.subtitle;
    view.clock = m === 'route' ? LS.route.clock : null;
    LS.syncTimebar();
    if (m === 'direct' && !directStarted) {
      directStarted = true;
      await computeTransfer();
      await computePorkchop();
    }
    if (m === 'route') LS.route.show();
    view.show();
  }

  /* Used by the "Suggest dates" helper after it fills in the dates. */
  view.refresh = async function () { await computeTransfer(); await computePorkchop(); };

  view.show = function () {
    const el = $('ch-pork'); if (el.data && mode === 'direct') Plotly.Plots.resize(el);
    if (mode === 'route') LS.route.resize();
  };
  view.update = (dt) => { if (mode === 'route') LS.route.update(dt); };
  view.render = () => { if (mode === 'route') LS.route.render(); };
  view.clockLabel = (t) => LS.route.clockLabel(t);
  view.nowLabel = 'Back to launch';
  view.onNow = () => LS.route.onNow();

  function err(msg) {
    $('mission-err').textContent = msg || '';
    $('mission-err').hidden = !msg;
  }

  /* play=true opens the full-screen playback once computed (when the user
     asked for this transfer, not on the automatic first calculation). */
  async function computeTransfer(play = false) {
    err();
    try {
      const t = await LS.busy('Solving the interplanetary Lambert problem…', $('btn-transfer'), () => LS.api('/api/transfer', {
        dep: $('m-dep').value, arr: $('m-arr').value, dep_date: $('m-dd').value, arr_date: $('m-ad').value,
      }));
      LS.transfer = t;
      LS.emit('transfer', t);
      renderHud(t);
      LS.emit('transfer', t);
      markSelection();
      if (play === true) LS.player.open(LS.player.fromTransfer(t));
    } catch (e) { err(e.message); }
  }

  async function computePorkchop() {
    err();
    const req = {
      dep: $('m-dep').value, arr: $('m-arr').value,
      dep_start: $('p-d0').value, dep_end: $('p-d1').value,
      arr_start: $('p-a0').value, arr_end: $('p-a1').value, n: +$('p-n').value,
    };
    const count = req.n * req.n;
    try {
      pork = await LS.busy(`Solving ${count.toLocaleString('en-US')} Lambert problems…`, $('btn-pork'),
        () => LS.api('/api/porkchop', req));
      pork.req = req;
      drawPorkchop();
    } catch (e) { err(e.message); }
  }

  function drawPorkchop() {
    $('empty-mission').hidden = true;
    const p = pork;
    const finite = p.Z.flat().filter((v) => v !== null).sort((a, b) => a - b);
    const zmin = finite[0];
    const zmax = Math.min(finite[Math.floor(finite.length * 0.55)] || zmin + 50, zmin + 80);
    const Zc = p.Z.map((row) => row.map((v) => (v === null ? null : Math.min(v, zmax))));
    const dep = p.dep.map((d) => d.slice(0, 10)), arr = p.arr.map((d) => d.slice(0, 10));
    const tof = arr.map((a) => dep.map((d) => (new Date(a) - new Date(d)) / 86400000));

    const traces = [{
      type: 'contour', x: dep, y: arr, z: Zc, zmin, zmax, ncontours: 22,
      colorscale: [[0, '#0b3a5c'], [0.15, '#1f77b4'], [0.35, '#35b0ab'], [0.6, '#b8d86b'], [0.85, '#f6c85f'], [1, '#2a1f3d']],
      contours: { coloring: 'heatmap', showlines: true, showlabels: true, labelfont: { size: 10, color: '#e9ecf3' } },
      line: { color: 'rgba(7,11,22,0.45)', width: 0.6 },
      colorbar: { title: { text: 'C₃  km²/s²', side: 'right' }, thickness: 14, outlinewidth: 0, tickfont: { color: '#8d95a8' } },
      hovertemplate: 'depart %{x}<br>arrive %{y}<br>C₃ %{z:.1f} km²/s²<extra></extra>',
    }, {
      type: 'contour', x: dep, y: arr, z: tof, showscale: false, hoverinfo: 'skip',
      contours: { coloring: 'none', showlabels: true, start: 100, end: 600, size: 50,
        labelfont: { size: 9, color: 'rgba(255,255,255,0.55)' } },
      line: { color: 'rgba(255,255,255,0.28)', width: 1, dash: 'dot' }, name: 'flight time (days)',
    }];
    if (p.best) {
      traces.push({ type: 'scatter', mode: 'markers+text', x: [p.best.dep_iso.slice(0, 10)], y: [p.best.arr_iso.slice(0, 10)],
        text: [`  best: C₃ ${LS.fmt(p.best.c3, 1)}`], textposition: 'middle right', textfont: { color: '#ffffff' },
        marker: { symbol: 'star', size: 16, color: '#ffffff', line: { color: '#070b16', width: 1 } }, hoverinfo: 'skip' });
    }
    traces.push({ type: 'scatter', mode: 'markers', x: [], y: [], hoverinfo: 'skip',
      marker: { symbol: 'circle-open', size: 16, color: '#e56f6f', line: { width: 3 } } });

    Plotly.react('ch-pork', traces, LS.plotLayout({
      title: { text: `${p.req.dep} → ${p.req.arr}  ·  ${p.count.toLocaleString('en-US')} Lambert solutions`, x: 0.02, font: { size: 14 } },
      xaxis: { title: 'Departure date', gridcolor: 'rgba(255,255,255,0.05)', color: '#8d95a8' },
      yaxis: { title: 'Arrival date', gridcolor: 'rgba(255,255,255,0.05)', color: '#8d95a8' },
      showlegend: false, margin: { l: 70, r: 20, t: 48, b: 56 },
    }), LS.plotConfig);
    markSelection();

    const el = $('ch-pork');
    el.removeAllListeners && el.removeAllListeners('plotly_click');
    el.on('plotly_click', (ev) => {
      const pt = ev.points[0];
      if (!pt) return;
      $('m-dd').value = String(pt.x).slice(0, 10);
      $('m-ad').value = String(pt.y).slice(0, 10);
      computeTransfer(true);
    });
  }

  function markSelection() {
    const el = $('ch-pork');
    if (!el.data) return;
    Plotly.restyle(el, { x: [[$('m-dd').value]], y: [[$('m-ad').value]] }, [el.data.length - 1]);
  }

  /* ---------------- explanation of a direct route ---------------- */

  function renderHud(t) {
    if (!LS.launch.data) LS.launch.load().then(() => renderHud(t)).catch(() => {});
    const f = LS.fmt, x = t.explain;
    const dep = t.departure, arr = t.arrival;
    const typeText = t.type === 'Type I'
      ? `<b>Type I route:</b> the spacecraft covers <b>less than half</b> a lap around the Sun (${f(t.transfer_angle_deg, 0)}°) — the shorter way round.`
      : `<b>Type II route:</b> the spacecraft covers <b>more than half</b> a lap around the Sun (${f(t.transfer_angle_deg, 0)}°) — a longer path that, for these dates, needs less energy.`;
    const lead = (deg) => `${f(Math.abs(deg), 0)}° ${deg >= 0 ? 'ahead of' : 'behind'}`;
    const extra = 100 * (t.c3 / x.hohmann_c3 - 1);
    $('hud-mission').innerHTML = `
      <div class="box"><h4>Route explained <span class="badge">${t.type}</span></h4>
        ${topView(t)}
        <p>${typeText}</p>
        <p><b>Aim ahead.</b> At launch ${arr} is <b>${lead(x.phase_deg)}</b> ${dep}. During the ${f(t.tof_days, 0)}-day trip
          ${arr} moves another ${f(x.target_moves_deg, 0)}° along its orbit, so the spacecraft is aimed at where ${arr}
          <i>will be</i> on arrival, not where it is at launch.</p>
        <p><b>Compared with the ideal.</b> The textbook Hohmann transfer needs ${arr} ${lead(x.hohmann_phase_deg)} ${dep}
          and takes ${f(x.hohmann_days, 0)} days with C₃ ${f(x.hohmann_c3, 1)} km²/s². This route needs C₃ ${f(t.c3, 1)}:
          <b>${f(Math.abs(extra), 0)}% ${extra >= 0 ? 'more' : 'less'} launch energy</b>
          (real planets have tilted, elliptical orbits, so the ideal case is only a guide).</p>
        <p><b>Launch windows.</b> ${dep} and ${arr} return to the same relative position every
          <b>${f(x.synodic_days, 0)} days (${f(x.synodic_days / 365.25, 1)} years)</b> — the synodic period. Miss a window and
          the next one is that far away.</p>
      </div>
      <div class="box"><h4>Transfer</h4>
        ${LS.kv([['Depart', t.dep_iso.slice(0, 10)], ['Arrive', t.arr_iso.slice(0, 10)],
                 ['Flight time', `${f(t.tof_days, 0)} days`], ['Launch energy C₃', `${f(t.c3, 2)} km²/s²`],
                 ['Δv leaving Earth orbit', `${f(t.dv_departure, 3)} km/s`], ['Δv to enter orbit', `${f(t.dv_arrival, 3)} km/s`],
                 ['Arrival speed v∞', `${f(t.vinf_arrival, 3)} km/s`]])}
        <p class="hint" style="margin-top:6px">Leaving from a 200 km parking orbit. Captured into a 400 km circular orbit (rocky planets) or a long ellipse like Juno and Cassini (gas giants).
          Planet positions: ${t.ephemeris}.</p>
        <button class="play-mission" id="m-play">▶ Play mission</button>
        <button class="ghost wide" id="m-3d" style="margin-top:8px">Show in the Solar tab</button>
      </div>
      ${LS.launch.data && dep === 'Earth' ? `<div class="box"><h4>Which rocket? <small>for 2,000 kg</small></h4>
        ${LS.launch.table(t.c3, 2000)}</div>` : ''}
      <div class="box"><button class="ghost wide" id="m-nbody">Check in full solar-system gravity</button>
        <div id="m-nbody-box"></div></div>`;
    $('m-nbody').onclick = async () => {
      try {
        const v = await LS.nbody.run({ seq: [t.departure, t.arrival], jds: [t.jd_departure, t.jd_arrival], capture: true },
          $('m-nbody'));
        $('m-nbody-box').innerHTML = LS.nbody.html(v).replace('<div class="box nbody">', '<div class="nbody" style="margin-top:8px">');
        LS.emit('nbody', v);
      } catch (e) {
        $('m-nbody-box').innerHTML = `<p class="hint">⚠ ${LS.esc(e.message)}</p>`;
      }
    };
    $('m-play').onclick = () => LS.player.open(LS.player.fromTransfer(t));
    $('m-3d').onclick = () => LS.setView('solar');
  }

  /* Small top-down diagram: orbits, the transfer arc, and where both
     planets are at launch and at arrival. */
  function topView(t) {
    const d = t.departure, a = t.arrival;
    const cd = LS.planetTable.elements[d].color, ca = LS.planetTable.elements[a].color;
    const dLaunch = LS.planetPos(d, t.jd_departure, [0, 0, 0]);
    const aLaunch = LS.planetPos(a, t.jd_departure, [0, 0, 0]);
    const aArrive = LS.planetPos(a, t.jd_arrival, [0, 0, 0]);
    return LS.topViewSvg({
      paths: [
        { pts: LS.planetOrbit(d, t.jd_departure, 180), color: cd, width: 1, opacity: 0.45 },
        { pts: LS.planetOrbit(a, t.jd_departure, 180), color: ca, width: 1, opacity: 0.45 },
        { pts: t.track_au, color: '#5eb3e6', width: 2.4 },
        { pts: [[0, 0], aLaunch], color: ca, width: 1, dash: '3 3', opacity: 0.7 },
        { pts: [[0, 0], dLaunch], color: cd, width: 1, dash: '3 3', opacity: 0.7 },
      ],
      bodies: [
        { p: dLaunch, color: cd, r: 4.5, label: `${d} at launch` },
        { p: aLaunch, color: ca, r: 4, hollow: true, label: `${a} at launch` },
        { p: aArrive, color: ca, r: 4.5, label: `${a} at arrival` },
      ],
    });
  }
})();

/* Top-down (ecliptic) SVG diagram, shared by the mission views.
   paths: [{pts:[[x,y,..]], color, width, dash, opacity}]
   bodies: [{p:[x,y], color, r, label, hollow}] — coordinates in AU. */
LS.topViewSvg = function ({ paths = [], bodies = [], size = 300 }) {
  const all = [[0, 0], ...paths.flatMap((p) => p.pts), ...bodies.map((b) => b.p)];
  const R = Math.max(...all.map((p) => Math.hypot(p[0], p[1]))) * 1.08 || 1;
  const s = (size / 2 - 6) / R, c = size / 2;
  const X = (p) => (c + p[0] * s).toFixed(1), Y = (p) => (c - p[1] * s).toFixed(1);
  const lines = paths.map((p) => `<polyline fill="none" stroke="${p.color}" stroke-width="${p.width || 1}"
      stroke-opacity="${p.opacity === undefined ? 1 : p.opacity}" ${p.dash ? `stroke-dasharray="${p.dash}"` : ''}
      stroke-linecap="round" points="${p.pts.map((q) => `${X(q)},${Y(q)}`).join(' ')}"/>`).join('');
  const dots = bodies.map((b) => {
    const x = +X(b.p), y = +Y(b.p), right = x < c;
    return `<circle cx="${x}" cy="${y}" r="${b.r || 4}" ${b.hollow ? `fill="none" stroke="${b.color}" stroke-width="1.6"` : `fill="${b.color}"`}/>
      ${b.label ? `<text x="${x + (right ? 8 : -8)}" y="${y + 4}" fill="#c9d4ea" font-size="10.5"
        text-anchor="${right ? 'start' : 'end'}" font-family="Segoe UI, sans-serif">${LS.esc(b.label)}</text>` : ''}`;
  }).join('');
  return `<svg class="topview" viewBox="0 0 ${size} ${size}" role="img" aria-label="Top view of the route">
    <defs><radialGradient id="sunG"><stop offset="0" stop-color="#fff3c4"/><stop offset="0.5" stop-color="#eea55a"/>
      <stop offset="1" stop-color="#eea55a" stop-opacity="0"/></radialGradient></defs>
    ${lines}<circle cx="${c}" cy="${c}" r="9" fill="url(#sunG)"/><circle cx="${c}" cy="${c}" r="3.5" fill="#fff1c1"/>${dots}</svg>`;
};
