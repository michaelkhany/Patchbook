// Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
// First-run setup: six short steps, saved in one go at the end.
(function () {
  'use strict';
  const PB = window.PB;
  const { esc, el } = PB.util;
  const wizard = PB.wizard = { step: 0, data: null, found: [] };

  const STEPS = ['Welcome', 'Look', 'Storage', 'Model', 'Permissions', 'Ready'];

  wizard.start = function () {
    wizard.step = 0;
    wizard.data = { userName: PB.config.userName || '', look: PB.config.look || 'simple', theme: PB.config.theme || 'system', projectsDir: '',
      model: { mode: (PB.state.model && PB.state.model.source === 'local-server') ? 'found' : 'demo', baseUrl: '', apiKey: '', model: 'auto', remember: true },
      permissionPreset: 'ask', createSample: true, tested: null };
    document.getElementById('splash').classList.add('hidden');
    document.getElementById('workbench').classList.add('hidden');
    const w = document.getElementById('wizard');
    w.classList.remove('hidden');
    wizard.render();
  };

  wizard.render = function () {
    const w = document.getElementById('wizard');
    const d = wizard.data;
    const step = wizard.step;
    const card = el('<div class="wizard-card"><div class="wizard-head"><div class="logo">P</div><div><h2 style="margin:0">Set up Patchbook</h2><div class="muted small">Step ' + (step + 1) + ' of ' + STEPS.length + ': ' + esc(STEPS[step]) + '</div></div></div>' +
      '<div class="wizard-steps">' + STEPS.map((s, i) => '<span class="' + (i < step ? 'done' : (i === step ? 'current' : '')) + '" title="' + esc(s) + '"></span>').join('') + '</div><div class="wizard-body"></div>' +
      '<div class="wizard-foot"><button data-back ' + (step === 0 ? 'disabled' : '') + '>' + PB.icon('arrow-left', 14) + ' Back</button><span class="grow"></span><span class="muted small" data-note></span><button class="primary" data-next>' + (step === STEPS.length - 1 ? 'Finish' : 'Next ' + PB.icon('arrow-right', 14)) + '</button></div></div>');
    const body = card.querySelector('.wizard-body');
    wizard['step' + step](body, d);
    card.querySelector('[data-back]').addEventListener('click', () => { wizard.collect(body); wizard.step--; wizard.render(); });
    card.querySelector('[data-next]').addEventListener('click', async () => {
      const ok = wizard.collect(body);
      if (ok === false) return;
      if (step === STEPS.length - 1) { await wizard.finish(card); return; }
      wizard.step++; wizard.render();
    });
    w.innerHTML = '';
    w.appendChild(card);
    w.scrollTop = 0;
  };
  wizard.collect = function (body) {
    const d = wizard.data;
    const q = (s) => body.querySelector(s);
    switch (wizard.step) {
      case 0: d.userName = q('[data-name]').value.trim(); break;
      case 1: d.look = q('[data-look].selected').dataset.look; d.theme = q('input[name="wtheme"]:checked').value; PB.ui.applyTheme(d.theme); break;
      case 2: d.projectsDir = q('[data-dir]').value.trim(); break;
      case 3: {
        d.model.mode = q('input[name="wmode"]:checked').value;
        if (d.model.mode === 'found') { const sel = q('input[name="wfound"]:checked'); if (!sel) { PB.ui.toast('Pick one of the services found, or choose another option.', 'warn'); return false; } d.model.baseUrl = sel.value; d.model.model = 'auto'; d.model.apiKey = ''; }
        if (d.model.mode === 'hosted') { d.model.baseUrl = q('[data-url]').value.trim(); d.model.apiKey = q('[data-key]').value; d.model.model = q('[data-model]').value.trim() || 'auto'; d.model.remember = q('[data-remember]').checked; if (!d.model.baseUrl) { PB.ui.toast('Enter the address of the service, or choose another option.', 'warn'); return false; } }
        break;
      }
      case 4: d.permissionPreset = q('input[name="wpreset"]:checked').value; break;
      case 5: d.createSample = q('[data-sample]').checked; break;
      default: break;
    }
    return true;
  };

  wizard.step0 = function (body, d) {
    body.innerHTML = '<h1>Welcome</h1><p>Patchbook is a notebook where you write what you want in plain language. iTailor, the engine behind it, writes the code, runs it on this computer, reads the real result, fixes what breaks and shows you what it found, with every file it produced.</p>' +
      '<p>These few steps set it up once. Everything can be changed later in Settings, and Settings has a reset that brings you back here.</p>' +
      '<label>What should Patchbook call you? (optional)<input type="text" data-name value="' + esc(d.userName) + '" placeholder="Your name"></label>';
  };
  wizard.step1 = function (body, d) {
    body.innerHTML = '<h1>Choose a look</h1><p>Both show the same Patchbooks; you can switch at any time from the View menu.</p><div class="cards">' +
      '<div class="card-opt ' + (d.look === 'simple' ? 'selected' : '') + '" data-look="simple"><h3>' + PB.icon('eye', 18) + ' Simple</h3><p>For everyone. The Patchbook, your files and a plain-language progress view. Nothing technical in sight. Recommended to start.</p></div>' +
      '<div class="card-opt ' + (d.look === 'professional' ? 'selected' : '') + '" data-look="professional"><h3>' + PB.icon('sliders', 18) + ' Professional</h3><p>Every panel and control: run engines, the raw event stream, the environment manifest, model selection, lessons, run reports, code cells.</p></div></div>' +
      '<label style="margin-top:16px">Theme</label><div class="row">' + ['system', 'light', 'dark'].map((t) => '<label class="inline"><input type="radio" name="wtheme" value="' + t + '" ' + (d.theme === t ? 'checked' : '') + '> ' + { system: 'Follow the system', light: 'Light', dark: 'Dark' }[t] + '</label>').join('') + '</div>';
    body.querySelectorAll('[data-look]').forEach((c) => c.addEventListener('click', () => body.querySelectorAll('[data-look]').forEach((x) => x.classList.toggle('selected', x === c))));
    body.querySelectorAll('input[name="wtheme"]').forEach((r) => r.addEventListener('change', () => PB.ui.applyTheme(r.value)));
  };
  wizard.step2 = function (body, d) {
    body.innerHTML = '<h1>Where projects are stored</h1><p>A project is a folder with your data files and your Patchbooks. By default they live inside the Patchbook folder, so the whole folder can be copied to another computer with everything in it.</p>' +
      '<label>Projects folder<input type="text" data-dir value="' + esc(d.projectsDir) + '" placeholder="' + esc(PB.boot.app.projectsDir) + '"></label><span class="hint">Leave it empty to use the default shown. If you type another folder, it is created if needed.</span>' +
      '<div class="callout" style="margin-top:16px">' + PB.icon('hard-drive', 14) + ' Patchbook keeps its own settings in <span class="mono">' + esc(PB.boot.app.dataDir) + '</span>. Nothing is stored anywhere else on this computer.</div>';
  };
  wizard.step3 = async function (body, d) {
    body.innerHTML = '<h1>Which model answers your patches?</h1><p>iTailor needs a language model to write code. It can be a service on this computer (free, private, slower) or a hosted service (needs an address and a key). You can also skip this and use the demo model for now.</p>' +
      '<div class="option-list">' +
      '<label class="option ' + (d.model.mode === 'found' ? 'selected' : '') + '"><input type="radio" name="wmode" value="found" ' + (d.model.mode === 'found' ? 'checked' : '') + '><div class="grow"><div class="title">A model service on this computer</div><div class="desc" data-found-desc>Looking for Ollama, LM Studio, llama.cpp and vLLM…</div><div data-found-list style="margin-top:6px"></div></div></label>' +
      '<label class="option ' + (d.model.mode === 'hosted' ? 'selected' : '') + '"><input type="radio" name="wmode" value="hosted" ' + (d.model.mode === 'hosted' ? 'checked' : '') + '><div class="grow"><div class="title">A hosted model service</div><div class="desc">Any OpenAI-compatible service, for example the academic cloud or a commercial provider. The key is stored only on this computer.</div>' +
      '<div data-hosted-fields style="margin-top:8px"><label>Address (base URL)<input type="url" data-url value="' + esc(d.model.baseUrl) + '" placeholder="https://chat-ai.academiccloud.de/v1"></label><label>Key<input type="password" data-key value="' + esc(d.model.apiKey) + '" placeholder="paste your key" autocomplete="off"></label><label>Model (optional)<input type="text" data-model value="' + esc(d.model.model === 'auto' ? '' : d.model.model) + '" placeholder="auto: iTailor picks one" list="w-models"><datalist id="w-models"></datalist></label>' +
      '<label class="inline"><input type="checkbox" data-remember ' + (d.model.remember ? 'checked' : '') + '> Remember the key on this computer</label><div class="row"><button class="small" data-test>' + PB.icon('activity', 14) + ' Test the connection</button></div><div data-test-result></div></div></div></label>' +
      '<label class="option ' + (d.model.mode === 'demo' ? 'selected' : '') + '"><input type="radio" name="wmode" value="demo" ' + (d.model.mode === 'demo' ? 'checked' : '') + '><div><div class="title">Skip for now: use the demo model</div><div class="desc">You can try every button. The demo model gives no real answers: it only lists the files of the project. Connect a model later in Settings.</div></div></label></div>';
    const sync = () => { body.querySelectorAll('.option').forEach((o) => o.classList.toggle('selected', o.querySelector('input[type="radio"]').checked)); body.querySelector('[data-hosted-fields]').classList.toggle('hidden', !body.querySelector('input[value="hosted"]').checked); };
    body.querySelectorAll('input[name="wmode"]').forEach((r) => r.addEventListener('change', sync));
    body.querySelectorAll('[data-hosted-fields] input, [data-hosted-fields] button').forEach((i) => i.addEventListener('focus', () => { body.querySelector('input[value="hosted"]').checked = true; sync(); }));
    sync();
    body.querySelector('[data-test]').addEventListener('click', async () => {
      const out = body.querySelector('[data-test-result]');
      const base = body.querySelector('[data-url]').value.trim();
      if (!base) { out.innerHTML = '<div class="callout warn">Enter the address first.</div>'; return; }
      out.innerHTML = '<div class="muted">' + PB.icon('loader', 14) + ' Testing…</div>';
      try {
        const r = await PB.api('/api/models/test', { method: 'POST', body: { baseUrl: base, apiKey: body.querySelector('[data-key]').value, model: body.querySelector('[data-model]').value.trim() } });
        body.querySelector('#w-models').innerHTML = (r.models || []).map((m) => '<option value="' + esc(m) + '">').join('');
        out.innerHTML = '<div class="callout ' + (r.ok ? 'ok' : 'bad') + '">' + (r.ok ? PB.icon('check-circle', 14) + ' ' + esc(r.message || 'It answers.') + (r.models && r.models.length ? ' ' + r.models.length + ' model(s) available.' : '') : PB.icon('x-circle', 14) + ' ' + esc(r.message || 'No answer.')) + '</div>';
      } catch (e) { out.innerHTML = '<div class="callout bad">' + esc(e.message) + '</div>'; }
    });
    // discovery of local services
    try {
      const r = await PB.api('/api/models/discover');
      wizard.found = (r.sources || []).filter((s) => s.base_url && s.local && (s.models || []).length);
      const desc = body.querySelector('[data-found-desc]'), list = body.querySelector('[data-found-list]');
      if (!wizard.found.length) { desc.textContent = 'None found right now. Start Ollama, LM Studio, llama.cpp or vLLM and press Back and Next to look again, or choose another option.'; }
      else {
        desc.textContent = 'Found on this computer:';
        list.innerHTML = wizard.found.map((s, i) => '<label class="inline"><input type="radio" name="wfound" value="' + esc(s.base_url) + '" ' + (i === 0 ? 'checked' : '') + '> ' + esc(s.note || s.base_url) + ' <span class="muted">(' + s.models.length + ' model' + (s.models.length === 1 ? '' : 's') + (s.models.length <= 4 ? ': ' + esc(s.models.join(', ')) : '') + ')</span></label>').join('');
        list.querySelectorAll('input').forEach((i) => i.addEventListener('change', () => { body.querySelector('input[value="found"]').checked = true; sync(); }));
        if (d.model.mode === 'demo') { body.querySelector('input[value="found"]').checked = true; sync(); }
      }
    } catch (e) { body.querySelector('[data-found-desc]').textContent = 'The search failed: ' + e.message; }
  };
  wizard.step4 = function (body, d) {
    const presets = (PB.boot.permissionPresets || []).filter((p) => p.id !== 'all');
    body.innerHTML = '<h1>What may iTailor do without asking?</h1><p>Reading your files and running code inside the project folder are always allowed; that is the point. This is about the rest: installing packages, commands that change things, the network.</p><div class="option-list">' +
      presets.map((p) => '<label class="option ' + (d.permissionPreset === p.id ? 'selected' : '') + '"><input type="radio" name="wpreset" value="' + esc(p.id) + '" ' + (d.permissionPreset === p.id ? 'checked' : '') + '><div><div class="title">' + esc(p.name) + '</div><div class="desc">' + esc(p.description) + '</div></div></label>').join('') +
      '</div><p class="muted small" style="margin-top:10px">When iTailor asks, the question appears inside the patch with the exact action and three buttons: Allow once, Always in this run, Don\'t allow. No answer counts as "Don\'t allow".</p>';
    body.querySelectorAll('input[name="wpreset"]').forEach((r) => r.addEventListener('change', () => body.querySelectorAll('.option').forEach((o) => o.classList.toggle('selected', o.querySelector('input').checked))));
  };
  wizard.step5 = function (body, d) {
    const modelText = d.model.mode === 'demo' ? 'the demo model (no real answers yet)' : (d.model.mode === 'found' ? 'a service on this computer at ' + d.model.baseUrl : 'the hosted service at ' + d.model.baseUrl);
    const preset = (PB.boot.permissionPresets || []).find((p) => p.id === d.permissionPreset) || {};
    body.innerHTML = '<h1>Ready' + (d.userName ? ', ' + esc(d.userName) : '') + '</h1><dl class="kv"><dt>Look</dt><dd>' + esc(d.look) + ', ' + esc(d.theme) + ' theme</dd><dt>Projects</dt><dd class="mono">' + esc(d.projectsDir || PB.boot.app.projectsDir) + '</dd><dt>Model</dt><dd>' + esc(modelText) + '</dd><dt>Permissions</dt><dd>' + esc(preset.name || d.permissionPreset) + '</dd></dl>' +
      '<label class="inline" style="margin-top:16px"><input type="checkbox" data-sample ' + (d.createSample ? 'checked' : '') + '> Create a sample project with a small dataset and three example patches (recommended)</label>' +
      '<p class="muted small" style="margin-top:14px">Press Finish to save. You can change any of this in Settings, and Help explains the screen.</p>';
  };
  wizard.finish = async function (card) {
    const d = wizard.data;
    const note = card.querySelector('[data-note]');
    const next = card.querySelector('[data-next]');
    next.disabled = true;
    note.innerHTML = PB.icon('loader', 14) + ' Saving…';
    try {
      const r = await PB.api('/api/setup', { method: 'POST', body: { userName: d.userName, look: d.look, theme: d.theme, projectsDir: d.projectsDir, model: d.model, permissionPreset: d.permissionPreset, createSample: d.createSample } });
      PB.config = r.config;
      PB.state.model = r.model;
      PB.ui.toast('Patchbook is set up.', 'ok');
      if (r.sample && r.sample.error) PB.ui.toast('The sample project could not be created: ' + r.sample.error, 'warn');
      document.getElementById('wizard').classList.add('hidden');
      PB.app.enterWorkbench(r.sample && r.sample.id ? r.sample.id : '');
    } catch (e) {
      note.textContent = '';
      next.disabled = false;
      PB.ui.toast('Setup could not be saved: ' + e.message, 'bad');
    }
  };
})();
