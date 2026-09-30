/* "How certain is this orbit?" (Orbit tab). Python (uncertainty.py)
   re-solves the orbit thousands of times with random measurement errors;
   this draws the cloud of possible orbits and explains what it means. */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const f = (x, d) => LS.fmt(x, d);
  const view = LS.views.orbit;
  let cloud = null, last = null;

  // Illustrative measurement quality (1 standard deviation).
  const SENSORS = [
    { label: 'Tracking radar', angle: 0.01, range: 0.015, time: 0.001 },
    { label: 'Precise (laser ranging)', angle: 0.001, range: 0.001, time: 0.0001 },
    { label: 'Rough (amateur)', angle: 0.1, range: 1, time: 0.1 },
  ];

  function init() {
    $('mc-presets').innerHTML = SENSORS.map((s, k) => `<button data-k="${k}">${s.label}</button>`).join('');
    $('mc-presets').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
      const s = SENSORS[+b.dataset.k];
      $('mc-angle').value = s.angle; $('mc-range').value = s.range; $('mc-time').value = s.time;
      run();
    }));
    $('btn-mc').addEventListener('click', run);
    $('mc-close').addEventListener('click', () => { $('mc-panel').hidden = true; clear(); });
    document.querySelectorAll('#mode-seg button').forEach((b) => b.addEventListener('click', () => {
      $('mc-box').hidden = b.dataset.mode !== 'observations';
    }));
    view.onSolved = () => { $('mc-panel').hidden = true; clear(); };
  }

  function clear() {
    const s3 = view.scene && view.scene();
    if (cloud && s3) {
      cloud.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
      s3.scene.remove(cloud);
    }
    cloud = null;
  }

  async function run() {
    $('mc-err').hidden = true;
    if (view.mode() !== 'observations') return;
    const req = Object.assign(view.request(), {
      sigma_angle: $('mc-angle').value, sigma_range: $('mc-range').value, sigma_time: $('mc-time').value, n: 3000,
    });
    try {
      const res = await LS.busy('Re-solving the orbit 3,000 times…', $('btn-mc'), () => LS.api('/api/uncertainty', req));
      last = res;
      draw(res);
      explain(res);
      LS.emit('mc-result', res);
    } catch (e) {
      $('mc-err').textContent = e.message;
      $('mc-err').hidden = false;
    }
  }

  function draw(res) {
    const s3 = view.scene && view.scene();
    if (!s3) return;
    clear();
    cloud = new THREE.Group();
    const S = view.scale;
    res.orbits.forEach((pts) => {
      cloud.add(LS.line(pts.map((p) => LS.v3(p, S)), 0xff8a80, 0.18));
    });
    s3.scene.add(cloud);
  }

  function explain(res) {
    const E = res.elements;
    const sens = res.sensitivity;
    const names = { angle: 'the angles', range: 'the range', time: 'the clock' };
    const ranked = Object.entries(sens).sort((a, b) => b[1].a_std - a[1].a_std);
    const main = ranked[0][0];
    const po = res.per_orbit;
    const week = po[po.length - 1];
    const perOrbit = po.length > 2 ? po[2].along_std / 2 : po[1].along_std;
    const bar = (v, max) => `<i style="width:${Math.max(2, 100 * v / max).toFixed(0)}%"></i>`;
    const maxS = Math.max(...ranked.map((r) => r[1].a_std));
    $('mc-text').innerHTML = `
      <h4>How certain is this orbit?</h4>
      <p>With these measurement errors, the ${res.n.toLocaleString()} re-solved orbits (red, in 3D) agree on the size of the
        orbit to within <b>±${f(E.a.std, 1)} km</b> and on its tilt to within <b>±${f(E.i.std, 3)}°</b>. The height of the
        lowest point varies by <b>±${f(E.perigee_alt.std, 1)} km</b>.</p>
      <p><b>What matters most:</b> ${names[main]}. Each error source on its own:</p>
      <div class="mc-bars">${ranked.map(([k, v]) => `<div><span>${names[k]}</span>${bar(v.a_std, maxS)}<b>±${f(v.a_std, 2)} km</b></div>`).join('')}</div>
      <p>An error in the orbit's size means an error in its <b>period</b> (±${f(E.period.std, 1)} s here). Each lap the
        prediction drifts about <b>${f(perOrbit, 0)} km</b> further along the orbit, so after a week it is
        ~${f(week.along_std, 0)} km off. That is why tracking stations keep measuring and updating the orbit.</p>`;
    $('mc-panel').hidden = false;
    Plotly.react('ch-mc', [
      { x: po.map((p) => p.hours / 24), y: po.map((p) => p.along_std), name: 'Along the orbit (ahead/behind)',
        type: 'scatter', mode: 'lines+markers', line: { color: '#ff8a80', width: 2.5 } },
      { x: res.growth.map((g) => g.hours / 24), y: res.growth.map((g) => g.radial), name: 'Up/down (radial)',
        type: 'scatter', mode: 'lines', line: { color: '#5ac8fa', width: 1.5, dash: 'dot' } },
      { x: res.growth.map((g) => g.hours / 24), y: res.growth.map((g) => g.cross), name: 'Sideways',
        type: 'scatter', mode: 'lines', line: { color: '#6ee7a8', width: 1.5, dash: 'dot' } },
    ], LS.plotLayout({
      title: { text: 'Position uncertainty of the prediction (km, 1σ)', x: 0.02, font: { size: 12.5 } },
      margin: { l: 50, r: 12, t: 58, b: 38 },
      legend: { orientation: 'h', y: 1.13, x: 0, font: { size: 10.5 } },
      xaxis: { title: { text: 'days after the first observation', font: { size: 11 } }, gridcolor: 'rgba(148,170,210,0.12)', color: '#8b9bbd' },
      yaxis: { gridcolor: 'rgba(148,170,210,0.12)', color: '#8b9bbd', rangemode: 'tozero' },
    }), LS.plotConfig);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
