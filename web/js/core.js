/* Lambert Studio — shared helpers: API calls, formatting, astronomy,
   and the Three.js building blocks every 3D view uses. */
'use strict';

const LS = (window.LS = {});

LS.R_EARTH = 6378.137;           // km
LS.MU_EARTH = 398600.4418;       // km^3/s^2
LS.AU = 1.495978707e8;           // km
LS.LD = 384400;                  // km, lunar distance
LS.DEG = Math.PI / 180;
LS.OBLIQUITY = 23.43928 * LS.DEG;

LS.views = {};             // filled in by the view_*.js files
LS.solution = null;        // latest Lambert solution, shared between views

/* Tiny event bus between views. */
const _handlers = {};
LS.on = (name, fn) => { (_handlers[name] = _handlers[name] || []).push(fn); };
LS.emit = (name, data) => (_handlers[name] || []).forEach((fn) => fn(data));

/* ------------------------------------------------------------------ */
/* server API                                                          */
/* ------------------------------------------------------------------ */

LS.api = async function (path, body) {
  const opt = body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  };
  let res;
  for (let attempt = 0; ; attempt++) {
    try {
      res = await fetch(path, opt);
      break;
    } catch (e) {
      // A momentary connection hiccup: try once more before giving up.
      if (attempt >= 1) {
        if (LS.report) LS.report(`Request failed twice: ${path}: ${e}`);
        throw new Error('The Lambert Studio server is not responding. Restart the app.');
      }
      await new Promise((r) => setTimeout(r, 800));
    }
  }
  const js = await res.json();
  if (!js.ok) throw new Error(js.error || 'Request failed');
  return js.data;
};

LS.status = function (text, kind) {
  const el = document.getElementById('status');
  el.className = 'status' + (kind ? ' ' + kind : '');
  document.getElementById('status-text').textContent = text;
};

/* Run an async task with the busy indicator and a button spinner. */
LS.busy = async function (label, button, fn) {
  LS.status(label, 'busy');
  if (button) { button.disabled = true; button.classList.add('busy'); }
  try {
    const out = await fn();
    LS.status('Ready');
    return out;
  } catch (e) {
    LS.status('Error', 'error');
    throw e;
  } finally {
    if (button) { button.disabled = false; button.classList.remove('busy'); }
  }
};

/* ------------------------------------------------------------------ */
/* formatting                                                          */
/* ------------------------------------------------------------------ */

LS.fmt = (x, d = 2) => (x === null || x === undefined || !isFinite(x)) ? '—'
  : Number(x).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
LS.jdToDate = (jd) => new Date((jd - 2440587.5) * 86400000);
LS.dateToJd = (d) => d.getTime() / 86400000 + 2440587.5;
LS.nowJd = () => LS.dateToJd(new Date());
LS.fmtUTC = (d) => d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
LS.fmtDate = (d) => d.toISOString().slice(0, 10);
LS.fmtDuration = function (s) {
  if (s === null || !isFinite(s)) return '—';
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.round(s % 60);
  if (h >= 48) return `${LS.fmt(s / 86400, 1)} days`;
  return h ? `${h} h ${m} min` : `${m} min ${sec} s`;
};
LS.esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

LS.kv = (pairs) => '<div class="kv">' +
  pairs.map(([k, v]) => `<span>${k}</span><span>${v}</span>`).join('') + '</div>';

LS.download = function (filename, text) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};

/* ------------------------------------------------------------------ */
/* astronomy                                                           */
/* ------------------------------------------------------------------ */

/* Greenwich Mean Sidereal Time [rad] — same formula as time_utils.py. */
LS.gmst = function (jd) {
  const T = (jd - 2451545.0) / 36525.0;
  let s = 67310.54841 + (876600 * 3600 + 8640184.812866) * T + 0.093104 * T * T - 6.2e-6 * T * T * T;
  s = ((s % 86400) + 86400) % 86400;
  return (s / 240) * LS.DEG;
};

/* Solve Kepler's equation M = E - e sin E. */
LS.kepler = function (M, e) {
  let E = e < 0.8 ? M : Math.PI;
  for (let k = 0; k < 12; k++) {
    const d = (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E));
    E -= d;
    if (Math.abs(d) < 1e-12) break;
  }
  return E;
};

/* Perifocal (xp, yp) -> frame, for node O, inclination i, arg. peri w [rad]. */
LS.rotate313 = function (xp, yp, O, i, w, out) {
  const cO = Math.cos(O), sO = Math.sin(O), ci = Math.cos(i), si = Math.sin(i),
    cw = Math.cos(w), sw = Math.sin(w);
  out[0] = (cO * cw - sO * sw * ci) * xp + (-cO * sw - sO * cw * ci) * yp;
  out[1] = (sO * cw + cO * sw * ci) * xp + (-sO * sw + cO * cw * ci) * yp;
  out[2] = (sw * si) * xp + (cw * si) * yp;
  return out;
};

/* Planet elements come from /api/planets (Standish, as in planets.py). */
LS.planetTable = null;
LS.loadPlanets = async function () {
  if (!LS.planetTable) {
    LS.planetTable = await LS.api('/api/planets');
    LS.eph.init(LS.planetTable.ephemeris);
  }
  return LS.planetTable;
};

/* Asteroid data is shared by the Flybys and Solar views; fetch it once. */
const _neo = {};
LS.getNeo = function (group) {
  if (!_neo[group]) {
    _neo[group] = LS.api(`/api/neo?group=${group}`);
    _neo[group].catch(() => { delete _neo[group]; });   // allow a retry
  }
  return _neo[group];
};

LS.planetElements = function (name, jd) {
  const { base, rate } = LS.planetTable.elements[name];
  const T = (jd - 2451545.0) / 36525.0;
  const [a, e, I, L, peri, node] = base.map((b, k) => b + rate[k] * T);
  return { a, e, I, L, peri, node };
};

/* ------------------------------------------------------------------ */
/* NASA/JPL DE440s ephemeris, streamed from the server in chunks and   */
/* interpolated here (cubic Hermite, using the velocities), so the     */
/* animation stays smooth while the positions are JPL-accurate. Until  */
/* a chunk arrives, the approximate formulas below are used instead.   */
/* ------------------------------------------------------------------ */

LS.eph = (function () {
  const J0 = 2451545.0;
  const P_DAYS = 400, M_DAYS = 8, M_STEP = 1 / 24;
  const chunks = { p: new Map(), m: new Map() };
  const pending = new Set();
  const api = { enabled: false, source: 'approximate formulas' };

  function fetchChunk(kind, key) {
    const id = kind + key;
    if (pending.has(id)) return;
    pending.add(id);
    const url = kind === 'p'
      ? `/api/ephemeris?start=${J0 + key * P_DAYS}&step=1&n=${P_DAYS + 1}`
      : `/api/moon?start=${J0 + key * M_DAYS}&step=${M_STEP}&n=${Math.round(M_DAYS / M_STEP) + 1}`;
    LS.api(url).then((d) => chunks[kind].set(key, d)).catch(() => { /* stay on the fallback */ });
  }

  function chunkFor(kind, jd) {
    const size = kind === 'p' ? P_DAYS : M_DAYS;
    const key = Math.floor((jd - J0) / size);
    const c = chunks[kind].get(key);
    // Prefetch the neighbour the clock is heading into.
    const frac = (jd - J0) / size - key;
    if (frac > 0.7) fetchChunk(kind, key + 1);
    else if (frac < 0.3) fetchChunk(kind, key - 1);
    if (!c) fetchChunk(kind, key);
    return c;
  }

  function hermite(p0, v0, p1, v1, h, s, out) {
    const s2 = s * s, s3 = s2 * s;
    const a = 2 * s3 - 3 * s2 + 1, b = s3 - 2 * s2 + s, c = -2 * s3 + 3 * s2, d = s3 - s2;
    for (let i = 0; i < 3; i++) out[i] = a * p0[i] + b * h * v0[i] + c * p1[i] + d * h * v1[i];
    return out;
  }

  function locate(c, jd) {
    const n = c.jd.length;
    const f = (jd - c.jd[0]) / c.step;
    if (f < 0 || f > n - 1) return null;
    const k = Math.min(Math.floor(f), n - 2);
    return [k, f - k];
  }

  /* Heliocentric ecliptic [AU] */
  api.planet = function (name, jd, out) {
    if (!api.enabled) return null;
    const c = chunkFor('p', jd);
    const at = c && locate(c, jd);
    if (!at) return null;
    const P = c.planets[name], [k, s] = at;
    return hermite(P.r[k], P.v[k], P.r[k + 1], P.v[k + 1], c.step, s, out);
  };

  /* Geocentric ICRF [km] */
  api.moon = function (jd, out) {
    if (!api.enabled) return null;
    const c = chunkFor('m', jd);
    const at = c && locate(c, jd);
    if (!at) return null;
    const [k, s] = at;
    return hermite(c.r[k], c.v[k], c.r[k + 1], c.v[k + 1], c.step * 86400, s, out);
  };

  api.init = function (status) {
    api.enabled = !!(status && status.available);
    api.source = api.enabled ? 'NASA/JPL DE440s' : 'approximate formulas';
    if (api.enabled) { fetchChunk('p', Math.floor((LS.nowJd() - J0) / P_DAYS)); }
  };
  return api;
})();

