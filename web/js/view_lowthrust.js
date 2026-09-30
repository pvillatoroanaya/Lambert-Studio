/* Ion engines: low-thrust spirals (lowthrust.py), compared with a
   chemical Hohmann transfer. Scene unit: 1 AU around the Sun, 1 Earth
   radius around Earth. */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const f = (x, d) => LS.fmt(x, d);
  const DAY = 86400;

  const view = {
    id: 'lowthrust',
    title: 'Ion engines',
    subtitle: 'Seen from above · the spiral colour goes from blue (start) to green (arrival)',
    clock: new LS.Clock({ t: 0, min: 0, max: 1, rate: 5, loop: true, rates: [[5, '5 days/s']] }),
  };
  LS.views.lowthrust = view;

  let s3, group = null, craft = null, plume = null, res = null, presets = [], body = 'Sun', unit = 1;
  let phaseTimer = 0;

  view.init = async function () {
    presets = (await LS.api('/api/lowthrust_presets')).presets;
    $('lt-presets').innerHTML = presets.map((p, k) => `<button class="preset" data-k="${k}"><b>${LS.esc(p.label)}</b>
      <span>${f(p.thrust_mN, 0)} mN · Isp ${f(p.isp, 0)} s · ${f(p.mass, 0)} kg</span></button>`).join('');
    $('lt-presets').querySelectorAll('.preset').forEach((b) => b.addEventListener('click', () => {
      mark(+b.dataset.k);
      fill(presets[+b.dataset.k]);
      run({ preset: presets[+b.dataset.k].key });
    }));
    document.querySelectorAll('#lt-body button').forEach((b) => b.addEventListener('click', () => setBody(b.dataset.b)));
    $('btn-lt').addEventListener('click', () => { mark(-1); run(request()); });
    s3 = new LS.Scene3D($('cv-lowthrust'), { near: 1e-4, far: 1e5 });
    s3.scene.add(new THREE.AmbientLight(0x3a4466, 0.4));
    const light = new THREE.PointLight(0xfff2dd, 1.4, 0, 0);
    s3.scene.add(light);
    s3.setFollowables([{ label: 'Spacecraft', obj: () => craft }]);
    fill(presets[0]);
    mark(0);
    await run({ preset: presets[0].key });
  };

  function mark(k) { $('lt-presets').querySelectorAll('.preset').forEach((x, i) => x.classList.toggle('on', i === k)); }

  function setBody(b) {
    document.querySelectorAll('#lt-body button').forEach((x) => x.classList.toggle('on', x.dataset.b === b));
    $('lt-r1-l').firstChild.textContent = b === 'Sun' ? 'Start orbit (AU)' : 'Start altitude (km)';
    $('lt-r2-l').firstChild.textContent = b === 'Sun' ? 'Target orbit (AU)' : 'Target altitude (km)';
  }

  function fill(p) {
    setBody(p.body);
    const R = 6378.137;
    $('lt-r1').value = p.unit === 'AU' ? p.r1 : Math.round(p.r1 - R);
    $('lt-r2').value = p.unit === 'AU' ? p.r2 : Math.round(p.r2 - R);
    $('lt-mass').value = p.mass; $('lt-thrust').value = p.thrust_mN; $('lt-isp').value = p.isp;
  }

  function request() {
    return { body: document.querySelector('#lt-body .on').dataset.b, r1: $('lt-r1').value, r2: $('lt-r2').value,
      mass: $('lt-mass').value, thrust_mN: $('lt-thrust').value, isp: $('lt-isp').value };
  }

  async function run(req) {
    $('lt-err').hidden = true;
    try {
      res = await LS.busy('Flying the spiral…', $('btn-lt'), () => LS.api('/api/lowthrust', req));
      res.presetInfo = req.preset ? presets.find((p) => p.key === req.preset) : null;
      $('empty-lowthrust').hidden = true;
      draw();
      chart();
      story();
      LS.emit('lowthrust-result', res);
    } catch (e) {
      $('lt-err').textContent = e.message;
      $('lt-err').hidden = false;
    }
  }

  /* ---------------- 3D ---------------- */

  function draw() {
    if (group) {
      group.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.element) o.element.remove(); });
      s3.scene.remove(group);
    }
    group = new THREE.Group();
    s3.scene.add(group);
    body = res.body;
    unit = body === 'Sun' ? 1 : 6378.137;          // xy comes in AU (Sun) or km (Earth)
    const P = (p) => new THREE.Vector3(p[0] / unit, 0, -p[1] / unit);
    if (body === 'Sun') {
      const sun = LS.sun(0.05); sun.add(LS.glowSprite(0xffa040, 0.5)); group.add(sun);
    } else {
      const e = LS.earth(); e.setSun(new THREE.Vector3(1, 0.3, 0.5)); group.add(e.group);
      const l = new THREE.DirectionalLight(0xffffff, 1.1); l.position.set(20, 6, 10); group.add(l);
    }
    const r1 = res.r1 / (body === 'Sun' ? res.scale : unit), r2 = res.r2 / (body === 'Sun' ? res.scale : unit);
    const circle = (r, color, text) => {
      const pts = [];
      for (let k = 0; k <= 256; k++) pts.push(new THREE.Vector3(r * Math.cos(k / 128 * Math.PI), 0, -r * Math.sin(k / 128 * Math.PI)));
      group.add(LS.line(pts, color, 0.55, true));
      const lb = LS.label(text, 'dim'); lb.position.set(0, 0, -r); group.add(lb);
    };
    circle(r1, 0x5ac8fa, 'start orbit');
    circle(r2, 0x6ee7a8, 'target orbit');

    // The spiral, coloured from blue (start) to green (end).
    const pts = res.xy.map(P);
    const g = new THREE.BufferGeometry().setFromPoints(pts);
    const col = new Float32Array(pts.length * 3);
    const c0 = new THREE.Color('#5ac8fa'), c1 = new THREE.Color('#6ee7a8'), c = new THREE.Color();
    for (let k = 0; k < pts.length; k++) { c.copy(c0).lerp(c1, k / (pts.length - 1)); c.toArray(col, 3 * k); }
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    group.add(new THREE.Line(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true,
      opacity: body === 'Earth' ? 0.55 : 0.9 })));

    const rmax = Math.max(r1, r2);
    craft = LS.spacecraft(rmax * 0.02, { label: 'spacecraft' });
    plume = LS.glowSprite(0x7fb8ff, rmax * 0.05);
    group.add(craft, plume);

    const clk = view.clock;
    const dur = res.duration / DAY;
    clk.min = 0; clk.max = dur; clk.t = 0; clk.playing = true; clk.loop = true;
    const base = Math.max(dur / 45, 0.05);
    clk.rates = [[base / 4, 'slow'], [base / 2, '½×'], [base, 'normal'], [base * 2, '2×'], [base * 4, '4×']];
    clk.rate = base;
    s3.controls.target.set(0, 0, 0);
    s3.camera.position.set(0, rmax * 2.2, rmax * 1.3);
    s3.focusOn(new THREE.Vector3(), rmax * 2.6);
    s3.controls.maxDistance = rmax * 40;
    renderHud();
    LS.syncTimebar();
  }

  function renderHud() {
    const r = res, ch = r.chem;
    const bar = (v, max, color) => `<div class="lt-bar"><i style="width:${Math.max(2, 100 * v / max).toFixed(0)}%;background:${color}"></i></div>`;
    const maxP = Math.max(r.propellant, ch.propellant);
    const years = (s) => (s / DAY > 700 ? `${f(s / DAY / 365.25, 1)} years` : s / DAY >= 2 ? `${f(s / DAY, 0)} days` : `${f(s / 3600, 1)} hours`);
    $('hud-lowthrust').innerHTML = `
      <div class="box"><h4>Ion engine</h4>
        ${LS.kv([['Trip time', years(r.duration)], ['Laps around', f(r.revs, r.revs < 10 ? 1 : 0)],
                 ['Δv', `${f(r.dv, 2)} km/s`], ['Propellant', `${f(r.propellant, 0)} kg (${f(100 * r.propellant / r.mass, 0)}%)`]])}
        ${bar(r.propellant, maxP, '#6ee7a8')}
      </div>
      <div class="box"><h4>Chemical rocket (Isp ${f(ch.isp, 0)} s)</h4>
        ${LS.kv([['Trip time', years(ch.time)], ['Δv', `${f(ch.dv, 2)} km/s`],
                 ['Propellant', `${f(ch.propellant, 0)} kg (${f(100 * ch.propellant / r.mass, 0)}%)`]])}
        ${bar(ch.propellant, maxP, '#ffb454')}
      </div>
      <div class="box"><h4>Now</h4><div id="lt-live"></div></div>`;
  }

  function chart() {
    const t = res.t.map((s) => s / DAY);
    const dist = body === 'Sun' ? res.r.map((x) => x / res.scale) : res.r.map((x) => x - 6378.137);
    // Thin the arrays for the chart (the GEO spiral has tens of thousands of points).
    const step = Math.max(1, Math.floor(t.length / 1500));
    const pick = (a) => a.filter((_, k) => k % step === 0);
    Plotly.react('ch-lt', [
      { x: pick(t), y: pick(dist), name: body === 'Sun' ? 'Distance from the Sun (AU)' : 'Altitude (km)', type: 'scatter',
        mode: 'lines', line: { color: '#5ac8fa', width: 2.5 } },
      { x: pick(t), y: pick(res.speed), name: 'Speed (km/s)', yaxis: 'y2', type: 'scatter', mode: 'lines',
        line: { color: '#ffb454', width: 2 } },
      { x: pick(t), y: pick(res.m), name: 'Mass (kg)', yaxis: 'y3', type: 'scatter', mode: 'lines',
        line: { color: '#6ee7a8', width: 1.5, dash: 'dot' } },
    ], LS.plotLayout({
      title: { text: 'Pushing forward… and ending up slower', x: 0.02, y: 0.97, font: { size: 12.5 } },
      margin: { l: 52, r: 96, t: 60, b: 40 },
      legend: { orientation: 'h', y: 1.12, x: 0, font: { size: 10.5 } },
      xaxis: { title: { text: 'days', font: { size: 11 } }, gridcolor: 'rgba(148,170,210,0.12)', color: '#8b9bbd',
        domain: [0, 0.8] },
      yaxis: { gridcolor: 'rgba(148,170,210,0.12)', color: '#5ac8fa' },
      yaxis2: { overlaying: 'y', side: 'right', anchor: 'x', color: '#ffb454', showgrid: false },
      yaxis3: { overlaying: 'y', side: 'right', position: 1, anchor: 'free', color: '#6ee7a8', showgrid: false },
    }), LS.plotConfig);
  }

  function story() {
    const r = res, ch = r.chem;
    const ve = r.isp * 9.80665 / 1000;
    const acc = r.accel0 * 1000;                                    // mm/s^2
    const to100 = 27.78 / r.accel0 / DAY;                           // days to reach 100 km/h
    const faster = r.speed[0] > r.speed[r.speed.length - 1];
    const hist = r.presetInfo ? `<p class="hint"><b>History:</b> ${LS.esc(r.presetInfo.history)}</p>` : '';
    $('lt-story').innerHTML = `
      <h4>Why ion engines are different</h4>
      <p><b>Very efficient.</b> A chemical engine throws its exhaust out at about 3 km/s. This engine accelerates
        charged xenon atoms with electric fields to about <b>${f(ve, 0)} km/s</b>. By the rocket equation, faster exhaust
        means far less propellant for the same change in speed: here <b>${f(r.propellant, 0)} kg</b> instead of
        ${f(ch.propellant, 0)} kg${ch.propellant > 0.95 * r.mass ? ' (for the chemical engine, that is practically the whole spacecraft)' : ''}.</p>
      <p><b>Very gentle.</b> ${f(r.thrust * 1000, 0)} mN on a ${f(r.mass, 0)} kg spacecraft gives an acceleration of
        ${f(acc, 3)} mm/s². Going from 0 to 100 km/h at that rate would take <b>${f(to100, 1)} days</b>. So the engine fires
        for months or years, and the path becomes a slow spiral (${f(r.revs, r.revs < 10 ? 1 : 0)} laps here) instead of
        a half-orbit coast.</p>
      <p><b>The surprise in the chart:</b> the engine always pushes ${r.r2 > r.r1 ? 'forward' : 'backward'}, yet the
        spacecraft ends up <b>${faster ? 'slower' : 'faster'}</b> (${f(r.speed[0], 1)} → ${f(r.speed[r.speed.length - 1], 1)} km/s).
        ${faster ? 'Pushing forward raises the orbit, and higher orbits are slower: the energy goes into height, not speed.'
          : 'Braking lowers the orbit, and lower orbits are faster: falling inward gains speed.'}</p>
      <p><b>Check:</b> Edelbaum's formula for a slow spiral between circular orbits predicts Δv = |v₁ − v₂| =
        ${f(r.edelbaum_dv, 2)} km/s; the simulation used ${f(r.dv, 2)} km/s.</p>${hist}`;
  }

  /* ---------------- animation ---------------- */

  view.update = function (dt) {
    if (!res || !craft) return;
    const t = view.clock.t * DAY;
    const ts = res.t, n = ts.length;
    let lo = 0, hi = n - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (ts[m] <= t) lo = m; else hi = m; }
    const u = Math.min(Math.max((t - ts[lo]) / ((ts[hi] - ts[lo]) || 1), 0), 1);
    const a = res.xy[lo], b = res.xy[hi];
    const x = a[0] + (b[0] - a[0]) * u, y = a[1] + (b[1] - a[1]) * u;
    const p = new THREE.Vector3(x / unit, 0, -y / unit);
    craft.position.copy(p);
    const q = res.xy[Math.min(hi + 1, n - 1)];
    const ahead = new THREE.Vector3(q[0] / unit, 0, -q[1] / unit);
    LS.aimCraft(craft, ahead);
    const back = p.clone().sub(ahead).normalize().multiplyScalar(craft.userData.model.scale.x * 1.4 * (res.r2 > res.r1 ? 1 : -1));
    plume.position.copy(p).add(back);
    plume.material.opacity = 0.55 + 0.25 * Math.sin(performance.now() / 90);
    phaseTimer -= dt;
    if (phaseTimer <= 0 && $('lt-live')) {
      phaseTimer = 0.2;
      const dist = body === 'Sun' ? `${f(res.r[lo] / res.scale, 3)} AU` : `${f(res.r[lo] - 6378.137, 0)} km altitude`;
      $('lt-live').innerHTML = LS.kv([['Day', f(view.clock.t, 1)], ['Distance', dist],
        ['Speed', `${f(res.speed[lo], 2)} km/s`], ['Mass left', `${f(res.m[lo], 0)} kg`]]);
    }
  };

  view.show = () => { if (s3) s3.resize(); };
  view.resize = function () {
    if (s3) s3.resize();
    const el = $('ch-lt'); if (el.data) Plotly.Plots.resize(el);
  };
  view.render = () => s3 && s3.render();
  view.clockLabel = (t) => (res ? `day ${f(t, 1)} of ${f(res.duration / DAY, 0)}` : '—');
  view.nowLabel = 'Start';
  view.onNow = () => { view.clock.t = 0; };
})();
