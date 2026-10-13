// Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
// Project manager: the home view, opening and closing projects, create / import / rename / duplicate / delete.
(function () {
  'use strict';
  const PB = window.PB;
  const { esc, el, relTime, plural } = PB.util;
  const projects = PB.projects = { list: [], projectsDir: '' };

  projects.load = async function () {
    const r = await PB.api('/api/projects');
    projects.list = r.projects || [];
    projects.projectsDir = r.projectsDir || '';
    return projects.list;
  };

  projects.open = async function (pid, patchbookId) {
    if (PB.state.activeRun) { PB.ui.toast('A patch is still running. Stop it before switching projects.', 'warn'); return; }
    PB.ui.status.mid(PB.icon('loader', 14) + ' Opening project…', true);
    try {
      const p = await PB.api('/api/projects/' + encodeURIComponent(pid) + '/open', { method: 'POST', body: {} });
      PB.state.project = p;
      PB.state.patchbooks = p.patchbookList || [];
      PB.state.patchbook = null;
      PB.bus.emit('project', p);
      const target = patchbookId && PB.state.patchbooks.some((b) => b.id === patchbookId) ? patchbookId : (PB.state.patchbooks[0] && PB.state.patchbooks[0].id);
      if (target) await PB.notebook.open(target); else await PB.notebook.create();
      PB.runs.recover();
    } catch (e) {
      PB.ui.toast('Could not open the project: ' + e.message, 'bad');
      projects.showHome();
    } finally { PB.ui.status.mid(''); }
  };

  projects.close = function () {
    if (PB.state.activeRun) { PB.ui.toast('A patch is still running. Stop it first.', 'warn'); return; }
    PB.notebook.saveNow();
    PB.state.project = null; PB.state.patchbook = null; PB.state.patchbooks = [];
    PB.saveConfig({ lastProjectId: '' });
    PB.bus.emit('project', null);
    projects.showHome();
  };

  projects.showHome = async function () {
    const center = document.getElementById('center');
    center.innerHTML = '<div class="home"><div class="home-hero"><div class="logo">P</div><div><h1>Projects</h1><p>A project is a folder with your files and your Patchbooks. Open one, or start a new one.</p></div></div>' +
      '<div class="home-actions"><button class="primary" data-new>' + PB.icon('plus') + ' New project</button>' +
      '<button data-sample>' + PB.icon('star') + ' Create the sample project</button>' +
      (PB.isPro() ? '<button data-import>' + PB.icon('folder-open') + ' Open an existing folder…</button>' : '') +
      '<button data-refresh class="ghost">' + PB.icon('refresh') + ' Refresh</button></div><div class="project-list"><div class="muted">Loading…</div></div>' +
      '<p class="muted small" style="margin-top:16px">Projects are stored in <span class="mono" data-dir></span></p></div>';
    center.querySelector('[data-new]').addEventListener('click', () => projects.create());
    center.querySelector('[data-sample]').addEventListener('click', () => projects.createSample());
    const imp = center.querySelector('[data-import]');
    if (imp) imp.addEventListener('click', () => projects.importFolder());
    center.querySelector('[data-refresh]').addEventListener('click', () => projects.showHome());
    PB.ui.status.left(PB.icon('home', 13) + ' Projects');
    PB.bus.emit('view', 'home');
    try { await projects.load(); } catch (e) { center.querySelector('.project-list').innerHTML = '<div class="callout bad">' + esc(e.message) + '</div>'; return; }
    center.querySelector('[data-dir]').textContent = projects.projectsDir;
    const list = center.querySelector('.project-list');
    list.innerHTML = '';
    if (!projects.list.length) {
      list.innerHTML = '<div class="empty">' + PB.icon('folder', 32) + 'No projects yet. Create a new one, or create the sample project to see how Patchbook works.</div>';
      return;
    }
    projects.list.forEach((p) => {
      const card = el('<div class="project-card" role="button" tabindex="0"><span class="ic">' + PB.icon(p.sample ? 'star' : 'folder', 22) + '</span><div class="grow">' +
        '<div class="name">' + esc(p.name) + (p.external ? ' <span class="badge">linked folder</span>' : '') + '</div>' + (p.description ? '<div class="desc">' + esc(p.description) + '</div>' : '') +
        '<div class="meta">' + plural(p.patchbooks, 'Patchbook') + (p.lastOpened ? ' · opened ' + relTime(p.lastOpened) : '') + (PB.isPro() ? ' · <span class="mono">' + esc(p.path) + '</span>' : '') + '</div></div>' +
        '<div class="acts"><button class="icon-btn" data-more title="More">' + PB.icon('more') + '</button></div></div>');
      card.addEventListener('click', (e) => { if (e.target.closest('[data-more]')) return; projects.open(p.id); });
      card.addEventListener('keydown', (e) => { if (e.key === 'Enter') projects.open(p.id); });
      card.querySelector('[data-more]').addEventListener('click', (e) => { e.stopPropagation(); const r = e.currentTarget.getBoundingClientRect(); projects.menu(p, r.left, r.bottom + 4); });
      card.addEventListener('contextmenu', (e) => { e.preventDefault(); projects.menu(p, e.clientX, e.clientY); });
      list.appendChild(card);
    });
  };

  projects.menu = function (p, x, y) {
    PB.ui.popup([
      { label: 'Open', icon: 'folder-open', action: () => projects.open(p.id) },
      { label: 'Rename…', icon: 'edit', action: () => projects.rename(p) },
      { label: 'Duplicate', icon: 'copy', action: () => projects.duplicate(p) },
      { label: 'Show folder', icon: 'external-link', action: () => PB.api('/api/open-folder', { method: 'POST', body: { path: p.path } }).catch((e) => PB.ui.toast(e.message, 'bad')) },
      { sep: true },
      { label: p.external ? 'Remove from the list…' : 'Delete…', icon: 'trash', action: () => projects.remove(p) },
    ], x, y);
  };

  projects.create = function () {
    const body = el('<div><label>Name<input type="text" placeholder="e.g. Sales analysis 2026"></label><label>What is it about? (optional)<input type="text" data-desc placeholder="One sentence; iTailor reads it at the start of every run"></label></div>');
    const name = body.querySelector('input');
    PB.ui.dialog({ title: 'New project', icon: 'folder-plus', body, buttons: [{ label: 'Cancel' }, { label: 'Create', primary: true, action: async () => {
      if (!name.value.trim()) { name.focus(); return false; }
      const p = await PB.api('/api/projects', { method: 'POST', body: { name: name.value.trim(), description: body.querySelector('[data-desc]').value.trim() } });
      PB.ui.toast('Project "' + p.name + '" created', 'ok');
      projects.open(p.id);
    } }] });
  };
  projects.createSample = async function () {
    try {
      PB.ui.status.mid(PB.icon('loader', 14) + ' Creating the sample project…', true);
      const p = await PB.api('/api/projects', { method: 'POST', body: { sample: true } });
      PB.ui.toast('Sample project created', 'ok');
      projects.open(p.id);
    } catch (e) { PB.ui.toast(e.message, 'bad'); } finally { PB.ui.status.mid(''); }
  };
  projects.importFolder = function () {
    const body = el('<div><p>Patchbook will use that folder as a project: it adds a small <span class="mono">patchbook-project.json</span>, a <span class="mono">patchbooks/</span> folder and an <span class="mono">ITAILOR.md</span>. Nothing else is changed.</p><label>Folder path<input type="text" placeholder="C:\\Users\\me\\Documents\\my-analysis"></label><label>Name (optional)<input type="text" data-name></label></div>');
    const path = body.querySelector('input');
    PB.ui.dialog({ title: 'Open an existing folder as a project', icon: 'folder-open', body, buttons: [{ label: 'Cancel' }, { label: 'Open', primary: true, action: async () => {
      if (!path.value.trim()) { path.focus(); return false; }
      const p = await PB.api('/api/projects/import', { method: 'POST', body: { path: path.value.trim(), name: body.querySelector('[data-name]').value.trim() } });
      projects.open(p.id);
    } }] });
  };
  projects.rename = async function (p) {
    const name = await PB.ui.prompt({ title: 'Rename project', label: 'Name', value: p.name });
    if (!name || name.trim() === p.name) return;
    try {
      const r = await PB.api('/api/projects/' + encodeURIComponent(p.id), { method: 'PATCH', body: { name: name.trim() } });
      if (PB.state.project && PB.state.project.id === p.id) { PB.state.project.name = r.name; PB.bus.emit('project', PB.state.project); }
      else projects.showHome();
    } catch (e) { PB.ui.toast(e.message, 'bad'); }
  };
  projects.duplicate = async function (p) {
    const name = await PB.ui.prompt({ title: 'Duplicate project', label: 'Name of the copy', value: p.name + ' copy', hint: 'Files and Patchbooks are copied; run history is not.' });
    if (!name) return;
    try { const r = await PB.api('/api/projects/' + encodeURIComponent(p.id) + '/duplicate', { method: 'POST', body: { name } }); PB.ui.toast('Copied to "' + r.name + '"', 'ok'); projects.open(r.id); }
    catch (e) { PB.ui.toast(e.message, 'bad'); }
  };
  projects.remove = async function (p) {
    const ok = await PB.ui.confirm({ title: (p.external ? 'Remove "' : 'Delete "') + p.name + '"?', danger: !p.external, okLabel: p.external ? 'Remove' : 'Delete',
      message: p.external ? 'The folder stays where it is; it is only removed from this list.' : 'The whole project folder, its files and its Patchbooks will be deleted. This cannot be undone.',
      checkbox: p.external ? '' : 'Yes, delete the folder and everything in it' });
    if (!ok) return;
    try {
      await PB.api('/api/projects/' + encodeURIComponent(p.id), { method: 'DELETE' });
      PB.ui.toast(p.external ? 'Removed from the list' : 'Project deleted', 'ok');
      if (PB.state.project && PB.state.project.id === p.id) projects.close(); else projects.showHome();
    } catch (e) { PB.ui.toast(e.message, 'bad'); }
  };
})();