/* Heliocentric ecliptic position [AU] of a planet. */
LS.planetPos = function (name, jd, out = [0, 0, 0]) {
  if (LS.eph.planet(name, jd, out)) return out;
  const el = LS.planetElements(name, jd);
  const M = ((((el.L - el.peri + 180) % 360) + 360) % 360 - 180) * LS.DEG;
  const E = LS.kepler(M, el.e);
  const xp = el.a * (Math.cos(E) - el.e);
  const yp = el.a * Math.sqrt(1 - el.e * el.e) * Math.sin(E);
  return LS.rotate313(xp, yp, el.node * LS.DEG, el.I * LS.DEG, (el.peri - el.node) * LS.DEG, out);
};

/* Closed orbit of a planet [AU], elements frozen at jd. */
LS.planetOrbit = function (name, jd, n = 360) {
  const el = LS.planetElements(name, jd);
  const pts = [];
  const p = el.a * (1 - el.e * el.e);
  for (let k = 0; k <= n; k++) {
    const nu = (2 * Math.PI * k) / n;
    const r = p / (1 + el.e * Math.cos(nu));
    pts.push(LS.rotate313(r * Math.cos(nu), r * Math.sin(nu),
      el.node * LS.DEG, el.I * LS.DEG, (el.peri - el.node) * LS.DEG, [0, 0, 0]));
  }
  return pts;
};

LS.eclToEq = function (v) {
  const c = Math.cos(LS.OBLIQUITY), s = Math.sin(LS.OBLIQUITY);
  return [v[0], c * v[1] - s * v[2], s * v[1] + c * v[2]];
};

/* Unit vector Earth -> Sun in the equatorial (ECI) frame. */
LS.sunDirection = function (jd) {
  const e = LS.planetPos('Earth', jd);
  const s = LS.eclToEq([-e[0], -e[1], -e[2]]);
  const n = Math.hypot(s[0], s[1], s[2]);
  return [s[0] / n, s[1] / n, s[2] / n];
};

/* Geocentric Moon position [km, ECI], low-precision series
   (Astronomical Almanac; ~0.3 deg, a few thousand km). */
LS.moonPosition = function (jd) {
  const exact = LS.eph.moon(jd, [0, 0, 0]);
  if (exact) return exact;
  const T = (jd - 2451545.0) / 36525.0, d = LS.DEG, sin = Math.sin, cos = Math.cos;
  const lam = 218.32 + 481267.881 * T
    + 6.29 * sin((135.0 + 477198.87 * T) * d) - 1.27 * sin((259.3 - 413335.36 * T) * d)
    + 0.66 * sin((235.7 + 890534.22 * T) * d) + 0.21 * sin((269.9 + 954397.74 * T) * d)
    - 0.19 * sin((357.5 + 35999.05 * T) * d) - 0.11 * sin((186.5 + 966404.03 * T) * d);
  const bet = 5.13 * sin((93.3 + 483202.02 * T) * d) + 0.28 * sin((228.2 + 960400.89 * T) * d)
    - 0.28 * sin((318.3 + 6003.15 * T) * d) - 0.17 * sin((217.6 - 407332.21 * T) * d);
  const par = 0.9508 + 0.0518 * cos((135.0 + 477198.87 * T) * d) + 0.0095 * cos((259.3 - 413335.36 * T) * d)
    + 0.0078 * cos((235.7 + 890534.22 * T) * d) + 0.0028 * cos((269.9 + 954397.74 * T) * d);
  const r = LS.R_EARTH / sin(par * d);
  const l = lam * d, b = bet * d;
  return LS.eclToEq([r * cos(b) * cos(l), r * cos(b) * sin(l), r * sin(b)]);
};

/* ------------------------------------------------------------------ */
/* Three.js building blocks                                            */
/* ------------------------------------------------------------------ */

/* Physics frames have z = north / ecliptic pole; Three.js has y up. */
LS.v3 = (p, s = 1) => new THREE.Vector3(p[0] * s, p[2] * s, -p[1] * s);
LS.setXYZ = (arr, k, p, s = 1) => { arr[3 * k] = p[0] * s; arr[3 * k + 1] = p[2] * s; arr[3 * k + 2] = -p[1] * s; };

/* Solar-system views: heliocentric position [AU] -> scene position.
   Real distances span 0.4 AU (Mercury) to 30 AU (Neptune), so at true
   scale the outer planets are off-screen whenever the inner ones are
   visible. With compression on (the default), every point keeps its
   direction but its distance r becomes sqrt(r): Earth stays at 1, and
   Neptune comes in to 5.5, so all eight planets fit at once. */
LS.helioScale = (p) => {
  if (!LS.settings.compress) return 1;
  const r = Math.hypot(p[0], p[1], p[2]);
  return r > 0 ? Math.sqrt(r) / r : 0;
};
LS.sv3 = (p) => LS.v3(p, LS.helioScale(p));
LS.setSXYZ = (arr, k, p) => LS.setXYZ(arr, k, p, LS.helioScale(p));

/* User display settings, remembered between sessions on this computer. */
LS.settings = (function () {
  const defaults = { bloom: true, milkyway: true, fps: false, compress: true, quality: 'auto', fx: true };
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('ls-settings') || '{}'); } catch (e) { /* ignore */ }
  return Object.assign({}, defaults, saved);
})();
LS.scenes = [];
LS.applySettings = function () {
  try { localStorage.setItem('ls-settings', JSON.stringify(LS.settings)); } catch (e) { /* ignore */ }
  LS.scenes.forEach((s) => s.applySettings());
};

