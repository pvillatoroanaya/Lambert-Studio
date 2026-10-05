/* Gravity-assist close-up, shown by the mission playback when the
   spacecraft reaches a flyby planet.

   Everything is drawn from the real flyby: the incoming and outgoing
   velocities relative to the planet (v∞ in / out, from the Lambert legs)
   and the closest-approach distance fix a hyperbola in 3D. The spacecraft
   moves along it with the hyperbolic Kepler equation, so it really does
   speed up as it swings past the planet. Then the same flyby is replayed
   "as seen from the Sun", where the planet's own motion is added, and a
   velocity triangle shows where the gained (or lost) speed comes from.

   LS.flybyCloseup.play(event, { onDone }) -- event is a flyby event from
   flyby.describe() (it needs vinf_in_vec, vinf_out_vec, v_planet_vec,
   sun_dir, mu, radius, rp). */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const f = (x, d) => LS.fmt(x, d);
  const N = 900;                          // samples along the hyperbola
  const T_INTRO = 3.5, T_FLY = 15, T_HOLD = 2.5, T_SUN = 10, T_END = 8;   // seconds of animation
  const COLORS = { in: 0x5eb3e6, out: 0x7fcf9f, planet: 0xeea55a, helio: 0xffffff };

  const FX = { active: false };
  LS.flybyCloseup = FX;

  let s3 = null, group = null, planet = null, earth = null, craft = null, flame = null;
  let rel = null, helio = null, ghost = null, arrows = [], sunLight = null;
  let E = null, G = null;                 // the event and its geometry
  let clock = 0, paused = false, userCam = false, onDone = null, step = -1;

  /* ---------------- geometry of the flyby ---------------- */

  function geometry(e) {
    const R = e.radius, mu = e.mu;
    const vin = LS.v3(e.vinf_in_vec), vout = LS.v3(e.vinf_out_vec), vp = LS.v3(e.v_planet_vec);
    const uin = vin.clone().normalize(), uout = vout.clone().normalize();
    let h = new THREE.Vector3().crossVectors(uin, uout);
    if (h.length() < 1e-6) {                        // (almost) no bending: any perpendicular will do
      h = new THREE.Vector3().crossVectors(uin, Math.abs(uin.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0));
    }
    h.normalize();
    const rp = e.rp;
    const side = (v) => {
      const a = mu / (v * v), ecc = 1 + rp * v * v / mu;
      return { a, e: ecc, n: Math.sqrt(mu / (a * a * a)) };
    };
    const A = side(vin.length()), B = side(vout.length());
    // Periapsis velocity: the incoming direction turned by asin(1/e) toward
    // the outgoing one; periapsis position is perpendicular, outside the bend.
    const th = Math.asin(1 / A.e);
    const q = uin.clone().multiplyScalar(Math.cos(th)).add(new THREE.Vector3().crossVectors(h, uin).multiplyScalar(Math.sin(th))).normalize();
    const p = new THREE.Vector3().crossVectors(q, h).normalize();

    // How far out to draw: far enough that the path is nearly straight.
    const view = Math.max(4 * rp, 8 * R);
    const Fmax = (S) => Math.acosh(Math.max((view / S.a + 1) / S.e, 1.0001));
    const F0 = -Fmax(A), F1 = Fmax(B);
    const pts = [], times = [], speeds = [];
    for (let k = 0; k < N; k++) {
      const F = F0 + (F1 - F0) * k / (N - 1);
      const S = F < 0 ? A : B;
      const x = S.a * (S.e - Math.cosh(F)), y = S.a * Math.sqrt(S.e * S.e - 1) * Math.sinh(F);
      pts.push(p.clone().multiplyScalar(x / R).add(q.clone().multiplyScalar(y / R)));   // in planet radii
      times.push((S.e * Math.sinh(F) - F) / S.n);                                       // seconds from closest approach
      const r = S.a * (S.e * Math.cosh(F) - 1);
      speeds.push(Math.sqrt(Math.max((F < 0 ? vin : vout).lengthSq() + 2 * mu / r, 0)));
    }
    return {
      R, rp, vin, vout, vp, uin, uout, h, p, q, pts, times, speeds, view: view / R,
      vperi_in: Math.sqrt(vin.lengthSq() + 2 * mu / rp), vperi_out: Math.sqrt(vout.lengthSq() + 2 * mu / rp),
      helioBefore: vp.clone().add(vin), helioAfter: vp.clone().add(vout),
      sun: LS.v3(e.sun_dir).normalize(),
    };
  }

  /* Position (planet radii), speed and index at a time from closest approach. */
  function sample(t) {
    const tt = G.times;
    if (t <= tt[0]) return { pos: G.pts[0].clone(), speed: G.speeds[0], k: 0 };
    if (t >= tt[N - 1]) return { pos: G.pts[N - 1].clone(), speed: G.speeds[N - 1], k: N - 1 };
    let lo = 0, hi = N - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (tt[m] <= t) lo = m; else hi = m; }
    const u = (t - tt[lo]) / (tt[hi] - tt[lo]);
    return { pos: G.pts[lo].clone().lerp(G.pts[hi], u), speed: G.speeds[lo] + (G.speeds[hi] - G.speeds[lo]) * u, k: lo };
  }

  /* ---------------- the scene ---------------- */

  function ensureScene() {
    if (s3) return;
    s3 = new LS.Scene3D($('cv-fx'), { near: 1e-3, far: 1e5 });
    s3.scene.add(new THREE.AmbientLight(0x3a4466, 0.35));
    sunLight = new THREE.DirectionalLight(0xfff4e0, 1.05);
    s3.scene.add(sunLight);
    s3.controls.addEventListener('start', () => { userCam = true; });
    $('fx-skip').addEventListener('click', () => finish());
    $('fx-replay').addEventListener('click', () => { clock = 0; step = -1; userCam = false; paused = false; });
    $('fx-pause').addEventListener('click', () => { paused = !paused; });
    window.addEventListener('keydown', (ev) => {
      if (!FX.active) return;
      if (ev.code === 'Space') { paused = !paused; ev.preventDefault(); ev.stopImmediatePropagation(); }
      if (ev.code === 'Escape' || ev.code === 'Enter') { finish(); ev.preventDefault(); ev.stopImmediatePropagation(); }
    }, true);
  }

  function arrow(dir, origin, length, color, text, cls) {
    const a = new THREE.ArrowHelper(dir.clone().normalize(), origin, length, color, length * 0.16, length * 0.08);
    a.line.material.linewidth = 2;
    group.add(a);
    if (text) {
      const lb = LS.label(text, cls);
      lb.position.copy(origin).add(dir.clone().normalize().multiplyScalar(length * 1.08));
      group.add(lb);
      a.userData.label = lb;
      lb.userData.base = lb.position.clone();
    }
    a.userData.base = origin.clone();
    arrows.push(a);
    return a;
  }

  function planetMesh(name) {
    const g = new THREE.Group();
    if (name === 'Earth') {
      earth = LS.earth();
      g.add(earth.group);
      return g;
    }
    earth = null;
    const m = new THREE.Mesh(new THREE.SphereGeometry(1, 160, 112),
      LS.planetMaterial(name, `${name.toLowerCase()}.jpg`));
    g.add(m);
    if (name === 'Saturn') {
      const inner = 1.24, outer = 2.27;
      const rg = new THREE.RingGeometry(inner, outer, 180, 1);
      const pos = rg.attributes.position, uv = rg.attributes.uv, v = new THREE.Vector3();
      for (let k = 0; k < pos.count; k++) { v.fromBufferAttribute(pos, k); uv.setXY(k, (v.length() - inner) / (outer - inner), 0.5); }
      const ring = new THREE.Mesh(rg, new THREE.MeshStandardMaterial({ map: LS.texture('textures/saturn_ring.png'),
        side: THREE.DoubleSide, transparent: true, depthWrite: false, roughness: 1 }));
      ring.rotation.x = Math.PI / 2 - 0.47;
      g.add(ring);
    }
    return g;
  }

  function build() {
    if (group) {
      group.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.element) o.element.remove(); });
      s3.scene.remove(group);
    }
    group = new THREE.Group();
    arrows = [];
    s3.scene.add(group);
    const V = G.view;

    planet = planetMesh(E.planet);
    group.add(planet);
    const pl = LS.label(E.planet, 'warm');
    pl.position.set(0, 1.25, 0);
    planet.add(pl);
    sunLight.position.copy(G.sun).multiplyScalar(100);
    if (earth) earth.setSun(G.sun);

    // The whole path, faint, and the part flown so far, bright.
    ghost = LS.line(G.pts, 0x8b9bbd, 0.35, true);
    ghost.material.dashSize = V * 0.02; ghost.material.gapSize = V * 0.014; ghost.computeLineDistances();
    group.add(ghost);
    rel = new THREE.Line(new THREE.BufferGeometry().setFromPoints(G.pts),
      new THREE.LineBasicMaterial({ color: COLORS.out, transparent: true, opacity: 0.95 }));
    const col = new Float32Array(N * 3);
    const cIn = new THREE.Color(COLORS.in), cOut = new THREE.Color(COLORS.out);
    for (let k = 0; k < N; k++) (G.times[k] < 0 ? cIn : cOut).toArray(col, 3 * k);
    rel.geometry.setAttribute('color', new THREE.BufferAttribute(col, 3));
    rel.material.vertexColors = true;
    rel.material.color.set(0xffffff);
    rel.geometry.setDrawRange(0, 0);
    group.add(rel);

    // The same flyby seen from the Sun (planet motion added), built later.
    helio = null;

    // Closest-approach marker.
    const peri = G.p.clone().multiplyScalar(G.rp / G.R);
    const dot = LS.dot(V * 0.006, 0xffffff);
    dot.position.copy(peri);
    const plb = LS.label('closest approach', '');
    plb.position.copy(peri.clone().multiplyScalar(1.12));
    G.periMark = new THREE.Group();
    G.periMark.add(dot, plb);
    group.add(G.periMark);

    // Arrows: v∞ in at the start, v∞ out at the end, the planet's motion,
    // and the direction of the Sun.
    const L = V * 0.28, vmax = Math.max(G.vin.length(), G.vout.length());
    arrow(G.uin, G.pts[0], L * G.vin.length() / vmax, COLORS.in, `arrives · ${f(G.vin.length(), 1)} km/s`, 'accent');
    arrow(G.uout, G.pts[N - 1].clone().sub(G.uout.clone().multiplyScalar(L * 0.1)), L * G.vout.length() / vmax, COLORS.out,
      `leaves · ${f(G.vout.length(), 1)} km/s`, 'accent');
    const pm = arrow(G.vp, new THREE.Vector3().add(G.h.clone().multiplyScalar(-V * 0.02)).add(G.vp.clone().normalize().multiplyScalar(1.3)),
      V * 0.3, COLORS.planet, `${E.planet} moves this way around the Sun · ${f(G.vp.length(), 1)} km/s`, 'warm');
    pm.userData.planetMotion = true;
    const sunA = arrow(G.sun, G.sun.clone().multiplyScalar(-V * 0.85).add(G.h.clone().multiplyScalar(V * 0.05)), V * 0.16, 0xffd27a,
      'to the Sun', 'warm');
    sunA.userData.sunArrow = true;

    craft = LS.spacecraft(V * 0.022, { color: 0x5eb3e6 });
    group.add(craft);
    flame = LS.glowSprite(0xff9a3c, V * 0.05);
    flame.visible = false;
    craft.add(flame);

    // Camera: above the flyby plane (from the ecliptic north side), tilted
    // toward the closest-approach side so the spacecraft passes in front.
    const hUp = G.h.y >= 0 ? G.h.clone() : G.h.clone().negate();
    G.camDir = hUp.multiplyScalar(Math.cos(0.7)).add(G.p.clone().multiplyScalar(Math.sin(0.7))).normalize();
    G.camDist = V * 2.6;
    s3.controls.target.set(0, 0, 0);
    s3.camera.position.copy(G.camDir).multiplyScalar(G.camDist * 1.6);
    s3.controls.maxDistance = V * 60;
  }

  /* After the relative-frame animation: the path as seen from the Sun. */
  function buildHelio() {
    const Vp = G.vp.clone().divideScalar(G.R);         // planet radii per second
    const pts = G.pts.map((q, k) => q.clone().add(Vp.clone().multiplyScalar(G.times[k])));
    helio = new THREE.Group();
    const path = LS.line(pts, 0xffffff, 0.95);
    path.geometry.setDrawRange(0, 0);
    helio.userData.path = path;
    // Where the spacecraft would have gone if the planet weren't there:
    // straight on with its speed around the Sun from before the flyby.
    const vb = G.helioBefore.clone().divideScalar(G.R);
    const straight = [pts[0], pts[0].clone().add(vb.multiplyScalar(G.times[N - 1] - G.times[0]))];
    const ghostLine = LS.line(straight, 0x8b9bbd, 0.6, true);
    ghostLine.material.dashSize = G.view * 0.03; ghostLine.material.gapSize = G.view * 0.02; ghostLine.computeLineDistances();
    const gl = LS.label(`without ${E.planet}: straight on at ${f(E.v_helio_before, 1)} km/s`, '');
    gl.position.copy(straight[0].clone().lerp(straight[1], 0.8));
    helio.add(path, ghostLine, gl);
    group.add(helio);
    G.helioPts = pts;
  }

  /* ---------------- side panels ---------------- */

  const STEPS = ['Approach', 'Closest approach', 'Departure', 'Seen from the Sun'];

  function stepText(k) {
    const e = E, vin = G.vin.length(), vout = G.vout.length();
    const alt = e.altitude > 1e5 ? `${f(e.altitude / 1000, 0)} thousand km` : `${f(e.altitude, 0)} km`;
    const burn = e.dv > 0.05;
    switch (k) {
      case 0: return `Seen from ${e.planet}, the spacecraft comes in at <b>${f(vin, 1)} km/s</b>. As it falls toward the
        planet, gravity pulls it faster and faster, like a skateboarder dropping into a half-pipe.`;
      case 1: return `Closest approach: <b>${alt}</b> above ${e.planet} (${f(e.altitude_radii, 1)} radii from its centre),
        moving at <b>${f(G.vperi_in, 1)} km/s</b>, its fastest. Here gravity bends the path the most.
        ${burn ? `The engine fires here for ${f(e.dv, 2)} km/s: a burn at the fastest point is the most efficient
        (the Oberth effect).` : 'No engine is used: the planet does all the work.'}`;
      case 2: return `Climbing away, it slows down again and leaves at <b>${f(vout, 1)} km/s</b>
        ${burn ? '(the burn changed that speed a little). ' : '— exactly as fast as it arrived. '}The only thing the planet changed is the <b>direction</b>: the path has
        turned by <b>${f(e.turn_deg, 0)}°</b>. So where does the gain come from? From the planet's own motion…`;
      default: {
        const g = e.gain;
        return `Now add ${e.planet}'s own motion around the Sun (<b>${f(G.vp.length(), 1)} km/s</b>). Before the flyby the
          spacecraft moved at <b>${f(e.v_helio_before, 1)} km/s</b> around the Sun; afterwards at
          <b>${f(e.v_helio_after, 1)} km/s</b>. ${g >= 0
            ? `It has <b>gained ${f(g, 1)} km/s</b> by being turned to point more along the planet's motion: the planet
               dragged it along and slowed down by an unmeasurably small amount in return.`
            : `It has <b>lost ${f(-g, 1)} km/s</b>: it was turned to point against the planet's motion, so ${e.planet}
               worked as a free brake and the spacecraft now falls closer to the Sun.`}`;
      }
    }
  }

  function renderSteps(active) {
    $('fx-steps').innerHTML = STEPS.map((s, k) => `<div class="${k === active ? 'on' : k < active ? 'done' : ''}">
      <div class="n">${k + 1}</div><div><b>${s}</b>${k === active ? `<p>${stepText(k)}</p>` : ''}</div></div>`).join('');
  }

  /* Velocity triangle: planet velocity + v∞ = velocity around the Sun,
     before (v∞ in) and after (v∞ out). Flattened onto the plane that
     contains the planet's velocity and the change in velocity. */
  function triangleSvg() {
    const e1 = G.vp.clone().normalize();
    const dv = G.vout.clone().sub(G.vin);
    let e2 = dv.clone().sub(e1.clone().multiplyScalar(dv.dot(e1)));
    if (e2.length() < 1e-6) e2 = G.vin.clone().sub(e1.clone().multiplyScalar(G.vin.dot(e1)));
    e2.normalize();
    const P2 = (v) => [v.dot(e1), v.dot(e2)];
    const O = [0, 0], A = [G.vp.length(), 0];
    const bi = P2(G.vin), bo = P2(G.vout);
    const B1 = [A[0] + bi[0], A[1] + bi[1]], B2 = [A[0] + bo[0], A[1] + bo[1]];
    const r = (G.vin.length() + G.vout.length()) / 2;
    // The planet's arrow is usually much longer than v∞: then zoom in on
    // its tip, where the flyby happens (the arrows from the origin come in
    // from the left edge).
    const zoom = A[0] > 3 * r;
    const xs = [A[0] - (zoom ? 1.6 * r : A[0]), A[0] + 1.15 * r, B1[0], B2[0]];
    const ys = [A[1] - 1.15 * r, A[1] + 1.15 * r, B1[1], B2[1]];
    const W = 300, H = 210, pad = 26;
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const s = Math.min((W - 2 * pad) / (x1 - x0 || 1), (H - 2 * pad) / (y1 - y0 || 1));
    const X = (p) => (pad + (p[0] - x0) * s).toFixed(1), Y = (p) => (H - pad - (p[1] - y0) * s).toFixed(1);
    const line = (a, b, c, w, dash = '', m = '') =>
      `<line x1="${X(a)}" y1="${Y(a)}" x2="${X(b)}" y2="${Y(b)}" stroke="${c}" stroke-width="${w}" ${dash ? `stroke-dasharray="${dash}"` : ''} marker-end="url(#m${m})"/>`;
    const txt = (p, t, c, dx = 0, dy = 0, anchor = 'middle') =>
      `<text x="${(+X(p) + dx).toFixed(1)}" y="${(+Y(p) + dy).toFixed(1)}" fill="${c}" font-size="10.5" text-anchor="${anchor}">${t}</text>`;
    const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    const mk = (id, c) => `<marker id="m${id}" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8z" fill="${c}"/></marker>`;
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Velocity triangle">
      <defs>${mk('p', '#eea55a')}${mk('i', '#5eb3e6')}${mk('o', '#7fcf9f')}${mk('b', '#8d95a8')}${mk('a', '#ffffff')}</defs>
      <circle cx="${X(A)}" cy="${Y(A)}" r="${(r * s).toFixed(1)}" fill="none" stroke="#8d95a8" stroke-opacity=".35" stroke-dasharray="3 4"/>
      ${line(O, B1, '#8d95a8', 1.6, '5 4', 'b')}
      ${line(O, B2, '#ffffff', 2.4, '', 'a')}
      ${line(O, A, '#eea55a', 2.2, '', 'p')}
      ${line(A, B1, '#5eb3e6', 2, '', 'i')}
      ${line(A, B2, '#7fcf9f', 2, '', 'o')}
      ${zoom ? txt([x0, 0], `${E.planet} ${f(G.vp.length(), 1)} ⟶`, '#eea55a', 4, 14, 'start')
        : txt(mid(O, A), `${E.planet} ${f(G.vp.length(), 1)}`, '#eea55a', 0, 14)}
      ${zoom ? `<text x="4" y="${(H - 6)}" fill="#5d6c8c" font-size="9.5">zoomed in on the tip of ${E.planet}'s arrow</text>` : ''}
      ${txt(B1, `before ${f(E.v_helio_before, 1)}`, '#c9d4ea', 0, B1[1] >= A[1] ? -8 : 15)}
      ${txt(B2, `after ${f(E.v_helio_after, 1)}`, '#ffffff', 0, B2[1] >= A[1] ? -8 : 15)}
    </svg>
    <div class="fx-legend"><span style="--c:#eea55a">planet's motion</span><span style="--c:#5eb3e6">v∞ in</span>
      <span style="--c:#7fcf9f">v∞ out</span><span style="--c:#fff">speed around the Sun</span></div>
    <p>Relative to ${E.planet}, the flyby can only <b>rotate</b> the arrow (it stays on the dashed circle, same length).
      Adding ${E.planet}'s motion turns that rotation into a change of speed around the Sun. Speeds in km/s; drawn flat on one plane.</p>`;
  }

  function renderSide() {
    const e = E;
    $('fx-side').innerHTML = `<div class="box"><h4>Velocity triangle</h4>${triangleSvg()}</div>
      <div class="box"><h4>This flyby</h4>${LS.kv([
        ['Closest distance', e.altitude > 1e5 ? `${f(e.altitude / 1000, 0)}k km altitude` : `${f(e.altitude, 0)} km altitude`],
        ['Path bent by', `${f(e.turn_deg, 1)}° (max ${f(e.max_turn_deg, 0)}°)`],
        ['Speed vs planet', `${f(G.vin.length(), 2)} → ${f(G.vout.length(), 2)} km/s`],
        ['Fastest (closest)', `${f(G.vperi_in, 1)} km/s`],
        ['Around the Sun', `${f(e.v_helio_before, 2)} → ${f(e.v_helio_after, 2)} km/s`],
        ['Engine burn', e.dv > 0.01 ? `${f(e.dv, 2)} km/s` : 'none'],
      ])}</div>`;
  }

  /* ---------------- playing ---------------- */

  FX.available = (e) => !!(e && e.kind === 'flyby' && e.vinf_in_vec && e.rp);

  FX.play = function (e, opts = {}) {
    if (!FX.available(e)) { if (opts.onDone) opts.onDone(); return; }
    E = e;
    onDone = opts.onDone || null;
    $('fx').hidden = false;
    ensureScene();
    s3.resize();
    G = geometry(e);
    build();
    renderSide();
    const again = opts.again ? ' (second pass)' : '';
    $('fx-title').textContent = `${e.planet} gravity assist${again}`;
    $('fx-sub').textContent = `${LS.fmtDate(LS.jdToDate(e.jd))} · closest approach ${e.altitude > 1e5
      ? `${f(e.altitude / 1000, 0)} thousand` : f(e.altitude, 0)} km · ${e.gain >= 0 ? '+' : '−'}${f(Math.abs(e.gain), 1)} km/s around the Sun`;
    clock = 0; step = -1; paused = false; userCam = false;
    FX.active = true;
  };

  function finish() {
    if (!FX.active) return;
    FX.active = false;
    $('fx').hidden = true;
    const cb = onDone; onDone = null;
    if (cb) cb();
  }

  /* Close without continuing (the player itself was closed). */
  FX.stop = function () {
    if (!FX.active) return;
    FX.active = false;
    onDone = null;
    $('fx').hidden = true;
  };

  const TOTAL = T_INTRO + T_FLY + T_HOLD + T_SUN + T_END;

  FX.frame = function (dt) {
    if (!FX.active) return;
    if (!paused) clock += dt;
    if (clock >= TOTAL) { finish(); return; }
    const tSpan = G.times[N - 1] - G.times[0];
    let tReal, k, phase;
    if (clock < T_INTRO) { tReal = G.times[0]; phase = 0; }
    else if (clock < T_INTRO + T_FLY) { tReal = G.times[0] + tSpan * (clock - T_INTRO) / T_FLY; phase = 1; }
    else if (clock < T_INTRO + T_FLY + T_HOLD) { tReal = G.times[N - 1]; phase = 2; }
    else {
      tReal = G.times[0] + tSpan * Math.min((clock - T_INTRO - T_FLY - T_HOLD) / T_SUN, 1);
      phase = 3;
    }
    const S = sample(tReal);
    k = S.k;

    // Which explanation step we are in.
    const rNow = S.pos.length() * G.R;
    let want;
    if (phase === 3) want = 3;
    else if (phase === 0) want = 0;
    else if (phase === 2) want = 2;
    else want = tReal < 0 ? (rNow < G.rp * 2.2 ? 1 : 0) : (rNow < G.rp * 2.2 ? 1 : 2);
    if (want !== step) {
      step = want;
      renderSteps(step);
      $('fx-side').classList.toggle('sun', step === 3);
    }

    if (phase < 3) {
      if (helio) {
        helio.traverse((o) => { if (o.geometry) o.geometry.dispose(); if (o.element) o.element.remove(); });
        group.remove(helio); helio = null;
      }
      arrows.forEach((a) => { a.position.copy(a.userData.base); if (a.userData.label) a.userData.label.position.copy(a.userData.label.userData.base); });
      planet.position.set(0, 0, 0);
      craft.position.copy(S.pos);
      rel.geometry.setDrawRange(0, phase === 0 ? 0 : k + 1);
      rel.visible = true; ghost.visible = true; G.periMark.visible = true;
      arrows.forEach((a) => { a.visible = true; if (a.userData.label) a.userData.label.userData.hide = false; });
      LS.aimCraft(craft, G.pts[Math.min(k + 3, N - 1)]);
      flame.visible = E.dv > 0.05 && Math.abs(tReal) < (G.times[N - 1] - G.times[0]) * 0.015;
    } else {
      // Heliocentric frame: the planet moves along its arrow, the path is
      // the relative hyperbola carried along with it.
      if (!helio) {
        buildHelio();
        rel.visible = false; ghost.visible = false; G.periMark.visible = false;
        arrows.forEach((a) => { a.visible = !!(a.userData.planetMotion || a.userData.sunArrow); if (a.userData.label) a.userData.label.userData.hide = !a.visible; });
      }
      const Vp = G.vp.clone().divideScalar(G.R);
      planet.position.copy(Vp.clone().multiplyScalar(tReal));
      craft.position.copy(S.pos.clone().add(planet.position));
      helio.userData.path.geometry.setDrawRange(0, k + 1);
      arrows.forEach((a) => {
        if (!a.userData.planetMotion) return;
        a.position.copy(a.userData.base).add(planet.position);
        a.userData.label.position.copy(a.userData.label.userData.base).add(planet.position);
      });
      LS.aimCraft(craft, G.helioPts[Math.min(k + 3, N - 1)]);
      flame.visible = false;
    }
    planet.rotation.y += dt * 0.15;
    if (earth) earth.setSun(G.sun);

    // Camera: frame the planet and spacecraft, closer near periapsis.
    if (!userCam) {
      const close = phase === 1 || phase === 2 ? Math.min(1, S.pos.length() / G.view) : 1;
      const dist = phase === 3 ? G.camDist * 1.5 : G.camDist * (0.55 + 0.45 * close);
      const target = phase === 3 ? planet.position.clone()
        : S.pos.clone().multiplyScalar(0.35 * (phase === 0 ? 0 : 1));
      const want3 = target.clone().add(G.camDir.clone().multiplyScalar(dist));
      const a = 1 - Math.exp(-dt * 1.6);
      s3.controls.target.lerp(target, a);
      s3.camera.position.lerp(want3, a);
    }
    s3.render();

    // Clock and progress.
    const hrs = tReal / 3600;
    const tt = Math.abs(hrs) < 48 ? `${hrs < 0 ? '−' : '+'}${f(Math.abs(hrs), 1)} h` : `${hrs < 0 ? '−' : '+'}${f(Math.abs(hrs) / 24, 1)} days`;
    const frame = phase === 3 ? `speed around the Sun ${f(helioSpeed(tReal), 1)} km/s`
      : `speed relative to ${E.planet} ${f(S.speed, 1)} km/s`;
    $('fx-clock').innerHTML = `closest approach ${tt} · <b>${frame}</b>${paused ? ' · paused' : ''}`;
    $('fx-prog').style.width = `${(100 * clock / TOTAL).toFixed(1)}%`;
    $('fx-pause').textContent = paused ? '▶ Resume' : '❚❚ Pause';
  };

  /* Speed around the Sun during the flyby: planet velocity + relative velocity. */
  function helioSpeed(t) {
    const a = sample(t - 30).pos, b = sample(t + 30).pos;
    const vrel = b.sub(a).multiplyScalar(G.R / 60);
    return vrel.add(G.vp).length();
  }
})();
