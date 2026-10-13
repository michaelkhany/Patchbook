// Patchbook - Copyright (c) 2026 Michael Bidollahkhani. All rights reserved. MIT License.
// The patch mechanism is Michael Bidollahkhani's original design; Patchbook's iTailor was its first application (b-0240331).
// Shared runtime: the API client, the event bus, utilities, configuration and keyboard shortcuts.
(function () {
  'use strict';
  const PB = window.PB = window.PB || {};

  PB.boot = null;          // what /api/boot returned
  PB.config = null;        // Patchbook's configuration (mirrors data/config.json)
  PB.state = {
    project: null,         // the open project (summary + patchbookList)
    patchbook: null,       // the open Patchbook document
    patchbooks: [],        // the project's Patchbook list
    activeRun: null,       // {id, cellId, ...} while a run is in progress
    queue: [],             // cell ids waiting to run (Run all / Run from here)
    model: null,           // /api/models/status
    env: null,             // /api/env
    activeTab: { left: '', right: '' },
    lastRun: null,         // the last run's summary for the Progress panel
  };

  // ---------------------------------------------------------------- bus
  const listeners = {};
  PB.bus = {
    on(event, fn) { (listeners[event] = listeners[event] || []).push(fn); return () => PB.bus.off(event, fn); },
    off(event, fn) { listeners[event] = (listeners[event] || []).filter((f) => f !== fn); },
    emit(event, data) { (listeners[event] || []).slice().forEach((fn) => { try { fn(data); } catch (e) { console.error('bus:' + event, e); } }); },
  };

  // ---------------------------------------------------------------- api
  PB.api = async function api(path, opts) {
    const options = Object.assign({ headers: {} }, opts || {});
    if (options.body !== undefined && typeof options.body !== 'string' && !(options.body instanceof FormData)) {
      options.body = JSON.stringify(options.body);
      options.headers['Content-Type'] = 'application/json';
    }
    let res;
    try { res = await fetch(path, options); } catch (e) {
      throw new Error('Patchbook cannot be reached. Is the Patchbook window (the terminal) still open?');
    }
    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { error: text.slice(0, 300) }; }
    if (!res.ok) {
      const err = new Error(data.error || res.statusText || 'The request failed.');
      err.status = res.status; err.data = data;
      throw err;
    }
    return data;
  };

  // ---------------------------------------------------------------- utilities
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function el(html) { const t = document.createElement('template'); t.innerHTML = String(html).trim(); return t.content.firstElementChild; }
  function debounce(fn, ms) { let t; const d = function () { const a = arguments, c = this; clearTimeout(t); t = setTimeout(() => fn.apply(c, a), ms); }; d.cancel = () => clearTimeout(t); d.flush = function () { clearTimeout(t); fn.apply(this, arguments); }; return d; }
  function fmtBytes(n) { if (n == null || isNaN(n)) return ''; if (n < 1024) return n + ' B'; if (n < 1048576) return (n / 1024).toFixed(1) + ' KB'; if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB'; return (n / 1073741824).toFixed(2) + ' GB'; }
  // Numbers are Unix seconds (what the server sends) unless they are clearly milliseconds (Date.now()).
  function toDate(ts) { if (ts instanceof Date) return ts; if (typeof ts === 'number') return new Date(ts < 1e11 ? ts * 1000 : ts); return new Date(ts); }
  function fmtClock(ts) { const d = toDate(ts); return isNaN(d) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
  function fmtDate(ts) { const d = toDate(ts); return isNaN(d) ? '' : d.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' }) + ' ' + fmtClock(d); }
  function relTime(ts) {
    const d = toDate(ts);
    if (isNaN(d)) return '';
    const s = Math.round((Date.now() - d.getTime()) / 1000);
    if (s < 45) return 'just now';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    if (s < 86400) return Math.round(s / 3600) + ' h ago';
    if (s < 86400 * 14) return Math.round(s / 86400) + ' days ago';
    return fmtDate(d);
  }
  function fmtSeconds(sec) { sec = Math.max(0, Math.round(sec)); const m = Math.floor(sec / 60), s = sec % 60; return (m ? m + ':' : '0:') + String(s).padStart(2, '0'); }
  function uid() { return Math.random().toString(16).slice(2, 10); }
  function plural(n, word, pluralWord) { return n + ' ' + (n === 1 ? word : (pluralWord || word + 's')); }
  function ext(path) { const m = /\.([a-z0-9]+)$/i.exec(path || ''); return m ? m[1].toLowerCase() : ''; }
  const IMAGE = new Set(['png', 'jpg', 'jpeg', 'gif', 'svg', 'webp', 'bmp']);
  const TABLE = new Set(['csv', 'tsv']);
  const TEXT = new Set(['md', 'txt', 'json', 'yaml', 'yml', 'html', 'htm', 'log', 'py', 'r', 'js', 'sql', 'xml', 'tex', 'sh', 'ps1', 'ipynb', 'jl', 'toml', 'ini', 'cfg']);
  PB.util = {
    esc, el, debounce, fmtBytes, fmtClock, fmtDate, relTime, fmtSeconds, uid, plural, ext,
    isImage: (p) => IMAGE.has(ext(p)), isTable: (p) => TABLE.has(ext(p)), isText: (p) => TEXT.has(ext(p)),
    basename: (p) => String(p || '').split('/').pop(),
    clamp: (n, a, b) => Math.min(b, Math.max(a, n)),
    sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
    nowIso: () => new Date().toISOString().slice(0, 19),
    cellLabel(cell, index) { const t = (cell.text || '').trim().split('\n')[0]; return (index != null ? (index + 1) + '. ' : '') + (t ? t.slice(0, 70) + (t.length > 70 ? '…' : '') : '(empty ' + cell.kind + ')'); },
  };

  // ---------------------------------------------------------------- look, config
  PB.look = () => (PB.config && PB.config.look) || 'simple';
  PB.isPro = () => PB.look() === 'professional';
  PB.lookAllows = (looks) => !looks || !looks.length || looks.indexOf(PB.look()) !== -1;

  function deepMerge(base, patch) {
    const out = Object.assign({}, base);
    Object.keys(patch || {}).forEach((k) => {
      if (patch[k] && typeof patch[k] === 'object' && !Array.isArray(patch[k]) && out[k] && typeof out[k] === 'object' && !Array.isArray(out[k])) out[k] = deepMerge(out[k], patch[k]);
      else out[k] = patch[k];
    });
    return out;
  }
  PB.deepMerge = deepMerge;
  let pendingConfig = {};
  const flushConfig = debounce(async () => {
    const patch = pendingConfig; pendingConfig = {};
    try { PB.config = await PB.api('/api/config', { method: 'POST', body: patch }); PB.bus.emit('config', PB.config); }
    catch (e) { PB.ui && PB.ui.toast('Settings could not be saved: ' + e.message, 'bad'); }
  }, 400);
  // Merge locally at once (the UI reacts immediately), write to the server shortly after.
  PB.saveConfig = function (patch, immediate) {
    PB.config = deepMerge(PB.config || {}, patch);
    pendingConfig = deepMerge(pendingConfig, patch);
    PB.bus.emit('config', PB.config);
    if (immediate) return flushConfig.flush();
    flushConfig();
  };

  // ---------------------------------------------------------------- shortcuts
  const shortcuts = {};
  function comboOf(e) {
    const parts = [];
    if (e.ctrlKey || e.metaKey) parts.push('ctrl');
    if (e.altKey) parts.push('alt');
    if (e.shiftKey) parts.push('shift');
    let key = (e.key || '').toLowerCase();
    if (key === ' ') key = 'space';
    parts.push(key);
    return parts.join('+');
  }
  PB.shortcut = {
    register(combo, fn, opts) { shortcuts[combo] = { fn, opts: opts || {} }; },
    install() {
      document.addEventListener('keydown', (e) => {
        if (e.defaultPrevented) return;
        const combo = comboOf(e);
        const entry = shortcuts[combo];
        if (!entry) return;
        const target = e.target;
        const typing = target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable || (target.closest && target.closest('.CodeMirror')));
        if (typing && !entry.opts.whileTyping) return;
        if (entry.fn(e) !== false) e.preventDefault();
      });
    },
  };
})();
