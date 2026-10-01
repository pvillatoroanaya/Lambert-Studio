/* "Check in full solar-system gravity" (nbody.py): the designed route is
   flown again with every planet (and the Moon) pulling at once, and small
   trajectory-correction manoeuvres keep it on target, as navigators do. */
'use strict';

(function () {
  const f = (x, d) => LS.fmt(x, d);
  const N = {};
  LS.nbody = N;
  const day = (iso) => iso.slice(0, 10);
  const km = (x) => (Math.abs(x) >= 1e5 ? `${f(x / 1000, 0)} thousand km` : `${f(x, 0)} km`);
  // What the simple-model trajectory would do if flown uncorrected.
  const fate = (u) => (u.impact ? `<b>crash into ${u.planet}</b>` : `miss ${u.planet} by <b>${km(u.miss_km)}</b>`);

  N.run = function (req, button) {
    return LS.busy('Flying the route in full solar-system gravity (10–60 s)…', button,
      () => LS.api('/api/verify_route', req));
  };

  /* A HUD box with the results. */
  N.html = function (v) {
    const u = v.uncorrected;
    const tcm = v.tcms.map((c) => {
      const what = c.kind === 'launch aim' ? `Launch aimed (energy ${c.launch_change >= 0 ? '+' : ''}${f(c.launch_change * 1000, 1)} m/s)`
        : c.kind === 'approach TCM' ? `Approach correction → ${c.to}` : `Correction → ${c.to}`;
      return [`${day(c.iso)}`, `${what}${c.kind === 'launch aim' ? '' : `: <b>${f(c.dv * 1000, 1)} m/s</b>`}`];
    });
    const enc = v.encounters.map((e) => [`${e.planet} ${e.kind === 'flyby' ? 'flyby' : 'arrival'}`,
      `${km(e.alt_actual)} <span class="muted">(planned ${km(e.alt_planned)})</span>`]);
    return `<div class="box nbody"><h4>Full solar-system gravity</h4>
      <div class="verdict ${Math.abs(v.total_dv - v.design_total_dv) < 0.1 ? 'good' : 'bad'}">Δv ${f(v.total_dv, 3)} km/s
        <small>(simple model ${f(v.design_total_dv, 3)})</small></div>
      <p>Without corrections, the simple-model trajectory would ${fate(u)}.
        With the corrections below it passes every planet as listed (a distant flyby aimed straight on to the next
        planet may come out a little higher or lower than designed).</p>
      ${LS.kv(tcm)}
      <div style="margin-top:6px">${LS.kv(enc)}</div>
      ${v.notes.map((n) => `<p class="hint">⚠ ${LS.esc(n)}</p>`).join('')}
      <p class="hint" style="margin-top:6px">Sun + ${v.bodies.join(', ')} (NASA/JPL DE440s) · ${v.evaluations.toLocaleString('en-US')} force
        evaluations in ${f(v.seconds, 1)} s</p></div>`;
  };

  /* A paragraph for the story panel. */
  N.story = function (v) {
    const u = v.uncorrected;
    const tcmTotal = v.tcm_total * 1000;
    return `<h4>Checked in full solar-system gravity</h4>
      <p>The route above was designed with <b>patched conics</b>: at each moment only one body pulls on the spacecraft.
        Real spacecraft feel the Sun, every planet and the Moon at once. Flown that way, the same launch would ${fate(u)}. Navigators fix this the way this check does: the launch is aimed with the
        full model, and small <b>trajectory-correction manoeuvres</b> (TCMs) adjust the path so each planet is passed at the
        planned point and time (aimed in the "B-plane" through the planet). Here the corrections add up to
        <b>${f(tcmTotal, 1)} m/s</b>, and the whole trip needs ${f(v.total_dv, 3)} km/s instead of ${f(v.design_total_dv, 3)}.
        Real missions budget a few tens of m/s for TCMs.</p>`;
  };
})();
