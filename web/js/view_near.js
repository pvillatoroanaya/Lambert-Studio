/* Near-Earth space: real satellites (CelesTrak), the Moon, and the user's
   solved orbit, all at their positions for the simulated time.

   Every satellite is moved each frame with a Kepler + J2 secular model
   (see satellites.py for the Python twin, validated against SGP4). */
'use strict';

(function () {
  const S = 1 / LS.R_EARTH;
  const J2 = 1.08262668e-3;
  const $ = (id) => document.getElementById(id);

  const view = {
    id: 'near',
    title: 'Satellites around Earth',
    subtitle: 'Live CelesTrak orbital data · hover a satellite for its name, click for details',
    clock: new LS.Clock({
      t: 0, min: -86400, max: 3 * 86400, rate: 1, playing: true,
      rates: [[1, 'Real time'], [10, '10×'], [60, '60×'], [300, '300×'], [1800, '1800×']],
    }),
  };
  LS.views.near = view;

  let s3, earth, sun, moon, moonLabel, cloud, myOrbit;
  let refJd = LS.nowJd();
  let groupsMeta = [];                  // from /api/satellite_groups
  let selectedGroups = new Set();
  let groupInfo = [];                   // per loaded group (count, source...)
  let sats = [];                        // raw rows
  let el = null;                        // typed arrays of elements
  let selected = -1, selMarker, selOrbit, selLabel;
  let hudTimer = 0;
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();

  view.init = async function () {
    s3 = new LS.Scene3D($('cv-near'), { near: 0.001, far: 5e4 });
    earth = LS.earth();
    s3.scene.add(earth.group);
    s3.scene.add(new THREE.AmbientLight(0x6070a0, 0.35));
    sun = new THREE.DirectionalLight(0xffffff, 1.25);
    s3.scene.add(sun);

    moon = new THREE.Mesh(new THREE.SphereGeometry(1737.4 / LS.R_EARTH, 64, 48),
      new THREE.MeshPhongMaterial({ map: LS.texture('textures/moon.jpg'), shininess: 2 }));
    moonLabel = LS.label('Moon', 'dim');
    moon.add(moonLabel);
    s3.scene.add(moon);

    selMarker = new THREE.Group();
    selMarker.add(LS.markerRing(0xffffff, 0.034));
    selMarker.visible = false;
    selLabel = LS.label('', 'accent');
    selMarker.add(selLabel);
    s3.scene.add(selMarker);

    s3.camera.position.set(7, 4.5, 10);
    s3.controls.minDistance = 1.2;
    s3.controls.maxDistance = 900;
    s3.setFollowables([
      { label: 'Selected satellite', obj: () => (selected >= 0 ? selMarker : null) },
      { label: 'Moon', obj: () => moon },
      { label: 'Earth', obj: () => earth.surface },
    ]);
    raycaster.params.Points.threshold = 0.05;

    wire();
    await LS.loadPlanets();
    const meta = await LS.api('/api/satellite_groups');
    groupsMeta = meta.groups;
    groupsMeta.forEach((g) => { if (g.default) selectedGroups.add(g.key); });
    renderGroupChecks();
    load(false);
    LS.on('solved', drawMyOrbit);
    drawMyOrbit();
  };

  function wire() {
    const cv = $('cv-near');
    cv.addEventListener('pointermove', (e) => {
      const r = cv.getBoundingClientRect();
      mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      view._hover = { x: e.clientX - r.left, y: e.clientY - r.top };
    });
    cv.addEventListener('pointerleave', () => { view._hover = null; $('tooltip').hidden = true; });
    let down = null;
    cv.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
    cv.addEventListener('pointerup', (e) => {
      if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 4) {
        const k = pick();
        select(k);
      }
      down = null;
    });

    $('sat-search').addEventListener('input', search);
    $('sat-refresh').addEventListener('click', () => load(true));
    $('sat-myorbit').addEventListener('change', drawMyOrbit);
    $('sat-moon').addEventListener('change', () => { moon.visible = $('sat-moon').checked; });
  }

  function renderGroupChecks() {
    $('sat-groups').innerHTML = groupsMeta.map((g) => {
      const info = groupInfo.find((x) => x.key === g.key);
      const n = info ? (info.error ? '⚠' : info.count.toLocaleString()) : '';
      return `<label class="check"><input type="checkbox" data-g="${g.key}" ${selectedGroups.has(g.key) ? 'checked' : ''}>
        <span class="sw" style="background:${g.color}"></span>${g.label}<span class="n">${n}</span></label>`;
    }).join('');
    $('sat-groups').querySelectorAll('input').forEach((c) => c.addEventListener('change', () => {
      if (c.checked) selectedGroups.add(c.dataset.g); else selectedGroups.delete(c.dataset.g);
      load(false);
    }));
  }

  let loadToken = 0;
  async function load(refresh) {
    const token = ++loadToken;
    const keys = groupsMeta.map((g) => g.key).filter((k) => selectedGroups.has(k));
    const big = keys.includes('starlink') ? ' (Starlink is large, this can take a moment)' : '';
    try {
      const data = await LS.busy('Loading satellites' + big + '…', $('sat-refresh'),
        () => LS.api(`/api/satellites?groups=${keys.join(',')}${refresh ? '&refresh=1' : ''}`));
      if (token !== loadToken) return;
      setData(data);
    } catch (e) {
      $('sat-status').textContent = e.message;
    }
  }

  function setData(data) {
    groupInfo = data.groups;
    sats = data.sats;
    const n = sats.length;
    el = {
      n: new Float64Array(n), a: new Float64Array(n), e: new Float64Array(n), i: new Float64Array(n),
      O0: new Float64Array(n), w0: new Float64Array(n), M0: new Float64Array(n),
      Od: new Float64Array(n), wd: new Float64Array(n), ep: new Float64Array(n),
    };
    for (let k = 0; k < n; k++) {
      const [, , , epoch, mm, e, i, raan, argp, M] = sats[k];
      const nn = (mm * 2 * Math.PI) / 86400;
      const a = Math.cbrt(LS.MU_EARTH / (nn * nn));
      const p = a * (1 - e * e);
      const fac = 1.5 * nn * J2 * (LS.R_EARTH / p) ** 2;
      const ir = i * LS.DEG;
      el.n[k] = nn; el.a[k] = a; el.e[k] = e; el.i[k] = ir;
      el.O0[k] = raan * LS.DEG; el.w0[k] = argp * LS.DEG; el.M0[k] = M * LS.DEG;
      el.Od[k] = -fac * Math.cos(ir);
      el.wd[k] = 0.5 * fac * (5 * Math.cos(ir) ** 2 - 1);
      el.ep[k] = epoch;
    }

    if (cloud) { s3.scene.remove(cloud); cloud.geometry.dispose(); }
    cloud = LS.pointCloud(n, n > 3000 ? 4 : 6);
    const col = cloud.geometry.attributes.color.array;
    const colors = groupInfo.map((g) => new THREE.Color(g.color));
    for (let k = 0; k < n; k++) {
      const c = colors[sats[k][2]];
      col[3 * k] = c.r; col[3 * k + 1] = c.g; col[3 * k + 2] = c.b;
    }
    cloud.geometry.attributes.color.needsUpdate = true;
    s3.scene.add(cloud);
    select(-1);
    renderGroupChecks();
    renderLegend();
    renderSummary();

    const src = groupInfo.filter((g) => g.fetched);
    const oldest = src.length ? Math.min(...src.map((g) => g.fetched)) : null;
    const errs = groupInfo.filter((g) => g.error);
    $('sat-status').textContent = `${n.toLocaleString()} satellites` +
      (oldest ? ` · data from ${ago(oldest)}` : '') +
      (errs.length ? ` · ${errs.length} group(s) could not be downloaded` : '') + ' · source: CelesTrak';
  }

  const ago = (unix) => {
    const m = (Date.now() / 1000 - unix) / 60;
    return m < 2 ? 'just now' : m < 120 ? `${Math.round(m)} min ago` : `${Math.round(m / 60)} h ago`;
  };

  /* Position [km, ECI] of satellite k at Julian Date jd. */
  function position(k, jd, out) {
    const dt = (jd - el.ep[k]) * 86400;
    const e = el.e[k];
    const M = el.M0[k] + el.n[k] * dt;
    const E = LS.kepler(((M % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI), e);
    const a = el.a[k];
    return LS.rotate313(a * (Math.cos(E) - e), a * Math.sqrt(1 - e * e) * Math.sin(E),
      el.O0[k] + el.Od[k] * dt, el.i[k], el.w0[k] + el.wd[k] * dt, out);
  }

  function orbitClass(k) {
    const a = el.a[k], e = el.e[k], rp = a * (1 - e) - LS.R_EARTH, ra = a * (1 + e) - LS.R_EARTH;
    if (e > 0.25) return 'HEO';
    if (Math.abs(ra - 35786) < 800 && Math.abs(rp - 35786) < 800) return 'GEO';
    if (ra < 2000) return 'LEO';
    return 'MEO';
  }

  function renderLegend() {
    $('legend-near').innerHTML = groupInfo.filter((g) => g.count).map((g) =>
      `<div><i style="background:${g.color}"></i>${g.label} <span class="muted">${g.count.toLocaleString()}</span></div>`).join('');
  }

  function renderSummary() {
    if (selected >= 0) return;
    const counts = { LEO: 0, MEO: 0, GEO: 0, HEO: 0 };
    for (let k = 0; k < sats.length; k++) counts[orbitClass(k)]++;
    $('hud-near').innerHTML = `<div class="box"><h4>Overview</h4>
      <div class="big">${sats.length.toLocaleString()} satellites</div>
      ${LS.kv([['Low Earth orbit (LEO)', counts.LEO.toLocaleString()], ['Medium (MEO)', counts.MEO.toLocaleString()],
               ['Geostationary (GEO)', counts.GEO.toLocaleString()], ['Highly elliptical', counts.HEO.toLocaleString()]])}
      <p class="hint" style="margin-top:8px">Click a satellite, or search for one, to see its details and orbit.</p></div>`;
  }

  function search() {
    const q = $('sat-search').value.trim().toLowerCase();
    if (!q) { $('sat-results').innerHTML = ''; return; }
    const hits = [];
    for (let k = 0; k < sats.length && hits.length < 40; k++) {
      if (sats[k][0].toLowerCase().includes(q) || String(sats[k][1]) === q) hits.push(k);
    }
    $('sat-results').innerHTML = hits.length
      ? hits.map((k) => `<button data-k="${k}">${LS.esc(sats[k][0])}<small>#${sats[k][1]}</small></button>`).join('')
      : '<p class="hint">No match in the loaded groups. Try enabling more groups.</p>';
    $('sat-results').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
      select(+b.dataset.k, true);
    }));
  }

  function select(k, fly = false) {
    selected = k;
    if (selOrbit) { s3.scene.remove(selOrbit); selOrbit.geometry.dispose(); selOrbit = null; }
    selMarker.visible = k >= 0;
    if (k < 0) { renderSummary(); return; }
    selLabel.setText(sats[k][0]);
    drawSelectedOrbit();
    if (fly) {
      const p = position(k, jdNow(), [0, 0, 0]);
      const v = LS.v3(p, S);
      s3.focusOn(new THREE.Vector3(), Math.max(v.length() * 2.4, 3));
    }
    hudTimer = 0;
  }

  function drawSelectedOrbit() {
    const k = selected, jd = jdNow();
    const period = 2 * Math.PI / el.n[k] / 86400;
    const pts = [];
    const tmp = [0, 0, 0];
    for (let j = 0; j <= 240; j++) pts.push(LS.v3(position(k, jd + (period * j) / 240, tmp), S));
    selOrbit = LS.line(pts, groupInfo[sats[k][2]].color, 0.9);
    s3.scene.add(selOrbit);
  }

  function drawMyOrbit() {
    if (myOrbit) { s3.scene.remove(myOrbit); myOrbit.traverse((o) => o.element && o.element.remove()); myOrbit = null; }
    if (!LS.solution || !$('sat-myorbit').checked) return;
    const pts = LS.solution.track.r.map((p) => LS.v3(p, S));
    myOrbit = LS.line(pts, 0xffb454, 0.85);
    const lb = LS.label('your solved orbit', 'warm');
    lb.position.copy(pts[Math.floor(pts.length / 3)]);
    myOrbit.add(lb);
    s3.scene.add(myOrbit);
  }

  const jdNow = () => refJd + view.clock.t / 86400;

  function pick() {
    if (!cloud) return -1;
    raycaster.setFromCamera(mouse, s3.camera);
    raycaster.params.Points.threshold = s3.camera.position.distanceTo(s3.controls.target) * 0.008;
    const hits = raycaster.intersectObject(cloud);
    if (!hits.length) return -1;
    // Prefer the hit closest to the ray, not the first along it.
    hits.sort((a, b) => a.distanceToRay - b.distanceToRay);
    return hits[0].index;
  }

  /* ---------------- per frame ---------------- */
  const buf = [0, 0, 0];
  let hoverTimer = 0;

  view.update = function (dt) {
    const jd = jdNow();
    earth.spin.rotation.y = LS.gmst(jd);
    earth.clouds.rotation.y += dt * 0.004;
    sun.position.copy(LS.v3(LS.sunDirection(jd), 50));
    earth.setSun(sun.position);
    moon.position.copy(LS.v3(LS.moonPosition(jd), S));

    if (cloud && el) {
      const pos = cloud.geometry.attributes.position.array;
      for (let k = 0; k < sats.length; k++) LS.setXYZ(pos, k, position(k, jd, buf), S);
      cloud.geometry.attributes.position.needsUpdate = true;
    }
    if (selected >= 0) {
      selMarker.position.copy(LS.v3(position(selected, jd, buf), S));
      hudTimer -= dt;
      if (hudTimer <= 0) { hudTimer = 0.25; renderSelected(jd); }
    }

    hoverTimer -= dt;
    if (hoverTimer <= 0 && view._hover) {
      hoverTimer = 0.08;
      const k = pick(), tip = $('tooltip');
      if (k >= 0) {
        tip.innerHTML = `${LS.esc(sats[k][0])} <span class="muted">· ${groupInfo[sats[k][2]].label}</span>`;
        tip.style.left = view._hover.x + 'px'; tip.style.top = view._hover.y + 'px';
        tip.hidden = false;
        $('cv-near').style.cursor = 'pointer';
      } else { tip.hidden = true; $('cv-near').style.cursor = ''; }
    }
  };

  function renderSelected(jd) {
    const k = selected, p = position(k, jd, [0, 0, 0]);
    const r = Math.hypot(p[0], p[1], p[2]);
    const v = Math.sqrt(LS.MU_EARTH * (2 / r - 1 / el.a[k]));
    const g = groupInfo[sats[k][2]];
    const cls = orbitClass(k);
    const age = (LS.nowJd() - el.ep[k]) * 24;
    $('hud-near').innerHTML = `<div class="box"><h4>${g.label} <span class="badge">${cls}</span></h4>
      <div class="big">${LS.esc(sats[k][0])}</div>
      ${LS.kv([['NORAD ID', sats[k][1]], ['Altitude', `${LS.fmt(r - LS.R_EARTH, 0)} km`],
               ['Speed', `${LS.fmt(v, 3)} km/s`], ['Period', LS.fmtDuration(2 * Math.PI / el.n[k])],
               ['Inclination', `${LS.fmt(el.i[k] / LS.DEG, 2)}°`], ['Eccentricity', LS.fmt(el.e[k], 5)],
               ['Perigee / apogee', `${LS.fmt(el.a[k] * (1 - el.e[k]) - LS.R_EARTH, 0)} / ${LS.fmt(el.a[k] * (1 + el.e[k]) - LS.R_EARTH, 0)} km`],
               ['Elements age', age < 48 ? `${LS.fmt(age, 1)} h` : `${LS.fmt(age / 24, 1)} days`]])}
      <div class="row gap" style="margin-top:10px"><button class="ghost small" id="near-desel">Close</button></div></div>`;
    $('near-desel').onclick = () => select(-1);
  }

  view.render = () => s3.render();
  view.clockLabel = (t) => LS.fmtUTC(LS.jdToDate(refJd + t / 86400));
  view.onNow = function () {
    refJd = LS.nowJd();
    view.clock.t = 0; view.clock.rate = 1; view.clock.playing = true;
    if (selected >= 0) { if (selOrbit) s3.scene.remove(selOrbit); drawSelectedOrbit(); }
  };
})();