class Scene3D {
  constructor(container, { fov = 45, near = 0.01, far = 1e7 } = {}) {
    this.container = container;
    // ONE WebGL renderer (and canvas) is shared by every 3D view: browsers
    // allow only ~16 WebGL contexts per page and drop the oldest beyond
    // that. Only one view is on screen at a time, so whichever scene is
    // being drawn moves the shared canvas into its own container.
    if (!Scene3D.shared) {
      // 'high-performance' asks for the dedicated GPU on laptops that also
      // have an integrated one.
      const r = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true,
        powerPreference: 'high-performance' });
      // Which graphics chip did the browser give us? A laptop's integrated
      // chip cannot supersample like a dedicated card, so quality starts
      // lower there (see LS.applyQuality) and adapts to the frame rate.
      const gl = r.getContext();
      const info = gl.getExtension('WEBGL_debug_renderer_info');
      const gpuName = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : '';
      LS.gpu = { name: gpuName, discrete: /nvidia|geforce|rtx|gtx|radeon rx|radeon pro|arc a/i.test(gpuName) };
      LS.aniso = r.capabilities.getMaxAnisotropy();
      Scene3D.shared = r;
      LS.applyQuality(true);
      // If the GPU driver resets, the scene can be rebuilt by reloading.
      r.domElement.addEventListener('webglcontextlost', (e) => {
        e.preventDefault();
        if (LS.report) LS.report('WebGL context lost');
        LS.status('Graphics were reset, reloading…', 'busy');
        setTimeout(() => location.reload(), 1500);
      });
      r.setClearColor(0x03050b, 1);
      Scene3D.shared = r;
    }
    this.renderer = Scene3D.shared;

    this.labels = new THREE.CSS2DRenderer();
    Object.assign(this.labels.domElement.style, { position: 'absolute', top: '0', left: '0', pointerEvents: 'none' });
    container.appendChild(this.labels.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(fov, 1, near, far);
    this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.rotateSpeed = 0.6;
    // Zoom limits for every view (views tighten them to their own scale):
    // never into the camera's near plane, never beyond the background sky.
    this.controls.minDistance = near * 3;
    this.controls.maxDistance = far * 0.2;
    this._near = near;
    this._far = far;

    // Glow ("bloom"): only the brightest pixels -- the Sun, satellites,
    // highlighted markers -- bleed light into their surroundings.
    // ONE glow pipeline (and one set of multisampled buffers) is shared by
    // every view: a private pipeline per view would keep a full-size
    // multisampled buffer alive for each tab ever opened.
    this.composer = null;
    if (THREE.EffectComposer && THREE.UnrealBloomPass) {
      if (!Scene3D.composer) {
        const target = new THREE.WebGLRenderTarget(256, 256, { type: THREE.HalfFloatType, samples: LS.gpu.discrete ? 4 : 2 });
        Scene3D.composer = new THREE.EffectComposer(this.renderer, target);
        Scene3D.renderPass = new THREE.RenderPass(this.scene, this.camera);
        Scene3D.composer.addPass(Scene3D.renderPass);
        Scene3D.composer.addPass(new THREE.UnrealBloomPass(new THREE.Vector2(256, 256), 0.6, 0.4, 0.86));
      }
      this.composer = Scene3D.composer;
    }

    // Background: the Milky Way panorama, or plain stars.
    const skyR = far * 0.5;
    this.sky = new THREE.Mesh(new THREE.SphereGeometry(skyR, 64, 32),
      new THREE.MeshBasicMaterial({ map: LS.texture('textures/milky_way.jpg'), side: THREE.BackSide,
        depthWrite: false, color: 0x8a8f9c }));
    this.sky.renderOrder = -10;
    this.stars = LS.stars(skyR * 0.9);
    this.sky.userData.noPick = this.stars.userData.noPick = true;
    this.scene.add(this.sky, this.stars);

    LS.scenes.push(this);
    this.applySettings();
    this._initFreeCamera();
    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
  }
  applySettings() {
    this.sky.visible = LS.settings.milkyway;
    this.stars.visible = !LS.settings.milkyway;
  }
  /* Is this the scene currently drawn on the shared canvas? */
  get active() { return Scene3D.current === this; }
  _attach() {
    const el = this.renderer.domElement;
    if (Scene3D.current === this && el.parentNode === this.container) return;
    Scene3D.current = this;
    this.container.insertBefore(el, this.container.firstChild);
    // Only the scene on screen reacts to the mouse.
    LS.scenes.forEach((s) => { s.controls.enabled = s === this && s.mode === 'orbit'; });
    this.resize();
  }
  resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h) return;
    if (this.active) this.renderer.setSize(w, h);
    this.labels.setSize(w, h);
    if (this.composer && this.active) {
      this.composer.setPixelRatio(this.renderer.getPixelRatio());
      this.composer.setSize(w, h);
    }
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }
  render() {
    this._attach();
    const now = performance.now();
    const dt = Math.min((now - this._lastT) / 1000, 0.1);
    this._lastT = now;
    if (!this.home) this._saveHome();
    this._stepCamera(dt);
    if (this.mode === 'orbit' && !this.anim) this.controls.update();
    this._guardCamera();
    this._lightPlanets();
    this.sky.position.copy(this.camera.position);      // the sky is always "at infinity"
    this.stars.position.copy(this.camera.position);
    if (this.composer && LS.settings.bloom) {
      Scene3D.renderPass.scene = this.scene;
      Scene3D.renderPass.camera = this.camera;
      this.composer.render();
    }
    else this.renderer.render(this.scene, this.camera);
    this._syncLabels();
    this.labels.render(this.scene, this.camera);
    if ((this._frame = (this._frame || 0) + 1) % 6 === 0) this._declutter();
  }
  /* Labels never cover each other or the panels floating over the scene:
     a label that would overlap one already placed, or a panel, fades out
     until the camera moves and there is room again. Labels claim space in
     order of importance: 'key' (Earth), then events (accent, warm), then
     plain names, then dim hints. Measured every few frames to keep it cheap. */
  _declutter() {
    const view = this.container.closest('.view') || this.container.parentElement;
    const pad = 3;
    const rank = (el) => {
      const c = el.classList;
      return c.contains('key') ? 0 : c.contains('accent') || c.contains('warm') ? 1 : c.contains('dim') ? 3 : 2;
    };
    const blockers = [...view.querySelectorAll('.hud > *, .legend, .camtools, .phase')]
      .filter((el) => el.offsetParent !== null && !el.hidden)
      .map((el) => el.getBoundingClientRect());
    const labels = [...this.labels.domElement.children]
      .filter((o) => o.style.display !== 'none' && o.firstChild)
      .map((o) => o.firstChild)
      .sort((a, b) => rank(a) - rank(b));
    const placed = [];
    const hit = (r, q) => r.left < q.right + pad && r.right > q.left - pad && r.top < q.bottom + pad && r.bottom > q.top - pad;
    for (const el of labels) {
      const r = el.getBoundingClientRect();
      if (!r.width) continue;
      const covered = blockers.some((q) => hit(r, q)) || placed.some((q) => hit(r, q));
      el.classList.toggle('hid', covered);
      if (!covered) placed.push(r);
    }
  }
  /* The label renderer only looks at a label's own `visible` flag, so a
     label on a hidden object would still be drawn (hidden planets sit at
     the origin, which put "Neptune" on top of the Sun). A label is shown
     only if every ancestor is visible and it is not switched off
     (userData.hide). */
  _syncLabels() {
    const walk = (o, parentShown) => {
      const shown = parentShown && o.visible !== false;
      if (o.isCSS2DObject) o.visible = parentShown && !o.userData.hide;
      for (const c of o.children) walk(c, o.isCSS2DObject ? parentShown : shown);
    };
    walk(this.scene, true);
  }
  /* Frame a point from the current viewing direction. Views call this
     after drawing something new; it also becomes the "Reset" view. */
  focusOn(target, distance) {
    if (!target || !this._finite(target) || !Number.isFinite(distance) || distance <= 0) return;
    distance = Math.min(Math.max(distance, this.controls.minDistance), this.controls.maxDistance);
    if (this.mode === 'fly') this.setMode('orbit');
    if (this.follow) this.setFollow(null);
    const dir = this._viewDir();
    this.controls.target.copy(target);
    this.camera.position.copy(target).add(dir.multiplyScalar(distance));
    this.anim = null;
    this._saveHome();
  }

  /* ------------------------------------------------------------------ */
  /* Free camera: orbit / fly modes, double-click to fly to anything,   */
  /* follow a moving object, reset. Shared by every 3D view.            */
  /* ------------------------------------------------------------------ */

  _initFreeCamera() {
    this.mode = 'orbit';
    this.follow = null;            // {label, obj: () => Object3D | null}
    this._followPos = null;
    this.followables = [];
    this.anim = null;
    this.home = null;
    this.keys = new Set();
    this.flySpeed = 1;
    this._euler = new THREE.Euler(0, 0, 0, 'YXZ');
    this._lastT = performance.now();
    this._ray = new THREE.Raycaster();
    this._buildCameraBar();

    const el = this.renderer.domElement;
    const visible = () => this.container.offsetParent !== null;
    const typing = (e) => e.target.matches && e.target.matches('input, select, textarea');
    const FLY_KEYS = ['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];
    window.addEventListener('keydown', (e) => {
      if (!visible() || !this.active || this.locked || typing(e)) return;
      if (e.code === 'Escape' && this.mode === 'fly') { this.setMode('orbit'); return; }
      if (e.code === 'KeyF' && !e.ctrlKey) { this.setMode(this.mode === 'fly' ? 'orbit' : 'fly'); return; }
      if (this.mode === 'fly' && FLY_KEYS.includes(e.code)) { this.keys.add(e.code); e.preventDefault(); }
    });
    window.addEventListener('keyup', (e) => this.keys.delete(e.code));
    window.addEventListener('blur', () => this.keys.clear());

    // Fly mode: drag to look around.
    let drag = null;
    el.addEventListener('pointerdown', (e) => {
      if (!this.active || this.mode !== 'fly' || e.button !== 0) return;
      drag = { x: e.clientX, y: e.clientY };
      el.setPointerCapture(e.pointerId);
    });
    el.addEventListener('pointermove', (e) => {
      if (!drag || !this.active) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag = { x: e.clientX, y: e.clientY };
      this._euler.y -= dx * 0.0035;
      this._euler.x = Math.max(-1.52, Math.min(1.52, this._euler.x - dy * 0.0035));
      this.camera.quaternion.setFromEuler(this._euler);
    });
    el.addEventListener('pointerup', () => { drag = null; });
    // Fly mode: the scroll wheel sets the speed.
    el.addEventListener('wheel', (e) => {
      if (!this.active || this.mode !== 'fly') return;
      e.preventDefault();
      this.flySpeed *= e.deltaY > 0 ? 1 / 1.25 : 1.25;
      this.flySpeed = Math.min(Math.max(this.flySpeed, this._near * 0.1), this._far * 0.01);
      this._showSpeed();
    }, { passive: false });
    // Double-click: fly to whatever is under the pointer.
    el.addEventListener('dblclick', (e) => { if (this.active && !this.locked) this._flyToPointer(e); });
  }

  _buildCameraBar() {
    const bar = document.createElement('div');
    bar.className = 'camtools';
    bar.innerHTML = `
      <div class="seg mini">
        <button data-m="orbit" class="on" title="Rotate around a point: drag to rotate, right-drag to pan, scroll to zoom">Orbit</button>
        <button data-m="fly" title="Move freely: W A S D to move, Q / E down / up, drag to look (key F)">Fly</button>
      </div>
      <select class="cam-follow" title="Keep the camera with a moving object"><option value="">Follow: nothing</option></select>
      <button class="cam-btn cam-reset" title="Back to the starting view">Reset</button>
      <button class="cam-btn cam-shot" title="Save a picture of this view (PNG)" aria-label="Save image"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 8h3l2-2.5h6L17 8h3v11H4z"/><circle cx="12" cy="13" r="3.4"/></svg></button>
      <button class="cam-btn cam-help" title="Camera controls">?</button>
      <span class="cam-speed" hidden></span>
      <div class="cam-helpbox" hidden>
        <b>Orbit mode</b><span>drag</span><span>rotate</span><span>right-drag</span><span>pan</span>
        <span>scroll</span><span>zoom</span>
        <b>Fly mode (F)</b><span>W A S D / arrows</span><span>move</span><span>Q / E</span><span>down / up</span>
        <span>drag</span><span>look around</span><span>Shift</span><span>5× faster</span><span>scroll</span><span>change speed</span>
        <span>Esc</span><span>back to orbit</span>
        <b>Anywhere</b><span>double-click</span><span>fly to that object</span><span>Follow</span><span>ride along with it</span>
      </div>`;
    this.container.appendChild(bar);
    this._bar = bar;
    bar.querySelectorAll('.seg button').forEach((b) => b.addEventListener('click', () => this.setMode(b.dataset.m)));
    bar.querySelector('.cam-reset').addEventListener('click', () => this.resetView());
    bar.querySelector('.cam-shot').addEventListener('click', () => this.saveImage());
    bar.querySelector('.cam-help').addEventListener('click', () => {
      const h = bar.querySelector('.cam-helpbox'); h.hidden = !h.hidden;
    });
    bar.querySelector('.cam-follow').addEventListener('change', (e) => {
      const item = this.followables[+e.target.value - 1];
      this.setFollow(e.target.value ? item : null, true);
    });
    // Keep keyboard focus off the controls, so W/A/S/D reach the camera.
    bar.querySelectorAll('button').forEach((b) => b.addEventListener('mouseup', () => b.blur()));
  }

  /* Save the current view as a PNG. The canvas is only readable right
     after drawing, so draw once and read it in the same step. */
  /* Save the current view as a PNG, drawn again at up to 3840 pixels wide
     (or 3x the window, whichever is larger) instead of the window's size. */
  saveImage() {
    const r = this.renderer;
    const w = this.container.clientWidth, h = this.container.clientHeight;
    const basePr = r.getPixelRatio();
    const maxSide = Math.min(r.capabilities.maxTextureSize, 7680);
    const pr = Math.min(Math.max(3840 / w, 3), maxSide / Math.max(w, h), 6);
    r.setPixelRatio(pr);
    if (this.composer) { this.composer.setPixelRatio(pr); this.composer.setSize(w, h); }
    r.setSize(w, h);
    let url;
    try {
      this.render();
      url = r.domElement.toDataURL('image/png');
    } finally {
      r.setPixelRatio(basePr);
      r.setSize(w, h);
      if (this.composer) { this.composer.setPixelRatio(basePr); this.composer.setSize(w, h); }
      this.render();
    }
    const a = document.createElement('a');
    a.href = url;
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    a.download = `lambert-studio-${stamp}.png`;
    a.click();
    LS.status(`Image saved to your Downloads folder (${Math.round(w * pr)} × ${Math.round(h * pr)} px)`);
  }

  /* Objects the camera can follow: [{label, obj: () => Object3D | null}] */
  setFollowables(list) {
    this.followables = list;
    const sel = this._bar.querySelector('.cam-follow');
    const current = this.follow && this.follow.label;
    sel.innerHTML = '<option value="">Follow: nothing</option>' +
      list.map((f, k) => `<option value="${k + 1}">Follow: ${LS.esc(f.label)}</option>`).join('');
    const k = list.findIndex((f) => f.label === current);
    sel.value = k >= 0 ? String(k + 1) : '';
  }

  setMode(mode) {
    if (mode === this.mode) return;
    const fwd = new THREE.Vector3();
    this.camera.getWorldDirection(fwd);
    if (mode === 'fly') {
      this.anim = null;
      this._euler.setFromQuaternion(this.camera.quaternion, 'YXZ');
      this.flySpeed = Math.min(Math.max(this.camera.position.distanceTo(this.controls.target) * 0.4,
        this._near * 0.1), this._far * 0.01);
      this.controls.enabled = false;
    } else {
      // Put the orbit centre straight ahead, so the view does not jump.
      const d = Math.max(this.flySpeed * 2.5, this.controls.minDistance * 1.5);
      this.controls.target.copy(this.camera.position).add(fwd.multiplyScalar(d));
      this.controls.enabled = true;
      this.keys.clear();
    }
    this.mode = mode;
    this._bar.querySelectorAll('.seg button').forEach((b) => b.classList.toggle('on', b.dataset.m === mode));
    this._showSpeed();
  }

  setFollow(item, fly = false) {
    this.follow = item;
    this._followPos = null;
    this._bar.querySelector('.cam-follow').value =
      item && this.followables.includes(item) ? String(this.followables.indexOf(item) + 1) : '';
    if (!item) return;
    const obj = item.obj();
    if (!obj) {
      LS.status(`${item.label} is not in the scene yet`, 'error');
      this.follow = null;
      this._bar.querySelector('.cam-follow').value = '';
      return;
    }
    if (fly) this.flyTo(obj.getWorldPosition(new THREE.Vector3()), this._viewDistance(obj), obj);
  }

  /* Smooth camera move to look at `target` from `dist` away. If `obj`
     is given, the destination tracks it while the camera travels. */
  flyTo(target, dist, obj = null) {
    if (!target || !this._finite(target) || !Number.isFinite(dist) || dist <= 0) return;
    dist = Math.min(Math.max(dist, this.controls.minDistance), this.controls.maxDistance);
    if (this.mode === 'fly') this.setMode('orbit');
    const dir = this._viewDir();
    this.anim = { t: 0, dur: 1.2, fromT: this.controls.target.clone(), fromP: this.camera.position.clone(),
      toT: target.clone(), dir, dist, obj };
  }

  /* Direction from the target to the camera (a safe default when they coincide). */
  _viewDir() {
    const d = this.camera.position.clone().sub(this.controls.target);
    return d.lengthSq() > 0 && this._finite(d) ? d.normalize() : new THREE.Vector3(0, 0.3, 1).normalize();
  }

  resetView() {
    this.setMode('orbit');
    this.setFollow(null);
    if (this.home) {
      this.anim = { t: 0, dur: 1.0, fromT: this.controls.target.clone(), fromP: this.camera.position.clone(),
        toT: this.home.t.clone(), toP: this.home.p.clone() };
    }
  }

  _saveHome() {
    if (!this._finite(this.camera.position) || !this._finite(this.controls.target)) return;
    this.home = { t: this.controls.target.clone(), p: this.camera.position.clone() };
  }

  /* Planets drawn with their own shader (LS.planetMaterial) are told where
     the Sun is: the scene's point light (the Sun itself) or directional
     light (sunlight from far away). The scene is rescanned every 2 s, so
     planets added later are picked up. */
  _lightPlanets() {
    if (!this._lit || (this._litScan = (this._litScan || 0) + 1) % 120 === 0) {
      this._lit = [];
      this._sunLight = null;
      this.scene.traverse((o) => {
        if (o.material && o.material.userData && o.material.userData.sunLit) this._lit.push(o.material);
        if (!this._sunLight && (o.isPointLight || o.isDirectionalLight)) this._sunLight = o;
      });
    }
    const L = this._sunLight;
    if (!L || !this._lit.length) return;
    const p = L.getWorldPosition(this._lp || (this._lp = new THREE.Vector3()));
    if (L.isDirectionalLight) p.sub(L.target.getWorldPosition(this._lq || (this._lq = new THREE.Vector3())));
    for (const m of this._lit) {
      m.uniforms.sunPos.value.copy(p);
      m.uniforms.sunPoint.value = L.isPointLight ? 1 : 0;
    }
  }

  _finite(v) { return Number.isFinite(v.x) && Number.isFinite(v.y) && Number.isFinite(v.z); }

  /* Safety net: whatever happens (extreme zoom, flying off at full speed,
     a bad value from a calculation), the camera never ends up at NaN,
     inside its own target, or outside the world -- which would leave the
     view black for good. A broken camera goes back to its last good view. */
  _guardCamera() {
    const cam = this.camera.position, tgt = this.controls.target;
    if (!this._finite(cam) || !this._finite(tgt) || !this._finite(this.camera.quaternion)) {
      this.anim = null;
      this.follow = null;
      if (this.mode === 'fly') { this.mode = 'orbit'; this.controls.enabled = this.active; this._showSpeed(); }
      if (this.home) { tgt.copy(this.home.t); cam.copy(this.home.p); }
      else { tgt.set(0, 0, 0); cam.set(0, 0, 10); }
      this.camera.lookAt(tgt);
      if (LS.report) LS.report('camera reset after an invalid position');
      return;
    }
    const limit = this._far * 0.3;                 // stay inside the background sky
    if (cam.length() > limit) {
      const back = cam.clone().setLength(limit).sub(cam);
      cam.add(back);
      tgt.add(back);
    }
    if (cam.distanceTo(tgt) < this._near * 2) {    // never sit on the target point
      const dir = new THREE.Vector3();
      this.camera.getWorldDirection(dir);
      tgt.copy(cam).add(dir.multiplyScalar(Math.max(this.controls.minDistance, this._near * 4)));
    }
  }

  /* A comfortable distance to look at an object from. */
  _viewDistance(obj) {
    const cur = this.camera.position.distanceTo(this.controls.target);
    let r = 0;
    try {
      const sphere = new THREE.Box3().setFromObject(obj).getBoundingSphere(new THREE.Sphere());
      r = isFinite(sphere.radius) ? sphere.radius : 0;
    } catch (e) { r = 0; }
    return Math.min(Math.max(r * 5, cur * 0.03, this.controls.minDistance * 1.2), cur);
  }

  _flyToPointer(e) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this._ray.setFromCamera(ndc, this.camera);
    const d = this.camera.position.distanceTo(this.controls.target);
    this._ray.params.Points.threshold = d * 0.01;
    this._ray.params.Line.threshold = d * 0.008;
    const shown = (o) => { for (; o; o = o.parent) if (!o.visible || o.userData.noPick) return false; return true; };
    const hit = this._ray.intersectObjects(this.scene.children, true).find((h) => shown(h.object));
    if (!hit) return;
    // A planet, moon or marker: go to its centre and follow it. Anything
    // else (a point on an orbit line): go to the point that was clicked.
    let body = hit.object;
    while (body && !(body.isMesh && body.geometry && body.geometry.type === 'SphereGeometry') && body.parent) body = body.parent;
    if (body && body.isMesh && body.geometry.type === 'SphereGeometry') {
      const item = this.followables.find((f) => f.obj() === body) || { label: 'selected object', obj: () => body };
      this.setFollow(item);
      this.flyTo(body.getWorldPosition(new THREE.Vector3()), this._viewDistance(body), body);
    } else {
      this.setFollow(null);
      this.flyTo(hit.point, d * 0.35);
    }
  }

  _showSpeed() {
    const s = this._bar.querySelector('.cam-speed');
    s.hidden = this.mode !== 'fly';
    if (this.mode === 'fly') s.textContent = `speed ${this.flySpeed.toPrecision(2)} units/s · scroll to change`;
  }

  _stepCamera(dt) {
    const followPos = this.follow && this.follow.obj() ? this.follow.obj().getWorldPosition(new THREE.Vector3()) : null;

    if (this.anim) {
      const a = this.anim;
      a.t += dt;
      const u = Math.min(a.t / a.dur, 1), s = u * u * (3 - 2 * u);          // smoothstep
      const toT = a.obj ? a.obj.getWorldPosition(new THREE.Vector3()) : a.toT;
      const toP = a.toP || toT.clone().add(a.dir.clone().multiplyScalar(a.dist));
      this.controls.target.lerpVectors(a.fromT, toT, s);
      this.camera.position.lerpVectors(a.fromP, toP, s);
      this.camera.lookAt(this.controls.target);
      if (u >= 1) { this.anim = null; this._followPos = followPos; }
      return;
    }

    // Following: move the camera by however much the object moved.
    if (followPos) {
      if (this._followPos) {
        const delta = followPos.clone().sub(this._followPos);
        this.camera.position.add(delta);
        this.controls.target.add(delta);
      }
      this._followPos = followPos;
    }

    if (this.mode === 'fly') {
      const k = this.keys;
      const f = (k.has('KeyW') || k.has('ArrowUp') ? 1 : 0) - (k.has('KeyS') || k.has('ArrowDown') ? 1 : 0);
      const r = (k.has('KeyD') || k.has('ArrowRight') ? 1 : 0) - (k.has('KeyA') || k.has('ArrowLeft') ? 1 : 0);
      const u = (k.has('KeyE') ? 1 : 0) - (k.has('KeyQ') ? 1 : 0);
      if (f || r || u) {
        const fwd = new THREE.Vector3(), right = new THREE.Vector3();
        this.camera.getWorldDirection(fwd);
        right.crossVectors(fwd, this.camera.up).normalize();
        const move = fwd.multiplyScalar(f).add(right.multiplyScalar(r)).add(this.camera.up.clone().multiplyScalar(u));
        move.normalize().multiplyScalar(this.flySpeed * dt * (this._shift ? 5 : 1));
        this.camera.position.add(move);
        this.controls.target.add(move);
      }
    }
  }
}
window.addEventListener('keydown', (e) => { if (e.key === 'Shift') LS.scenes.forEach((s) => { s._shift = true; }); });
window.addEventListener('keyup', (e) => { if (e.key === 'Shift') LS.scenes.forEach((s) => { s._shift = false; }); });
LS.Scene3D = Scene3D;

