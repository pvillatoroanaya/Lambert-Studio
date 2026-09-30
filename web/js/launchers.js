/* Which rocket can launch it? Payload-vs-C3 curves (launchers.py: NASA
   Launch Services Program planning data, via the AMAT dataset), loaded
   once and interpolated here. */
'use strict';

(function () {
  const L = { data: null };
  LS.launch = L;

  L.load = async function () {
    if (!L.data) L.data = await LS.api('/api/launchers');
    return L.data;
  };

  L.capacity = function (name, c3) {
    const pts = L.data.curves[name];
    if (c3 < pts[0][0] - 1 || c3 > pts[pts.length - 1][0]) return null;
    for (let k = 1; k < pts.length; k++) {
      if (c3 <= pts[k][0]) {
        const [x0, y0] = pts[k - 1], [x1, y1] = pts[k];
        return y0 + (y1 - y0) * (c3 - x0) / (x1 - x0);
      }
    }
    return pts[0][1];
  };

  /* All vehicles, the ones that can do it first (smallest capable first). */
  L.options = function (c3, mass) {
    const rows = L.data.order.map((name) => {
      const cap = L.capacity(name, c3);
      return { name, cap, fits: cap !== null && cap >= mass, ...L.data.info[name] };
    });
    const fit = rows.filter((r) => r.fits).sort((a, b) => a.cap - b.cap);
    return fit.concat(rows.filter((r) => !r.fits));
  };

  L.smallest = function (c3, mass) {
    const o = L.options(c3, mass).find((r) => r.fits);
    return o ? o.name : null;
  };

  /* A short verdict for a card or HUD. */
  L.verdict = function (c3, mass) {
    if (!L.data) return '';
    if (c3 > 100) return `C₃ ${LS.fmt(c3, 0)} is beyond these rockets' published curves (they stop at 100)`;
    const s = L.smallest(c3, mass);
    return s ? s : `no single rocket in the dataset can launch ${LS.fmt(mass, 0)} kg at C₃ ${LS.fmt(c3, 0)}`;
  };

  /* A table of every rocket's capacity at this C3. */
  L.table = function (c3, mass) {
    if (!L.data) return '';
    const rows = L.options(c3, mass).map((r) => `<div class="lv${r.fits ? ' ok' : ''}">
      <span>${r.name}</span><b>${r.cap === null ? '—' : `${LS.fmt(r.cap, 0)} kg`}</b></div>`).join('');
    return `<div class="lv-table">${rows}</div>
      <p class="hint">Mass each rocket can send away at C₃ = ${LS.fmt(c3, 1)} km²/s² (NASA planning curves with margins;
      green: can launch ${LS.fmt(mass, 0)} kg).</p>`;
  };
})();
