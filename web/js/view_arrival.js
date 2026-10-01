/* Arrival at a giant planet and moon tours. Python (moontour.py) finds
   the tour; this view flies it in 3D around the planet, draws the
   Tisserand graph, and explains every step. Scene unit: 1 planet radius. */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const f = (x, d) => LS.fmt(x, d);
  const DAY = 86400;
  const MOON_SCALE = 8;                      // moons drawn 8x larger than scale
  const CHART_COLORS = ['#5eb3e6', '#eea55a', '#e3cc6a', '#7fcf9f'];
  const KIND_COLOR = { capture: '#eea55a', raised: '#ffd27a', transfer: '#e9ecf3' };

  const view = {
    id: 'arrival',
    title: 'Arrival & moon tours',
    subtitle: 'Seen from above the planet · the spacecraft loops the planet and meets its moons again and again',
    clock: new LS.Clock({ t: 0, min: 0, max: 1, rate: 5, loop: true, rates: [[5, '5 days/s']] }),
  };
  LS.views.arrival = view;

  let s3, planet = null, moons = {}, group = null, craft = null, tour = null, presets = [], meta = null;
  let arcLines = [], current = -1, phaseTimer = 0, lastEvent = -1;

  /* ---------------- controls ---------------- */

  view.init = async function () {
    meta = await LS.api('/api/tour_presets');
    presets = meta.presets;
    $('ar-presets').innerHTML = presets.map((p, k) => `
      <button class="preset" data-k="${k}"><b>${LS.esc(p.label)}</b><span>${p.planet} · ${p.goal === 'orbit'
        ? `ends in orbit around ${p.target}` : `shrinks the orbit to ${p.goal_period} days`}</span></button>`).join('');
    $('ar-presets').querySelectorAll('.preset').forEach((b) => b.addEventListener('click', () => {
      markPreset(+b.dataset.k);
      applyPreset(presets[+b.dataset.k]);
      plan({ preset: presets[+b.dataset.k].key });
    }));
    $('ar-planet').addEventListener('change', () => { fillMoons(); });
    $('ar-goal').addEventListener('change', syncGoal);
    $('btn-tour').addEventListener('click', () => { markPreset(-1); plan(request()); });
    $('ar-from-route').addEventListener('click', () => {
      const r = LS.lastRoute;
      const arr = r.events[r.events.length - 1];
      $('ar-planet').value = arr.planet;
      fillMoons();
      $('ar-vinf').value = arr.vinf.toFixed(2);
    });
    LS.on('route', updateFromRoute);
    ensureScene();
    applyPreset(presets[0]);
    markPreset(0);
    await plan({ preset: presets[0].key });
  };

  function markPreset(k) {
    $('ar-presets').querySelectorAll('.preset').forEach((x, i) => x.classList.toggle('on', i === k));
  }

  function updateFromRoute(r) {
    const arr = r && r.events[r.events.length - 1];
    const ok = arr && ['Jupiter', 'Saturn', 'Uranus'].includes(arr.planet);
    $('ar-from-route').hidden = !ok;
    if (ok) $('ar-from-route').textContent = `Use my last route's arrival: ${arr.planet}, v∞ ${f(arr.vinf, 2)} km/s`;
  }

  function fillMoons(sel) {
    const pl = $('ar-planet').value;
    const list = meta.moons[pl] || [];
    const chosen = new Set(sel || list.slice(-2));
    $('ar-moons').innerHTML = list.map((m) => `<button data-m="${m}" class="${chosen.has(m) ? 'on' : ''}">${m}</button>`).join('');
    $('ar-moons').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => b.classList.toggle('on')));
    $('ar-target').innerHTML = list.map((m) => `<option>${m}</option>`).join('');
  }

  function syncGoal() {
    const orbit = $('ar-goal').value === 'orbit';
    $('ar-target-l').hidden = !orbit;
    $('ar-gp-l').hidden = orbit;
  }

  function applyPreset(p) {
    $('ar-planet').value = p.planet;
    fillMoons(p.moons);
    $('ar-goal').value = p.goal;
    if (p.target) $('ar-target').value = p.target;
    if (p.goal_period) $('ar-gp').value = p.goal_period;
    $('ar-vinf').value = p.vinf; $('ar-rp').value = p.rp_radii; $('ar-period').value = p.period_days;
    $('ar-raise').value = p.raise_radii || ''; $('ar-years').value = p.years;
    syncGoal();
  }

  function request() {
    return {
      planet: $('ar-planet').value, goal: $('ar-goal').value, target: $('ar-target').value,
      goal_period: $('ar-gp').value,
      moons: [...$('ar-moons').querySelectorAll('button.on')].map((b) => b.dataset.m),
      vinf: $('ar-vinf').value, rp_radii: $('ar-rp').value, period_days: $('ar-period').value,
      raise_radii: $('ar-raise').value, years: $('ar-years').value,
    };
  }

  async function plan(req) {
    $('ar-err').hidden = true;
    try {
      tour = await LS.busy('Searching moon tours…', $('btn-tour'), () => LS.api('/api/tour', req));
      tour.presetInfo = req.preset ? presets.find((p) => p.key === req.preset) : null;
      $('empty-arrival').hidden = true;
      draw();
      tisserand();
      story();
      LS.emit('tour-result', tour);
    } catch (e) {
      $('ar-err').textContent = e.message;
      $('ar-err').hidden = false;
    }
  }

  /* ---------------- 3D ---------------- */

  // (x, y) in the orbit plane [km] -> scene (planet radii), plane = horizontal
  const P3 = (x, y, R) => new THREE.Vector3(x / R, 0, -y / R);

  function ensureScene() {
    if (s3) return;
    s3 = new LS.Scene3D($('cv-arrival'), { near: 1e-3, far: 1e5 });
    s3.scene.add(new THREE.AmbientLight(0x3a4466, 0.4));
    const sunLight = new THREE.DirectionalLight(0xfff4e0, 1.25);
    sunLight.position.set(-60, 25, 40);
    s3.scene.add(sunLight);
    s3.camera.position.set(0, 40, 40);
    s3.setFollowables([
      { label: 'Spacecraft', obj: () => craft },
      { label: 'Planet', obj: () => planet },
      ...['Io', 'Europa', 'Ganymede', 'Callisto', 'Titan', 'Rhea', 'Dione', 'Enceladus', 'Titania', 'Oberon']
        .map((n) => ({ label: n, obj: () => (moons[n] ? moons[n].mesh : null) })),
    ]);
  }

  function planetMesh(name) {
    const g = new THREE.Group();
    const m = new THREE.Mesh(new THREE.SphereGeometry(1, 96, 64),
      new THREE.MeshStandardMaterial({ map: LS.texture(`textures/${name.toLowerCase()}.jpg`), roughness: 1 }));
    g.add(m);
    if (name === 'Saturn') {
      const inner = 1.24, outer = 2.27;
      const rg = new THREE.RingGeometry(inner, outer, 180, 1);
      const pos = rg.attributes.position, uv = rg.attributes.uv, v = new THREE.Vector3();
      for (let k = 0; k < pos.count; k++) { v.fromBufferAttribute(pos, k); uv.setXY(k, (v.length() - inner) / (outer - inner), 0.5); }
      const ring = new THREE.Mesh(rg, new THREE.MeshStandardMaterial({ map: LS.texture('textures/saturn_ring.png'),
        side: THREE.DoubleSide, transparent: true, depthWrite: false, roughness: 1 }));
      ring.rotation.x = Math.PI / 2;           // in the moons' plane
      g.add(ring);
    }
    g.add(LS.label(name, 'warm'));
    return g;
  }

  function draw() {
    if (group) {
      group.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.element) o.element.remove(); });
      s3.scene.remove(group);
    }
    group = new THREE.Group();
    s3.scene.add(group);
    const R = tour.radius;
    planet = planetMesh(tour.planet);
    group.add(planet);

    moons = {};
    let rMoonMax = 0;
    for (const [name, m] of Object.entries(tour.moons)) {
      const r = m.r / R;
      rMoonMax = Math.max(rMoonMax, r);
      const circle = [];
      for (let k = 0; k <= 256; k++) circle.push(new THREE.Vector3(r * Math.cos(k / 256 * 2 * Math.PI), 0, -r * Math.sin(k / 256 * 2 * Math.PI)));
      group.add(LS.line(circle, new THREE.Color(m.color).getHex(), 0.45));
      const mat = new THREE.MeshStandardMaterial({ map: LS.texture('textures/moon.jpg'), color: m.color, roughness: 1 });
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(m.R / R * MOON_SCALE, 48, 32), mat);
      mesh.add(LS.label(name));
      mesh.add(LS.markerRing(new THREE.Color(m.color).getHex(), 0.018));
      group.add(mesh);
      moons[name] = { ...m, mesh };
    }

    // The tour's arcs (each resonant arc repeats itself, so one lap is drawn).
    arcLines = tour.arcs.map((a) => {
      const color = a.kind === 'resonant' ? tourMoonColor(a) : (KIND_COLOR[a.kind] || '#e9ecf3');
      const line = LS.line(a.samples.map((p) => P3(p[0], p[1], R)), new THREE.Color(color).getHex(), 0.25);
      group.add(line);
      return line;
    });

    // Burn and flyby markers.
    tour.events.forEach((e) => {
      let p = null, txt = '', cls = '';
      if (e.kind === 'capture') { p = P3(e.rp, 0, R); txt = `Capture burn ${f(e.dv, 2)} km/s`; cls = 'warm'; }
      else if (e.kind === 'raise') { p = P3(-e.ra, 0, R); txt = `Raise burn ${f(e.dv, 2)} km/s`; cls = 'warm'; }
      if (p) {
        const d = LS.dot(0.12, 0xe56f6f); d.position.copy(p); group.add(d);
        const lb = LS.label(txt, cls); lb.position.copy(p); group.add(lb);
      }
    });

    craft = LS.spacecraft(0.35, { label: 'spacecraft' });
    group.add(craft);

    const c = view.clock;
    const dur = tour.duration_days;
    c.min = 0; c.max = dur + 10; c.t = 0; c.playing = true; c.loop = true;
    const base = Math.max(dur / 70, 0.5);
    c.rates = [[base / 4, 'slow'], [base / 2, '½×'], [base, 'normal'], [base * 2, '2×'], [base * 4, '4×']];
    c.rate = base;
    current = -1; lastEvent = -1;
    s3.controls.target.set(0, 0, 0);
    s3.camera.position.set(rMoonMax * 0.25, rMoonMax * 1.55, rMoonMax * 1.25);
    s3.focusOn(new THREE.Vector3(), rMoonMax * 2.1);
    s3.controls.maxDistance = rMoonMax * 40;
    renderLegend();
    renderHud();
    LS.syncTimebar();
  }

  function tourMoonColor(arc) {
    // Resonant arcs belong to the moon met at their start.
    const ev = tour.events.find((e) => e.kind === 'flyby' && Math.abs(e.t - arc.t0) < 1);
    return ev ? tour.moons[ev.moon].color : '#e9ecf3';
  }

  function renderLegend() {
    const items = [['#eea55a', 'Capture orbit'], ['#ffd27a', 'After the raise burn'],
      ...Object.entries(tour.moons).map(([n, m]) => [m.color, `Loops that return to ${n}`]), ['#e9ecf3', 'Hops between moons']];
    $('legend-arrival').innerHTML = items.map(([c, t]) => `<div><i style="background:${c}"></i>${t}</div>`).join('');
  }

  function renderHud() {
    const t = tour;
    const rows = [['Capture burn', `${f(t.capture_dv, 3)} km/s`]];
    if (t.raise_dv) rows.push(['Raise burn', `${f(t.raise_dv, 3)} km/s`]);
    if (t.insertion_dv !== null) rows.push([`Enter orbit at ${t.target}`, `${f(t.insertion_dv, 3)} km/s`]);
    rows.push(['Total', `<b>${f(t.total_dv, 3)} km/s</b>`], ['Flybys', `${t.n_flybys}`],
      ['Tour length', `${f(t.duration_days, 0)} days (${f(t.duration_days / 365.25, 1)} y)`]);
    let verdict = '';
    if (t.direct) {
      const saved = t.direct.dv - t.insertion_dv;
      verdict = `<div class="verdict good">Tour saves ${f(saved, 2)} km/s</div>
        <p>Entering orbit around ${t.target} on the first pass would need <b>${f(t.direct.dv, 2)} km/s</b>
        (arriving at ${f(t.direct.vinf, 1)} km/s); after the tour it needs only <b>${f(t.insertion_dv, 2)} km/s</b>.</p>`;
    } else if (t.goal === 'period') {
      verdict = `<div class="verdict good">${f(t.final_period_days, 1)}-day orbit</div>
        <p>Shrunk from a ${f(t.events[0].period_days, 0)}-day capture orbit using only moon flybys (no fuel).</p>`;
    }
    $('hud-arrival').innerHTML = `<div class="box"><h4>${t.planet}${t.target ? ` → orbit around ${t.target}` : ' moon tour'}</h4>
        ${verdict}${LS.kv(rows)}</div>
      <div class="box"><h4>Now</h4><div id="ar-live"></div></div>`;
  }

  /* ---------------- Tisserand graph ---------------- */

  function tisserand() {
    const traces = [];
    const shown = new Set();
    const names = Object.keys(tour.moons);
    const moonColor = (m) => CHART_COLORS[names.indexOf(m) % CHART_COLORS.length];
    const R = tour.radius;
    const rMin = Math.min(...names.map((n) => tour.moons[n].r / R));
    tour.tisserand.forEach((c) => {
      const color = moonColor(c.moon);
      traces.push({ x: c.pts.map((p) => p[0]), y: c.pts.map((p) => p[1]), type: 'scatter', mode: 'lines',
        line: { color, width: 1 }, opacity: 0.55, hoverinfo: 'text',
        text: c.pts.map(() => `${c.moon}: v∞ = ${c.vinf} km/s`), name: c.moon,
        showlegend: !shown.has(c.moon), legendgroup: c.moon });
      shown.add(c.moon);
    });
    const path = tour.path;
    traces.push({ x: path.map((p) => p.rp), y: path.map((p) => p.P), type: 'scatter', mode: 'lines+markers',
      name: 'This tour', line: { color: '#ea7f7f', width: 2.5 }, marker: { size: 7, color: '#ea7f7f' },
      text: path.map((p, k) => `${k === 0 ? 'capture' : p.label} · closest ${f(p.rp, 1)} R · period ${f(p.P, 1)} d`),
      hoverinfo: 'text' });
    // Label each moon's contours with their v∞ at the right-hand end.
    const ann = tour.tisserand.filter((c) => [1, 2, 4, 6].includes(c.vinf)).map((c) => {
      const p = c.pts[c.pts.length - 1];
      return { x: Math.log10(p[0]), y: Math.log10(p[1]), text: `${c.vinf}`, showarrow: false,
        font: { size: 9, color: moonColor(c.moon) }, xanchor: 'left' };
    });
    // Round numbers only on the log axes (Plotly's default repeats 2 and 5 in every decade).
    const TICKS = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000];
    Plotly.react('ch-tisserand', traces, LS.plotLayout({
      title: { text: 'Tisserand graph: how the tour steps down', x: 0.02, y: 0.97, font: { size: 12.5 } },
      margin: { l: 54, r: 14, t: 64, b: 40 }, annotations: ann,
      xaxis: { type: 'log', tickvals: TICKS, ticktext: TICKS.map(String), range: [Math.log10(Math.max(1, rMin * 0.25)), Math.log10(Math.max(...path.map((p) => p.rp)) * 1.6)],
        title: { text: 'closest approach to the planet (planet radii)', font: { size: 11 } },
        gridcolor: 'rgba(255,255,255,0.06)', color: '#8d95a8' },
      yaxis: { type: 'log', tickvals: TICKS, ticktext: TICKS.map(String), title: { text: 'orbit period (days)', font: { size: 11 } },
        gridcolor: 'rgba(255,255,255,0.06)', color: '#8d95a8' },
    }), LS.plotConfig);
  }

  /* ---------------- the story ---------------- */

  function flybyText(e, k) {
    const move = e.move === 'resonant'
      ? `The new orbit takes ${f(e.period_days, 1)} days: exactly ${e.res[1] === 1 ? '' : `${e.res[1]} laps = `}${e.res[0]}
         ${e.moon} lap${e.res[0] > 1 ? 's' : ''} (a ${e.res[0]}:${e.res[1]} resonance), so the two meet again at the same place.`
      : `The new orbit (${f(e.period_days, 1)} days) now crosses ${e.to}'s path: the next flyby is with ${e.to}.`;
    const alt = e.altitude > 1e5 ? `${f(e.altitude / 1000, 0)} thousand km` : `${f(e.altitude, 0)} km`;
    return `Passing ${alt} above ${e.moon} at ${f(e.vinf, 2)} km/s relative to it, the path is bent by ${f(e.turn_deg, 1)}°
      (the most ${e.moon} can give at this speed is ${f(e.max_turn_deg, 1)}°). ${move}`;
  }

  function story() {
    const t = tour;
    const R = t.radius;
    const items = t.events.map((e, k) => {
      const when = `day ${f(e.t / DAY, 0)}`;
      let title, text, color = '#7fcf9f';
      if (e.kind === 'capture') {
        title = `Capture at ${t.planet}`; color = '#eea55a';
        text = `Arriving at ${f(e.vinf, 1)} km/s, the spacecraft brakes by <b>${f(e.dv, 2)} km/s</b> at its closest point,
          ${f(e.rp / R, 1)} ${t.planet} radii from the centre. Braking where it moves fastest is the most efficient place
          (the Oberth effect). ${t.planet}'s gravity now holds it in a loose ${f(e.period_days, 0)}-day orbit.`;
      } else if (e.kind === 'raise') {
        title = 'Raise the closest approach'; color = '#ffd27a';
        text = `At the far point, where the spacecraft moves slowest, a small burn of <b>${f(e.dv, 2)} km/s</b> lifts the
          closest approach to ${f(e.rp / R, 1)} radii, close to the moons' orbits. Now it meets the moons gently instead of
          racing past them, and each flyby can bend its path more.`;
      } else if (e.kind === 'flyby') {
        title = `${e.moon} flyby`; color = t.moons[e.moon].color;
        text = flybyText(e, k);
      } else if (e.kind === 'insertion') {
        title = `Enter orbit around ${e.moon}`; color = '#ea7f7f';
        text = `The spacecraft now reaches ${e.moon} at only ${f(e.vinf, 2)} km/s, so a braking burn of
          <b>${f(e.dv, 2)} km/s</b> puts it into a ${f(e.altitude, 0)} km orbit.
          ${t.direct ? `Doing this on the first pass would have cost ${f(t.direct.dv, 2)} km/s.` : ''}`;
      } else {
        title = 'Tour complete'; color = '#ea7f7f';
        text = `The orbit now takes ${f(e.period_days, 1)} days, down from ${f(t.events[0].period_days, 0)}: the moons did
          all of that without a drop of fuel.`;
      }
      return `<div class="ev" style="--c:${color}"><div class="when">${when}</div><div class="what">${title}</div><p>${text}</p></div>`;
    }).join('');
    const hist = t.presetInfo ? `<p class="hint"><b>History:</b> ${LS.esc(t.presetInfo.history)}</p>` : '';
    $('arrival-story').innerHTML = `
      <h4>How a moon tour works</h4>
      <p>Relative to a moon, a flyby can only <b>turn</b> the spacecraft's velocity; its speed relative to the moon stays
        the same. But the moon itself is moving around the planet, so that turn changes the spacecraft's orbit around the
        <i>planet</i>: shorter or longer, rounder or more stretched. Choosing the turn so the spacecraft comes back to
        the same moon later (a <b>resonance</b>) lets mission designers repeat the trick again and again.</p>
      <p><b>Reading the Tisserand graph:</b> each coloured line is the family of orbits that meet one moon at one relative
        speed (v∞, the small numbers). Flybys of a moon slide the orbit along its line. Where the lines of two moons cross,
        the spacecraft can hop to the other moon's line, often a slower one: that "ladder" is how tours arrive gently.</p>
      <h4>This tour, step by step</h4>
      <div class="timeline">${items}</div>${hist}`;
  }

  /* ---------------- animation ---------------- */

  function moonAngle(m, t) {
    const ks = m.knots;
    if (!ks.length) return m.rate * t;
    if (t <= ks[0][0]) return ks[0][1] + m.rate * (t - ks[0][0]);
    for (const s of m.segs) if (t <= s[1]) return s[2] + s[3] * (t - s[0]);
    const lastK = ks[ks.length - 1];
    return lastK[1] + m.rate * (t - lastK[0]);
  }

  function craftPos(t) {
    const arcs = tour.arcs;
    let k = arcs.findIndex((a) => t < a.t1);
    if (k < 0) k = arcs.length - 1;
    const a = arcs[k];
    const M = (a.M0 + a.n * (t - a.t0)) % (2 * Math.PI);
    const E = LS.kepler(M < 0 ? M + 2 * Math.PI : M, a.e);
    const nu = 2 * Math.atan2(Math.sqrt(1 + a.e) * Math.sin(E / 2), Math.sqrt(1 - a.e) * Math.cos(E / 2));
    const r = a.a * (1 - a.e * Math.cos(E));
    return { k, x: r * Math.cos(nu + a.w), y: r * Math.sin(nu + a.w), r };
  }

  view.update = function (dt) {
    if (!tour || !s3) return;
    const t = view.clock.t * DAY;
    const R = tour.radius;
    planet.rotation.y += dt * 0.2;
    for (const [, m] of Object.entries(moons)) {
      const th = moonAngle(m, t);
      m.mesh.position.set(m.r / R * Math.cos(th), 0, -m.r / R * Math.sin(th));
    }
    const p = craftPos(t);
    craft.position.copy(P3(p.x, p.y, R));
    const q = craftPos(t + 3600);
    LS.aimCraft(craft, P3(q.x, q.y, R));
    if (p.k !== current) {
      arcLines.forEach((l, i) => { l.material.opacity = i === p.k ? 0.95 : 0.2; });
      current = p.k;
    }
    phaseTimer -= dt;
    if (phaseTimer <= 0) {
      phaseTimer = 0.2;
      const evs = tour.events;
      let idx = -1;
      evs.forEach((e, i) => { if (e.t <= t) idx = i; });
      const next = evs.find((e) => e.t > t);
      const period = 2 * Math.PI / tour.arcs[p.k].n / DAY;
      const live = $('ar-live');
      if (live) {
        live.innerHTML = LS.kv([['Day', f(view.clock.t, 1)], ['Distance', `${f(p.r / R, 1)} ${tour.planet} radii`],
          ['Orbit period now', `${f(period, 1)} days`],
          ['Next', next ? `${next.kind === 'flyby' ? `${next.moon} flyby` : next.kind === 'insertion' ? `orbit ${next.moon}` : next.kind} in ${f((next.t - t) / DAY, 1)} d` : 'tour complete']]);
      }
      if (idx !== lastEvent && idx >= 0) {
        lastEvent = idx;
        const e = evs[idx];
        $('ar-phase').hidden = false;
        $('ar-phase').innerHTML = e.kind === 'flyby'
          ? `<b>${e.moon} flyby</b> · bent ${f(e.turn_deg, 1)}° · new period ${f(e.period_days, 1)} d`
          : e.kind === 'capture' ? `<b>Capture burn</b> · ${f(e.dv, 2)} km/s`
            : e.kind === 'raise' ? `<b>Raise burn</b> · ${f(e.dv, 2)} km/s`
              : e.kind === 'insertion' ? `<b>In orbit around ${e.moon}</b> · ${f(e.dv, 2)} km/s burn`
                : `<b>Tour complete</b> · ${f(e.period_days, 1)}-day orbit`;
      }
    }
  };

  view.show = function () { if (s3) s3.resize(); if (LS.lastRoute) updateFromRoute(LS.lastRoute); };
  view.resize = function () {
    if (s3) s3.resize();
    const el = $('ch-tisserand'); if (el.data) Plotly.Plots.resize(el);
  };
  view.render = () => s3 && s3.render();
  view.clockLabel = (t) => (tour ? `day ${f(t, 1)} of ${f(tour.duration_days, 0)}` : '—');
  view.nowLabel = 'Back to start';
  view.onNow = () => { view.clock.t = 0; };
})();