/* Graphics quality. 'auto' (default) draws as sharp as the graphics chip
   can keep smooth: up to 2x the screen's pixels on a dedicated card, less on
   an integrated chip, and the app lowers or raises it by itself while it
   runs (see the frame loop in app.js). 'max' is fixed and as sharp as
   possible; 'smooth' is plain screen resolution. */
LS.quality = { pr: 1, max: 1, min: 1 };
LS.applyQuality = function (initial) {
  const r = Scene3D.shared;
  if (!r) return;
  const q = LS.quality, dpr = window.devicePixelRatio || 1, disc = LS.gpu && LS.gpu.discrete;
  const mode = LS.settings.quality;
  if (mode === 'max') { q.max = disc ? 2.5 : 2; q.min = q.max; }
  else if (mode === 'smooth') { q.max = q.min = 1; }
  else { q.max = disc ? 2 : Math.max(1, Math.min(dpr, 1.5)); q.min = 1; }
  q.pr = q.max;
  r.setPixelRatio(q.pr);
  if (!initial && Scene3D.current) Scene3D.current.resize();
};
/* Change the drawing resolution while running (used by the frame-rate governor). */
LS.setPixelRatio = function (pr) {
  const r = Scene3D.shared, q = LS.quality;
  pr = Math.min(q.max, Math.max(q.min, pr));
  if (!r || Math.abs(pr - q.pr) < 0.01) return false;
  q.pr = pr;
  r.setPixelRatio(pr);
  if (Scene3D.current) Scene3D.current.resize();
  return true;
};

