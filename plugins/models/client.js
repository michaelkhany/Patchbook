// Patchbook plugin: Models - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
(function () {
  'use strict';
  Patchbook.plugins.register({
    id: 'models',
    panel: {
      render(body, panel, ctx) {
        const { icon, util } = ctx;
        const esc = util.esc;
        body.innerHTML = '<div class="callout" data-status>…</div><div class="row" style="margin:8px 0"><button class="small" data-discover>' + icon('search', 14) + ' Discover services and rank models</button><button class="small ghost" data-settings>' + icon('settings', 14) + ' Change the model</button></div><div data-out class="small"></div>';
        body.querySelector('[data-settings]').addEventListener('click', () => PB.settings.open('model'));
        async function status() {
          try { const s = await ctx.api('/api/models/status'); ctx.state.model = s; const box = body.querySelector('[data-status]'); box.className = 'callout ' + (s.configured ? 'ok' : 'warn'); box.innerHTML = (s.configured ? icon('check-circle', 14) + ' ' : icon('alert-triangle', 14) + ' ') + esc(s.label) + (s.provider ? ' <span class="muted">(' + esc(s.provider) + ')</span>' : ''); }
          catch (e) { body.querySelector('[data-status]').textContent = e.message; }
        }
        async function discover() {
          const out = body.querySelector('[data-out]');
          out.innerHTML = '<div class="muted">' + icon('loader', 14) + ' Listing models from every source (a few seconds)…</div>';
          try {
            const m = await ctx.api('/api/models/discover');
            let html = '<h4>Sources</h4><table class="table"><thead><tr><th>Source</th><th>Address</th><th>Models</th><th>Note</th></tr></thead><tbody>' +
              (m.sources || []).map((s) => '<tr><td>' + esc(s.id) + '<br><span class="muted">' + esc(s.kind) + '</span></td><td class="mono">' + esc(s.base_url || '') + (s.api_key ? ' <span class="badge ok">key</span>' : '') + '</td><td>' + ((s.models || []).length) + '</td><td class="muted">' + esc(s.note || '') + (s.message && !(s.models || []).length ? ' ' + esc(s.message) : '') + '</td></tr>').join('') + '</tbody></table>';
            const sel = m.selection || {};
            html += '<h4 style="margin-top:12px">Ranking for the coder role</h4>';
            const current = (ctx.state.model || {}).model || 'auto';
            if ((sel.ranked || []).length) {
              html += '<table class="table"><thead><tr><th>Score</th><th>Model</th><th>Context</th><th>Tools</th><th>Criteria</th><th></th></tr></thead><tbody>' + sel.ranked.slice(0, 25).map((r) => '<tr><td>' + Number(r.score).toFixed(3) + '</td><td class="mono">' + esc(r.model) + (r.model === current ? ' <span class="badge ok">in use</span>' : '') + '</td><td>' + esc(r.context || '?') + '</td><td>' + esc(String(r.nativeTools)) + '</td><td class="muted">' + esc(Object.entries(r.criteria || {}).map(([k, v]) => k + '=' + Number(v).toFixed(2)).join(' ')) + '</td><td><button class="small" data-use="' + esc(r.model) + '" title="Use this model for every patch">Use</button></td></tr>').join('') + '</tbody></table>' +
                '<div class="row" style="margin-top:6px"><button class="small" data-use="auto">' + icon('refresh', 13) + ' Back to automatic choice</button></div>';
            } else html += '<div class="muted">No candidate. Connect a service in Settings or start a local server.</div>';
            html += '<h4 style="margin-top:12px">Selection</h4><ul style="margin:0;padding-left:18px">' + (sel.explanation || []).map((l) => '<li>' + esc(l) + '</li>').join('') + '</ul>' +
              '<div class="muted" style="margin-top:6px">Roles: ' + esc(JSON.stringify(sel.roles || {})) + '</div>';
            out.innerHTML = html;
            out.querySelectorAll('[data-use]').forEach((btn) => btn.addEventListener('click', async () => {
              try {
                await ctx.api('/api/settings/itailor', { method: 'POST', body: { model: btn.dataset.use } });
                ctx.state.model = await ctx.api('/api/models/status?refresh=1');
                PB.notebook.markSaved(PB.notebook.saveState);
                ctx.ui.toast(btn.dataset.use === 'auto' ? 'Back to the automatic choice.' : 'Model set to ' + btn.dataset.use, 'ok');
                status(); discover();
              } catch (e) { ctx.ui.toast(e.message, 'bad'); }
            }));
          } catch (e) { out.innerHTML = '<div class="callout bad">' + esc(e.message) + '</div>'; }
        }
        body.querySelector('[data-discover]').addEventListener('click', discover);
        panel.status = status;
        status();
      },
      refresh(panel) { panel.status(); },
      onShow(panel) { panel.status(); },
    },
  });
})();
