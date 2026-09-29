/* Mission design: an interplanetary transfer from the same Lambert solver
   (mu = mu_Sun), and the porkchop plot that finds the launch window. */
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

  let pork = null;

  view.init = async function () {
    await LS.loadPlanets();
    const opts = LS.planetTable.order.map((p) => `<option>${p}</option>`).join('');
    $('m-dep').innerHTML = opts; $('m-arr').innerHTML = opts;
    $('m-dep').value = 'Earth'; $('m-arr').value = 'Mars';
    $('btn-transfer').addEventListener('click', computeTransfer);
    $('btn-pork').addEventListener('click', computePorkchop);
    await computeTransfer();
    await computePorkchop();
  };

  view.show = function () { const el = $('ch-pork'); if (el.data) Plotly.Plots.resize(el); };

  function err(msg) {
    $('mission-err').textContent = msg || '';
    $('mission-err').hidden = !msg;
  }

  async function computeTransfer() {
    err();
    try {
      const t = await LS.busy('Solving the interplanetary Lambert problem…', $('btn-transfer'), () => LS.api('/api/transfer', {
        dep: $('m-dep').value, arr: $('m-arr').value, dep_date: $('m-dd').value, arr_date: $('m-ad').value,
      }));
      LS.transfer = t;
      LS.emit('transfer', t);
      renderHud(t);
      markSelection();
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
      pork = await LS.busy(`Solving ${count.toLocaleString()} Lambert problems…`, $('btn-pork'),
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
      contours: { coloring: 'heatmap', showlines: true, showlabels: true, labelfont: { size: 10, color: '#e7edf8' } },
      line: { color: 'rgba(7,11,22,0.45)', width: 0.6 },
      colorbar: { title: { text: 'C₃  km²/s²', side: 'right' }, thickness: 14, outlinewidth: 0, tickfont: { color: '#8b9bbd' } },
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
      marker: { symbol: 'circle-open', size: 16, color: '#ff6b6b', line: { width: 3 } } });

    Plotly.react('ch-pork', traces, LS.plotLayout({
      title: { text: `${p.req.dep} → ${p.req.arr}  ·  ${p.count.toLocaleString()} Lambert solutions`, x: 0.02, font: { size: 14 } },
      xaxis: { title: 'Departure date', gridcolor: 'rgba(148,170,210,0.1)', color: '#8b9bbd' },
      yaxis: { title: 'Arrival date', gridcolor: 'rgba(148,170,210,0.1)', color: '#8b9bbd' },
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
      computeTransfer();
    });
  }

  function markSelection() {
    const el = $('ch-pork');
    if (!el.data) return;
    Plotly.restyle(el, { x: [[$('m-dd').value]], y: [[$('m-ad').value]] }, [el.data.length - 1]);
  }

  function renderHud(t) {
    const f = LS.fmt;
    $('hud-mission').innerHTML = `
      <div class="box"><h4>Transfer <span class="badge">${t.type}</span></h4>
        <div class="big">${t.departure} → ${t.arrival}</div>
        ${LS.kv([['Depart', t.dep_iso.slice(0, 10)], ['Arrive', t.arr_iso.slice(0, 10)],
                 ['Flight time', `${f(t.tof_days, 0)} days`], ['Transfer angle', `${f(t.transfer_angle_deg, 1)}°`]])}
      </div>
      <div class="box"><h4>Energy &amp; Δv</h4>
        ${LS.kv([['Launch energy C₃', `${f(t.c3, 2)} km²/s²`], ['Departure v∞', `${f(t.vinf_departure, 3)} km/s`],
                 ['Arrival v∞', `${f(t.vinf_arrival, 3)} km/s`], ['Δv injection', `${f(t.dv_departure, 3)} km/s`],
                 ['Δv capture', `${f(t.dv_arrival, 3)} km/s`], ['Total Δv', `${f(t.dv_departure + t.dv_arrival, 3)} km/s`]])}
        <p class="hint" style="margin-top:6px">Injection from a 200 km parking orbit; capture into a 400 km circular orbit.
          Planet positions: ${t.ephemeris}.</p>
      </div>
      <div class="box"><h4>Transfer orbit</h4>
        ${LS.kv([['Semi-major axis', `${f(t.a_au, 4)} AU`], ['Eccentricity', f(t.e, 4)]])}
        <button class="primary wide" id="m-3d" style="margin-top:10px">View in 3D</button>
      </div>`;
    $('m-3d').onclick = () => LS.setView('solar');
  }
})();
