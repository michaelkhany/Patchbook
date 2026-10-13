// Patchbook plugin: Project graph - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
(function () {
  'use strict';
  Patchbook.plugins.register({
    id: 'graph',
    panel: {
      render(body, panel, ctx) {
        const { icon, util } = ctx;
        const esc = util.esc;
        body.innerHTML = '<div class="row" style="margin-bottom:8px"><button class="small" data-rebuild>' + icon('refresh', 14) + ' Rebuild from the runs</button><span class="muted small" data-meta></span></div><h4>As the model sees it</h4><pre class="box small" data-summary>…</pre><h4>graph.yaml</h4><pre class="box small" data-yaml></pre>';
        async function load(rebuild) {
          const p = ctx.project();
          if (!p) { body.querySelector('[data-summary]').textContent = 'Open a project.'; body.querySelector('[data-yaml]').textContent = ''; return; }
          try {
            const g = await ctx.api(ctx.base + '/' + encodeURIComponent(p.id) + (rebuild ? '?rebuild=1' : ''));
            body.querySelector('[data-meta]').textContent = g.nodes + ' nodes, ' + g.edges + ' edges';
            body.querySelector('[data-summary]').textContent = g.summary || '(nothing recorded yet; run a patch first)';
            body.querySelector('[data-yaml]').textContent = g.yaml || '(no file yet)';
          } catch (e) { body.querySelector('[data-summary]').textContent = e.message; }
        }
        body.querySelector('[data-rebuild]').addEventListener('click', () => load(true));
        panel.load = load;
        load();
        ctx.bus.on('project', () => load());
        ctx.bus.on('run-end', () => load());
        void esc;
      },
      refresh(panel) { panel.load(); },
    },
  });
})();
