/* Start page: a story you scroll through. One full-screen 3D scene stays
   behind the text; as you scroll, the Earth glides, grows and shrinks, and
   the things that belong to each section fade in (orbit rings, satellites,
   a transfer to Mars, an asteroid belt, the Moon). */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));

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
  const MU = 398600.4418, RE = 6378.137;           // km^3/s^2, km

  /* One value per section (hero, 1..5, final). The scene moves between them. */
  const POSE = {
    x:     [1.75, -1.75, 1.75, 2.35, -1.9, 1.9, 0],
    y:     [0, 0, 0, 0.05, -0.1, 0, 0],
    scale: [1.0, 1.15, 0.95, 0.6, 0.85, 0.5, 1.45],
  };
  const SHOW = {                                    // how visible each extra is in each section
    rings: [1, 1, 1, 0, 0, 0, 0.35],
    sats:  [1, 1, 1, 0, 0, 0, 0.35],
    grid:  [0.5, 0.3, 0.2, 0.9, 0.2, 1, 0.2],
    moon:  [1, 0, 0, 0, 0, 1, 0.5],
    mars:  [0, 0, 0, 1, 0, 1, 0],
    belt:  [0, 0, 0, 0.35, 1, 0.9, 0],
  };
  const key = (arr, f) => {
    const i = Math.min(arr.length - 2, Math.floor(f)), t = clamp(f - i, 0, 1), s = t * t * (3 - 2 * t);
    return arr[i] + (arr[i + 1] - arr[i]) * s;
  };

  let s3, earth, world, ringsGroup, grid, moonPivot, marsPivot, arc, belt, sats = [];
  const fade = {};                                  // objects whose opacity follows SHOW

  // Scale the opacity of every material under obj (remembering the original).
  function setOpacity(obj, o) {
    obj.visible = o > 0.01;
    obj.traverse((c) => {
      const m = c.material;
      if (!m || !m.transparent) return;
      if (m.userData.o0 === undefined) m.userData.o0 = m.opacity;
      m.opacity = m.userData.o0 * o;
    });
  }

  view.init = function () {
    setupPage();
    s3 = new LS.Scene3D($('cv-landing'), { near: 0.05, far: 2000 });
    s3.controls.enableRotate = s3.controls.enableZoom = s3.controls.enablePan = false;
    s3.controls.autoRotate = false;

    // Everything sits in one group that the scroll moves and the pointer tilts;
    // the stars stay put, so the planet seems to float in front of them.
    world = new THREE.Group();
    s3.scene.add(world);
    earth = LS.earth();
    earth.group.rotation.z = 23.4 * LS.DEG;
    earth.setSun(SUN);
    world.add(earth.group);
    grid = polarGrid(5);
    world.add(grid);
    const light = new THREE.DirectionalLight(0xffffff, 1.25);
    light.position.copy(SUN).multiplyScalar(10);
    s3.scene.add(light, new THREE.AmbientLight(0x6070a0, 0.35));

    ringsGroup = new THREE.Group();
    world.add(ringsGroup);
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
      ringsGroup.add(g);
    });

    // The Moon, circling at a distance.
    moonPivot = new THREE.Group();
    const moon = new THREE.Mesh(new THREE.SphereGeometry(0.27, 64, 48), LS.planetMaterial('Moon', 'moon.jpg'));
    moon.position.set(4.1, 0.1, 0);
    moonPivot.add(moon);
    world.add(moonPivot);

    // Mars and a transfer arc to it (not to scale: it is a picture of the idea).
    marsPivot = new THREE.Group();
    const mars = new THREE.Mesh(new THREE.SphereGeometry(0.5, 64, 48), LS.planetMaterial('Mars', 'mars.jpg'));
    mars.position.set(-4.2, 0.3, -1.0);
    marsPivot.add(mars);
    const arcPts = [];
    for (let k = 0; k <= 120; k++) {
      const t = k / 120;
      arcPts.push(new THREE.Vector3(-4.2 * t, 0.3 * t, -1.0 * t + Math.sin(Math.PI * t) * 1.6));
    }
    arc = LS.line(arcPts, 0xffb86b, 0.9);
    arc.geometry.setDrawRange(0, 0);
    marsPivot.add(arc);
    world.add(marsPivot);

    // Asteroid belt: a loose ring of points.
    const N = 900, pos = new Float32Array(N * 3);
    for (let k = 0; k < N; k++) {
      const a = Math.random() * 2 * Math.PI, r = 3.1 + Math.random() * 1.6;
      pos.set([r * Math.cos(a), (Math.random() - 0.5) * 0.35, r * Math.sin(a)], 3 * k);
    }
    const bg = new THREE.BufferGeometry();
    bg.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    belt = new THREE.Points(bg, new THREE.PointsMaterial({ size: 2.2, sizeAttenuation: false, color: 0xc9b9a3,
      transparent: true, opacity: 0.8, depthWrite: false, blending: THREE.AdditiveBlending }));
    world.add(belt);

    // Moon and Mars are solid: only their group's visibility follows SHOW (no fading of textures).
    fade.rings = ringsGroup; fade.grid = grid; fade.belt = belt;

    s3.camera.position.set(0, 1.5, 6.4);
    s3.camera.lookAt(0, 0, 0);
    s3.controls.update();

  };

  /* Everything that is not 3D: it must work even if WebGL is unavailable. */
  function setupPage() {
    buildTelemetry();
    buildDots();
    reveal();
    const go = (id) => LS.setView(id);
    document.querySelectorAll('#landing [data-go]').forEach((b) => b.addEventListener('click', () => go(b.dataset.go)));
    $('ld-start').addEventListener('click', () => $('landing').scrollTo({ top: $('landing').clientHeight, behavior: 'smooth' }));
    // Keys 1-6 open the six modules while the start page is showing.
    const order = [...document.querySelectorAll('#landing .ld-modules [data-go]')].map((b) => b.dataset.go);
    window.addEventListener('keydown', (e) => {
      if (LS.activeView !== view || e.ctrlKey || e.altKey || e.metaKey) return;
      const k = +e.key;
      if (k >= 1 && k <= order.length) go(order[k - 1]);
    });
    // A soft light that follows the pointer.
    const glow = $('st-glow');
    $('landing').addEventListener('pointermove', (e) => {
      glow.style.transform = `translate(${e.clientX}px, ${e.clientY}px)`;
    }, { passive: true });
  }

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

  /* ---- section dots, and the reveal of each section's text ---- */
  const sections = () => [...document.querySelectorAll('#landing .st-sec')];

  function buildDots() {
    const nav = $('st-dots');
    nav.innerHTML = sections().map((s, i) =>
      `<button aria-label="Section ${i + 1}" data-i="${i}"><i></i></button>`).join('');
    nav.addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (b) sections()[+b.dataset.i].scrollIntoView({ behavior: 'smooth' });
    });
  }

  function reveal() {
    const io = new IntersectionObserver((list) => {
      list.forEach((en) => {
        en.target.classList.toggle('in', en.isIntersecting);
        if (en.isIntersecting && en.target.classList.contains('st-final')) finalSeen();
      });
    }, { root: $('landing'), threshold: 0.4 });
    sections().forEach((s) => {
      s.querySelectorAll('.st-rv').forEach((el, i) => el.style.setProperty('--d', `${0.12 + i * 0.09}s`));
      s.querySelectorAll('.ln').forEach((el, i) => el.style.setProperty('--d', `${i * 0.1}s`));
      io.observe(s);
    });
  }

  /* ---- readouts ---- */
  let clockTimer = 0, typed = false, counted = false, sourcesLoaded = false, finalVisible = false;

  function tickClock() {
    $('ld-clock').textContent = 'UTC ' + new Date().toISOString().replace('T', ' ').slice(0, 19);
  }

  function typeKicker() {
    const el = $('ld-kicker'), text = el.dataset.text;
    if (typed || document.body.classList.contains('no-fx')) { el.textContent = text; return; }
    typed = true;
    let k = 0;
    const step = () => { el.textContent = text.slice(0, ++k); if (k < text.length) setTimeout(step, 28); };
    setTimeout(step, 500);
  }

  function countUp() {
    document.querySelectorAll('#landing [data-count]').forEach((b) => {
      const to = +b.dataset.count, t0 = performance.now();
      const run = (now) => {
        const f = Math.min(1, (now - t0) / 1100);
        b.textContent = String(Math.round(to * (1 - Math.pow(1 - f, 3))));
        if (f < 1) requestAnimationFrame(run);
      };
      requestAnimationFrame(run);
    });
  }
  // The numbers count up when the last section comes into view (and the data has arrived).
  function maybeCount() { if (!counted && finalVisible && sourcesLoaded) { counted = true; countUp(); } }
  function finalSeen() { finalVisible = true; maybeCount(); }

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
    maybeCount();
  }

  view.show = function () {
    $('landing').hidden = false;
    tickClock();
    clearInterval(clockTimer);
    clockTimer = setInterval(tickClock, 1000);
    typeKicker();
    if (!sourcesLoaded) loadSources();
    // ?scroll=2.5 opens the page already scrolled to that section (handy for screenshots)
    const q = parseFloat(new URLSearchParams(location.search).get('scroll'));
    if (q > 0) { $('landing').scrollTop = q * $('landing').clientHeight; sf = clamp(q, 0, 6); }
  };
  view.hide = function () { $('landing').hidden = true; clearInterval(clockTimer); };

  /* ---- every frame: scroll position drives the scene ---- */
  let t = 0, px = 0, py = 0, sf = 0, lastActive = -1;
  view.update = function (dt) {
    t += dt;
    const box = $('landing');
    const on = !document.body.classList.contains('no-fx');
    const target = clamp(box.scrollTop / Math.max(1, box.clientHeight), 0, 6);
    sf += (target - sf) * (on ? 1 - Math.exp(-dt * 4.5) : 1);

    // narrow windows: keep the planet centred behind the text instead of beside it
    const aspect = box.clientWidth / Math.max(1, box.clientHeight);
    const side = clamp((aspect - 0.9) / 0.8, 0, 1);
    const k = 1 - Math.exp(-dt * 4);
    px += ((on ? LS.pointer.x : 0) - px) * k;
    py += ((on ? LS.pointer.y : 0) - py) * k;

    world.position.set(key(POSE.x, sf) * side, key(POSE.y, sf), 0);
    world.scale.setScalar(key(POSE.scale, sf) * (side < 1 ? 0.8 : 1));
    world.rotation.set(py * 0.12, px * 0.2, 0);

    Object.keys(fade).forEach((name) => setOpacity(fade[name], key(SHOW[name], sf)));
    moonPivot.visible = key(SHOW.moon, sf) > 0.05;
    const m = key(SHOW.mars, sf);
    marsPivot.visible = m > 0.05;
    marsPivot.children[0].scale.setScalar(Math.min(1, m * 1.5));   // Mars grows in
    ringsGroup.visible = key(SHOW.rings, sf) > 0.02;
    // the transfer arc draws itself as the mission section arrives
    const draw = clamp((sf - 2.2) / 0.8, 0, 1) * (sf < 4.6 ? 1 : clamp(1 - (sf - 4.6) / 0.6, 0, 1));
    arc.geometry.setDrawRange(0, Math.round(draw * 121));

    earth.spin.rotation.y += dt * 0.07;
    earth.clouds.rotation.y += dt * 0.012;
    ringsGroup.rotation.y += dt * 0.02;
    moonPivot.rotation.y += dt * 0.05;
    belt.rotation.y += dt * 0.03;
    marsPivot.children[0].rotation.y += dt * 0.1;
    sats.forEach((s) => {
      const place = (obj, a) => obj.position.set(s.ring.r * Math.cos(a), 0, s.ring.r * Math.sin(a));
      const a = s.phase + t * s.w;
      s.body.children[0].position.set(s.ring.r * Math.cos(a), 0, s.ring.r * Math.sin(a));
      s.body.children[1].position.copy(s.body.children[0].position);
      s.trail.forEach((sp, i) => place(sp, a - (i + 1) * 0.07 * s.ring.r / 1.5));
    });

    // interface bits that follow the scroll
    const max = Math.max(1, box.scrollHeight - box.clientHeight);
    $('st-bar').style.transform = `scaleX(${(box.scrollTop / max).toFixed(4)})`;
    box.style.setProperty('--sf', sf.toFixed(3));
    const idx = Math.round(sf);
    if (idx !== lastActive) {
      lastActive = idx;
      document.querySelectorAll('#st-dots button').forEach((b, i) => b.classList.toggle('on', i === idx));
    }
  };
  view.render = function () { s3.render(); };
})();
