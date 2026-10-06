/* Asteroid flybys: NASA/JPL close approaches, and for the chosen one its
   exact geocentric path from JPL Horizons, with Earth and the Moon. */
'use strict';

(function () {
  const S = 1 / LS.R_EARTH;
  const $ = (id) => document.getElementById(id);

  const view = {
    id: 'flybys',
    title: 'Asteroid flybys',
    subtitle: 'Geocentric paths from JPL Horizons · Earth and Moon to scale',
    clock: new LS.Clock({
      t: 0, min: -3 * 86400, max: 3 * 86400, rate: 3600, playing: true,
      rates: [[600, '10 min/s'], [3600, '1 h/s'], [7200, '2 h/s'], [21600, '6 h/s']],
    }),
  };
  LS.views.flybys = view;

  let s3, earth, sun, moon, moonRing, earthPin, pathGroup, rock, rockLabel;
  let approaches = [], filter = 'upcoming', current = null, path = null;
  let hudTimer = 0;

  view.init = async function () {
    s3 = new LS.Scene3D($('cv-flybys'), { near: 0.01, far: 1e6 });
    earth = LS.earth();
    s3.scene.add(earth.group);
    s3.scene.add(new THREE.AmbientLight(0x6070a0, 0.2));
    sun = new THREE.DirectionalLight(0xffffff, 0.9);
    s3.scene.add(sun);

    // Screen-size markers, so Earth and the asteroid stay findable when
    // the camera is thousands of Earth radii away.
    earthPin = new THREE.Sprite(new THREE.SpriteMaterial({ map: LS.spriteTexture(), color: 0x4da6ff,
      sizeAttenuation: false, depthWrite: false, blending: THREE.AdditiveBlending }));
    earthPin.scale.set(0.035, 0.035, 1);
    const el = LS.label('Earth', 'accent'); earthPin.add(el);
    s3.scene.add(earthPin);

    moon = new THREE.Mesh(new THREE.SphereGeometry(1737.4 / LS.R_EARTH, 160, 112),
      LS.planetMaterial('Moon', 'moon.jpg'));
    const mp = new THREE.Sprite(new THREE.SpriteMaterial({ map: LS.spriteTexture(), color: 0xc8cfdc,
      sizeAttenuation: false, depthWrite: false, blending: THREE.AdditiveBlending }));
    mp.scale.set(0.02, 0.02, 1);
    moon.add(mp);
    moon.add(LS.label('Moon', 'dim'));
    s3.scene.add(moon);

    const geo = new THREE.Mesh(new THREE.TorusGeometry(42164 / LS.R_EARTH, 0.03, 6, 160),
      new THREE.MeshBasicMaterial({ color: 0x3b5486, transparent: true, opacity: 0.6 }));
    geo.rotation.x = Math.PI / 2;
    s3.scene.add(geo);

    s3.camera.position.set(90, 60, 140);
    s3.controls.maxDistance = 1e5;
    s3.setFollowables([
      { label: 'Asteroid', obj: () => rock || null },
      { label: 'Earth', obj: () => earth.surface },
      { label: 'Moon', obj: () => moon },
    ]);

    document.querySelectorAll('#fly-seg button').forEach((b) => b.addEventListener('click', () => {
      document.querySelectorAll('#fly-seg button').forEach((x) => x.classList.toggle('on', x === b));
      filter = b.dataset.f;
      renderList();
    }));

    try {
      const data = await LS.busy('Loading close approaches from NASA/JPL…', null, () => LS.getNeo('pha'));
      if (data.approaches) {
        approaches = data.approaches.approaches;
        $('fly-status').textContent = `${approaches.length} close approaches · source: NASA/JPL CNEOS · ` +
          (data.approaches.source === 'live' ? 'downloaded now' : 'saved copy');
      } else {
        $('fly-status').textContent = data.errors.join(' ');
      }
    } catch (e) {
      $('fly-status').textContent = e.message;
    }
    renderList();
    const first = visible()[0];
    if (first) choose(first);
    else $('empty-flybys').hidden = false;
  };

  function visible() {
    const now = LS.nowJd();
    const list = approaches.filter((a) => (filter === 'upcoming' ? a.jd >= now : a.jd < now));
    return filter === 'upcoming' ? list.sort((a, b) => a.jd - b.jd) : list.sort((a, b) => b.jd - a.jd);
  }

  function sizeText(d) { return d ? `${d[0]}–${d[1]} m` : 'size unknown'; }

  function renderList() {
    const list = visible();
    $('fly-list').innerHTML = list.length ? list.map((a, k) => `
      <button class="fly${current && current.des === a.des && current.jd === a.jd ? ' on' : ''}" data-k="${k}">
        <b>${LS.esc(a.name.replace(/^\((.*)\)$/, '$1'))}</b><span class="d">${LS.fmt(a.dist_ld, 2)} LD</span>
        <span class="m">${a.date} UTC</span><span class="m">${LS.fmt(a.v_rel, 1)} km/s · ${sizeText(a.diameter_m)}</span>
      </button>`).join('') : '<p class="hint">Nothing in this window.</p>';
    $('fly-list').querySelectorAll('.fly').forEach((b) => b.addEventListener('click', () => choose(list[+b.dataset.k])));
  }

  async function choose(a) {
    current = a;
    renderList();
    $('empty-flybys').hidden = true;
    try {
      path = await LS.busy(`Getting ${a.des}'s path from JPL Horizons…`, null,
        () => LS.api(`/api/flyby?des=${encodeURIComponent(a.des)}&jd=${a.jd}`));
    } catch (e) {
      $('hud-flybys').innerHTML = `<div class="box"><h4>Could not load path</h4><p>${LS.esc(e.message)}</p></div>`;
      return;
    }
    if (current !== a) return;
    draw(a, path);
  }

  function draw(a, p) {
    if (pathGroup) {
      pathGroup.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.element) o.element.remove(); });
      s3.scene.remove(pathGroup);
    }
    if (moonRing) { s3.scene.remove(moonRing); moonRing = null; }
    pathGroup = new THREE.Group();
    s3.scene.add(pathGroup);

    const pts = p.r.map((r) => LS.v3(r, S));
    const dists = pts.map((v) => v.length());
    const iCa = dists.indexOf(Math.min(...dists));
    const span = Math.max(...dists);
    pathGroup.add(LS.tube(pts, Math.max(span * 0.002, 0.08), 0xeea55a, false, 0.9));

    const ca = pts[iCa];
    const caLine = LS.line([new THREE.Vector3(), ca], 0xe56f6f, 0.8, true);
    caLine.material.dashSize = span * 0.01; caLine.material.gapSize = span * 0.008; caLine.computeLineDistances();
    pathGroup.add(caLine);
    const caDot = LS.dot(Math.max(span * 0.004, 0.2), 0xe56f6f); caDot.position.copy(ca); pathGroup.add(caDot);
    const caLbl = LS.label(`closest: ${LS.fmt(a.dist_ld, 2)} LD`, 'warm'); caLbl.position.copy(ca); pathGroup.add(caLbl);

    rock = new THREE.Sprite(new THREE.SpriteMaterial({ map: LS.spriteTexture(), color: 0xffffff,
      sizeAttenuation: false, depthWrite: false, blending: THREE.AdditiveBlending }));
    rock.scale.set(0.03, 0.03, 1);
    rockLabel = LS.label(a.des, 'accent');
    rock.add(rockLabel);
    pathGroup.add(rock);

    // The Moon's actual orbit for this month, from the same lunar series.
    const mpts = [];
    for (let j = 0; j <= 200; j++) mpts.push(LS.v3(LS.moonPosition(a.jd - 13.7 + (27.4 * j) / 200), S));
    moonRing = LS.line(mpts, 0x8b9bbd, 0.35);
    s3.scene.add(moonRing);

    const c = view.clock;
    c.min = (p.jd[0] - a.jd) * 86400;
    c.max = (p.jd[p.jd.length - 1] - a.jd) * 86400;
    c.t = c.min * 0.5;
    c.playing = true;
    // Frame the whole path together with Earth.
    const box = new THREE.Box3().setFromPoints([...pts, new THREE.Vector3()]);
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    s3.focusOn(sphere.center, Math.max(sphere.radius * 2.3, 90));
    renderHud();
    LS.syncTimebar();
  }

  function renderHud() {
    const a = current;
    $('hud-flybys').innerHTML = `
      <div class="box"><h4>Close approach</h4>
        <div class="big">${LS.esc(a.name.replace(/^\((.*)\)$/, '$1'))}</div>
        ${LS.kv([['Date', `${a.date} UTC`], ['Miss distance', `${LS.fmt(a.dist_km, 0)} km`],
                 ['', `${LS.fmt(a.dist_ld, 2)} lunar distances`], ['', `${LS.fmt(a.dist_km / LS.R_EARTH, 0)} Earth radii`],
                 ['Relative speed', `${LS.fmt(a.v_rel, 2)} km/s`], ['Estimated size', sizeText(a.diameter_m)],
                 ['Abs. magnitude H', LS.fmt(a.H, 1)]])}
      </div>
      <div class="box"><h4>Live</h4><div id="fly-live"></div></div>`;
  }

  view.update = function (dt) {
    const jdRef = current ? current.jd : LS.nowJd();
    const jd = jdRef + view.clock.t / 86400;
    earth.spin.rotation.y = LS.gmst(jd);
    sun.position.copy(LS.v3(LS.sunDirection(jd), 50));
    earth.setSun(sun.position);
    moon.position.copy(LS.v3(LS.moonPosition(jd), S));
    if (!path || !rock) return;

    const n = path.jd.length;
    const f = Math.min(Math.max((jd - path.jd[0]) / (path.jd[n - 1] - path.jd[0]) * (n - 1), 0), n - 1);
    const k = Math.min(Math.floor(f), n - 2), u = f - k;
    const p = [0, 1, 2].map((i) => path.r[k][i] + (path.r[k + 1][i] - path.r[k][i]) * u);
    rock.position.copy(LS.v3(p, S));

    hudTimer -= dt;
    if (hudTimer <= 0 && $('fly-live')) {
      hudTimer = 0.2;
      const d = Math.hypot(...p);
      const dtCa = view.clock.t;
      $('fly-live').innerHTML = LS.kv([
        ['Distance now', `${LS.fmt(d, 0)} km`], ['', `${LS.fmt(d / LS.LD, 2)} LD`],
        [dtCa < 0 ? 'Closest approach in' : 'Closest approach was', LS.fmtDuration(Math.abs(dtCa)) + (dtCa < 0 ? '' : ' ago')]]);
    }
  };

  view.render = () => s3.render();
  view.clockLabel = (t) => LS.fmtUTC(LS.jdToDate((current ? current.jd : LS.nowJd()) + t / 86400));
  view.nowLabel = 'Closest';
  view.onNow = function () { view.clock.t = 0; view.clock.playing = false; };
})();
