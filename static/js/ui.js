// Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
// UI toolkit: menu bar, dialogs, toasts, status bar, Markdown and code views, theme.
(function () {
  'use strict';
  const PB = window.PB;
  const { esc, el } = PB.util;
  const ui = PB.ui = {};

  // ---------------------------------------------------------------- theme
  ui.applyTheme = function (theme) {
    const value = theme || (PB.config && PB.config.theme) || 'system';
    document.documentElement.setAttribute('data-theme', value);
    PB.bus.emit('theme', value);
  };
  ui.isDark = function () {
    const t = document.documentElement.getAttribute('data-theme');
    if (t === 'dark') return true;
    if (t === 'light') return false;
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
  };
  if (window.matchMedia) window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => PB.bus.emit('theme', document.documentElement.getAttribute('data-theme')));

  // ---------------------------------------------------------------- markdown + code
  const CM_MODES = { python: 'python', r: 'r', javascript: 'javascript', typescript: 'javascript', shellscript: 'shell', bash: 'shell', sh: 'shell',
    powershell: 'shell', markdown: 'markdown', md: 'markdown', yaml: 'yaml', yml: 'yaml', json: { name: 'javascript', json: true }, sql: 'sql', julia: 'julia',
    py: 'python', js: 'javascript', jl: 'julia' };
  ui.cmMode = (lang) => CM_MODES[String(lang || '').toLowerCase()] || null;
  ui.cmTheme = () => (ui.isDark() ? 'material-darker' : 'default');

  function highlight(code, lang) {
    const mode = ui.cmMode(lang);
    if (!mode || !window.CodeMirror || !CodeMirror.runMode) return esc(code);
    const holder = document.createElement('div');
    try { CodeMirror.runMode(code, mode, holder); return holder.innerHTML; } catch (e) { return esc(code); }
  }
  ui.markdown = function (text) {
    if (!text) return '';
    let html;
    try {
      marked.setOptions({ gfm: true, breaks: false });
      const renderer = new marked.Renderer();
      renderer.code = function (code, lang) {
        const c = typeof code === 'object' ? code.text : code;
        const l = typeof code === 'object' ? code.lang : lang;
        return '<pre class="cm-s-' + ui.cmTheme() + '"><code>' + highlight(c, l) + '</code></pre>';
      };
      html = marked.parse(String(text), { renderer });
    } catch (e) { html = '<pre>' + esc(text) + '</pre>'; }
    try { html = DOMPurify.sanitize(html, { USE_PROFILES: { html: true }, ADD_ATTR: ['target'] }); } catch (e) { /* keep */ }
    return html;
  };
  ui.codeView = function (container, code, lang, options) {
    container.innerHTML = '';
    if (!window.CodeMirror) { container.innerHTML = '<pre>' + esc(code) + '</pre>'; return null; }
    const cm = CodeMirror(container, Object.assign({ value: code || '', mode: ui.cmMode(lang) || 'text/plain', readOnly: true, lineNumbers: true,
      lineWrapping: true, theme: ui.cmTheme(), viewportMargin: 50 }, options || {}));
    PB.bus.on('theme', () => cm.setOption('theme', ui.cmTheme()));
    return cm;
  };

  // ---------------------------------------------------------------- toasts
  ui.toast = function (message, kind, opts) {
    const box = document.getElementById('toasts');
    const icons = { ok: 'check-circle', bad: 'x-circle', warn: 'alert-triangle', info: 'info' };
    const t = el('<div class="toast ' + esc(kind || 'info') + '">' + PB.icon(icons[kind] || 'info') + '<div class="grow">' + esc(message) + '</div><span class="close" title="Dismiss">' + PB.icon('x', 14) + '</span></div>');
    t.querySelector('.close').addEventListener('click', () => t.remove());
    box.appendChild(t);
    const ms = (opts && opts.timeout) || (kind === 'bad' ? 9000 : 4500);
    setTimeout(() => t.remove(), ms);
    return t;
  };

  // ---------------------------------------------------------------- dialogs
  const dialogs = [];
  ui.dialog = function (spec) {
    const host = document.getElementById('dialogs');
    const overlay = el('<div class="overlay" role="dialog" aria-modal="true"></div>');
    const dlg = el('<div class="dialog ' + (spec.wide ? 'wide' : '') + (spec.narrow ? ' narrow' : '') + '"><div class="dialog-head">' +
      (spec.icon ? PB.icon(spec.icon, 18) : '') + '<h2>' + esc(spec.title || '') + '</h2><button class="icon-btn" data-close title="Close">' + PB.icon('x') + '</button></div>' +
      '<div class="dialog-body"></div><div class="dialog-foot"></div></div>');
    overlay.appendChild(dlg);
    const body = dlg.querySelector('.dialog-body');
    if (typeof spec.body === 'string') body.innerHTML = spec.body; else if (spec.body) body.appendChild(spec.body);
    const foot = dlg.querySelector('.dialog-foot');
    const handle = { el: dlg, overlay, body, foot, close(result) { overlay.remove(); const i = dialogs.indexOf(handle); if (i !== -1) dialogs.splice(i, 1); if (spec.onClose) spec.onClose(result); } };
    (spec.buttons || [{ label: 'Close' }]).forEach((b) => {
      const btn = el('<button class="' + (b.primary ? 'primary' : '') + (b.danger ? ' danger' : '') + (b.left ? ' left' : '') + '">' + (b.icon ? PB.icon(b.icon) : '') + esc(b.label) + '</button>');
      btn.addEventListener('click', async () => {
        if (!b.action) { handle.close(); return; }
        btn.disabled = true;
        try { const r = await b.action(handle, btn); if (r !== false) handle.close(r); } catch (e) { ui.toast(e.message || String(e), 'bad'); }
        finally { btn.disabled = false; }
      });
      foot.appendChild(btn);
    });
    if (!foot.children.length) foot.remove();
    dlg.querySelector('[data-close]').addEventListener('click', () => handle.close());
    overlay.addEventListener('mousedown', (e) => { if (e.target === overlay && spec.closeOnOverlay !== false) handle.close(); });
    host.appendChild(overlay);
    dialogs.push(handle);
    if (spec.onOpen) spec.onOpen(handle);
    const focus = dlg.querySelector('input, textarea, select, button.primary');
    if (focus) setTimeout(() => focus.focus(), 30);
    return handle;
  };
  ui.closeTopDialog = function () { const d = dialogs[dialogs.length - 1]; if (d) { d.close(); return true; } return false; };
  ui.confirm = function (spec) {
    return new Promise((resolve) => {
      let checked = !spec.checkbox;
      const body = el('<div><p>' + (spec.html ? spec.message : esc(spec.message || '')) + '</p>' + (spec.checkbox ? '<label class="inline"><input type="checkbox"> ' + esc(spec.checkbox) + '</label>' : '') + '</div>');
      const dlg = ui.dialog({ title: spec.title || 'Please confirm', narrow: true, body, icon: spec.danger ? 'alert-triangle' : 'help-circle',
        buttons: [{ label: spec.cancelLabel || 'Cancel' }, { label: spec.okLabel || 'OK', primary: !spec.danger, danger: !!spec.danger, action: () => { if (!checked) { ui.toast('Tick the box first.', 'warn'); return false; } resolve(true); } }],
        onClose: (r) => { if (r !== true) resolve(false); } });
      const cb = body.querySelector('input[type="checkbox"]');
      if (cb) cb.addEventListener('change', () => { checked = cb.checked; });
      dlg.foot.lastElementChild.addEventListener('click', () => {}, { once: true });
    });
  };
  ui.prompt = function (spec) {
    return new Promise((resolve) => {
      const body = el('<div>' + (spec.message ? '<p>' + esc(spec.message) + '</p>' : '') + '<label>' + esc(spec.label || '') + '<input type="text" value="' + esc(spec.value || '') + '" placeholder="' + esc(spec.placeholder || '') + '"></label>' + (spec.hint ? '<span class="hint">' + esc(spec.hint) + '</span>' : '') + '</div>');
      const input = body.querySelector('input');
      let done = false;
      const dlg = ui.dialog({ title: spec.title || '', narrow: true, body, buttons: [{ label: 'Cancel' }, { label: spec.okLabel || 'OK', primary: true, action: () => { done = true; resolve(input.value); } }], onClose: () => { if (!done) resolve(null); } });
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { done = true; resolve(input.value); dlg.close(true); } });
      setTimeout(() => { input.focus(); input.select(); }, 30);
    });
  };
  ui.lightbox = function (src, caption) {
    const box = el('<div class="lightbox"><figure style="margin:0;text-align:center"><img src="' + esc(src) + '" alt="' + esc(caption || '') + '"><figcaption style="color:#ddd;margin-top:6px">' + esc(caption || '') + '</figcaption></figure></div>');
    box.addEventListener('click', () => box.remove());
    document.body.appendChild(box);
  };
  ui.tabs = function (container, panes, initial) {
    // container: element holding .tabs buttons[data-tab] and .tab-pane[data-pane]
    const buttons = container.querySelectorAll('.tabs button');
    function activate(id) {
      buttons.forEach((b) => b.classList.toggle('active', b.dataset.tab === id));
      container.querySelectorAll('.tab-pane').forEach((p) => p.classList.toggle('active', p.dataset.pane === id));
    }
    buttons.forEach((b) => b.addEventListener('click', () => activate(b.dataset.tab)));
    activate(initial || (buttons[0] && buttons[0].dataset.tab));
    return activate;
  };

  // ---------------------------------------------------------------- status bar
  ui.status = {
    left(html) { document.getElementById('status-left').innerHTML = html; },
    mid(html, busy) { const m = document.getElementById('status-mid'); m.innerHTML = html; m.classList.toggle('busy', !!busy); },
    right(html) { document.getElementById('status-right').innerHTML = html; },
  };

  // ---------------------------------------------------------------- menus
  const menu = PB.menu = { defs: [], openId: null, pop: null };
  menu.define = function (defs) { menu.defs = defs; menu.render(); };
  menu.render = function () {
    const nav = document.getElementById('menus');
    nav.innerHTML = '';
    menu.defs.forEach((def) => {
      if (def.visible && !def.visible()) return;
      const btn = el('<button class="menu-btn" data-menu="' + esc(def.id) + '">' + esc(def.label) + '</button>');
      btn.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopPropagation(); if (menu.openId === def.id) menu.close(); else menu.open(def.id, btn); });
      btn.addEventListener('mouseenter', () => { if (menu.openId && menu.openId !== def.id) menu.open(def.id, btn); });
      nav.appendChild(btn);
    });
    const mobile = document.getElementById('menu-mobile');
    mobile.innerHTML = PB.icon('menu', 18);
    mobile.onmousedown = (e) => { e.preventDefault(); e.stopPropagation(); if (menu.openId === '__mobile') menu.close(); else menu.openMobile(mobile); };
  };
  function itemsOf(def) { return typeof def.items === 'function' ? def.items() : (def.items || []); }
  function buildItems(container, items, closeAfter) {
    items.forEach((item) => {
      if (!item) return;
      if (item.visible && !item.visible()) return;
      if (item.sep) { container.appendChild(el('<div class="menu-sep"></div>')); return; }
      if (item.head) { container.appendChild(el('<div class="menu-head">' + esc(item.head) + '</div>')); return; }
      const enabled = item.enabled ? !!item.enabled() : true;
      const checked = typeof item.checked === 'function' ? item.checked() : item.checked;
      let mark = '';
      if (item.radio) mark = checked ? PB.icon('check', 14) : '';
      else if (item.checked !== undefined) mark = checked ? PB.icon('check', 14) : '';
      else if (item.icon) mark = '<span class="muted">' + PB.icon(item.icon, 14) + '</span>';
      const row = el('<div class="menu-item ' + (enabled ? '' : 'disabled') + '" role="menuitem"><span class="mark">' + mark + '</span><span class="label">' + esc(item.label) + '</span>' +
        (item.shortcut ? '<span class="shortcut">' + esc(item.shortcut) + '</span>' : '') + (item.submenu ? '<span class="sub">' + PB.icon('chevron-right', 14) + '</span>' : '') + '</div>');
      if (item.submenu) {
        let sub = null;
        row.addEventListener('mouseenter', () => {
          if (sub) return;
          sub = el('<div class="menu-pop sub-pop"></div>');
          buildItems(sub, typeof item.submenu === 'function' ? item.submenu() : item.submenu, closeAfter);
          document.body.appendChild(sub);
          const r = row.getBoundingClientRect();
          sub.style.left = Math.min(r.right, window.innerWidth - sub.offsetWidth - 8) + 'px';
          sub.style.top = Math.min(r.top - 5, window.innerHeight - sub.offsetHeight - 8) + 'px';
          menu.subs.push(sub);
        });
      } else if (enabled && item.action) {
        row.addEventListener('mousedown', (e) => e.stopPropagation());
        row.addEventListener('click', (e) => { e.stopPropagation(); closeAfter(); try { item.action(); } catch (err) { ui.toast(err.message || String(err), 'bad'); } });
      }
      container.appendChild(row);
    });
  }
  menu.subs = [];
  menu.open = function (id, btn) {
    menu.close();
    const def = menu.defs.find((d) => d.id === id);
    if (!def) return;
    const pop = el('<div class="menu-pop" role="menu"></div>');
    buildItems(pop, itemsOf(def), menu.close);
    document.body.appendChild(pop);
    const r = btn.getBoundingClientRect();
    pop.style.left = Math.min(r.left, window.innerWidth - pop.offsetWidth - 6) + 'px';
    menu.pop = pop; menu.openId = id;
    btn.classList.add('open');
  };
  menu.openMobile = function (btn) {
    menu.close();
    const pop = el('<div class="menu-pop" role="menu" style="max-height:80vh;overflow:auto;width:min(92vw,360px)"></div>');
    menu.defs.forEach((def) => {
      if (def.visible && !def.visible()) return;
      pop.appendChild(el('<div class="menu-head">' + esc(def.label) + '</div>'));
      buildItems(pop, itemsOf(def), menu.close);
    });
    document.body.appendChild(pop);
    pop.style.left = '6px';
    menu.pop = pop; menu.openId = '__mobile';
  };
  menu.close = function () {
    if (menu.pop) menu.pop.remove();
    menu.subs.forEach((s) => s.remove()); menu.subs = [];
    menu.pop = null; menu.openId = null;
    document.querySelectorAll('.menu-btn.open').forEach((b) => b.classList.remove('open'));
  };
  document.addEventListener('mousedown', (e) => { if (menu.openId && !(e.target.closest && e.target.closest('.menu-pop'))) menu.close(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { if (menu.openId) { menu.close(); return; } ui.closeTopDialog(); } });

  // Context menus (a popup at the pointer) for cells and files.
  ui.popup = function (items, x, y) {
    menu.close();
    const pop = el('<div class="menu-pop" role="menu"></div>');
    buildItems(pop, items, menu.close);
    document.body.appendChild(pop);
    pop.style.left = Math.min(x, window.innerWidth - pop.offsetWidth - 6) + 'px';
    pop.style.top = Math.min(y, window.innerHeight - pop.offsetHeight - 6) + 'px';
    menu.pop = pop; menu.openId = '__popup';
  };
})();
