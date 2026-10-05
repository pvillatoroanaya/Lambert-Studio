/* Start page: a slowly turning Earth with satellites circling it, drawn on
   the same shared WebGL renderer as every other 3D view. */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);

  const view = {
    id: 'landing',
    title: 'Lambert Studio',
    subtitle: 'Orbit determination and mission design',
  };
  LS.views.landing = view;

  // Inclination (deg), node (deg), radius (Earth radii), colour, satellites on the ring.
  const RINGS = [
    { inc: 52, node: 20, r: 1.38, color: 0x7fb4ff, n: 2 },
    { inc: 98, node: 110, r: 1.62, color: 0x9ad7ff, n: 2 },
    { inc: 28, node: 200, r: 1.9, color: 0xffd27a, n: 1 },
    { inc: 63, node: 290, r: 2.25, color: 0x7fb4ff, n: 2 },
    { inc: 5, node: 0, r: 2.7, color: 0xb9c8ff, n: 1 },
  ];
  const SUN = new THREE.Vector3(-0.85, 0.3, 0.6);

  let s3, earth, world, sats = [];
  const MU = 398600.4418, RE = 6378.137;           // km^3/s^2, km

  view.init = function () {
    s3 = new LS.Scene3D($('cv-landing'), { near: 0.05, far: 2000 });
    s3.controls.enableRotate = s3.controls.enableZoom = s3.controls.enablePan = false;
    s3.controls.autoRotate = true;
    s3.controls.autoRotateSpeed = 0.35;

    // Everything that belongs to the Earth system sits in one group, which
    // leans a few degrees toward the pointer: the stars stay put, so the
    // planet, rings and grid seem to float in front of them (depth).
    world = new THREE.Group();
    s3.scene.add(world);
    earth = LS.earth();
    earth.group.rotation.z = 23.4 * LS.DEG;
    earth.setSun(SUN);
    world.add(earth.group);
    world.add(polarGrid(3.4));
    const light = new THREE.DirectionalLight(0xffffff, 1.2);
    light.position.copy(SUN).multiplyScalar(10);
    s3.scene.add(light, new THREE.AmbientLight(0x6070a0, 0.35));

    RINGS.forEach((ring) => {
      const g = new THREE.Group();
      g.rotation.set(0, ring.node * LS.DEG, 0);
      const tilt = new THREE.Group();
      tilt.rotation.x = ring.inc * LS.DEG;
      g.add(tilt);
      const pts = [];
      for (let k = 0; k <= 180; k++) {
        const a = (k / 180) * 2 * Math.PI;
        pts.push(new THREE.Vector3(ring.r * Math.cos(a), 0, ring.r * Math.sin(a)));
      }
      tilt.add(LS.line(pts, ring.color, 0.4));
      for (let k = 0; k < ring.n; k++) {
        const body = new THREE.Group();
        body.add(LS.glowSprite(ring.color, 0.34));
        body.add(LS.glowSprite(0xffffff, 0.12));
        // short fading trail behind the satellite
        const trail = [];
        for (let t = 1; t <= 4; t++) {
          const sp = LS.glowSprite(ring.color, 0.2 - t * 0.03);
          sp.material.opacity = 0.5 - t * 0.1;
          trail.push(sp);
          body.add(sp);
        }
        tilt.add(body);
        sats.push({ body, trail, ring, phase: (k / ring.n) * 2 * Math.PI + ring.node, w: 0.5 / Math.pow(ring.r, 1.5) });
      }
      world.add(g);
    });

    s3.camera.position.set(0, 1.5, 6.4);
    s3.camera.lookAt(0, 0, 0);
    s3.controls.update();

    buildTelemetry();
    const go = (id) => LS.setView(id);
    $('ld-start').addEventListener('click', () => go('orbit'));
    document.querySelectorAll('#landing [data-go]').forEach((b) => b.addEventListener('click', () => go(b.dataset.go)));
    // Keys 1-6 open the six modules while the start page is showing.
    const order = [...document.querySelectorAll('#landing .ld-modules [data-go]')].map((b) => b.dataset.go);
    window.addEventListener('keydown', (e) => {
      if (LS.activeView !== view || e.ctrlKey || e.altKey || e.metaKey) return;
      const k = +e.key;
      if (k >= 1 && k <= order.length) go(order[k - 1]);
    });
  };

  /* A holographic polar grid in the equatorial plane: rings every 0.5 Earth
     radii and a spoke every 30 degrees. Drawn as faint light traces. */
  function polarGrid(R) {
    const g = new THREE.Group();
    for (let r = 1; r <= R + 0.01; r += 0.5) {
      const pts = [];
      for (let k = 0; k <= 128; k++) { const a = (k / 128) * 2 * Math.PI; pts.push(new THREE.Vector3(r * Math.cos(a), 0, r * Math.sin(a))); }
      g.add(LS.line(pts, 0x4fb4ff, r % 1 === 0 ? 0.2 : 0.09));
    }
    for (let d = 0; d < 360; d += 30) {
      const a = d * LS.DEG;
      g.add(LS.line([new THREE.Vector3(Math.cos(a), 0, Math.sin(a)), new THREE.Vector3(R * Math.cos(a), 0, R * Math.sin(a))], 0x4fb4ff, 0.1));
    }
    return g;
  }

  /* Real numbers for the circular orbits drawn on the Earth: altitude,
     speed v = sqrt(mu / r) and period T = 2 pi sqrt(r^3 / mu). */
  function buildTelemetry() {
    const rows = RINGS.map((ring, i) => {
      const r = ring.r * RE, v = Math.sqrt(MU / r), T = 2 * Math.PI * Math.sqrt(r * r * r / MU) / 60;
      const hex = '#' + ring.color.toString(16).padStart(6, '0');
      return `<div class="ld-tr"><i style="background:${hex}"></i><b>O${i + 1}</b><span>${Math.round(r - RE).toLocaleString('en-US')} km</span>` +
        `<span>${v.toFixed(2)} km/s</span><span>${Math.floor(T / 60)}h ${String(Math.round(T % 60)).padStart(2, '0')}m</span></div>`;
    });
    $('ld-tele-rows').innerHTML = `<div class="ld-tr head"><i></i><b></b><span>ALT</span><span>SPEED</span><span>PERIOD</span></div>` + rows.join('');
  }

  /* ---- the readout on the left ---- */
  let clockTimer = 0, typed = false, counted = false, sourcesLoaded = false;

  function tickClock() {
    $('ld-clock').textContent = 'UTC ' + new Date().toISOString().replace('T', ' ').slice(0, 19);
  }

  function typeKicker() {
    const el = $('ld-kicker'), text = el.dataset.text;
    if (typed || matchMedia('(prefers-reduced-motion: reduce)').matches) { el.textContent = text; return; }
    typed = true;
    let k = 0;
    const step = () => { el.textContent = text.slice(0, ++k); if (k < text.length) setTimeout(step, 28); };
    step();
  }

  function countUp() {
    document.querySelectorAll('#landing [data-count]').forEach((b) => {
      const to = +b.dataset.count, t0 = performance.now();
      const run = (now) => {
        const f = Math.min(1, (now - t0) / 900);
        b.textContent = String(Math.round(to * (1 - Math.pow(1 - f, 3))));
        if (f < 1) requestAnimationFrame(run);
      };
      requestAnimationFrame(run);
    });
  }

  function setStatus(id, text, cls) {
    const b = $(id);
    b.textContent = text;
    b.className = cls;
  }

  async function loadSources() {
    sourcesLoaded = true;
    try {
      const r = await (await fetch('/api/sources')).json();
      if (!r.ok) throw new Error(r.error);
      const d = r.data;
      setStatus('src-eph', d.ephemeris.available ? 'READY' : 'APPROXIMATE', d.ephemeris.available ? 'ok' : 'warn');
      setStatus('src-celestrak', d.online.celestrak ? 'ONLINE' : 'OFFLINE · SAVED COPY', d.online.celestrak ? 'ok' : 'warn');
      setStatus('src-jpl', d.online.jpl ? 'ONLINE' : 'OFFLINE · SAVED COPY', d.online.jpl ? 'ok' : 'warn');
      $('cap-groups').dataset.count = d.satellite_groups;
    } catch (e) {
      ['src-eph', 'src-celestrak', 'src-jpl'].forEach((id) => setStatus(id, 'UNKNOWN', 'warn'));
    }
    if (!counted) { counted = true; countUp(); }
  }

  view.show = function () {
    $('landing').hidden = false;
    tickClock();
    clearInterval(clockTimer);
    clockTimer = setInterval(tickClock, 1000);
    typeKicker();
    if (!sourcesLoaded) loadSources();
  };
  view.hide = function () { $('landing').hidden = true; clearInterval(clockTimer); };

  let t = 0, px = 0, py = 0;
  view.update = function (dt) {
    t += dt;
    // The world leans toward the pointer, smoothly (and not at all with effects off).
    const on = !document.body.classList.contains('no-fx');
    const k = 1 - Math.exp(-dt * 4);
    px += ((on ? LS.pointer.x : 0) - px) * k;
    py += ((on ? LS.pointer.y : 0) - py) * k;
    world.rotation.set(py * 0.16, px * 0.26, 0);
    $('landing').style.setProperty('--tx', px.toFixed(3));
    $('landing').style.setProperty('--ty', py.toFixed(3));
    earth.spin.rotation.y += dt * 0.07;
    earth.clouds.rotation.y += dt * 0.012;
    sats.forEach((s) => {
      const place = (obj, a) => obj.position.set(s.ring.r * Math.cos(a), 0, s.ring.r * Math.sin(a));
      const a = s.phase + t * s.w;
      s.body.children[0].position.set(s.ring.r * Math.cos(a), 0, s.ring.r * Math.sin(a));
      s.body.children[1].position.copy(s.body.children[0].position);
      s.trail.forEach((sp, i) => place(sp, a - (i + 1) * 0.07 * s.ring.r / 1.5));
    });
  };
  view.render = function () { s3.render(); };
})();
