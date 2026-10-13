// Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
// The Patchbook editor: tabs, toolbar, cells (patch / note / code), results, autosave, outline panel.
(function () {
  'use strict';
  const PB = window.PB;
  const { esc, el, debounce, fmtBytes, plural } = PB.util;
  const nb = PB.notebook = { cellEls: {}, editors: {}, outputEditors: {}, focusedId: '', saveState: 'saved', savedAt: null, editingNote: {} };

  const ENGINE_INFO = {
    quick: { label: 'Quick', icon: 'zap', hint: 'One script: written, run, repaired until it works. Best for one clear task.' },
    thorough: { label: 'Thorough', icon: 'layers', hint: 'Understands the goal, plans steps, runs and verifies each one, writes a report. For bigger tasks.' },
    ask: { label: 'Ask', icon: 'message', hint: 'A conversational answer. It may read files or run something to answer.' },
  };
  const STATUS_LABEL = { idle: '', done: 'Done', failed: 'Failed', partial: 'Partly done', stopped: 'Stopped', stale: 'Edited since last run', running: 'Running', queued: 'Waiting to run' };
  nb.ENGINE_INFO = ENGINE_INFO;

  // ---------------------------------------------------------------- open / render
  nb.open = async function (nid) {
    nb.saveNow();
    const pid = PB.state.project.id;
    const book = await PB.api('/api/projects/' + encodeURIComponent(pid) + '/patchbooks/' + encodeURIComponent(nid));
    PB.state.patchbook = book;
    nb.cellEls = {}; nb.editors = {}; nb.outputEditors = {}; nb.editingNote = {};
    nb.render();
    PB.bus.emit('patchbook', book);
    return book;
  };
  nb.create = async function (name) {
    const pid = PB.state.project.id;
    const book = await PB.api('/api/projects/' + encodeURIComponent(pid) + '/patchbooks', { method: 'POST', body: { name: name || '' } });
    PB.state.patchbooks.push({ id: book.id, name: book.name, cells: 0 });
    await nb.open(book.id);
    return book;
  };
  nb.refreshList = async function () {
    const r = await PB.api('/api/projects/' + encodeURIComponent(PB.state.project.id) + '/patchbooks');
    PB.state.patchbooks = r.patchbooks || [];
    nb.renderTabs();
  };

  nb.render = function () {
    const center = document.getElementById('center');
    center.innerHTML = '<div class="center-tabs" id="book-tabs"></div><div class="center-toolbar" id="book-toolbar"></div><div class="center-body" id="book-body"><div class="cells" id="cells"></div></div>';
    nb.renderTabs();
    nb.renderToolbar();
    nb.renderCells();
    PB.ui.status.left(PB.icon('folder', 13) + ' ' + esc(PB.state.project.name) + ' <span class="muted">/</span> ' + esc(PB.state.patchbook.name));
    PB.bus.emit('view', 'notebook');
  };

  nb.renderTabs = function () {
    const tabs = document.getElementById('book-tabs');
    if (!tabs || !PB.state.patchbook) return;
    tabs.innerHTML = '';
    PB.state.patchbooks.forEach((b) => {
      const active = b.id === PB.state.patchbook.id;
      const tab = el('<div class="book-tab ' + (active ? 'active' : '') + '" title="Double-click to rename">' + PB.icon('notebook', 14) + '<span>' + esc(active ? PB.state.patchbook.name : b.name) + '</span></div>');
      tab.addEventListener('click', () => { if (!active) nb.open(b.id).catch((e) => PB.ui.toast(e.message, 'bad')); });
      tab.addEventListener('dblclick', () => nb.renameInline(tab, b));
      tab.addEventListener('contextmenu', (e) => { e.preventDefault(); nb.tabMenu(b, e.clientX, e.clientY); });
      tabs.appendChild(tab);
    });
    const add = el('<button class="icon-btn" title="New Patchbook (Ctrl+Alt+N)">' + PB.icon('plus') + '</button>');
    add.addEventListener('click', () => nb.create().catch((e) => PB.ui.toast(e.message, 'bad')));
    tabs.appendChild(add);
  };
  nb.renameInline = function (tab, b) {
    const span = tab.querySelector('span');
    const input = el('<input type="text" value="' + esc(b.name) + '">');
    span.replaceWith(input);
    input.focus(); input.select();
    const finish = async (commit) => {
      const name = input.value.trim();
      input.replaceWith(span);
      if (commit && name && name !== b.name) await nb.rename(b.id, name);
    };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') finish(true); if (e.key === 'Escape') finish(false); });
    input.addEventListener('blur', () => finish(true));
  };
  nb.rename = async function (nid, name) {
    try {
      await PB.api('/api/projects/' + encodeURIComponent(PB.state.project.id) + '/patchbooks/' + encodeURIComponent(nid), { method: 'PATCH', body: { name } });
      const entry = PB.state.patchbooks.find((x) => x.id === nid);
      if (entry) entry.name = name;
      if (PB.state.patchbook && PB.state.patchbook.id === nid) { PB.state.patchbook.name = name; PB.ui.status.left(PB.icon('folder', 13) + ' ' + esc(PB.state.project.name) + ' <span class="muted">/</span> ' + esc(name)); }
      nb.renderTabs();
    } catch (e) { PB.ui.toast(e.message, 'bad'); }
  };
  nb.tabMenu = function (b, x, y) {
    PB.ui.popup([
      { label: 'Rename…', icon: 'edit', action: async () => { const n = await PB.ui.prompt({ title: 'Rename Patchbook', label: 'Name', value: b.name }); if (n && n.trim()) nb.rename(b.id, n.trim()); } },
      { label: 'Duplicate', icon: 'copy', action: () => nb.duplicate(b.id) },
      { sep: true },
      { label: 'Delete…', icon: 'trash', action: () => nb.remove(b.id) },
    ], x, y);
  };
  nb.duplicate = async function (nid) {
    try { const r = await PB.api('/api/projects/' + encodeURIComponent(PB.state.project.id) + '/patchbooks/' + encodeURIComponent(nid) + '/duplicate', { method: 'POST', body: {} }); await nb.refreshList(); await nb.open(r.id); }
    catch (e) { PB.ui.toast(e.message, 'bad'); }
  };
  nb.remove = async function (nid) {
    const b = PB.state.patchbooks.find((x) => x.id === nid) || { name: nid };
    const ok = await PB.ui.confirm({ title: 'Delete Patchbook "' + b.name + '"?', message: 'Its patches and results are removed. Files it produced stay in the project folder.', okLabel: 'Delete', danger: true });
    if (!ok) return;
    try {
      await PB.api('/api/projects/' + encodeURIComponent(PB.state.project.id) + '/patchbooks/' + encodeURIComponent(nid), { method: 'DELETE' });
      await nb.refreshList();
      if (PB.state.patchbook.id === nid) { if (PB.state.patchbooks.length) await nb.open(PB.state.patchbooks[0].id); else await nb.create(); }
    } catch (e) { PB.ui.toast(e.message, 'bad'); }
  };

  nb.renderToolbar = function () {
    const bar = document.getElementById('book-toolbar');
    const pro = PB.isPro();
    const book = PB.state.patchbook;
    const efforts = PB.boot.efforts || [];
    const currentEffort = book.settings.effort || (PB.config.cellDefaults || {}).effort || 'normal';
    const effortIndex = Math.max(0, efforts.findIndex((e) => e.id === currentEffort));
    const effortNow = efforts[effortIndex] || { label: 'Normal', description: '' };
    bar.innerHTML = '<button class="primary small" data-runall title="Run every patch from top to bottom">' + PB.icon('fast-forward', 14) + ' <span class="label-text">Run all</span></button>' +
      '<button class="small" data-stop title="Stop the running patch" disabled>' + PB.icon('stop', 14) + ' <span class="label-text">Stop</span></button><span class="sep"></span>' +
      '<button class="small" data-add="patch" title="Add a patch at the end">' + PB.icon('plus', 14) + ' Patch</button>' +
      '<button class="small" data-add="note" title="Add a note (Markdown) at the end">' + PB.icon('type', 14) + ' Note</button>' +
      (pro ? '<button class="small" data-add="code" title="Add a code cell you write yourself">' + PB.icon('code', 14) + ' Code</button>' : '') +
      (efforts.length ? '<span class="sep"></span><label class="inline small effort-bar" title="' + esc(effortNow.description) + '"><span class="label-text">Effort</span><input type="range" min="0" max="' + (efforts.length - 1) + '" value="' + effortIndex + '" data-effort aria-label="Effort"><span data-effort-label>' + esc(effortNow.label) + '</span></label>' : '') +
      (pro ? '<span class="sep"></span><label class="inline small" title="How patches in this Patchbook run unless a patch says otherwise">Engine <select data-engine><option value="">default (' + esc(ENGINE_INFO[(PB.config.cellDefaults || {}).engine || 'quick'].label) + ')</option>' +
        Object.keys(ENGINE_INFO).map((k) => '<option value="' + k + '" ' + (book.settings.engine === k ? 'selected' : '') + '>' + esc(ENGINE_INFO[k].label) + '</option>').join('') + '</select></label>' +
        '<label class="inline small" title="Language iTailor writes in (auto picks from the task)">Language <select data-language><option value="auto">auto</option>' + (PB.boot.languages || []).map((l) => '<option value="' + esc(l) + '" ' + (book.settings.language === l ? 'selected' : '') + '>' + esc(l) + '</option>').join('') + '</select></label>' : '') +
      '<span class="save-state" data-save></span>';
    bar.querySelector('[data-runall]').addEventListener('click', () => nb.runAll());
    bar.querySelector('[data-stop]').addEventListener('click', () => PB.runs.stop());
    bar.querySelectorAll('[data-add]').forEach((b) => b.addEventListener('click', () => nb.addCell(b.dataset.add)));
    const eng = bar.querySelector('[data-engine]');
    if (eng) eng.addEventListener('change', () => { book.settings.engine = eng.value; nb.save(); });
    const lang = bar.querySelector('[data-language]');
    if (lang) lang.addEventListener('change', () => { book.settings.language = lang.value; nb.save(); });
    const effortInput = bar.querySelector('[data-effort]');
    if (effortInput) {
      const show = () => { const e = efforts[Number(effortInput.value)] || efforts[0]; bar.querySelector('[data-effort-label]').textContent = e.label; effortInput.parentElement.title = e.description; return e; };
      effortInput.addEventListener('input', show);
      effortInput.addEventListener('change', () => {
        const e = show();
        book.settings.effort = e.id;
        nb.save();
        if (!PB.state.activeRun) { PB.ui.status.mid(e.label + ' effort: ' + e.description); setTimeout(() => { if (!PB.state.activeRun) PB.ui.status.mid(''); }, 7000); }
      });
    }
    nb.markSaved(nb.saveState);
    nb.updateRunButtons();
  };
  nb.updateRunButtons = function () {
    const bar = document.getElementById('book-toolbar');
    if (!bar) return;
    const running = !!PB.state.activeRun;
    bar.querySelector('[data-stop]').disabled = !running;
    bar.querySelector('[data-runall]').disabled = running;
  };

  nb.renderCells = function () {
    const host = document.getElementById('cells');
    if (!host) return;
    host.innerHTML = '';
    const book = PB.state.patchbook;
    book.cells.forEach((cell, i) => { host.appendChild(nb.renderCell(cell, i)); host.appendChild(nb.addRow(cell.id)); });
    const foot = el('<div class="cells-foot"><button data-add="patch">' + PB.icon('plus', 14) + ' Add a patch</button><button data-add="note">' + PB.icon('type', 14) + ' Add a note</button>' + (PB.isPro() ? '<button data-add="code">' + PB.icon('code', 14) + ' Add a code cell</button>' : '') + '</div>');
    foot.querySelectorAll('[data-add]').forEach((b) => b.addEventListener('click', () => nb.addCell(b.dataset.add)));
    host.appendChild(foot);
    nb.refreshEditors();
    PB.bus.emit('cells');
  };
  // CodeMirror measures itself when created; an editor built in a detached element (or resized with the window)
  // needs a refresh once it is on screen.
  nb.refreshEditors = function () {
    setTimeout(() => {
      Object.values(nb.editors).forEach((cm) => { try { cm.refresh(); } catch (e) { /* removed */ } });
      Object.values(nb.outputEditors).forEach((cm) => { try { cm.refresh(); } catch (e) { /* removed */ } });
    }, 0);
  };
  window.addEventListener('resize', debounce(() => nb.refreshEditors(), 150));
  nb.addRow = function (afterId) {
    const row = el('<div class="cell-add"><button title="Insert a patch below">' + PB.icon('plus', 12) + ' patch</button><button title="Insert a note below">' + PB.icon('type', 12) + ' note</button></div>');
    row.children[0].addEventListener('click', () => nb.addCell('patch', afterId));
    row.children[1].addEventListener('click', () => nb.addCell('note', afterId));
    return row;
  };

  // ---------------------------------------------------------------- one cell
  nb.renderCell = function (cell, index) {
    const pro = PB.isPro();
    const article = el('<article class="cell cell-' + esc(cell.kind) + ' status-' + esc(cell.status) + '" data-id="' + esc(cell.id) + '"><div class="cell-gutter"><span class="no"></span><span class="dot"></span></div><div class="cell-main"><div class="cell-head"></div><div class="cell-input"></div><div class="cell-progress hidden"></div><div class="cell-questions"></div><div class="cell-output"></div></div></article>');
    nb.cellEls[cell.id] = article;
    article.addEventListener('focusin', () => nb.focusCell(cell.id, false));
    article.addEventListener('click', () => nb.focusCell(cell.id, false));
    nb.renderHead(cell, article);
    nb.renderInput(cell, article);
    nb.renderOutput(cell, article);
    nb.renderGutter(cell, article);
    void index; void pro;
    return article;
  };
  nb.renderGutter = function (cell, article) {
    article = article || nb.cellEls[cell.id];
    if (!article) return;
    article.className = 'cell cell-' + cell.kind + ' status-' + cell.status + (nb.focusedId === cell.id ? ' focused' : '');
    const no = article.querySelector('.cell-gutter .no');
    no.textContent = cell.kind === 'note' ? '' : (cell.status === 'running' ? '[*]' : (cell.executionCount != null ? '[' + cell.executionCount + ']' : '[ ]'));
    no.title = STATUS_LABEL[cell.status] || '';
  };
  nb.renderHead = function (cell, article) {
    const head = article.querySelector('.cell-head');
    const pro = PB.isPro();
    const kindIcon = { patch: 'patch', note: 'type', code: 'code' }[cell.kind];
    let html = '<span class="cell-kind">' + PB.icon(kindIcon, 14) + ' ' + esc(cell.kind) + '</span>';
    if (cell.kind === 'patch' && pro) {
      html += '<select data-engine title="How this patch runs"><option value="">engine: default</option>' + Object.keys(ENGINE_INFO).map((k) => '<option value="' + k + '" ' + (cell.engine === k ? 'selected' : '') + '>' + esc(ENGINE_INFO[k].label.toLowerCase()) + '</option>').join('') + '</select>';
    }
    if ((cell.kind === 'code' || (cell.kind === 'patch' && pro))) {
      html += '<select data-language title="Language"><option value="auto">' + (cell.kind === 'code' ? 'python' : 'language: auto') + '</option>' + (PB.boot.languages || []).filter((l) => cell.kind !== 'code' || l !== 'python').map((l) => '<option value="' + esc(l) + '" ' + (cell.language === l ? 'selected' : '') + '>' + esc(l) + '</option>').join('') + '</select>';
    }
    html += '<span class="badge status-badge hidden"></span>';
    html += '<div class="cell-actions">' + (cell.kind !== 'note' ? '<button class="icon-btn" data-run title="Run this ' + cell.kind + ' (Ctrl+Enter)">' + PB.icon('play') + '</button><button class="icon-btn hidden" data-stopcell title="Stop">' + PB.icon('stop') + '</button>' : '') +
      '<button class="icon-btn" data-more title="More">' + PB.icon('more') + '</button></div>';
    head.innerHTML = html;
    const eng = head.querySelector('[data-engine]');
    if (eng) eng.addEventListener('change', () => { cell.engine = eng.value; nb.save(); });
    const lang = head.querySelector('[data-language]');
    if (lang) lang.addEventListener('change', () => { cell.language = lang.value; if (cell.kind === 'code' && nb.editors[cell.id]) nb.editors[cell.id].setOption('mode', PB.ui.cmMode(lang.value === 'auto' ? 'python' : lang.value) || 'text/plain'); nb.save(); });
    const run = head.querySelector('[data-run]');
    if (run) run.addEventListener('click', () => nb.runCell(cell.id));
    const stop = head.querySelector('[data-stopcell]');
    if (stop) stop.addEventListener('click', () => PB.runs.stop());
    head.querySelector('[data-more]').addEventListener('click', (e) => { const r = e.currentTarget.getBoundingClientRect(); nb.cellMenu(cell, r.left, r.bottom + 4); });
    nb.updateBadge(cell, article);
  };
  nb.updateBadge = function (cell, article) {
    article = article || nb.cellEls[cell.id];
    if (!article) return;
    const badge = article.querySelector('.status-badge');
    const label = STATUS_LABEL[cell.status] || '';
    badge.classList.toggle('hidden', !label || cell.kind === 'note');
    badge.className = 'badge status-badge ' + cell.status + (label && cell.kind !== 'note' ? '' : ' hidden');
    badge.textContent = label;
    const running = cell.status === 'running';
    const run = article.querySelector('[data-run]'), stop = article.querySelector('[data-stopcell]');
    if (run) run.classList.toggle('hidden', running);
    if (stop) stop.classList.toggle('hidden', !running);
  };

  nb.renderInput = function (cell, article) {
    const box = article.querySelector('.cell-input');
    box.innerHTML = '';
    if (cell.kind === 'note' && !nb.editingNote[cell.id]) {
      const view = el('<div class="note-view markdown"></div>');
      view.innerHTML = PB.ui.markdown(cell.text);
      view.title = 'Double-click to edit';
      view.addEventListener('dblclick', () => { nb.editingNote[cell.id] = true; nb.renderInput(cell, article); box.querySelector('textarea').focus(); });
      box.appendChild(view);
      return;
    }
    if (cell.kind === 'code') {
      const holder = el('<div></div>');
      box.appendChild(holder);
      const cm = CodeMirror(holder, { value: cell.text || '', mode: PB.ui.cmMode(cell.language === 'auto' ? 'python' : cell.language) || 'python', lineNumbers: true, lineWrapping: true, theme: PB.ui.cmTheme(),
        matchBrackets: true, placeholder: 'Write code here. It runs as it is, in the project folder; no model is involved.', viewportMargin: Infinity, indentUnit: 4,
        extraKeys: { 'Ctrl-Enter': () => nb.runCell(cell.id), 'Shift-Enter': () => nb.runCell(cell.id, { next: true }) } });
      cm.on('change', () => { cell.text = cm.getValue(); nb.touched(cell); });
      cm.on('focus', () => nb.focusCell(cell.id, false));
      PB.bus.on('theme', () => cm.setOption('theme', PB.ui.cmTheme()));
      nb.editors[cell.id] = cm;
      return;
    }
    const placeholder = cell.kind === 'note' ? 'Write a note in Markdown. It documents; it never runs.' : 'What should this patch do? For example: Plot the price distribution of data/products.csv as a histogram and save it as price_hist.png.';
    const ta = el('<textarea rows="2" placeholder="' + esc(placeholder) + '"></textarea>');
    ta.value = cell.text || '';
    box.appendChild(ta);
    const grow = () => { ta.style.height = 'auto'; ta.style.height = Math.max(54, ta.scrollHeight + 2) + 'px'; };
    ta.addEventListener('input', () => { cell.text = ta.value; grow(); nb.touched(cell); });
    ta.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); if (cell.kind === 'patch') nb.runCell(cell.id); else nb.finishNote(cell); }
      else if (e.key === 'Enter' && e.shiftKey) { e.preventDefault(); if (cell.kind === 'patch') nb.runCell(cell.id, { next: true }); else nb.finishNote(cell); }
      else if (e.key === 'Escape' && cell.kind === 'note') { nb.finishNote(cell); }
    });
    if (cell.kind === 'note') ta.addEventListener('blur', () => setTimeout(() => { if (nb.editingNote[cell.id]) nb.finishNote(cell); }, 120));
    requestAnimationFrame(grow);
  };
  nb.finishNote = function (cell) {
    nb.editingNote[cell.id] = false;
    const article = nb.cellEls[cell.id];
    if (article) nb.renderInput(cell, article);
    nb.save();
  };
  nb.touched = function (cell) {
    if (cell.result && cell.kind !== 'note' && cell.status !== 'running' && cell.status !== 'stale') { cell.status = 'stale'; nb.renderGutter(cell); nb.updateBadge(cell); PB.bus.emit('cells'); }
    nb.save();
  };

  // ---------------------------------------------------------------- output
  nb.renderOutput = function (cell, article) {
    article = article || nb.cellEls[cell.id];
    if (!article) return;
    const out = article.querySelector('.cell-output');
    out.innerHTML = '';
    const r = cell.result;
    if (!r || cell.kind === 'note') return;
    const pro = PB.isPro();
    const pid = PB.state.project.id;
    const sections = [];
    // While a new run is going, what is shown below is the previous result, and says so.
    const previous = cell.status === 'running' || cell.status === 'queued';
    out.classList.toggle('previous', previous);
    if (previous) sections.push('<div class="out-section previous-label"><div class="out-label">' + PB.icon('history', 13) + ' Previous result' + (r.finishedAt ? ' · finished ' + esc(PB.util.relTime(r.finishedAt)) : '') + ' · replaced when this run ends</div></div>');
    const status = previous ? (r.ok ? 'done' : 'failed') : cell.status;
    if (r.demo) sections.push('<div class="out-section"><div class="callout warn">' + PB.icon('info', 14) + ' This answer came from the <b>demo model</b>, which only lists the files of the project. <a href="#" data-open-settings>Connect a model in Settings</a> to get real answers.</div></div>');
    if (r.error && status !== 'done') sections.push('<div class="out-section"><div class="out-label">' + (status === 'stopped' ? 'Stopped' : 'What went wrong') + '</div><div class="out-error">' + esc(r.error) + (pro && r.stderr && !String(r.error).includes(String(r.stderr).trim().slice(-80)) ? '\n\n' + esc(String(r.stderr).trim().slice(-1500)) : '') + '</div></div>');
    if (r.attempts && r.attempts.length > 1) {
      const WORD = { done: 'done', failed: 'did not finish', partial: 'partly done', stopped: 'stopped' };
      const COLOR = { done: 'var(--ok)', failed: 'var(--bad)', partial: 'var(--warn)', stopped: 'var(--warn)' };
      const ICON = { done: 'check-circle', failed: 'x-circle', partial: 'alert-circle', stopped: 'stop' };
      sections.push('<div class="out-section"><div class="out-label">' + r.attempts.length + ' approaches tried' + (r.effort ? '<span class="right">effort: ' + esc(r.effort) + '</span>' : '') + '</div><ul class="out-steps" style="list-style:none;padding:0;margin:0">' +
        r.attempts.map((a, i) => '<li><span style="color:' + (COLOR[a.status] || 'var(--muted)') + '">' + PB.icon(ICON[a.status] || 'circle', 14) + '</span> ' + (i + 1) + '. ' + esc(a.label || a.strategy) + ' <span class="muted">— ' + esc(WORD[a.status] || a.status) + (a.status !== 'done' && a.error ? ': ' + esc(String(a.error).slice(0, 160)) : '') + (a.elapsed ? ' · ' + PB.util.fmtSeconds(a.elapsed) : '') + '</span></li>').join('') + '</ul></div>');
    }
    const summary = (r.summary || '').trim();
    if (summary) {
      const isProse = r.engine === 'thorough' || r.engine === 'ask';
      sections.push('<div class="out-section"><div class="out-label">' + (isProse ? 'Answer' : 'Result') + (r.engine === 'thorough' && r.reportPath ? '<a href="#" class="right" data-report>Open the full report</a>' : '') + '</div>' +
        (isProse ? '<div class="markdown">' + PB.ui.markdown(summary) + '</div>' : '<div class="out-stdout">' + esc(summary) + '</div>') + '</div>');
    } else if (status === 'done' && !r.error) {
      sections.push('<div class="out-section"><div class="muted">Finished without printing anything.</div></div>');
    }
    if (r.planSteps && r.planSteps.length) {
      const icon = (s) => ({ done: 'check-circle', failed: 'x-circle', skipped: 'minus', running: 'loader', pending: 'circle' }[s] || 'circle');
      sections.push('<div class="out-section"><div class="out-label">Steps</div><ul class="out-steps" style="list-style:none;padding:0;margin:0">' + r.planSteps.map((s) => '<li><span class="' + (s.status === 'done' ? 'ok' : (s.status === 'failed' ? 'bad' : 'muted')) + '" style="color:' + (s.status === 'done' ? 'var(--ok)' : (s.status === 'failed' ? 'var(--bad)' : 'var(--muted)')) + '">' + PB.icon(icon(s.status), 14) + '</span> ' + esc(s.title) + (s.summary ? ' <span class="muted">— ' + esc(String(s.summary).slice(0, 200)) + '</span>' : '') + '</li>').join('') + '</ul></div>');
    }
    const files = (r.files || []);
    if (files.length) {
      const images = files.filter((f) => f.kind === 'image');
      const others = files.filter((f) => f.kind !== 'image');
      let html = '<div class="out-section"><div class="out-label">' + plural(files.length, 'file') + ' produced</div>';
      if (others.length) html += '<div class="out-files">' + others.map((f) => '<span class="file-chip" data-file="' + esc(f.path) + '">' + PB.icon(f.kind === 'table' ? 'grid' : 'file-text', 14) + esc(f.name) + '<span class="size">' + fmtBytes(f.size) + '</span></span>').join('') + '</div>';
      if (images.length) html += '<div class="out-images">' + images.map((f) => '<figure><img src="' + esc(PB.files.rawUrl(f.path)) + '?t=' + Date.now() + '" alt="' + esc(f.name) + '" data-img="' + esc(f.path) + '"><figcaption>' + esc(f.path) + '</figcaption></figure>').join('') + '</div>';
      sections.push(html + '</div>');
    }
    if (r.checks && r.checks.length) {
      sections.push('<div class="out-section"><div class="out-label">Checks</div>' + r.checks.map((c) => '<div>' + (c.passed ? '<span style="color:var(--ok)">' + PB.icon('check', 14) + '</span>' : '<span style="color:var(--bad)">' + PB.icon('x', 14) + '</span>') + ' ' + esc(c.name) + (c.detail ? ' <span class="muted">' + esc(c.detail) + '</span>' : '') + '</div>').join('') + '</div>');
    }
    if (r.code && cell.kind === 'patch') {
      const show = cell.options.showCode != null ? cell.options.showCode : !!(PB.config.cellDefaults || {}).showCode;
      sections.push('<div class="out-section out-code"><div class="out-label"><a href="#" data-togglecode>' + PB.icon(show ? 'chevron-down' : 'chevron-right', 14) + ' ' + (show ? 'Hide the code' : 'Show the code') + '</a><span class="right muted">' + esc(r.language || '') + (r.iterations > 1 ? ' · repaired ' + (r.iterations - 1) + 'x' : '') + '</span></div><div class="code-holder ' + (show ? '' : 'hidden') + '"></div></div>');
    }
    if (pro && r.stderr && status === 'done' && String(r.stderr).trim()) sections.push('<div class="out-section"><details><summary class="muted small">Warnings and messages (stderr)</summary><div class="out-stdout">' + esc(String(r.stderr).trim().slice(-3000)) + '</div></details></div>');
    const meta = [];
    if (r.model) meta.push('model: ' + esc(r.model));
    if (r.elapsed != null) meta.push('took ' + PB.util.fmtSeconds(r.elapsed));
    if (r.finishedAt) meta.push('finished ' + PB.util.relTime(r.finishedAt));
    if (pro && r.runDir) meta.push('<span class="mono">' + esc(r.runDir) + '</span>');
    if (pro && r.usage && r.usage.totalTokens) meta.push(r.usage.totalTokens + ' tokens');
    if (pro && r.engine) meta.push('engine: ' + esc(r.engine));
    if (r.effort && !(r.attempts && r.attempts.length > 1)) meta.push('effort: ' + esc(r.effort));
    if (meta.length) sections.push('<div class="out-section"><div class="out-meta">' + meta.map((m) => '<span>' + m + '</span>').join('') + '</div></div>');
    out.innerHTML = sections.join('');
    const settingsLink = out.querySelector('[data-open-settings]');
    if (settingsLink) settingsLink.addEventListener('click', (e) => { e.preventDefault(); PB.settings.open('model'); });
    out.querySelectorAll('[data-file]').forEach((chip) => chip.addEventListener('click', () => PB.files.preview(chip.dataset.file)));
    out.querySelectorAll('[data-img]').forEach((img) => img.addEventListener('click', () => PB.ui.lightbox(img.src, img.dataset.img)));
    const report = out.querySelector('[data-report]');
    if (report) report.addEventListener('click', (e) => { e.preventDefault(); PB.files.preview(r.reportPath); });
    const toggle = out.querySelector('[data-togglecode]');
    if (toggle) {
      const holder = out.querySelector('.code-holder');
      const mount = () => { if (!holder.dataset.mounted) { holder.dataset.mounted = '1'; nb.outputEditors[cell.id] = PB.ui.codeView(holder, r.code, r.language); } };
      if (!holder.classList.contains('hidden')) mount();
      toggle.addEventListener('click', (e) => { e.preventDefault(); const show = holder.classList.contains('hidden'); holder.classList.toggle('hidden', !show); cell.options.showCode = show; if (show) { mount(); setTimeout(() => nb.outputEditors[cell.id] && nb.outputEditors[cell.id].refresh(), 10); } toggle.innerHTML = PB.icon(show ? 'chevron-down' : 'chevron-right', 14) + ' ' + (show ? 'Hide the code' : 'Show the code'); nb.save(); });
    }
    void pid;
  };

  // ---------------------------------------------------------------- cell operations
  nb.cellIndex = (id) => PB.state.patchbook.cells.findIndex((c) => c.id === id);
  nb.cell = (id) => PB.state.patchbook.cells.find((c) => c.id === id);
  nb.newCell = function (kind, text) {
    const now = PB.util.nowIso();
    return { id: PB.util.uid(), kind: kind || 'patch', text: text || '', language: 'auto', engine: '', status: 'idle', executionCount: null, result: null, steps: [], runId: '', created: now, updated: now, finished: '', options: { showCode: null, excluded: false, pinned: false, collapsed: false } };
  };
  nb.addCell = function (kind, afterId, text) {
    const cell = nb.newCell(kind, text);
    const cells = PB.state.patchbook.cells;
    const at = afterId ? nb.cellIndex(afterId) + 1 : cells.length;
    cells.splice(at, 0, cell);
    if (kind === 'note') nb.editingNote[cell.id] = true;
    nb.renderCells();
    nb.focusCell(cell.id, true);
    nb.save();
    return cell;
  };
  nb.deleteCell = async function (id) {
    const cell = nb.cell(id);
    if (!cell) return;
    if (cell.status === 'running') { PB.ui.toast('Stop the patch before deleting it.', 'warn'); return; }
    if ((cell.text || '').trim() || cell.result) {
      const ok = await PB.ui.confirm({ title: 'Delete this ' + cell.kind + '?', message: 'Its text and result are removed from the Patchbook. Files it produced stay in the project folder.', okLabel: 'Delete', danger: true });
      if (!ok) return;
    }
    PB.state.patchbook.cells.splice(nb.cellIndex(id), 1);
    if (!PB.state.patchbook.cells.length) PB.state.patchbook.cells.push(nb.newCell('patch'));
    nb.renderCells(); nb.save();
  };
  nb.moveCell = function (id, dir) {
    const cells = PB.state.patchbook.cells;
    const i = nb.cellIndex(id), j = i + dir;
    if (i < 0 || j < 0 || j >= cells.length) return;
    const [c] = cells.splice(i, 1); cells.splice(j, 0, c);
    nb.renderCells(); nb.focusCell(id, true); nb.save();
  };
  nb.duplicateCell = function (id) {
    const src = nb.cell(id);
    const copy = nb.newCell(src.kind, src.text);
    copy.language = src.language; copy.engine = src.engine;
    PB.state.patchbook.cells.splice(nb.cellIndex(id) + 1, 0, copy);
    nb.renderCells(); nb.focusCell(copy.id, true); nb.save();
  };
  nb.changeKind = function (id, kind) {
    const cell = nb.cell(id);
    if (!cell || cell.kind === kind || cell.status === 'running') return;
    cell.kind = kind; cell.result = null; cell.status = 'idle'; cell.executionCount = null; cell.steps = [];
    if (kind === 'code' && cell.language === 'auto') cell.language = 'python';
    nb.renderCells(); nb.focusCell(id, true); nb.save();
  };
  nb.clearResult = function (id) {
    const cell = nb.cell(id);
    if (!cell || cell.status === 'running') return;
    cell.result = null; cell.status = 'idle'; cell.executionCount = null; cell.steps = []; cell.runId = '';
    nb.replaceCell(cell); nb.save();
  };
  nb.clearAll = async function () {
    const ok = await PB.ui.confirm({ title: 'Clear every result?', message: 'The patches stay; their results and numbering are cleared. Files stay in the project folder.', okLabel: 'Clear' });
    if (!ok) return;
    PB.state.patchbook.cells.forEach((c) => { if (c.status !== 'running') { c.result = null; c.status = 'idle'; c.executionCount = null; c.steps = []; c.runId = ''; } });
    PB.state.patchbook.executionCounter = 0;
    nb.renderCells(); nb.save();
  };
  nb.replaceCell = function (cell) {
    const old = nb.cellEls[cell.id];
    if (!old) return;
    const i = nb.cellIndex(cell.id);
    const fresh = nb.renderCell(cell, i);
    old.replaceWith(fresh);
    nb.refreshEditors();
    PB.bus.emit('cells');
  };
  nb.focusCell = function (id, scroll) {
    if (nb.focusedId && nb.cellEls[nb.focusedId]) nb.cellEls[nb.focusedId].classList.remove('focused');
    nb.focusedId = id;
    const art = nb.cellEls[id];
    if (!art) return;
    art.classList.add('focused');
    if (scroll) {
      art.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      const ta = art.querySelector('textarea');
      if (ta) ta.focus(); else if (nb.editors[id]) nb.editors[id].focus();
    }
    PB.bus.emit('focus-cell', id);
  };
  nb.cellMenu = function (cell, x, y) {
    const pro = PB.isPro();
    const i = nb.cellIndex(cell.id);
    const items = [];
    if (cell.kind !== 'note') {
      items.push({ label: 'Run', icon: 'play', shortcut: 'Ctrl+Enter', enabled: () => !PB.state.activeRun, action: () => nb.runCell(cell.id) });
      items.push({ label: 'Run and move to the next', icon: 'play', shortcut: 'Shift+Enter', enabled: () => !PB.state.activeRun, action: () => nb.runCell(cell.id, { next: true }) });
      items.push({ label: 'Run from here to the end', icon: 'skip-forward', enabled: () => !PB.state.activeRun, action: () => nb.runFrom(cell.id) });
      if (cell.kind === 'patch' && pro) items.push({ label: 'Run with…', icon: 'sliders', submenu: Object.keys(ENGINE_INFO).map((k) => ({ label: ENGINE_INFO[k].label + ' — ' + ENGINE_INFO[k].hint, action: () => nb.runCell(cell.id, { engine: k }) })) });
      if (cell.kind === 'patch' && (PB.boot.efforts || []).length) items.push({ label: 'Run with effort…', icon: 'activity', submenu: PB.boot.efforts.map((e) => ({ label: e.label + ' — ' + e.description, action: () => nb.runCell(cell.id, { effort: e.id }) })) });
      items.push({ sep: true });
    }
    items.push({ label: 'Move up', icon: 'arrow-up', enabled: () => i > 0, action: () => nb.moveCell(cell.id, -1) });
    items.push({ label: 'Move down', icon: 'arrow-down', enabled: () => i < PB.state.patchbook.cells.length - 1, action: () => nb.moveCell(cell.id, 1) });
    items.push({ label: 'Duplicate', icon: 'copy', action: () => nb.duplicateCell(cell.id) });
    items.push({ label: 'Change to…', icon: 'edit', submenu: [
      { label: 'Patch (plain language)', radio: true, checked: cell.kind === 'patch', action: () => nb.changeKind(cell.id, 'patch') },
      { label: 'Note (Markdown)', radio: true, checked: cell.kind === 'note', action: () => nb.changeKind(cell.id, 'note') },
      { label: 'Code cell', radio: true, checked: cell.kind === 'code', visible: () => pro, action: () => nb.changeKind(cell.id, 'code') }] });
    if (cell.kind === 'patch' && cell.result && cell.result.code && pro) items.push({ label: 'Copy the code into a new code cell', icon: 'code', action: () => { const c = nb.addCell('code', cell.id, cell.result.code); c.language = cell.result.language || 'python'; nb.replaceCell(c); nb.save(); } });
    if (cell.kind !== 'note') items.push({ label: 'Clear the result', icon: 'rotate-ccw', enabled: () => !!cell.result && cell.status !== 'running', action: () => nb.clearResult(cell.id) });
    if (pro && cell.kind !== 'note') {
      items.push({ sep: true });
      items.push({ label: 'Keep this cell in context for later patches', checked: () => !!cell.options.pinned, action: () => { cell.options.pinned = !cell.options.pinned; nb.save(); } });
      items.push({ label: 'Hide this cell from later patches', checked: () => !!cell.options.excluded, action: () => { cell.options.excluded = !cell.options.excluded; nb.save(); } });
    }
    items.push({ sep: true });
    items.push({ label: 'Delete', icon: 'trash', enabled: () => cell.status !== 'running', action: () => nb.deleteCell(cell.id) });
    PB.ui.popup(items, x, y);
  };

  // ---------------------------------------------------------------- running
  nb.runCell = function (id, opts) {
    const cell = nb.cell(id);
    if (!cell) return;
    if (cell.kind === 'note') { if (opts && opts.next) nb.focusNext(id); return; }
    if (!(cell.text || '').trim()) { PB.ui.toast('Write what the patch should do first.', 'warn'); nb.focusCell(id, true); return; }
    if (nb.editingNote[id]) nb.finishNote(cell);
    PB.runs.runCell(id, opts || {});
    if (opts && opts.next) nb.focusNext(id, true);
  };
  nb.focusNext = function (id, createIfLast) {
    const cells = PB.state.patchbook.cells;
    const i = nb.cellIndex(id);
    if (i < cells.length - 1) nb.focusCell(cells[i + 1].id, true);
    else if (createIfLast) nb.addCell('patch');
  };
  nb.runAll = function () {
    const ids = PB.state.patchbook.cells.filter((c) => c.kind !== 'note' && (c.text || '').trim()).map((c) => c.id);
    if (!ids.length) { PB.ui.toast('There is nothing to run yet.', 'warn'); return; }
    PB.runs.runMany(ids);
  };
  nb.runFrom = function (id) {
    const cells = PB.state.patchbook.cells;
    const ids = cells.slice(nb.cellIndex(id)).filter((c) => c.kind !== 'note' && (c.text || '').trim()).map((c) => c.id);
    PB.runs.runMany(ids);
  };

  // ---------------------------------------------------------------- save
  nb.save = debounce(() => nb.saveNow(), 700);
  nb.saveNow = async function () {
    nb.save.cancel();
    const book = PB.state.patchbook, project = PB.state.project;
    if (!book || !project) return;
    if (PB.config.autosave === false && !nb.forceSave) { nb.markSaved('dirty'); return; }
    nb.forceSave = false;
    nb.markSaved('saving');
    try {
      const saved = await PB.api('/api/projects/' + encodeURIComponent(project.id) + '/patchbooks/' + encodeURIComponent(book.id), { method: 'PUT', body: book });
      if (PB.state.patchbook === book) { book.updated = saved.updated; }
      nb.savedAt = new Date();
      nb.markSaved('saved');
      const entry = PB.state.patchbooks.find((x) => x.id === book.id);
      if (entry) entry.name = book.name;
    } catch (e) { nb.markSaved('error', e.message); }
  };
  nb.saveExplicit = function () { nb.forceSave = true; nb.saveNow(); };
  nb.markSaved = function (state, detail) {
    nb.saveState = state;
    const elSave = document.querySelector('[data-save]');
    const text = { saving: PB.icon('loader', 12) + ' Saving…', saved: PB.icon('check', 12) + ' Saved' + (nb.savedAt ? ' ' + PB.util.fmtClock(nb.savedAt) : ''), dirty: 'Not saved (autosave is off; press Ctrl+S)', error: '<span style="color:var(--bad)">Not saved: ' + esc(detail || '') + '</span>' }[state] || '';
    if (elSave) elSave.innerHTML = text;
    const modelText = !PB.state.model ? '' : (!PB.state.model.configured ? 'demo model' : (PB.state.model.model !== 'auto' ? PB.state.model.model : ('model: automatic' + (PB.state.lastModel ? ' (last: ' + PB.state.lastModel + ')' : ''))));
    PB.ui.status.right((PB.state.model ? '<span class="seg clickable" data-model title="The model answering your patches. Click to change it.">' + PB.icon(PB.state.model.configured ? 'cpu' : 'alert-triangle', 13) + ' ' + esc(modelText) + '</span>' : '') +
      ' <span class="seg hide-sm">' + esc(PB.isPro() ? 'Professional' : 'Simple') + ' look</span>');
    const m = document.querySelector('[data-model]');
    if (m) m.addEventListener('click', () => PB.settings.open('model'));
  };

  // ---------------------------------------------------------------- outline panel
  PB.panels.register({
    id: 'outline', title: 'Outline', icon: 'list', dock: 'left', order: 20, looks: ['professional'],
    description: 'Every cell of the open Patchbook. Click one to jump to it.',
    defaultVisible: { simple: false, professional: true },
    render(body) { body.innerHTML = '<div class="muted">Open a Patchbook.</div>'; nb.renderOutline(); },
    refresh() { nb.renderOutline(); },
  });
  nb.renderOutline = function () {
    const inst = PB.panels.instances.outline;
    if (!inst) return;
    const book = PB.state.patchbook;
    if (!book) { inst.body.innerHTML = '<div class="empty">' + PB.icon('list', 26) + 'Open a Patchbook to see its outline.</div>'; return; }
    const ul = el('<ul class="steps-list"></ul>');
    book.cells.forEach((c, i) => {
      const li = el('<li style="cursor:pointer" class="' + (c.status === 'done' ? 'ok' : (c.status === 'failed' ? 'bad' : '')) + '"><span class="ic">' + PB.icon({ patch: 'patch', note: 'type', code: 'code' }[c.kind], 13) + '</span><span class="grow truncate">' + esc(PB.util.cellLabel(c, i)) + '</span>' + (c.kind !== 'note' && STATUS_LABEL[c.status] ? '<span class="badge ' + esc(c.status) + '">' + esc(STATUS_LABEL[c.status]) + '</span>' : '') + '</li>');
      li.addEventListener('click', () => nb.focusCell(c.id, true));
      ul.appendChild(li);
    });
    inst.body.innerHTML = '<div class="muted small" style="margin-bottom:6px">' + esc(book.name) + ' · ' + plural(book.cells.length, 'cell') + '</div>';
    inst.body.appendChild(ul);
  };
  PB.bus.on('cells', () => nb.renderOutline());
  PB.bus.on('patchbook', () => nb.renderOutline());
  PB.bus.on('project', (p) => { if (!p) nb.renderOutline(); });
})();
