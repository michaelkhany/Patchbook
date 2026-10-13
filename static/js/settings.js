// Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
// Settings: look, model, permissions, panels, advanced, reset.
(function () {
  'use strict';
  const PB = window.PB;
  const { esc, el } = PB.util;
  const settings = PB.settings = {};

  settings.open = async function (tab) {
    const pro = PB.isPro();
    let it = {};
    try { it = await PB.api('/api/settings/itailor'); } catch (e) { PB.ui.toast('Could not read the model settings: ' + e.message, 'bad'); }
    const cfg = PB.config;
    const presets = PB.boot.permissionPresets || [];
    const body = el('<div class="settings-dialog"><div class="tabs">' +
      '<button data-tab="general">General</button><button data-tab="model">Model</button><button data-tab="permissions">Permissions</button><button data-tab="panels">Panels</button>' +
      (pro ? '<button data-tab="advanced">Advanced</button>' : '') + '<button data-tab="reset">Reset</button></div>' +
      // ---- general
      '<div class="tab-pane" data-pane="general">' +
      '<label>Your name <span class="hint">Only used to greet you.</span><input type="text" data-f="userName" value="' + esc(cfg.userName || '') + '"></label>' +
      '<label>Look</label><div class="cards">' +
      '<div class="card-opt ' + (cfg.look === 'simple' ? 'selected' : '') + '" data-look="simple"><h3>' + PB.icon('eye', 18) + ' Simple</h3><p>Only what you need: the Patchbook, your files and the progress. Nothing technical.</p></div>' +
      '<div class="card-opt ' + (cfg.look === 'professional' ? 'selected' : '') + '" data-look="professional"><h3>' + PB.icon('sliders', 18) + ' Professional</h3><p>Every panel and setting: engines, events, environment, models, lessons, run reports, code cells.</p></div></div>' +
      '<label>Theme</label><div class="row">' + ['system', 'light', 'dark'].map((t) => '<label class="inline"><input type="radio" name="theme" value="' + t + '" ' + (cfg.theme === t ? 'checked' : '') + '> ' + { system: 'Follow the system', light: 'Light', dark: 'Dark' }[t] + '</label>').join('') + '</div>' +
      '<label class="inline"><input type="checkbox" data-f="autosave" ' + (cfg.autosave !== false ? 'checked' : '') + '> Save changes automatically</label>' +
      '<label class="inline"><input type="checkbox" data-f="openLastProject" ' + (cfg.openLastProject !== false ? 'checked' : '') + '> Open the last project when Patchbook starts</label>' +
      '<label class="inline"><input type="checkbox" data-f="showCode" ' + ((cfg.cellDefaults || {}).showCode ? 'checked' : '') + '> Show the generated code under each result by default</label>' +
      '<label>Effort for new Patchbooks <span class="hint">How hard iTailor tries before it gives up or asks you. Every Patchbook also has its own effort bar in the toolbar.</span><select data-f="effort">' + (PB.boot.efforts || []).map((e) => '<option value="' + esc(e.id) + '" ' + (((cfg.cellDefaults || {}).effort || 'normal') === e.id ? 'selected' : '') + '>' + esc(e.label) + ' — ' + esc(e.description) + '</option>').join('') + '</select></label>' +
      (pro ? '<label>Default engine for patches <span class="hint">How a patch runs unless the Patchbook or the patch says otherwise.</span><select data-f="engine">' + Object.keys(PB.notebook.ENGINE_INFO).map((k) => '<option value="' + k + '" ' + ((cfg.cellDefaults || {}).engine === k ? 'selected' : '') + '>' + esc(PB.notebook.ENGINE_INFO[k].label) + ' — ' + esc(PB.notebook.ENGINE_INFO[k].hint) + '</option>').join('') + '</select></label>' : '') +
      (pro ? '<label>Projects folder <span class="hint">Where new projects are created. Leave empty for the default folder inside Patchbook (data/projects). Existing projects stay where they are.</span><input type="text" data-f="projectsDir" value="' + esc(cfg.projectsDir || '') + '" placeholder="' + esc(PB.boot.app.projectsDir) + '"></label>' : '') +
      '</div>' +
      // ---- model
      '<div class="tab-pane" data-pane="model">' +
      '<div class="callout" data-model-status></div>' +
      '<div class="option-list">' +
      '<label class="option"><input type="radio" name="mmode" value="service"><div><div class="title">Connect to a model service</div><div class="desc">Any OpenAI-compatible service: a hosted one (needs the address and your key) or a local server on this computer (Ollama, LM Studio, llama.cpp, vLLM).</div></div></label>' +
      '<label class="option"><input type="radio" name="mmode" value="demo"><div><div class="title">Use the demo model</div><div class="desc">No real answers: it only lists the files of the project so you can see how Patchbook works.</div></div></label></div>' +
      '<div data-service-fields>' +
      '<div class="row" style="margin-top:10px"><button class="small" data-find>' + PB.icon('search', 14) + ' Find services on this computer</button><span class="muted small" data-find-result></span></div>' +
      '<label>Address (base URL)<input type="url" data-f="baseUrl" value="' + esc(it.baseUrl || '') + '" placeholder="https://chat-ai.academiccloud.de/v1 or http://localhost:11434/v1" list="pb-urls"><datalist id="pb-urls"></datalist></label>' +
      '<label>Key <span class="hint">' + (it.apiKeySet ? 'A key is ' + (it.apiKeyRemembered ? 'saved on this computer' : 'set for this session') + '. Enter a new one to replace it.' : 'Local servers need none.') + '</span><input type="password" data-f="apiKey" placeholder="' + (it.apiKeySet ? '(unchanged)' : 'paste your key') + '" autocomplete="off"></label>' +
      '<label class="inline"><input type="checkbox" data-f="remember" checked> Remember the key on this computer (data/secrets.json)</label>' +
      '<label>Model <span class="hint">The list comes from the service itself. "auto" lets iTailor pick the best model the service offers for each role.</span>' +
      '<select data-f="model"><option value="auto">auto — iTailor chooses</option>' + (it.model && it.model !== 'auto' ? '<option value="' + esc(it.model) + '" selected>' + esc(it.model) + '</option>' : '') + '</select>' +
      '<span class="hint" data-model-note></span></label>' +
      '<label>Or type a model id <span class="hint">Only if it is not in the list; it overrides the selection above.</span><input type="text" data-f="modelOther" placeholder="model id"></label>' +
      '<div class="row"><button data-test>' + PB.icon('activity', 14) + ' Test the connection</button>' + (it.apiKeySet ? '<button data-forget class="ghost">Forget the saved key</button>' : '') + '</div><div data-test-result></div>' +
      (pro ? '<label class="inline" style="margin-top:10px"><input type="checkbox" data-f="localOnly" ' + ((it.privacy || {}).localOnly ? 'checked' : '') + '> Only use models that run on this computer (privacy)</label>' : '') +
      '</div></div>' +
      // ---- permissions
      '<div class="tab-pane" data-pane="permissions"><p>Reading your files and running code inside the project are always allowed. This decides what iTailor must ask you about first.</p><div class="option-list">' +
      presets.filter((p) => pro || p.id !== 'all').map((p) => '<label class="option"><input type="radio" name="preset" value="' + esc(p.id) + '" ' + ((it.permissionPreset || cfg.permissionPreset) === p.id ? 'checked' : '') + '><div><div class="title">' + esc(p.name) + '</div><div class="desc">' + esc(p.description) + '</div></div></label>').join('') +
      '</div><p class="muted small" style="margin-top:10px">Questions appear inside the patch and in the Progress panel with the exact action. No answer within the time limit counts as "Don\'t allow".</p>' +
      '<label style="margin-top:14px">When a question comes up</label><div class="option-list">' +
      '<label class="option ' + (cfg.autonomy !== 'auto' ? 'selected' : '') + '"><input type="radio" name="autonomy" value="ask" ' + (cfg.autonomy !== 'auto' ? 'checked' : '') + '><div><div class="title">Ask me, with a recommendation</div><div class="desc">Every question is shown with what Patchbook would do and why (from iTailor\'s risk assessment and your earlier answers). You decide.</div></div></label>' +
      '<label class="option ' + (cfg.autonomy === 'auto' ? 'selected' : '') + '"><input type="radio" name="autonomy" value="auto" ' + (cfg.autonomy === 'auto' ? 'checked' : '') + '><div><div class="title">Answer clear cases for me</div><div class="desc">Low-risk actions are allowed and very risky ones refused without asking; what was decided appears in the progress. You are still asked when the risk is high or unclear, and iTailor\'s own questions about the goal always reach you.</div></div></label></div>' +
      '<p class="muted small" style="margin-top:8px">A question card also offers "Don\'t ask again for this kind in this project", which adds a standing allow rule to the project\'s iTailor settings.</p></div>' +
      // ---- panels
      '<div class="tab-pane" data-pane="panels"><p>Panels shown in the <b>' + esc(cfg.look) + '</b> look. The View menu toggles the same list, and every panel has a close button.</p><div data-panel-list></div></div>' +
      // ---- advanced
      (pro ? '<div class="tab-pane" data-pane="advanced">' +
        '<fieldset><legend>Running code</legend>' +
        '<label>Sandbox for generated Python <span class="hint">strict: no reads outside the project and no network · writes: only writes are confined (default) · off: no guard</span><select data-f="sandboxMode"><option value="">default (writes)</option><option value="strict" ' + ((it.sandbox || {}).mode === 'strict' ? 'selected' : '') + '>strict</option><option value="writes" ' + ((it.sandbox || {}).mode === 'writes' ? 'selected' : '') + '>writes</option><option value="off" ' + ((it.sandbox || {}).mode === 'off' ? 'selected' : '') + '>off</option></select></label>' +
        '<div class="row"><label class="grow">Time limit for one script (seconds)<input type="number" data-f="runTimeoutSeconds" value="' + esc(it.runTimeoutSeconds || 180) + '" min="5" max="3600"></label><label class="grow">Repair attempts for a quick patch<input type="number" data-f="maxIterations" value="' + esc(it.maxIterations || 6) + '" min="0" max="50"></label></div></fieldset>' +
        '<fieldset><legend>Model calls</legend>' +
        '<div class="row"><label class="grow">Tool calling<select data-f="toolCalling"><option value="auto" ' + (it.toolCalling === 'auto' ? 'selected' : '') + '>auto (probe the model)</option><option value="native" ' + (it.toolCalling === 'native' ? 'selected' : '') + '>native</option><option value="text" ' + (it.toolCalling === 'text' ? 'selected' : '') + '>text protocol</option></select></label>' +
        '<label class="grow">Time limit for a model call (seconds)<input type="number" data-f="modelTimeoutSeconds" value="' + esc(it.modelTimeoutSeconds || 180) + '" min="5" max="3600"></label></div>' +
        '<div class="row"><label class="grow">Temperature<input type="number" step="0.05" min="0" max="2" data-f="temperature" value="' + esc(it.temperature != null ? it.temperature : 0.1) + '"></label><label class="grow">Max tokens per reply<input type="number" data-f="maxTokens" value="' + esc(it.maxTokens || 4000) + '" min="256" max="200000"></label></div>' +
        '<label class="inline"><input type="checkbox" data-f="webSearch" ' + (it.webSearch !== false ? 'checked' : '') + '> Allow web search (DuckDuckGo, no key)</label>' +
        '<label class="inline"><input type="checkbox" data-f="approvePlans" ' + (it.approvePlans ? 'checked' : '') + '> Ask me to approve the plan before a thorough run executes it</label>' +
        '<label class="inline"><input type="checkbox" data-f="discoverApps" ' + (it.discoverApps !== false ? 'checked' : '') + '> Discover installed applications (slower first discovery)</label></fieldset>' +
        '<fieldset><legend>Budgets for thorough runs</legend><div class="row">' +
        '<label class="grow">Steps<input type="number" data-b="steps" value="' + esc((it.budgets || {}).steps || 20) + '" min="1" max="200"></label>' +
        '<label class="grow">Repairs per step<input type="number" data-b="repairsPerStep" value="' + esc((it.budgets || {}).repairsPerStep || 3) + '" min="0" max="20"></label>' +
        '<label class="grow">Replans<input type="number" data-b="replans" value="' + esc((it.budgets || {}).replans || 2) + '" min="0" max="20"></label>' +
        '<label class="grow">Minutes<input type="number" data-b="minutes" value="' + esc((it.budgets || {}).minutes || 30) + '" min="1" max="1440"></label></div>' +
        '<label>Time limit for a permission question (seconds)<input type="number" data-f="permissionTimeoutSeconds" value="' + esc(it.permissionTimeoutSeconds || 300) + '" min="10" max="86400"></label></fieldset>' +
        '<p class="muted small">iTailor settings are written to <span class="mono">' + esc(it.userConfigPath || '') + '</span>. A project can add rules of its own in its <span class="mono">.itailor/settings.json</span>.</p></div>' : '') +
      // ---- reset
      '<div class="tab-pane" data-pane="reset">' +
      '<div class="box"><h3>Reset the settings</h3><p>Look, theme, panels, defaults, the model connection and the saved key go back to how they were on first start. Your projects and Patchbooks stay. Patchbook then shows the setup steps again.</p><button data-reset="settings" class="danger">' + PB.icon('rotate-ccw', 14) + ' Reset settings to defaults</button></div>' +
      '<div class="box" style="margin-top:12px"><h3>Reset everything</h3><p>Everything above, plus what iTailor learned (lessons), its environment and model caches. Tick the box to also delete every project in the projects folder.</p><label class="inline"><input type="checkbox" data-delete-projects> Also delete all projects and their Patchbooks</label><div style="margin-top:8px"><button data-reset="everything" class="danger">' + PB.icon('alert-triangle', 14) + ' Reset everything to defaults</button></div></div>' +
      '</div></div>');

    const activate = PB.ui.tabs(body, null, tab || 'general');
    // look cards
    body.querySelectorAll('[data-look]').forEach((c) => c.addEventListener('click', () => { body.querySelectorAll('[data-look]').forEach((x) => x.classList.toggle('selected', x === c)); }));
    // model mode
    const status = PB.state.model || {};
    const statusBox = body.querySelector('[data-model-status]');
    const renderStatus = (s) => {
      statusBox.innerHTML = (s.configured ? PB.icon('check-circle', 14) + ' Connected: ' : PB.icon('alert-triangle', 14) + ' ') + esc(s.label || '') +
        (s.configured && it.apiKeySet ? ' <span class="muted">· key ' + (it.apiKeyRemembered ? 'saved on this computer' : 'set for this session') + '</span>' : '') +
        (PB.state.lastModel ? '<br><span class="muted">The last run used ' + esc(PB.state.lastModel) + '.</span>' : '');
      statusBox.className = 'callout ' + (s.configured ? 'ok' : 'warn');
    };
    renderStatus(status);
    // The model selection: filled from the service's own list, with the current choice selected.
    const modelSelect = body.querySelector('[data-f="model"]');
    const modelNote = body.querySelector('[data-model-note]');
    const fillModels = (models, current, note) => {
      const chosen = current || modelSelect.value || 'auto';
      modelSelect.innerHTML = '<option value="auto">auto — iTailor chooses</option>' + (models || []).map((m) => '<option value="' + esc(m) + '">' + esc(m) + '</option>').join('') +
        (chosen !== 'auto' && !(models || []).includes(chosen) ? '<option value="' + esc(chosen) + '">' + esc(chosen) + ' (not in the list)</option>' : '');
      modelSelect.value = chosen;
      modelNote.textContent = note || '';
    };
    const loadModelList = async (refresh) => {
      if (!(it.baseUrl || status.source === 'local-server')) { modelNote.textContent = 'Connect a service to see its models.'; return; }
      modelNote.textContent = 'Loading the list of models from ' + (it.baseUrl || status.baseUrl || 'the service') + '…';
      try {
        const r = await PB.api('/api/models/list' + (refresh ? '?refresh=1' : ''));
        if (r.ok) fillModels(r.models, r.current, r.models.length + ' model' + (r.models.length === 1 ? '' : 's') + ' offered by ' + r.baseUrl);
        else fillModels([], r.current, 'The list could not be loaded: ' + (r.message || 'no answer') + '. You can still type a model id below.');
      } catch (e) { modelNote.textContent = 'The list could not be loaded: ' + e.message; }
    };
    loadModelList(false);
    const modeInputs = body.querySelectorAll('input[name="mmode"]');
    const initialMode = (it.baseUrl || status.source === 'local-server') ? 'service' : 'demo';
    modeInputs.forEach((i) => { i.checked = i.value === initialMode; i.addEventListener('change', syncMode); });
    function syncMode() { const mode = body.querySelector('input[name="mmode"]:checked').value; body.querySelector('[data-service-fields]').classList.toggle('hidden', mode !== 'service'); body.querySelectorAll('.option').forEach((o) => o.classList.toggle('selected', o.querySelector('input').checked)); }
    syncMode();
    body.querySelectorAll('.option input[type="radio"]').forEach((i) => i.addEventListener('change', () => body.querySelectorAll('.option').forEach((o) => o.classList.toggle('selected', o.querySelector('input').checked))));
    body.querySelector('[data-find]').addEventListener('click', async () => {
      const out = body.querySelector('[data-find-result]');
      out.textContent = 'Looking…';
      try {
        const r = await PB.api('/api/models/discover');
        const found = (r.sources || []).filter((s) => s.base_url && (s.models || []).length);
        body.querySelector('#pb-urls').innerHTML = found.map((s) => '<option value="' + esc(s.base_url) + '">' + esc(s.note || s.id) + '</option>').join('');
        out.textContent = found.length ? 'Found: ' + found.map((s) => s.base_url + ' (' + s.models.length + ' models)').join(', ') + '. Pick one in the address field.' : 'No service found. Start Ollama, LM Studio, llama.cpp or vLLM, or enter the address of a hosted service.';
        if (found.length === 1 && !body.querySelector('[data-f="baseUrl"]').value) body.querySelector('[data-f="baseUrl"]').value = found[0].base_url;
      } catch (e) { out.textContent = e.message; }
    });
    body.querySelector('[data-test]').addEventListener('click', async () => {
      const out = body.querySelector('[data-test-result]');
      const base = body.querySelector('[data-f="baseUrl"]').value.trim();
      if (!base) { out.innerHTML = '<div class="callout warn">Enter the address first.</div>'; return; }
      out.innerHTML = '<div class="muted">' + PB.icon('loader', 14) + ' Testing…</div>';
      try {
        const typed = body.querySelector('[data-f="modelOther"]').value.trim();
        const chosen = typed || modelSelect.value;
        const r = await PB.api('/api/models/test', { method: 'POST', body: { baseUrl: base, apiKey: body.querySelector('[data-f="apiKey"]').value, model: chosen === 'auto' ? '' : chosen } });
        if (r.ok && r.models && r.models.length) fillModels(r.models, chosen, r.models.length + ' model' + (r.models.length === 1 ? '' : 's') + ' offered by ' + base);
        out.innerHTML = '<div class="callout ' + (r.ok ? 'ok' : 'bad') + '">' + (r.ok ? PB.icon('check-circle', 14) + ' ' + esc(r.message || 'It answers.') + (r.models && r.models.length ? ' ' + r.models.length + ' model(s) available; pick one in the list above or keep auto.' : '') + (r.chat ? (r.chat.ok ? ' A test question was answered.' : ' But the chosen model did not answer: ' + esc(r.chat.error)) : '') : PB.icon('x-circle', 14) + ' ' + esc(r.message || 'No answer.')) + ' <span class="muted">(' + r.ms + ' ms)</span></div>';
      } catch (e) { out.innerHTML = '<div class="callout bad">' + esc(e.message) + '</div>'; }
    });
    const forget = body.querySelector('[data-forget]');
    if (forget) forget.addEventListener('click', async () => { await PB.api('/api/settings/itailor', { method: 'POST', body: { forgetKey: true } }); PB.ui.toast('The saved key was removed.', 'ok'); forget.remove(); });
    // panels list
    const plist = body.querySelector('[data-panel-list]');
    PB.panels.available().forEach((d) => {
      const row = el('<label class="inline"><input type="checkbox" data-panel="' + esc(d.id) + '" ' + (PB.panels.isVisible(d.id) ? 'checked' : '') + '> ' + PB.icon(d.icon || 'box', 14) + ' <b>' + esc(d.title) + '</b> <span class="muted">— ' + esc(d.description || '') + ' (' + d.dock + ')</span></label>');
      plist.appendChild(row);
    });
    // reset
    body.querySelectorAll('[data-reset]').forEach((b) => b.addEventListener('click', async () => {
      const scope = b.dataset.reset;
      const deleteProjects = scope === 'everything' && body.querySelector('[data-delete-projects]').checked;
      const ok = await PB.ui.confirm({ title: scope === 'everything' ? 'Reset everything?' : 'Reset the settings?', danger: true, okLabel: 'Reset',
        message: scope === 'everything' ? ('Settings, the saved key, lessons and caches are removed' + (deleteProjects ? ', and every project in the projects folder is deleted' : '') + '. This cannot be undone.') : 'Settings and the saved key go back to defaults. Projects stay.',
        checkbox: deleteProjects ? 'Yes, delete all projects too' : '' });
      if (!ok) return;
      try {
        await PB.api('/api/reset', { method: 'POST', body: { scope, deleteProjects } });
        PB.ui.toast('Reset done. Patchbook restarts with the setup steps.', 'ok');
        setTimeout(() => window.location.reload(), 900);
      } catch (e) { PB.ui.toast(e.message, 'bad'); }
    }));

    PB.ui.dialog({ title: 'Settings', icon: 'settings', wide: true, body, buttons: [{ label: 'Cancel' }, { label: 'Save', primary: true, action: async () => {
      const f = (name) => body.querySelector('[data-f="' + name + '"]');
      const look = body.querySelector('[data-look].selected').dataset.look;
      const patch = { userName: f('userName').value.trim(), look, theme: body.querySelector('input[name="theme"]:checked').value, autosave: f('autosave').checked, openLastProject: f('openLastProject').checked,
        cellDefaults: { showCode: f('showCode').checked } };
      if (f('engine')) patch.cellDefaults.engine = f('engine').value;
      if (f('effort')) patch.cellDefaults.effort = f('effort').value;
      if (f('projectsDir')) patch.projectsDir = f('projectsDir').value.trim();
      const layoutPatch = { layout: {} }; layoutPatch.layout[PB.look()] = { panels: {} };
      body.querySelectorAll('[data-panel]').forEach((cb) => { layoutPatch.layout[PB.look()].panels[cb.dataset.panel] = cb.checked; });
      Object.assign(patch, layoutPatch);
      const it2 = {};
      const mode = body.querySelector('input[name="mmode"]:checked').value;
      if (mode === 'demo') { it2.baseUrl = ''; it2.model = 'auto'; }
      else { it2.baseUrl = f('baseUrl').value.trim(); it2.model = f('modelOther').value.trim() || f('model').value || 'auto'; if (f('apiKey').value) { it2.apiKey = f('apiKey').value; it2.remember = f('remember').checked; } }
      const preset = body.querySelector('input[name="preset"]:checked');
      if (preset) { it2.permissionPreset = preset.value; patch.permissionPreset = preset.value; }
      const autonomy = body.querySelector('input[name="autonomy"]:checked');
      if (autonomy) patch.autonomy = autonomy.value;
      if (f('localOnly')) it2.localOnly = f('localOnly').checked;
      if (f('sandboxMode')) {
        it2.sandboxMode = f('sandboxMode').value; it2.toolCalling = f('toolCalling').value; it2.webSearch = f('webSearch').checked; it2.approvePlans = f('approvePlans').checked; it2.discoverApps = f('discoverApps').checked;
        ['runTimeoutSeconds', 'maxIterations', 'modelTimeoutSeconds', 'maxTokens', 'permissionTimeoutSeconds'].forEach((k) => { it2[k] = Number(f(k).value); });
        it2.temperature = Number(f('temperature').value);
        it2.budgets = {}; body.querySelectorAll('[data-b]').forEach((i) => { it2.budgets[i.dataset.b] = Number(i.value); });
      }
      await PB.api('/api/settings/itailor', { method: 'POST', body: it2 });
      await PB.saveConfig(patch, true);
      PB.state.model = await PB.api('/api/models/status?refresh=1');
      PB.ui.applyTheme(PB.config.theme);
      PB.app.applyLook();
      PB.notebook.markSaved(PB.notebook.saveState);
      PB.ui.toast('Settings saved. ' + (PB.state.model.configured ? 'Model: ' + (PB.state.model.model !== 'auto' ? PB.state.model.model : 'automatic choice') + '.' : 'No model connected; the demo model answers.'), PB.state.model.configured ? 'ok' : 'warn');
    } }] });
    void activate;
  };
})();
