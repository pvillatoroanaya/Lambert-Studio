/* Page shell: the parts that every tab shares. It reshapes the panel markup
   once at start-up, so each tab's HTML stays plain:
     - a header band (title, one short line, a faint copy of the tab's icon)
     - every "h3 + what follows" becomes a collapsible card
     - long hint paragraphs hide behind a small (i) button
     - the icon sidebar can widen into icons with names (remembered) */
'use strict';

(function () {
  const $ = (id) => document.getElementById(id);

  function headers() {
    document.querySelectorAll('.panel .ctl').forEach((ctl) => {
      const h2 = ctl.querySelector(':scope > h2');
      if (!h2) return;
      const head = document.createElement('div');
      head.className = 'ctl-head';
      const lede = h2.nextElementSibling && h2.nextElementSibling.classList.contains('lede') ? h2.nextElementSibling : null;
      ctl.insertBefore(head, h2);
      head.appendChild(h2);
      if (lede) head.appendChild(lede);
      const icon = document.querySelector(`.nav[data-view="${ctl.dataset.for}"] svg`);
      if (icon) {
        const g = icon.cloneNode(true);
        g.classList.add('ctl-glyph');
        head.appendChild(g);
      }
    });
  }

  function cards() {
    document.querySelectorAll('.panel .ctl h3').forEach((h3) => {
      if (h3.parentElement.classList.contains('pcard')) return;      // already a card title
      const card = document.createElement('section');
      card.className = 'pcard';
      h3.parentNode.insertBefore(card, h3);
      card.appendChild(h3);
      while (card.nextElementSibling && card.nextElementSibling.tagName !== 'H3') card.appendChild(card.nextElementSibling);
      h3.addEventListener('click', () => card.classList.toggle('collapsed'));
    });
  }

  function infoIcons() {
    document.querySelectorAll('.panel p.hint').forEach((p) => {
      if (p.id || p.textContent.length < 70 || p.closest('.menu')) return;
      const box = document.createElement('details');
      box.className = 'info';
      box.innerHTML = '<summary><i>i</i>About this</summary>';
      p.parentNode.insertBefore(box, p);
      box.appendChild(p);
    });
  }

  function sidebar() {
    const rail = document.querySelector('.rail');
    let group = null;
    [...rail.children].forEach((el) => {
      if (el.classList.contains('nav-group')) {
        group = el.textContent.trim() === 'Earth orbit' ? 'earth' : 'deep';
        el.dataset.g = group;
      } else if (el.classList.contains('nav')) {
        if (group) el.dataset.g = group;
        const label = document.createElement('span');
        label.className = 'nav-l';
        label.textContent = el.dataset.label;
        el.appendChild(label);
      }
    });
    const spacer = document.createElement('div');
    spacer.className = 'nav-spacer';
    const toggle = document.createElement('button');
    toggle.className = 'rail-toggle';
    toggle.title = 'Show or hide the names';
    toggle.setAttribute('aria-label', 'Expand or collapse the sidebar');
    toggle.innerHTML = '<svg viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg><span class="nav-l">Collapse</span>';
    rail.append(spacer, toggle);

    const apply = (open) => {
      document.body.classList.toggle('rail-open', open);
      toggle.querySelector('.nav-l').textContent = open ? 'Collapse' : 'Expand';
      try { localStorage.setItem('ls-rail', open ? '1' : '0'); } catch (e) { /* not remembered */ }
      // the 3D views resize with their container
      setTimeout(() => window.dispatchEvent(new Event('resize')), 260);
    };
    let open = false;
    try { open = localStorage.getItem('ls-rail') === '1'; } catch (e) { /* default */ }
    apply(open);
    toggle.addEventListener('click', () => apply(!document.body.classList.contains('rail-open')));
  }

  LS.shell = function () {
    headers();
    cards();
    infoIcons();
    sidebar();
  };
})();
