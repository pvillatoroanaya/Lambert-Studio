/* Interactive diagrams for the Learn tab. Each widget is a function
   (container) -> { stop() } that builds its own controls and SVG drawing,
   computes the physics in the browser, and animates while visible. */
'use strict';

(function () {
  const W = {};
  LS.learnWidgets = W;
  const f = (x, d) => LS.fmt(x, d);
  const NS = 'http://www.w3.org/2000/svg';
  const G0 = 9.80665 / 1000;

  // Planet data for the widgets (NASA/JPL: GM km^3/s^2, equatorial radius km,
  // mean orbital speed km/s, mean distance AU, period days).
  const PL = {
    Venus: { mu: 324859, R: 6051.8, V: 35.02, a: 0.723, T: 224.7, color: '#e3bb76' },
    Earth: { mu: 398600.4, R: 6378.1, V: 29.78, a: 1.0, T: 365.25, color: '#5eb3e6' },
    Mars: { mu: 42828.4, R: 3396.2, V: 24.07, a: 1.524, T: 687.0, color: '#e8734a' },
    Jupiter: { mu: 126686534, R: 71492, V: 13.06, a: 5.203, T: 4332.6, color: '#d8a86d' },
    Saturn: { mu: 37931187, R: 60268, V: 9.68, a: 9.537, T: 10759, color: '#e8d18f' },
  };
  W.PLANETS = PL;

  /* ---------------- small helpers ---------------- */

  function el(tag, attrs = {}, parent) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (parent) parent.appendChild(e);
    return e;
  }

  function svg(container, w, h) {
    const s = el('svg', { viewBox: `0 0 ${w} ${h}`, class: 'lw-svg', role: 'img' });
    const defs = el('defs', {}, s);
    for (const [id, c] of [['w', '#e9ecf3'], ['b', '#5eb3e6'], ['g', '#7fcf9f'], ['o', '#eea55a'], ['r', '#ea7f7f']]) {
      const m = el('marker', { id: `lw-${id}`, markerWidth: 8, markerHeight: 8, refX: 6, refY: 4, orient: 'auto' }, defs);
      el('path', { d: 'M0,0 L8,4 L0,8z', fill: c }, m);
    }
    container.appendChild(s);
    return s;
  }

  function arrow(parent, x1, y1, x2, y2, color, id, width = 2, dash) {
    return el('line', { x1, y1, x2, y2, stroke: color, 'stroke-width': width, 'marker-end': `url(#lw-${id})`,
      ...(dash ? { 'stroke-dasharray': dash } : {}) }, parent);
  }

  function text(parent, x, y, t, color = '#c9d4ea', size = 11, anchor = 'start') {
    const e = el('text', { x, y, fill: color, 'font-size': size, 'text-anchor': anchor }, parent);
    e.textContent = t;
    return e;
  }

  /* A labelled slider: returns the input element. */
  function slider(box, label, min, max, step, value, fmt) {
    const wrap = document.createElement('label');
    wrap.className = 'lw-slider';
    wrap.innerHTML = `<span>${label}</span><input type="range" min="${min}" max="${max}" step="${step}" value="${value}"><b></b>`;
    box.appendChild(wrap);
    const input = wrap.querySelector('input'), out = wrap.querySelector('b');
    const show = () => { out.textContent = fmt(+input.value); };
    input.addEventListener('input', show);
    show();
    return input;
  }

  function select(box, label, options, value) {
    const wrap = document.createElement('label');
    wrap.className = 'lw-select';
    wrap.innerHTML = `<span>${label}</span><select>${options.map((o) => `<option${o === value ? ' selected' : ''}>${o}</option>`).join('')}</select>`;
    box.appendChild(wrap);
    return wrap.querySelector('select');
  }

  function frame(container, cls = '') {
    const box = document.createElement('div');
    box.className = `lw ${cls}`;
    const controls = document.createElement('div');
    controls.className = 'lw-controls';
    const stage = document.createElement('div');
    stage.className = 'lw-stage';
    const readout = document.createElement('div');
    readout.className = 'lw-readout';
    box.append(controls, stage, readout);
    container.appendChild(box);
    return { box, controls, stage, readout };
  }

  function animate(step) {
    let run = true, last = performance.now();
    const loop = (now) => {
      if (!run) return;
      const dt = Math.min((now - last) / 1000, 0.05);
      last = now;
      step(dt);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
    return { stop() { run = false; } };
  }

  /* ---------------- 1. Newton's cannon ---------------- */

  W.cannon = function (container) {
    const { controls, stage, readout } = frame(container);
    const v = slider(controls, 'Launch speed', 4, 12, 0.1, 7.6, (x) => `${f(x, 1)} km/s`);
    const alt = 400, R = 6378.1, mu = 398600.4;
    const s = svg(stage, 560, 360);
    const cx = 280, cy = 180, scale = 95 / R;
    el('circle', { cx, cy, r: R * scale, fill: '#1d4f7a', stroke: '#5eb3e6', 'stroke-opacity': 0.4 }, s);
    el('rect', { x: cx - 3, y: cy - (R + alt) * scale, width: 6, height: alt * scale, fill: '#8d95a8' }, s);
    const path = el('polyline', { fill: 'none', stroke: '#eea55a', 'stroke-width': 2 }, s);
    const ball = el('circle', { r: 4, fill: '#fff' }, s);
    text(s, cx, cy - (R + alt) * scale - 8, 'cannon on a 400 km mountain', '#8d95a8', 10.5, 'middle');
    let pts = [], k = 0, verdict = '';

    function simulate() {
      const v0 = +v.value;
      let x = 0, y = R + alt, vx = v0, vy = 0;
      pts = [[x, y]];
      const dt = 5;
      let crashed = false, escaped = false, angle = 0, prev = Math.atan2(x, y);
      for (let i = 0; i < 20000; i++) {
        const acc = (px, py) => { const r3 = Math.pow(px * px + py * py, 1.5); return [-mu * px / r3, -mu * py / r3]; };
        // RK4
        const [ax1, ay1] = acc(x, y);
        const [ax2, ay2] = acc(x + vx * dt / 2, y + vy * dt / 2);
        const [ax3, ay3] = acc(x + (vx + ax1 * dt / 2) * dt / 2, y + (vy + ay1 * dt / 2) * dt / 2);
        const [ax4, ay4] = acc(x + (vx + ax2 * dt / 2) * dt, y + (vy + ay2 * dt / 2) * dt);
        const nx = x + dt * (vx + dt / 6 * (ax1 + ax2 + ax3));
        const ny = y + dt * (vy + dt / 6 * (ay1 + ay2 + ay3));
        vx += dt / 6 * (ax1 + 2 * ax2 + 2 * ax3 + ax4);
        vy += dt / 6 * (ay1 + 2 * ay2 + 2 * ay3 + ay4);
        x = nx; y = ny;
        const r = Math.hypot(x, y);
        const a = Math.atan2(x, y);
        let d = a - prev; if (d < -Math.PI) d += 2 * Math.PI; if (d > Math.PI) d -= 2 * Math.PI;
        angle += d; prev = a;
        if (i % 3 === 0) pts.push([x, y]);
        if (r < R) { crashed = true; break; }
        if (r * scale > 400) { escaped = true; break; }
        if (angle > 2 * Math.PI) break;
      }
      pts.push([x, y]);
      const vc = Math.sqrt(mu / (R + alt)), ve = Math.sqrt(2 * mu / (R + alt));
      verdict = crashed ? `It falls back to Earth after travelling ${f(angle * R, 0)} km around it.`
        : v0 >= ve ? `It escapes: at ${f(ve, 2)} km/s or more, Earth's gravity can never pull it back.`
          : escaped ? 'A very stretched ellipse: it climbs far beyond this picture before falling back.'
          : Math.abs(v0 - vc) < 0.15 ? 'A circular orbit: it falls all the time, but the ground curves away just as fast.'
            : v0 > vc ? 'An elliptical orbit: it climbs higher on the far side, then falls back to the cannon.'
              : 'It never quite makes it round.';
      readout.innerHTML = `<b>${verdict}</b><br>Circular orbit at this height: ${f(vc, 2)} km/s · escape speed: ${f(ve, 2)} km/s
        (about ${f(vc * 3600, 0)} km/h: the whole way round Earth in ${f(2 * Math.PI * (R + alt) / vc / 60, 0)} minutes).`;
      path.setAttribute('points', pts.map((p) => `${cx + p[0] * scale},${cy - p[1] * scale}`).join(' '));
      k = 0;
    }
    v.addEventListener('input', simulate);
    simulate();
    return animate(() => {
      k = (k + 1.2) % pts.length;
      const p = pts[Math.floor(k)];
      ball.setAttribute('cx', cx + p[0] * scale);
      ball.setAttribute('cy', cy - p[1] * scale);
    });
  };

  /* ---------------- 2. Kepler: faster when closer ---------------- */

  W.kepler = function (container) {
    const { controls, stage, readout } = frame(container);
    const ecc = slider(controls, 'Eccentricity (how stretched)', 0, 0.85, 0.01, 0.6, (x) => f(x, 2));
    const s = svg(stage, 560, 340);
    const a = 200, cx = 300, cy = 170;
    const g = el('g', {}, s);
    let state = { M: 0 };
    function draw() {
      g.innerHTML = '';
      const e = +ecc.value, b = a * Math.sqrt(1 - e * e), c = a * e;
      // Sun at the focus (cx, cy); ellipse centre at cx - c.
      el('ellipse', { cx: cx - c, cy, rx: a, ry: b * 0.72, fill: 'none', stroke: '#5eb3e6', 'stroke-opacity': 0.6 }, g);
      // Equal-area sectors: 12 equal slices of TIME.
      for (let k = 0; k < 12; k++) {
        const pts = [[cx, cy]];
        for (let j = 0; j <= 10; j++) {
          const M = 2 * Math.PI * (k + j / 10) / 12;
          const E = LS.kepler(M, e);
          pts.push([cx - c + a * Math.cos(E), cy - b * 0.72 * Math.sin(E)]);
        }
        el('polygon', { points: pts.map((p) => p.join(',')).join(' '), fill: k % 2 ? 'rgba(94,179,230,0.10)' : 'rgba(238,165,90,0.10)',
          stroke: 'none' }, g);
      }
      el('circle', { cx, cy, r: 10, fill: '#eea55a' }, g);
      text(g, cx, cy + 26, 'Sun', '#eea55a', 11, 'middle');
      state.dot = el('circle', { r: 6, fill: '#fff' }, g);
      state.e = e; state.b = b; state.c = c;
      const ratio = (1 + e) / (1 - e);
      readout.innerHTML = `Each coloured slice is swept in the <b>same amount of time</b> (Kepler's second law), so the planet
        must move <b>${f(ratio, 1)}× faster</b> at its closest point than at its farthest. Stretching the orbit does not change
        its period as long as its size (the long axis) stays the same (Kepler's third law).`;
    }
    ecc.addEventListener('input', draw);
    draw();
    return animate((dt) => {
      state.M = (state.M + dt * 0.55) % (2 * Math.PI);
      const E = LS.kepler(state.M, state.e);
      state.dot.setAttribute('cx', cx - state.c + a * Math.cos(E));
      state.dot.setAttribute('cy', cy - state.b * 0.72 * Math.sin(E));
    });
  };

  /* ---------------- 3. Hohmann transfer ---------------- */

  W.hohmann = function (container) {
    const { controls, stage, readout } = frame(container);
    const ratio = slider(controls, 'Target orbit / starting orbit', 1.2, 30, 0.1, 6.3, (x) => `${f(x, 1)}×`);
    const s = svg(stage, 620, 330);
    const g = el('g', {}, s);
    const mu = 398600.4, r1 = 6678.1;
    function dv(q) {
      const r2 = r1 * q, a = (r1 + r2) / 2;
      const d1 = Math.sqrt(mu * (2 / r1 - 1 / a)) - Math.sqrt(mu / r1);
      const d2 = Math.sqrt(mu / r2) - Math.sqrt(mu * (2 / r2 - 1 / a));
      return [d1, d2];
    }
    function draw() {
      g.innerHTML = '';
      const q = +ratio.value;
      const cx = 160, cy = 165, maxR = 140, s1 = maxR / q;
      el('circle', { cx, cy, r: s1 * 0.95 < 4 ? 4 : s1 * 0.6, fill: '#1d4f7a' }, g);
      el('circle', { cx, cy, r: s1, fill: 'none', stroke: '#5eb3e6', 'stroke-width': 1.5 }, g);
      el('circle', { cx, cy, r: maxR, fill: 'none', stroke: '#7fcf9f', 'stroke-width': 1.5 }, g);
      const a = (s1 + maxR) / 2, c = (maxR - s1) / 2, b = Math.sqrt(s1 * maxR);
      el('path', { d: `M ${cx + s1} ${cy} A ${a} ${b} 0 0 0 ${cx - maxR} ${cy}`, fill: 'none', stroke: '#eea55a',
        'stroke-width': 2, 'stroke-dasharray': '5 3' }, g);
      el('circle', { cx: cx + s1, cy, r: 4, fill: '#e56f6f' }, g);
      el('circle', { cx: cx - maxR, cy, r: 4, fill: '#e56f6f' }, g);
      text(g, cx + s1 + 6, cy - 6, 'burn 1', '#ea7f7f', 10.5);
      text(g, cx - maxR - 4, cy - 8, 'burn 2', '#ea7f7f', 10.5, 'end');
      void c;
      // Chart: total dv against the ratio.
      const X0 = 350, X1 = 600, Y0 = 290, Y1 = 40;
      const xs = (x) => X0 + (Math.log(x) - Math.log(1.2)) / (Math.log(30) - Math.log(1.2)) * (X1 - X0);
      const ys = (y) => Y0 - y / 4.5 * (Y0 - Y1);
      el('line', { x1: X0, y1: Y0, x2: X1, y2: Y0, stroke: '#5d6c8c' }, g);
      el('line', { x1: X0, y1: Y0, x2: X0, y2: Y1, stroke: '#5d6c8c' }, g);
      const pts = [];
      for (let k = 0; k <= 80; k++) { const x = 1.2 * Math.pow(30 / 1.2, k / 80); const [d1, d2] = dv(x); pts.push(`${xs(x)},${ys(d1 + d2)}`); }
      el('polyline', { points: pts.join(' '), fill: 'none', stroke: '#eea55a', 'stroke-width': 2 }, g);
      const [d1, d2] = dv(q);
      el('circle', { cx: xs(q), cy: ys(d1 + d2), r: 5, fill: '#fff' }, g);
      text(g, X0, Y1 - 12, 'total Δv (km/s) vs how much bigger the orbit is', '#8d95a8', 10.5);
      [1, 2, 3, 4].forEach((y) => text(g, X0 - 6, ys(y) + 3, `${y}`, '#5d6c8c', 9.5, 'end'));
      [2, 5, 10, 20].forEach((x) => text(g, xs(x), Y0 + 14, `${x}×`, '#5d6c8c', 9.5, 'middle'));
      const alt2 = r1 * q - 6378.1;
      readout.innerHTML = `From a 300 km orbit to ${f(alt2, 0)} km altitude${Math.abs(q - 6.31) < 0.15 ? ' (geostationary)' : ''}:
        <b>burn 1 = ${f(d1, 2)} km/s</b> (speed up to stretch the orbit), coast half an ellipse, then <b>burn 2 = ${f(d2, 2)} km/s</b>
        (speed up again to round it off). Total <b>${f(d1 + d2, 2)} km/s</b>. Notice the curve: going further costs less and
        less extra: beyond about 15.6× the total even goes down. Above about 12×, a three-burn "bi-elliptic" transfer (out
        beyond the target, then back) can beat Hohmann: try it in the Maneuver tab.`;
    }
    ratio.addEventListener('input', draw);
    draw();
    return { stop() {} };
  };

  /* ---------------- 4. Rocket equation ---------------- */

  W.rocket = function (container) {
    const { controls, stage, readout } = frame(container);
    const dv = slider(controls, 'Change of speed Δv', 0.5, 15, 0.1, 6, (x) => `${f(x, 1)} km/s`);
    const eng = select(controls, 'Engine', ['Solid rocket (Isp 280 s)', 'Kerosene/oxygen (Isp 320 s)',
      'Hydrogen/oxygen (Isp 450 s)', 'Ion engine (Isp 3,000 s)'], 'Kerosene/oxygen (Isp 320 s)');
    const s = svg(stage, 560, 140);
    const g = el('g', {}, s);
    function draw() {
      const isp = +eng.value.match(/Isp ([\d,]+)/)[1].replace(',', '');
      const ve = isp * G0;
      const ratio = Math.exp(+dv.value / ve);
      const prop = 1 - 1 / ratio;
      g.innerHTML = '';
      el('rect', { x: 20, y: 40, width: 520, height: 44, rx: 6, fill: '#18233b' }, g);
      el('rect', { x: 20, y: 40, width: 520 * prop, height: 44, rx: 6, fill: '#eea55a' }, g);
      el('rect', { x: 20 + 520 * prop, y: 40, width: 520 * (1 - prop), height: 44, rx: 6, fill: '#5eb3e6' }, g);
      text(g, 26, 32, `propellant ${f(100 * prop, 1)}%`, '#eea55a', 12);
      text(g, 534, 32, `everything else ${f(100 * (1 - prop), 1)}%`, '#5eb3e6', 12, 'end');
      text(g, 280, 110, `m_start / m_end = e^(Δv / v_exhaust) = e^(${f(+dv.value, 1)} / ${f(ve, 2)}) = ${f(ratio, 2)}`, '#e9ecf3', 12, 'middle');
      readout.innerHTML = `The exhaust leaves at <b>${f(ve, 2)} km/s</b>. To change speed by ${f(+dv.value, 1)} km/s, <b>${f(100 * prop, 0)}%</b>
        of the spacecraft must be propellant. Every extra km/s multiplies the starting mass again, not adds to it:
        that is why mission designers fight for every 0.1 km/s, and why gravity assists matter so much.`;
    }
    dv.addEventListener('input', draw);
    eng.addEventListener('change', draw);
    draw();
    return { stop() {} };
  };

  /* ---------------- 5. Launch windows ---------------- */

  W.windows = function (container) {
    const { controls, stage, readout } = frame(container);
    const speed = slider(controls, 'Speed', 10, 120, 5, 50, (x) => `${x} days/s`);
    const s = svg(stage, 560, 330);
    const cx = 200, cy = 165, sc = 95;
    el('circle', { cx, cy, r: 9, fill: '#eea55a' }, s);
    el('circle', { cx, cy, r: sc, fill: 'none', stroke: '#5eb3e6', 'stroke-opacity': 0.4 }, s);
    el('circle', { cx, cy, r: sc * 1.524, fill: 'none', stroke: '#e8734a', 'stroke-opacity': 0.4 }, s);
    const earth = el('circle', { r: 6, fill: '#5eb3e6' }, s);
    const mars = el('circle', { r: 5, fill: '#e8734a' }, s);
    const lineE = el('line', { stroke: '#5eb3e6', 'stroke-opacity': 0.5 }, s);
    const lineM = el('line', { stroke: '#e8734a', 'stroke-opacity': 0.5 }, s);
    const lamp = el('circle', { cx: 470, cy: 60, r: 16 }, s);
    const lampText = text(s, 470, 96, '', '#c9d4ea', 11.5, 'middle');
    const phaseText = text(s, 470, 140, '', '#e9ecf3', 13, 'middle');
    const dayText = text(s, 470, 170, '', '#8d95a8', 11, 'middle');
    const need = 44.3;                               // Hohmann: Mars leads Earth by ~44 degrees at launch
    let t = 0, windows = 0, wasOpen = false;
    const nE = 360 / 365.25, nM = 360 / 687.0;
    const start = need + 180;                        // start half a synodic cycle away from a window
    return animate((dt) => {
      t += dt * +speed.value;
      const aE = nE * t, aM = start + nM * t;
      const P = (deg, r) => [cx + r * Math.cos(deg * Math.PI / 180), cy - r * Math.sin(deg * Math.PI / 180)];
      const [ex, ey] = P(aE, sc), [mx, my] = P(aM, sc * 1.524);
      earth.setAttribute('cx', ex); earth.setAttribute('cy', ey);
      mars.setAttribute('cx', mx); mars.setAttribute('cy', my);
      lineE.setAttribute('x1', cx); lineE.setAttribute('y1', cy); lineE.setAttribute('x2', ex); lineE.setAttribute('y2', ey);
      lineM.setAttribute('x1', cx); lineM.setAttribute('y1', cy); lineM.setAttribute('x2', mx); lineM.setAttribute('y2', my);
      let phase = ((aM - aE) % 360 + 360) % 360;
      const open = Math.abs(phase - need) < 6;
      if (open && !wasOpen) windows++;
      wasOpen = open;
      lamp.setAttribute('fill', open ? '#7fcf9f' : '#3a2530');
      lampText.textContent = open ? 'WINDOW OPEN: launch!' : 'window closed';
      phaseText.textContent = `Mars is ${f(phase, 0)}° ahead of Earth`;
      dayText.textContent = `day ${f(t, 0)} · windows so far: ${windows}`;
      readout.innerHTML = `A cheap (Hohmann-like) trip to Mars takes about 259 days, and Mars moves 136° around the Sun in that
        time. So at launch Mars must already be about <b>${f(need, 0)}° ahead</b> of Earth, or the spacecraft arrives at an
        empty point in space. Earth laps Mars once every <b>780 days (26 months)</b>, so the window opens only that often.`;
    });
  };

  /* ---------------- 6. Lambert's problem ---------------- */

  function lambert2d(r1, r2, dt, mu) {
    // Universal variables in 2D, prograde, bisection (as lambert_solver.py).
    const r1n = Math.hypot(...r1), r2n = Math.hypot(...r2);
    let dth = Math.acos(Math.max(-1, Math.min(1, (r1[0] * r2[0] + r1[1] * r2[1]) / (r1n * r2n))));
    if (r1[0] * r2[1] - r1[1] * r2[0] < 0) dth = 2 * Math.PI - dth;
    const A = Math.sin(dth) * Math.sqrt(r1n * r2n / (1 - Math.cos(dth)));
    const C = (z) => (z > 1e-8 ? (1 - Math.cos(Math.sqrt(z))) / z : z < -1e-8 ? (Math.cosh(Math.sqrt(-z)) - 1) / -z : 0.5 - z / 24);
    const S = (z) => (z > 1e-8 ? (Math.sqrt(z) - Math.sin(Math.sqrt(z))) / Math.pow(z, 1.5)
      : z < -1e-8 ? (Math.sinh(Math.sqrt(-z)) - Math.sqrt(-z)) / Math.pow(-z, 1.5) : 1 / 6 - z / 120);
    const y = (z) => r1n + r2n + A * (z * S(z) - 1) / Math.sqrt(C(z));
    const tof = (z) => { const yy = y(z); if (yy < 0) return NaN; return (Math.pow(yy / C(z), 1.5) * S(z) + A * Math.sqrt(yy)) / Math.sqrt(mu); };
    let lo = -40, hi = 4 * Math.PI * Math.PI * (1 - 1e-6);
    for (let k = 0; k < 120; k++) {
      const mid = (lo + hi) / 2, t = tof(mid);
      if (isNaN(t) || t < dt) lo = mid; else hi = mid;
    }
    const z = (lo + hi) / 2, yy = y(z);
    const fL = 1 - yy / r1n, g = A * Math.sqrt(yy / mu);
    return { v1: [(r2[0] - fL * r1[0]) / g, (r2[1] - fL * r1[1]) / g], dth, ok: isFinite(g) };
  }

  W.lambert = function (container) {
    const { controls, stage, readout } = frame(container);
    const ang = slider(controls, 'Where Mars is on arrival (angle)', 60, 300, 1, 160, (x) => `${x}°`);
    const days = slider(controls, 'Time of flight', 80, 500, 1, 230, (x) => `${x} days`);
    const s = svg(stage, 560, 340);
    const g = el('g', {}, s);
    const mu = 1.32712440018e11, AU = 1.495978707e8;
    function draw() {
      g.innerHTML = '';
      const cx = 280, cy = 170, sc = 95;
      el('circle', { cx, cy, r: 8, fill: '#eea55a' }, g);
      el('circle', { cx, cy, r: sc, fill: 'none', stroke: '#5eb3e6', 'stroke-opacity': 0.35 }, g);
      el('circle', { cx, cy, r: sc * 1.524, fill: 'none', stroke: '#e8734a', 'stroke-opacity': 0.35 }, g);
      let th = +ang.value * Math.PI / 180;
      // Exactly 180 degrees has no unique transfer plane (Lambert's singular case).
      if (Math.abs(th - Math.PI) < 2e-3) th += 4e-3;
      const r1 = [AU, 0], r2 = [1.524 * AU * Math.cos(th), 1.524 * AU * Math.sin(th)];
      const sol = lambert2d(r1, r2, +days.value * 86400, mu);
      // Draw the conic from r1 with v1 (2D orbit equation).
      const [vx, vy] = sol.v1, h = r1[0] * vy - r1[1] * vx;
      const ex = (vy * h) / mu - 1, ey = (-vx * h) / mu;
      const e = Math.hypot(ex, ey), w = Math.atan2(ey, ex), p = h * h / mu;
      const pts = [];
      for (let k = 0; k <= 120; k++) {
        const nu = (0 - w) + sol.dth * k / 120;
        const r = p / (1 + e * Math.cos(nu));
        pts.push(`${cx + r * Math.cos(nu + w) / AU * sc},${cy - r * Math.sin(nu + w) / AU * sc}`);
      }
      el('polyline', { points: pts.join(' '), fill: 'none', stroke: '#eea55a', 'stroke-width': 2.2 }, g);
      el('circle', { cx: cx + sc, cy, r: 6, fill: '#5eb3e6' }, g);
      text(g, cx + sc + 9, cy + 4, 'Earth at launch (r₁)', '#5eb3e6', 10.5);
      const mx = cx + 1.524 * sc * Math.cos(th), my = cy - 1.524 * sc * Math.sin(th);
      el('circle', { cx: mx, cy: my, r: 5, fill: '#e8734a' }, g);
      text(g, mx + 8, my - 6, 'Mars on arrival (r₂)', '#e8734a', 10.5);
      const vE = 29.78, dvx = vx - 0, dvy = vy - vE;
      const vinf = Math.hypot(dvx, dvy);
      const eType = e < 1 ? `an ellipse (e = ${f(e, 2)})` : `a hyperbola (e = ${f(e, 2)}): very fast`;
      readout.innerHTML = `<b>Lambert's problem:</b> given two positions and the time between them, find the orbit. Here the
        answer is ${eType}. Leaving Earth, the spacecraft must move ${f(Math.hypot(vx, vy), 1)} km/s around the Sun, which is
        <b>${f(vinf, 2)} km/s relative to Earth</b> (launch energy C₃ = ${f(vinf * vinf, 1)} km²/s²). Try to find the cheapest
        combination: that is exactly what the porkchop plot in the Mission tab does, thousands of times.`;
    }
    ang.addEventListener('input', draw);
    days.addEventListener('input', draw);
    draw();
    return { stop() {} };
  };

  /* ---------------- 7. The flyby sandbox ---------------- */

  W.sandbox = function (container, onResult) {
    const { controls, stage, readout } = frame(container, 'wide');
    const planet = select(controls, 'Planet', Object.keys(PL), 'Jupiter');
    const vinf = slider(controls, 'Arrival speed relative to the planet (v∞)', 2, 20, 0.1, 8, (x) => `${f(x, 1)} km/s`);
    const dir = slider(controls, 'Arrival direction', 0, 359, 1, 200, (x) => `${x}°`);
    const aim = slider(controls, 'Aim (how far to the side you pass)', -30, 30, 0.1, 6, (x) => `${x > 0 ? 'left' : x < 0 ? 'right' : 'centre'} ${f(Math.abs(x), 1)} radii`);
    const s = svg(stage, 760, 400);
    const g = el('g', {}, s);
    const dot = el('circle', { r: 5, fill: '#fff' }, s);
    let path = [], k = 0;

    function compute() {
      const P = PL[planet.value], v = +vinf.value, b = +aim.value * P.R;
      const th = +dir.value * Math.PI / 180;
      const u = [Math.cos(th), Math.sin(th)];
      const crash = { v };
      const rp = P.mu / (v * v) * (Math.sqrt(1 + Math.pow(b * v * v / P.mu, 2)) - 1);
      const turn = 2 * Math.asin(1 / (1 + rp * v * v / P.mu));
      const sgn = b >= 0 ? -1 : 1;                   // passing on the left bends the path to the right
      const out = [Math.cos(th + sgn * turn), Math.sin(th + sgn * turn)];
      const before = [P.V + v * u[0], v * u[1]], after = [P.V + v * out[0], v * out[1]];
      const gain = Math.hypot(...after) - Math.hypot(...before);
      return { P, v, b, th, u, out, rp, turn, sgn, before, after, gain, crash: rp < P.R };
    }

    function draw() {
      const r = compute();
      g.innerHTML = '';
      const cx = 250, cy = 200;
      const view = Math.max(5 * r.rp, 10 * r.P.R, Math.abs(r.b) * 1.6);
      const sc = 170 / view;
      // planet and its motion
      el('circle', { cx, cy, r: Math.max(r.P.R * sc, 3), fill: r.P.color }, g);
      arrow(g, cx - 60, cy + 150, cx + 60, cy + 150, '#eea55a', 'o', 2.5);
      text(g, cx, cy + 168, `${planet.value} moves this way around the Sun (${f(r.P.V, 1)} km/s)`, '#eea55a', 11, 'middle');
      // hyperbola: periapsis direction and velocity (same maths as the 3D close-up)
      const e = 1 + r.rp * r.v * r.v / r.P.mu, a = r.P.mu / (r.v * r.v);
      const half = Math.asin(1 / e);
      const qdir = r.th + r.sgn * half;              // periapsis velocity direction
      const pdir = qdir - r.sgn * Math.PI / 2;       // periapsis position: outside the bend (same side as the aim)
      path = [];
      for (let F = -4; F <= 4; F += 0.02) {
        const x = a * (e - Math.cosh(F)), y = a * Math.sqrt(e * e - 1) * Math.sinh(F);
        const X = x * Math.cos(pdir) + y * Math.cos(qdir), Y = x * Math.sin(pdir) + y * Math.sin(qdir);
        if (Math.hypot(X, Y) > view * 1.3) continue;
        path.push([cx + X * sc, cy - Y * sc, F]);
      }
      if (r.crash) {
        el('polyline', { points: path.filter((p) => p[2] < 0).map((p) => `${p[0]},${p[1]}`).join(' '), fill: 'none',
          stroke: '#e56f6f', 'stroke-width': 2.2 }, g);
      } else {
        el('polyline', { points: path.map((p) => `${p[0]},${p[1]}`).join(' '), fill: 'none', stroke: '#7fcf9f', 'stroke-width': 2.2 }, g);
      }
      // velocity triangle
      const tx = 560, ty = 220, ts = 170 / Math.max(r.P.V + r.v, 20);
      const T = (vx, vy) => [tx - (r.P.V + r.v) * ts * 0.5 + vx * ts, ty - vy * ts];
      const [ox, oy] = T(0, 0), [ax, ay] = T(r.P.V, 0);
      const [bx, by] = T(...r.before), [cx2, cy2] = T(...r.after);
      el('circle', { cx: ax, cy: ay, r: r.v * ts, fill: 'none', stroke: '#8d95a8', 'stroke-dasharray': '3 4', 'stroke-opacity': 0.5 }, g);
      arrow(g, ox, oy, ax, ay, '#eea55a', 'o', 2.2);
      arrow(g, ax, ay, bx, by, '#5eb3e6', 'b', 2);
      if (!r.crash) arrow(g, ax, ay, cx2, cy2, '#7fcf9f', 'g', 2);
      arrow(g, ox, oy, bx, by, '#8d95a8', 'w', 1.4, '5 4');
      if (!r.crash) arrow(g, ox, oy, cx2, cy2, '#ffffff', 'w', 2.4);
      text(g, tx, 60, 'Velocity triangle', '#5eb3e6', 11.5, 'middle');
      text(g, tx, 76, 'planet + v∞ = speed around the Sun', '#8d95a8', 10, 'middle');
      if (r.crash) {
        readout.innerHTML = `<b class="bad">Crash!</b> Aiming ${f(Math.abs(+aim.value), 1)} radii to the side at ${f(r.v, 1)} km/s,
          ${planet.value}'s gravity pulls the spacecraft into the planet. Aim further out.`;
        if (onResult) onResult(null);
        return;
      }
      const behind = Math.cos(pdir) < 0;             // periapsis on the trailing side of the planet?
      const alt = r.rp - r.P.R;
      readout.innerHTML = `Closest approach <b>${alt > 1e5 ? `${f(alt / 1000, 0)} thousand` : f(alt, 0)} km</b> above ${planet.value};
        path bent by <b>${f(r.turn * 180 / Math.PI, 1)}°</b>. Relative to the planet it leaves at ${f(r.v, 1)} km/s, exactly as it
        arrived. Around the Sun: ${f(Math.hypot(...r.before), 1)} → <b>${f(Math.hypot(...r.after), 1)} km/s</b>
        (<b class="${r.gain >= 0 ? 'good' : 'bad'}">${r.gain >= 0 ? '+' : ''}${f(r.gain, 2)} km/s</b>).
        You passed ${behind ? '<b>behind</b> the planet (on the side it is moving away from): its gravity dragged you along.'
          : '<b>in front of</b> the planet: you gave it some of your speed.'}`;
      if (onResult) onResult({ planet: planet.value, gain: r.gain, turn: r.turn, alt });
    }
    [planet, vinf, dir, aim].forEach((c) => c.addEventListener('input', draw));
    planet.addEventListener('change', draw);
    draw();
    return animate(() => {
      if (!path.length) return;
      k = (k + 1) % path.length;
      dot.setAttribute('cx', path[k][0]);
      dot.setAttribute('cy', path[k][1]);
    });
  };

  /* ---------------- 8. Ion vs chemical ---------------- */

  W.ion = function (container) {
    const { controls, stage, readout } = frame(container);
    const dv = slider(controls, 'Δv needed', 1, 15, 0.1, 6, (x) => `${f(x, 1)} km/s`);
    const thrust = slider(controls, 'Ion thrust', 10, 1000, 10, 90, (x) => `${x} mN`);
    const isp = slider(controls, 'Ion Isp', 1000, 5000, 100, 3100, (x) => `${x} s`);
    const s = svg(stage, 560, 150);
    const g = el('g', {}, s);
    const m0 = 1200;
    function draw() {
      g.innerHTML = '';
      const ve = +isp.value * G0, veC = 320 * G0;
      const pIon = m0 * (1 - Math.exp(-+dv.value / ve)), pChem = m0 * (1 - Math.exp(-+dv.value / veC));
      const time = pIon * ve * 1000 / (+thrust.value / 1000) / 86400;      // days of firing
      const bar = (y, frac, color, label) => {
        el('rect', { x: 150, y, width: 380, height: 22, rx: 5, fill: '#18233b' }, g);
        el('rect', { x: 150, y, width: 380 * frac, height: 22, rx: 5, fill: color }, g);
        text(g, 140, y + 15, label, '#c9d4ea', 11.5, 'end');
      };
      bar(30, pIon / m0, '#7fcf9f', `ion: ${f(pIon, 0)} kg`);
      bar(80, pChem / m0, '#eea55a', `chemical: ${f(pChem, 0)} kg`);
      text(g, 150, 18, `propellant needed by a ${m0} kg spacecraft`, '#8d95a8', 10.5);
      readout.innerHTML = `The ion engine needs <b>${f(pIon, 0)} kg</b> of xenon instead of ${f(pChem, 0)} kg of chemical propellant,
        but it has to fire for about <b>${f(time, 0)} days</b> (${f(time / 365.25, 1)} years) without stopping; the chemical engine
        does it in minutes. More thrust means more electrical power, and bigger solar panels.`;
    }
    [dv, thrust, isp].forEach((c) => c.addEventListener('input', draw));
    draw();
    return { stop() {} };
  };

  /* ---------------- 9. Measurement errors ---------------- */

  W.errors = function (container) {
    const { controls, stage, readout } = frame(container);
    const range = slider(controls, 'Distance to the satellite', 500, 40000, 100, 17000, (x) => `${f(x, 0)} km`);
    const angle = slider(controls, 'Angle error', 0.001, 0.1, 0.001, 0.01, (x) => `${f(x, 3)}°`);
    const s = svg(stage, 560, 220);
    const g = el('g', {}, s);
    function draw() {
      g.innerHTML = '';
      const err = +range.value * +angle.value * Math.PI / 180;
      const x0 = 40, y0 = 190, len = 40 + 460 * (+range.value / 40000);
      const spread = Math.min(Math.max(+angle.value * 12, 0.012), 0.6);
      el('path', { d: `M${x0},${y0} L${x0 + len},${y0 - len * 0.3 - len * spread} L${x0 + len},${y0 - len * 0.3 + len * spread} Z`,
        fill: 'rgba(255,138,128,0.18)', stroke: '#ea7f7f', 'stroke-opacity': 0.5 }, g);
      el('circle', { cx: x0, cy: y0, r: 6, fill: '#7fcf9f' }, g);
      text(g, x0, y0 + 20, 'station', '#7fcf9f', 10.5, 'middle');
      el('circle', { cx: x0 + len, cy: y0 - len * 0.3, r: 5, fill: '#fff' }, g);
      text(g, x0 + len - 8, y0 - len * 0.3 - len * spread - 8, `±${f(err, 2)} km`, '#ea7f7f', 12, 'end');
      readout.innerHTML = `A tiny angle error becomes a big position error far away: <b>${f(+angle.value, 3)}°</b> at
        ${f(+range.value, 0)} km is <b>±${f(err, 2)} km</b> sideways (distance × angle in radians). That uncertainty in position
        becomes an uncertainty in the orbit's size and period, and so in where the satellite will be tomorrow.`;
    }
    [range, angle].forEach((c) => c.addEventListener('input', draw));
    draw();
    return { stop() {} };
  };
})();
