/* Realistic orbit prediction: the orbit integrated with J2 and drag
   (perturb.py), drawn over time next to the ideal Kepler orbit, with the
   drift of the orbital elements charted below. */
'use strict';

(function () {
  const S = 1 / LS.R_EARTH;
  const $ = (id) => document.getElementById(id);

  const view = {
    id: 'perturb',
    title: 'Realistic orbit prediction',
    subtitle: 'Path colour runs from blue (start) to orange (end) · dashed white: the ideal Kepler orbit',
    clock: new LS.Clock({ t: 0, min: 0, max: 1, rate: 0.25, loop: true,
      rates: [[1 / 96, '15 min/s'], [1 / 24, '1 h/s'], [0.25, '6 h/s'], [1, '1 day/s'], [5, '5 days/s']] }),
  };
  LS.views.perturb = view;

  let s3, earth, sun, group, craft, res = null, presets = [], source = 'elements', startJd = LS.nowJd();

  view.init = async function () {
    s3 = new LS.Scene3D($('cv-perturb'), { near: 0.001, far: 5e4 });
    earth = LS.earth();
    s3.scene.add(earth.group);
    s3.scene.add(new THREE.AmbientLight(0x6070a0, 0.35));
    sun = new THREE.DirectionalLight(0xffffff, 1.25);
    s3.scene.add(sun);
    s3.camera.position.set(3.5, 2.5, 5);
    s3.controls.minDistance = 1.2;
    s3.controls.maxDistance = 400;
    s3.setFollowables([
      { label: 'Satellite', obj: () => craft || null },
      { label: 'Earth', obj: () => earth.surface },
    ]);

    document.querySelectorAll('#pt-source button').forEach((b) => b.addEventListener('click', () => {
      document.querySelectorAll('#pt-source button').forEach((x) => x.classList.toggle('on', x === b));
      source = b.dataset.s;
      $('pt-elements').hidden = source === 'solution';
      $('pt-preset').parentElement.hidden = source === 'solution';
    }));
    $('pt-atm').addEventListener('change', syncForces);
    $('pt-date').value = LS.fmtDate(new Date());
    $('btn-pt').addEventListener('click', run);
    document.querySelector('[data-for="perturb"]').addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });

    presets = (await LS.api('/api/perturb_presets')).presets;
    $('pt-preset').innerHTML = presets.map((p, k) => `<option value="${k}">${LS.esc(p.label)}</option>`).join('');
    $('pt-preset').addEventListener('change', () => { applyPreset(presets[+$('pt-preset').value]); run(); });
    applyPreset(presets[0]);
    run();
  };

  let presetLon = null;

  function syncForces() { $('pt-act-l').hidden = $('pt-atm').value !== 'msis'; }

  function applyPreset(p) {
    $('pt-altp').value = p.alt_p; $('pt-alta').value = p.alt_a; $('pt-i').value = p.i;
    $('pt-raan').value = p.raan || 0; $('pt-argp').value = p.argp || 0; $('pt-days').value = p.days;
    if (p.cd) { $('pt-cd').value = p.cd; $('pt-area').value = p.area; $('pt-mass').value = p.mass; }
    $('pt-cr').value = p.cr || 1.3;
    const m = p.model || { zonal_degree: 2, drag: p.drag ? 'exponential' : '' };
    $('pt-grav').value = m.tesseral ? '6t' : String(m.zonal_degree);
    $('pt-moon').checked = !!m.moon; $('pt-sun').checked = !!m.sun; $('pt-srp').checked = !!m.srp;
    $('pt-atm').value = m.drag || '';
    if (m.activity) $('pt-act').value = m.activity;
    presetLon = p.lon === undefined ? null : p.lon;
    syncForces();
  }

  /* The forces chosen in the panel. Plain J2 (+ simple drag) keeps the
     original, faster path; anything more uses the full model. */
  function forceModel() {
    const g = $('pt-grav').value;
    const m = { zonal_degree: g === '6t' ? 6 : +g, tesseral: g === '6t', moon: $('pt-moon').checked,
      sun: $('pt-sun').checked, srp: $('pt-srp').checked, drag: $('pt-atm').value || null, activity: $('pt-act').value };
    const simple = m.zonal_degree === 2 && !m.tesseral && !m.moon && !m.sun && !m.srp && m.drag !== 'msis';
    return simple ? null : m;
  }

  async function run() {
    $('pt-err').hidden = true;
    const v = (id) => $(id).value;
    const model = forceModel();
    const req = { source, days: v('pt-days'), j2: $('pt-grav').value !== '0', drag: $('pt-atm').value !== '',
      cd: v('pt-cd'), cr: v('pt-cr'), area: v('pt-area'), mass: v('pt-mass'), model, date: v('pt-date'),
      alt_p: v('pt-altp'), alt_a: v('pt-alta'), i: v('pt-i'), raan: v('pt-raan'), argp: v('pt-argp') };
    if (source === 'elements' && presetLon !== null) req.lon = presetLon;
    if (source === 'solution') {
      if (!LS.solution) { showErr('Solve an orbit in the Orbit tab first.'); return; }
      req.r = LS.solution.r1; req.v = LS.solution.v1;
      if (LS.solution.mode === 'observations') req.jd0 = LS.solution.jd0;   // the orbit's own date
    }
    try {
      res = await LS.busy(model ? 'Integrating with the full force model…' : 'Integrating the equations of motion…',
        $('btn-pt'), () => LS.api('/api/perturb', req));
      startJd = res.jd0 || LS.nowJd();
      LS.emit('perturb-result', res);
      $('empty-perturb').hidden = true;
      draw();
      charts();
    } catch (e) { showErr(e.message); }
  }

  function showErr(msg) { $('pt-err').textContent = msg; $('pt-err').hidden = false; }

  function draw() {
    if (group) {
      group.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.element) o.element.remove(); });
      s3.scene.remove(group);
    }
    group = new THREE.Group();
    s3.scene.add(group);

    // Perturbed path, coloured by time.
    const n = res.r.length;
    const pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
    const c0 = new THREE.Color(0x5eb3e6), c1 = new THREE.Color(0xeea55a), c = new THREE.Color();
    let rmax = 0;
    for (let k = 0; k < n; k++) {
      LS.setXYZ(pos, k, res.r[k], S);
      c.copy(c0).lerp(c1, k / (n - 1));
      col.set([c.r, c.g, c.b], 3 * k);
      rmax = Math.max(rmax, Math.hypot(...res.r[k]) * S);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    group.add(new THREE.Line(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.8 })));

    // The ideal orbit, which never changes.
    const kep = LS.line(res.kepler_r.map((p) => LS.v3(p, S)), 0xffffff, 0.55, true);
    kep.material.dashSize = rmax * 0.02; kep.material.gapSize = rmax * 0.015; kep.computeLineDistances();
    group.add(kep);

    craft = LS.spacecraft(Math.max(rmax * 0.012, 0.03));
    group.add(craft);

    const cl = view.clock;
    cl.min = 0; cl.max = res.summary.days_run; cl.t = 0; cl.playing = true;
    cl.rate = [1 / 96, 1 / 24, 0.25, 1, 5].reduce((best, r) => (Math.abs(r - cl.max / 30) < Math.abs(best - cl.max / 30) ? r : best), 1);
    s3.focusOn(new THREE.Vector3(), Math.max(rmax * 2.4, 3));
    renderHud();
    LS.syncTimebar();
  }

  function renderHud() {
    const s = res.summary, f = LS.fmt, i0 = s.initial, i1 = s.final;
    const rows = [
      ['Simulated', `${f(s.days_run, 2)} days · ${f(s.revolutions, 0)} orbits`],
      ['Perigee altitude', `${f(i0.alt_p, 1)} → ${f(i1.alt_p, 1)} km`],
      ['Apogee altitude', `${f(i0.alt_a, 1)} → ${f(i1.alt_a, 1)} km`],
      ['Drift from Kepler', `${f(s.max_diff, 0)} km`],
    ];
    // For a (nearly) equatorial orbit the node does not exist, so its drift means nothing.
    const equatorial = i0.i !== undefined ? i0.i < 1 : Math.abs(res.i[0]) < 1;
    const rates = equatorial
      ? [['Node drift', 'undefined (equatorial orbit)']]
      : [['RAAN drift', `${f(s.raan_rate, 4)} °/day`], ['J2 formula', `${f(s.raan_rate_analytic, 4)} °/day`]];
    if (s.argp_rate !== null) {
      rates.push(['Perigee drift', `${f(s.argp_rate, 4)} °/day`], ['J2 formula', `${f(s.argp_rate_analytic, 4)} °/day`]);
    }
    const reentry = s.reentered
      ? `<div class="box"><h4>Re-entry <span class="badge warn">decayed</span></h4><p>The orbit decayed below 100 km after <b>${f(s.days_run, 1)} days</b>.</p></div>` : '';
    const geo = res.lon && i0.alt_p > 30000;
    if (geo) {
      rows.push(['Inclination', `${f(res.i[0], 3)}° → ${f(res.i[res.i.length - 1], 3)}°`],
        ['Longitude', `${f(res.lon[0], 1)}° → ${f(res.lon[res.lon.length - 1], 1)}° E`]);
    }
    const bars = res.breakdown ? breakdownHtml(res.breakdown) : '';
    const notes = (res.notes || []).map((n) => `<p class="hint">⚠ ${LS.esc(n)}</p>`).join('');
    const atm = s.atmosphere === 'msis' ? `NRLMSIS 2.1, ${s.activity} solar activity`
      : s.atmosphere === 'exponential' ? 'simple exponential' : 'none';
    $('hud-perturb').innerHTML = `
      ${reentry}
      <div class="box"><h4>Result</h4>${LS.kv(rows)}
        <p class="hint" style="margin-top:6px">Atmosphere: ${atm}.</p>${notes}</div>
      ${bars}
      <div class="box"><h4>Measured vs theory</h4>${LS.kv(rates)}
        <p class="hint" style="margin-top:6px">${s.steps.toLocaleString('en-US')} integration steps in ${f(s.compute_s, 2)} s</p></div>`;
  }

  /* How strong each force is at the start, relative to Earth's main pull. */
  function breakdownHtml(list) {
    const f = LS.fmt;
    const rows = list.slice(1).filter((b) => b.accel > 0);
    const lmin = -14, lmax = -3;
    const w = (r) => Math.max(2, 100 * (Math.log10(Math.max(r, 1e-14)) - lmin) / (lmax - lmin));
    const words = (r) => (r >= 1e-3 ? `${f(r * 100, 2)}%`
      : 1 / r >= 1e6 ? `1 part in ${f(1 / r / 1e6, 1)} million` : `1 part in ${Math.round(1 / r).toLocaleString('en-US')}`);
    return `<div class="box"><h4>Which force matters here?</h4>
      <div class="fb">${rows.map((b) => `<div><span>${b.force}</span><i style="width:${w(b.ratio).toFixed(0)}%"></i>
        <b>${words(b.ratio)}</b></div>`).join('')}</div>
      <p class="hint" style="margin-top:6px">Size of each force at the start, compared with Earth's main pull
        (log scale). Small forces still add up over thousands of orbits.</p></div>`;
  }

  function charts() {
    const d = res.days;
    const base = LS.plotLayout({ margin: { l: 58, r: 54, t: 64, b: 40 } });
    // J2 makes the osculating altitudes wobble every orbit; a one-orbit
    // moving average shows the underlying trend (e.g. decay from drag).
    const perRev = Math.max(1, Math.round(d.length / Math.max(res.summary.revolutions, 1)));
    const smooth = (y) => y.map((_, k) => {
      const a = Math.max(0, k - (perRev >> 1)), b = Math.min(y.length, a + perRev);
      let s = 0; for (let j = a; j < b; j++) s += y[j];
      return s / (b - a);
    });
    Plotly.react('ch-pt-alt', [
      { x: d, y: res.alt_a, name: 'Apogee', type: 'scattergl', mode: 'lines', line: { color: 'rgba(238,165,90,0.25)', width: 1 }, showlegend: false, hoverinfo: 'skip' },
      { x: d, y: res.alt_p, name: 'Perigee', type: 'scattergl', mode: 'lines', line: { color: 'rgba(94,179,230,0.25)', width: 1 }, showlegend: false, hoverinfo: 'skip' },
      { x: d, y: smooth(res.alt_a), name: 'Apogee (orbit average)', type: 'scattergl', mode: 'lines', line: { color: '#eea55a', width: 2.5 } },
      { x: d, y: smooth(res.alt_p), name: 'Perigee (orbit average)', type: 'scattergl', mode: 'lines', line: { color: '#5eb3e6', width: 2.5 } },
    ], Object.assign({}, base, {
      title: { text: 'Altitude (km)', x: 0.02, y: 0.97, font: { size: 13 } },
      xaxis: Object.assign({}, base.xaxis, { title: 'days' }),
    }), LS.plotConfig);

    const s = res.summary;
    if (res.lon && s.initial.alt_p > 30000) {
      // Geostationary: where over the equator it drifts, and how its orbit tilts.
      Plotly.react('ch-pt-ang', [
        { x: d, y: res.lon, name: 'Longitude (° E)', type: 'scattergl', mode: 'lines', line: { color: '#5eb3e6', width: 2 } },
        { x: d, y: res.i, name: 'Inclination (°)', type: 'scattergl', mode: 'lines', yaxis: 'y2', line: { color: '#e3cc6a', width: 2 } },
      ], Object.assign({}, base, {
        title: { text: 'Drift over the equator, and tilt', x: 0.02, y: 0.97, font: { size: 13 } },
        xaxis: Object.assign({}, base.xaxis, { title: 'days' }),
        shapes: [{ type: 'line', xref: 'paper', x0: 0, x1: 1, y0: 75.07, y1: 75.07,
          line: { color: 'rgba(127,207,159,0.6)', dash: 'dot', width: 1 } }],
        annotations: [{ xref: 'paper', x: 1, y: 75.07, text: 'stable point 75° E', showarrow: false, xanchor: 'right',
          yanchor: 'bottom', font: { size: 10, color: '#7fcf9f' } }],
        yaxis2: { overlaying: 'y', side: 'right', color: '#e3cc6a', gridcolor: 'rgba(0,0,0,0)', showgrid: false },
      }), LS.plotConfig);
      return;
    }
    const an = d.map((t) => res.raan[0] + s.raan_rate_analytic * t);
    const tr = [
      { x: d, y: res.raan, name: 'RAAN (integrated)', type: 'scattergl', mode: 'lines', line: { color: '#5eb3e6', width: 2 } },
      { x: d, y: an, name: 'RAAN (J2 formula)', type: 'scattergl', mode: 'lines', line: { color: '#ffffff', width: 1, dash: 'dash' } },
    ];
    if (s.argp_rate !== null) {
      tr.push({ x: d, y: res.argp, name: 'Arg. of perigee', type: 'scattergl', mode: 'lines', yaxis: 'y2', line: { color: '#e3cc6a', width: 2 } });
    }
    Plotly.react('ch-pt-ang', tr, Object.assign({}, base, {
      title: { text: 'Orbit orientation drift (°)', x: 0.02, y: 0.97, font: { size: 13 } },
      xaxis: Object.assign({}, base.xaxis, { title: 'days' }),
      yaxis2: { overlaying: 'y', side: 'right', color: '#e3cc6a', gridcolor: 'rgba(0,0,0,0)', showgrid: false },
    }), LS.plotConfig);
  }

  view.show = function () {
    ['ch-pt-alt', 'ch-pt-ang'].forEach((id) => { const el = $(id); if (el.data) Plotly.Plots.resize(el); });
  };

  view.update = function (dt) {
    const jd = startJd + view.clock.t;
    earth.spin.rotation.y = LS.gmst(jd);
    earth.clouds.rotation.y += dt * 0.004;
    sun.position.copy(LS.v3(LS.sunDirection(jd), 50));
    earth.setSun(sun.position);
    if (!res || !craft) return;
    const n = res.r.length, T = res.summary.days_run;
    const f = Math.min(Math.max(view.clock.t / T, 0), 1) * (n - 1);
    const k = Math.min(Math.floor(f), n - 2), u = f - k;
    const a = res.r[k], b = res.r[k + 1];
    craft.position.copy(LS.v3([a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u], S));
    LS.aimCraft(craft, LS.v3(res.r[Math.min(k + 2, n - 1)], S));
  };

  view.render = () => s3.render();
  view.clockLabel = (t) => `day ${LS.fmt(t, 2)}`;
  view.nowLabel = 'Back to start';
  view.onNow = () => { view.clock.t = 0; };
})();
