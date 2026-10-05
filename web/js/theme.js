/* Look and feel: the light / dark theme, the "futuristic effects" switch,
   the 3D tilt on the start page, and a short edge pulse on the HUD boxes
   when their numbers are refreshed. Pure presentation: no physics here. */
'use strict';

(function () {
  const root = document.documentElement;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');

  /* ---------------- theme ---------------- */

  LS.theme = root.dataset.theme === 'dark' ? 'dark' : 'light';

  LS.setTheme = function (name) {
    LS.theme = name === 'dark' ? 'dark' : 'light';
    root.dataset.theme = LS.theme;
    try { localStorage.setItem('ls-theme', LS.theme); } catch (e) { /* not remembered */ }
    document.querySelectorAll('[data-theme-toggle]').forEach((b) => {
      b.setAttribute('aria-pressed', LS.theme === 'dark' ? 'true' : 'false');
      b.title = LS.theme === 'dark' ? 'Switch to the bright theme' : 'Switch to the dark theme';
    });
  };
  LS.toggleTheme = () => LS.setTheme(LS.theme === 'dark' ? 'light' : 'dark');
  document.querySelectorAll('[data-theme-toggle]').forEach((b) => b.addEventListener('click', LS.toggleTheme));
  LS.setTheme(LS.theme);

  /* ---------------- effects switch ---------------- */

  const baseApply = LS.applySettings;
  LS.applySettings = function () {
    baseApply();
    document.body.classList.toggle('no-fx', !LS.settings.fx || reduced.matches);
  };
  document.body.classList.toggle('no-fx', !LS.settings.fx || reduced.matches);

  /* ---------------- start page: pointer depth ---------------- */

  const landing = document.getElementById('landing');
  LS.pointer = { x: 0, y: 0 };                       // -1 .. 1 across the window, smoothed by the landing view
  window.addEventListener('pointermove', (e) => {
    LS.pointer.x = (e.clientX / innerWidth) * 2 - 1;
    LS.pointer.y = (e.clientY / innerHeight) * 2 - 1;
  }, { passive: true });

  // Each module card tilts toward the pointer and carries a moving highlight.
  landing.querySelectorAll('.ld-modules button').forEach((b) => {
    b.addEventListener('pointermove', (e) => {
      if (document.body.classList.contains('no-fx')) return;
      const r = b.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
      b.style.setProperty('--mx', `${x * 100}%`);
      b.style.setProperty('--my', `${y * 100}%`);
      b.style.setProperty('--rx', `${((0.5 - y) * 9).toFixed(2)}deg`);
      b.style.setProperty('--ry', `${((x - 0.5) * 11).toFixed(2)}deg`);
    });
    b.addEventListener('pointerleave', () => {
      b.style.setProperty('--rx', '0deg');
      b.style.setProperty('--ry', '0deg');
    });
  });

  /* ---------------- HUD refresh pulse ---------------- */

  // A HUD box that gets new numbers glows once. Boxes that change many times
  // a second (live telemetry) are left alone, so nothing ever flickers.
  const last = new WeakMap();
  const watch = new MutationObserver((list) => {
    if (document.body.classList.contains('no-fx')) return;
    const now = performance.now();
    const hit = new Set();
    list.forEach((m) => { const h = m.target.closest && m.target.closest('.hud'); if (h) hit.add(h); });
    hit.forEach((h) => {
      const prev = last.get(h) || 0;
      last.set(h, now);
      if (now - prev < 1500) return;
      h.classList.remove('pulse');
      void h.offsetWidth;                              // restart the animation
      h.classList.add('pulse');
    });
  });
  document.querySelectorAll('.hud').forEach((h) => watch.observe(h, { childList: true, subtree: true, characterData: true }));
})();
