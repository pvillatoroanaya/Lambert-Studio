/* Cinematic shell: the controls panel that floats over the full-screen 3D
   window (hide it with the button or the [ key), and a short curtain wipe
   between views. Presentation only. */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);
  const body = document.body;

  /* ---------------- floating controls panel ---------------- */

  const btn = $('btn-panel');
  function setPanel(open) {
    body.classList.toggle('panel-closed', !open);
    btn.setAttribute('aria-pressed', open ? 'true' : 'false');
    try { localStorage.setItem('ls-panel', open ? '1' : '0'); } catch (e) { /* not remembered */ }
  }
  let open = true;
  try { open = localStorage.getItem('ls-panel') !== '0'; } catch (e) { /* default */ }
  setPanel(open);
  btn.addEventListener('click', () => setPanel(body.classList.contains('panel-closed')));
  window.addEventListener('keydown', (e) => {
    if (e.key !== '[' || e.ctrlKey || e.altKey || e.metaKey) return;
    if (e.target.matches && e.target.matches('input, select, textarea')) return;
    if (LS.activeView && LS.activeView.id === 'landing') return;
    setPanel(body.classList.contains('panel-closed'));
  });

  /* ---------------- curtain between views ---------------- */

  const curtain = $('curtain');
  const baseSetView = LS.setView;
  let first = true, busy = false;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  LS.setView = async function (id) {
    if (first || busy || body.classList.contains('no-fx')) { first = false; return baseSetView(id); }
    if (LS.views[id] === LS.activeView) return;
    busy = true;
    // The curtain only covers the screen when you go in or out of the start page.
    const fromHome = LS.activeView && LS.activeView.id === 'landing', toHome = id === 'landing';
    curtain.className = (fromHome || toHome) ? 'on big' : 'on';
    await wait(fromHome || toHome ? 380 : 170);
    try { await baseSetView(id); }
    finally {
      curtain.classList.add('off');
      await wait(420);
      curtain.className = '';
      busy = false;
    }
  };
})();
