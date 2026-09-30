/* Full-screen mission playback.

   LS.player.open(mission) takes a mission in a common form, built from
   either a gravity-assist route or a direct transfer (see fromRoute and
   fromTransfer below):

     { title, subtitle, seq, jd0, tof, track_au, t_days, legs:[{start,end,from,to}],
       events:[{kind:'launch'|'flyby'|'arrival', planet, jd, ...details}] }

   and plays it: the spacecraft flies the route among the real planets,
   the camera follows it and swings to each planet as it is reached, time
   slows down around each event, and a card explains what happens. */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const LEG_CSS = ['#5ac8fa', '#ffb454', '#c792ea', '#6ee7a8', '#ff8a80'];
  const EVENT_CSS = { launch: '#5ac8fa', flyby: '#6ee7a8', arrival: '#ffb454', dsm: '#ff8a80' };
  const SIZE = { Mercury: 0.03, Venus: 0.045, Earth: 0.048, Mars: 0.036,
    Jupiter: 0.2, Saturn: 0.17, Uranus: 0.11, Neptune: 0.11 };
  const AU_KM = 1.495978707e8;

  const P = { isOpen: false };
  LS.player = P;

  let s3 = null, bodies = {}, sun = null, group = null, craft = null, trail = null;
  let M = null;                         // the mission being played
  let t = 0, rate = 1, baseRate = 1, playing = true, camMode = 'auto';
  let rmax = 1, lastFocus = null, shownEvent = -1, eventTimer = 0, teleTimer = 0;

  /* ---------------- building a mission from the app's results ---------------- */

  P.fromRoute = function (r, info) {
    return {
      title: r.seq.join(' → '),
      subtitle: info && info.label ? info.label : 'Gravity-assist route',
      seq: r.seq, jd0: r.jds[0], tof: r.tof_days,
      track_au: r.track_au, t_days: r.t_days, legs: r.legs, events: r.events,
      total_dv: r.total_dv, direct_dv: r.direct ? r.direct.total_dv : null,
    };
  };

  P.fromTransfer = function (tr) {
    const n = tr.track_au.length;
    const t_days = tr.track_au.map((_, k) => (tr.tof_days * k) / (n - 1));
    return {
      title: `${tr.departure} → ${tr.arrival}`,
      subtitle: `Direct transfer · ${tr.type}`,
      seq: [tr.departure, tr.arrival], jd0: tr.jd_departure, tof: tr.tof_days,
      track_au: tr.track_au, t_days,
      legs: [{ start: 0, end: n, from: tr.departure, to: tr.arrival, revs: 0 }],
      events: [
        { kind: 'launch', planet: tr.departure, jd: tr.jd_departure, c3: tr.c3, dv: tr.dv_departure,
          vinf: tr.vinf_departure },
        { kind: 'arrival', planet: tr.arrival, jd: tr.jd_arrival, vinf: tr.vinf_arrival, capture_dv: tr.dv_arrival },
      ],
      total_dv: tr.dv_departure + tr.dv_arrival, direct_dv: null,
    };
  };

  /* ---------------- the 3D scene (built once) ---------------- */

  function ensureScene() {
    if (s3) return;
    s3 = new LS.Scene3D($('cv-player'), { near: 1e-4, far: 1e5 });
    s3.scene.add(new THREE.AmbientLight(0x404a66, 0.3));
    s3.scene.add(new THREE.PointLight(0xfff2dd, 1.15, 0, 0));   // softer: planets drawn larger here
    sun = LS.sun(0.08);
    sun.add(LS.glowSprite(0xffa040, 0.9));
    sun.add(LS.label('Sun', 'warm'));
    s3.scene.add(sun);
    for (const name of LS.planetTable.order) {
      const st = LS.planetTable.elements[name];
      const file = name === 'Earth' ? 'earth_day_hd.jpg' : `${name.toLowerCase()}.jpg`;
      const m = new THREE.Mesh(new THREE.SphereGeometry(SIZE[name], 64, 48),
        new THREE.MeshStandardMaterial({ map: LS.texture(`textures/${file}`), roughness: 1 }));
      if (name === 'Saturn') {
        const inner = SIZE.Saturn * 1.24, outer = SIZE.Saturn * 2.27;
        const g = new THREE.RingGeometry(inner, outer, 160, 1);
        const pos = g.attributes.position, uv = g.attributes.uv, v = new THREE.Vector3();
        for (let k = 0; k < pos.count; k++) { v.fromBufferAttribute(pos, k); uv.setXY(k, (v.length() - inner) / (outer - inner), 0.5); }
        const ring = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ map: LS.texture('textures/saturn_ring.png'),
          side: THREE.DoubleSide, transparent: true, depthWrite: false }));
        ring.rotation.x = Math.PI / 2 - 0.47;
        m.add(ring);
      }
      const pin = new THREE.Sprite(new THREE.SpriteMaterial({ map: LS.spriteTexture(), color: st.color,
        sizeAttenuation: false, depthWrite: false, blending: THREE.AdditiveBlending }));
      pin.scale.set(0.02, 0.02, 1);
      m.add(pin);
      m.userData.label = LS.label(name);
      m.add(m.userData.label);
      m.userData.orbit = LS.line(orbitPoints(name), st.color, 0.3);
      s3.scene.add(m, m.userData.orbit);
      bodies[name] = m;
    }
    s3.setFollowables([
      { label: 'Spacecraft', obj: () => craft },
      { label: 'Sun', obj: () => sun },
      ...LS.planetTable.order.map((n) => ({ label: n, obj: () => bodies[n] })),
    ]);
    LS.on('scale', () => {
      LS.planetTable.order.forEach((n) => bodies[n].userData.orbit.geometry.setFromPoints(orbitPoints(n)));
      if (M) buildRoute();
    });
    wire();
  }

  const orbitPoints = (name) => LS.planetOrbit(name, M ? M.jd0 : LS.nowJd()).map((q) => LS.sv3(q));

  function wire() {
    $('p-close').addEventListener('click', P.close);
    $('p-play').addEventListener('click', () => { playing = !playing; });
    $('p-rate').addEventListener('change', () => { baseRate = +$('p-rate').value; });
    document.querySelectorAll('#p-cam button').forEach((b) => b.addEventListener('click', () => setCam(b.dataset.c)));
    window.addEventListener('keydown', (e) => {
      if (!P.isOpen || LS.flybyCloseup.active || (e.target.matches && e.target.matches('input, select, textarea'))) return;
      if (e.code === 'Escape' && s3.mode !== 'fly') { P.close(); e.stopPropagation(); }
      if (e.code === 'Space') { playing = !playing; e.preventDefault(); e.stopPropagation(); }
    }, true);
    const tl = $('p-timeline');
    const seek = (e) => {
      const r = tl.getBoundingClientRect();
      t = tMin() + Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1) * (tMax() - tMin());
      shownEvent = M.eventT.filter((te) => te <= t).length - 1;
      lastFocus = null;
      $('p-event').hidden = true;
    };
    let dragging = false;
    tl.addEventListener('pointerdown', (e) => { if (e.target.closest('.p-mark')) return; dragging = true; seek(e); });
    window.addEventListener('pointermove', (e) => { if (dragging) seek(e); });
    window.addEventListener('pointerup', () => { dragging = false; });
  }

  const tMin = () => -15;
  const tMax = () => M.tof + 30;

  /* ---------------- opening a mission ---------------- */

  P.open = async function (mission) {
    await LS.loadPlanets();
    M = mission;
    // Speed along the path, from the sampled positions (works for every mission type).
    M.speed = M.track_au.map((_, k) => {
      const a = Math.max(0, k - 1), b = Math.min(M.track_au.length - 1, k + 1);
      const dt = (M.t_days[b] - M.t_days[a]) * 86400;
      if (dt <= 0) return null;
      const p = M.track_au[a], q = M.track_au[b];
      return Math.hypot(q[0] - p[0], q[1] - p[1], q[2] - p[2]) * AU_KM / dt;
    });
    for (let k = 0; k < M.speed.length; k++) if (M.speed[k] === null) M.speed[k] = M.speed[k - 1] || M.speed[k + 1] || 0;
    M.eventT = M.events.map((e) => e.jd - M.jd0);

    $('player').hidden = false;
    P.isOpen = true;
    ensureScene();
    s3.resize();
    LS.planetTable.order.forEach((n) => bodies[n].userData.orbit.geometry.setFromPoints(orbitPoints(n)));
    buildRoute();

    $('p-title').textContent = M.title;
    $('p-sub').textContent = `${M.subtitle} · launch ${LS.fmtDate(LS.jdToDate(M.jd0))} · ` +
      `${M.tof >= 365 ? `${LS.fmt(M.tof / 365.25, 1)} years` : `${LS.fmt(M.tof, 0)} days`} · Δv ${LS.fmt(M.total_dv, 2)} km/s`;

    // A whole mission plays in about a minute at normal speed.
    const base = Math.max(M.tof / 60, 1);
    $('p-rate').innerHTML = [[0.25, 'Slow'], [0.5, '½×'], [1, 'Normal'], [2, '2×'], [4, '4×']]
      .map(([k, l]) => `<option value="${base * k}">${l} · ${LS.fmt(base * k, 0)} days/s</option>`).join('');
    $('p-rate').value = String(base);
    baseRate = base;
    buildTimeline();

    t = tMin();
    playing = true;
    shownEvent = -1;
    lastFocus = null;
    $('p-event').hidden = true;
    setCam('auto');
    s3.controls.target.set(0, 0, 0);
    s3.camera.position.set(rmax * 0.5, rmax * 1.3, rmax * 1.9);
    s3.focusOn(new THREE.Vector3(), s3.camera.position.length());
  };

  P.close = function () {
    LS.flybyCloseup.stop();
    $('player').hidden = true;
    P.isOpen = false;
    if (s3) { s3.setMode('orbit'); s3.keys.clear(); }
  };

  function buildRoute() {
    if (group) {
      group.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.element) o.element.remove(); });
      s3.scene.remove(group);
    }
    group = new THREE.Group();
    s3.scene.add(group);
    const pts = M.track_au.map((p) => LS.sv3(p));
    rmax = Math.max(...pts.map((p) => p.length()), 1.2);

    // The planned route, faint, one colour per leg.
    M.legs.forEach((L, k) => {
      group.add(LS.tube(pts.slice(L.start, L.end), rmax * 0.0016, new THREE.Color(LEG_CSS[k % LEG_CSS.length]).getHex(), false, 0.28));
    });
    // The part already flown: a bright trail that grows with time.
    const g = new THREE.BufferGeometry().setFromPoints(pts);
    const col = new Float32Array(pts.length * 3);
    M.legs.forEach((L, k) => {
      const c = new THREE.Color(LEG_CSS[k % LEG_CSS.length]);
      for (let i = L.start; i < L.end; i++) col.set([c.r, c.g, c.b], 3 * i);
    });
    g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    trail = new THREE.Points(g, new THREE.PointsMaterial({ size: 3.2, sizeAttenuation: false, vertexColors: true,
      map: LS.spriteTexture(), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    trail.userData.noPick = true;
    trail.geometry.setDrawRange(0, 0);
    group.add(trail);

    // Event markers where the spacecraft meets each planet.
    M.events.forEach((e, k) => {
      const idx = k === 0 ? 0 : M.legs[Math.min(k, M.legs.length) - 1].end - 1;
      const p = pts[idx];
      const ring = new THREE.Mesh(new THREE.RingGeometry(rmax * 0.01, rmax * 0.014, 48),
        new THREE.MeshBasicMaterial({ color: new THREE.Color(EVENT_CSS[e.kind]).getHex(), side: THREE.DoubleSide,
          transparent: true, opacity: 0.85, depthWrite: false }));
      ring.position.copy(p);
      ring.lookAt(p.clone().add(new THREE.Vector3(0, 1, 0)));
      ring.userData.noPick = true;
      group.add(ring);
    });

    craft = LS.spacecraft(rmax * 0.012, { label: 'spacecraft' });
    group.add(craft);

    const used = new Set(M.seq);
    LS.planetTable.order.forEach((n) => {
      bodies[n].userData.orbit.material.opacity = used.has(n) ? 0.6 : 0.2;
      bodies[n].userData.label.element.firstChild.className = 'lbl ' + (used.has(n) ? '' : 'dim');
    });
  }

  function buildTimeline() {
    const tl = $('p-timeline');
    tl.querySelectorAll('.p-mark').forEach((m) => m.remove());
    let lastX = -100, below = false;
    M.events.forEach((e, k) => {
      const x = (M.eventT[k] - tMin()) / (tMax() - tMin()) * 100;
      const m = document.createElement('div');
      // Labels of events close together alternate above / below the line.
      below = x - lastX < 7 ? !below : false;
      lastX = x;
      m.className = 'p-mark' + (below ? ' below' : '');
      m.style.left = `${x}%`;
      m.style.setProperty('--c', EVENT_CSS[e.kind]);
      m.title = `${eventTitle(e)} · ${LS.fmtDate(LS.jdToDate(e.jd))}`;
      m.innerHTML = `<span>${e.kind === 'launch' ? 'Launch' : e.kind === 'dsm' ? 'Burn' : e.planet}</span>`;
      m.addEventListener('click', () => {
        t = M.eventT[k] - Math.max(M.tof * 0.03, 8);    // arrive just before it
        shownEvent = k - 1;
        lastFocus = null;
        playing = true;
        $('p-event').hidden = true;
      });
      tl.appendChild(m);
    });
  }

  /* ---------------- camera ---------------- */

  function setCam(mode) {
    camMode = mode;
    lastFocus = null;
    document.querySelectorAll('#p-cam button').forEach((b) => b.classList.toggle('on', b.dataset.c === mode));
    if (mode === 'overview') {
      s3.setFollow(null);
      // The whole solar system, not just the route (so Neptune is in view too).
      s3.flyTo(new THREE.Vector3(), Math.max(rmax, LS.settings.compress ? 5.6 : rmax) * 2.3);
    }
    if (mode === 'free') s3.setFollow(null);
  }

  const eventWindow = () => Math.max(M.tof * 0.025, 10);        // days either side of an event

  function nearEvent() {
    let best = -1, bd = Infinity;
    M.eventT.forEach((te, k) => {
      const d = Math.abs(t - te);
      if (d < eventWindow() && d < bd && M.events[k].kind !== 'launch') { best = k; bd = d; }
    });
    return best;
  }

  function updateCamera() {
    if (camMode === 'overview' || camMode === 'free') return;
    let want = 'craft';
    if (camMode === 'auto') {
      const k = nearEvent();
      if (k >= 0 && bodies[M.events[k].planet]) want = M.events[k].planet;     // (a deep-space burn has no planet)
    }
    if (want === lastFocus) return;
    lastFocus = want;
    const obj = want === 'craft' ? craft : bodies[want];
    const item = s3.followables.find((f) => f.label === (want === 'craft' ? 'Spacecraft' : want));
    s3.setFollow(item);
    const dist = want === 'craft' ? rmax * 0.55 : Math.max(SIZE[want] * 16, rmax * 0.12);
    s3.flyTo(obj.getWorldPosition(new THREE.Vector3()), dist, obj);
  }

  /* ---------------- per frame ---------------- */

  P.frame = function (dt) {
    if (!P.isOpen || !M) return;
    // While a flyby close-up is showing, the mission waits for it.
    if (LS.flybyCloseup.active) { LS.flybyCloseup.frame(dt); return; }
    // Slow motion around flybys and arrival in the cinematic view.
    const k = nearEvent();
    rate = baseRate * (camMode === 'auto' && k >= 0 ? 0.3 : 1);
    if (playing) {
      t += dt * rate;
      if (t > tMax()) { t = tMax(); playing = false; }
    }
    const jd = M.jd0 + t;
    const buf = [0, 0, 0];
    for (const n of LS.planetTable.order) {
      bodies[n].position.copy(LS.sv3(LS.planetPos(n, jd, buf)));
      bodies[n].rotation.y += dt * 0.25;
    }

    // Spacecraft position and trail.
    const td = M.t_days, n = td.length;
    let lo = 0, hi = n - 1;
    const tc = Math.min(Math.max(t, 0), M.tof);
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (td[m] <= tc) lo = m; else hi = m; }
    const u = Math.min(Math.max((tc - td[lo]) / ((td[hi] - td[lo]) || 1), 0), 1);
    const a = M.track_au[lo], b = M.track_au[hi];
    const pos = [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u];
    craft.position.copy(LS.sv3(pos));
    LS.aimCraft(craft, LS.sv3(M.track_au[Math.min(hi + 1, n - 1)]));
    trail.geometry.setDrawRange(0, t <= 0 ? 0 : lo + 1);
    const speed = M.speed[lo] + (M.speed[hi] - M.speed[lo]) * u;

    updateCamera();
    s3.render();

    // Event cards: shown when the clock passes each event. At a gravity
    // assist the mission pauses for the close-up (unless switched off).
    for (let e = shownEvent + 1; e < M.events.length; e++) {
      if (t < M.eventT[e]) break;
      shownEvent = e;
      if (playing && $('p-fxon').checked && LS.flybyCloseup.available(M.events[e])) {
        t = M.eventT[e];
        closeup(e);
        break;
      }
      showEvent(e);
    }
    if (eventTimer > 0) {
      eventTimer -= dt;
      if (eventTimer <= 0) $('p-event').hidden = true;
    }

    teleTimer -= dt;
    if (teleTimer <= 0) { teleTimer = 0.15; telemetry(pos, speed, lo, jd); }
    $('player').querySelector('.p-bar').classList.toggle('playing', playing);
    const frac = (t - tMin()) / (tMax() - tMin()) * 100;
    $('p-fill').style.width = `${frac}%`;
    $('p-head').style.left = `${frac}%`;
  };

  /* Show flyby k up close; the mission carries on when it ends. */
  function closeup(k) {
    playing = false;
    $('p-event').hidden = true;
    const again = k >= 2 && M.events[k - 1].planet === M.events[k].planet;
    LS.flybyCloseup.play(M.events[k], { again, onDone: () => { showEvent(k); playing = true; } });
  }

  function eventTitle(e) {
    return e.kind === 'launch' ? `Launch from ${e.planet}` : e.kind === 'flyby' ? `${e.planet} gravity assist`
      : e.kind === 'dsm' ? 'Deep-space burn' : `Arrival at ${e.planet}`;
  }

  function showEvent(k) {
    const e = M.events[k], f = LS.fmt;
    let text;
    if (e.kind === 'launch') {
      text = `The rocket fires for <b>${f(e.dv, 2)} km/s</b> of Δv from a 200 km parking orbit
        (launch energy C₃ = ${f(e.c3, 1)} km²/s²) and leaves ${e.planet}'s gravity behind.`;
    } else if (e.kind === 'dsm') {
      text = `Far from any planet, ${f(e.r_au, 2)} AU from the Sun, the main engine fires for <b>${f(e.dv, 2)} km/s</b>.
        Out here the spacecraft moves slowly, so a modest burn reshapes its orbit: it will come back past Earth much
        faster than it left, and Earth's gravity will fling it onward.`;
    } else if (e.kind === 'flyby') {
      text = `Passing ${f(e.altitude_radii, 1)} ${e.planet} radii from its centre, gravity bends the path by
        <b>${f(e.turn_deg, 0)}°</b>. Because ${e.planet} is moving at ${f(e.v_planet, 1)} km/s around the Sun, the spacecraft
        ${e.gain >= 0 ? `<b>gains ${f(e.gain, 2)} km/s</b>` : `<b>loses ${f(-e.gain, 2)} km/s</b> (used as a brake)`}
        — ${e.dv > 0.01 ? `plus an engine burn of ${f(e.dv, 2)} km/s at closest approach.` : 'without using any fuel.'}`;
    } else {
      const yrs = (e.jd - M.jd0) / 365.25;
      text = `After ${yrs >= 1 ? `${f(yrs, 1)} years` : `${f(e.jd - M.jd0, 0)} days`}, the spacecraft reaches ${e.planet}
        at <b>${f(e.vinf, 2)} km/s</b> relative to it. ${e.capture_dv !== null && e.capture_dv !== undefined
          ? `A braking burn of <b>${f(e.capture_dv, 2)} km/s</b> puts it into orbit.` : 'It flies past to continue its journey.'}`;
    }
    const box = $('p-event');
    box.style.setProperty('--c', EVENT_CSS[e.kind]);
    const replay = LS.flybyCloseup.available(e) ? '<button class="fx-open">▶ Watch this flyby up close</button>' : '';
    box.innerHTML = `<div class="k">${LS.fmtDate(LS.jdToDate(e.jd))} · event ${k + 1} of ${M.events.length}</div>
      <div class="t">${eventTitle(e)}</div><p>${text}</p>${replay}`;
    if (replay) box.querySelector('.fx-open').onclick = () => closeup(k);
    box.hidden = false;
    // Replay the entrance animation.
    box.style.animation = 'none'; void box.offsetWidth; box.style.animation = '';
    eventTimer = 7;
  }

  function telemetry(pos, speed, idx, jd) {
    const f = LS.fmt;
    const r = Math.hypot(...pos);
    const day = Math.max(0, Math.min(t, M.tof));
    const next = M.eventT.findIndex((te) => te > t);
    const legIdx = M.legs.findIndex((L) => idx >= L.start && idx < L.end);
    const spent = M.events.filter((e, k) => M.eventT[k] <= t)
      .reduce((s, e) => s + (e.kind === 'launch' || e.kind === 'flyby' || e.kind === 'dsm' ? e.dv || 0 : e.capture_dv || 0), 0);
    const escape = Math.sqrt(2 * 1.32712440018e11 / (r * AU_KM));
    $('p-tele').innerHTML = `
      <div class="box"><h4>Mission time</h4>
        <div class="p-big">Day ${f(day, 0)}<small>of ${f(M.tof, 0)}</small></div>
        <div class="p-meter"><i style="width:${(100 * day / M.tof).toFixed(1)}%"></i></div>
        ${LS.kv([['Date', LS.fmtDate(LS.jdToDate(jd))],
                 ['Next', next >= 0 ? `${eventTitle(M.events[next]).replace('gravity assist', 'flyby')} in ${f(M.eventT[next] - t, 0)} d` : 'mission complete']])}
      </div>
      <div class="box"><h4>Spacecraft</h4>
        ${LS.kv([['Distance from Sun', `${f(r, 3)} AU`], ['', `${f(r * AU_KM / 1e6, 0)} million km`],
                 ['Speed around Sun', `${f(speed, 2)} km/s`],
                 ['Solar escape speed here', `${f(escape, 2)} km/s`],
                 ['Δv used so far', `${f(spent, 2)} of ${f(M.total_dv, 2)} km/s`]])}
      </div>
      <div class="box"><h4>Route</h4><div class="p-legs">${M.legs.map((L, k) => `
        <div class="${k === legIdx && t >= 0 && t <= M.tof ? 'now' : k < legIdx || t > M.tof ? 'done' : ''}">
          <i style="background:${LEG_CSS[k % LEG_CSS.length]}"></i>Leg ${k + 1}: ${L.from} → ${L.to}${L.revs ? ' (+loop)' : ''}</div>`).join('')}
        </div></div>`;
    $('p-clock').innerHTML = `${LS.fmtDate(LS.jdToDate(jd))} · <b>day ${f(day, 0)}</b>` +
      (rate < baseRate ? ' · slow motion' : '');
  }
})();