const _tex = {};
LS.texture = function (path) {
  if (!_tex[path]) {
    _tex[path] = new THREE.TextureLoader().load(path);
    _tex[path].anisotropy = LS.aniso || 16;
  }
  return _tex[path];
};

/* Surface of a planet or moon: the picture alone, lit by the Sun. (Using
   the picture's brightness as a bump map made every bright or dark speck a
   dimple -- the "golf ball" look -- so no bump map is used.)

   Mars and Jupiter get their own shader, drawn with the same care as the
   Earth: a crisp day/night line (soft on a gas giant), a truly dark night
   side instead of a grey haze, limb darkening, and a thin glow of
   atmosphere on the sunlit edge. The Sun is found in the scene by
   Scene3D (a point light = the Sun's position, a directional light = its
   direction), so the same material works in every view. */
const SURFACES = {
  // terminator: where the day fades into night (cos of the sun angle);
  // limb: how much the edge darkens; haze: the sunlit rim's colour and strength
  mars:    { terminator: [-0.03, 0.2], limb: 0.18, haze: [0.95, 0.6, 0.42], hazeK: 0.22, hazeP: 3.5, gain: 1.05 },
  jupiter: { terminator: [-0.08, 0.3], limb: 0.42, haze: [0.95, 0.88, 0.75], hazeK: 0.04, hazeP: 5.0, gain: 1.02 },
};
LS.planetMaterial = function (name, file, extra = {}) {
  const map = LS.texture(`textures/${file || name.toLowerCase() + '.jpg'}`);
  const surf = SURFACES[name.toLowerCase()];
  if (!surf || Object.keys(extra).length) {
    const params = Object.assign({ map, roughness: 1, metalness: 0, color: 0xc8c8c8 }, extra);
    return new THREE.MeshStandardMaterial(params);
  }
  const mat = new THREE.ShaderMaterial({
    uniforms: {
      map: { value: map },
      sunPos: { value: new THREE.Vector3() }, sunPoint: { value: 1 },
      term: { value: new THREE.Vector2(...surf.terminator) }, limbK: { value: surf.limb },
      haze: { value: new THREE.Color(...surf.haze) }, hazeK: { value: surf.hazeK }, hazeP: { value: surf.hazeP },
      gain: { value: surf.gain },
    },
    vertexShader: `${LOGDEPTH_V}
      varying vec2 vUv; varying vec3 vN; varying vec3 vP;
      void main(){
        vUv = uv;
        vN = normalize(mat3(modelMatrix) * normal);
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vP = wp.xyz;
        gl_Position = projectionMatrix * viewMatrix * wp;
        #include <logdepthbuf_vertex>
      }`,
    fragmentShader: `${LOGDEPTH_F}
      uniform sampler2D map; uniform vec3 sunPos; uniform float sunPoint;
      uniform vec2 term; uniform float limbK; uniform vec3 haze; uniform float hazeK; uniform float hazeP; uniform float gain;
      varying vec2 vUv; varying vec3 vN; varying vec3 vP;
      void main(){
        #include <logdepthbuf_fragment>
        vec3 n = normalize(vN);
        vec3 v = normalize(cameraPosition - vP);
        vec3 s = normalize(sunPoint > 0.5 ? sunPos - vP : sunPos);
        float ndl = dot(n, s);
        float day = smoothstep(term.x, term.y, ndl);
        float mu = max(dot(n, v), 0.0);
        float limb = 1.0 - limbK * (1.0 - pow(mu, 0.6));
        vec3 col = texture2D(map, vUv).rgb * gain;
        vec3 lit = col * (0.012 + day * (0.25 + 0.75 * max(ndl, 0.0)) * limb);
        // thin atmosphere: a glow on the sunlit rim, strongest near the day/night line
        float rim = pow(1.0 - mu, hazeP);
        lit += haze * rim * hazeK * smoothstep(-0.15, 0.25, ndl);
        gl_FragColor = vec4(lit, 1.0);
      }`,
  });
  mat.userData.sunLit = true;
  return mat;
};

