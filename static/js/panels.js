// Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
// Panels: the two docks, their tabs, visibility per look (persisted), and the Files panel.
(function () {
  'use strict';
  const PB = window.PB;
  const { esc, el, fmtBytes, plural } = PB.util;
  const panels = PB.panels = { defs: {}, instances: {} };

  // def: {id, title, description, icon, dock, looks, defaultVisible: {simple, professional}, order, render(body, panel), refresh(panel), onShow(panel)}
  panels.register = function (def) {
    def.dock = def.dock === 'left' ? 'left' : 'right';
    def.order = def.order == null ? 100 : def.order;
    def.looks = def.looks && def.looks.length ? def.looks : ['simple', 'professional'];
    def.defaultVisible = def.defaultVisible || { simple: false, professional: true };
    panels.defs[def.id] = def;
  };
  panels.available = function () {
    return Object.values(panels.defs).filter((d) => PB.lookAllows(d.looks)).sort((a, b) => a.order - b.order || a.title.localeCompare(b.title));
  };
  panels.isVisible = function (id) {
    const def = panels.defs[id];
    if (!def || !PB.lookAllows(def.looks)) return false;
    const layout = (PB.config.layout || {})[PB.look()] || {};
    const stored = layout.panels || {};
    if (Object.prototype.hasOwnProperty.call(stored, id)) return !!stored[id];
    return !!def.defaultVisible[PB.look()];
  };
  panels.setVisible = function (id, visible) {
    const patch = { layout: {} };
    patch.layout[PB.look()] = { panels: {} };
    patch.layout[PB.look()].panels[id] = !!visible;
    PB.saveConfig(patch);
    if (visible) PB.state.activeTab[panels.defs[id].dock] = id;
    panels.renderDocks();
  };
  panels.toggle = (id) => panels.setVisible(id, !panels.isVisible(id));
  panels.show = function (id) {
    const def = panels.defs[id];
    if (!def) return;
    if (!panels.isVisible(id)) panels.setVisible(id, true);
    panels.activate(id);
    panels.openDock(def.dock);
  };
  panels.activate = function (id) {
    const def = panels.defs[id];
    if (!def) return;
    PB.state.activeTab[def.dock] = id;
    panels.renderDocks();
  };
  panels.busy = function (id, busy) {
    const tab = document.querySelector('.dock-tab[data-panel="' + id + '"]');
    if (tab) tab.classList.toggle('busy', !!busy);
  };
  panels.refresh = function (id) {
    const inst = panels.instances[id];
    const def = panels.defs[id];
    if (inst && def && def.refresh && panels.isVisible(id)) { try { def.refresh(inst); } catch (e) { console.error('refresh', id, e); } }
  };
  panels.refreshAll = function () { Object.keys(panels.instances).forEach(panels.refresh); };
  panels.openDock = function (dock) { document.getElementById('dock-' + dock).classList.add('open'); };
  panels.closeDock = function (dock) { document.getElementById('dock-' + dock).classList.remove('open'); };
  panels.toggleDock = function (dock) { document.getElementById('dock-' + dock).classList.toggle('open'); };

  function instance(def) {
    let inst = panels.instances[def.id];
    if (inst) return inst;
    const root = el('<div class="panel" data-panel="' + esc(def.id) + '"><div class="panel-head"><span class="muted">' + PB.icon(def.icon || 'box') + '</span><h3>' + esc(def.title) +
      '<span class="desc">' + esc(def.description || '') + '</span></h3><button class="icon-btn" data-refresh title="Refresh">' + PB.icon('refresh', 14) + '</button><button class="icon-btn" data-hide title="Hide this panel (View menu shows it again)">' + PB.icon('x', 14) + '</button></div><div class="panel-body"></div></div>');
    inst = { id: def.id, def, root, body: root.querySelector('.panel-body'), head: root.querySelector('.panel-head') };
    root.querySelector('[data-hide]').addEventListener('click', () => panels.setVisible(def.id, false));
    const refreshBtn = root.querySelector('[data-refresh]');
    if (def.refresh) refreshBtn.addEventListener('click', () => panels.refresh(def.id)); else refreshBtn.remove();
    panels.instances[def.id] = inst;
    try { def.render(inst.body, inst); } catch (e) { inst.body.innerHTML = '<div class="callout bad">This panel failed to render: ' + esc(e.message) + '</div>'; console.error(e); }
    return inst;
  }

  panels.renderDocks = function () {
    const main = document.getElementById('main');
    ['left', 'right'].forEach((dock) => {
      const visible = panels.available().filter((d) => d.dock === dock && panels.isVisible(d.id));
      const tabs = document.getElementById('dock-' + dock + '-tabs');
      const body = document.getElementById('dock-' + dock + '-body');
      const dockEl = document.getElementById('dock-' + dock);
      main.classList.toggle('no-' + dock, visible.length === 0);
      dockEl.hidden = visible.length === 0;
      tabs.innerHTML = '';
      // Every panel that is not the active one of its dock is taken off screen, whether hidden or merely inactive.
      Object.values(panels.instances).forEach((inst) => { if (inst.def.dock === dock) { inst.root.classList.remove('active'); inst.root.hidden = true; } });
      if (!visible.length) { dockEl.classList.remove('open'); return; }
      let active = PB.state.activeTab[dock];
      if (!visible.some((d) => d.id === active)) active = visible[0].id;
      PB.state.activeTab[dock] = active;
      visible.forEach((def) => {
        const tab = el('<div class="dock-tab ' + (def.id === active ? 'active' : '') + '" data-panel="' + esc(def.id) + '" title="' + esc(def.description || def.title) + '">' + PB.icon(def.icon || 'box', 14) + '<span>' + esc(def.title) + '</span><span class="dot"></span><span class="close" title="Hide">' + PB.icon('x', 12) + '</span></div>');
        tab.addEventListener('click', (e) => { if (e.target.closest('.close')) { panels.setVisible(def.id, false); return; } panels.activate(def.id); });
        tabs.appendChild(tab);
        const inst = instance(def);
        if (inst.root.parentElement !== body) body.appendChild(inst.root);
        const isActive = def.id === active;
        inst.root.hidden = !isActive;
        inst.root.classList.toggle('active', isActive);
        if (isActive && def.onShow) { try { def.onShow(inst); } catch (e) { console.error(e); } }
      });
    });
    PB.bus.emit('docks');
  };

  // ======================================================================
  // Files panel
  // ======================================================================
  const files = PB.files = { tree: [], expanded: {}, selected: new Set(), anchor: '', order: [] };
  const ROOT_LABEL = '(project folder)';

  files.load = async function () {
    if (!PB.state.project) { files.tree = []; files.selected.clear(); files.render(); return; }
    try {
      const r = await PB.api('/api/projects/' + encodeURIComponent(PB.state.project.id) + '/files');
      files.tree = r.files || [];
      files.root = r.root || '';
    } catch (e) { files.tree = []; }
    const known = new Set(files.tree.map((f) => f.path));
    files.selected.forEach((p) => { if (!known.has(p)) files.selected.delete(p); });
    files.render();
  };
  files.item = (path) => files.tree.find((f) => f.path === path);
  files.rawUrl = (path, download) => '/projects/' + encodeURIComponent(PB.state.project.id) + '/raw/' + path.split('/').map(encodeURIComponent).join('/') + (download ? '?download=1' : '');
  files.absolute = (path) => (files.root || '') + (files.root && files.root.includes('\\') ? '\\' : '/') + (files.root && files.root.includes('\\') ? path.replace(/\//g, '\\') : path);
  files.dirs = () => files.tree.filter((f) => f.dir).map((f) => f.path).sort();

  // ---------------------------------------------------------------- render
  files.render = function () {
    const inst = panels.instances.files;
    if (!inst) return;
    const treeEl = inst.body.querySelector('.tree');
    const empty = inst.body.querySelector('.files-empty');
    files.renderSelectionBar();
    if (!PB.state.project) { treeEl.innerHTML = ''; empty.classList.remove('hidden'); empty.innerHTML = PB.icon('folder', 28) + 'Open a project to see its files.'; return; }
    if (!files.tree.length) { treeEl.innerHTML = ''; empty.classList.remove('hidden'); empty.innerHTML = PB.icon('folder', 28) + 'This project has no files yet. Add data files here, or let a patch produce some.'; return; }
    empty.classList.add('hidden');
    const byDir = {};
    files.tree.forEach((f) => { const parent = f.path.includes('/') ? f.path.slice(0, f.path.lastIndexOf('/')) : ''; (byDir[parent] = byDir[parent] || []).push(f); });
    files.order = [];
    function build(parent, depth) {
      const ul = document.createElement('ul');
      (byDir[parent] || []).sort((a, b) => (b.dir - a.dir) || a.name.localeCompare(b.name)).forEach((f) => {
        const li = document.createElement('li');
        const open = files.expanded[f.path] !== undefined ? files.expanded[f.path] : depth === 0;
        const icon = f.dir ? (open ? 'folder-open' : 'folder') : (PB.util.isImage(f.path) ? 'image' : (PB.util.isTable(f.path) ? 'grid' : 'file-text'));
        const node = el('<div class="node ' + (f.dir ? 'dir' : '') + (files.selected.has(f.path) ? ' selected' : '') + '" data-path="' + esc(f.path) + '" title="' + esc(f.path) + '">' +
          (f.dir ? '<span class="chev">' + PB.icon(open ? 'chevron-down' : 'chevron-right', 12) + '</span>' : '<span class="chev"></span>') +
          '<span class="ic">' + PB.icon(icon, 14) + '</span><span class="name truncate">' + esc(f.name) + '</span>' + (f.dir ? '' : '<span class="size">' + fmtBytes(f.size) + '</span>') +
          '<span class="more" title="More">' + PB.icon('more', 14) + '</span></div>');
        node.addEventListener('click', (e) => {
          if (e.target.closest('.more')) { e.stopPropagation(); if (!files.selected.has(f.path)) files.select(f.path, 'single'); const r = e.target.closest('.more').getBoundingClientRect(); files.menu(r.left, r.bottom + 2); return; }
          if (e.target.closest('.chev') && f.dir) { files.expanded[f.path] = !open; files.render(); return; }
          files.select(f.path, (e.ctrlKey || e.metaKey) ? 'toggle' : (e.shiftKey ? 'range' : 'single'));
          if (f.dir && !e.ctrlKey && !e.metaKey && !e.shiftKey) { files.expanded[f.path] = !open; files.render(); }
        });
        node.addEventListener('dblclick', (e) => { e.preventDefault(); if (!f.dir) files.preview(f.path); });
        node.addEventListener('contextmenu', (e) => { e.preventDefault(); if (!files.selected.has(f.path)) files.select(f.path, 'single'); files.menu(e.clientX, e.clientY); });
        li.appendChild(node);
        files.order.push(f.path);
        if (f.dir && open) li.appendChild(build(f.path, depth + 1));
        ul.appendChild(li);
      });
      return ul;
    }
    treeEl.innerHTML = '';
    treeEl.appendChild(build('', 0));
  };
  // Selection changes touch classes only; the tree is rebuilt just for loads and expand/collapse,
  // so a double-click lands on the same element as the click before it.
  files.applySelection = function () {
    const inst = panels.instances.files;
    if (!inst) return;
    inst.body.querySelectorAll('.tree .node').forEach((n) => n.classList.toggle('selected', files.selected.has(n.dataset.path)));
    files.renderSelectionBar();
  };
  files.select = function (path, mode) {
    if (mode === 'toggle') { if (files.selected.has(path)) files.selected.delete(path); else files.selected.add(path); files.anchor = path; }
    else if (mode === 'range' && files.anchor && files.order.includes(files.anchor)) {
      const a = files.order.indexOf(files.anchor), b = files.order.indexOf(path);
      files.order.slice(Math.min(a, b), Math.max(a, b) + 1).forEach((p) => files.selected.add(p));
    } else { files.selected.clear(); files.selected.add(path); files.anchor = path; }
    files.applySelection();
  };
  files.clearSelection = function () { files.selected.clear(); files.applySelection(); };
  files.selectAll = function () { files.order.forEach((p) => files.selected.add(p)); files.applySelection(); };
  files.renderSelectionBar = function () {
    const inst = panels.instances.files;
    if (!inst) return;
    const bar = inst.body.querySelector('.sel-bar');
    const n = files.selected.size;
    bar.classList.toggle('hidden', n === 0);
    if (!n) return;
    bar.innerHTML = '<span class="count">' + plural(n, 'item') + '</span>' +
      '<button class="small ghost" data-act="copy" title="Copy the selection to another folder of the project">' + PB.icon('copy', 13) + ' Copy</button>' +
      '<button class="small ghost" data-act="move" title="Move the selection to another folder of the project">' + PB.icon('arrow-right', 13) + ' Move</button>' +
      '<button class="small ghost" data-act="download" title="Download as a zip">' + PB.icon('download', 13) + '</button>' +
      '<button class="small ghost" data-act="delete" title="Delete">' + PB.icon('trash', 13) + '</button>' +
      '<button class="small ghost" data-act="clear" title="Clear the selection">' + PB.icon('x', 13) + '</button>';
    bar.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', () => files.action(b.dataset.act)));
  };

  // ---------------------------------------------------------------- menu and actions
  files.menu = function (x, y) {
    const sel = Array.from(files.selected);
    const single = sel.length === 1 ? files.item(sel[0]) : null;
    const items = [];
    if (single && !single.dir) {
      items.push({ label: 'Open', icon: 'eye', action: () => files.preview(single.path) });
      items.push({ label: 'Edit as text', icon: 'edit', action: () => files.edit(single.path) });
    }
    if (single) {
      items.push({ label: single.dir ? 'Open in the file manager' : 'Open with the default program', icon: 'external-link', action: () => files.openWith(single.path, false) });
      items.push({ label: 'Show in folder', icon: 'folder-open', action: () => files.openWith(single.path, true) });
      items.push({ sep: true });
      items.push({ label: 'Copy path', icon: 'copy', action: () => files.copyText(files.absolute(single.path), 'Path copied') });
      items.push({ label: 'Copy relative path', icon: 'copy', action: () => files.copyText(single.path, 'Relative path copied') });
      items.push({ sep: true });
      items.push({ label: 'Rename…', icon: 'edit', action: () => files.rename(single.path) });
    }
    items.push({ label: 'Duplicate', icon: 'copy', action: () => files.action('duplicate') });
    items.push({ label: 'Copy to…', icon: 'copy', action: () => files.action('copy') });
    items.push({ label: 'Move to…', icon: 'arrow-right', action: () => files.action('move') });
    items.push({ label: sel.length === 1 && single && !single.dir ? 'Download' : 'Download as zip', icon: 'download', action: () => files.action('download') });
    if (single && single.dir) {
      items.push({ sep: true });
      items.push({ label: 'Add files here…', icon: 'upload', action: () => files.upload(single.path) });
      items.push({ label: 'New folder here…', icon: 'folder-plus', action: () => files.newFolder(single.path) });
      items.push({ label: 'New text file here…', icon: 'file-text', action: () => files.newFile(single.path) });
    }
    items.push({ sep: true });
    items.push({ label: sel.length > 1 ? 'Delete ' + plural(sel.length, 'item') + '…' : 'Delete…', icon: 'trash', action: () => files.action('delete') });
    PB.ui.popup(items, x, y);
  };
  files.action = async function (act) {
    const sel = Array.from(files.selected);
    if (!sel.length) return;
    if (act === 'clear') { files.clearSelection(); return; }
    if (act === 'download') {
      const single = sel.length === 1 ? files.item(sel[0]) : null;
      if (single && !single.dir) window.open(files.rawUrl(single.path, true), '_blank');
      else window.open('/api/projects/' + encodeURIComponent(PB.state.project.id) + '/zip?' + sel.map((p) => 'paths=' + encodeURIComponent(p)).join('&'), '_blank');
      return;
    }
    if (act === 'delete') {
      const ok = await PB.ui.confirm({ title: sel.length === 1 ? 'Delete ' + PB.util.basename(sel[0]) + '?' : 'Delete ' + plural(sel.length, 'item') + '?', danger: true, okLabel: 'Delete',
        message: (sel.length === 1 ? 'It is' : 'They are') + ' removed from the project folder. This cannot be undone.' + (sel.some((p) => (files.item(p) || {}).dir) ? ' Folders are deleted with everything in them.' : '') });
      if (!ok) return;
      await files.op('delete', sel);
      files.selected.clear();
      return;
    }
    if (act === 'duplicate') { await files.op('duplicate', sel); return; }
    if (act === 'copy' || act === 'move') {
      const target = await files.pickFolder(act === 'copy' ? 'Copy ' + plural(sel.length, 'item') + ' to' : 'Move ' + plural(sel.length, 'item') + ' to');
      if (target === null) return;
      await files.op(act, sel, { target });
      if (act === 'move') files.selected.clear();
    }
  };
  files.op = async function (op, paths, extra) {
    try {
      const r = await PB.api('/api/projects/' + encodeURIComponent(PB.state.project.id) + '/files/op', { method: 'POST', body: Object.assign({ op, paths }, extra || {}) });
      if (r.failed && r.failed.length) PB.ui.toast(r.failed.map((f) => f.path + ': ' + f.error).join('\n'), 'bad');
      else PB.ui.toast({ delete: 'Deleted', duplicate: 'Duplicated', copy: 'Copied', move: 'Moved', rename: 'Renamed', create: 'Created' }[op] + ' ' + plural((r.done || [r]).length, 'item'), 'ok', { timeout: 2500 });
      await files.load();
      return r;
    } catch (e) { PB.ui.toast(e.message, 'bad'); return null; }
  };
  files.pickFolder = function (title) {
    return new Promise((resolve) => {
      const dirs = files.dirs();
      const body = el('<div><div class="option-list" style="max-height:40vh;overflow:auto">' + ['', ...dirs].map((d, i) => '<label class="option ' + (i === 0 ? 'selected' : '') + '"><input type="radio" name="pf" value="' + esc(d) + '" ' + (i === 0 ? 'checked' : '') + '><div class="title">' + PB.icon('folder', 14) + ' ' + esc(d || ROOT_LABEL) + '</div></label>').join('') + '</div>' +
        '<label>Or into a new folder there (optional)<input type="text" data-new placeholder="new folder name"></label></div>');
      body.querySelectorAll('input[name="pf"]').forEach((r) => r.addEventListener('change', () => body.querySelectorAll('.option').forEach((o) => o.classList.toggle('selected', o.querySelector('input').checked))));
      let done = false;
      PB.ui.dialog({ title, icon: 'folder', body, buttons: [{ label: 'Cancel' }, { label: 'OK', primary: true, action: () => { done = true; const base = body.querySelector('input[name="pf"]:checked').value; const extra = body.querySelector('[data-new]').value.trim(); resolve(base && extra ? base + '/' + extra : (extra || base)); } }], onClose: () => { if (!done) resolve(null); } });
    });
  };
  files.rename = async function (path) {
    const name = await PB.ui.prompt({ title: 'Rename', label: 'New name', value: PB.util.basename(path) });
    if (!name || name.trim() === PB.util.basename(path)) return;
    const r = await files.op('rename', [path], { name: name.trim() });
    if (r && r.path) { files.selected.clear(); files.selected.add(r.path); files.render(); }
  };
  files.newFolder = async function (where) {
    const name = await PB.ui.prompt({ title: 'New folder', label: 'Folder name', placeholder: 'results', message: 'Inside ' + (where || ROOT_LABEL) });
    if (!name) return;
    try { await PB.api('/api/projects/' + encodeURIComponent(PB.state.project.id) + '/mkdir', { method: 'POST', body: { path: (where ? where + '/' : '') + name.trim() } }); if (where) files.expanded[where] = true; files.load(); }
    catch (e) { PB.ui.toast(e.message, 'bad'); }
  };
  files.newFile = async function (where) {
    const name = await PB.ui.prompt({ title: 'New text file', label: 'File name', placeholder: 'notes.md', message: 'Inside ' + (where || ROOT_LABEL) });
    if (!name) return;
    const r = await files.op('create', [], { target: where || '', name: name.trim() });
    if (r && r.path) { if (where) files.expanded[where] = true; files.selected.clear(); files.selected.add(r.path); files.render(); files.edit(r.path); }
  };
  files.openWith = async function (path, reveal) {
    try { await PB.api('/api/projects/' + encodeURIComponent(PB.state.project.id) + '/open-with', { method: 'POST', body: { path, reveal: !!reveal } }); }
    catch (e) { PB.ui.toast(e.message, 'bad'); }
  };
  files.copyText = async function (text, note) {
    try { await navigator.clipboard.writeText(text); }
    catch (e) {
      const ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); } catch (err) { PB.ui.toast('Could not copy: ' + text, 'warn'); ta.remove(); return; }
      ta.remove();
    }
    PB.ui.toast(note || 'Copied', 'ok', { timeout: 1800 });
  };
  files.remove = async function (path) { files.selected.clear(); files.selected.add(path); await files.action('delete'); };

  // ---------------------------------------------------------------- upload
  files.upload = function (dir) {
    const input = document.createElement('input');
    input.type = 'file'; input.multiple = true;
    input.addEventListener('change', () => files.uploadList(input.files, dir));
    input.click();
  };
  files.uploadList = async function (list, dir) {
    if (!list || !list.length || !PB.state.project) return;
    const form = new FormData();
    form.append('dir', dir || 'data');
    Array.from(list).forEach((f) => form.append('files', f, f.name));
    PB.ui.status.mid(PB.icon('loader', 14) + ' Adding ' + plural(list.length, 'file') + '…', true);
    try {
      const r = await PB.api('/api/projects/' + encodeURIComponent(PB.state.project.id) + '/upload', { method: 'POST', body: form });
      PB.ui.toast('Added ' + (r.saved || []).map((s) => s.path).join(', '), 'ok');
      if (dir) files.expanded[dir] = true;
      files.load();
    } catch (e) { PB.ui.toast('Upload failed: ' + e.message, 'bad'); }
    finally { PB.ui.status.mid(''); }
  };

  // ---------------------------------------------------------------- preview and editor
  files.preview = async function (path) {
    const pid = PB.state.project.id;
    const name = PB.util.basename(path);
    const body = el('<div><div class="preview-actions"></div><div class="preview-content"><div class="muted">Loading…</div></div></div>');
    const actions = body.querySelector('.preview-actions');
    const content = body.querySelector('.preview-content');
    const dlg = PB.ui.dialog({ title: name, wide: true, body, icon: 'file-text', buttons: [
      { label: 'Download', icon: 'download', action: () => { window.open(files.rawUrl(path, true), '_blank'); return false; } },
      { label: 'Delete…', icon: 'trash', danger: true, action: (d) => { d.close(); files.remove(path); } }, { label: 'Close' }] });
    const addAction = (label, icon, fn) => { const b = el('<button class="small">' + PB.icon(icon, 13) + ' ' + esc(label) + '</button>'); b.addEventListener('click', fn); actions.appendChild(b); };
    addAction('Open with the default program', 'external-link', () => files.openWith(path, false));
    addAction('Show in folder', 'folder-open', () => files.openWith(path, true));
    addAction('Copy path', 'copy', () => files.copyText(files.absolute(path), 'Path copied'));
    if (PB.util.isImage(path)) { content.innerHTML = '<img class="preview-img" src="' + esc(files.rawUrl(path)) + '?t=' + Date.now() + '" alt="' + esc(name) + '">'; content.querySelector('img').addEventListener('click', () => PB.ui.lightbox(files.rawUrl(path), name)); return; }
    try {
      const r = await PB.api('/api/projects/' + encodeURIComponent(pid) + '/file?path=' + encodeURIComponent(path));
      if (r.binary) { content.innerHTML = '<div class="empty">' + PB.icon('file', 28) + 'This file cannot be shown here (' + fmtBytes(r.size) + '). Open it with the default program, or download it.</div>'; return; }
      addAction('Edit', 'edit', () => { dlg.close(); files.edit(path); });
      const x = PB.util.ext(path);
      const note = r.truncated ? '<div class="callout warn">Only the first part of the file is shown (' + fmtBytes(r.size) + ' in total).</div>' : '';
      if (x === 'md') { content.innerHTML = note + '<div class="markdown">' + PB.ui.markdown(r.text) + '</div>'; return; }
      if (PB.util.isTable(path)) { content.innerHTML = note + files.tableHtml(r.text, x === 'tsv' ? '\t' : ','); return; }
      const mode = PB.ui.cmMode(x);
      content.innerHTML = note + '<div class="preview-code"></div>';
      if (mode) PB.ui.codeView(content.querySelector('.preview-code'), r.text, x); else content.querySelector('.preview-code').innerHTML = '<div class="preview-text"><pre>' + esc(r.text) + '</pre></div>';
    } catch (e) { content.innerHTML = '<div class="callout bad">' + esc(e.message) + '</div>'; }
  };
  files.edit = async function (path) {
    const pid = PB.state.project.id;
    let r;
    try { r = await PB.api('/api/projects/' + encodeURIComponent(pid) + '/file?path=' + encodeURIComponent(path)); }
    catch (e) { PB.ui.toast(e.message, 'bad'); return; }
    if (r.binary) { PB.ui.toast('This file is not text. Open it with the default program instead.', 'warn'); return; }
    if (r.truncated) { PB.ui.toast('This file is too large to edit here (' + fmtBytes(r.size) + '). Open it with the default program.', 'warn'); return; }
    const body = el('<div class="file-editor"><div class="row" style="margin-bottom:6px"><span class="mono small muted truncate grow">' + esc(path) + '</span><span class="small muted" data-state>Saved</span></div><div data-editor></div></div>');
    let dirty = false, cm = null;
    const setState = (t) => { body.querySelector('[data-state]').textContent = t; };
    const save = async () => {
      try { await PB.api('/api/projects/' + encodeURIComponent(pid) + '/file', { method: 'POST', body: { path, text: cm.getValue() } }); dirty = false; setState('Saved ' + PB.util.fmtClock(Date.now())); files.load(); return true; }
      catch (e) { PB.ui.toast('Could not save: ' + e.message, 'bad'); return false; }
    };
    const dlg = PB.ui.dialog({ title: 'Edit ' + PB.util.basename(path), icon: 'edit', wide: true, body, closeOnOverlay: false, buttons: [
      { label: 'Save', icon: 'save', action: async () => { await save(); return false; } },
      { label: 'Save and close', primary: true, action: async () => (await save()) },
      { label: 'Close', action: async () => { if (dirty) { const ok = await PB.ui.confirm({ title: 'Discard the changes?', message: 'The file has unsaved changes.', okLabel: 'Discard', danger: true }); if (!ok) return false; } return true; } }] });
    cm = CodeMirror(body.querySelector('[data-editor]'), { value: r.text, mode: PB.ui.cmMode(PB.util.ext(path)) || 'text/plain', lineNumbers: true, lineWrapping: true, theme: PB.ui.cmTheme(), matchBrackets: true, indentUnit: 4,
      extraKeys: { 'Ctrl-S': () => save(), 'Cmd-S': () => save() } });
    cm.on('change', () => { dirty = true; setState('Unsaved changes'); });
    setTimeout(() => { cm.refresh(); cm.focus(); }, 30);
    void dlg;
  };
  files.parseCsv = function (text, sep, maxRows) {
    const rows = []; let row = [], field = '', q = false;
    for (let i = 0; i < text.length && rows.length <= maxRows; i++) {
      const c = text[i];
      if (q) { if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else q = false; } else field += c; }
      else if (c === '"') q = true;
      else if (c === sep) { row.push(field); field = ''; }
      else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(field); rows.push(row); row = []; field = ''; }
      else field += c;
    }
    if (field || row.length) { row.push(field); rows.push(row); }
    return rows;
  };
  files.tableHtml = function (text, sep) {
    const rows = files.parseCsv(text, sep, 300);
    if (!rows.length) return '<div class="muted">(empty)</div>';
    const head = rows[0], bodyRows = rows.slice(1, 301);
    const total = text.split('\n').length - 1;
    return '<div class="muted small" style="margin-bottom:6px">' + (total > 300 ? 'First 300 of about ' + total + ' rows' : plural(bodyRows.length, 'row')) + ', ' + plural(head.length, 'column') + '</div>' +
      '<div class="preview-table"><table class="table"><thead><tr>' + head.map((h) => '<th>' + esc(h) + '</th>').join('') + '</tr></thead><tbody>' +
      bodyRows.map((r) => '<tr>' + r.map((c) => '<td>' + esc(c) + '</td>').join('') + '</tr>').join('') + '</tbody></table></div>';
  };

  // ---------------------------------------------------------------- the panel
  panels.register({
    id: 'files', title: 'Files', icon: 'folder', dock: 'left', order: 10,
    description: 'The files in the project folder. Double-click opens one; right-click shows what you can do; drop files here to add them.',
    defaultVisible: { simple: true, professional: true },
    render(body, inst) {
      body.classList.add('flush');
      body.innerHTML = '<div class="panel-toolbar"><button class="small" data-add title="Add files to the data folder">' + PB.icon('upload', 14) + ' Add files</button>' +
        '<button class="small" data-new title="New folder or text file">' + PB.icon('plus', 14) + ' New</button>' +
        '<button class="small" data-folder title="Show the project folder on this computer">' + PB.icon('external-link', 14) + ' <span class="label-text">Show folder</span></button></div>' +
        '<div class="dropzone">Drop files here to add them to the project</div>' +
        '<div class="tree-scroll scroll" tabindex="0"><div class="files-empty empty hidden"></div><ul class="tree"></ul></div>' +
        // The selection actions sit below the tree so that appearing never moves the rows (a double-click must land twice on the same row).
        '<div class="sel-bar hidden"></div>';
      body.querySelector('[data-add]').addEventListener('click', () => files.upload('data'));
      body.querySelector('[data-new]').addEventListener('click', (e) => {
        const r = e.currentTarget.getBoundingClientRect();
        const sel = Array.from(files.selected);
        const where = sel.length === 1 && files.item(sel[0]) ? (files.item(sel[0]).dir ? sel[0] : (sel[0].includes('/') ? sel[0].slice(0, sel[0].lastIndexOf('/')) : '')) : '';
        PB.ui.popup([{ head: 'Create in ' + (where || ROOT_LABEL) }, { label: 'Folder…', icon: 'folder-plus', action: () => files.newFolder(where) }, { label: 'Text file…', icon: 'file-text', action: () => files.newFile(where) }], r.left, r.bottom + 4);
      });
      body.querySelector('[data-folder]').addEventListener('click', async () => { if (!PB.state.project) return; try { await PB.api('/api/open-folder', { method: 'POST', body: { path: PB.state.project.path } }); } catch (e) { PB.ui.toast(e.message, 'bad'); } });
      const zone = body.querySelector('.dropzone');
      ['dragenter', 'dragover'].forEach((ev) => body.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.add('over'); }));
      ['dragleave', 'drop'].forEach((ev) => body.addEventListener(ev, (e) => { e.preventDefault(); zone.classList.remove('over'); }));
      body.addEventListener('drop', (e) => { if (e.dataTransfer && e.dataTransfer.files.length) files.uploadList(e.dataTransfer.files, 'data'); });
      const scroll = body.querySelector('.tree-scroll');
      scroll.addEventListener('click', (e) => { if (e.target === scroll || e.target.classList.contains('tree')) files.clearSelection(); });
      scroll.addEventListener('contextmenu', (e) => { if (e.target === scroll || e.target.classList.contains('tree')) { e.preventDefault(); PB.ui.popup([{ label: 'Add files…', icon: 'upload', action: () => files.upload('data') }, { label: 'New folder…', icon: 'folder-plus', action: () => files.newFolder('') }, { label: 'New text file…', icon: 'file-text', action: () => files.newFile('') }, { label: 'Select all', icon: 'check', action: () => files.selectAll() }], e.clientX, e.clientY); } });
      scroll.addEventListener('keydown', (e) => {
        const sel = Array.from(files.selected);
        if (e.key === 'Delete' || (e.key === 'Backspace' && sel.length)) { e.preventDefault(); files.action('delete'); }
        else if (e.key === 'Enter' && sel.length === 1) { e.preventDefault(); const it = files.item(sel[0]); if (it && !it.dir) files.preview(it.path); else if (it) { files.expanded[it.path] = !(files.expanded[it.path] !== undefined ? files.expanded[it.path] : !it.path.includes('/')); files.render(); } }
        else if (e.key === 'F2' && sel.length === 1) { e.preventDefault(); files.rename(sel[0]); }
        else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') { e.preventDefault(); files.selectAll(); }
        else if (e.key === 'Escape') { if (!PB.menu.openId && !document.querySelector('.overlay')) files.clearSelection(); }
        else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          const current = files.anchor && files.order.includes(files.anchor) ? files.order.indexOf(files.anchor) : -1;
          const next = files.order[Math.max(0, Math.min(files.order.length - 1, current + (e.key === 'ArrowDown' ? 1 : -1)))];
          if (next) files.select(next, e.shiftKey ? 'range' : 'single');
        }
      });
      files.render();
      void inst;
    },
    refresh() { files.load(); },
    onShow() { if (PB.state.project && !files.tree.length) files.load(); },
  });
  PB.bus.on('project', () => { files.selected.clear(); files.expanded = {}; files.load(); });
  PB.bus.on('run-end', () => files.load());
})();
