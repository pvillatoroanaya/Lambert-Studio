/* App controller: navigation between views, the shared time bar, the
   animation loop, and the report dialog. */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const started = new Set();
  let active = null;

  LS.setView = async function (id) {
    const view = LS.views[id];
    if (active === view) return;
    document.querySelectorAll('.nav').forEach((b) => b.classList.toggle('active', b.dataset.view === id));
    document.querySelectorAll('.view').forEach((v) => { v.hidden = v.dataset.view !== id; });
    document.querySelectorAll('.ctl').forEach((c) => { c.hidden = c.dataset.for !== id; });
    $('tooltip').hidden = true;
    $('view-title').textContent = view.title;
    $('view-sub').textContent = view.subtitle;
    active = view;
    LS.activeView = view;

    if (!started.has(id)) {
      started.add(id);
      try {
        await view.init();
      } catch (e) {
        console.error(e);
        view.failed = true;
        const webgl = /WebGL/i.test(String(e.message));
        LS.status(webgl ? '3D graphics unavailable' : e.message, 'error');
        const box = document.querySelector(`.view[data-view="${id}"] .empty`) || document.createElement('div');
        box.className = 'empty';
        box.hidden = false;
        box.innerHTML = webgl
          ? '<div><b>3D graphics are not available in this window</b><br>Your graphics driver blocked WebGL. ' +
            'Close the app and start it with <em>run_studio.bat --browser</em> to use your web browser instead.</div>'
          : `<div><b>This view could not start</b><br>${LS.esc(e.message)}</div>`;
        document.querySelector(`.view[data-view="${id}"]`).appendChild(box);
      }
    }
    if (active !== view) return;
    if (view.show) view.show();
    LS.syncTimebar();
  };

  /* ---------------- time bar ---------------- */

  const bar = $('timebar'), slider = $('tb-slider'), rateSel = $('tb-rate');
  let dragging = false;

  LS.syncTimebar = function () {
    const c = active && active.clock;
    bar.classList.toggle('off', !c);
    if (!c) return;
    rateSel.innerHTML = c.rates.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
    if (!c.rates.some(([v]) => v === c.rate)) {
      rateSel.insertAdjacentHTML('beforeend', `<option value="${c.rate}">${c.rate}×</option>`);
    }
    rateSel.value = String(c.rate);
    $('tb-now').textContent = active.nowLabel || 'Now';
  };

  $('tb-play').addEventListener('click', () => { const c = active.clock; if (c) c.playing = !c.playing; });
  rateSel.addEventListener('change', () => { active.clock.rate = +rateSel.value; });
  $('tb-now').addEventListener('click', () => active.onNow && active.onNow());
  slider.addEventListener('pointerdown', () => { dragging = true; });
  window.addEventListener('pointerup', () => { dragging = false; });
  slider.addEventListener('input', () => {
    const c = active.clock;
    if (c.min === null || c.max === null) return;
    c.t = c.min + (slider.value / 1000) * (c.max - c.min);
  });

  window.addEventListener('keydown', (e) => {
    if (e.target.matches('input, select, textarea')) return;
    if (e.code === 'Space' && active && active.clock) { e.preventDefault(); active.clock.playing = !active.clock.playing; }
    if (e.key === 'Escape') $('modal').hidden = true;
  });

  /* ---------------- animation loop ---------------- */

  let last = performance.now(), barTimer = 0, fpsFrames = 0, fpsTime = 0;
  function frame(now) {
    const dt = Math.min((now - last) / 1000, 0.1);
    last = now;
    if (LS.settings.fps) {
      fpsFrames++; fpsTime += dt;
      if (fpsTime >= 0.5) { $('fps').textContent = `${Math.round(fpsFrames / fpsTime)} fps`; fpsFrames = 0; fpsTime = 0; }
    }
    const v = active;
    if (v && started.has(v.id) && !v.failed) {
      try {
        if (v.clock) v.clock.tick(dt);
        if (v.update) v.update(dt);
        if (v.render) v.render();
      } catch (e) {
        console.error(e);
        if (!frame.lastErr || frame.lastErr !== String(e)) {   // log each distinct error once
          frame.lastErr = String(e);
          if (LS.report) LS.report(`${v.id}: ${e.stack || e}`);
        }
      }
      barTimer -= dt;
      if (v.clock && barTimer <= 0) {
        barTimer = 0.1;
        const c = v.clock;
        bar.classList.toggle('playing', c.playing);
        $('tb-clock').textContent = v.clockLabel ? v.clockLabel(c.t) : '';
        if (!dragging && c.min !== null && c.max !== null && c.max > c.min) {
          slider.value = String(Math.round(((c.t - c.min) / (c.max - c.min)) * 1000));
        }
      }
    }
    requestAnimationFrame(frame);
  }

  /* ---------------- settings menu ---------------- */

  const menu = $('settings-menu');
  $('btn-settings').addEventListener('click', (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; });
  document.addEventListener('click', (e) => { if (!menu.hidden && !menu.contains(e.target)) menu.hidden = true; });
  menu.querySelectorAll('input[data-set]').forEach((box) => {
    box.checked = !!LS.settings[box.dataset.set];
    box.addEventListener('change', () => {
      LS.settings[box.dataset.set] = box.checked;
      LS.applySettings();
      $('fps').hidden = !LS.settings.fps;
    });
  });
  $('fps').hidden = !LS.settings.fps;

  /* ---------------- report dialog ---------------- */

  $('modal-close').addEventListener('click', () => { $('modal').hidden = true; });
  $('modal').addEventListener('click', (e) => { if (e.target === $('modal')) $('modal').hidden = true; });
  $('report-save').addEventListener('click', () => LS.download('lambert_report.txt', $('report-text').textContent));
  $('report-copy').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText($('report-text').textContent);
      $('report-copy').textContent = 'Copied';
      setTimeout(() => { $('report-copy').textContent = 'Copy'; }, 1500);
    } catch (e) { /* clipboard unavailable: the text can still be selected */ }
  });

  /* ---------------- link to the desktop launcher ---------------- */

  // "Still open" pings, and a goodbye when the window closes, so the
  // launcher can stop the server exactly when the window goes away.
  const ping = () => fetch('/api/ping').catch(() => {});
  ping();
  setInterval(ping, 5000);
  window.addEventListener('pagehide', () => navigator.sendBeacon('/api/bye', '{}'));

  // JavaScript errors go to the log file, so problems can be diagnosed.
  let reported = 0;
  function report(message) {
    if (reported++ > 20) return;
    fetch('/api/log', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }) }).catch(() => {});
  }
  window.addEventListener('error', (e) => report(`${e.message} @ ${e.filename}:${e.lineno}`));
  window.addEventListener('unhandledrejection', (e) => report(`Unhandled: ${e.reason && (e.reason.stack || e.reason)}`));
  LS.report = report;

  /* ---------------- start ---------------- */

  document.querySelectorAll('.nav').forEach((b) => b.addEventListener('click', () => LS.setView(b.dataset.view)));

  (async function start() {
    // Every 3D view lights its scene from the Sun's real direction, which
    // needs the planet table, so it is loaded before anything is drawn.
    try {
      await LS.loadPlanets();
    } catch (e) {
      LS.status(e.message, 'error');
      return;
    }
    await LS.setView('orbit');
    requestAnimationFrame(frame);
    // Solve the example straight away, so the first thing on screen is an orbit.
    $('btn-solve').click();
    // Opening the page as .../#near (etc.) goes straight to that view.
    // A sub-mode can follow a slash, e.g. #mission/route.
    const [wanted, sub] = location.hash.slice(1).split('/');
    if (wanted && LS.views[wanted]) {
      await LS.setView(wanted);
      const btn = sub && document.querySelector(`.ctl[data-for="${wanted}"] .seg button[data-m="${sub}"]`);
      if (btn) btn.click();
    }
  })();
})();