LS.stars = function (radius, count = 6000) {
  const pos = new Float32Array(count * 3), col = new Float32Array(count * 3);
  for (let k = 0; k < count; k++) {
    const u = Math.random() * 2 - 1, t = Math.random() * 2 * Math.PI, s = Math.sqrt(1 - u * u);
    pos.set([radius * s * Math.cos(t), radius * u, radius * s * Math.sin(t)], 3 * k);
    const b = 0.35 + Math.pow(Math.random(), 3) * 0.65;
    const warm = Math.random();
    col.set([b * (warm > 0.8 ? 1 : 0.85), b * 0.9, b * (warm < 0.2 ? 1 : 0.95)], 3 * k);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('color', new THREE.BufferAttribute(col, 3));
  return new THREE.Points(g, new THREE.PointsMaterial({ size: 1.6, sizeAttenuation: false, vertexColors: true, depthWrite: false }));
};

/* Custom shaders must include these chunks to work with the
   logarithmic depth buffer every scene uses. */
const LOGDEPTH_V = ['#include <common>', '#include <logdepthbuf_pars_vertex>'].join('\n');
const LOGDEPTH_F = ['#include <common>', '#include <logdepthbuf_pars_fragment>'].join('\n');

/* Fresnel glow shell (atmosphere, sun corona). */
LS.glow = function (radius, color, power = 3.0, strength = 1.0) {
  const mat = new THREE.ShaderMaterial({
    uniforms: { c: { value: new THREE.Color(color) }, p: { value: power }, s: { value: strength } },
    vertexShader: `${LOGDEPTH_V}
      varying vec3 vN; varying vec3 vV;
      void main(){ vec4 mv = modelViewMatrix * vec4(position,1.0);
        vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
        #include <logdepthbuf_vertex>
      }`,
    fragmentShader: `${LOGDEPTH_F}
      uniform vec3 c; uniform float p; uniform float s; varying vec3 vN; varying vec3 vV;
      void main(){
        #include <logdepthbuf_fragment>
        float f = pow(1.0 - abs(dot(vN, vV)), p) * s; gl_FragColor = vec4(c, f); }`,
    side: THREE.FrontSide, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false,
  });
  const m = new THREE.Mesh(new THREE.SphereGeometry(radius, 96, 72), mat);
  m.userData.noPick = true;          // decoration: clicks go to the body underneath
  return m;
};

/* An atmosphere seen from space: a glowing shell around a planet, like the
   Earth's, but brightest on the sunlit side and fading into the night side
   (a plain glow would ring the dark side too). The Sun is supplied by
   Scene3D like the planet shaders (sunLit). */
LS.atmosphere = function (radius, color, power = 3.0, strength = 1.0) {
  const mat = new THREE.ShaderMaterial({
    uniforms: { c: { value: new THREE.Color(color) }, p: { value: power }, k: { value: strength },
      sunPos: { value: new THREE.Vector3(1, 0, 0) }, sunPoint: { value: 0 } },
    vertexShader: `${LOGDEPTH_V}
      varying vec3 vN; varying vec3 vP;
      void main(){
        vN = normalize(mat3(modelMatrix) * normal);
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vP = wp.xyz;
        gl_Position = projectionMatrix * viewMatrix * wp;
        #include <logdepthbuf_vertex>
      }`,
    fragmentShader: `${LOGDEPTH_F}
      uniform vec3 c; uniform float p; uniform float k; uniform vec3 sunPos; uniform float sunPoint;
      varying vec3 vN; varying vec3 vP;
      void main(){
        #include <logdepthbuf_fragment>
        vec3 n = normalize(vN);
        vec3 v = normalize(cameraPosition - vP);
        vec3 s = normalize(sunPoint > 0.5 ? sunPos - vP : sunPos);
        float fres = pow(1.0 - abs(dot(n, v)), p);
        float lit = smoothstep(-0.35, 0.5, dot(n, s));
        gl_FragColor = vec4(c, fres * k * (0.06 + 0.94 * lit));
      }`,
    side: THREE.FrontSide, blending: THREE.AdditiveBlending, transparent: true, depthWrite: false,
  });
  mat.userData.sunLit = true;
  const m = new THREE.Mesh(new THREE.SphereGeometry(radius, 128, 96), mat);
  m.userData.noPick = true;
  return m;
};

/* Earth: NASA Blue Marble by day, NASA Black Marble city lights by
   night, sunlight glinting on the oceans, clouds and atmosphere.
   Radius 1 = R_EARTH. `spin` is the Earth-fixed frame (rotate by GMST);
   call setSun(direction) every frame with the Sun's world direction. */
LS.earth = function () {
  const group = new THREE.Group();
  const spin = new THREE.Group();
  group.add(spin);
  const uniforms = {
    dayMap: { value: LS.texture('textures/earth_day_hd.jpg') },
    nightMap: { value: LS.texture('textures/earth_night.jpg') },
    specMap: { value: LS.texture('textures/earth_specular.jpg') },
    cloudMap: { value: LS.texture('textures/earth_clouds.png') },
    sunDir: { value: new THREE.Vector3(1, 0, 0) },
  };
  const surface = new THREE.Mesh(new THREE.SphereGeometry(1, 160, 120), new THREE.ShaderMaterial({
    uniforms,
    vertexShader: `${LOGDEPTH_V}
      varying vec2 vUv; varying vec3 vN; varying vec3 vP;
      void main(){
        vUv = uv;
        vN = normalize(mat3(modelMatrix) * normal);
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vP = wp.xyz;
        gl_Position = projectionMatrix * viewMatrix * wp;
        #include <logdepthbuf_vertex>
      }`,
    fragmentShader: `${LOGDEPTH_F}
      uniform sampler2D dayMap; uniform sampler2D nightMap; uniform sampler2D specMap; uniform sampler2D cloudMap; uniform vec3 sunDir;
      varying vec2 vUv; varying vec3 vN; varying vec3 vP;
      void main(){
        #include <logdepthbuf_fragment>
        vec3 N = normalize(vN), L = normalize(sunDir), V = normalize(cameraPosition - vP);
        float d = dot(N, L);
        vec3 day = texture2D(dayMap, vUv).rgb;
        vec3 night = texture2D(nightMap, vUv).rgb;
        float water = texture2D(specMap, vUv).r;
        float daylight = smoothstep(-0.10, 0.22, d);
        float cloud = texture2D(cloudMap, vUv).a;
        float shade = texture2D(cloudMap, vUv + vec2(0.0010, -0.0005)).a;      // cloud shadow, offset away from the Sun
        vec3 col = day * (0.035 + 1.08 * max(d, 0.0)) * (1.0 - 0.34 * shade * smoothstep(0.0, 0.35, d));
        col += night * vec3(1.0, 0.82, 0.55) * 1.7 * (1.0 - daylight) * (1.0 - 0.55 * cloud);   // city lights, dimmed by cloud
        vec3 H = normalize(L + V);
        col += vec3(1.0, 0.93, 0.8) * pow(max(dot(N, H), 0.0), 48.0) * water * 0.6 * step(0.0, d); // sun glint
        float rim = pow(1.0 - max(dot(N, V), 0.0), 2.6);
        col += vec3(0.28, 0.58, 1.0) * rim * 0.5 * smoothstep(-0.3, 0.4, d);     // blue limb
        gl_FragColor = vec4(col, 1.0);
      }`,
  }));
  spin.add(surface);
  const clouds = new THREE.Mesh(
    new THREE.SphereGeometry(1.008, 160, 120),
    new THREE.MeshLambertMaterial({ map: LS.texture('textures/earth_clouds.png'), transparent: true, opacity: 0.5, depthWrite: false }));
  clouds.userData.noPick = true;
  spin.add(clouds);
  group.add(LS.glow(1.025, 0x4da6ff, 2.6, 1.0));
  group.add(LS.glow(1.07, 0x6fb4ff, 4.2, 0.55));              // thin outer haze of the atmosphere
  const setSun = (dir) => uniforms.sunDir.value.copy(dir).normalize();
  return { group, spin, clouds, surface, setSun };
};

/* Saturn, drawn with the same care as the Earth: an oblate, tilted planet
   whose rings cast their shadow on its clouds, and whose body casts its
   shadow across the rings. Proportions are real: radius R (equatorial),
   polar radius 0.902 R, rings from 1.24 R to 2.33 R (C ring to A ring),
   axial tilt 26.7 deg. Call setSun(direction) with the Sun's world direction;
   the shadows follow the planet wherever it is placed. */
LS.saturn = function (R = 1) {
  const group = new THREE.Group();
  const tilt = new THREE.Group();
  tilt.rotation.z = 26.7 * LS.DEG;
  group.add(tilt);
  const R_IN = 1.24 * R, R_OUT = 2.33 * R;
  const shared = {
    sunDir: { value: new THREE.Vector3(1, 0, 0) },
    center: { value: new THREE.Vector3() },
    ringNormal: { value: new THREE.Vector3(0, 1, 0) },
    ringMap: { value: LS.texture('textures/saturn_ring.png') },
    rIn: { value: R_IN }, rOut: { value: R_OUT }, radius: { value: R },
  };

  // The planet: the cloud bands, lit by the Sun with a soft terminator,
  // a touch of limb darkening, and the rings' shadow.
  const planet = new THREE.Mesh(new THREE.SphereGeometry(R, 192, 128), new THREE.ShaderMaterial({
    uniforms: Object.assign({ map: { value: LS.texture('textures/saturn.jpg') } }, shared),
    vertexShader: `${LOGDEPTH_V}
      varying vec2 vUv; varying vec3 vN; varying vec3 vP;
      void main(){
        vUv = uv;
        vN = normalize(mat3(modelMatrix) * normal);
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vP = wp.xyz;
        gl_Position = projectionMatrix * viewMatrix * wp;
        #include <logdepthbuf_vertex>
      }`,
    fragmentShader: `${LOGDEPTH_F}
      uniform sampler2D map; uniform sampler2D ringMap;
      uniform vec3 sunDir; uniform vec3 center; uniform vec3 ringNormal;
      uniform float rIn; uniform float rOut;
      varying vec2 vUv; varying vec3 vN; varying vec3 vP;
      void main(){
        #include <logdepthbuf_fragment>
        vec3 n = normalize(vN);
        vec3 v = normalize(cameraPosition - vP);
        float ndl = dot(n, sunDir);
        float day = smoothstep(-0.06, 0.28, ndl);
        // ring shadow: follow the ray towards the Sun to the ring plane
        float shade = 1.0;
        float dn = dot(sunDir, ringNormal);
        if (abs(dn) > 1e-4) {
          float t = dot(center - vP, ringNormal) / dn;
          if (t > 0.0) {
            float r = length(vP + sunDir * t - center);
            if (r > rIn && r < rOut) shade = 1.0 - 0.82 * texture2D(ringMap, vec2((r - rIn) / (rOut - rIn), 0.5)).a;
          }
        }
        vec3 col = texture2D(map, vUv).rgb * 0.84;
        float limb = mix(0.6, 1.0, pow(max(dot(n, v), 0.0), 0.45));
        vec3 lit = col * (0.03 + 0.97 * day * shade) * limb;
        // faint warm haze on the lit limb
        lit += vec3(0.9, 0.78, 0.55) * pow(1.0 - max(dot(n, v), 0.0), 4.0) * day * 0.05;
        gl_FragColor = vec4(lit, 1.0);
      }`,
  }));
  planet.scale.y = 0.902;
  tilt.add(planet);

  // The rings: colour and transparency from the radial ring picture,
  // brighter on the side the Sun shines on, dark in the planet's shadow.
  const ringGeo = new THREE.RingGeometry(R_IN, R_OUT, 384, 6);
  const ring = new THREE.Mesh(ringGeo, new THREE.ShaderMaterial({
    uniforms: shared,
    vertexShader: `${LOGDEPTH_V}
      varying vec3 vP;
      void main(){
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vP = wp.xyz;
        gl_Position = projectionMatrix * viewMatrix * wp;
        #include <logdepthbuf_vertex>
      }`,
    fragmentShader: `${LOGDEPTH_F}
      uniform sampler2D ringMap; uniform vec3 sunDir; uniform vec3 center; uniform vec3 ringNormal;
      uniform float rIn; uniform float rOut; uniform float radius;
      varying vec3 vP;
      void main(){
        #include <logdepthbuf_fragment>
        float r = length(vP - center);
        vec4 tex = texture2D(ringMap, vec2((r - rIn) / (rOut - rIn), 0.5));
        if (tex.a < 0.01) discard;
        // planet shadow: does the ray towards the Sun hit the (oblate) planet?
        vec3 d = vP - center;
        float b = dot(d, sunDir);
        float c = dot(d, d) - radius * radius * 0.95;
        float shadow = (b < 0.0 && b * b - c > 0.0) ? 0.06 : 1.0;
        // the lit face is bright; seen from the unlit face the rings glow faintly
        vec3 v = normalize(cameraPosition - vP);
        float sameSide = sign(dot(sunDir, ringNormal)) * sign(dot(v, ringNormal));
        float light = sameSide > 0.0 ? 0.35 + 0.65 * abs(dot(sunDir, ringNormal)) + 0.25 : 0.28 * (1.0 - tex.a) + 0.1;
        gl_FragColor = vec4(tex.rgb * 1.08 * light * shadow, tex.a * 0.96);
      }`,
    side: THREE.DoubleSide, transparent: true, depthWrite: false,
  }));
  ring.rotation.x = -Math.PI / 2;
  tilt.add(ring);
  // its atmosphere: a thin bright limb and a wider soft haze, like the Earth's
  [LS.atmosphere(R * 1.02, 0xf2d9a4, 3.4, 0.42), LS.atmosphere(R * 1.06, 0xffe6b8, 5.0, 0.3)].forEach((a) => {
    a.scale.y = 0.902;
    tilt.add(a);
  });

  const n = new THREE.Vector3(), q = new THREE.Quaternion();
  const setSun = (dir) => {
    shared.sunDir.value.copy(dir).normalize();
    group.updateMatrixWorld(true);
    tilt.getWorldPosition(shared.center.value);
    tilt.getWorldQuaternion(q);
    shared.ringNormal.value.copy(n.set(0, 1, 0).applyQuaternion(q)).normalize();
  };
  return { group, tilt, planet, ring, setSun, radius: R, ringRadius: R_OUT };
};

/* The Sun: animated plasma surface (procedural noise) with limb
   darkening. Bright enough that the bloom pass makes it glow. */
LS.sun = function (radius) {
  const uniforms = { time: { value: 0 } };
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(radius, 96, 64), new THREE.ShaderMaterial({
    uniforms,
    vertexShader: `${LOGDEPTH_V}
      varying vec3 vPos; varying vec3 vN; varying vec3 vV;
      void main(){ vPos = position / ${radius.toFixed(8)};
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        vN = normalize(normalMatrix * normal); vV = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
        #include <logdepthbuf_vertex>
      }`,
    fragmentShader: `${LOGDEPTH_F}
      uniform float time; varying vec3 vPos; varying vec3 vN; varying vec3 vV;
      float h(vec3 p){ return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
      float noise(vec3 p){ vec3 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
        return mix(mix(mix(h(i), h(i+vec3(1,0,0)), f.x), mix(h(i+vec3(0,1,0)), h(i+vec3(1,1,0)), f.x), f.y),
                   mix(mix(h(i+vec3(0,0,1)), h(i+vec3(1,0,1)), f.x), mix(h(i+vec3(0,1,1)), h(i+vec3(1,1,1)), f.x), f.y), f.z); }
      float fbm(vec3 p){ float s = 0.0, a = 0.5; for (int k = 0; k < 5; k++){ s += a*noise(p); p *= 2.1; a *= 0.5; } return s; }
      void main(){
        #include <logdepthbuf_fragment>
        float n = fbm(vPos * 5.0 + vec3(time * 0.04, time * 0.03, -time * 0.05));
        float m = fbm(vPos * 14.0 - vec3(time * 0.08));
        vec3 col = mix(vec3(1.0, 0.42, 0.06), vec3(1.0, 0.86, 0.45), n);
        col += vec3(0.25, 0.15, 0.0) * m;
        float mu = max(dot(vN, vV), 0.0);
        col *= 0.55 + 0.75 * pow(mu, 0.45);                  // limb darkening
        gl_FragColor = vec4(col * 1.35, 1.0);
      }`,
  }));
  mesh.onBeforeRender = () => { uniforms.time.value = performance.now() / 1000; };
  return mesh;
};

