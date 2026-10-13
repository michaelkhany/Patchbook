// Patchbook plugin: Lessons - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
(function () {
  'use strict';
  Patchbook.plugins.register({
    id: 'lessons',
    panel: {
      render(body, panel, ctx) {
        const { icon, util } = ctx;
        const esc = util.esc;
        async function load() {
          const p = ctx.project();
          if (!p) { body.innerHTML = '<div class="empty">' + icon('book', 26) + 'Open a project to see what iTailor remembered.</div>'; return; }
          try {
            const r = await ctx.api(ctx.base + '/' + encodeURIComponent(p.id));
            let html = '<p class="muted small">Every answer you give and every repair that finally worked is kept as a lesson. Lessons inform iTailor; they never authorise anything by themselves.</p>';
            if (!(r.lessons || []).length) html += '<div class="empty">' + icon('book', 26) + 'Nothing remembered yet. Answer a permission question or let a repair succeed.</div>';
            else html += '<table class="table"><thead><tr><th>Kind</th><th>Lesson</th><th>Conf.</th><th></th></tr></thead><tbody>' + r.lessons.map((l) => '<tr><td>' + esc(l.kind) + '</td><td>' + esc(l.decision || l.fix || l.answer || '') + '<div class="muted small mono">' + esc(JSON.stringify(l.situation || {}).slice(0, 160)) + '</div></td><td>' + Number(l.confidence || 0).toFixed(2) + '</td><td><button class="small" data-forget="' + esc(l.id) + '">forget</button></td></tr>').join('') + '</tbody></table>';
            html += '<h4 style="margin-top:12px">Proposed standing rules</h4>' + ((r.proposals || []).length ? '<ul style="margin:0;padding-left:18px">' + r.proposals.map((x) => '<li><span class="mono">' + esc(x.rule) + '</span> → permissions.' + esc(x.list) + ' <span class="muted">(used ' + esc(x.uses) + 'x)</span></li>').join('') + '</ul><p class="muted small">Add a rule to the project by editing .itailor/settings.json; Patchbook never adds one for you.</p>' : '<div class="muted small">None yet. Answer "Always in this run" to a permission question to get one.</div>');
            body.innerHTML = html;
            body.querySelectorAll('[data-forget]').forEach((b) => b.addEventListener('click', async () => { await ctx.api(ctx.base + '/' + encodeURIComponent(p.id) + '/' + encodeURIComponent(b.dataset.forget), { method: 'DELETE' }); load(); }));
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
