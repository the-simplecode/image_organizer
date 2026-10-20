// gallery_template.hpp
// Static parts of the generated image_gallery.html (CSS, markup, JavaScript).
// The C++ generator inserts ONE dynamic piece: a JSON array placed inside
//   <script type="application/json" id="gallery-data">...</script>
// The JavaScript builds every card with textContent / setAttribute (never
// innerHTML), so metadata can never inject markup.
//
// The text is split into several raw-string literals so each one stays well
// below MSVC's ~16 KB per-literal limit.
#pragma once

namespace gallery_template {

inline const char* const kCss = R"GAL(
:root{--bg:#f5f6f8;--panel:#fff;--text:#1b1f27;--muted:#5d6675;--border:#dde1e8;--accent:#2f6fed;--accent-text:#fff;--shadow:0 1px 3px rgba(20,30,50,.08);--ph:#e6e9ef;color-scheme:light}
:root[data-theme="dark"]{--bg:#12151b;--panel:#1b2029;--text:#e7eaf0;--muted:#a0a9b8;--border:#2c3340;--accent:#6c9bff;--accent-text:#0d1220;--shadow:0 1px 3px rgba(0,0,0,.5);--ph:#262c37;color-scheme:dark}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;overflow-x:hidden;transition:background .2s,color .2s}
body.lb-open{overflow:hidden}
button,input,select{font:inherit;color:inherit}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.topbar{position:sticky;top:0;z-index:5;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px clamp(12px,3vw,32px);background:var(--panel);border-bottom:1px solid var(--border)}
.brand{display:flex;align-items:center;gap:10px;min-width:0}
.brand h1{margin:0;font-size:1.2rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.logo{display:inline-grid;place-items:center;width:32px;height:32px;border-radius:8px;background:var(--accent);color:var(--accent-text);font-weight:700}
main{max-width:1500px;margin:0 auto;padding:16px clamp(12px,3vw,32px) 48px}
.btn{min-height:44px;padding:0 16px;border:1px solid var(--border);border-radius:10px;background:var(--panel);cursor:pointer;transition:background .15s,border-color .15s}
.btn:hover{border-color:var(--accent)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-text)}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:0 0 12px;padding:0;list-style:none}
.stat{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:12px 14px;box-shadow:var(--shadow);min-width:0}
.stat b{display:block;font-size:1.4rem;overflow-wrap:anywhere}
.stat span{color:var(--muted);font-size:.85rem}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 16px}
.chip{min-height:36px;padding:0 12px;border:1px solid var(--border);border-radius:999px;background:var(--panel);cursor:pointer;font-size:.9rem}
.chip[aria-pressed="true"]{background:var(--accent);border-color:var(--accent);color:var(--accent-text)}
.controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:14px;box-shadow:var(--shadow)}
.field{display:flex;flex-direction:column;gap:4px;min-width:0}
.field label{font-size:.8rem;color:var(--muted);font-weight:600}
.field input,.field select{width:100%;min-height:44px;padding:0 10px;border:1px solid var(--border);border-radius:10px;background:var(--bg)}
.field.wide{grid-column:1/-1}
@media(min-width:720px){.field.wide{grid-column:span 2}}
.resultbar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px;margin:14px 0}
#counter{color:var(--muted)}
.empty{padding:48px 16px;text-align:center;color:var(--muted);background:var(--panel);border:1px dashed var(--border);border-radius:12px}
.empty h2{margin:0 0 6px;color:var(--text);font-size:1.15rem}
.grid{list-style:none;margin:0;padding:0;display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(min(100%,210px),1fr))}
.card{background:var(--panel);border:1px solid var(--border);border-radius:12px;overflow:hidden;box-shadow:var(--shadow);min-width:0;transition:transform .15s,border-color .15s}
.card:hover{transform:translateY(-2px);border-color:var(--accent)}
.thumb{position:relative;display:block;width:100%;aspect-ratio:4/3;padding:0;border:0;background:var(--ph);cursor:zoom-in;overflow:hidden}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.thumb.loading::before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(127,127,127,.25),transparent);animation:sh 1.2s infinite}
.thumb.broken img{display:none}
.thumb.broken::after{content:"Image unavailable";position:absolute;inset:0;display:grid;place-items:center;color:var(--muted);font-size:.85rem;padding:8px;text-align:center}
@keyframes sh{from{transform:translateX(-100%)}to{transform:translateX(100%)}}
.meta{padding:10px 12px;display:flex;flex-direction:column;gap:2px;font-size:.85rem;min-width:0}
.meta strong{font-size:.9rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.meta span{color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
footer{margin-top:28px;text-align:center;color:var(--muted);font-size:.8rem}
.lightbox{position:fixed;inset:0;z-index:20;display:flex;flex-direction:column;background:rgba(5,8,14,.94);color:#f2f4f8;touch-action:pan-y}
.lightbox[hidden]{display:none}
.lb-top,.lb-bottom{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px clamp(10px,3vw,24px)}
.lb-bottom{flex-direction:column;align-items:center;text-align:center;gap:2px;padding-bottom:max(12px,env(safe-area-inset-bottom))}
.lb-stage{position:relative;flex:1;min-height:0;display:flex;align-items:center;justify-content:center;padding:0 clamp(48px,8vw,90px)}
.lb-stage img{max-width:100%;max-height:100%;object-fit:contain;display:block}
.lb-stage.loading::before{content:"Loading…";position:absolute;color:#aab3c2}
.lb-stage.broken img{display:none}
.lb-stage.broken::before{content:"Image unavailable";position:absolute;color:#aab3c2}
.lb-btn{min-width:44px;min-height:44px;border:1px solid rgba(255,255,255,.3);border-radius:10px;background:rgba(255,255,255,.1);color:#fff;cursor:pointer;font-size:1.2rem}
.lb-btn:hover{background:rgba(255,255,255,.22)}
.lb-nav{position:absolute;top:50%;transform:translateY(-50%)}
.lb-prev{left:clamp(4px,1.5vw,16px)}.lb-next{right:clamp(4px,1.5vw,16px)}
#lbName{font-weight:600;overflow-wrap:anywhere}
#lbInfo{color:#b9c1ce;font-size:.9rem}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
)GAL";

inline const char* const kBody = R"GAL(
<header class="topbar">
  <div class="brand"><span class="logo" aria-hidden="true">&#9635;</span><h1>Image Gallery</h1></div>
  <button id="themeToggle" class="btn" type="button" aria-pressed="false">Dark theme</button>
</header>
<main>
  <noscript><p class="empty">This gallery needs JavaScript (no internet connection required) to display and filter images.</p></noscript>
  <ul class="stats" id="stats" aria-label="Collection summary"></ul>
  <div class="chips" id="chips" aria-label="Quick filter by camera make"></div>
  <section class="controls" aria-label="Filters and sorting">
    <div class="field wide"><label for="q">Search</label><input id="q" type="search" placeholder="Filename, camera make, model, date" autocomplete="off"></div>
    <div class="field"><label for="make">Camera make</label><select id="make"></select></div>
    <div class="field"><label for="model">Camera model</label><select id="model"></select></div>
    <div class="field"><label for="on">Capture date (exact)</label><input id="on" type="date"></div>
    <div class="field"><label for="from">Date from</label><input id="from" type="date"></div>
    <div class="field"><label for="to">Date to</label><input id="to" type="date"></div>
    <div class="field"><label for="sort">Sort by</label>
      <select id="sort"><option value="date">Capture date</option><option value="name">Filename</option><option value="make">Camera make</option><option value="model">Camera model</option></select></div>
    <div class="field"><label for="dir">Order</label>
      <select id="dir"><option value="asc">Ascending</option><option value="desc">Descending</option></select></div>
  </section>
  <div class="resultbar">
    <div id="counter" role="status" aria-live="polite"></div>
    <button id="reset" class="btn" type="button">Reset filters</button>
  </div>
  <div id="empty" class="empty" hidden></div>
  <ul id="grid" class="grid"></ul>
  <footer>Generated @@GENERATED@@ &middot; works offline &middot; keep this file next to the camera folders</footer>
</main>
<div id="lightbox" class="lightbox" role="dialog" aria-modal="true" aria-label="Image viewer" hidden>
  <div class="lb-top"><span id="lbCount" aria-live="polite"></span><button id="lbClose" class="lb-btn" type="button" aria-label="Close viewer">&times;</button></div>
  <div class="lb-stage loading" id="lbStage">
    <button id="lbPrev" class="lb-btn lb-nav lb-prev" type="button" aria-label="Previous image">&#8249;</button>
    <img id="lbImg" alt="">
    <button id="lbNext" class="lb-btn lb-nav lb-next" type="button" aria-label="Next image">&#8250;</button>
  </div>
  <div class="lb-bottom"><div id="lbName"></div><div id="lbInfo"></div></div>
</div>
)GAL";

inline const char* const kJs1 = R"GAL(
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var UNKNOWN = 'Unknown';
  var isoRe = /^\d{4}-\d{2}-\d{2}$/;
  var root = document.documentElement;
  var items = [];
  try {
    var parsed = JSON.parse($('gallery-data').textContent);
    items = Array.isArray(parsed) ? parsed : [];
  } catch (e) { console.error('Could not read gallery data', e); }
  items = items.map(function (raw, i) {
    raw = raw || {};
    var it = { id: i, f: String(raw.f == null ? '' : raw.f), u: String(raw.u == null ? '' : raw.u),
      mk: String(raw.mk || UNKNOWN), md: String(raw.md || UNKNOWN), d: String(raw.d || UNKNOWN) };
    it.known = isoRe.test(it.d);
    it.s = (it.f + ' ' + it.mk + ' ' + it.md + ' ' + it.d).toLowerCase();
    return it;
  });

  var els = { make: $('make'), model: $('model'), on: $('on'), from: $('from'), to: $('to'), q: $('q'),
    sort: $('sort'), dir: $('dir'), grid: $('grid'), empty: $('empty'), counter: $('counter'),
    stats: $('stats'), chips: $('chips'), theme: $('themeToggle') };
  var state = { make: '', model: '', on: '', from: '', to: '', q: '', sort: 'date', dir: 'asc' };
  var visible = [];
  var collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

  /* ---- theme ---- */
  function applyTheme(t) {
    root.setAttribute('data-theme', t);
    els.theme.setAttribute('aria-pressed', String(t === 'dark'));
    els.theme.textContent = t === 'dark' ? 'Light theme' : 'Dark theme';
  }
  var saved = null;
  try { saved = localStorage.getItem('gallery-theme'); } catch (e) { /* storage may be blocked on file:// */ }
  applyTheme(saved || (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  els.theme.addEventListener('click', function () {
    var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    try { localStorage.setItem('gallery-theme', next); } catch (e) { /* ignore */ }
  });

  /* ---- helpers ---- */
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function uniqueSorted(list) {
    var seen = {}, out = [];
    list.forEach(function (v) { if (!Object.prototype.hasOwnProperty.call(seen, v)) { seen[v] = 1; out.push(v); } });
    return out.sort(collator.compare);
  }
  function fillSelect(sel, values, allLabel, current) {
    sel.textContent = '';
    var o = el('option', '', allLabel); o.value = ''; sel.appendChild(o);
    values.forEach(function (v) { var op = el('option', '', v); op.value = v; sel.appendChild(op); });
    sel.value = values.indexOf(current) >= 0 ? current : '';
    return sel.value;
  }
  function refreshModels() {
    var pool = state.make ? items.filter(function (it) { return it.mk === state.make; }) : items;
    state.model = fillSelect(els.model, uniqueSorted(pool.map(function (it) { return it.md; })), 'All models', state.model);
  }
  function pluralize(n, w) { return n + ' ' + w + (n === 1 ? '' : 's'); }

  /* ---- statistics ---- */
  function renderStats() {
    var makes = {}, models = {}, dates = [], missing = 0;
    items.forEach(function (it) {
      makes[it.mk] = (makes[it.mk] || 0) + 1; models[it.md] = 1;
      if (it.known) dates.push(it.d);
      if (it.mk === UNKNOWN || it.md === UNKNOWN || !it.known) missing++;
    });
    dates.sort();
    var range = dates.length ? (dates[0] === dates[dates.length - 1] ? dates[0] : dates[0] + ' \u2192 ' + dates[dates.length - 1]) : '\u2014';
    var cards = [[items.length, 'Total images'], [Object.keys(makes).length, 'Camera makes'],
      [Object.keys(models).length, 'Camera models'], [range, 'Capture date range'], [missing, 'With missing metadata']];
    els.stats.textContent = '';
    cards.forEach(function (c) { var li = el('li', 'stat'); li.appendChild(el('b', '', String(c[0]))); li.appendChild(el('span', '', c[1])); els.stats.appendChild(li); });
    els.chips.textContent = '';
    Object.keys(makes).sort(function (a, b) { return makes[b] - makes[a] || collator.compare(a, b); }).slice(0, 8).forEach(function (m) {
      var b = el('button', 'chip', m + ' (' + makes[m] + ')'); b.type = 'button'; b.dataset.make = m;
      b.setAttribute('aria-pressed', String(state.make === m)); els.chips.appendChild(b);
    });
  }
)GAL";

inline const char* const kJs2 = R"GAL(
  /* ---- filtering, sorting, rendering ---- */
  function cmp(a, b) {
    var r = 0;
    if (state.sort === 'date') {
      if (a.known !== b.known) return a.known ? -1 : 1;        /* unknown dates always last */
      r = a.d < b.d ? -1 : a.d > b.d ? 1 : 0;
    } else if (state.sort === 'make') r = collator.compare(a.mk, b.mk);
    else if (state.sort === 'model') r = collator.compare(a.md, b.md);
    else r = collator.compare(a.f, b.f);
    if (state.dir === 'desc') r = -r;
    return r || collator.compare(a.f, b.f) || a.id - b.id;
  }
  function applyFilters() {
    var terms = state.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
    var from = state.from, to = state.to;
    if (from && to && from > to) { var t = from; from = to; to = t; }
    visible = items.filter(function (it) {
      if (state.make && it.mk !== state.make) return false;
      if (state.model && it.md !== state.model) return false;
      if (state.on && !(it.known && it.d === state.on)) return false;
      if (from && !(it.known && it.d >= from)) return false;
      if (to && !(it.known && it.d <= to)) return false;
      for (var i = 0; i < terms.length; i++) if (it.s.indexOf(terms[i]) < 0) return false;
      return true;
    }).sort(cmp);
    render();
  }
  function card(it, idx) {
    var li = el('li', 'card');
    var b = el('button', 'thumb loading'); b.type = 'button'; b.dataset.index = String(idx);
    b.setAttribute('aria-label', 'Open ' + it.f);
    var img = document.createElement('img');
    img.loading = 'lazy'; img.decoding = 'async'; img.alt = it.f + (it.mk !== UNKNOWN ? ' \u2013 ' + it.mk + ' ' + it.md : '');
    img.addEventListener('load', function () { b.classList.remove('loading'); });
    img.addEventListener('error', function () { b.classList.remove('loading'); b.classList.add('broken'); });
    img.src = it.u;
    b.appendChild(img);
    var meta = el('div', 'meta');
    var name = el('strong', '', it.f); name.title = it.f;
    meta.appendChild(name);
    meta.appendChild(el('span', '', 'Make: ' + it.mk));
    meta.appendChild(el('span', '', 'Model: ' + it.md));
    meta.appendChild(el('span', '', 'Date: ' + it.d));
    li.appendChild(b); li.appendChild(meta);
    return li;
  }
  function render() {
    var frag = document.createDocumentFragment();
    visible.forEach(function (it, i) { frag.appendChild(card(it, i)); });
    els.grid.textContent = ''; els.grid.appendChild(frag);
    els.counter.textContent = 'Showing ' + visible.length + ' of ' + pluralize(items.length, 'image');
    els.empty.textContent = '';
    if (!items.length) {
      els.empty.appendChild(el('h2', '', 'No images yet'));
      els.empty.appendChild(el('p', '', 'No arranged images were found when this gallery was generated.'));
      els.empty.hidden = false;
    } else if (!visible.length) {
      els.empty.appendChild(el('h2', '', 'No images match your filters'));
      els.empty.appendChild(el('p', '', 'Try removing a filter or searching for something else.'));
      var r = el('button', 'btn primary', 'Reset filters'); r.type = 'button'; r.addEventListener('click', resetAll);
      els.empty.appendChild(r); els.empty.hidden = false;
    } else els.empty.hidden = true;
    Array.prototype.forEach.call(els.chips.children, function (c) { c.setAttribute('aria-pressed', String(c.dataset.make === state.make)); });
  }
  function resetAll() {
    state = { make: '', model: '', on: '', from: '', to: '', q: '', sort: 'date', dir: 'asc' };
    els.q.value = ''; els.on.value = ''; els.from.value = ''; els.to.value = '';
    els.sort.value = 'date'; els.dir.value = 'asc';
    fillSelect(els.make, uniqueSorted(items.map(function (it) { return it.mk; })), 'All makes', '');
    refreshModels(); applyFilters();
  }

  /* ---- control wiring ---- */
  var timer = null;
  els.q.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(function () { state.q = els.q.value; applyFilters(); }, 120); });
  els.make.addEventListener('change', function () { state.make = els.make.value; refreshModels(); applyFilters(); });
  els.model.addEventListener('change', function () { state.model = els.model.value; applyFilters(); });
  ['on', 'from', 'to', 'sort', 'dir'].forEach(function (k) {
    els[k].addEventListener('change', function () { state[k] = els[k].value; applyFilters(); });
  });
  $('reset').addEventListener('click', resetAll);
  els.chips.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('.chip') : null;
    if (!b) return;
    state.make = state.make === b.dataset.make ? '' : b.dataset.make;
    els.make.value = state.make; refreshModels(); applyFilters();
  });

  /* ---- lightbox ---- */
  var lb = { box: $('lightbox'), img: $('lbImg'), stage: $('lbStage'), name: $('lbName'), info: $('lbInfo'),
    count: $('lbCount'), idx: -1, opener: null };
  function showLb() {
    var it = visible[lb.idx]; if (!it) return;
    lb.stage.classList.add('loading'); lb.stage.classList.remove('broken');
    lb.img.alt = it.f; lb.img.src = it.u;
    lb.name.textContent = it.f;
    lb.info.textContent = it.mk + ' \u00b7 ' + it.md + ' \u00b7 ' + it.d;
    lb.count.textContent = (lb.idx + 1) + ' / ' + visible.length;
  }
  function openLb(i) {
    if (!visible.length) return;
    lb.idx = Math.max(0, Math.min(i, visible.length - 1)); lb.opener = document.activeElement;
    lb.box.hidden = false; document.body.classList.add('lb-open'); showLb(); $('lbClose').focus();
  }
  function closeLb() {
    lb.box.hidden = true; document.body.classList.remove('lb-open'); lb.img.removeAttribute('src');
    if (lb.opener && lb.opener.focus) lb.opener.focus();
  }
  function step(d) { if (visible.length) { lb.idx = (lb.idx + d + visible.length) % visible.length; showLb(); } }
  lb.img.addEventListener('load', function () { lb.stage.classList.remove('loading'); });
  lb.img.addEventListener('error', function () { lb.stage.classList.remove('loading'); lb.stage.classList.add('broken'); });
  els.grid.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('.thumb') : null;
    if (b) openLb(parseInt(b.dataset.index, 10));
  });
  $('lbClose').addEventListener('click', closeLb);
  $('lbPrev').addEventListener('click', function () { step(-1); });
  $('lbNext').addEventListener('click', function () { step(1); });
  lb.box.addEventListener('click', function (e) { if (e.target === lb.box || e.target === lb.stage) closeLb(); });
  document.addEventListener('keydown', function (e) {
    if (lb.box.hidden) return;
    if (e.key === 'Escape') closeLb();
    else if (e.key === 'ArrowLeft') step(-1);
    else if (e.key === 'ArrowRight') step(1);
    else if (e.key === 'Home') { lb.idx = 0; showLb(); }
    else if (e.key === 'End') { lb.idx = visible.length - 1; showLb(); }
    else if (e.key === 'Tab') {
      var f = lb.box.querySelectorAll('button'); if (!f.length) return;
      var first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    } else return;
    if (e.key !== 'Tab') e.preventDefault();
  });
  var tx = 0, ty = 0;
  lb.box.addEventListener('touchstart', function (e) { var t = e.changedTouches[0]; tx = t.clientX; ty = t.clientY; }, { passive: true });
  lb.box.addEventListener('touchend', function (e) {
    var t = e.changedTouches[0], dx = t.clientX - tx, dy = t.clientY - ty;
    if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.5) step(dx < 0 ? 1 : -1);
  }, { passive: true });

  /* ---- start ---- */
  renderStats();
  fillSelect(els.make, uniqueSorted(items.map(function (it) { return it.mk; })), 'All makes', '');
  refreshModels();
  applyFilters();
})();
)GAL";

}  // namespace gallery_template