LS.line = function (points, color, opacity = 1, dashed = false) {
  const g = new THREE.BufferGeometry().setFromPoints(points);
  const m = dashed
    ? new THREE.LineDashedMaterial({ color, dashSize: 0.12, gapSize: 0.08, transparent: true, opacity,
      blending: THREE.AdditiveBlending, depthWrite: false })
    // additive blending makes every path read as a light trace (holographic look)
    : new THREE.LineBasicMaterial({ color, transparent: true, opacity,
      blending: THREE.AdditiveBlending, depthWrite: false });
  const l = new THREE.Line(g, m);
  if (dashed) l.computeLineDistances();
  return l;
};

LS.tube = function (points, radius, color, closed = false, opacity = 1) {
  const curve = new THREE.CatmullRomCurve3(points, closed);
  const g = new THREE.TubeGeometry(curve, Math.min(points.length * 2, 1600), radius, 8, closed);
  return new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color, transparent: opacity < 1, opacity }));
};

LS.dot = function (radius, color) {
  return new THREE.Mesh(new THREE.SphereGeometry(radius, 24, 16), new THREE.MeshBasicMaterial({ color }));
};

/* Soft round sprite texture, drawn once. */
LS.spriteTexture = (function () {
  let t = null;
  return function () {
    if (t) return t;
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const g = c.getContext('2d');
    const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    grd.addColorStop(0, 'rgba(255,255,255,1)'); grd.addColorStop(0.25, 'rgba(255,255,255,0.9)');
    grd.addColorStop(0.5, 'rgba(255,255,255,0.25)'); grd.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
    t = new THREE.CanvasTexture(c);
    return t;
  };
})();

