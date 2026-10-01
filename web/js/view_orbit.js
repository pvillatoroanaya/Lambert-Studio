/* Orbit determination view: inputs -> /api/solve -> 3D orbit around a
   rotating Earth, with the satellite moving along it in time. */
'use strict';

(function () {
  const S = 1 / LS.R_EARTH;            // scene unit = one Earth radius
  const $ = (id) => document.getElementById(id);

  const view = {
    id: 'orbit',
    title: 'Orbit determination',
    subtitle: 'Inertial frame (ECI) · drag to rotate · scroll to zoom · right-drag to pan',
    clock: new LS.Clock({
      t: 0, min: 0, max: 1, rate: 600, loop: true, playing: true,
      rates: [[60, '60×'], [300, '300×'], [600, '600×'], [1800, '1800×'], [3600, '3600×']],
    }),
    sol: null,
  };
  LS.views.orbit = view;

  let s3, earth, sun, orbitGroup, sat, station, los, hudLive;

  view.init = function () {
    // Inputs first: solving must work even if 3D graphics are unavailable.
    wireInputs();
    s3 = new LS.Scene3D($('cv-orbit'), { near: 0.001, far: 5e4 });
    earth = LS.earth();
    s3.scene.add(earth.group);
    s3.scene.add(new THREE.AmbientLight(0x6070a0, 0.35));
    sun = new THREE.DirectionalLight(0xffffff, 1.25);
    s3.scene.add(sun);

    // Equatorial plane and the vernal-equinox direction (ECI +X).
    const grid = new THREE.PolarGridHelper(12, 12, 6, 96, 0x2a3b60, 0x1a2640);
    grid.material.transparent = true; grid.material.opacity = 0.35;
    s3.scene.add(grid);
    const xAxis = LS.line([new THREE.Vector3(0, 0, 0), new THREE.Vector3(13, 0, 0)], 0x3b5486, 0.8);
    s3.scene.add(xAxis);
    const xl = LS.label('X  ♈ vernal equinox', 'dim'); xl.position.set(13.3, 0, 0); s3.scene.add(xl);
    const zAxis = LS.line([new THREE.Vector3(0, 1, 0), new THREE.Vector3(0, 4, 0)], 0x3b5486, 0.8);
    s3.scene.add(zAxis);
    const zl = LS.label('Z  north', 'dim'); zl.position.set(0, 4.2, 0); s3.scene.add(zl);

    s3.camera.position.set(9, 5, 12);
    s3.controls.minDistance = 1.3;
    s3.controls.maxDistance = 400;
    s3.setFollowables([
      { label: 'Satellite', obj: () => sat || null },
      { label: 'Earth', obj: () => earth.surface },
      { label: 'Ground station', obj: () => (station ? station.children[0] : null) },
    ]);
  };

  /* ---------------- inputs ---------------- */

  function mode() { return document.querySelector('#mode-seg .on').dataset.mode; }

  function wireInputs() {
    document.querySelectorAll('#mode-seg button').forEach((b) => b.addEventListener('click', () => {
      document.querySelectorAll('#mode-seg button').forEach((x) => x.classList.toggle('on', x === b));
      $('in-obs').hidden = b.dataset.mode !== 'observations';
      $('in-vec').hidden = b.dataset.mode !== 'vectors';
    }));
    $('btn-solve').addEventListener('click', solve);
    document.querySelector('[data-for="orbit"]').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') solve();
    });
    $('btn-report').addEventListener('click', () => {
      $('report-text').textContent = view.sol.report;
      $('modal').hidden = false;
    });
    $('btn-example').addEventListener('click', resetExample);
  }

  const DEFAULTS = {
    'st-x': '1344.143', 'st-y': '6068.601', 'st-z': '1429.311',
    'o1-date': '2023-04-02', 'o1-time': '00:30:00', 'o1-az': '132.67', 'o1-el': '32.44', 'o1-rng': '16945.450',
    'o2-date': '2023-04-02', 'o2-time': '03:00:00', 'o2-az': '123.08', 'o2-el': '50.06', 'o2-rng': '37350.340',
    'r1-x': '5000', 'r1-y': '10000', 'r1-z': '2100', 'r2-x': '-14600', 'r2-y': '2500', 'r2-z': '7000', 'tof': '3600',
  };
  function resetExample() {
    for (const [id, v] of Object.entries(DEFAULTS)) $(id).value = v;
    $('prograde').checked = true;
  }

  function request() {
    const v = (id) => $(id).value;
    return {
      mode: mode(), prograde: $('prograde').checked,
      station: [v('st-x'), v('st-y'), v('st-z')],
      obs1: { date: v('o1-date'), time: v('o1-time'), az: v('o1-az'), el: v('o1-el'), rng: v('o1-rng') },
      obs2: { date: v('o2-date'), time: v('o2-time'), az: v('o2-az'), el: v('o2-el'), rng: v('o2-rng') },
      r1: [v('r1-x'), v('r1-y'), v('r1-z')], r2: [v('r2-x'), v('r2-y'), v('r2-z')], tof: v('tof'),
    };
  }

  async function solve() {
    $('orbit-err').hidden = true;
    try {
      const sol = await LS.busy('Solving Lambert\'s problem…', $('btn-solve'), () => LS.api('/api/solve', request()));
      view.sol = sol;
      LS.solution = sol;
      if (s3) draw(sol); else renderHud(sol);
      $('btn-report').disabled = false;
      $('empty-orbit').hidden = true;
      LS.emit('solved', sol);
      if (view.onSolved) view.onSolved(sol);
    } catch (e) {
      $('orbit-err').textContent = e.message;
      $('orbit-err').hidden = false;
    }
  }

  /* ---------------- drawing ---------------- */

  function draw(sol) {
    if (orbitGroup) {
      orbitGroup.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.element) o.element.remove(); });
      s3.scene.remove(orbitGroup);
    }
    if (station) { earth.spin.remove(station); station.traverse((o) => o.element && o.element.remove()); station = null; }
    orbitGroup = new THREE.Group();
    s3.scene.add(orbitGroup);

    const pts = sol.track.r.map((p) => LS.v3(p, S));
    const rmax = Math.max(...pts.map((p) => p.length()));
    const w = Math.max(rmax * 0.0022, 0.012);

    orbitGroup.add(LS.tube(pts, w, 0x5eb3e6, sol.track.closed, 0.9));
    orbitGroup.add(LS.tube(sol.arc.map((p) => LS.v3(p, S)), w * 2.2, 0xeea55a));

    const obsLabel = sol.mode === 'observations' ? ['r₁ · obs 1', 'r₂ · obs 2'] : ['r₁', 'r₂'];
    [sol.r1, sol.r2].forEach((r, k) => {
      const p = LS.v3(r, S);
      const l = LS.line([new THREE.Vector3(), p], 0xeea55a, 0.7, true);
      l.material.dashSize = rmax * 0.02; l.material.gapSize = rmax * 0.012; l.computeLineDistances();
      orbitGroup.add(l);
      const d = LS.dot(w * 4, 0xe56f6f); d.position.copy(p); orbitGroup.add(d);
      const lb = LS.label(obsLabel[k], 'warm'); lb.position.copy(p); orbitGroup.add(lb);
    });

    // Apsides, found directly on the sampled track.
    const radii = pts.map((p) => p.length());
    const iP = radii.indexOf(Math.min(...radii));
    addMark(pts[iP], 'perigee', w);
    if (sol.track.closed) addMark(pts[radii.indexOf(Math.max(...radii))], 'apogee', w);

    sat = LS.spacecraft(Math.max(rmax * 0.012, 0.04), { label: 'satellite' });
    orbitGroup.add(sat);

    if (sol.station_ecef) {
      station = new THREE.Group();
      const d = LS.dot(0.022, 0x7fcf9f);
      station.add(d);
      station.add(LS.glowSprite(0x7fcf9f, 0.12));
      const lb = LS.label('station', 'dim'); station.add(lb);
      station.position.copy(LS.v3(sol.station_ecef, S));
      earth.spin.add(station);
      los = LS.line([new THREE.Vector3(), new THREE.Vector3()], 0x7fcf9f, 0.7);
      orbitGroup.add(los);
    } else los = null;

    const c = view.clock;
    c.min = sol.track.t[0];
    c.max = sol.track.t[sol.track.t.length - 1];
    c.t = 0;
    c.loop = sol.track.closed;
    c.playing = true;
    s3.focusOn(new THREE.Vector3(), rmax * 2.6);
    s3.controls.maxDistance = rmax * 20;
    renderHud(sol);
    LS.syncTimebar();
  }

  function addMark(p, text, w) {
    const d = LS.dot(w * 2.6, 0xe7edf8); d.position.copy(p); orbitGroup.add(d);
    const l = LS.label(text, 'dim'); l.position.copy(p); orbitGroup.add(l);
  }

  function renderHud(sol) {
    const e = sol.elements, f = LS.fmt;
    const badge = `<span class="badge">${e.orbit_type}</span>`;
    $('hud-orbit').innerHTML = `
      <div class="box"><h4>Orbit ${badge}</h4>
        ${LS.kv([
          ['Semi-major axis a', `${f(e.a, 1)} km`], ['Eccentricity e', f(e.e, 5)],
          ['Inclination i', `${f(e.i, 3)}°`], ['RAAN Ω', `${f(e.RAAN, 3)}°`],
          ['Arg. of perigee ω', `${f(e.argp, 3)}°`], ['True anomaly ν₁', `${f(e.nu, 3)}°`],
          ['Period', LS.fmtDuration(e.period)],
          ['Perigee altitude', `${f(e.alt_p, 0)} km`],
          ['Apogee altitude', e.alt_a === null ? '—' : `${f(e.alt_a, 0)} km`]])}
      </div>
      <div class="box"><h4>Live</h4><div id="hud-orbit-live"></div></div>
      <div class="box"><h4>Check</h4>
        ${LS.kv([['|v₁|', `${f(Math.hypot(...sol.v1), 4)} km/s`], ['|v₂|', `${f(Math.hypot(...sol.v2), 4)} km/s`],
                 ['Energy difference', `${Math.abs(sol.energy[0] - sol.energy[1]).toExponential(1)} km²/s²`]])}
      </div>`;
    hudLive = $('hud-orbit-live');
  }

  /* ---------------- per frame ---------------- */

  const tmp = new THREE.Vector3(), stW = new THREE.Vector3();
  let hudTimer = 0;

  view.update = function (dt) {
    if (!s3) return;
    const jd = (view.sol ? view.sol.jd0 : LS.nowJd()) + view.clock.t / 86400;
    earth.spin.rotation.y = LS.gmst(jd);
    earth.clouds.rotation.y += dt * 0.004;
    const sd = LS.sunDirection(jd);
    sun.position.copy(LS.v3(sd, 50));
    earth.setSun(sun.position);

    if (view.sol) {
      const tr = view.sol.track, n = tr.t.length;
      const f = Math.min(Math.max((view.clock.t - tr.t[0]) / (tr.t[n - 1] - tr.t[0]) * (n - 1), 0), n - 1);
      const k = Math.min(Math.floor(f), n - 2), u = f - k;
      const a = tr.r[k], b = tr.r[k + 1];
      const p = [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u];
      sat.position.copy(LS.v3(p, S));
      LS.aimCraft(sat, LS.v3(tr.r[Math.min(k + 2, n - 1)], S));

      let elev = null;
      if (station) {
        station.getWorldPosition(stW);
        tmp.copy(sat.position).sub(stW).normalize();
        elev = Math.asin(tmp.dot(stW.clone().normalize())) / LS.DEG;
        los.visible = elev > 0;
        if (los.visible) {
          los.geometry.setFromPoints([stW, sat.position]);
        }
      }

      hudTimer -= dt;
      if (hudTimer <= 0 && hudLive) {
        hudTimer = 0.2;
        const r = Math.hypot(...p), a_ = view.sol.elements.a;
        const v = Math.sqrt(LS.MU_EARTH * (2 / r - 1 / a_));
        const rows = [['Time from obs 1', LS.fmtDuration(Math.abs(view.clock.t)) + (view.clock.t < 0 ? ' before' : '')],
          ['Altitude', `${LS.fmt(r - LS.R_EARTH, 0)} km`], ['Speed', `${LS.fmt(v, 3)} km/s`]];
        if (elev !== null) rows.push(['Seen from station', elev > 0
          ? `<span class="badge ok">el ${LS.fmt(elev, 1)}°</span>` : '<span class="badge warn">below horizon</span>']);
        hudLive.innerHTML = LS.kv(rows);
      }
    }
  };

  view.render = () => s3 && s3.render();
  // For orbit_uncertainty.js: the scene, the scale and the current inputs.
  view.scene = () => s3;
  view.scale = S;
  view.request = request;
  view.mode = mode;

  view.clockLabel = function (t) {
    if (!view.sol) return '—';
    return LS.fmtUTC(LS.jdToDate(view.sol.jd0 + t / 86400));
  };
  view.nowLabel = 'Back to obs 1';
  view.onNow = function () { view.clock.t = 0; };
})();
