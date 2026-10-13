// Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
// Start-up: the startup screen, boot, plugins, then the wizard or the workbench. Menus and the look switch live here too.
(function () {
  'use strict';
  const PB = window.PB;
  const { esc, el, sleep } = PB.util;
  const app = PB.app = {};

  // ---------------------------------------------------------------- startup screen
  const splash = {
    steps: [], el: null,
    init(list) {
      this.el = document.getElementById('splash-steps');
      this.el.innerHTML = '';
      this.steps = list.map((label) => { const li = el('<li><span class="state">' + PB.icon('circle', 12) + '</span><span class="label">' + esc(label) + '</span><span class="detail"></span></li>'); this.el.appendChild(li); return { label, li }; });
      this.bar(0);
    },
    start(i, detail) { const s = this.steps[i]; s.li.className = 'active'; s.li.querySelector('.state').innerHTML = PB.icon('loader', 14) + ''; s.li.querySelector('.state').firstChild.classList.add('spin'); if (detail != null) s.li.querySelector('.detail').textContent = detail; },
    done(i, detail) { const s = this.steps[i]; s.li.className = 'done'; s.li.querySelector('.state').innerHTML = PB.icon('check', 14); if (detail != null) s.li.querySelector('.detail').textContent = detail; this.bar((i + 1) / this.steps.length * 100); },
    fail(i, detail) { const s = this.steps[i]; s.li.className = 'failed'; s.li.querySelector('.state').innerHTML = PB.icon('x', 14); if (detail != null) s.li.querySelector('.detail').textContent = detail; },
    bar(pct) { document.getElementById('splash-bar').style.width = pct + '%'; },
    note(text) { document.getElementById('splash-note').textContent = text || ''; },
  };

  app.start = async function () {
    splash.init(['Starting Patchbook', 'Loading the iTailor library', 'Loading plugins', 'Loading tools', 'Loading sections', 'Checking your configuration', 'Discovering this computer']);
    const minStep = 220;
    splash.start(0);
    let boot;
    try {
      boot = await PB.api('/api/boot');
    } catch (e) {
      splash.fail(0, 'failed');
      splash.note('Patchbook cannot be reached: ' + e.message + '. Start it with start.bat / start.sh and reload this page.');
      return;
    }
    PB.boot = boot; PB.config = boot.config; PB.state.model = boot.model; PB.state.env = boot.env;
    PB.ui.applyTheme(PB.config.theme);
    await sleep(minStep);
    splash.done(0, 'version ' + boot.app.version);
    splash.start(1);
    await sleep(minStep);
    splash.done(1, 'iTailor ' + boot.library.version);
    splash.start(2);
    let loadedCount = 0;
    await PB.plugins.loadClients(boot.plugins, (p) => { if (p.status === 'loaded') loadedCount++; splash.start(2, p.name); });
    await sleep(minStep);
    const broken = boot.plugins.filter((p) => p.status === 'error');
    splash.done(2, loadedCount + ' loaded' + (broken.length ? ', ' + broken.length + ' failed' : ''));
    if (broken.length) splash.note('Plugin problems: ' + broken.map((p) => p.name + ' (' + p.error + ')').join('; '));
    splash.start(3);
    await sleep(minStep);
    splash.done(3, PB.plugins.tools.length + ' tools');
    splash.start(4);
    await sleep(minStep);
    splash.done(4, PB.panels.available().length + ' panels');
    splash.start(5);
    await sleep(minStep);
    splash.done(5, boot.setupDone ? (boot.model.configured ? 'model connected' : 'demo model') : 'first start');
    splash.start(6);
    const deadline = Date.now() + 3500;
    let env = boot.env;
    while (env.status === 'running' && Date.now() < deadline) { await sleep(400); try { env = await PB.api('/api/env'); } catch (e) { break; } }
    PB.state.env = env;
    if (env.status === 'ready') splash.done(6, env.cached ? 'from cache' : env.seconds + ' s'); else if (env.status === 'error') splash.fail(6, 'failed'); else splash.done(6, 'continues in the background');
    PB.shortcut.install();
    app.defineMenus();
    app.installShortcuts();
    PB.bus.on('config', () => { PB.menu.render(); });
    await sleep(350);
    if (!boot.setupDone) PB.wizard.start(); else app.enterWorkbench(PB.config.openLastProject !== false ? PB.config.lastProjectId : '');
  };

  // ---------------------------------------------------------------- workbench
  app.enterWorkbench = async function (projectId) {
    document.getElementById('splash').classList.add('hidden');
    document.getElementById('wizard').classList.add('hidden');
    document.getElementById('workbench').classList.remove('hidden');
    app.renderMenubarRight();
    PB.menu.render();
    PB.panels.renderDocks();
    PB.notebook.markSaved('saved');
    const greeting = PB.config.userName ? 'Hello ' + PB.config.userName + '. ' : '';
    if (projectId) {
      try { await PB.projects.open(projectId); } catch (e) { PB.projects.showHome(); }
    } else {
      PB.projects.showHome();
    }
    if (!PB.state.model || !PB.state.model.configured) PB.ui.status.mid(greeting + 'No model is connected: patches run with the demo model. Settings connects one.', false);
    else if (greeting) PB.ui.status.mid(greeting + 'Ready.');
    (PB.boot.warnings || []).forEach((w) => PB.ui.toast(w, 'warn', { timeout: 20000 }));
    app.watchEnv();
  };
  app.watchEnv = async function () {
    if (!PB.state.env || PB.state.env.status !== 'running') return;
    for (let i = 0; i < 120; i++) {
      await sleep(2000);
      try { PB.state.env = await PB.api('/api/env'); } catch (e) { return; }
      if (PB.state.env.status !== 'running') { PB.panels.refresh('environment'); return; }
    }
  };
  app.renderMenubarRight = function () {
    const box = document.getElementById('menubar-right');
    box.innerHTML = '<button class="icon-btn dock-toggle" data-dock="left" title="Left panels">' + PB.icon('sidebar', 18) + '</button>' +
      '<span class="project-name truncate muted" data-project></span>' +
      '<button class="ghost small" data-look title="Switch between the Simple and the Professional look">' + PB.icon(PB.isPro() ? 'sliders' : 'eye', 14) + ' <span class="label-text">' + (PB.isPro() ? 'Professional' : 'Simple') + '</span></button>' +
      '<button class="icon-btn" data-settings title="Settings (Ctrl+,)">' + PB.icon('settings', 18) + '</button>' +
      '<button class="icon-btn dock-toggle" data-dock="right" title="Right panels">' + PB.icon('sidebar-right', 18) + '</button>';
    box.querySelector('[data-look]').addEventListener('click', () => app.setLook(PB.isPro() ? 'simple' : 'professional'));
    box.querySelector('[data-settings]').addEventListener('click', () => PB.settings.open());
    box.querySelectorAll('[data-dock]').forEach((b) => b.addEventListener('click', () => PB.panels.toggleDock(b.dataset.dock)));
    const name = box.querySelector('[data-project]');
    name.textContent = PB.state.project ? PB.state.project.name : '';
  };
  PB.bus.on('project', (p) => { const n = document.querySelector('[data-project]'); if (n) n.textContent = p ? p.name : ''; });

  app.setLook = function (look) {
    if (look === PB.look()) return;
    PB.saveConfig({ look });
    app.applyLook();
    PB.ui.toast((look === 'professional' ? 'Professional' : 'Simple') + ' look', 'info', { timeout: 1800 });
  };
  app.applyLook = function () {
    app.renderMenubarRight();
    PB.menu.render();
    PB.panels.renderDocks();
    PB.panels.refreshAll();
    if (PB.state.project && PB.state.patchbook) PB.notebook.render(); else PB.projects.showHome();
    PB.bus.emit('look', PB.look());
  };

  // ---------------------------------------------------------------- menus
  app.defineMenus = function () {
    const hasBook = () => !!(PB.state.project && PB.state.patchbook);
    const focused = () => (hasBook() && PB.notebook.focusedId) ? PB.notebook.cell(PB.notebook.focusedId) : null;
    const idle = () => !PB.state.activeRun;
    PB.menu.define([
      { id: 'file', label: 'File', items: () => [
        { label: 'New project…', icon: 'folder-plus', action: () => PB.projects.create() },
        { label: 'Projects', icon: 'home', action: () => { if (PB.state.project) PB.projects.close(); else PB.projects.showHome(); } },
        { label: 'Open an existing folder…', icon: 'folder-open', visible: PB.isPro, action: () => PB.projects.importFolder() },
        { sep: true },
        { label: 'New Patchbook', icon: 'notebook', shortcut: 'Ctrl+Alt+N', enabled: () => !!PB.state.project, action: () => PB.notebook.create().catch((e) => PB.ui.toast(e.message, 'bad')) },
        { label: 'Rename Patchbook…', icon: 'edit', enabled: hasBook, action: async () => { const n = await PB.ui.prompt({ title: 'Rename Patchbook', label: 'Name', value: PB.state.patchbook.name }); if (n && n.trim()) PB.notebook.rename(PB.state.patchbook.id, n.trim()); } },
        { label: 'Duplicate Patchbook', icon: 'copy', enabled: hasBook, action: () => PB.notebook.duplicate(PB.state.patchbook.id) },
        { label: 'Delete Patchbook…', icon: 'trash', enabled: () => hasBook() && idle(), action: () => PB.notebook.remove(PB.state.patchbook.id) },
        { sep: true },
        { label: 'Add files to the project…', icon: 'upload', enabled: () => !!PB.state.project, action: () => PB.files.upload('data') },
        { label: 'Show the project folder', icon: 'external-link', enabled: () => !!PB.state.project, action: () => PB.api('/api/open-folder', { method: 'POST', body: { path: PB.state.project.path } }).catch((e) => PB.ui.toast(e.message, 'bad')) },
        { label: 'Save now', icon: 'save', shortcut: 'Ctrl+S', enabled: hasBook, action: () => PB.notebook.saveExplicit() },
        { sep: true },
        { label: 'Settings…', icon: 'settings', shortcut: 'Ctrl+,', action: () => PB.settings.open() },
        { label: 'Close project', icon: 'log-out', enabled: () => !!PB.state.project && idle(), action: () => PB.projects.close() },
      ] },
      { id: 'edit', label: 'Edit', items: () => [
        { label: 'Add a patch', icon: 'plus', enabled: hasBook, action: () => PB.notebook.addCell('patch', PB.notebook.focusedId) },
        { label: 'Add a note', icon: 'type', enabled: hasBook, action: () => PB.notebook.addCell('note', PB.notebook.focusedId) },
        { label: 'Add a code cell', icon: 'code', visible: PB.isPro, enabled: hasBook, action: () => PB.notebook.addCell('code', PB.notebook.focusedId) },
        { sep: true },
        { label: 'Move cell up', icon: 'arrow-up', enabled: () => !!focused(), action: () => PB.notebook.moveCell(PB.notebook.focusedId, -1) },
        { label: 'Move cell down', icon: 'arrow-down', enabled: () => !!focused(), action: () => PB.notebook.moveCell(PB.notebook.focusedId, 1) },
        { label: 'Duplicate cell', icon: 'copy', enabled: () => !!focused(), action: () => PB.notebook.duplicateCell(PB.notebook.focusedId) },
        { label: 'Delete cell', icon: 'trash', enabled: () => !!focused() && focused().status !== 'running', action: () => PB.notebook.deleteCell(PB.notebook.focusedId) },
        { sep: true },
        { label: 'Clear the result of this cell', icon: 'rotate-ccw', enabled: () => !!focused() && !!focused().result, action: () => PB.notebook.clearResult(PB.notebook.focusedId) },
        { label: 'Clear every result…', icon: 'rotate-ccw', enabled: () => hasBook() && idle(), action: () => PB.notebook.clearAll() },
      ] },
      { id: 'view', label: 'View', items: () => [
        { head: 'Look' },
        { label: 'Simple', radio: true, checked: () => !PB.isPro(), action: () => app.setLook('simple') },
        { label: 'Professional', radio: true, checked: () => PB.isPro(), action: () => app.setLook('professional') },
        { head: 'Theme' },
        { label: 'Follow the system', radio: true, checked: () => PB.config.theme === 'system', action: () => { PB.saveConfig({ theme: 'system' }); PB.ui.applyTheme('system'); } },
        { label: 'Light', radio: true, checked: () => PB.config.theme === 'light', action: () => { PB.saveConfig({ theme: 'light' }); PB.ui.applyTheme('light'); } },
        { label: 'Dark', radio: true, checked: () => PB.config.theme === 'dark', action: () => { PB.saveConfig({ theme: 'dark' }); PB.ui.applyTheme('dark'); } },
        { head: 'Panels' },
        ...PB.panels.available().map((d) => ({ label: d.title + ' (' + d.dock + ')', checked: () => PB.panels.isVisible(d.id), action: () => PB.panels.toggle(d.id) })),
        { sep: true },
        { label: 'Show generated code by default', checked: () => !!(PB.config.cellDefaults || {}).showCode, action: () => { PB.saveConfig({ cellDefaults: { showCode: !(PB.config.cellDefaults || {}).showCode } }); if (hasBook()) PB.notebook.renderCells(); } },
      ] },
      { id: 'run', label: 'Run', items: () => [
        { label: 'Run this cell', icon: 'play', shortcut: 'Ctrl+Enter', enabled: () => !!focused() && focused().kind !== 'note' && idle(), action: () => PB.notebook.runCell(PB.notebook.focusedId) },
        { label: 'Run and move to the next', icon: 'play', shortcut: 'Shift+Enter', enabled: () => !!focused() && idle(), action: () => PB.notebook.runCell(PB.notebook.focusedId, { next: true }) },
        { label: 'Run from here to the end', icon: 'skip-forward', enabled: () => !!focused() && idle(), action: () => PB.notebook.runFrom(PB.notebook.focusedId) },
        { label: 'Run all', icon: 'fast-forward', enabled: () => hasBook() && idle(), action: () => PB.notebook.runAll() },
        { sep: true },
        { label: 'Stop', icon: 'stop', enabled: () => !idle(), action: () => PB.runs.stop() },
        { sep: true },
        { label: 'Answer clear permission questions for me', checked: () => PB.config.autonomy === 'auto', action: () => { const on = PB.config.autonomy !== 'auto'; PB.saveConfig({ autonomy: on ? 'auto' : 'ask' }); PB.ui.toast(on ? 'Low-risk actions will be allowed and very risky ones refused without asking. You are still asked when it is unclear.' : 'Every question is shown to you, with a recommendation.', 'info', { timeout: 5000 }); } },
        { head: 'Effort for new Patchbooks' },
        ...(PB.boot.efforts || []).map((e) => ({ label: e.label + ' — ' + e.description, radio: true, checked: () => ((PB.config.cellDefaults || {}).effort || 'normal') === e.id, action: () => { PB.saveConfig({ cellDefaults: { effort: e.id } }); if (hasBook() && !PB.state.patchbook.settings.effort) PB.notebook.renderToolbar(); } })),
        { head: 'Default engine', visible: PB.isPro },
        ...(PB.isPro() ? Object.keys(PB.notebook.ENGINE_INFO).map((k) => ({ label: PB.notebook.ENGINE_INFO[k].label + ' — ' + PB.notebook.ENGINE_INFO[k].hint, radio: true, checked: () => ((PB.config.cellDefaults || {}).engine || 'quick') === k, action: () => { PB.saveConfig({ cellDefaults: { engine: k } }); if (hasBook()) PB.notebook.renderToolbar(); } })) : []),
      ] },
      { id: 'tools', label: 'Tools', items: () => [
        ...PB.plugins.toolItems(),
        { sep: true },
        { label: 'Discover this computer again', icon: 'cpu', action: async () => { await PB.api('/api/env?refresh=1'); PB.state.env = { status: 'running' }; PB.ui.toast('Looking at this computer again (interpreters, packages, applications).', 'info'); app.watchEnv(); } },
        { label: 'Run the setup steps again', icon: 'rotate-ccw', enabled: idle, action: () => PB.wizard.start() },
      ] },
      { id: 'help', label: 'Help', items: () => [
        { label: 'Quick guide', icon: 'book-open', action: () => app.guide() },
        { label: 'About Patchbook', icon: 'info', action: () => app.about() },
      ] },
    ]);
  };

  app.installShortcuts = function () {
    PB.shortcut.register('ctrl+enter', () => { if (PB.notebook.focusedId) PB.notebook.runCell(PB.notebook.focusedId); }, { whileTyping: true });
    PB.shortcut.register('shift+enter', () => { if (PB.notebook.focusedId) PB.notebook.runCell(PB.notebook.focusedId, { next: true }); else return false; }, { whileTyping: true });
    PB.shortcut.register('ctrl+s', () => { PB.notebook.saveExplicit(); }, { whileTyping: true });
    PB.shortcut.register('ctrl+alt+n', () => { if (PB.state.project) PB.notebook.create().catch((e) => PB.ui.toast(e.message, 'bad')); }, { whileTyping: true });
    PB.shortcut.register('ctrl+,', () => PB.settings.open(), { whileTyping: true });
  };

  // ---------------------------------------------------------------- help
  app.guide = function () {
    const body = el('<div class="guide">' +
      '<h3>What a Patchbook is</h3><p>A list of <b>patches</b>. A patch is one instruction in plain language, for example <i>Plot the price distribution of data/products.csv as a histogram and save it as price_hist.png</i>. Press <b>Run</b> and iTailor writes the code, runs it in the project folder, reads the real output, repairs it if it fails, and shows the result, the files it produced and, if you want, the code.</p>' +
      '<h3>The screen</h3><ul><li><b>Left: Files.</b> What is in the project folder. Drop files there to add data.</li><li><b>Middle: the Patchbook.</b> Tabs for each Patchbook of the project; the toolbar runs everything; each cell has Run and a menu with more.</li><li><b>Right: Progress.</b> What iTailor is doing right now, in plain words, and its questions.</li><li><b>Bottom: the status line.</b> The open project, what is happening, which model answers.</li></ul>' +
      '<h3>When iTailor asks</h3><p>Installing a package, a command that changes something, the network: these pause the patch and ask inside the cell. <b>Allow once</b> does that one thing; <b>Always in this run</b> that kind of thing until the patch ends; <b>Don\'t allow</b> refuses. No answer counts as a refusal.</p>' +
      '<h3>Notes and order</h3><p>A <b>note</b> is text that documents the work and never runs. Patches run in order and know what earlier patches produced, so a later patch can say <i>use the merged table from above</i>.</p>' +
      '<h3>Effort</h3><p>The <b>Effort</b> bar in the toolbar says how hard iTailor tries. Low: one script and a few repairs. Normal: if the script dead-ends, a different approach that knows what failed. High: then a step-by-step plan with verified steps, and one question to you if still stuck. Maximum: a second plan and up to three rounds of asking you for a hint. The result shows every approach tried.</p>' +
      '<h3>Files and the shared store</h3><p>Code runs in the project folder and may read, create and change files there (and nowhere else). To pass something from one patch to the next, including between languages, iTailor writes it into the <b>shared/</b> folder: tables as CSV, small parameters in <span class="mono">shared/params.json</span>, reusable functions under <span class="mono">shared/methods/</span>. Patchbook records what is there after every run, shows it in the Shared store panel, mirrors it into the project knowledge graph, and tells later patches what exists and how to use it.</p>' +
      '<h3>Two looks</h3><p><b>Simple</b> shows only what you need. <b>Professional</b> adds engines (quick, thorough, ask), code cells, the raw event stream, the environment of this computer, model selection, lessons and run reports. Switch in the View menu or with the button at the top right. Every panel can be hidden from the View menu or with its close button.</p>' +
      '<h3>Keyboard</h3><p><kbd>Ctrl</kbd>+<kbd>Enter</kbd> run the cell · <kbd>Shift</kbd>+<kbd>Enter</kbd> run and move on · <kbd>Ctrl</kbd>+<kbd>S</kbd> save · <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>N</kbd> new Patchbook · <kbd>Ctrl</kbd>+<kbd>,</kbd> settings</p>' +
      '<h3>Reset</h3><p>Settings has a Reset tab: settings only, or everything including what iTailor learned, and optionally the projects.</p></div>');
    PB.ui.dialog({ title: 'Quick guide', icon: 'book-open', wide: true, body });
  };
  app.about = function () {
    const b = PB.boot;
    const plugins = (b.plugins || []).map((p) => '<li>' + esc(p.name) + ' <span class="muted">' + esc(p.version) + ' · ' + esc(p.kind) + ' · ' + esc(p.status) + (p.error ? ': ' + esc(p.error) : '') + '</span></li>').join('');
    const body = el('<div><p><b>Patchbook ' + esc(b.app.version) + '</b><br>Write what you want in plain language; iTailor writes the code, runs it here, repairs it and shows what it found.</p>' +
      '<dl class="kv"><dt>iTailor library</dt><dd>' + esc(b.library.version) + ' <span class="mono small">' + esc(b.library.path) + '</span></dd><dt>Python</dt><dd>' + esc(b.python) + ' on ' + esc(b.platform) + '</dd><dt>Patchbook folder</dt><dd class="mono small">' + esc(b.app.dir) + '</dd><dt>Data folder</dt><dd class="mono small">' + esc(b.app.dataDir) + '</dd><dt>Projects</dt><dd class="mono small">' + esc(b.app.projectsDir) + '</dd></dl>' +
      '<h4 style="margin-top:12px">Plugins</h4><ul style="margin:0;padding-left:18px">' + (plugins || '<li class="muted">none</li>') + '</ul>' +
      '<p class="muted small" style="margin-top:12px">Copyright (c) 2026 Michael Bidollahkhani. MIT License. The patch mechanism is Michael Bidollahkhani\'s original design; Patchbook\'s iTailor was its first application (b-0240331). Third-party components: CodeMirror, marked, DOMPurify (see THIRD_PARTY_NOTICES.md).</p></div>');
    PB.ui.dialog({ title: 'About Patchbook', icon: 'info', body });
  };

  document.addEventListener('DOMContentLoaded', () => { app.start().catch((e) => { console.error(e); splash.note('Patchbook could not start: ' + e.message); }); });
})();
