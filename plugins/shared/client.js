// Patchbook plugin: Shared store - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
(function () {
  'use strict';
  Patchbook.plugins.register({
    id: 'shared',
    panel: {
      defaultVisible: { simple: false, professional: true },
      render(body, panel, ctx) {
        const { icon, util } = ctx;
        const esc = util.esc;
        body.innerHTML = '<div class="row" style="margin-bottom:8px"><button class="small" data-scan>' + icon('refresh', 14) + ' Scan the folder</button><button class="small" data-folder>' + icon('external-link', 14) + ' Show folder</button></div><div data-out></div>';
        body.querySelector('[data-scan]').addEventListener('click', () => load(true));
        body.querySelector('[data-folder]').addEventListener('click', async () => { const p = ctx.project(); if (!p) return; try { await ctx.api('/api/projects/' + encodeURIComponent(p.id) + '/open-with', { method: 'POST', body: { path: 'shared', reveal: false } }); } catch (e) { ctx.ui.toast(e.message, 'bad'); } });
        async function load(scan) {
          const out = body.querySelector('[data-out]');
          const p = ctx.project();
          if (!p) { out.innerHTML = '<div class="empty">' + icon('hard-drive', 26) + 'Open a project to see its shared store.</div>'; return; }
          try {
            const r = await ctx.api(ctx.base + '/' + encodeURIComponent(p.id) + (scan ? '?scan=1' : ''));
            const reg = r.registry || {};
            const vars = Object.entries(reg.variables || {}), params = Object.entries(reg.parameters || {}), methods = Object.entries(reg.methods || {});
            let html = '<p class="muted small">What one patch leaves for the next, on disk, in any language: the folder <span class="mono">shared/</span>. Tables as CSV, small parameters in <span class="mono">shared/params.json</span>, reusable functions under <span class="mono">shared/methods/</span> with a comment saying how to call them. Patchbook records it after every run and tells later patches what exists.</p>';
            if (!vars.length && !params.length && !methods.length) html += '<div class="empty">' + icon('hard-drive', 26) + 'Nothing shared yet. A patch that writes into shared/ fills this.</div>';
            if (vars.length) html += '<h4>Values</h4><table class="table"><thead><tr><th>Name</th><th>What</th><th>From</th></tr></thead><tbody>' + vars.map(([n, v]) => '<tr><td><a href="#" data-open="' + esc(v.file) + '">' + esc(n) + '</a></td><td>' + esc(v.kind) + (v.columns ? ' · ' + esc(v.rows) + ' rows · ' + esc(v.columns.slice(0, 6).join(', ')) + (v.columns.length > 6 ? '…' : '') : '') + (v.description ? '<br><span class="muted">' + esc(v.description) + '</span>' : '') + '</td><td class="muted small">' + esc(v.producedBy && v.producedBy.cell ? 'patch ' + v.producedBy.cell : '') + (v.updated ? '<br>' + esc(util.relTime(v.updated)) : '') + '</td></tr>').join('') + '</tbody></table>';
            if (params.length) html += '<h4 style="margin-top:10px">Parameters</h4><table class="table"><thead><tr><th>Name</th><th>Value</th><th>From</th></tr></thead><tbody>' + params.map(([n, v]) => '<tr><td>' + esc(n) + '</td><td class="mono">' + esc(JSON.stringify(v.value)).slice(0, 120) + '</td><td class="muted small">' + esc(v.producedBy && v.producedBy.cell ? 'patch ' + v.producedBy.cell : '') + '</td></tr>').join('') + '</tbody></table>';
            if (methods.length) html += '<h4 style="margin-top:10px">Methods</h4><table class="table"><thead><tr><th>Name</th><th>How to call</th><th>From</th></tr></thead><tbody>' + methods.map(([n, v]) => '<tr><td><a href="#" data-open="' + esc(v.file) + '">' + esc(n) + '</a><br><span class="muted small">' + esc(v.language) + '</span></td><td class="mono small">' + esc(v.call || '(no call line in the file header)') + (v.description ? '<br><span class="muted" style="font-family:var(--sans)">' + esc(v.description) + '</span>' : '') + '</td><td class="muted small">' + esc(v.producedBy && v.producedBy.cell ? 'patch ' + v.producedBy.cell : '') + '</td></tr>').join('') + '</tbody></table>';
            html += '<details style="margin-top:10px"><summary class="muted small" style="cursor:pointer">What the model is told</summary><pre class="box small">' + esc(r.prompt || '') + '</pre></details>';
            out.innerHTML = html;
            out.querySelectorAll('[data-open]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); ctx.files.preview(a.dataset.open); }));
          } catch (e) { out.innerHTML = '<div class="callout bad">' + esc(e.message) + '</div>'; }
        }
        panel.load = load;
        load(false);
        ctx.bus.on('project', () => load(false));
        ctx.bus.on('run-end', () => load(false));
      },
      refresh(panel) { panel.load(true); },
    },
  });
})();
