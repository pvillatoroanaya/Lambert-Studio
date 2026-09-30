/* Maneuver planner: Hohmann, bi-elliptic, plane change, or circularising
   the solved orbit. Python (maneuvers.py) builds the plan from state
   vectors; this view draws it and flies a spacecraft through it. */
'use strict';

(function () {
  const S = 1 / LS.R_EARTH;
  const $ = (id) => document.getElementById(id);
  const COLORS = { initial: 0x5ac8fa, transfer: 0xffb454, final: 0x6ee7a8 };

  const view = {
    id: 'maneuver',
    title: 'Maneuver planner',
    subtitle: 'Blue: starting orbit · orange: transfer · green: final orbit · red arrows: engine burns',
    clock: new LS.Clock({ t: 0, min: 0, max: 1, rate: 100, loop: true, rates: [[100, '100×']] }),
  };
  LS.views.maneuver = view;

  let s3, earth, sun, planGroup, craft, plan = null, kind = 'hohmann', where = 'apogee';

  const PRESETS = [
    { label: 'LEO → GEO from Cape Canaveral', kind: 'hohmann', alt1: 300, alt2: 35786, i1: 28.5, i2: 0, altb: 100000 },
    { label: 'LEO → GEO from the equator', kind: 'hohmann', alt1: 300, alt2: 35786, i1: 0, i2: 0, altb: 100000 },
    { label: 'ISS reboost', kind: 'hohmann', alt1: 400, alt2: 420, i1: 51.6, i2: 51.6, altb: 100000 },
    { label: 'When bi-elliptic wins', kind: 'bielliptic', alt1: 300, alt2: 400000, i1: 0, i2: 0, altb: 900000 },
    { label: 'Cape → ISS plane', kind: 'plane', alt1: 400, alt2: 400, i1: 28.5, i2: 51.6, altb: 100000 },
  ];

  view.init = function () {
    s3 = new LS.Scene3D($('cv-maneuver'), { near: 0.001, far: 5e5 });
    earth = LS.earth();
    s3.scene.add(earth.group);
    s3.scene.add(new THREE.AmbientLight(0x6070a0, 0.35));
    sun = new THREE.DirectionalLight(0xffffff, 1.25);
    s3.scene.add(sun);
    const grid = new THREE.PolarGridHelper(10, 12, 5, 96, 0x2a3b60, 0x1a2640);
    grid.material.transparent = true; grid.material.opacity = 0.3;
    s3.scene.add(grid);
    s3.camera.position.set(6, 5, 10);
    s3.controls.minDistance = 1.3;
    s3.controls.maxDistance = 5000;
    s3.setFollowables([
      { label: 'Spacecraft', obj: () => craft || null },
      { label: 'Earth', obj: () => earth.surface },
    ]);

    document.querySelectorAll('#mv-kind button').forEach((b) => b.addEventListener('click', () => setKind(b.dataset.k)));
    document.querySelectorAll('#mv-where button').forEach((b) => b.addEventListener('click', () => {
      document.querySelectorAll('#mv-where button').forEach((x) => x.classList.toggle('on', x === b));
      where = b.dataset.w;
    }));
    $('mv-presets').innerHTML = PRESETS.map((p, k) => `<button data-k="${k}">${p.label}</button>`).join('');
    $('mv-presets').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
      const p = PRESETS[+b.dataset.k];
      for (const f of ['alt1', 'alt2', 'i1', 'i2', 'altb']) $('mv-' + f).value = p[f];
      setKind(p.kind);
      compute();
    }));
    $('btn-mv').addEventListener('click', compute);
    document.querySelector('[data-for="maneuver"]').addEventListener('keydown', (e) => { if (e.key === 'Enter') compute(); });
    setKind('hohmann');
    compute();
  };

  function setKind(k) {
    kind = k;
    document.querySelectorAll('#mv-kind button').forEach((x) => x.classList.toggle('on', x.dataset.k === k));
    $('mv-orbits').hidden = k === 'circularize';
    $('mv-circ').hidden = k !== 'circularize';
    $('mv-alt2-l').hidden = k === 'plane';
    $('mv-altb-l').hidden = k === 'plane';
    $('mv-altb-l').firstChild.textContent = k === 'bielliptic'
      ? 'Intermediate apoapsis altitude (km)' : 'Bi-elliptic apoapsis, for comparison (km)';
  }

  async function compute() {
    $('mv-err').hidden = true;
    const v = (id) => $(id).value;
    const req = { kind, mass: v('mv-mass'), isp: v('mv-isp'), alt1: v('mv-alt1'), alt2: v('mv-alt2'),
      i1: v('mv-i1'), i2: v('mv-i2'), altb: v('mv-altb'), where };
    if (kind === 'circularize') {
      if (!LS.solution) { showErr('Solve an orbit in the Orbit tab first.'); return; }
      req.r = LS.solution.r1; req.v = LS.solution.v1;
    }
    try {
      plan = await LS.busy('Planning the maneuver…', $('btn-mv'), () => LS.api('/api/maneuver', req));
      LS.emit('maneuver', { plan, req });
      draw();
    } catch (e) { showErr(e.message); }
  }

  function showErr(msg) { $('mv-err').textContent = msg; $('mv-err').hidden = false; }

  function draw() {
    if (planGroup) {
      planGroup.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.element) o.element.remove(); });
      s3.scene.remove(planGroup);
    }
    planGroup = new THREE.Group();
    s3.scene.add(planGroup);

    const all = plan.segments.flatMap((s) => s.r);
    const rmax = Math.max(...all.map((p) => Math.hypot(...p))) * S;
    const w = Math.max(rmax * 0.0028, 0.012);
    for (const seg of plan.segments) {
      const pts = seg.r.map((p) => LS.v3(p, S));
      const closed = seg.kind !== 'transfer' && seg.t[seg.t.length - 1] - seg.t[0] > 0;
      planGroup.add(LS.tube(pts, seg.kind === 'transfer' ? w * 1.6 : w, COLORS[seg.kind], false, seg.kind === 'initial' ? 0.75 : 0.95));
      if (closed && seg.kind === 'final') {
        const lb = LS.label(seg.label, 'dim'); lb.position.copy(pts[Math.floor(pts.length * 0.3)]); planGroup.add(lb);
      }
    }
    plan.burns.forEach((b) => {
      const p = LS.v3(b.r, S);
      const dot = LS.dot(w * 3.5, 0xff6b6b); dot.position.copy(p); planGroup.add(dot);
      const dir = LS.v3(b.dir).normalize();
      const len = rmax * 0.12;
      planGroup.add(new THREE.ArrowHelper(dir, p, len, 0xff6b6b, len * 0.3, len * 0.18));
      const lb = LS.label(`${b.label.split(' · ')[0]}  ${LS.fmt(b.dv, 3)} km/s`, 'warm');
      lb.position.copy(p.clone().add(dir.clone().multiplyScalar(len)));
      planGroup.add(lb);
    });
    craft = LS.spacecraft(Math.max(rmax * 0.012, 0.05));
    planGroup.add(craft);

    const c = view.clock, T = plan.duration;
    c.min = 0; c.max = T; c.t = 0; c.loop = true; c.playing = true;
    const base = T / 40;                                   // a full run in ~40 s
    c.rates = [[base / 4, 'slow'], [base / 2, '½'], [base, 'normal'], [base * 2, '2×'], [base * 4, '4×']];
    c.rate = base;
    s3.focusOn(new THREE.Vector3(), Math.max(rmax * 2.6, 4));
    s3.controls.maxDistance = rmax * 30;
    renderHud();
    LS.syncTimebar();
  }

  function renderHud() {
    const f = LS.fmt;
    const burns = plan.burns.map((b) => [b.label, `${f(b.dv, 3)}&nbsp;km/s`]);
    let cmp = '';
    if (plan.comparison) {
      cmp = `<div class="box"><h4>Compare the options</h4>${plan.comparison.map((r) => `
        <div class="opt${r.best ? ' best' : ''}"><div>${r.name}${r.best ? ' <span class="badge ok">cheapest</span>' : ''}</div>
        <div class="muted">${r.total_dv === null ? '—' : `<b>${f(r.total_dv, 3)} km/s</b> · ${LS.fmtDuration(r.time)}`}</div></div>`).join('')}</div>`;
    }
    $('hud-maneuver').innerHTML = `
      <div class="box"><h4>${plan.title}</h4>
        <div class="big">Δv ${f(plan.total_dv, 3)} km/s</div>
        ${LS.kv([['Transfer time', LS.fmtDuration(plan.transfer_time)],
                 ['Propellant', `${f(plan.propellant, 1)} kg`],
                 ['Mass left', `${f(plan.final_mass, 1)} kg (${f(100 * plan.final_mass / (plan.final_mass + plan.propellant), 1)}%)`]])}
      </div>
      <div class="box"><h4>Burns</h4>${LS.kv(burns)}
        ${plan.notes.map((n) => `<p class="hint" style="margin-top:6px">${LS.esc(n)}</p>`).join('')}</div>
      ${cmp}`;
  }

  /* ---------------- per frame ---------------- */

  function positionAt(t) {
    for (const seg of plan.segments) {
      const ts = seg.t, n = ts.length;
      if (t <= ts[n - 1] || seg === plan.segments[plan.segments.length - 1]) {
        let lo = 0, hi = n - 1;
        while (hi - lo > 1) { const m = (lo + hi) >> 1; if (ts[m] <= t) lo = m; else hi = m; }
        const u = Math.min(Math.max((t - ts[lo]) / ((ts[hi] - ts[lo]) || 1), 0), 1);
        const a = seg.r[lo], b = seg.r[hi];
        return { seg, p: [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u] };
      }
    }
    return null;
  }

  let phaseTimer = 0;
  view.update = function (dt) {
    const jd = LS.nowJd() + view.clock.t / 86400;
    earth.spin.rotation.y = LS.gmst(jd);
    earth.clouds.rotation.y += dt * 0.004;
    sun.position.copy(LS.v3(LS.sunDirection(jd), 50));
    earth.setSun(sun.position);
    if (!plan || !craft) return;
    const at = positionAt(view.clock.t);
    if (!at) return;
    craft.position.copy(LS.v3(at.p, S));
    const ahead = positionAt(view.clock.t + 60);
    if (ahead) LS.aimCraft(craft, LS.v3(ahead.p, S));
    phaseTimer -= dt;
    if (phaseTimer <= 0) {
      phaseTimer = 0.2;
      const next = plan.burns.find((b) => b.t > view.clock.t);
      const r = Math.hypot(...at.p);
      $('mv-phase').hidden = false;
      $('mv-phase').innerHTML = `<b>${LS.esc(at.seg.label)}</b> · altitude ${LS.fmt(r - LS.R_EARTH, 0)} km` +
        (next ? ` · next burn in ${LS.fmtDuration(next.t - view.clock.t)}` : '');
    }
  };

  view.render = () => s3.render();
  view.clockLabel = (t) => `T + ${LS.fmtDuration(t)}`;
  view.nowLabel = 'Start';
  view.onNow = () => { view.clock.t = 0; };
})();
