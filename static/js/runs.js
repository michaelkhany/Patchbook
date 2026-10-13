// Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
// Running cells: start, follow the live event stream, show progress in plain language, answer questions, stop.
(function () {
  'use strict';
  const PB = window.PB;
  const { esc, el, fmtSeconds, fmtClock } = PB.util;
  const runs = PB.runs = { current: null, timer: null };

  const STAGES = [
    { id: 'prepare', label: 'Preparing' }, { id: 'write', label: 'Writing code' }, { id: 'run', label: 'Running' },
    { id: 'check', label: 'Checking' }, { id: 'finish', label: 'Finished' },
  ];
  const STAGE_INDEX = {}; STAGES.forEach((s, i) => { STAGE_INDEX[s.id] = i; });

  // The stage follows the latest event, forwards or backwards: a repair goes back to "Writing code".
  function stageOf(ev) {
    const m = String(ev.message || '').toLowerCase();
    switch (ev.type) {
      case 'patchbook_start': case 'run_start': return 'prepare';
      case 'think':
        if (m.includes('fixing') || m.includes('repair') || m.includes('revis')) return 'write';
        if (m.includes('writing') || m.includes('thinking')) return 'write';
        if (m.includes('plan') || m.includes('understand') || m.includes('discover') || m.includes('model selection') || m.includes('replan')) return 'prepare';
        return null;
      case 'plan': return 'prepare';
      case 'tool_call': case 'step_start': case 'output': return 'run';
      case 'observe':
        if (m.includes('script failed') || m.includes('revising')) return 'write';
        return (m.includes('check') || m.includes('verified') || m.includes('ran cleanly') || m.includes('must produce')) ? 'check' : null;
      case 'step_done': return 'check';
      case 'final': case 'run_end': case 'patchbook_end': return 'finish';
      default: return null;
    }
  }
  // What program is running: from tool calls, streamed output and results. Generic over every tool iTailor has.
  function describeCall(ev) {
    const a = ev.args || {};
    switch (ev.name) {
      case 'RunCode': return { kind: 'script', what: (a.language || 'script') + ' script' + (a.lines ? ' (' + a.lines + ' lines)' : '') };
      case 'Shell': return { kind: 'command', what: String(a.command || ev.message || 'command') };
      case 'Install': return { kind: 'install', what: (a.manager || 'package manager') + ': ' + ((a.packages || (a.package ? [a.package] : [])).join(', ') || '?') };
      case 'OpenWith': return { kind: 'application', what: String(a.app || a.name || ev.message || 'application') };
      case 'WebSearch': case 'WebFetch': return { kind: 'web', what: String(a.query || a.url || ev.name) };
      default: return ev.name ? { kind: 'tool', what: ev.name + (a.path || a.pattern ? ': ' + (a.path || a.pattern) : '') } : null;
    }
  }
  const ERROR_LINE = /\b(error|exception|traceback|fatal|failed)\b/i, WARNING_LINE = /\bwarn(ing)?\b/i;
  function trackProcess(cur, ev) {
    cur.processes = cur.processes || [];
    const running = () => cur.processes.filter((p) => p.status === 'running');
    if (ev.type === 'tool_call') {
      const d = describeCall(ev);
      if (d) cur.processes.push(Object.assign(d, { name: ev.name, startedAt: ev.ts ? ev.ts * 1000 : Date.now(), status: 'running', output: '', errors: 0, warnings: 0 }));
    } else if (ev.type === 'output') {
      const p = running().slice(-1)[0];
      if (p) {
        const text = String(ev.message || '');
        p.output = (p.output + text).slice(-3000);
        text.split('\n').forEach((line) => { if (ERROR_LINE.test(line) || ev.stream === 'stderr' && line.trim()) p.errors += ERROR_LINE.test(line) ? 1 : 0; if (WARNING_LINE.test(line)) p.warnings += 1; });
      }
    } else if (ev.type === 'tool_result') {
      const p = running().reverse().find((x) => x.name === ev.name) || running().slice(-1)[0];
      if (p) { p.status = ev.ok === false ? 'failed' : 'done'; p.endedAt = ev.ts ? ev.ts * 1000 : Date.now(); p.summary = String(ev.message || ''); }
    } else if (ev.type === 'observe' && /^The script (ran|failed)/.test(String(ev.message || ''))) {
      const p = running().reverse().find((x) => x.name === 'RunCode');
      if (p) { p.status = /^The script ran/.test(ev.message) ? 'done' : 'failed'; p.endedAt = ev.ts ? ev.ts * 1000 : Date.now(); p.summary = String(ev.message || ''); }
    } else if (ev.type === 'patchbook_strategy' || ev.type === 'patchbook_end' || ev.type === 'patchbook_attempt') {
      running().forEach((p) => { p.status = 'done'; p.endedAt = Date.now(); });
    }
  }
  runs.processesHtml = function (cur, onlyRunning) {
    const list = (cur.processes || []).filter((p) => !onlyRunning || p.status === 'running');
    if (!list.length) return '';
    const ICON = { running: 'loader', done: 'check-circle', failed: 'x-circle' };
    return '<ul class="procs">' + list.slice(-8).map((p) => {
      const secs = ((p.endedAt || Date.now()) - p.startedAt) / 1000;
      const tail = p.output ? p.output.trim().split('\n').slice(-4).join('\n') : '';
      const waiting = p.status === 'running' && cur.waiting;
      return '<li class="' + (p.status === 'running' ? 'running' : (p.status === 'failed' ? 'bad' : 'ok')) + '"><span class="ic">' + PB.icon(waiting ? 'help-circle' : (ICON[p.status] || 'circle'), 13) + '</span><span class="grow"><span class="what">' + esc(p.kind) + ': ' + esc(p.what) + '</span> <span class="muted">' +
        (p.status === 'running' ? (waiting ? 'waiting for your answer' : 'running for ' + fmtSeconds(secs)) : (p.status === 'failed' ? 'failed' : 'finished') + ' after ' + fmtSeconds(secs)) +
        (p.errors ? ' · <span style="color:var(--bad)">' + p.errors + ' error line' + (p.errors === 1 ? '' : 's') + '</span>' : '') + (p.warnings ? ' · <span style="color:var(--warn)">' + p.warnings + ' warning' + (p.warnings === 1 ? '' : 's') + '</span>' : '') + '</span>' +
        (p.summary && p.status !== 'running' ? '<div class="muted small">' + esc(p.summary.slice(0, 160)) + '</div>' : '') + (tail ? '<div class="tail">' + esc(tail) + '</div>' : '') + '</span></li>';
    }).join('') + '</ul>';
  };
  function plain(ev) {
    // One short, plain sentence per event for the Progress panel and the cell strip.
    const m = String(ev.message || '');
    switch (ev.type) {
      case 'patchbook_start': return 'Starting' + (ev.demo ? ' (demo model)' : '') + (ev.effort ? ', ' + ev.effort + ' effort' : '');
      case 'patchbook_strategy': return m;
      case 'patchbook_attempt': return m;
      case 'patchbook_auto': return m;
      case 'run_start': return 'Run started';
      case 'think':
        if (/^Model selection:/i.test(m)) return 'Choosing a model' + (PB.isPro() ? ': ' + m.replace(/^Model selection:\s*/i, '').slice(0, 160) : '');
        return m.replace(/…$/, '').replace(/^iTailor is /, '') || 'Thinking';
      case 'plan': return m;
      case 'step_start': return m;
      case 'step_done': return m || 'Step finished';
      case 'tool_call': return m || ('Using ' + (ev.name || 'a tool'));
      case 'tool_result': return m;
      case 'observe': return m;
      case 'oversight': return ev.requestType === 'consult' ? 'Waiting for your answer: ' + (ev.question || '') : 'Waiting for your permission: ' + (ev.summary || '');
      case 'permission_request': return 'Asking for permission: ' + m;
      case 'consult_request': return 'Asking you: ' + m;
      case 'decision': return (ev.allowed === false || /denied|refused|blocked/i.test(m) ? 'Not allowed: ' : 'Decision: ') + m;
      case 'consult_answer': return 'Your answer: ' + m;
      case 'lesson': return 'Remembered: ' + m;
      case 'error': return 'Problem: ' + m;
      case 'final': return m;
      case 'run_end': return m;
      case 'patchbook_end': return ({ done: 'Finished', failed: 'Failed', partial: 'Partly done', stopped: 'Stopped' }[ev.status] || ev.status);
      default: return '';
    }
  }
  const STEP_ICON = { think: 'message', plan: 'list', step_start: 'chevron-right', step_done: 'check-circle', tool_call: 'play', tool_result: 'check', observe: 'check',
    oversight: 'help-circle', permission_request: 'shield', consult_request: 'help-circle', decision: 'shield', consult_answer: 'user', lesson: 'book', error: 'x-circle', final: 'check-circle', run_end: 'check-circle', patchbook_end: 'check-circle', patchbook_start: 'play', run_start: 'play',
    patchbook_strategy: 'layers', patchbook_attempt: 'check-circle', patchbook_auto: 'shield' };
  runs.plain = plain;

  // ---------------------------------------------------------------- start
  runs.runCell = async function (cellId, opts) {
    opts = opts || {};
    if (PB.state.activeRun) { PB.ui.toast('A patch is already running. Wait for it or press Stop.', 'warn'); return; }
    const cell = PB.notebook.cell(cellId);
    if (!cell) return;
    const pid = PB.state.project.id, nid = PB.state.patchbook.id;
    await PB.notebook.saveNow();
    cell.status = 'running'; cell.steps = []; cell.result = cell.result; cell.runId = '';
    PB.notebook.renderGutter(cell); PB.notebook.updateBadge(cell); PB.notebook.renderOutput(cell);
    const body = { text: cell.text, engine: opts.engine || undefined, effort: opts.effort || undefined, checks: opts.checks || undefined, mode: opts.mode || undefined, model: opts.model || undefined };
    let r;
    try {
      r = await PB.api('/api/projects/' + encodeURIComponent(pid) + '/patchbooks/' + encodeURIComponent(nid) + '/cells/' + encodeURIComponent(cellId) + '/run', { method: 'POST', body });
    } catch (e) {
      cell.status = cell.result ? 'stale' : 'idle';
      PB.notebook.renderGutter(cell); PB.notebook.updateBadge(cell);
      PB.ui.toast(e.message, e.status === 409 ? 'warn' : 'bad');
      PB.state.queue = [];
      return;
    }
    cell.runId = r.run.id;
    runs.attach(r.run, cellId);
  };
  runs.runMany = function (ids) {
    if (!ids.length) return;
    if (PB.state.activeRun) { PB.ui.toast('A patch is already running. Wait for it or press Stop.', 'warn'); return; }
    PB.state.queue = ids.slice(1);
    ids.slice(1).forEach((id) => { const c = PB.notebook.cell(id); if (c) { c.status = 'queued'; PB.notebook.renderGutter(c); PB.notebook.updateBadge(c); } });
    runs.runCell(ids[0]);
  };
  runs.recover = async function () {
    // After a page reload: re-attach to a run that is still going in this Patchbook.
    try {
      const r = await PB.api('/api/runs/active');
      const mine = (r.runs || []).find((x) => PB.state.patchbook && x.patchbookId === PB.state.patchbook.id);
      if (mine) { const cell = PB.notebook.cell(mine.cellId); if (cell) { cell.status = 'running'; PB.notebook.renderGutter(cell); PB.notebook.updateBadge(cell); } runs.attach(mine, mine.cellId); }
    } catch (e) { /* nothing to recover */ }
  };

  // ---------------------------------------------------------------- follow
  runs.attach = function (run, cellId) {
    const cur = runs.current = { id: run.id, cellId, startedAt: run.started ? run.started * 1000 : Date.now(), stage: 'prepare', steps: [], events: [], questions: {}, output: '', demo: !!run.demo, engine: run.engine, status: 'running', source: null };
    PB.state.activeRun = cur;
    PB.notebook.updateRunButtons();
    PB.panels.busy('progress', true);
    runs.renderCellStrip();
    runs.renderProgress();
    runs.renderEvents(true);
    runs.tick();
    runs.timer = setInterval(runs.tick, 1000);
    const source = new EventSource('/api/runs/' + encodeURIComponent(run.id) + '/events');
    cur.source = source;
    source.onmessage = (m) => { let ev; try { ev = JSON.parse(m.data); } catch (e) { return; } runs.handle(ev); };
    source.onerror = () => { /* the stream closes when the run ends; a reload re-attaches */ };
    PB.bus.emit('run-start', cur);
  };
  runs.tick = function () {
    const cur = runs.current;
    if (!cur) return;
    const elapsed = fmtSeconds((Date.now() - cur.startedAt) / 1000);
    document.querySelectorAll('[data-elapsed="' + cur.id + '"]').forEach((e) => { e.textContent = elapsed; });
    Object.values(cur.questions).forEach((q) => { const left = Math.max(0, Math.round(q.deadline - Date.now() / 1000)); document.querySelectorAll('[data-qtimeout="' + q.requestId + '"]').forEach((e) => { e.textContent = left > 0 ? 'No answer in ' + fmtSeconds(left) + ' counts as "Don\'t allow"' : 'Timed out'; }); });
  };
  runs.handle = function (ev) {
    const cur = runs.current;
    if (!cur) return;
    cur.events.push(ev);
    if (cur.events.length > 3000) cur.events.splice(0, cur.events.length - 3000);
    if (ev.type === 'patchbook_strategy') {
      // A new approach starts: the stage chips begin again.
      cur.stage = 'prepare';
      cur.approach = { index: ev.index, total: ev.total, label: ev.label, round: ev.round || 1, strategy: ev.strategy };
      cur.output = '';
      cur.repairs = 0;
    } else {
      const stage = stageOf(ev);
      if (stage && cur.stage !== 'finish') cur.stage = stage;
      if (ev.type === 'think' && /fixing|repair/.test(String(ev.message || '').toLowerCase())) cur.repairs = (cur.repairs || 0) + 1;
    }
    trackProcess(cur, ev);
    if (ev.type === 'output') { cur.output += String(ev.message || ''); if (cur.output.length > 20000) cur.output = cur.output.slice(-20000); }
    const text = plain(ev);
    if (text && ['patchbook_start', 'patchbook_strategy', 'patchbook_attempt', 'patchbook_auto', 'think', 'plan', 'step_start', 'step_done', 'tool_call', 'observe', 'oversight', 'decision', 'consult_answer', 'lesson', 'error', 'final', 'patchbook_end'].includes(ev.type)) {
      if (ev.type === 'oversight' && ev.auto) { /* answered automatically: the patchbook_auto event tells it */ } else {
      const kind = ev.type === 'error' ? 'bad' : (['observe', 'step_done', 'final'].includes(ev.type) ? 'ok' : (ev.type === 'oversight' ? 'ask' : (ev.type === 'patchbook_attempt' ? (ev.status === 'done' ? 'ok' : 'bad') : (ev.type === 'patchbook_auto' ? (ev.decision === 'allow' ? 'ok' : 'bad') : ''))));
      cur.steps.push({ at: ev.ts ? ev.ts * 1000 : Date.now(), type: ev.type, text, kind });
      if (cur.steps.length > 120) cur.steps.shift();
      cur.lastText = ev.type === 'patchbook_strategy' ? 'Starting' : text;
      }
    }
    if (ev.type === 'oversight' && !ev.auto) { cur.questions[ev.requestId] = Object.assign({ deadline: Date.now() / 1000 + ((PB.boot.itailorTimeouts || {}).permission || 300) }, ev); cur.waiting = true; runs.renderQuestions(); PB.ui.toast(ev.requestType === 'consult' ? 'iTailor has a question for you.' : 'iTailor asks for your permission.', 'warn'); }
    if (ev.type === 'decision' || ev.type === 'consult_answer') { cur.waiting = Object.keys(cur.questions).length > 0; }
    if (ev.type === 'patchbook_end') { runs.finish(ev); return; }
    if (ev.type === 'stream_end') { if (cur.source) cur.source.close(); if (cur.status === 'running') runs.finish({ status: ev.status || 'failed', cell: null }); return; }
    runs.renderCellStrip();
    runs.renderProgress();
    runs.appendEvent(ev);
    const live = (cur.processes || []).filter((p) => p.status === 'running').slice(-1)[0];
    PB.ui.status.mid(PB.icon('loader', 13) + ' ' + esc(cur.lastText || 'Working') + (live ? ' <span class="muted">· running: ' + esc(live.what) + '</span>' : '') + ' <span class="muted">(' + esc(STAGES[STAGE_INDEX[cur.stage]].label.toLowerCase()) + ')</span>', true);
  };
  runs.finish = function (ev) {
    const cur = runs.current;
    if (!cur) return;
    cur.status = ev.status || 'failed';
    cur.stage = 'finish';
    cur.questions = {};
    cur.finishedAt = Date.now();
    if (cur.source) cur.source.close();
    clearInterval(runs.timer); runs.timer = null;
    const cell = PB.notebook.cell(cur.cellId);
    if (cell) {
      if (ev.cell) { Object.assign(cell, ev.cell); if (PB.state.patchbook) PB.state.patchbook.executionCounter = Math.max(PB.state.patchbook.executionCounter || 0, ev.cell.executionCount || 0); }
      else { cell.status = cur.status; cell.result = ev.result || cell.result; }
      PB.notebook.replaceCell(cell);
    }
    PB.state.activeRun = null;
    PB.state.lastRun = cur;
    if (ev.result && ev.result.model && !ev.result.demo) PB.state.lastModel = ev.result.model;
    runs.current = null;
    PB.notebook.updateRunButtons();
    PB.notebook.markSaved(PB.notebook.saveState);
    PB.panels.busy('progress', false);
    runs.renderProgress();
    runs.appendEvent(ev);
    const label = { done: 'Finished', failed: 'Failed', partial: 'Partly done', stopped: 'Stopped' }[cur.status] || cur.status;
    PB.ui.status.mid(label + ' · ' + fmtSeconds((cur.finishedAt - cur.startedAt) / 1000), false);
    setTimeout(() => { if (!PB.state.activeRun) PB.ui.status.mid(''); }, 8000);
    PB.bus.emit('run-end', cur);
    if (cur.status === 'failed' && !PB.state.queue.length) PB.ui.toast('The patch did not finish. The cell shows what went wrong.', 'bad');
    if (cur.status === 'stopped') { PB.state.queue.forEach((id) => { const c = PB.notebook.cell(id); if (c && c.status === 'queued') { c.status = c.result ? 'stale' : 'idle'; PB.notebook.renderGutter(c); PB.notebook.updateBadge(c); } }); PB.state.queue = []; }
    if (PB.state.queue.length) { const next = PB.state.queue.shift(); setTimeout(() => runs.runCell(next), 250); }
  };
  runs.stop = async function () {
    const cur = runs.current;
    if (!cur) return;
    PB.state.queue.forEach((id) => { const c = PB.notebook.cell(id); if (c && c.status === 'queued') { c.status = c.result ? 'stale' : 'idle'; PB.notebook.renderGutter(c); PB.notebook.updateBadge(c); } });
    PB.state.queue = [];
    try { await PB.api('/api/runs/' + encodeURIComponent(cur.id) + '/stop', { method: 'POST', body: {} }); PB.ui.status.mid(PB.icon('loader', 13) + ' Stopping…', true); }
    catch (e) { PB.ui.toast(e.message, 'bad'); }
  };
  runs.answer = async function (requestId, body) {
    const cur = runs.current;
    if (!cur) return;
    try { await PB.api('/api/runs/' + encodeURIComponent(cur.id) + '/answer', { method: 'POST', body: Object.assign({ requestId }, body) }); }
    catch (e) { PB.ui.toast(e.message, 'bad'); throw e; }
    delete cur.questions[requestId];
    cur.waiting = Object.keys(cur.questions).length > 0;
    runs.renderQuestions();
  };

  // ---------------------------------------------------------------- views: cell strip
  runs.approachHtml = function (cur) {
    if (!cur.approach) return '';
    const a = cur.approach;
    return '<div class="approach">' + PB.icon('layers', 12) + ' ' + (a.index ? 'Approach ' + a.index + ' of ' + a.total + ': ' : '') + esc(a.label) + (a.round > 1 ? ' <span class="muted">(round ' + a.round + ')</span>' : '') + (cur.repairs ? ' <span class="muted">· repair ' + cur.repairs + '</span>' : '') + '</div>';
  };
  runs.stripHtml = function (cur) {
    const idx = STAGE_INDEX[cur.stage];
    const chips = STAGES.map((s, i) => '<span class="stage ' + (i < idx || cur.status !== 'running' ? 'done' : (i === idx ? (cur.waiting ? 'waiting' : 'active') : '')) + '">' + (i < idx ? PB.icon('check', 12) : (i === idx && cur.status === 'running' ? PB.icon('loader', 12) : '')) + esc(s.label) + '</span>').join('');
    return runs.approachHtml(cur) + '<div class="stages">' + chips + '</div><div class="progress-line"><span class="msg">' + esc(cur.lastText || 'Starting') + '</span><span class="elapsed" data-elapsed="' + esc(cur.id) + '">' + fmtSeconds((Date.now() - cur.startedAt) / 1000) + '</span><button class="small" data-stop>' + PB.icon('stop', 12) + ' Stop</button></div><div class="bar indeterminate"><div class="bar-fill"></div></div>';
  };
  runs.renderCellStrip = function () {
    const cur = runs.current;
    if (!cur) return;
    const art = PB.notebook.cellEls[cur.cellId];
    if (!art) return;
    const strip = art.querySelector('.cell-progress');
    strip.classList.remove('hidden');
    strip.innerHTML = runs.stripHtml(cur);
    strip.querySelector('[data-stop]').addEventListener('click', () => runs.stop());
    const procs = runs.processesHtml(cur, true);
    if (procs) strip.appendChild(el('<div class="running-now">' + procs + '</div>'));
    if (cur.output && PB.isPro()) {
      const live = el('<div class="out-stdout" style="margin-top:8px;max-height:160px"></div>');
      live.textContent = cur.output.slice(-4000);
      strip.appendChild(live);
      live.scrollTop = live.scrollHeight;
    }
  };
  runs.questionCard = function (q) {
    const card = el('<div class="qcard"></div>');
    if (q.requestType === 'consult') {
      card.innerHTML = '<h4>' + PB.icon('help-circle', 16) + ' iTailor needs your answer</h4><div class="why">' + esc(q.question) + '</div>' + (q.why ? '<div class="meta">' + esc(q.why) + '</div>' : '') +
        '<div class="actions">' + (q.options || []).map((o) => '<button class="opt">' + esc(o) + '</button>').join('') + '<input type="text" class="free" placeholder="or type an answer" style="width:220px"><button class="primary" data-send>Answer</button><button data-skip title="iTailor continues with its most careful assumption">No answer</button><span class="timeout" data-qtimeout="' + esc(q.requestId) + '"></span></div>';
      card.querySelectorAll('.opt').forEach((b) => b.addEventListener('click', () => runs.answer(q.requestId, { answer: b.textContent })));
      card.querySelector('[data-send]').addEventListener('click', () => { const v = card.querySelector('.free').value.trim(); if (v) runs.answer(q.requestId, { answer: v }); });
      card.querySelector('.free').addEventListener('keydown', (e) => { if (e.key === 'Enter') card.querySelector('[data-send]').click(); });
      card.querySelector('[data-skip]').addEventListener('click', () => runs.answer(q.requestId, { answer: null }));
    } else {
      const risk = q.risk && q.risk.level ? '<span class="badge ' + (/high/.test(q.risk.level) ? 'bad' : (q.risk.level === 'moderate' ? 'warn' : '')) + '">risk: ' + esc(String(q.risk.level).replace('_', ' ')) + '</span>' : '';
      const rec = q.recommendation || null;
      const recHtml = rec ? '<div class="recommend ' + (rec.decision === 'deny' ? 'deny' : (rec.decision === 'allow' && rec.confident ? '' : 'unsure')) + '">' + PB.icon('thumbs-up', 13) + ' Recommended: ' + esc(rec.label) + ' <span class="muted">— ' + esc(rec.reason) + '</span></div>' : '';
      const primary = rec && rec.decision === 'deny' ? 'deny' : 'allow';
      card.innerHTML = '<h4>' + PB.icon('shield', 16) + ' May iTailor do this?</h4><div class="why"><b>' + esc(q.summary) + '</b></div>' + (q.detail ? '<div class="why">' + esc(q.detail) + '</div>' : '') + (q.command ? '<code>' + esc(q.command) + '</code>' : '') +
        '<div class="meta">' + esc(q.kind || '') + (q.tool ? ' · ' + esc(q.tool) : '') + ' ' + risk + '</div>' + recHtml + (q.hints || []).map((h) => '<div class="meta">' + PB.icon('book', 12) + ' ' + esc(h) + '</div>').join('') +
        '<div class="actions"><button class="' + (primary === 'allow' ? 'primary' : '') + '" data-d="allow">Allow once</button><button data-d="always" title="Allow this kind of action for the rest of this run">Always in this run</button><button class="' + (primary === 'deny' ? 'primary' : '') + '" data-d="deny">Don\'t allow</button><span class="timeout" data-qtimeout="' + esc(q.requestId) + '"></span></div>' +
        '<label class="inline small" style="margin:6px 0 0"><input type="checkbox" data-remember> Don\'t ask again for this kind in this project <span class="muted">(adds a standing allow rule to the project)</span></label>';
      card.querySelectorAll('[data-d]').forEach((b) => b.addEventListener('click', () => {
        const remember = card.querySelector('[data-remember]').checked && b.dataset.d !== 'deny';
        runs.answer(q.requestId, { decision: b.dataset.d, remember }).then(() => { if (remember) PB.ui.toast('A standing allow rule for this kind of action was added to the project.', 'ok'); });
      }));
    }
    return card;
  };
  runs.renderQuestions = function () {
    const cur = runs.current;
    const art = cur ? PB.notebook.cellEls[cur.cellId] : null;
    if (art) {
      const box = art.querySelector('.cell-questions');
      box.innerHTML = '';
      Object.values(cur.questions).forEach((q) => box.appendChild(runs.questionCard(q)));
      if (Object.keys(cur.questions).length) box.scrollIntoView({ block: 'nearest' });
    }
    runs.renderCellStrip();
    runs.renderProgress();
    runs.tick();
  };

  // ---------------------------------------------------------------- Progress panel
  PB.panels.register({
    id: 'progress', title: 'Progress', icon: 'activity', dock: 'right', order: 10,
    description: 'What iTailor is doing right now, step by step, in plain language.',
    defaultVisible: { simple: true, professional: true },
    render(body) { body.innerHTML = ''; runs.renderProgress(); },
  });
  runs.renderProgress = function () {
    const inst = PB.panels.instances.progress;
    if (!inst) return;
    const cur = runs.current || PB.state.lastRun;
    const body = inst.body;
    if (!cur) { body.innerHTML = '<div class="empty">' + PB.icon('activity', 28) + 'Nothing is running. Press Run on a patch and watch its progress here.</div>'; return; }
    const cell = PB.notebook.cell(cur.cellId);
    const index = cell ? PB.notebook.cellIndex(cur.cellId) : -1;
    const running = cur.status === 'running';
    let html = '<div class="progress-cell"><b>' + esc(running ? 'Running' : ({ done: 'Finished', failed: 'Failed', partial: 'Partly done', stopped: 'Stopped' }[cur.status] || cur.status)) + '</b>' + (cell ? ': ' + esc(PB.util.cellLabel(cell, index)) : '') + (cur.demo ? ' <span class="badge warn">demo model</span>' : '') + '</div>';
    if (running) html += runs.stripHtml(cur);
    else html += (cur.approach && cur.approach.total > 1 ? runs.approachHtml(cur) : '') + '<div class="muted small">' + fmtSeconds(((cur.finishedAt || Date.now()) - cur.startedAt) / 1000) + ' · ' + fmtClock(cur.finishedAt || Date.now()) + '</div>';
    html += '<div class="questions"></div>';
    const procs = runs.processesHtml(cur, false);
    if (procs) html += '<div class="out-label" style="margin-top:8px">' + (running && (cur.processes || []).some((p) => p.status === 'running') ? 'Running now' : 'Programs run') + '</div>' + procs;
    html += '<ul class="steps-list">' + cur.steps.slice(-60).map((s) => '<li class="' + esc(s.kind) + '"><span class="t">' + fmtClock(s.at) + '</span><span class="ic">' + PB.icon(STEP_ICON[s.type] || 'circle', 13) + '</span><span class="grow">' + esc(s.text) + '</span></li>').join('') + '</ul>';
    body.innerHTML = html;
    const stop = body.querySelector('[data-stop]');
    if (stop) stop.addEventListener('click', () => runs.stop());
    const qbox = body.querySelector('.questions');
    if (running) Object.values(cur.questions).forEach((q) => qbox.appendChild(runs.questionCard(q)));
    const list = body.querySelector('.steps-list');
    if (list) list.scrollTop = list.scrollHeight;
    if (cell && running) { const art = PB.notebook.cellEls[cur.cellId]; if (art && !art.querySelector('.cell-progress').innerHTML) runs.renderCellStrip(); }
  };

  // ---------------------------------------------------------------- Events panel (professional)
  PB.panels.register({
    id: 'events', title: 'Events', icon: 'terminal', dock: 'right', order: 20, looks: ['professional'],
    description: 'Every event of the current run, with its raw details.',
    defaultVisible: { simple: false, professional: true },
    render(body) {
      body.classList.add('flush');
      body.innerHTML = '<div class="panel-toolbar"><label class="inline small"><input type="checkbox" data-all ' + (PB.config.eventsShowAll ? 'checked' : '') + '> show usage, output and streamed text</label><button class="small right" data-clear>Clear</button></div><div class="events scroll"></div>';
      body.querySelector('[data-all]').addEventListener('change', (e) => { PB.saveConfig({ eventsShowAll: e.target.checked }); runs.renderEvents(true); });
      body.querySelector('[data-clear]').addEventListener('click', () => { body.querySelector('.events').innerHTML = ''; });
    },
  });
  runs.renderEvents = function (reset) {
    const inst = PB.panels.instances.events;
    if (!inst) return;
    const box = inst.body.querySelector('.events');
    if (reset) box.innerHTML = '';
    const cur = runs.current || PB.state.lastRun;
    if (cur) cur.events.forEach((ev) => runs.appendEvent(ev, true));
  };
  runs.appendEvent = function (ev, quiet) {
    const inst = PB.panels.instances.events;
    if (!inst) return;
    if (!PB.config.eventsShowAll && ['usage', 'delta', 'output', 'heartbeat'].includes(ev.type)) return;
    const box = inst.body.querySelector('.events');
    const extra = Object.assign({}, ev);
    ['seq', 'ts', 'type', 'message', 'n'].forEach((k) => delete extra[k]);
    const detail = Object.keys(extra).length ? '<details><summary>details</summary><pre>' + esc(JSON.stringify(extra, null, 1).slice(0, 6000)) + '</pre></details>' : '';
    const row = el('<div class="ev ' + esc(ev.type) + '"><span class="t">' + esc(ev.type) + '</span>' + esc(String(ev.message || '').slice(0, 600)) + detail + '</div>');
    box.appendChild(row);
    if (box.children.length > 1500) box.removeChild(box.firstChild);
    if (!quiet) box.scrollTop = box.scrollHeight;
  };
})();
