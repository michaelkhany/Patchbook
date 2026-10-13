// Patchbook plugin: Export - Copyright (c) 2026 Michael Bidollahkhani. MIT License.
(function () {
  'use strict';
  Patchbook.plugins.register({
    id: 'export',
    tool: {
      label: 'Export the Patchbook…', icon: 'download',
      enabled: (ctx) => !!(ctx.project() && ctx.patchbook()),
      run(ctx) {
        const p = ctx.project(), b = ctx.patchbook();
        if (!p || !b) { ctx.ui.toast('Open a Patchbook first.', 'warn'); return; }
        const body = ctx.util.el('<div><p>Everything in <b>' + ctx.util.esc(b.name) + '</b>: the patches, their answers, the code and the files.</p><div class="option-list">' +
          '<label class="option selected"><input type="radio" name="xfmt" value="md" checked><div><div class="title">Markdown report (.md)</div><div class="desc">Readable text with the code and links to the files. Opens anywhere.</div></div></label>' +
          '<label class="option"><input type="radio" name="xfmt" value="ipynb"><div><div class="title">Jupyter notebook (.ipynb)</div><div class="desc">Your patches as Markdown cells, the generated code as code cells with their output and images. Opens in JupyterLab or VS Code.</div></div></label>' +
          '<label class="option"><input type="radio" name="xfmt" value="html"><div><div class="title">Web page (.html)</div><div class="desc">One self-contained file with the images embedded. Good for sending to someone.</div></div></label></div>' +
          '<label class="inline" style="margin-top:10px"><input type="checkbox" data-save> Also save a copy into the project folder</label></div>');
        body.querySelectorAll('input[name="xfmt"]').forEach((r) => r.addEventListener('change', () => body.querySelectorAll('.option').forEach((o) => o.classList.toggle('selected', o.querySelector('input').checked))));
        ctx.ui.dialog({ title: 'Export the Patchbook', icon: 'download', body, buttons: [{ label: 'Cancel' }, { label: 'Export', primary: true, action: async () => {
          const fmt = body.querySelector('input[name="xfmt"]:checked').value;
          await ctx.notebook.saveNow();
          const url = ctx.base + '/' + encodeURIComponent(p.id) + '/' + encodeURIComponent(b.id) + '?format=' + fmt;
          if (body.querySelector('[data-save]').checked) { const r = await ctx.api(url + '&save=1'); ctx.ui.toast('Saved ' + r.path + ' in the project folder', 'ok'); ctx.files.load(); }
          window.open(url, '_blank');
        } }] });
      },
    },
  });
})();
