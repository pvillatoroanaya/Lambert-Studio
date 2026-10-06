/* Solar system: planets from the Standish elements (same model as
   planets.py), near-Earth asteroids from JPL, and — when one has been
   designed in the Mission tab — an interplanetary transfer. */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const GAUSS_K = 0.01720209895;         // Gaussian gravitational constant [rad/day, AU]

  const view = {
    id: 'solar',
    title: 'Solar system',
    subtitle: 'Heliocentric ecliptic frame, distances in AU · planet sizes exaggerated for visibility',
    clock: new LS.Clock({
      t: 0, min: -3650, max: 3650, rate: 10, playing: true,
      rates: [[1, '1 day/s'], [5, '5 days/s'], [10, '10 days/s'], [30, '30 days/s'], [100, '100 days/s']],
    }),
  };
  LS.views.solar = view;

  let s3, planetsGroup, orbitsGroup, labels = [], bodies = {}, astCloud = null, ast = null, astGroup = 'pha';
  let transferGroup = null, craft = null, refJd = LS.nowJd();
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  let hover = null, hoverTimer = 0;

  const SIZE = { Mercury: 0.012, Venus: 0.02, Earth: 0.021, Mars: 0.015,
    Jupiter: 0.09, Saturn: 0.08, Uranus: 0.05, Neptune: 0.05 };

  view.init = async function () {
    s3 = new LS.Scene3D($('cv-solar'), { near: 1e-4, far: 1e5 });
    s3.scene.add(new THREE.AmbientLight(0x404a66, 0.2));
    s3.scene.add(new THREE.PointLight(0xfff2dd, 1.05, 0, 0));

    const sunMesh = LS.sun(0.035);
    sunMesh.add(LS.glowSprite(0xffa040, 0.45));
    sunMesh.add(LS.label('Sun', 'warm'));
    s3.scene.add(sunMesh);
    bodies.Sun = sunMesh;

    await LS.loadPlanets();
    planetsGroup = new THREE.Group();
    orbitsGroup = new THREE.Group();
    s3.scene.add(planetsGroup, orbitsGroup);

    for (const name of LS.planetTable.order) {
      const st = LS.planetTable.elements[name];
      // Surface textures: Solar System Scope (CC BY 4.0); Earth: NASA Blue Marble.
      const file = name === 'Earth' ? 'earth_day_hd.jpg' : `${name.toLowerCase()}.jpg`;
      const mat = LS.planetMaterial(name, file);
      const m = new THREE.Mesh(new THREE.SphereGeometry(SIZE[name], 128, 96), mat);
      if (name === 'Saturn') {
        const inner = SIZE.Saturn * 1.24, outer = SIZE.Saturn * 2.27;
        const g = new THREE.RingGeometry(inner, outer, 160, 1);
        // The ring texture is a radial strip: map u to the distance from the planet.
        const pos = g.attributes.position, uv = g.attributes.uv, v = new THREE.Vector3();
        for (let k = 0; k < pos.count; k++) {
          v.fromBufferAttribute(pos, k);
          uv.setXY(k, (v.length() - inner) / (outer - inner), 0.5);
        }
        const ring = new THREE.Mesh(g, new THREE.MeshBasicMaterial({
          map: LS.texture('textures/saturn_ring.png'), side: THREE.DoubleSide, transparent: true, depthWrite: false }));
        ring.rotation.x = Math.PI / 2 - 0.47;          // Saturn's 26.7° tilt, roughly
        m.add(ring);
      }
      // Always-visible dot so planets stay findable when zoomed far out.
      const pin = new THREE.Sprite(new THREE.SpriteMaterial({ map: LS.spriteTexture(), color: st.color,
        sizeAttenuation: false, depthWrite: false, blending: THREE.AdditiveBlending }));
      pin.scale.set(0.022, 0.022, 1);
      m.add(pin);
      const lb = LS.label(name, name === 'Earth' ? 'key' : '');
      m.add(lb);
      labels.push(lb);
      planetsGroup.add(m);
      bodies[name] = m;
    }
    buildOrbits();

    s3.controls.maxDistance = 400;
    s3.controls.minDistance = 0.02;
    frameSystem();

    $('sol-truescale').checked = !LS.settings.compress;
    $('sol-truescale').addEventListener('change', () => {
      LS.settings.compress = !$('sol-truescale').checked;
      LS.applySettings();
      LS.emit('scale');
    });
    LS.on('scale', () => {
      buildOrbits();
      if (LS.transfer) showTransfer(LS.transfer, true);
      frameSystem();
    });

    $('sol-focus').innerHTML = ['Sun', ...LS.planetTable.order].map((n) =>
      `<button data-f="${n}"><i style="background:${n === 'Sun' ? '#ffd98a' : LS.planetTable.elements[n].color}"></i>${n}</button>`).join('');
    $('sol-focus').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => setFocus(b.dataset.f)));
    $('sol-orbits').addEventListener('change', () => { orbitsGroup.visible = $('sol-orbits').checked; });
    $('sol-labels').addEventListener('change', () => {
      labels.forEach((l) => { l.userData.hide = !$('sol-labels').checked; });
    });
    $('sol-ast').addEventListener('change', () => { if (astCloud) astCloud.visible = $('sol-ast').checked; });
    document.querySelectorAll('#sol-astgroup button').forEach((b) => b.addEventListener('click', () => {
      document.querySelectorAll('#sol-astgroup button').forEach((x) => x.classList.toggle('on', x === b));
      astGroup = b.dataset.g;
      loadAsteroids();
    }));

    const cv = $('cv-solar');
    cv.addEventListener('pointermove', (e) => {
      const r = cv.getBoundingClientRect();
      mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      hover = { x: e.clientX - r.left, y: e.clientY - r.top };
    });
    cv.addEventListener('pointerleave', () => { hover = null; $('tooltip').hidden = true; });

    s3.setFollowables([
      { label: 'Sun', obj: () => bodies.Sun },
      ...LS.planetTable.order.map((n) => ({ label: n, obj: () => bodies[n] })),
      { label: 'Spacecraft', obj: () => (craft && craft.visible ? craft : null) },
    ]);
    LS.on('transfer', showTransfer);
    if (LS.transfer) showTransfer(LS.transfer);
    renderHud();
    loadAsteroids();
  };

  function buildOrbits() {
    orbitsGroup.children.slice().forEach((o) => { o.geometry.dispose(); orbitsGroup.remove(o); });
    for (const name of LS.planetTable.order) {
      const pts = LS.planetOrbit(name, refJd).map((p) => LS.sv3(p));
      orbitsGroup.add(LS.line(pts, LS.planetTable.elements[name].color, 0.45));
    }
  }

  /* Start with the whole system in view: all eight planets when distances
     are compressed; the inner planets at true scale. */
  function frameSystem() {
    s3.controls.target.set(0, 0, 0);
    if (LS.settings.compress) s3.camera.position.set(1.6, 7.2, 9.6);
    else s3.camera.position.set(0.6, 1.9, 2.6);
    s3.focusOn(new THREE.Vector3(), s3.camera.position.length());
  }

  /* Focus chips: fly to the body and keep following it (the camera's own
     Follow system, so the toolbar and double-click stay in sync). */
  function setFocus(name) {
    document.querySelectorAll('#sol-focus button').forEach((b) => b.classList.toggle('on', b.dataset.f === name));
    if (name === 'Sun') {
      s3.setFollow(null);
      s3.flyTo(new THREE.Vector3(), LS.settings.compress ? 12 : 3.2);
      return;
    }
    s3.setFollow(s3.followables.find((f) => f.label === name));
    s3.flyTo(bodies[name].position.clone(), Math.max(SIZE[name] * 14, 0.25), bodies[name]);
  }

  async function loadAsteroids() {
    const group = astGroup;
    try {
      const data = await LS.busy(group === 'neo' ? 'Loading all near-Earth objects (≈ 40 000)…' : 'Loading hazardous asteroids…',
        null, () => LS.getNeo(group));
      if (group !== astGroup) return;
      if (!data.elements) { $('sol-status').textContent = data.errors.join(' '); return; }
      const rows = data.elements.rows;
      const n = rows.length;
      ast = { rows, a: new Float64Array(n), e: new Float64Array(n), i: new Float64Array(n), O: new Float64Array(n),
        w: new Float64Array(n), M0: new Float64Array(n), ep: new Float64Array(n), n: new Float64Array(n) };
      rows.forEach((r, k) => {
        ast.a[k] = r[1]; ast.e[k] = r[2]; ast.i[k] = r[3] * LS.DEG; ast.O[k] = r[4] * LS.DEG;
        ast.w[k] = r[5] * LS.DEG; ast.M0[k] = r[6] * LS.DEG; ast.ep[k] = r[7];
        ast.n[k] = GAUSS_K / Math.pow(r[1], 1.5);
      });
      if (astCloud) { s3.scene.remove(astCloud); astCloud.geometry.dispose(); }
      astCloud = LS.pointCloud(n, n > 10000 ? 3 : 5);
      const col = astCloud.geometry.attributes.color.array;
      const cP = new THREE.Color(0xff8a5c), cN = new THREE.Color(0x6f86b8);
      rows.forEach((r, k) => { const c = r[9] ? cP : cN; col[3 * k] = c.r; col[3 * k + 1] = c.g; col[3 * k + 2] = c.b; });
      astCloud.visible = $('sol-ast').checked;
      s3.scene.add(astCloud);
      const pha = rows.filter((r) => r[9]).length;
      $('sol-status').textContent = `${n.toLocaleString('en-US')} asteroids (${pha.toLocaleString('en-US')} potentially hazardous, orange) · source: NASA/JPL SBDB` +
        ` · planet positions: ${LS.eph.source} · planet textures: Solar System Scope (CC BY 4.0)`;
    } catch (e) {
      $('sol-status').textContent = e.message;
    }
  }

  function astPosition(k, jd, out) {
    const e = ast.e[k];
    let M = (ast.M0[k] + ast.n[k] * (jd - ast.ep[k])) % (2 * Math.PI);
    if (M < 0) M += 2 * Math.PI;
    const E = LS.kepler(M, e), a = ast.a[k];
    return LS.rotate313(a * (Math.cos(E) - e), a * Math.sqrt(1 - e * e) * Math.sin(E), ast.O[k], ast.i[k], ast.w[k], out);
  }

  /* ---------------- transfer from the Mission tab ---------------- */

  /* redraw=true only rebuilds the drawing (after a scale change) and
     keeps the clock where it is. */
  function showTransfer(t, redraw = false) {
    if (!s3) return;
    if (transferGroup) {
      transferGroup.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.element) o.element.remove(); });
      s3.scene.remove(transferGroup);
    }
    transferGroup = new THREE.Group();
    s3.scene.add(transferGroup);
    const pts = t.track_au.map((p) => LS.sv3(p));
    transferGroup.add(LS.tube(pts, 0.006, 0x5eb3e6));
    const d = LS.dot(0.018, 0x7fcf9f); d.position.copy(pts[0]); transferGroup.add(d);
    const dl = LS.label(`${t.departure} · depart`, 'dim'); dl.position.copy(pts[0]); transferGroup.add(dl);
    const a = LS.dot(0.018, 0xe56f6f); a.position.copy(pts[pts.length - 1]); transferGroup.add(a);
    const al = LS.label(`${t.arrival} · arrive`, 'dim'); al.position.copy(pts[pts.length - 1]); transferGroup.add(al);
    craft = LS.spacecraft(0.016, { label: 'spacecraft' });
    transferGroup.add(craft);

    if (!redraw) {
      refJd = t.jd_departure;
      const c = view.clock;
      c.min = -60; c.max = t.tof_days + 120; c.t = -20; c.rate = 20; c.playing = true;
      LS.syncTimebar();
    }

    $('sol-transfer').hidden = false;
    $('sol-transfer').innerHTML = `<b>${t.departure} → ${t.arrival}</b>
      ${LS.kv([['Depart', t.dep_iso.slice(0, 10)], ['Arrive', t.arr_iso.slice(0, 10)],
               ['Flight time', `${LS.fmt(t.tof_days, 0)} days`], ['C₃', `${LS.fmt(t.c3, 2)} km²/s²`]])}
      <div class="row gap" style="margin-top:8px"><button class="ghost small" id="sol-clear">Hide transfer</button></div>`;
    $('sol-clear').onclick = () => {
      s3.scene.remove(transferGroup); transferGroup = null; craft = null;
      $('sol-transfer').hidden = true; LS.transfer = null;
    };
    renderHud();
  }

  function renderHud() {
    $('hud-solar').innerHTML = `<div class="box"><h4>Distances today</h4><div id="sol-live"></div></div>`;
  }

  /* ---------------- per frame ---------------- */
  const buf = [0, 0, 0];
  let hudTimer = 0;

  view.update = function (dt) {
    const jd = refJd + view.clock.t;
    for (const name of LS.planetTable ? LS.planetTable.order : []) {
      bodies[name].position.copy(LS.sv3(LS.planetPos(name, jd, buf)));
      bodies[name].rotation.y += dt * 0.3;
    }
    if (astCloud && ast) {
      const pos = astCloud.geometry.attributes.position.array;
      for (let k = 0; k < ast.rows.length; k++) LS.setSXYZ(pos, k, astPosition(k, jd, buf));
      astCloud.geometry.attributes.position.needsUpdate = true;
    }
    if (craft && LS.transfer) {
      const t = LS.transfer, n = t.track_au.length;
      const f = (jd - t.jd_departure) / t.tof_days;
      craft.visible = f >= 0 && f <= 1;
      if (craft.visible) {
        const x = f * (n - 1), k = Math.min(Math.floor(x), n - 2), u = x - k;
        const a = t.track_au[k], b = t.track_au[k + 1];
        craft.position.copy(LS.sv3([a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u]));
        LS.aimCraft(craft, LS.sv3(t.track_au[Math.min(k + 2, n - 1)]));
      }
    }

    hudTimer -= dt;
    if (hudTimer <= 0 && $('sol-live') && LS.planetTable) {
      hudTimer = 0.3;
      const e = LS.planetPos('Earth', jd, [0, 0, 0]);
      const rows = [['Earth – Sun', `${LS.fmt(Math.hypot(...e), 4)} AU`]];
      for (const name of ['Venus', 'Mars', 'Jupiter']) {
        const p = LS.planetPos(name, jd, [0, 0, 0]);
        rows.push([`Earth – ${name}`, `${LS.fmt(Math.hypot(p[0] - e[0], p[1] - e[1], p[2] - e[2]), 3)} AU`]);
      }
      if (craft && craft.visible) {
        const f = (jd - LS.transfer.jd_departure);
        rows.push(['Spacecraft', `day ${Math.floor(f)} of ${Math.round(LS.transfer.tof_days)}`]);
      }
      $('sol-live').innerHTML = LS.kv(rows);
    }

    hoverTimer -= dt;
    if (hoverTimer <= 0 && hover && astCloud && astCloud.visible && ast) {
      hoverTimer = 0.1;
      raycaster.setFromCamera(mouse, s3.camera);
      raycaster.params.Points.threshold = s3.camera.position.distanceTo(s3.controls.target) * 0.006;
      const hits = raycaster.intersectObject(astCloud).sort((a, b) => a.distanceToRay - b.distanceToRay);
      const tip = $('tooltip');
      if (hits.length) {
        const r = ast.rows[hits[0].index];
        tip.innerHTML = `${LS.esc(r[0])}${r[9] ? ' <span class="badge warn">PHA</span>' : ''}<br>
          <span class="muted">a ${LS.fmt(r[1], 3)} AU · e ${LS.fmt(r[2], 3)} · i ${LS.fmt(r[3], 1)}°</span>`;
        tip.style.left = hover.x + 'px'; tip.style.top = hover.y + 'px';
        tip.hidden = false;
      } else tip.hidden = true;
    }
  };

  view.render = () => s3.render();
  view.clockLabel = (t) => LS.fmtUTC(LS.jdToDate(refJd + t)).slice(0, 10);
  view.nowLabel = 'Today';
  view.onNow = function () {
    view.clock.t = LS.nowJd() - refJd;
    view.clock.playing = false;
  };
})();
