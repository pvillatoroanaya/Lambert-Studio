/* Gravity-assist routes (Mission tab, second mode). Python (flyby.py)
   finds the cheapest dates; this file draws the route in 3D, charts the
   spacecraft's speed, and tells the story of each flyby in plain words. */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const LEG_COLORS = [0x5ac8fa, 0xffb454, 0xc792ea];
  const LEG_CSS = ['#5ac8fa', '#ffb454', '#c792ea'];
  const SIZE = { Mercury: 0.02, Venus: 0.03, Earth: 0.032, Mars: 0.024,
    Jupiter: 0.14, Saturn: 0.12, Uranus: 0.08, Neptune: 0.08 };

  const R = {
    clock: new LS.Clock({ t: 0, min: -30, max: 1, rate: 30, loop: true,
      rates: [[5, '5 days/s'], [15, '15 days/s'], [30, '30 days/s'], [60, '60 days/s'], [120, '120 days/s']] }),
  };
  LS.route = R;

  let s3 = null, bodies = {}, routeGroup = null, craft = null, route = null, presets = [];

  R.init = async function () {
    const data = await LS.api('/api/route_presets');
    presets = data.presets;
    const opts = (none) => (none ? '<option value="">— none —</option>' : '') +
      data.planets.map((p) => `<option>${p}</option>`).join('');
    $('r-p0').innerHTML = opts(false); $('r-p3').innerHTML = opts(false);
    $('r-p1').innerHTML = opts(true); $('r-p2').innerHTML = opts(true);
    $('r-presets').innerHTML = presets.map((p, k) => `
      <button class="preset" data-k="${k}"><b>${LS.esc(p.label)}</b><span>${p.from.slice(0, 4)} launch · ${p.capture ? 'enter orbit' : 'fly past'}</span></button>`).join('');
    $('r-presets').querySelectorAll('.preset').forEach((b) => b.addEventListener('click', () => {
      $('r-presets').querySelectorAll('.preset').forEach((x) => x.classList.toggle('on', x === b));
      applyPreset(presets[+b.dataset.k]);
      find();
    }));
    $('btn-route').addEventListener('click', () => {
      $('r-presets').querySelectorAll('.preset').forEach((x) => x.classList.remove('on'));
      R.preset = null;
      find();
    });
    applyPreset(presets[0]);
  };

  function applyPreset(p) {
    R.preset = p;
    const s = p.seq;
    $('r-p0').value = s[0];
    $('r-p3').value = s[s.length - 1];
    $('r-p1').value = s.length > 2 ? s[1] : '';
    $('r-p2').value = s.length > 3 ? s[2] : '';
    $('r-from').value = p.from; $('r-to').value = p.to;
    $('r-max').value = p.max_years;
    $('r-goal').value = p.capture ? 'orbit' : 'flyby';
  }

  function ensureScene() {
    if (s3) return;
    s3 = new LS.Scene3D($('cv-route'), { near: 1e-4, far: 1e5 });
    s3.scene.add(new THREE.AmbientLight(0x404a66, 0.3));
    s3.scene.add(new THREE.PointLight(0xfff2dd, 1.7, 0, 0));
    const sun = LS.sun(0.05);
    sun.add(LS.glowSprite(0xffa040, 0.6));
    s3.scene.add(sun);
    for (const name of LS.planetTable.order) {
      const st = LS.planetTable.elements[name];
      const file = name === 'Earth' ? 'earth_day_hd.jpg' : `${name.toLowerCase()}.jpg`;
      const m = new THREE.Mesh(new THREE.SphereGeometry(SIZE[name], 48, 32),
        new THREE.MeshStandardMaterial({ map: LS.texture(`textures/${file}`), roughness: 1 }));
      const pin = new THREE.Sprite(new THREE.SpriteMaterial({ map: LS.spriteTexture(), color: st.color,
        sizeAttenuation: false, depthWrite: false, blending: THREE.AdditiveBlending }));
      pin.scale.set(0.022, 0.022, 1);
      m.add(pin);
      m.userData.label = LS.label(name);
      m.add(m.userData.label);
      m.userData.orbit = LS.line(LS.planetOrbit(name, LS.nowJd()).map((q) => LS.v3(q)), st.color, 0.35);
      s3.scene.add(m, m.userData.orbit);
      bodies[name] = m;
    }
    s3.camera.position.set(2, 6, 9);
    s3.controls.maxDistance = 600;
  }

  R.show = function () {
    ensureScene();
    if (!route && !R.busy) find();
  };
  R.resize = function () {
    if (s3) s3.resize();
    const el = $('ch-route-speed'); if (el.data) Plotly.Plots.resize(el);
  };

  function err(msg) { $('route-err').textContent = msg || ''; $('route-err').hidden = !msg; }

  async function find() {
    err();
    const seq = [$('r-p0').value, $('r-p1').value, $('r-p2').value, $('r-p3').value].filter(Boolean);
    const req = { seq, from: $('r-from').value, to: $('r-to').value, max_years: $('r-max').value,
      capture: $('r-goal').value === 'orbit' };
    R.busy = true;
    try {
      const r = await LS.busy(`Searching ${seq.join(' → ')} routes (a few seconds)…`, $('btn-route'),
        () => LS.api('/api/route', req));
      route = r;
      route.presetInfo = R.preset;
      ensureScene();
      draw();
      chart();
      story();
      $('empty-route').hidden = true;
    } catch (e) { err(e.message); }
    finally { R.busy = false; }
  }

  /* ---------------- 3D ---------------- */

  function draw() {
    if (routeGroup) {
      routeGroup.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.element) o.element.remove(); });
      s3.scene.remove(routeGroup);
    }
    routeGroup = new THREE.Group();
    s3.scene.add(routeGroup);

    const n = route.events.length - 1;                 // legs
    const per = route.track_au.length / n;
    const rmax = Math.max(...route.track_au.map((p) => Math.hypot(p[0], p[1], p[2])));
    for (let k = 0; k < n; k++) {
      const pts = route.track_au.slice(Math.round(k * per), Math.round((k + 1) * per)).map((p) => LS.v3(p));
      routeGroup.add(LS.tube(pts, Math.max(rmax * 0.0022, 0.004), LEG_COLORS[k % 3]));
    }
    if (route.direct) {
      const d = LS.line(route.direct.track_au.map((p) => LS.v3(p)), 0xffffff, 0.35, true);
      d.material.dashSize = rmax * 0.02; d.material.gapSize = rmax * 0.015; d.computeLineDistances();
      routeGroup.add(d);
    }
    // Where each event happens (the spacecraft meets the planet there).
    route.events.forEach((e, k) => {
      const idx = k === 0 ? 0 : Math.min(Math.round(k * per) - 1, route.track_au.length - 1);
      const p = LS.v3(route.track_au[idx]);
      const ring = new THREE.Mesh(new THREE.RingGeometry(rmax * 0.012, rmax * 0.016, 48),
        new THREE.MeshBasicMaterial({ color: e.kind === 'flyby' ? 0x6ee7a8 : 0xffffff, side: THREE.DoubleSide,
          transparent: true, opacity: 0.9, depthWrite: false }));
      ring.position.copy(p);
      ring.lookAt(p.clone().add(new THREE.Vector3(0, 1, 0)));
      routeGroup.add(ring);
      const txt = e.kind === 'launch' ? `Launch · ${e.iso.slice(0, 10)}`
        : e.kind === 'flyby' ? `${e.planet} flyby · ${e.gain >= 0 ? '+' : ''}${LS.fmt(e.gain, 1)} km/s`
          : `Arrival · ${e.iso.slice(0, 10)}`;
      const lb = LS.label(txt, e.kind === 'flyby' ? 'accent' : 'warm');
      lb.position.copy(p);
      routeGroup.add(lb);
    });
    craft = LS.glowSprite(0xffffff, rmax * 0.05);
    craft.add(LS.label('spacecraft', 'dim'));
    routeGroup.add(craft);

    // Show the orbits of every planet out to the destination.
    const used = new Set(route.seq);
    const outer = Math.max(...route.seq.map((p) => LS.planetTable.order.indexOf(p)));
    LS.planetTable.order.forEach((name, i) => {
      const on = i <= outer;
      bodies[name].visible = on;
      bodies[name].userData.orbit.visible = on;
      bodies[name].userData.orbit.material.opacity = used.has(name) ? 0.6 : 0.2;
      // Only name the planets on the route; the others are context.
      bodies[name].userData.label.element.style.display = used.has(name) ? '' : 'none';
    });

    const c = R.clock;
    c.min = -30; c.max = route.tof_days + 60; c.t = -30; c.playing = true;
    c.rate = [5, 15, 30, 60, 120].reduce((b, r) => (Math.abs(r - route.tof_days / 35) < Math.abs(b - route.tof_days / 35) ? r : b), 30);
    s3.controls.target.set(0, 0, 0);
    s3.camera.position.set(rmax * 0.35, rmax * 1.35, rmax * 1.6);
    renderLegend();
    renderHud();
    LS.syncTimebar();
  }

  function renderLegend() {
    const legs = route.events.slice(0, -1).map((e, k) =>
      `<div><i style="background:${LEG_CSS[k % 3]}"></i>Leg ${k + 1}: ${e.planet} → ${route.events[k + 1].planet}</div>`);
    if (route.direct) legs.push('<div><i style="background:#fff;opacity:.5"></i>Direct route, for comparison</div>');
    $('legend-route').innerHTML = legs.join('');
  }

  function renderHud() {
    const f = LS.fmt, d = route.direct;
    let verdict = '';
    if (d) {
      const saved = d.total_dv - route.total_dv;
      verdict = saved > 0.05
        ? `<div class="verdict good">Saves ${f(saved, 2)} km/s</div><p>${f(100 * saved / d.total_dv, 0)}% less Δv than flying direct
            ${route.max_days ? `within the same ${f(route.max_days / 365.25, 1)}-year limit` : ''}.</p>`
        : `<div class="verdict bad">Direct is ${f(-saved, 2)} km/s cheaper</div><p>For these dates the flyby does not pay off —
            see the story below for why.</p>`;
    }
    const years = route.tof_days / 365.25;
    $('hud-route').innerHTML = `
      <div class="box"><h4>${route.seq.join(' → ')}</h4>${verdict}
        ${LS.kv([['Total Δv', `${f(route.total_dv, 3)} km/s`],
                 ['Launch energy C₃', `${f(route.events[0].c3, 1)} km²/s²`],
                 ['Trip time', years >= 1 ? `${f(years, 2)} years` : `${f(route.tof_days, 0)} days`],
                 ['Arrival speed v∞', `${f(route.events[route.events.length - 1].vinf, 2)} km/s`],
                 ...(d ? [['Direct route Δv', `${f(d.total_dv, 3)} km/s`]] : [])])}
        ${route.feasible ? '' : '<p class="hint" style="margin-top:6px">⚠ Some flyby would need more bending than the planet can give.</p>'}
      </div>`;
  }

  /* ---------------- speed chart ---------------- */

  function chart() {
    const t0 = route.jds[0];
    const date = (days) => LS.fmtDate(LS.jdToDate(t0 + days));
    const x = route.t_days.map(date);
    const traces = [
      { x, y: route.escape_speed, name: 'Speed needed to escape the Sun', type: 'scatter', mode: 'lines',
        line: { color: 'rgba(255,107,107,0.8)', width: 1.5, dash: 'dash' } },
      { x, y: route.speed, name: 'Spacecraft speed around the Sun', type: 'scatter', mode: 'lines',
        line: { color: '#5ac8fa', width: 3 } },
    ];
    if (route.direct) {
      const d0 = route.direct.jds[0];
      traces.unshift({ x: route.direct.t_days.map((t) => LS.fmtDate(LS.jdToDate(d0 + t))), y: route.direct.speed,
        name: 'Direct route', type: 'scatter', mode: 'lines', line: { color: 'rgba(255,255,255,0.35)', width: 1.5 } });
    }
    const ann = route.events.filter((e) => e.kind === 'flyby').map((e) => ({
      x: e.iso.slice(0, 10), y: e.v_helio_after, text: `${e.planet} ${e.gain >= 0 ? '+' : ''}${LS.fmt(e.gain, 1)} km/s`,
      showarrow: true, arrowhead: 0, arrowcolor: '#6ee7a8', ax: 0, ay: -26, font: { color: '#6ee7a8', size: 11 },
      bgcolor: 'rgba(12,19,34,0.85)',
    }));
    Plotly.react('ch-route-speed', traces, LS.plotLayout({
      title: { text: 'Speed around the Sun (km/s)', x: 0.02, y: 0.97, font: { size: 13 } },
      margin: { l: 46, r: 16, t: 52, b: 36 }, annotations: ann,
      legend: { orientation: 'h', y: 1.16, x: 0, bgcolor: 'rgba(0,0,0,0)', font: { size: 10.5 } },
      yaxis: { gridcolor: 'rgba(148,170,210,0.12)', color: '#8b9bbd', rangemode: 'tozero' },
      xaxis: { gridcolor: 'rgba(148,170,210,0.12)', color: '#8b9bbd' },
    }), LS.plotConfig);
  }

  /* ---------------- the story, in plain language ---------------- */

  const HOW_SVG = `<svg viewBox="0 0 150 120" width="150" height="120" aria-label="How a gravity assist works">
    <defs><marker id="ah" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7z" fill="#e7edf8"/></marker>
      <marker id="ahg" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7z" fill="#ffb454"/></marker></defs>
    <circle cx="80" cy="62" r="17" fill="#d8a86d"/><circle cx="80" cy="62" r="17" fill="none" stroke="#ffb454" stroke-opacity=".3" stroke-width="10"/>
    <path d="M8,108 C45,70 55,30 80,34 C104,38 112,60 144,50" fill="none" stroke="#5ac8fa" stroke-width="2.4" stroke-dasharray="0" />
    <line x1="18" y1="100" x2="34" y2="84" stroke="#e7edf8" stroke-width="1.6" marker-end="url(#ah)"/>
    <line x1="118" y1="56" x2="140" y2="50" stroke="#e7edf8" stroke-width="1.6" marker-end="url(#ah)"/>
    <line x1="80" y1="92" x2="112" y2="92" stroke="#ffb454" stroke-width="2" marker-end="url(#ahg)"/>
    <text x="96" y="106" fill="#ffb454" font-size="9" text-anchor="middle" font-family="Segoe UI">planet's motion</text>
    <text x="10" y="80" fill="#c9d4ea" font-size="9" font-family="Segoe UI">in</text>
    <text x="126" y="42" fill="#c9d4ea" font-size="9" font-family="Segoe UI">out</text></svg>`;

  function story() {
    const f = LS.fmt, ev = route.events, d = (e) => e.iso.slice(0, 10);
    const items = ev.map((e, k) => {
      const color = e.kind === 'flyby' ? '#6ee7a8' : e.kind === 'launch' ? '#5ac8fa' : '#ffb454';
      let text = '';
      if (e.kind === 'launch') {
        text = `The rocket leaves a 200 km parking orbit with <b>${f(e.dv, 2)} km/s</b> of Δv (launch energy
          C₃ = ${f(e.c3, 1)} km²/s²). Adding Earth's own ${f(e.v_planet, 1)} km/s around the Sun, the spacecraft starts
          at <b>${f(e.v_helio_after, 1)} km/s</b> relative to the Sun.`;
      } else if (e.kind === 'flyby') {
        const esc = Math.sqrt(2 * 1.32712440018e11 / (e.r_au * 1.495978707e8));
        const alt = e.altitude > 1e5 ? `${f(e.altitude / 1000, 0)} thousand km` : `${f(e.altitude, 0)} km`;
        const how = e.gain >= 0
          ? `Because ${e.planet} is itself moving at ${f(e.v_planet, 1)} km/s, swinging around it the right way
             <b>adds ${f(e.gain, 2)} km/s</b> to the spacecraft's speed around the Sun (${f(e.v_helio_before, 1)} → ${f(e.v_helio_after, 1)} km/s)
             — without using fuel.`
          : `Here ${e.planet} is used as a <b>brake</b>: passing ahead of it removes ${f(-e.gain, 2)} km/s
             (${f(e.v_helio_before, 1)} → ${f(e.v_helio_after, 1)} km/s), letting the spacecraft fall further in toward the Sun.`;
        const burn = e.dv > 0.01
          ? ` The spacecraft arrives and leaves at different speeds relative to ${e.planet}, so an engine burn of
             <b>${f(e.dv, 2)} km/s</b> is needed at closest approach.`
          : ' No engine burn is needed.';
        const escText = e.v_helio_after > esc
          ? ` The spacecraft is now faster than the ${f(esc, 1)} km/s needed to <b>escape the Sun</b> at this distance.` : '';
        text = `Passing ${alt} above ${e.planet} (${f(e.altitude_radii, 1)} planet radii from its centre), gravity bends the
          path by <b>${f(e.turn_deg, 0)}°</b> (at most ${f(e.max_turn_deg, 0)}° possible here). ${how}${burn}${escText}
          ${e.feasible ? '' : ' <b>⚠ This needs more bending than the planet can provide.</b>'}`;
      } else {
        const yrs = (e.jd - ev[0].jd) / 365.25;
        text = `After ${yrs >= 1 ? `${f(yrs, 1)} years` : `${f(e.jd - ev[0].jd, 0)} days`}, the spacecraft reaches ${e.planet}
          at <b>${f(e.vinf, 2)} km/s</b> relative to it. ${e.capture_dv !== null
            ? `Entering orbit takes a braking burn of <b>${f(e.capture_dv, 2)} km/s</b>.`
            : 'It flies past, so no fuel is needed to stop.'}`;
      }
      const title = e.kind === 'launch' ? `Launch from ${e.planet}` : e.kind === 'flyby' ? `${e.planet} gravity assist` : `Arrival at ${e.planet}`;
      return `<div class="ev" style="--c:${color}"><div class="when">${d(e)}</div><div class="what">${title}</div><p>${text}</p></div>`;
    }).join('');

    let lesson = '';
    if (route.direct) {
      const saved = route.direct.total_dv - route.total_dv;
      lesson = saved > 0.05
        ? `<p><b>Why it works:</b> the flybys provide ${f(saved, 2)} km/s that the rocket would otherwise have to deliver.
            On a spacecraft, every extra km/s of Δv costs a large share of the launch mass, so this is often what makes a
            mission possible at all.</p>`
        : `<p><b>Why it doesn't help here:</b> the flyby planet isn't in a useful position for these dates, or it's too small
            to bend the path enough, so the engine has to make up the difference. Flybys only pay off when the planets line up.</p>`;
    }
    const hist = route.presetInfo ? `<p class="hint" style="margin-top:10px"><b>History:</b> ${LS.esc(route.presetInfo.history)}</p>` : '';
    $('route-story').innerHTML = `
      <h4>How a gravity assist works</h4>
      <div class="how">${HOW_SVG}<p>Relative to the planet, the spacecraft leaves as fast as it arrived — gravity only
        <b>turns</b> its direction. But the planet is moving around the Sun, so after the turn the spacecraft carries away
        part of the planet's speed (or gives some to it). The planet slows by an immeasurably small amount.</p></div>
      <h4>This route, step by step</h4>
      <div class="timeline">${items}</div>
      ${lesson}${hist}
      <p class="hint">Found by testing ${route.search.evaluated.toLocaleString()} date combinations in ${f(route.search.seconds, 1)} s ·
        patched-conic model · planet positions: ${route.ephemeris}.</p>`;
  }

  /* ---------------- animation ---------------- */

  const buf = [0, 0, 0];
  R.update = function () {
    if (!s3 || !route) return;
    const jd = route.jds[0] + R.clock.t;
    for (const name of LS.planetTable.order) {
      if (bodies[name].visible) bodies[name].position.copy(LS.v3(LS.planetPos(name, jd, buf)));
    }
    const f = R.clock.t / route.tof_days;
    craft.visible = f >= 0 && f <= 1;
    if (craft.visible) {
      // Locate the time within the sampled track (uniform within each leg).
      const td = route.t_days, n = td.length;
      let lo = 0, hi = n - 1;
      while (hi - lo > 1) { const m = (lo + hi) >> 1; if (td[m] <= R.clock.t) lo = m; else hi = m; }
      const u = Math.min(Math.max((R.clock.t - td[lo]) / ((td[hi] - td[lo]) || 1), 0), 1);
      const a = route.track_au[lo], b = route.track_au[hi];
      craft.position.copy(LS.v3([a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u]));
    }
  };
  R.render = () => s3 && s3.render();
  R.clockLabel = (t) => (route ? LS.fmtDate(LS.jdToDate(route.jds[0] + t)) + (t >= 0 && t <= route.tof_days ? `  ·  day ${Math.floor(t)}` : '') : '—');
  R.onNow = () => { R.clock.t = 0; };
})();