LS.glowSprite = function (color, size) {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({
    map: LS.spriteTexture(), color, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true,
  }));
  s.scale.set(size, size, 1);
  return s;
};

/* Thin ring marker, drawn once: keeps a small object findable at any
   zoom without a glowing blob (normal blending, so the bloom pass does
   not turn it into a bright ball). */
LS.ringTexture = (function () {
  let t = null;
  return function () {
    if (t) return t;
    const c = document.createElement('canvas'); c.width = c.height = 64;
    const g = c.getContext('2d');
    g.strokeStyle = '#ffffff'; g.lineWidth = 5;
    g.beginPath(); g.arc(32, 32, 24, 0, Math.PI * 2); g.stroke();
    g.fillStyle = '#ffffff';
    g.beginPath(); g.arc(32, 32, 4, 0, Math.PI * 2); g.fill();
    t = new THREE.CanvasTexture(c);
    return t;
  };
})();

LS.markerRing = function (color = 0x5eb3e6, screenSize = 0.026) {
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: LS.ringTexture(), color, sizeAttenuation: false,
    transparent: true, opacity: 0.85, depthWrite: false, depthTest: false }));
  s.scale.set(screenSize, screenSize, 1);
  s.renderOrder = 20;
  s.userData.noPick = true;
  return s;
};

/* Solar-panel cells: dark blue squares with fine silver grid lines. */
LS.panelTexture = (function () {
  let t = null;
  return function () {
    if (t) return t;
    const c = document.createElement('canvas'); c.width = 256; c.height = 128;
    const g = c.getContext('2d');
    g.fillStyle = '#17346b'; g.fillRect(0, 0, 256, 128);
    const grd = g.createLinearGradient(0, 0, 256, 128);
    grd.addColorStop(0, 'rgba(120,170,255,0.25)'); grd.addColorStop(1, 'rgba(0,0,0,0.25)');
    g.fillStyle = grd; g.fillRect(0, 0, 256, 128);
    g.strokeStyle = 'rgba(190,205,230,0.85)'; g.lineWidth = 2;
    for (let x = 0; x <= 256; x += 32) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, 128); g.stroke(); }
    for (let y = 0; y <= 128; y += 32) { g.beginPath(); g.moveTo(0, y); g.lineTo(256, y); g.stroke(); }
    g.strokeStyle = 'rgba(190,205,230,0.35)'; g.lineWidth = 1;
    for (let x = 16; x < 256; x += 32) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, 128); g.stroke(); }
    t = new THREE.CanvasTexture(c);
    t.anisotropy = LS.aniso || 16;
    return t;
  };
})();

/* A small spacecraft: gold-foil bus with a thruster, a white high-gain dish
   with its feed, a magnetometer boom, and two gridded solar wings, plus a
   ring marker so it stays visible when zoomed out. `size` is the length of
   the bus in scene units. Call LS.aimCraft(craft, point) to point it along
   its direction of travel. */
LS.spacecraft = function (size, { color = 0x5eb3e6, label = null } = {}) {
  const craft = new THREE.Group();
  const model = new THREE.Group();
  // Gold multi-layer insulation. Low metalness: a metal needs an
  // environment to reflect, and without one it renders almost black.
  const foil = new THREE.MeshStandardMaterial({ color: 0xd4a94f, metalness: 0.15, roughness: 0.42, emissive: 0x2a1c06 });
  const white = new THREE.MeshStandardMaterial({ color: 0xdfe6ee, metalness: 0.1, roughness: 0.5, side: THREE.DoubleSide });
  const dark = new THREE.MeshStandardMaterial({ color: 0x2a2f3a, metalness: 0.5, roughness: 0.45 });
  const panelMap = LS.panelTexture();
  const panel = new THREE.MeshStandardMaterial({ map: panelMap, color: 0xffffff, metalness: 0.45, roughness: 0.32, emissive: 0x06142b });
  const bus = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.6, 1), foil);
  const dish = new THREE.Mesh(new THREE.SphereGeometry(0.55, 48, 20, 0, Math.PI * 2, 0, Math.PI / 3.2), white);
  dish.rotation.x = -Math.PI / 2;            // opening faces backwards (towards Earth, roughly)
  dish.position.z = -0.75;
  const feed = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.42, 8), white);
  feed.rotation.x = Math.PI / 2; feed.position.z = -1.0;
  const horn = new THREE.Mesh(new THREE.ConeGeometry(0.05, 0.1, 16), dark);
  horn.rotation.x = -Math.PI / 2; horn.position.z = -1.24;
  const nozzle = new THREE.Mesh(new THREE.ConeGeometry(0.16, 0.26, 20, 1, true), dark);
  nozzle.rotation.x = Math.PI / 2; nozzle.position.z = 0.62;
  const boom = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 2.9, 10), white);
  boom.rotation.z = Math.PI / 2;
  const mag = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.014, 0.9, 6), dark);
  mag.rotation.x = Math.PI / 2; mag.position.set(0, 0.32, 0.55);
  const wingGeo = new THREE.BoxGeometry(1.1, 0.03, 0.55);
  const left = new THREE.Mesh(wingGeo, panel); left.position.x = -1.05;
  const right = new THREE.Mesh(wingGeo, panel); right.position.x = 1.05;
  model.add(bus, dish, feed, horn, nozzle, boom, mag, left, right);
  model.scale.setScalar(size);
  craft.add(model, LS.markerRing(color));
  if (label) craft.add(LS.label(label, 'accent'));
  craft.userData.model = model;
  return craft;
};

LS.aimCraft = function (craft, point) {
  if (!craft || !craft.userData.model || !point) return;
  const p = craft.getWorldPosition(new THREE.Vector3());
  if (p.distanceToSquared(point) > 1e-18) craft.userData.model.lookAt(point);
};

LS.label = function (text, cls = '') {
  // CSS2DRenderer owns the outer element's transform, so the styling
  // (including the upward offset) goes on an inner element.
  const outer = document.createElement('div');
  const inner = document.createElement('div');
  inner.className = 'lbl ' + cls;
  inner.textContent = text;
  outer.appendChild(inner);
  const obj = new THREE.CSS2DObject(outer);
  obj.setText = (t) => { inner.textContent = t; };
  return obj;
};

/* Points cloud with per-point colour, positions updated every frame. */
LS.pointCloud = function (count, size = 3) {
  const g = new THREE.BufferGeometry();
  const pos = new THREE.BufferAttribute(new Float32Array(count * 3), 3);
  pos.setUsage(THREE.DynamicDrawUsage);               // rewritten every frame
  g.setAttribute('position', pos);
  g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
  // A fixed, generous bounding sphere: recomputing it over thousands of
  // points every frame is wasted work.
  g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e7);
  const m = new THREE.PointsMaterial({
    size, sizeAttenuation: false, vertexColors: true, map: LS.spriteTexture(),
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  return new THREE.Points(g, m);
};

/* A clock for a view: simulated time t (units defined by the view),
   advanced by `rate` per real second while playing. */
class Clock {
  constructor({ t = 0, min = null, max = null, rate = 1, loop = false, rates = [[1, '1×']], playing = true }) {
    Object.assign(this, { t, min, max, rate, loop, rates, playing });
  }
  tick(dt) {
    if (!this.playing) return;
    this.t += dt * this.rate;
    if (this.max !== null && this.t > this.max) {
      if (this.loop) this.t = this.min + ((this.t - this.min) % (this.max - this.min));
      else { this.t = this.max; this.playing = false; }
    }
    if (this.min !== null && this.t < this.min) this.t = this.min;
  }
}
LS.Clock = Clock;

/* Every chart legend: one row (or more if needed) just above the plot area,
   aligned left under the title. */
LS.legendTop = { orientation: 'h', x: 0, xanchor: 'left', y: 1.02, yanchor: 'bottom',
  bgcolor: 'rgba(0,0,0,0)', borderwidth: 0, font: { size: 11 } };

/* Plotly layout shared by every 2D chart. */
LS.plotLayout = function (extra) {
  const axis = { gridcolor: 'rgba(255,255,255,0.06)', zerolinecolor: 'rgba(255,255,255,0.12)',
    color: '#8d95a8', linecolor: 'rgba(255,255,255,0.1)' };
  return Object.assign({
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#e9ecf3', family: 'Segoe UI Variable Text, Segoe UI, system-ui, sans-serif', size: 12 },
    margin: { l: 56, r: 20, t: 44, b: 44 },
    xaxis: Object.assign({}, axis), yaxis: Object.assign({}, axis),
    legend: Object.assign({}, LS.legendTop),
    hoverlabel: { bgcolor: '#141824', bordercolor: '#9cc2ff', font: { color: '#e9ecf3' } },
  }, extra || {});
};
/* A results panel taller than the view scrolls; it fades out at the bottom
   while there is more below, so a cut-off line reads as "scroll for more". */
setInterval(() => {
  document.querySelectorAll('.hud.wide').forEach((el) => {
    if (el.offsetParent === null) return;
    el.classList.toggle('more', el.scrollHeight - el.scrollTop - el.clientHeight > 4);
  });
}, 400);

LS.plotConfig = { displaylogo: false, responsive: true,
  modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'] };
