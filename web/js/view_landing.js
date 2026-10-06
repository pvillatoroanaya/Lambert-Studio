/* Start page: a journey you scroll through. One full-screen 3D scene stays
   behind the text. The first sections belong to the Earth (orbit rings,
   satellites, the Moon); then the camera leaves along a transfer arc to
   Mars, threads through a field of asteroids, arrives at Saturn, and flies
   home to the Earth for the last section. Everything lives in one space,
   so nothing pops in: it is simply there when the camera arrives. */
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

  /* Where things are in the journey (units: Earth radii). Distances are
     shortened so the trip fits one page; the sizes of the Earth, the Moon,
     Mars and Saturn are to scale with each other. */
  // The route climbs well above the Earth's sections, so none of it is in
  // view until the camera sets off.
  const MARS_AT = new THREE.Vector3(-22, 42, -58), MARS_R = 0.532;
  const BELT_AT = new THREE.Vector3(-55, 100, -125);
  const SATURN_AT = new THREE.Vector3(-100, 160, -225), SATURN_R = 9.45;
  // Moons and spacecraft around Mars and Saturn, in the Earth's style
  // (radii in planet radii, compressed like the Earth's so they frame the planet).
  const MARS_ORBITS = [
    { inc: 1.1, node: 30, r: 1.8, color: 0xffc796, n: 1, big: 1.3 },    // Phobos
    { inc: 1.8, node: 150, r: 2.75, color: 0xffe0bd, n: 1, big: 1.2 },  // Deimos
    { inc: 93, node: 250, r: 1.22, color: 0x9ad7ff, n: 1 },             // a polar mapping orbiter
    { inc: 75, node: 70, r: 1.5, color: 0x7fb4ff, n: 1 },               // an atmosphere orbiter
  ];
  const SATURN_ORBITS = [
    { inc: 0, node: 0, r: 2.9, color: 0xf3e6c8, n: 1 },                  // Enceladus
    { inc: 1, node: 80, r: 3.5, color: 0xf6eedb, n: 1 },                 // Tethys
    { inc: 0, node: 160, r: 4.2, color: 0xefe2c4, n: 1 },                // Dione
    { inc: 0.3, node: 240, r: 5.0, color: 0xfff1d6, n: 1, big: 1.3 },    // Rhea
    { inc: 62, node: 300, r: 3.2, color: 0x7fb4ff, n: 1, o: 0.32 },      // a Cassini-style spacecraft
  ];
  const SECTIONS = 6;                               // hero = 0 ... final = 6
  /* Which side of the screen the subject sits on in each section, so it
     never hides behind the text: +1 right, -1 left, 0 centre. */
  const SIDE = [1, -1, 1, 1, -1, 1, 0];
  const SHOW = {                                    // how visible the Earth's extras are in each section
    rings: [1, 1, 1, 0.2, 0, 0, 0.6],
    grid:  [0.5, 0.3, 0.25, 0, 0, 0, 0.2],
    arc:   [1, 1, 1, 1, 1, 0.5, 0],
    marsOrbits:   [0, 0, 0.15, 1, 0.2, 0, 0],
    saturnOrbits: [0, 0, 0, 0, 0.35, 1, 0.1],
  };
  const smoother = (u) => u * u * u * (u * (u * 6 - 15) + 10);    // starts and ends at rest
  const key = (arr, f) => {
    const i = Math.min(arr.length - 2, Math.floor(f)), s = smoother(clamp(f - i, 0, 1));
    return arr[i] + (arr[i + 1] - arr[i]) * s;
  };
  // A seeded random generator, so the asteroid field is the same every visit.
  const rng = (seed) => () => {
    seed = (seed + 0x6D2B79F5) | 0;
    let x = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };

  let marsOrbits, saturnOrbits;
  let s3, earth, world, ringsGroup, grid, moonPivot, mars, saturn, arc, arcHead, hero, rocks = [], sats = [];
  let K = [];                                       // camera keyframes, one per section
  const fade = {};                                  // objects whose opacity follows SHOW

  /* Orbits drawn the same way around every planet: a faint ring of light
     and glowing bodies with short trails. Radii in planet radii; `unit` is
     the planet's radius in scene units, `size` scales the glows to how far
     the camera stands from that planet. */
  function makeOrbits(list, unit, size) {
    const group = new THREE.Group();
    list.forEach((ring) => {
      const g = new THREE.Group();
      g.rotation.set(0, ring.node * LS.DEG, 0);
      const tilt = new THREE.Group();
      tilt.rotation.x = ring.inc * LS.DEG;
      g.add(tilt);
      const R = ring.r * unit, pts = [];
      for (let k = 0; k <= 240; k++) {
        const a = (k / 240) * 2 * Math.PI;
        pts.push(new THREE.Vector3(R * Math.cos(a), 0, R * Math.sin(a)));
      }
      tilt.add(LS.line(pts, ring.color, ring.o || 0.4));
      for (let k = 0; k < ring.n; k++) {
        const body = new THREE.Group();
        body.add(LS.glowSprite(ring.color, 0.34 * size * (ring.big || 1)));
        body.add(LS.glowSprite(0xffffff, 0.12 * size * (ring.big || 1)));
        const trail = [];
        for (let t = 1; t <= 4; t++) {
          const sp = LS.glowSprite(ring.color, (0.2 - t * 0.03) * size);
          sp.material.opacity = 0.5 - t * 0.1;
          trail.push(sp);
          body.add(sp);
        }
        tilt.add(body);
        sats.push({ body, trail, R, k: ring.r, phase: (k / ring.n) * 2 * Math.PI + ring.node, w: 0.5 / Math.pow(ring.r, 1.5) });
      }
      group.add(g);
    });
    return group;
  }

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
    s3 = new LS.Scene3D($('cv-landing'), { near: 0.05, far: 6000 });
    s3.controls.enableRotate = s3.controls.enableZoom = s3.controls.enablePan = false;
    s3.controls.enableDamping = false;
    s3.controls.enabled = false;
    s3.locked = true;            // the scroll story drives this camera: no fly mode or double-click

    world = new THREE.Group();
    s3.scene.add(world);
    const sun = SUN.clone().normalize();
    const light = new THREE.DirectionalLight(0xffffff, 0.9);
    light.position.copy(sun).multiplyScalar(10);
    s3.scene.add(light, new THREE.AmbientLight(0x6070a0, 0.16));

    // ---- the Earth and its neighbourhood ----
    earth = LS.earth();
    earth.group.rotation.z = 23.4 * LS.DEG;
    earth.setSun(sun);
    world.add(earth.group);
    grid = polarGrid(5);
    world.add(grid);

    ringsGroup = makeOrbits(RINGS, 1, 1);
    world.add(ringsGroup);

    // The Moon, to scale with the Earth (its distance is shortened).
    moonPivot = new THREE.Group();
    const moon = new THREE.Mesh(new THREE.SphereGeometry(0.273, 96, 64), LS.planetMaterial('Moon', 'moon.jpg'));
    moon.position.set(4.1, 0.1, 0);
    moonPivot.add(moon);
    world.add(moonPivot);
    fade.rings = ringsGroup; fade.grid = grid;

    // ---- Mars ----
    mars = new THREE.Group();
    mars.position.copy(MARS_AT);
    const marsTilt = new THREE.Group();
    marsTilt.rotation.z = 25.2 * LS.DEG;
    mars.add(marsTilt);
    const marsBody = new THREE.Mesh(new THREE.SphereGeometry(MARS_R, 192, 128), LS.planetMaterial('Mars', 'mars.jpg'));
    marsTilt.add(marsBody);
    // a thin dusty atmosphere, drawn like the Earth's (brightest on the day side)
    marsTilt.add(LS.atmosphere(MARS_R * 1.018, 0xff9f70, 3.0, 0.85), LS.atmosphere(MARS_R * 1.055, 0xffbe98, 4.6, 0.4));
    marsOrbits = makeOrbits(MARS_ORBITS, MARS_R, 0.52);
    marsTilt.add(marsOrbits);
    mars.userData.body = marsBody;
    world.add(mars);

    // The transfer arc from the Earth to Mars, drawn as the trip begins,
    // with a small bright spacecraft at its tip.
    const toMars = MARS_AT.clone().normalize();
    const a0 = toMars.clone().multiplyScalar(1.3);
    const a1 = MARS_AT.clone().addScaledVector(toMars, -MARS_R * 1.6);
    const bend = new THREE.Vector3().crossVectors(toMars, new THREE.Vector3(0, 1, 0)).normalize().multiplyScalar(9);
    const ctrl = a0.clone().add(a1).multiplyScalar(0.5).add(bend).add(new THREE.Vector3(0, 4, 0));
    const arcPts = [];
    for (let k = 0; k <= 240; k++) {
      const s = k / 240, u = 1 - s;
      arcPts.push(a0.clone().multiplyScalar(u * u).addScaledVector(ctrl, 2 * u * s).addScaledVector(a1, s * s));
    }
    arc = LS.line(arcPts, 0xffb86b, 0.85);
    arc.userData.pts = arcPts;
    arc.geometry.setDrawRange(0, 0);
    world.add(arc);
    fade.arc = arc;
    arcHead = new THREE.Group();
    arcHead.add(LS.glowSprite(0xffd9a0, 0.5), LS.glowSprite(0xffffff, 0.16));
    arcHead.visible = false;
    world.add(arcHead);

    // ---- Saturn ----
    saturn = LS.saturn(SATURN_R);
    saturn.group.position.copy(SATURN_AT);
    saturn.group.rotation.y = -0.5;
    world.add(saturn.group);
    saturn.setSun(sun);
    saturnOrbits = makeOrbits(SATURN_ORBITS, SATURN_R, 8.5);
    saturn.tilt.add(saturnOrbits);                   // in Saturn's equator, like its rings and moons
    fade.marsOrbits = marsOrbits; fade.saturnOrbits = saturnOrbits;

    // ---- the camera's path: one keyframe per section ----
    // Mars is seen from beyond it, half-way towards the Sun: mostly lit, with
    // the arc and the far-off Earth behind it.
    const marsView = MARS_AT.clone().normalize().addScaledVector(sun, 0.5).normalize();
    K = [
      { p: new THREE.Vector3(0, 1.5, 6.4), t: new THREE.Vector3() },                       // hero
      { p: new THREE.Vector3(3.4, 1.4, 4.9), t: new THREE.Vector3() },                     // orbit determination
      { p: new THREE.Vector3(-2.6, 3.4, 5.0), t: new THREE.Vector3() },                    // satellites
      { p: MARS_AT.clone().addScaledVector(marsView, 3.3), t: MARS_AT.clone() },          // Mars
      { p: BELT_AT.clone().add(new THREE.Vector3(9, 2.5, 13)),
        t: BELT_AT.clone().add(new THREE.Vector3(-6, -1, -8)) },                           // inside the asteroid field
      { p: SATURN_AT.clone().add(new THREE.Vector3(-40, 21, 70)), t: SATURN_AT.clone() },  // Saturn
      { p: new THREE.Vector3(0, 0.6, 5.2), t: new THREE.Vector3() },                       // home again
    ];
    // The camera comes to rest at every keyframe and flies a straight line
    // between them (eased), so it can never swing past or into a planet.
    K.forEach((k) => { k.v = new THREE.Vector3(); });

    buildAsteroids();

    s3.camera.position.copy(K[0].p);
    s3.controls.target.copy(K[0].t);
    s3.camera.lookAt(K[0].t);
    prewarm();
  };

  /* Upload every texture and compile every shader now, while the page
     opens, instead of the first time each object comes into view -- which
     froze the scroll for up to a tenth of a second (Mars, Saturn, the
     asteroids, the 8K Moon map). */
  function prewarm(tries = 0) {
    const r = s3.renderer, seen = new Set();
    let waiting = 0;
    s3.scene.traverse((o) => {
      [].concat(o.material || []).forEach((m) => {
        Object.values(m).concat(Object.values(m.uniforms || {}).map((u) => u.value)).forEach((v) => {
          if (!v || !v.isTexture || seen.has(v)) return;
          seen.add(v);
          const img = v.image;
          if (!img || img.complete === false || !(img.width || img.naturalWidth)) waiting++;   // still downloading
          else r.initTexture(v);
        });
      });
    });
    r.compile(s3.scene, s3.camera);
    if (waiting && tries < 60) setTimeout(() => prewarm(tries + 1), 250);
  }

  /* A field of real 3D asteroids around the camera's path: four rock
     shapes (lumpy spheres with a cratered surface), each drawn many times
     at different sizes, tints and tumbling speeds. One large rock is the
     section's subject. Nothing is placed where the camera flies. */
  function buildAsteroids() {
    const rand = rng(7);
    const rockGeometry = (seed, detail) => {
      const r = rng(seed), g = new THREE.SphereGeometry(1, detail * 2, detail);
      const waves = Array.from({ length: 7 }, (_, k) => ({
        d: new THREE.Vector3(r() - 0.5, r() - 0.5, r() - 0.5).normalize(),
        f: 1.2 + k * 1.1 + r(), ph: r() * 6.3, a: 0.16 / (1 + k * 0.7) }));
      const stretch = new THREE.Vector3(1 + r() * 0.5, 0.65 + r() * 0.3, 0.8 + r() * 0.3);
      const p = g.attributes.position, v = new THREE.Vector3();
      for (let i = 0; i < p.count; i++) {
        v.fromBufferAttribute(p, i).normalize();
        let d = 1;
        waves.forEach((w) => { d += w.a * Math.sin(v.dot(w.d) * w.f * 3 + w.ph); });
        v.multiplyScalar(d).multiply(stretch);
        p.setXYZ(i, v.x, v.y, v.z);
      }
      g.computeVertexNormals();
      return g;
    };
    const mat = new THREE.MeshStandardMaterial({ map: LS.texture('textures/moon.jpg'), color: 0xc2b29e, roughness: 1, metalness: 0 });

    // keep the camera's corridor clear
    const path = [];
    for (let f = 2.6; f <= SECTIONS; f += 0.02) path.push(camAt(f).p);
    const clear = (pos, size) => path.every((q) => q.distanceTo(pos) > 2.2 + size * 2.5);

    const PER = 170, m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), c = new THREE.Color();
    for (let g = 0; g < 4; g++) {
      const mesh = new THREE.InstancedMesh(rockGeometry(11 + g * 17, 22), mat, PER);
      mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      mesh.frustumCulled = false;
      const list = [];
      for (let k = 0; k < PER; k++) {
        let pos, size, tries = 0;
        do {
          const a = rand() * 2 * Math.PI, r = Math.sqrt(rand()) * 48;
          pos = BELT_AT.clone().add(new THREE.Vector3(r * Math.cos(a) * 1.2, (rand() + rand() + rand() - 1.5) * 6, r * Math.sin(a)));
          size = 0.08 + Math.pow(rand(), 4) * 1.5;
        } while (!clear(pos, size) && ++tries < 30);
        const axis = new THREE.Vector3(rand() - 0.5, rand() - 0.5, rand() - 0.5).normalize();
        list.push({ pos, size, axis, spin: (rand() - 0.5) * 0.6, angle: rand() * 6.3 });
        const tint = 0.75 + rand() * 0.35;
        mesh.setColorAt(k, c.setRGB(tint, tint * (0.93 + rand() * 0.05), tint * (0.85 + rand() * 0.08)));
      }
      mesh.instanceColor.needsUpdate = true;
      const group = { mesh, list };
      rocks.push(group);
      world.add(mesh);
      placeRocks(group, 0, m, q, s);
    }
    // the subject of the asteroid section, just beside where the camera looks
    hero = new THREE.Mesh(rockGeometry(3, 64), mat);
    hero.scale.setScalar(2.1);
    hero.position.copy(BELT_AT).add(new THREE.Vector3(-3.5, -0.6, -4.5));
    world.add(hero);
  }

  function placeRocks(group, dt, m, q, s) {
    group.list.forEach((r, k) => {
      r.angle += r.spin * dt;
      q.setFromAxisAngle(r.axis, r.angle);
      group.mesh.setMatrixAt(k, m.compose(r.pos, q, s.setScalar(r.size)));
    });
    group.mesh.instanceMatrix.needsUpdate = true;
  }

  /* The camera at any scroll position, between the keyframes of the two
     nearest sections. It accelerates and settles gently, so each section is
     framed at rest. (Hermite form: the tangents are zero, so the path is
     straight; they are kept to bend the path later if wanted.) */
  function camAt(f) {
    f = clamp(f, 0, SECTIONS);
    const i = Math.min(SECTIONS - 1, Math.floor(f)), raw = f - i, u = smoother(raw);
    const A = K[i], B = K[i + 1];
    const u2 = u * u, u3 = u2 * u;
    const h00 = 2 * u3 - 3 * u2 + 1, h10 = u3 - 2 * u2 + u, h01 = -2 * u3 + 3 * u2, h11 = u3 - u2;
    const p = A.p.clone().multiplyScalar(h00).addScaledVector(A.v, h10).addScaledVector(B.p, h01).addScaledVector(B.v, h11);
    // The gaze turns to the next subject early in the flight, so during the
    // trip you watch the destination grow instead of empty space.
    return { p, t: A.t.clone().lerp(B.t, smoother(clamp(raw * 1.8, 0, 1))) };
  }

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

  /* Each section's text follows the scroll continuously: it drifts and
     fades with the position, and its line-by-line reveal starts once the
     section is mostly in view (with some slack, so it never flickers). */
  function reveal() {
    sections().forEach((s) => {
      s.querySelectorAll('.st-rv').forEach((el, i) => el.style.setProperty('--d', `${0.12 + i * 0.09}s`));
      s.querySelectorAll('.ln').forEach((el, i) => el.style.setProperty('--d', `${i * 0.1}s`));
    });
  }

  let secs = null;
  function followText(f) {
    secs = secs || sections();
    secs.forEach((s, i) => {
      const d = f - i, a = Math.abs(d);
      if (a > 2 && s.dataset.far) return;            // far away and already parked
      s.dataset.far = a > 2 ? '1' : '';
      s.style.setProperty('--off', clamp(d, -1, 1).toFixed(4));
      s.style.setProperty('--vis', clamp(1.3 - a * 1.25, 0, 1).toFixed(4));
      const shown = s.classList.contains('in');
      if (!shown && a < 0.5) {
        s.classList.add('in');
        if (s.classList.contains('st-final')) finalSeen();
      } else if (shown && a > 0.85) s.classList.remove('in');
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

  /* ---- every frame: the scroll position drives the journey ---- */
  let t = 0, px = 0, py = 0, sf = 0, sv = 0, lastActive = -1, drawnSf = -1;
  const right = new THREE.Vector3(), up = new THREE.Vector3(), fwd = new THREE.Vector3();
  const m4 = new THREE.Matrix4(), q4 = new THREE.Quaternion(), s4 = new THREE.Vector3();
  view.update = function (dt) {
    t += dt;
    const box = $('landing');
    const on = !document.body.classList.contains('no-fx');
    const target = clamp(box.scrollTop / Math.max(1, box.clientHeight), 0, SECTIONS);
    // A critically damped spring: the scene glides after the scroll with
    // inertia, never overshoots, and moves the same at any frame rate.
    if (!on) { sf = target; sv = 0; }
    else {
      const w = 6.5;
      for (let left = Math.min(dt, 0.1); left > 1e-6; left -= 1 / 240) {
        const h = Math.min(left, 1 / 240);
        sv += (w * w * (target - sf) - 2 * w * sv) * h;
        sf += sv * h;
      }
      if (Math.abs(target - sf) < 1e-4 && Math.abs(sv) < 1e-4) { sf = target; sv = 0; }
    }

    // the camera on its path, with the subject moved to the side away from the text
    const cam = camAt(sf);
    const aspect = box.clientWidth / Math.max(1, box.clientHeight);
    const wide = clamp((aspect - 0.9) / 0.8, 0, 1);    // narrow windows: keep the subject centred
    const k = 1 - Math.exp(-dt * 4);
    px += ((on ? LS.pointer.x : 0) - px) * k;
    py += ((on ? LS.pointer.y : 0) - py) * k;
    fwd.copy(cam.t).sub(cam.p);
    const dist = fwd.length();
    fwd.normalize();
    right.crossVectors(fwd, s3.camera.up).normalize();
    up.crossVectors(right, fwd).normalize();
    const halfW = dist * Math.tan((s3.camera.fov * LS.DEG) / 2) * s3.camera.aspect;
    const look = cam.t.clone().addScaledVector(right, -key(SIDE, sf) * wide * halfW * 0.42);
    cam.p.addScaledVector(right, px * dist * 0.035).addScaledVector(up, -py * dist * 0.025);
    s3.camera.position.copy(cam.p);
    s3.controls.target.copy(look);
    s3.camera.lookAt(look);

    // the Earth's extras fade away as the camera leaves
    Object.keys(fade).forEach((name) => setOpacity(fade[name], key(SHOW[name], sf)));

    // the transfer arc draws itself as the trip begins; the spacecraft rides its tip
    const draw = clamp((sf - 2.1) / 0.8, 0, 1);
    const n = Math.round(draw * 240);
    arc.geometry.setDrawRange(0, n + 1);
    arcHead.visible = draw > 0.002 && draw < 0.998;
    if (arcHead.visible) arcHead.position.copy(arc.userData.pts[n]);

    earth.spin.rotation.y += dt * 0.07;
    earth.clouds.rotation.y += dt * 0.012;
    ringsGroup.rotation.y += dt * 0.02;
    moonPivot.rotation.y += dt * 0.05;
    mars.userData.body.rotation.y += dt * 0.06;
    saturn.planet.rotation.y += dt * 0.04;
    hero.rotation.x += dt * 0.05;
    hero.rotation.y += dt * 0.08;
    // the asteroid field is only drawn (and tumbled) while it can be in view
    const field = sf > 2.4 && sf < 5.97;
    rocks.forEach((g) => { g.mesh.visible = field; if (field) placeRocks(g, dt, m4, q4, s4); });
    sats.forEach((s) => {
      if (!s.body.parent.parent.parent.visible) return;          // its planet's orbits are faded out
      const place = (obj, a) => obj.position.set(s.R * Math.cos(a), 0, s.R * Math.sin(a));
      const a = s.phase + t * s.w;
      place(s.body.children[0], a);
      s.body.children[1].position.copy(s.body.children[0].position);
      s.trail.forEach((sp, i) => place(sp, a - (i + 1) * 0.07 * s.k / 1.5));
    });

    // interface bits that follow the scroll
    const max = Math.max(1, box.scrollHeight - box.clientHeight);
    $('st-bar').style.transform = `scaleX(${(box.scrollTop / max).toFixed(4)})`;
    if (Math.abs(sf - drawnSf) > 2e-4) {          // restyle the page only while something moves
      drawnSf = sf;
      box.style.setProperty('--sf', sf.toFixed(3));
      followText(sf);
    }
    const idx = Math.round(sf);
    if (idx !== lastActive) {
      lastActive = idx;
      document.querySelectorAll('#st-dots button').forEach((b, i) => b.classList.toggle('on', i === idx));
    }
  };
  view.render = function () { s3.render(); };
})();
