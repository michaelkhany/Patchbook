// Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
// Plugins in the browser: loading each plugin's client script and registering what it adds.
//
// A plugin's client.js calls:
//   Patchbook.plugins.register({
//     id: 'my-plugin',
//     panel: { title, description, icon, dock, looks, defaultVisible, render(body, panel, ctx), refresh(panel, ctx), onShow(panel, ctx) },
//     tool:  { label, icon, looks, run(ctx) },
//   });
// ctx gives it Patchbook's services: api, state, ui, icon, bus, util, notebook, panels, project(), patchbook().
(function () {
  'use strict';
  const PB = window.PB;
  const plugins = PB.plugins = { list: [], tools: [], registry: {}, loaded: {} };

  plugins.ctx = function (plugin) {
    return {
      id: plugin ? plugin.id : '', api: PB.api, state: PB.state, ui: PB.ui, icon: PB.icon, bus: PB.bus, util: PB.util, notebook: PB.notebook, panels: PB.panels,
      project: () => PB.state.project, patchbook: () => PB.state.patchbook, config: () => PB.config, boot: () => PB.boot, isPro: PB.isPro, files: PB.files,
      base: plugin ? '/api/plugins/' + plugin.id : '',
    };
  };

  plugins.register = function (def) {
    if (!def || !def.id) throw new Error('a plugin must have an id');
    const manifest = plugins.list.find((p) => p.id === def.id) || { id: def.id, name: def.id, looks: ['simple', 'professional'] };
    plugins.registry[def.id] = def;
    const ctx = plugins.ctx(manifest);
    if (def.panel) {
      const p = def.panel;
      PB.panels.register({
        id: def.id, title: p.title || manifest.name, description: p.description || manifest.description, icon: p.icon || manifest.icon,
        dock: p.dock || manifest.dock || 'right', looks: p.looks || manifest.looks, order: p.order != null ? p.order : (manifest.order || 100),
        defaultVisible: p.defaultVisible || { simple: false, professional: true },
        render: (body, inst) => p.render(body, inst, ctx), refresh: p.refresh ? (inst) => p.refresh(inst, ctx) : null, onShow: p.onShow ? (inst) => p.onShow(inst, ctx) : null,
      });
    }
    if (def.tool) {
      const t = def.tool;
      plugins.tools.push({ id: def.id, label: t.label || manifest.name, icon: t.icon || manifest.icon || 'tool', looks: t.looks || manifest.looks, run: () => t.run(ctx), enabled: t.enabled ? () => t.enabled(ctx) : null });
    }
  };

  plugins.loadClients = async function (list, onProgress) {
    plugins.list = list || [];
    for (const plugin of plugins.list) {
      if (plugin.status !== 'loaded' || !plugin.clientUrl) { plugins.loaded[plugin.id] = plugin.status; if (onProgress) onProgress(plugin); continue; }
      await new Promise((resolve) => {
        const s = document.createElement('script');
        s.src = plugin.clientUrl + '?v=' + encodeURIComponent(plugin.version || '1');
        s.async = false;
        s.onload = () => { plugins.loaded[plugin.id] = 'loaded'; resolve(); };
        s.onerror = () => { plugins.loaded[plugin.id] = 'error'; plugin.status = 'error'; plugin.error = 'the browser part (client.js) failed to load'; resolve(); };
        document.body.appendChild(s);
      });
      if (onProgress) onProgress(plugin);
    }
    return plugins.list;
  };

  plugins.toolItems = function () {
    return plugins.tools.filter((t) => PB.lookAllows(t.looks)).map((t) => ({ label: t.label, icon: t.icon, enabled: t.enabled || undefined, action: t.run }));
  };

  window.Patchbook = window.Patchbook || {};
  window.Patchbook.plugins = plugins;
  window.Patchbook.version = () => PB.boot && PB.boot.app.version;
})();
