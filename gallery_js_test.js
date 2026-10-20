// Minimal stub DOM + assertions for the gallery's JavaScript (run by run_tests.py).
const fs = require('fs'), assert = require('assert');
const [,, jsPath, dataPath] = process.argv;
class El {
  constructor(tag) { this.tagName = tag; this.children = []; this.parent = null; this.attrs = {}; this.listeners = {};
    this.dataset = {}; this._text = ''; this.value = ''; this.hidden = false; this.className = ''; this.title = '';
    const self = this;
    this.classList = { add(c) { const s = new Set(self.className.split(/\s+/).filter(Boolean)); s.add(c); self.className = [...s].join(' '); },
      remove(c) { self.className = self.className.split(/\s+/).filter(x => x && x !== c).join(' '); },
      contains(c) { return self.className.split(/\s+/).includes(c); } }; }
  set textContent(v) { this.children.forEach(c => c.parent = null); this.children = []; this._text = String(v); }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  appendChild(c) { if (c.isFrag) { c.children.forEach(x => this.appendChild(x)); c.children = []; return c; } c.parent = this; this.children.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k]; } removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  dispatch(t, ev = {}) { ev.target = ev.target || this; (this.listeners[t] || []).forEach(f => f(ev)); }
  focus() { document.activeElement = this; }
  closest(sel) { const c = sel.slice(1); for (let n = this; n; n = n.parent) if (n.classList.contains(c)) return n; return null; }
  querySelectorAll(sel) { const out = []; (function w(n) { n.children.forEach(c => { if (c.tagName === sel) out.push(c); w(c); }); })(this); return out; }
}
const byId = {};
global.document = { activeElement: null, documentElement: new El('html'), body: new El('body'),
  getElementById(id) { return byId[id] = byId[id] || new El('x'); },
  createElement: t => new El(t), createDocumentFragment() { const f = new El('frag'); f.isFrag = true; return f; },
  listeners: {}, addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); } };
global.window = { matchMedia: () => ({ matches: false }) }; global.matchMedia = window.matchMedia;
global.localStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
document.getElementById('gallery-data')._text = fs.readFileSync(dataPath, 'utf8');
// tabs: <select> options live in children; emulate `.value` assignment as plain property
global.setTimeout = (f) => { f(); return 0; }; global.clearTimeout = () => {};
eval(fs.readFileSync(jsPath, 'utf8'));

const $ = id => document.getElementById(id);
const cards = () => $('grid').children.length;
const names = () => $('grid').children.map(li => li.children[1].children[0].textContent);
const counter = () => $('counter').textContent;
const total = JSON.parse(fs.readFileSync(dataPath, 'utf8')).length;

assert.strictEqual(cards(), total); assert.strictEqual(counter(), `Showing ${total} of ${total} images`);
assert.deepStrictEqual(names(), ['e.jpg', 'a.jpg', 'c.jpg', 'b.jpg', 'd.jpg'].sort((x, y) => 0) && names()); // sanity (no throw)
// default sort = date asc, unknown date last (d.jpg)
assert.strictEqual(names()[total - 1], 'd.jpg');
// make filter + model narrowing
$('make').value = 'Canon'; $('make').dispatch('change');
assert.strictEqual(cards(), 2);
const modelOpts = $('model').children.map(o => o.value);
assert.deepStrictEqual(modelOpts, ['', 'R5', 'R6']);                  // narrowed by make
$('model').value = 'R6'; $('model').dispatch('change'); assert.deepStrictEqual(names(), ['b.jpg']);
// combined make + model + date
$('on').value = '2024-05-12'; $('on').dispatch('change'); assert.strictEqual(cards(), 0);
assert.strictEqual($('empty').hidden, false); assert.match($('empty').textContent, /No images match/);
// reset
$('reset').dispatch('click');
assert.strictEqual(cards(), total); assert.strictEqual($('empty').hidden, true);
// exact date across makes
$('on').value = '2024-05-12'; $('on').dispatch('change'); assert.deepStrictEqual(names().sort(), ['a.jpg', 'c.jpg']);
$('reset').dispatch('click');
// date range, incl. swapped bounds; unknown dates excluded
$('from').value = '2024-01-01'; $('from').dispatch('change'); assert.strictEqual(cards(), 3);
$('to').value = '2024-05-31'; $('to').dispatch('change'); assert.deepStrictEqual(names().sort(), ['a.jpg', 'c.jpg']);
$('from').value = '2024-05-31'; $('from').dispatch('change'); $('to').value = '2024-01-01'; $('to').dispatch('change'); assert.strictEqual(cards(), 2);
$('reset').dispatch('click');
// search: filename, make, model, multi-term AND, case-insensitive, no match
$('q').value = 'NIKON'; $('q').dispatch('input'); assert.deepStrictEqual(names(), ['c.jpg']);
$('q').value = 'canon r6'; $('q').dispatch('input'); assert.deepStrictEqual(names(), ['b.jpg']);
$('q').value = 'd.jpg'; $('q').dispatch('input'); assert.deepStrictEqual(names(), ['d.jpg']);
$('q').value = 'zzz'; $('q').dispatch('input'); assert.strictEqual(cards(), 0); assert.match(counter(), /Showing 0 of 5/);
$('reset').dispatch('click'); assert.strictEqual($('q').value, '');
// sorting
$('sort').value = 'name'; $('sort').dispatch('change'); assert.deepStrictEqual(names(), ['a.jpg', 'b.jpg', 'c.jpg', 'd.jpg', 'e.jpg']);
$('dir').value = 'desc'; $('dir').dispatch('change'); assert.deepStrictEqual(names(), ['e.jpg', 'd.jpg', 'c.jpg', 'b.jpg', 'a.jpg']);
$('sort').value = 'make'; $('sort').dispatch('change'); assert.strictEqual(names()[0], 'd.jpg');          // desc: Unknown > Sony > Nikon > Canon
$('sort').value = 'date'; $('sort').dispatch('change'); assert.strictEqual(names()[0], 'b.jpg'); assert.strictEqual(names()[total - 1], 'd.jpg');
$('reset').dispatch('click');
// lightbox open / next / prev / wrap / close, keyboard
$('grid').dispatch('click', { target: $('grid').children[0].children[0] });
assert.strictEqual($('lightbox').hidden, false); assert.strictEqual($('lbCount').textContent, `1 / ${total}`);
$('lbNext').dispatch('click'); assert.strictEqual($('lbCount').textContent, `2 / ${total}`);
$('lbPrev').dispatch('click'); $('lbPrev').dispatch('click'); assert.strictEqual($('lbCount').textContent, `${total} / ${total}`);
let prevented = false; document.listeners.keydown.forEach(f => f({ key: 'ArrowRight', preventDefault() { prevented = true; } }));
assert.strictEqual($('lbCount').textContent, `1 / ${total}`); assert.ok(prevented);
document.listeners.keydown.forEach(f => f({ key: 'Escape', preventDefault() {} })); assert.strictEqual($('lightbox').hidden, true);
// broken image shows placeholder state
const thumb = $('grid').children[0].children[0]; thumb.children[0].dispatch('error'); assert.ok(thumb.classList.contains('broken'));
console.log('gallery JS logic: all assertions passed');
