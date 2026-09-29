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

    document.querySelectorAll('#pt-source button').forEach((b) => b.addEventListener('click', () => {
      document.querySelectorAll('#pt-source button').forEach((x) => x.classList.toggle('on', x === b));
      source = b.dataset.s;
      $('pt-elements').hidden = source === 'solution';
      $('pt-preset').parentElement.hidden = source === 'solution';
    }));
    $('pt-drag').addEventListener('change', () => { $('pt-dragbox').hidden = !$('pt-drag').checked; });
    $('btn-pt').addEventListener('click', run);
    document.querySelector('[data-for="perturb"]').addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });

    presets = (await LS.api('/api/perturb_presets')).presets;
    $('pt-preset').innerHTML = presets.map((p, k) => `<option value="${k}">${LS.esc(p.label)}</option>`).join('');
    $('pt-preset').addEventListener('change', () => { applyPreset(presets[+$('pt-preset').value]); run(); });
    applyPreset(presets[0]);
    run();
  };

  function applyPreset(p) {
    $('pt-altp').value = p.alt_p; $('pt-alta').value = p.alt_a; $('pt-i').value = p.i;
    $('pt-raan').value = p.raan || 0; $('pt-argp').value = p.argp || 0; $('pt-days').value = p.days;
    $('pt-drag').checked = !!p.drag; $('pt-dragbox').hidden = !p.drag;
    if (p.drag) { $('pt-cd').value = p.cd; $('pt-area').value = p.area; $('pt-mass').value = p.mass; }
    $('pt-j2').checked = true;
  }

  async function run() {
    $('pt-err').hidden = true;
    const v = (id) => $(id).value;
    const req = { source, days: v('pt-days'), j2: $('pt-j2').checked, drag: $('pt-drag').checked,
      cd: v('pt-cd'), area: v('pt-area'), mass: v('pt-mass'),
      alt_p: v('pt-altp'), alt_a: v('pt-alta'), i: v('pt-i'), raan: v('pt-raan'), argp: v('pt-argp') };
    if (source === 'solution') {
      if (!LS.solution) { showErr('Solve an orbit in the Orbit tab first.'); return; }
      req.r = LS.solution.r1; req.v = LS.solution.v1;
    }
    try {
      res = await LS.busy('Integrating the equations of motion…', $('btn-pt'), () => LS.api('/api/perturb', req));
      startJd = LS.nowJd();
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
    const c0 = new THREE.Color(0x5ac8fa), c1 = new THREE.Color(0xffb454), c = new THREE.Color();
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

    craft = LS.glowSprite(0xffffff, Math.max(rmax * 0.06, 0.12));
    craft.add(LS.dot(0.02, 0xffffff));
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
    const rates = [['RAAN drift', `${f(s.raan_rate, 4)} °/day`], ['J2 formula', `${f(s.raan_rate_analytic, 4)} °/day`]];
    if (s.argp_rate !== null) {
      rates.push(['Perigee drift', `${f(s.argp_rate, 4)} °/day`], ['J2 formula', `${f(s.argp_rate_analytic, 4)} °/day`]);
    }
    const reentry = s.reentered
      ? `<div class="box"><h4>Re-entry <span class="badge warn">decayed</span></h4><p>The orbit decayed below 100 km after <b>${f(s.days_run, 1)} days</b>.</p></div>` : '';
    $('hud-perturb').innerHTML = `
      ${reentry}
      <div class="box"><h4>Result</h4>${LS.kv(rows)}</div>
      <div class="box"><h4>Measured vs theory</h4>${LS.kv(rates)}
        <p class="hint" style="margin-top:6px">${s.steps.toLocaleString()} integration steps in ${f(s.compute_s, 2)} s</p></div>`;
  }

  function charts() {
    const d = res.days;
    const base = LS.plotLayout({ margin: { l: 58, r: 54, t: 38, b: 40 }, legend: { orientation: 'h', y: 1.14, x: 0, bgcolor: 'rgba(0,0,0,0)' } });
    // J2 makes the osculating altitudes wobble every orbit; a one-orbit
    // moving average shows the underlying trend (e.g. decay from drag).
    const perRev = Math.max(1, Math.round(d.length / Math.max(res.summary.revolutions, 1)));
    const smooth = (y) => y.map((_, k) => {
      const a = Math.max(0, k - (perRev >> 1)), b = Math.min(y.length, a + perRev);
      let s = 0; for (let j = a; j < b; j++) s += y[j];
      return s / (b - a);
    });
    Plotly.react('ch-pt-alt', [
      { x: d, y: res.alt_a, name: 'Apogee', type: 'scattergl', mode: 'lines', line: { color: 'rgba(255,180,84,0.25)', width: 1 }, showlegend: false, hoverinfo: 'skip' },
      { x: d, y: res.alt_p, name: 'Perigee', type: 'scattergl', mode: 'lines', line: { color: 'rgba(90,200,250,0.25)', width: 1 }, showlegend: false, hoverinfo: 'skip' },
      { x: d, y: smooth(res.alt_a), name: 'Apogee (orbit average)', type: 'scattergl', mode: 'lines', line: { color: '#ffb454', width: 2.5 } },
      { x: d, y: smooth(res.alt_p), name: 'Perigee (orbit average)', type: 'scattergl', mode: 'lines', line: { color: '#5ac8fa', width: 2.5 } },
    ], Object.assign({}, base, {
      title: { text: 'Altitude (km)', x: 0.02, y: 0.97, font: { size: 13 } },
      xaxis: Object.assign({}, base.xaxis, { title: 'days' }),
    }), LS.plotConfig);

    const s = res.summary;
    const an = d.map((t) => res.raan[0] + s.raan_rate_analytic * t);
    const tr = [
      { x: d, y: res.raan, name: 'RAAN (integrated)', type: 'scattergl', mode: 'lines', line: { color: '#5ac8fa', width: 2 } },
      { x: d, y: an, name: 'RAAN (J2 formula)', type: 'scattergl', mode: 'lines', line: { color: '#ffffff', width: 1, dash: 'dash' } },
    ];
    if (s.argp_rate !== null) {
      tr.push({ x: d, y: res.argp, name: 'Arg. of perigee', type: 'scattergl', mode: 'lines', yaxis: 'y2', line: { color: '#c792ea', width: 2 } });
    }
    Plotly.react('ch-pt-ang', tr, Object.assign({}, base, {
      title: { text: 'Orbit orientation drift (°)', x: 0.02, y: 0.97, font: { size: 13 } },
      xaxis: Object.assign({}, base.xaxis, { title: 'days' }),
      yaxis2: { overlaying: 'y', side: 'right', color: '#c792ea', gridcolor: 'rgba(0,0,0,0)', showgrid: false },
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
  };

  view.render = () => s3.render();
  view.clockLabel = (t) => `day ${LS.fmt(t, 2)}`;
  view.nowLabel = 'Start';
  view.onNow = () => { view.clock.t = 0; };
})();
