// Patchbook plugin: Activity - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
(function () {
  'use strict';
  Patchbook.plugins.register({
    id: 'activity',
    panel: {
      defaultVisible: { simple: false, professional: true },
      render(body, panel, ctx) {
        const { icon, util } = ctx;
        const esc = util.esc;
        const STATUS = { done: ['done', 'done'], failed: ['failed', 'did not finish'], partial: ['partial', 'partly done'], stopped: ['stopped', 'stopped'] };
        async function load() {
          const p = ctx.project();
          if (!p) { body.innerHTML = '<div class="empty">' + icon('history', 26) + 'Open a project to see what its runs used.</div>'; return; }
          try {
            const r = await ctx.api(ctx.base + '/' + encodeURIComponent(p.id));
            const recs = r.records || [];
            if (!recs.length) { body.innerHTML = '<div class="empty">' + icon('history', 26) + 'Nothing recorded yet. Every run adds one entry: programs, installs, permissions, model, files.</div>'; return; }
            body.innerHTML = '<p class="muted small">One entry per run, newest first. Click an entry for the details. The raw transcripts are in the Runs panel.</p>' +
              recs.map((x, i) => {
                const st = STATUS[x.status] || ['', x.status];
                const programs = (x.programs || []);
                const head = '<div class="row" style="gap:6px"><span class="badge ' + esc(st[0]) + '">' + esc(st[1]) + '</span><span class="grow truncate"><b>' + esc(x.cell ? 'Patch ' + x.cell : 'Run') + '</b> ' + esc(x.task || '') + '</span></div>' +
                  '<div class="muted small">' + esc(util.relTime(x.at)) + ' · ' + util.fmtSeconds(x.seconds || 0) + (x.model ? ' · ' + esc(x.model) : '') + (x.effort ? ' · ' + esc(x.effort) + ' effort' : '') +
                  ' · ' + programs.length + ' program' + (programs.length === 1 ? '' : 's') + (x.installs && x.installs.length ? ' · ' + x.installs.length + ' install' + (x.installs.length === 1 ? '' : 's') : '') +
                  (x.errors ? ' · <span style="color:var(--bad)">' + x.errors + ' error line' + (x.errors === 1 ? '' : 's') + '</span>' : '') + (x.warnings ? ' · <span style="color:var(--warn)">' + x.warnings + ' warning' + (x.warnings === 1 ? '' : 's') + '</span>' : '') + '</div>';
                const details = '<div class="kv" style="margin-top:6px">' +
                  (x.approaches && x.approaches.length ? '<dt>Approaches</dt><dd>' + x.approaches.map((a) => esc(a.label) + ' (' + esc((STATUS[a.status] || ['', a.status])[1]) + ')').join('; ') + '</dd>' : '') +
                  (programs.length ? '<dt>Programs</dt><dd>' + programs.map((pr) => '<span style="color:' + (pr.ok === false ? 'var(--bad)' : (pr.ok ? 'var(--ok)' : 'var(--muted)')) + '">' + icon(pr.ok === false ? 'x-circle' : (pr.ok ? 'check-circle' : 'circle'), 12) + '</span> ' + esc(pr.kind) + ': <span class="mono">' + esc(pr.what) + '</span>' + (pr.seconds != null ? ' <span class="muted">' + util.fmtSeconds(pr.seconds) + '</span>' : '') + (pr.summary ? ' <span class="muted">' + esc(pr.summary) + '</span>' : '')).join('<br>') + '</dd>' : '') +
                  (x.decisions && x.decisions.length ? '<dt>Permissions</dt><dd>' + x.decisions.map((d) => esc(d.decision || '') + ' <span class="mono">' + esc(d.tool || '') + ' ' + esc(d.command || '') + '</span> <span class="muted">(' + esc(d.source || '') + (d.reason ? ': ' + esc(d.reason) : '') + ')</span>').join('<br>') + '</dd>' : '') +
                  (x.files && x.files.length ? '<dt>Files</dt><dd>' + x.files.map((f) => '<a href="#" data-open="' + esc(f) + '">' + esc(f) + '</a>').join(', ') + '</dd>' : '') + '</div>';
                return '<details class="box" style="margin-bottom:8px"' + (i === 0 ? ' open' : '') + '><summary style="cursor:pointer;list-style:none">' + head + '</summary>' + details + '</details>';
              }).join('') + '<p class="muted small">Stored in <span class="mono">' + esc(r.path || '') + '</span></p>';
            body.querySelectorAll('[data-open]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); ctx.files.preview(a.dataset.open); }));
          } catch (e) { body.innerHTML = '<div class="callout bad">' + esc(e.message) + '</div>'; }
        }
        panel.load = load;
        load();
        ctx.bus.on('project', load);
        ctx.bus.on('run-end', load);
      },
      refresh(panel) { panel.load(); },
    },
  });
})();
