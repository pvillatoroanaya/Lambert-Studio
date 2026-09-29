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

/* User display settings, remembered between sessions on this computer. */
LS.settings = (function () {
  const defaults = { bloom: true, milkyway: true, fps: false };
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
    // 'high-performance' asks for the dedicated GPU on laptops that also
    // have an integrated one.
    this.renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true,
      powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    // If the GPU driver resets, the scene can be rebuilt by reloading.
    this.renderer.domElement.addEventListener('webglcontextlost', (e) => {
      e.preventDefault();
      if (LS.report) LS.report('WebGL context lost');
      LS.status('Graphics were reset, reloading…', 'busy');
      setTimeout(() => location.reload(), 1500);
    });
    this.renderer.setClearColor(0x03050b, 1);
    container.appendChild(this.renderer.domElement);

    this.labels = new THREE.CSS2DRenderer();
    Object.assign(this.labels.domElement.style, { position: 'absolute', top: '0', left: '0', pointerEvents: 'none' });
    container.appendChild(this.labels.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(fov, 1, near, far);
    this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.rotateSpeed = 0.6;

    // Glow ("bloom"): only the brightest pixels -- the Sun, satellites,
    // highlighted markers -- bleed light into their surroundings.
    this.composer = null;
    if (THREE.EffectComposer && THREE.UnrealBloomPass) {
      this.composer = new THREE.EffectComposer(this.renderer);
      this.composer.addPass(new THREE.RenderPass(this.scene, this.camera));
      this.bloom = new THREE.UnrealBloomPass(new THREE.Vector2(256, 256), 0.6, 0.4, 0.86);
      this.composer.addPass(this.bloom);
    }

    // Background: the Milky Way panorama, or plain stars.
    const skyR = far * 0.5;
    this.sky = new THREE.Mesh(new THREE.SphereGeometry(skyR, 64, 32),
      new THREE.MeshBasicMaterial({ map: LS.texture('textures/milky_way.jpg'), side: THREE.BackSide,
        depthWrite: false, color: 0x8a8f9c }));
    this.sky.renderOrder = -10;
    this.stars = LS.stars(skyR * 0.9);
    this.scene.add(this.sky, this.stars);

    LS.scenes.push(this);
    this.applySettings();
    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
  }
  applySettings() {
    this.sky.visible = LS.settings.milkyway;
    this.stars.visible = !LS.settings.milkyway;
  }
  resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h);
    this.labels.setSize(w, h);
    if (this.composer) {
      this.composer.setPixelRatio(this.renderer.getPixelRatio());
      this.composer.setSize(w, h);
    }
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }
  render() {
    this.controls.update();
    this.sky.position.copy(this.camera.position);      // the sky is always "at infinity"
    this.stars.position.copy(this.camera.position);
    if (this.composer && LS.settings.bloom) this.composer.render();
    else this.renderer.render(this.scene, this.camera);
    this.labels.render(this.scene, this.camera);
  }
  /* Smoothly move the orbit-controls target (and camera with it). */
  focusOn(target, distance) {
    const dir = this.camera.position.clone().sub(this.controls.target).normalize();
    this.controls.target.copy(target);
    this.camera.position.copy(target).add(dir.multiplyScalar(distance));
  }
}
LS.Scene3D = Scene3D;

const _tex = {};
LS.texture = function (path) {
  if (!_tex[path]) {
    _tex[path] = new THREE.TextureLoader().load(path);
    _tex[path].anisotropy = 8;
  }
  return _tex[path];
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
  return new THREE.Mesh(new THREE.SphereGeometry(radius, 64, 48), mat);
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
      uniform sampler2D dayMap; uniform sampler2D nightMap; uniform sampler2D specMap; uniform vec3 sunDir;
      varying vec2 vUv; varying vec3 vN; varying vec3 vP;
      void main(){
        #include <logdepthbuf_fragment>
        vec3 N = normalize(vN), L = normalize(sunDir), V = normalize(cameraPosition - vP);
        float d = dot(N, L);
        vec3 day = texture2D(dayMap, vUv).rgb;
        vec3 night = texture2D(nightMap, vUv).rgb;
        float water = texture2D(specMap, vUv).r;
        float daylight = smoothstep(-0.10, 0.22, d);
        vec3 col = day * (0.035 + 1.08 * max(d, 0.0));
        col += night * vec3(1.0, 0.82, 0.55) * 1.7 * (1.0 - daylight);          // city lights
        vec3 H = normalize(L + V);
        col += vec3(1.0, 0.93, 0.8) * pow(max(dot(N, H), 0.0), 48.0) * water * 0.6 * step(0.0, d); // sun glint
        float rim = pow(1.0 - max(dot(N, V), 0.0), 2.6);
        col += vec3(0.28, 0.58, 1.0) * rim * 0.5 * smoothstep(-0.3, 0.4, d);     // blue limb
        gl_FragColor = vec4(col, 1.0);
      }`,
  }));
  spin.add(surface);
  const clouds = new THREE.Mesh(
    new THREE.SphereGeometry(1.008, 96, 72),
    new THREE.MeshLambertMaterial({ map: LS.texture('textures/earth_clouds.png'), transparent: true, opacity: 0.5, depthWrite: false }));
  spin.add(clouds);
  group.add(LS.glow(1.025, 0x4da6ff, 2.6, 1.0));
  const setSun = (dir) => uniforms.sunDir.value.copy(dir).normalize();
  return { group, spin, clouds, surface, setSun };
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
    ? new THREE.LineDashedMaterial({ color, dashSize: 0.12, gapSize: 0.08, transparent: true, opacity })
    : new THREE.LineBasicMaterial({ color, transparent: opacity < 1, opacity });
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

/* Plotly layout shared by every 2D chart. */
LS.plotLayout = function (extra) {
  const axis = { gridcolor: 'rgba(148,170,210,0.12)', zerolinecolor: 'rgba(148,170,210,0.2)',
    color: '#8b9bbd', linecolor: 'rgba(148,170,210,0.2)' };
  return Object.assign({
    paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
    font: { color: '#e7edf8', family: 'Segoe UI, system-ui, sans-serif', size: 12 },
    margin: { l: 56, r: 20, t: 44, b: 44 },
    xaxis: Object.assign({}, axis), yaxis: Object.assign({}, axis),
    legend: { bgcolor: 'rgba(12,19,34,0.8)', bordercolor: 'rgba(148,170,210,0.14)', borderwidth: 1 },
    hoverlabel: { bgcolor: '#121b2f', bordercolor: '#5ac8fa', font: { color: '#e7edf8' } },
  }, extra || {});
};
LS.plotConfig = { displaylogo: false, responsive: true,
  modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'] };
