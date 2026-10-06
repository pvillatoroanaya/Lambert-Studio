/* Gravity-assist routes (Mission tab, second mode). Python (flyby.py)
   finds the cheapest dates; this file draws the route in 3D, charts the
   spacecraft's speed, and tells the story of each flyby in plain words. */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const LEG_CSS = ['#5eb3e6', '#eea55a', '#e3cc6a', '#7fcf9f', '#ea7f7f'];
  const LEG_COLORS = LEG_CSS.map((c) => new THREE.Color(c).getHex());
  const FLYBYS = ['r-f1', 'r-f2', 'r-f3', 'r-f4'];
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
    // Deep-space-burn examples (Juno) are listed with the others but use
    // their own optimiser (dsm.py).
    presets = data.presets.concat((data.dsm_presets || []).map((p) => ({ ...p, dsm: true, seq: ['Earth', p.target] })));
    const opts = (none) => (none ? '<option value="">— none —</option>' : '') +
      data.planets.map((p) => `<option>${p}</option>`).join('');
    $('r-p0').innerHTML = opts(false); $('r-p3').innerHTML = opts(false);
    FLYBYS.forEach((id) => { $(id).innerHTML = opts(true); });
    $('r-presets').innerHTML = presets.map((p, k) => `
      <button class="preset" data-k="${k}"><b>${LS.esc(p.label)}</b><span>${p.from.slice(0, 4)} launch · ${p.dsm ? 'deep-space burn + Earth flyby' : p.capture ? 'enter orbit' : 'fly past'}</span></button>`).join('');
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
    $('r-year').value = new Date().getUTCFullYear();
    $('btn-suggest').addEventListener('click', suggest);

    // #mission/route/<preset key> opens that example directly.
    const wanted = (location.hash.split('/')[2] || '').split('?')[0];
    const k = Math.max(0, presets.findIndex((p) => p.key === wanted));
    applyPreset(presets[k]);
    $('r-presets').querySelectorAll('.preset')[k].classList.add('on');
  };

  /* ---------------- route suggestions ---------------- */

  // How much a year of extra cruise is "worth" when balancing cost and
  // time: longer missions cost more to operate and carry more risk.
  const DV_PER_YEAR = 0.25;
  const years = (d) => d / 365.25;
  const fmtDate = (iso) => new Date(iso + 'T00:00:00Z').toLocaleDateString('en-GB',
    { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });

  async function suggest() {
    err();
    const dep = $('r-p0').value, arr = $('r-p3').value;
    const box = $('r-suggest');
    // While the search runs (a few seconds), show a rotating space fact.
    let tip = Math.floor(Math.random() * LS.routeTips.length);
    const showTip = () => {
      box.innerHTML = `<div class="searching"><div class="spin"></div><div><b>Comparing every route from ${dep} to ${arr}…</b>
        <p>Did you know? ${LS.routeTips[tip++ % LS.routeTips.length]}</p></div></div>`;
    };
    showTip();
    box.hidden = false;
    const timer = setInterval(showTip, 5000);
    try {
      const data = await LS.busy(`Comparing routes from ${dep} to ${arr}…`, $('btn-suggest'),
        () => LS.api('/api/route_suggest', { dep, arr, capture: $('r-goal').value === 'orbit',
          from_year: $('r-year').value, years: $('r-years').value }));
      clearInterval(timer);
      try { await LS.launch.load(); } catch (e) { /* optional */ }
      renderSuggestions(data, dep, arr);
      box.hidden = false;
      box.scrollIntoView({ behavior: 'smooth', block: 'start' });   // results sit below the form
    } catch (e) {
      clearInterval(timer);
      box.hidden = true;
      err(e.message);
    }
  }

  function chain(seq) {
    return seq.map((p) => `<span><i style="background:${LS.planetTable.elements[p].color}"></i>${p}</span>`)
      .join('<span class="arr">→</span>');
  }

  function renderSuggestions(data, dep, arr) {
    const f = LS.fmt;
    // A route that needs a big engine burn during a flyby is not a real
    // gravity assist: leave it out of the recommendations (it is still
    // explained under "Why not the other routes?").
    const maxBurn = (o) => Math.max(0, ...o.flybys.map((fb) => fb.dv));
    const practical = data.options.filter((o) => maxBurn(o) <= 1.0);
    const opts = practical.length ? practical : data.options;
    const score = (o) => o.total_dv + DV_PER_YEAR * years(o.tof_days);
    const byScore = [...opts].sort((a, b) => score(a) - score(b));
    const cheapest = [...opts].sort((a, b) => a.total_dv - b.total_dv)[0];
    const fastest = [...opts].sort((a, b) => a.tof_days - b.tof_days)[0];
    const balanced = byScore[0];
    const direct = opts.filter((o) => o.seq.length === 2).sort((a, b) => a.total_dv - b.total_dv)[0];

    // Cards: the recommendation, then the best of each other route family,
    // then further launch opportunities; at most 2 per family and 6 in total.
    const family = (o) => o.seq.join('-');
    const order = [];
    const perFamily = {};
    const add = (o) => {
      if (!o || order.includes(o) || order.length >= 6 || (perFamily[family(o)] || 0) >= 2) return;
      order.push(o);
      perFamily[family(o)] = (perFamily[family(o)] || 0) + 1;
    };
    add(balanced);
    [cheapest, fastest, direct].forEach(add);
    [...new Set(byScore.map(family))].forEach((fam) => add(byScore.find((o) => family(o) === fam)));
    byScore.forEach(add);
    const why = LS.routeLesson(balanced, { cheapest, fastest, direct, data, mass: mass() });
    const cards = order.map((o, k) => {
      const badges = [];
      if (o === balanced) badges.push('<span class="best">Recommended · best balance</span>');
      if (o === cheapest) badges.push('<span>Cheapest</span>');
      if (o === fastest) badges.push('<span class="fast">Fastest</span>');
      if (o.seq.length === 2) badges.push('<span>Direct</span>');
      const loops = o.legs.some((L) => L.revs) ? ' · includes a loop around the Sun' : '';
      return `<button class="sg-card" data-k="${k}">
        <div class="sg-chain">${chain(o.seq)}</div>
        ${badges.length ? `<div class="sg-badges">${badges.join('')}</div>` : ''}
        <div class="sg-win">Launch window <b>${fmtDate(o.window_iso[0])} – ${fmtDate(o.window_iso[1])}</b>
          (best ${fmtDate(o.iso[0])})${loops}</div>
        <div class="sg-stats"><div>Total Δv<b>${f(o.total_dv, 2)} km/s</b></div>
          <div>Trip time<b>${f(years(o.tof_days), 1)} years</b></div><div>Launch C₃<b>${f(o.c3, 0)} km²/s²</b></div></div>
        ${LS.launch.data ? `<div class="sg-rocket">Rocket for ${f(mass(), 0)} kg: <b>${LS.launch.verdict(o.c3, mass())}</b></div>` : ''}
      </button>`;
    }).join('');
    const whyNot = data.tried.map((t) => {
      const name = t.seq.join(' → ');
      if (!t.found) return `<div><b>${name}:</b> no workable trajectory within ${f(data.max_years, 0)} years in this period.</div>`;
      if (t.max_burn > 1.0) {
        return `<div><b>${name}:</b> needs a ${f(t.max_burn, 1)} km/s engine burn during a flyby — the planet cannot bend the path enough for free.</div>`;
      }
      const extra = t.best_dv - balanced.total_dv;
      return extra > 0.05
        ? `<div><b>${name}:</b> best ${f(t.best_dv, 2)} km/s, ${f(extra, 2)} km/s more than the recommendation${t.tof_days ? `, ${f(years(t.tof_days), 1)} years` : ''}.</div>`
        : '';
    }).join('');
    $('r-suggest').innerHTML = `${why}${cards}
      <details class="advanced"><summary>Why not the other routes?</summary><div class="whynot">${whyNot || 'All route families are shown above.'}</div></details>
      <p class="hint">Searched ${data.tried.length} route families from ${fmtDate(data.start_iso)} for ${f(data.years, 0)} years,
        with trips of up to ${f(data.max_years, 0)} years (typical for ${arr}), in ${f(data.seconds, 0)} s.
        “Best balance” weighs each extra year of travel as ${DV_PER_YEAR} km/s. Click a route to load it and play it.</p>`;
    $('r-suggest').querySelectorAll('.sg-card').forEach((b) => b.addEventListener('click', () => {
      $('r-suggest').querySelectorAll('.sg-card').forEach((x) => x.classList.toggle('on', x === b));
      applyOption(order[+b.dataset.k], data);
    }));
  }

  /* Load a suggestion into the builder (with a launch window a little
     wider than recommended, so the optimiser has room) and play it. */
  function applyOption(o, data) {
    const pad = 10;
    const shift = (iso, d) => LS.fmtDate(new Date(new Date(iso + 'T00:00:00Z').getTime() + d * 86400000));
    $('r-p0').value = o.seq[0];
    $('r-p3').value = o.seq[o.seq.length - 1];
    FLYBYS.forEach((id, k) => { $(id).value = k + 1 < o.seq.length - 1 ? o.seq[k + 1] : ''; });
    $('r-from').value = shift(o.window_iso[0], -pad);
    $('r-to').value = shift(o.window_iso[1], pad);
    $('r-max').value = (Math.ceil(years(o.tof_days) * 1.1 * 10) / 10).toFixed(1);
    $('r-advanced').open = true;
    R.preset = { label: `Suggested: ${o.seq.join(' → ')}`, history:
      `Recommended by the route search: launch window ${fmtDate(o.window_iso[0])} – ${fmtDate(o.window_iso[1])}, ` +
      `${LS.fmt(o.total_dv, 2)} km/s, ${LS.fmt(years(o.tof_days), 1)} years.` };
    $('r-presets').querySelectorAll('.preset').forEach((x) => x.classList.remove('on'));
    find(true);
  }

  function applyPreset(p) {
    R.preset = p;
    const s = p.seq;
    $('r-p0').value = s[0];
    $('r-p3').value = s[s.length - 1];
    FLYBYS.forEach((id, k) => { $(id).value = k + 1 < s.length - 1 ? s[k + 1] : ''; });
    $('r-from').value = p.from; $('r-to').value = p.to;
    $('r-max').value = p.max_years;
    $('r-goal').value = p.capture ? 'orbit' : 'flyby';
  }

  const orbitPoints = (name) => LS.planetOrbit(name, LS.nowJd()).map((q) => LS.sv3(q));

  function ensureScene() {
    if (s3) return;
    s3 = new LS.Scene3D($('cv-route'), { near: 1e-4, far: 1e5 });
    s3.scene.add(new THREE.AmbientLight(0x404a66, 0.2));
    s3.scene.add(new THREE.PointLight(0xfff2dd, 1.05, 0, 0));
    const sun = LS.sun(0.05);
    sun.add(LS.glowSprite(0xffa040, 0.6));
    s3.scene.add(sun);
    for (const name of LS.planetTable.order) {
      const st = LS.planetTable.elements[name];
      const file = name === 'Earth' ? 'earth_day_hd.jpg' : `${name.toLowerCase()}.jpg`;
      const m = new THREE.Mesh(new THREE.SphereGeometry(SIZE[name], 96, 64),
        LS.planetMaterial(name, file));
      const pin = new THREE.Sprite(new THREE.SpriteMaterial({ map: LS.spriteTexture(), color: st.color,
        sizeAttenuation: false, depthWrite: false, blending: THREE.AdditiveBlending }));
      pin.scale.set(0.022, 0.022, 1);
      m.add(pin);
      m.userData.label = LS.label(name, name === 'Earth' ? 'key' : '');
      m.add(m.userData.label);
      m.userData.orbit = LS.line(orbitPoints(name), st.color, 0.35);
      s3.scene.add(m, m.userData.orbit);
      bodies[name] = m;
    }
    // Switching between compressed and true-scale distances redraws everything.
    LS.on('scale', () => {
      LS.planetTable.order.forEach((n) => bodies[n].userData.orbit.geometry.setFromPoints(orbitPoints(n)));
      if (route) draw();
    });
    s3.camera.position.set(2, 6, 9);
    s3.controls.maxDistance = 600;
    s3.setFollowables([
      { label: 'Spacecraft', obj: () => (craft && craft.visible ? craft : null) },
      { label: 'Sun', obj: () => sun },
      ...LS.planetTable.order.map((n) => ({ label: n, obj: () => (bodies[n].visible ? bodies[n] : null) })),
    ]);
  }

  R.show = function () {
    ensureScene();
    if (!route && !R.busy) find(false);          // automatic first example: no auto-play
  };
  R.resize = function () {
    if (s3) s3.resize();
    const el = $('ch-route-speed'); if (el.data) Plotly.Plots.resize(el);
  };

  function err(msg) {
    $('route-err').textContent = msg || '';
    $('route-err').hidden = !msg;
    // Also show it in the middle of the view, where it can't be missed.
    if (msg) {
      $('empty-route').innerHTML = `<div><b>No route to show</b><br>${LS.esc(msg)}</div>`;
      $('empty-route').hidden = false;
    }
  }

  async function find(play = true) {
    err();
    const seq = [$('r-p0').value, ...FLYBYS.map((id) => $(id).value), $('r-p3').value].filter(Boolean);
    const dsmRoute = R.preset && R.preset.dsm;
    const req = dsmRoute
      ? { target: R.preset.target, from: $('r-from').value, to: $('r-to').value, max_years: $('r-max').value,
          capture: $('r-goal').value === 'orbit' }
      : { seq, from: $('r-from').value, to: $('r-to').value, max_years: $('r-max').value,
          capture: $('r-goal').value === 'orbit' };
    R.busy = true;
    const wait = seq.length >= 5 ? 'up to ~30 s' : 'a few seconds';
    try {
      const r = dsmRoute
        ? await LS.busy('Optimising launch, deep-space burn and Earth flyby (~10 s)…', $('btn-route'),
          () => LS.api('/api/route_dsm', req))
        : await LS.busy(`Searching ${seq.join(' → ')} routes (${wait})…`, $('btn-route'),
          () => LS.api('/api/route', req));
      route = r;
      route.presetInfo = R.preset;
      try { await LS.launch.load(); } catch (e) { /* rocket table is optional */ }
      LS.lastRoute = r;
      LS.emit('route', r);
      ensureScene();
      draw();
      chart();
      story();
      $('empty-route').hidden = true;
      // Open the full-screen playback straight away (unless an automated
      // screenshot asked for the analysis view with #...?noplay).
      if (play && !location.hash.includes('noplay')) R.play();
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

    // Each leg is its own slice of the track (a leg that loops around the
    // Sun has more samples than one that doesn't).
    const rmax = Math.max(...route.track_au.map((p) => LS.sv3(p).length()));
    route.legs.forEach((L, k) => {
      const pts = route.track_au.slice(L.start, L.end).map((p) => LS.sv3(p));
      routeGroup.add(LS.tube(pts, Math.max(rmax * 0.0022, 0.004), LEG_COLORS[k % LEG_COLORS.length]));
    });
    if (route.direct) {
      const d = LS.line(route.direct.track_au.map((p) => LS.sv3(p)), 0xffffff, 0.35, true);
      d.material.dashSize = rmax * 0.02; d.material.gapSize = rmax * 0.015; d.computeLineDistances();
      routeGroup.add(d);
    }
    // Where each event happens (the spacecraft meets the planet there).
    route.events.forEach((e, k) => {
      const idx = k === 0 ? 0 : route.legs[k - 1].end - 1;
      const p = LS.sv3(route.track_au[idx]);
      const ring = new THREE.Mesh(new THREE.RingGeometry(rmax * 0.012, rmax * 0.016, 48),
        new THREE.MeshBasicMaterial({ color: e.kind === 'flyby' ? 0x7fcf9f : e.kind === 'dsm' ? 0xe56f6f : 0xffffff, side: THREE.DoubleSide,
          transparent: true, opacity: 0.9, depthWrite: false }));
      ring.position.copy(p);
      ring.lookAt(p.clone().add(new THREE.Vector3(0, 1, 0)));
      routeGroup.add(ring);
      const txt = e.kind === 'launch' ? `Launch · ${e.iso.slice(0, 10)}`
        : e.kind === 'flyby' ? `${e.planet} flyby · ${e.gain >= 0 ? '+' : ''}${LS.fmt(e.gain, 1)} km/s`
          : e.kind === 'dsm' ? `Deep-space burn · ${LS.fmt(e.dv, 2)} km/s`
            : `Arrival · ${e.iso.slice(0, 10)}`;
      const lb = LS.label(txt, e.kind === 'flyby' ? 'accent' : 'warm');
      if (e.kind === 'dsm') lb.element.firstChild.style.color = '#ea7f7f';
      lb.position.copy(p);
      routeGroup.add(lb);
    });
    craft = LS.spacecraft(rmax * 0.012, { label: 'spacecraft' });
    routeGroup.add(craft);

    // All eight planets are always shown; the ones on the route are brighter.
    const used = new Set(route.seq);
    LS.planetTable.order.forEach((name) => {
      bodies[name].visible = true;
      bodies[name].userData.orbit.visible = true;
      bodies[name].userData.orbit.material.opacity = used.has(name) ? 0.65 : 0.22;
      bodies[name].userData.label.userData.hide = false;
      bodies[name].userData.label.element.firstChild.className = 'lbl ' + (used.has(name) ? '' : 'dim');
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
    const legs = route.legs.map((L, k) =>
      `<div><i style="background:${LEG_CSS[k % LEG_CSS.length]}"></i>Leg ${k + 1}: ${L.from} → ${L.to}` +
      `${L.revs ? ` <span class="muted">(+${L.revs} loop)</span>` : ''}</div>`);
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
        <button class="play-mission" id="route-play">▶ Play mission</button>
        ${route.dsm ? '' : '<button class="ghost wide" id="route-nbody" style="margin-top:8px">Check in full solar-system gravity</button>'}
      </div>
      <div id="route-nbody-box"></div>
      ${LS.launch.data ? `<div class="box"><h4>Which rocket? <small>for ${f(mass(), 0)} kg</small></h4>
        ${LS.launch.table(route.events[0].c3, mass())}</div>` : ''}`;
    $('route-play').onclick = R.play;
    if ($('route-nbody')) $('route-nbody').onclick = verifyRoute;
  }

  const mass = () => Math.max(+$('r-mass').value || 2000, 1);

  /* Fly the designed route again in full solar-system gravity (nbody.py). */
  let nbodyLine = null;
  async function verifyRoute() {
    err();
    const r = route;
    try {
      const v = await LS.nbody.run({ seq: r.seq, jds: r.jds, capture: r.capture,
        legs: r.legs.map((L) => ({ revs: L.revs, branch: L.branch })) }, $('route-nbody'));
      if (r !== route) return;                      // a new route was loaded meanwhile
      r.nbody = v;
      $('route-nbody-box').innerHTML = LS.nbody.html(v);
      if (nbodyLine) routeGroup.remove(nbodyLine);
      nbodyLine = LS.line(v.track_au.map((p) => LS.sv3(p)), 0x7fcf9f, 0.95);
      routeGroup.add(nbodyLine);
      $('route-story').insertAdjacentHTML('beforeend', LS.nbody.story(v));
      $('route-nbody').textContent = '✓ Checked in full solar-system gravity';
      LS.emit('nbody', v);
    } catch (e) { err(e.message); }
  }

  R.play = () => { if (route) LS.player.open(LS.player.fromRoute(route, route.presetInfo)); };

  /* ---------------- speed chart ---------------- */

  function chart() {
    const t0 = route.jds[0];
    const date = (days) => LS.fmtDate(LS.jdToDate(t0 + days));
    const x = route.t_days.map(date);
    const traces = [
      { x, y: route.escape_speed, name: 'Solar escape speed', type: 'scatter', mode: 'lines',
        line: { color: 'rgba(229,111,111,0.8)', width: 1.5, dash: 'dash' } },
      { x, y: route.speed, name: 'Spacecraft', type: 'scatter', mode: 'lines',
        line: { color: '#5eb3e6', width: 3 } },
    ];
    if (route.direct) {
      const d0 = route.direct.jds[0];
      traces.unshift({ x: route.direct.t_days.map((t) => LS.fmtDate(LS.jdToDate(d0 + t))), y: route.direct.speed,
        name: 'Direct route', type: 'scatter', mode: 'lines', line: { color: 'rgba(255,255,255,0.35)', width: 1.5 } });
    }
    const ann = route.events.filter((e) => e.kind === 'flyby' || e.kind === 'dsm').map((e, k) => ({
      x: e.iso.slice(0, 10), y: e.v_helio_after,
      text: e.kind === 'dsm' ? `burn ${LS.fmt(e.dv, 2)} km/s` : `${e.planet} ${e.gain >= 0 ? '+' : ''}${LS.fmt(e.gain, 1)} km/s`,
      showarrow: true, arrowhead: 0, arrowcolor: '#7fcf9f', ax: 0, ay: k % 2 ? -44 : -24, font: { color: '#7fcf9f', size: 11 },
      bgcolor: 'rgba(12,19,34,0.85)',
    }));
    Plotly.react('ch-route-speed', traces, LS.plotLayout({
      title: { text: 'Speed around the Sun (km/s)', x: 0.02, y: 0.975, font: { size: 13 } },
      margin: { l: 46, r: 16, t: 60, b: 36 }, annotations: ann,
      yaxis: { gridcolor: 'rgba(255,255,255,0.06)', color: '#8d95a8', rangemode: 'tozero' },
      xaxis: { gridcolor: 'rgba(255,255,255,0.06)', color: '#8d95a8' },
    }), LS.plotConfig);
  }

  /* ---------------- the story, in plain language ---------------- */

  const HOW_SVG = `<svg viewBox="0 0 150 120" width="150" height="120" aria-label="How a gravity assist works">
    <defs><marker id="ah" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7z" fill="#e9ecf3"/></marker>
      <marker id="ahg" markerWidth="7" markerHeight="7" refX="5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7z" fill="#eea55a"/></marker></defs>
    <circle cx="80" cy="62" r="17" fill="#d8a86d"/><circle cx="80" cy="62" r="17" fill="none" stroke="#eea55a" stroke-opacity=".3" stroke-width="10"/>
    <path d="M8,108 C45,70 55,30 80,34 C104,38 112,60 144,50" fill="none" stroke="#5eb3e6" stroke-width="2.4" stroke-dasharray="0" />
    <line x1="18" y1="100" x2="34" y2="84" stroke="#e9ecf3" stroke-width="1.6" marker-end="url(#ah)"/>
    <line x1="118" y1="56" x2="140" y2="50" stroke="#e9ecf3" stroke-width="1.6" marker-end="url(#ah)"/>
    <line x1="80" y1="92" x2="112" y2="92" stroke="#eea55a" stroke-width="2" marker-end="url(#ahg)"/>
    <text x="96" y="106" fill="#eea55a" font-size="9" text-anchor="middle" font-family="Segoe UI">planet's motion</text>
    <text x="10" y="80" fill="#c9d4ea" font-size="9" font-family="Segoe UI">in</text>
    <text x="126" y="42" fill="#c9d4ea" font-size="9" font-family="Segoe UI">out</text></svg>`;

  /* One line for the cruise between two events; longer when it loops. */
  function cruise(L, k) {
    const f = LS.fmt, days = `${f(L.days, 0)} days`;
    const loops = L.revs === 1 ? 'once' : `${L.revs} times`;
    let text;
    if (L.same_planet) {
      text = `The flyby put the spacecraft on an orbit around the Sun that takes ${f(L.period_days, 0)} days.
        ${L.revs ? `It loops ${loops} around the Sun and` : 'It'} comes back to ${L.to} ${days} later, so ${L.to}'s gravity
        can be used a <b>second time</b>. This is the trick that let Galileo reach Jupiter.`;
    } else if (L.revs) {
      text = `On the way, the spacecraft loops ${loops} fully around the Sun before meeting ${L.to} (${days}).
        For a looping trip, Lambert's problem has two solutions; the cheaper one was chosen.`;
    } else if (L.to === 'deep-space burn') {
      text = `The spacecraft coasts outward on a loop that reaches beyond Mars' orbit (${days}).`;
    } else if (L.from === 'deep-space burn') {
      text = `After the burn it falls back toward the Sun and meets Earth again (${days}).`;
    } else {
      text = `Cruise to ${L.to}: ${days}.`;
    }
    return `<div class="ev leg" style="--c:${LEG_CSS[k % LEG_CSS.length]}"><div class="when">Leg ${k + 1}</div><p>${text}</p></div>`;
  }

  function story() {
    const f = LS.fmt, ev = route.events, d = (e) => e.iso.slice(0, 10);
    const items = ev.map((e, k) => {
      const color = e.kind === 'flyby' ? '#7fcf9f' : e.kind === 'launch' ? '#5eb3e6' : e.kind === 'dsm' ? '#ea7f7f' : '#eea55a';
      let text = '';
      if (e.kind === 'dsm') {
        text = `Far from any planet (${f(e.r_au, 2)} AU from the Sun, beyond Mars' orbit), the main engine fires for
          <b>${f(e.dv, 2)} km/s</b>. The spacecraft is moving slowly out here, near the far end of its loop, so a modest burn
          changes the shape of its orbit a lot: it re-aims the spacecraft to come back past Earth much faster than it left.
          Earth's gravity then turns that speed toward the destination. This is a <b>ΔV-EGA</b> ("delta-V Earth gravity
          assist"): a small engine burn plus a flyby replaces a much bigger rocket.`;
      } else if (e.kind === 'launch') {
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
      const again = e.kind === 'flyby' && k >= 2 && ev[k - 1].planet === e.planet;
      const title = e.kind === 'launch' ? `Launch from ${e.planet}`
        : e.kind === 'flyby' ? `${e.planet} gravity assist${again ? ' (second pass)' : ''}`
          : e.kind === 'dsm' ? 'Deep-space burn' : `Arrival at ${e.planet}`;
      const event = `<div class="ev" style="--c:${color}"><div class="when">${d(e)}</div><div class="what">${title}</div><p>${text}</p></div>`;
      return event + (k < route.legs.length ? cruise(route.legs[k], k) : '');
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
      <p class="hint">Found by testing ${route.search.evaluated.toLocaleString('en-US')} date combinations in ${f(route.search.seconds, 1)} s ·
        patched-conic model · planet positions: ${route.ephemeris}.</p>`;
  }

  /* ---------------- animation ---------------- */

  const buf = [0, 0, 0];
  R.update = function () {
    if (!s3 || !route) return;
    const jd = route.jds[0] + R.clock.t;
    for (const name of LS.planetTable.order) {
      bodies[name].position.copy(LS.sv3(LS.planetPos(name, jd, buf)));
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
      craft.position.copy(LS.sv3([a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u]));
      LS.aimCraft(craft, LS.sv3(route.track_au[Math.min(hi + 1, n - 1)]));
    }
  };
  R.render = () => s3 && s3.render();
  R.clockLabel = (t) => (route ? LS.fmtDate(LS.jdToDate(route.jds[0] + t)) + (t >= 0 && t <= route.tof_days ? `  ·  day ${Math.floor(t)}` : '') : '—');
  R.onNow = () => { R.clock.t = 0; };
})();
