// Review build only (never in the public build): shows each image's rights status, who to ask,
// and what the public build would show today. Data comes from <script id="review-data">.
(function () {
  const dataEl = document.getElementById('review-data');
  if (!dataEl) return;
  const { items } = JSON.parse(dataEl.textContent);
  const KEY = 'portfolio-review-main-v1';
  const state = { badges: false, preview: false, open: false };
  try {
    Object.assign(state, JSON.parse(localStorage.getItem(KEY) || '{}'));
  } catch (e) {}
  const save = () => {
    try {
      localStorage.setItem(KEY, JSON.stringify(state));
    } catch (e) {}
  };
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const ORDER = { blocked: 0, check: 1, clear: 2 };
  const ids = Object.keys(items).sort((a, b) => ORDER[items[a].level] - ORDER[items[b].level] || a.localeCompare(b));
  const blocked = ids.filter((id) => !items[id].cleared);

  /* ---------- badges on the images ---------- */
  const layer = el('div', 'rv-layer');
  document.body.append(layer);
  let queued = false;
  function drawBadges() {
    queued = false;
    layer.textContent = '';
    if (!state.badges) return;
    document.querySelectorAll('[data-mid]').forEach((node) => {
      // Skip anything not drawn: closed rows (their content still reports a box), the preview's hidden half.
      if (node.closest('details:not([open]) > :not(summary), [hidden]')) return;
      if (node.checkVisibility && !node.checkVisibility()) return;
      const r = node.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return;
      const it = items[node.dataset.mid];
      if (!it) return;
      const b = el('div', `rv-badge rv-${it.level}`, it.short + (it.quality === 'low' ? ' · low-res' : ''));
      b.title = `${node.dataset.mid}: ${it.label}`;
      layer.append(b);
      // Top right: cards already use the top-left corner (award badge) and the bottom (credit, play button).
      b.style.top = `${r.top + scrollY + 8}px`;
      b.style.left = `${Math.max(r.left, r.right - b.offsetWidth - 8) + scrollX}px`;
    });
  }
  const redraw = () => {
    if (!queued) {
      queued = true;
      requestAnimationFrame(drawBadges);
    }
  };
  ['scroll', 'resize', 'load'].forEach((e) => addEventListener(e, redraw, { passive: true }));
  ['toggle', 'transitionend', 'load'].forEach((e) => document.addEventListener(e, redraw, true));

  /* ---------- public preview: swap in what the public build would show ---------- */
  function applyPreview() {
    document.querySelectorAll('.rv-slot').forEach((slot) => {
      const hide = state.preview && slot.dataset.rv.split(' ').some((id) => !items[id] || !items[id].cleared);
      slot.hidden = hide;
      const alt = slot.nextElementSibling;
      if (alt && alt.classList.contains('rv-alt')) alt.hidden = !hide;
    });
    redraw();
  }

  /* ---------- panel ---------- */
  const button = el('button', 'rv-button');
  button.type = 'button';
  button.setAttribute('aria-expanded', String(state.open));
  button.append(el('span', 'rv-dot'), el('span', null, 'Review'), el('span', 'rv-sub', blocked.length ? `${blocked.length} to ask` : 'all cleared'));
  if (blocked.length) button.classList.add('has-blocked');

  const panel = el('aside', 'rv-panel');
  panel.setAttribute('aria-label', 'Image rights review');
  panel.hidden = !state.open;
  const head = el('div', 'rv-head');
  head.append(
    el('strong', null, 'Image rights'),
    el('p', null, `Review build, not public. ${ids.length} images and videos on this page; ${blocked.length} need permission before the public build can use them.`),
  );
  const toggles = el('div', 'rv-toggles');
  for (const [key, label] of [['badges', 'Status on images'], ['preview', 'Preview public build']]) {
    const l = el('label');
    const box = el('input');
    box.type = 'checkbox';
    box.checked = state[key];
    box.addEventListener('change', () => {
      state[key] = box.checked;
      save();
      key === 'preview' ? applyPreview() : redraw();
    });
    l.append(box, document.createTextNode(label));
    toggles.append(l);
  }
  head.append(toggles);

  const list = el('ul', 'rv-list');
  for (const id of ids) {
    const it = items[id];
    // An item can appear twice (a stand-in hidden until the public preview): prefer the copy on show.
    const nodes = [...document.querySelectorAll(`[data-mid="${CSS.escape(id)}"]`)];
    const visibleNode = () => nodes.find((n) => !n.closest('[hidden]')) ?? nodes[0];
    const node = nodes[0];
    const li = el('li', 'rv-item');
    const thumb = el('img', 'rv-thumb');
    thumb.alt = '';
    thumb.loading = 'lazy';
    const src = node && (node.tagName === 'VIDEO' ? node.poster : node.currentSrc || node.src);
    if (src) thumb.src = src;
    const body = el('div');
    const status = el('span', `rv-status rv-${it.level}`, it.label);
    body.append(status, el('div', 'rv-credit', it.credit));
    if (!it.cleared) {
      const ask = el('div', 'rv-ask', `Ask: ${it.holder}`);
      if (it.contact) {
        const mail = (it.contact.match(/[\w.+-]+@[\w-]+(\.[\w-]+)+/) || [])[0];
        ask.append(document.createTextNode(' — '));
        if (mail) {
          const a = el('a', null, it.contact);
          a.href = `mailto:${mail}`;
          ask.append(a);
        } else ask.append(document.createTextNode(it.contact));
      }
      body.append(ask);
    }
    body.append(el('div', 'rv-meta', `${id} · ${it.size}${it.quality ? ` · ${it.quality}` : ''} · ${it.source}`));
    if (node) {
      const go = el('button', null, 'Show on page');
      go.type = 'button';
      go.addEventListener('click', () => {
        const node = visibleNode();
        let d = node.closest('details');
        while (d) {
          d.open = true;
          d = d.parentElement && d.parentElement.closest('details');
        }
        node.scrollIntoView({ behavior: 'smooth', block: 'center' });
        node.classList.add('rv-flash');
        setTimeout(() => node.classList.remove('rv-flash'), 1600);
      });
      body.append(go);
    }
    li.append(thumb, body);
    list.append(li);
  }
  const foot = el(
    'p',
    'rv-foot',
    'npm run build:public stops while any image here says "Ask". Record the holder\'s OK in src/content/media.json, or build with --drop-blocked to use each image\'s stand-in.',
  );
  panel.append(head, list, foot);
  button.addEventListener('click', () => {
    state.open = !state.open;
    panel.hidden = !state.open;
    button.setAttribute('aria-expanded', String(state.open));
    save();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && state.open) {
      state.open = false;
      panel.hidden = true;
      button.setAttribute('aria-expanded', 'false');
      save();
    }
  });
  document.body.append(panel, button);
  applyPreview();
})();
