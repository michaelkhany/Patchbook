// Patchbook plugin: Runs - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
(function () {
  'use strict';
  Patchbook.plugins.register({
    id: 'runs',
    panel: {
      render(body, panel, ctx) {
        const { icon, util } = ctx;
        const esc = util.esc;
        body.innerHTML = '<div data-list></div><div data-detail class="hidden"></div>';
        let detail = null, sub = 'report';
        async function load() {
          const list = body.querySelector('[data-list]');
          const p = ctx.project();
          if (!p) { list.innerHTML = '<div class="empty">' + icon('clock', 26) + 'Open a project to see its runs.</div>'; return; }
          try {
            const r = await ctx.api('/api/projects/' + encodeURIComponent(p.id) + '/runs');
            if (!(r.runs || []).length) { list.innerHTML = '<div class="empty">' + icon('clock', 26) + 'No runs yet. Every patch that runs leaves a folder under .itailor/runs/.</div>'; return; }
            const badge = { succeeded: ['done', 'done'], partial: ['partial', 'partly done'], failed: ['failed', 'failed'], cancelled: ['stopped', 'stopped'], running: ['running', 'running'], script: ['', 'script run'], unknown: ['', 'no report'] };
            const iconOf = { succeeded: 'check-circle', partial: 'alert-circle', failed: 'x-circle', cancelled: 'stop', running: 'loader', script: 'zap', unknown: 'circle' };
            list.innerHTML = '<p class="muted small">Every run leaves a folder under .itailor/runs/ with its plan, transcript and report. Thorough runs write a full report; quick runs keep the scripts and their output.</p><ul class="steps-list">' + r.runs.map((run) => {
              const b = badge[run.status] || ['', run.status];
              const where = run.cell ? (run.cell.patchbook + ' · cell ' + run.cell.cellIndex + (run.engine ? ' · ' + run.engine : '')) : run.id;
              return '<li style="cursor:pointer" data-run="' + esc(run.id) + '"><span class="ic">' + icon(iconOf[run.status] || 'circle', 13) + '</span><span class="grow"><span class="truncate" style="display:block">' + esc(run.goal || run.id) + '</span><span class="muted small">' + esc(where) + (run.started ? ' · ' + esc(util.relTime(run.started)) : '') + '</span></span><span class="badge ' + esc(b[0]) + '">' + esc(b[1]) + '</span></li>';
            }).join('') + '</ul>';
            list.querySelectorAll('[data-run]').forEach((li) => li.addEventListener('click', () => open(li.dataset.run)));
          } catch (e) { list.innerHTML = '<div class="callout bad">' + esc(e.message) + '</div>'; }
        }
        async function open(id) {
          const p = ctx.project();
          try { detail = await ctx.api('/api/projects/' + encodeURIComponent(p.id) + '/runs/' + encodeURIComponent(id) + '/report'); } catch (e) { ctx.ui.toast(e.message, 'bad'); return; }
          body.querySelector('[data-list]').classList.add('hidden');
          renderDetail();
        }
        function renderDetail() {
          const d = body.querySelector('[data-detail]');
          d.classList.remove('hidden');
          const views = { report: () => '<div class="markdown">' + ctx.ui.markdown(detail.report || '(no report)') + '</div>', plan: () => '<div class="markdown">' + ctx.ui.markdown(detail.plan || '(no plan)') + '</div>',
            state: () => '<pre class="box small">' + esc(JSON.stringify(detail.state, null, 2)) + '</pre>', transcript: () => '<div class="events">' + (detail.transcript || []).map((e) => '<div class="ev ' + esc(e.type) + '"><span class="t">' + esc(e.type) + '</span>' + esc(String(e.message || '').slice(0, 400)) + '</div>').join('') + '</div>' };
          d.innerHTML = '<div class="row" style="margin-bottom:8px"><button class="small" data-back>' + icon('arrow-left', 14) + ' All runs</button><span class="mono small muted truncate">' + esc(detail.id) + '</span></div><div class="tabs">' + ['report', 'plan', 'state', 'transcript'].map((k) => '<button class="' + (sub === k ? 'active' : '') + '" data-sub="' + k + '">' + k + '</button>').join('') + '</div><div data-view>' + views[sub]() + '</div>';
          d.querySelector('[data-back]').addEventListener('click', () => { d.classList.add('hidden'); body.querySelector('[data-list]').classList.remove('hidden'); });
          d.querySelectorAll('[data-sub]').forEach((b) => b.addEventListener('click', () => { sub = b.dataset.sub; renderDetail(); }));
        }
        panel.load = load;
        load();
        ctx.bus.on('run-end', () => { if (!body.querySelector('[data-list]').classList.contains('hidden')) load(); });
        ctx.bus.on('project', () => { body.querySelector('[data-detail]').classList.add('hidden'); body.querySelector('[data-list]').classList.remove('hidden'); load(); });
      },
      refresh(panel) { panel.load(); },
    },
  });
})();
