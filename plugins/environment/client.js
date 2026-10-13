// Patchbook plugin: Environment - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
(function () {
  'use strict';
  Patchbook.plugins.register({
    id: 'environment',
    panel: {
      render(body, panel, ctx) {
        const { icon, util } = ctx;
        body.innerHTML = '<div class="row" style="margin-bottom:8px"><button class="small" data-refresh>' + icon('refresh', 14) + ' Look again</button>' +
          '<input type="search" data-find placeholder="find a program or application, e.g. Rscript, Excel" style="flex:1;min-width:160px"><button class="small" data-findbtn>' + icon('search', 14) + '</button></div>' +
          '<div class="muted small" data-meta></div><pre class="box small" data-summary>Loading…</pre><pre class="box small hidden" data-found></pre>' +
          '<details><summary class="muted small" style="cursor:pointer">Full manifest (JSON)</summary><pre class="box small" data-json></pre></details>';
        body.querySelector('[data-refresh]').addEventListener('click', async () => { await ctx.api('/api/env?refresh=1'); body.querySelector('[data-summary]').textContent = 'Looking at this computer again…'; setTimeout(() => load(true), 1500); });
        const find = async () => {
          const name = body.querySelector('[data-find]').value.trim();
          if (!name) return;
          const r = await ctx.api('/api/env/find?name=' + encodeURIComponent(name));
          const out = body.querySelector('[data-found]');
          out.classList.remove('hidden');
          out.textContent = 'Program: ' + (r.program && r.program.found ? r.program.path || JSON.stringify(r.program) : 'not on PATH') + '\nApplication: ' + (r.app && r.app.found ? (r.app.name || '') + ' ' + (r.app.path || r.app.command || '') : 'not found');
        };
        body.querySelector('[data-findbtn]').addEventListener('click', find);
        body.querySelector('[data-find]').addEventListener('keydown', (e) => { if (e.key === 'Enter') find(); });
        async function load(poll) {
          try {
            const e = await ctx.api('/api/env?full=1');
            if (e.status === 'running') { body.querySelector('[data-meta]').textContent = 'Discovery is running…'; if (poll) setTimeout(() => load(true), 1500); return; }
            if (e.status === 'error') { body.querySelector('[data-summary]').textContent = 'Discovery failed: ' + e.error; return; }
            body.querySelector('[data-meta]').textContent = (e.cached ? 'From cache' : 'Fresh') + (e.generatedAt ? ', generated ' + util.relTime(e.generatedAt) : '') + (e.seconds ? ', took ' + e.seconds + ' s' : '');
            body.querySelector('[data-summary]').textContent = e.summary || '(empty)';
            body.querySelector('[data-json]').textContent = JSON.stringify(e.manifest, null, 2);
          } catch (err) { body.querySelector('[data-summary]').textContent = err.message; }
        }
        panel.load = load;
        load(true);
      },
      refresh(panel) { panel.load(true); },
    },
  });
})();
