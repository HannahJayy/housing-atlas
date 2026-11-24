// Static mode: answers the app's /api/... requests from pre-built JSON files (written by
// `python app.py export-static`), so Housing Atlas runs on any static web host with no Python server.
// Searching, ranking, CSV export, change calculations and map history are done here in the browser;
// the watchlist and saved views are kept in this browser's storage.

const CFG = window.HA_STATIC || {};
const LOCAL_USER = { id: 0, username: 'My places', is_admin: false, local: true };
const LAG = { M: { mom: 1, yoy: 12, chg_5y: 60, chg_10y: 120 }, Q: { mom: 1, yoy: 4, chg_5y: 20, chg_10y: 40 },
  A: { mom: null, yoy: 1, chg_5y: 5, chg_10y: 10 } };

// ---------------------------------------------------------------- files
const files = new Map();
function httpErr(msg, status) { const e = new Error(msg); e.status = status; return e; }
// Hosted copies store the data files gzip-compressed (name + '.gz', about 5x smaller) and unpack them here.
async function fetchJSON(path) {
  const gz = CFG.gz && path.startsWith('api/');
  const r = await fetch(gz ? path + '.gz' : path);
  if (!r.ok) throw httpErr(r.status === 404 ? 'Not found' : 'HTTP ' + r.status, r.status);
  if (!gz) return r.json();
  const buf = new Uint8Array(await r.arrayBuffer());
  if (buf[0] !== 0x1f || buf[1] !== 0x8b) return JSON.parse(new TextDecoder().decode(buf)); // already unpacked
  if (typeof DecompressionStream === 'undefined') throw httpErr('Please update your browser to open this page.', 500);
  const stream = new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip'));
  return JSON.parse(await new Response(stream).text());
}
function getFile(path) {
  if (!files.has(path)) {
    const p = fetchJSON(path);
    p.catch(() => files.delete(path));
    files.set(path, p);
  }
  return files.get(path);
}
// kind = map | region | hist, key = "<level>/<id>"
async function part(kind, key) {
  if (CFG.bundle) {
    const all = await getFile('api/' + kind + '-' + key.split('/')[0] + '.json');
    if (!all[key]) throw httpErr('Not found', 404);
    return all[key];
  }
  return getFile('api/' + kind + '/' + key + '.json');
}

let metaP = null;
function meta() { if (!metaP) metaP = getFile('api/meta.json'); return metaP; }
async function metricById(id) {
  const m = await meta();
  if (!m._byId) m._byId = Object.fromEntries(m.catalog.metrics.map((x) => [x.id, x]));
  return m._byId[id];
}

const geoRows = new Map();
async function geos(level) {
  if (!geoRows.has(level)) {
    geoRows.set(level, getFile('api/geos/' + level + '.json').then((d) => {
      const out = {};
      for (const [gid, row] of Object.entries(d.r)) {
        const o = {};
        d.f.forEach((k, i) => { o[k] = row[i]; });
        out[gid] = o;
      }
      return { rows: out, bbox: d.bbox || {} };
    }).catch(() => ({ rows: {}, bbox: {} })));
  }
  return geoRows.get(level);
}

// ---------------------------------------------------------------- browser storage (memory fallback)
const mem = {};
const store = {
  get(k, d) {
    try { const v = localStorage.getItem(k); if (v) return JSON.parse(v); } catch (e) { /* storage blocked */ }
    return k in mem ? mem[k] : d;
  },
  set(k, v) { mem[k] = v; try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* memory only */ } },
};
const watchItems = () => store.get('ha-watchlist', []);
const viewItems = () => store.get('ha-views', []);
const isWatched = (level, id) => watchItems().some((w) => w.level === level && w.id === id);

// ---------------------------------------------------------------- numbers & periods (mirror housing/util.py)
const fin = (x) => typeof x === 'number' && Number.isFinite(x);
export function smartRound(x) {
  if (!fin(x)) return null;
  const a = Math.abs(x);
  const r = (d) => Math.round(x * 10 ** d) / 10 ** d;
  if (a >= 1000) return Math.round(x);
  if (a >= 100) return r(1);
  if (a >= 1) return r(2);
  if (a >= 0.01) return r(4);
  return r(6);
}
export function periodStr(freq, i) {
  if (i === null || i === undefined) return null;
  if (freq === 'M') return Math.floor(i / 12) + '-' + String(i % 12 + 1).padStart(2, '0');
  if (freq === 'Q') return Math.floor(i / 4) + '-Q' + (i % 4 + 1);
  return String(i);
}
export function parsePeriod(freq, s) {
  if (!s) return null;
  s = String(s);
  const mm = s.match(/^(\d{4})-(\d{1,2})/);
  const month = mm ? (+mm[1]) * 12 + (+mm[2]) - 1 : null;
  if (freq === 'M') return month;
  if (freq === 'Q') {
    const q = s.match(/^(\d{4})-?Q([1-4])$/);
    if (q) return (+q[1]) * 4 + (+q[2]) - 1;
    return month === null ? null : Math.floor(month / 12) * 4 + Math.floor((month % 12) / 3);
  }
  const y = s.match(/^(\d{4})/);
  return y ? +y[1] : null;
}
function normName(s) {
  if (s === null || s === undefined) return '';
  s = String(s).normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase();
  s = s.replace(/&/g, ' and ').replace(/\bsaint\b/g, 'st').replace(/\bste\.?(?![a-z0-9])/g, 'ste').replace(/\bst\./g, 'st');
  s = s.replace(/[^a-z0-9 ]+/g, ' ');
  return s.replace(/\s+/g, ' ').trim();
}

// ---------------------------------------------------------------- transforms (mirror housing/engine.py)
function chg(a, b, mode) {
  if (!fin(a) || !fin(b)) return NaN;
  if (mode === 'diff') return a - b;
  if (b === 0) return NaN;
  return (a / b - 1) * 100;
}
const at = (s, i) => { const k = i - s.start; return k >= 0 && k < s.v.length ? s.v[k] : NaN; };
function vsPreBase(s) {
  const out = new Map();
  if (s.freq === 'M' || s.freq === 'Q') {
    const per = s.freq === 'M' ? 12 : 4;
    for (let j = 0; j < per; j++) {
      const xs = [2017, 2018, 2019].map((y) => at(s, y * per + j)).filter(fin);
      if (xs.length) out.set(j, xs.reduce((a, b) => a + b, 0) / xs.length);
    }
  } else {
    const b = at(s, 2019);
    if (fin(b)) out.set(0, b);
  }
  return out.size ? out : null;
}
const preKey = (s, p) => (s.freq === 'M' ? ((p % 12) + 12) % 12 : s.freq === 'Q' ? ((p % 4) + 4) % 4 : 0);

export function transform(s, tf, mode) {
  if (!tf || tf === 'level') return s;
  const v = s.v;
  const n = v.length;
  const out = new Array(n).fill(NaN);
  const lags = LAG[s.freq] || {};
  if (tf in lags) {
    const lag = lags[tf];
    if (!lag) return null;
    for (let k = lag; k < n; k++) out[k] = chg(v[k], v[k - lag], mode);
    return { freq: s.freq, start: s.start, v: out };
  }
  if (tf === 'from_peak') {
    let peak = NaN;
    for (let k = 0; k < n; k++) {
      if (fin(v[k]) && (!fin(peak) || v[k] > peak)) peak = v[k];
      out[k] = chg(v[k], peak, mode);
    }
    return { freq: s.freq, start: s.start, v: out };
  }
  if (tf === 'vs_pre') {
    const base = vsPreBase(s);
    if (!base) return null;
    for (let k = 0; k < n; k++) {
      const b = base.get(preKey(s, s.start + k));
      if (b !== undefined) out[k] = chg(v[k], b, mode);
    }
    return { freq: s.freq, start: s.start, v: out };
  }
  return null;
}

function valueAt(s, tf, mode, p) {
  const k = p - s.start;
  const v = s.v;
  if (k < 0 || k >= v.length) return NaN;
  if (!tf || tf === 'level') return v[k];
  const lags = LAG[s.freq] || {};
  if (tf in lags) {
    const lag = lags[tf];
    return lag && k >= lag ? chg(v[k], v[k - lag], mode) : NaN;
  }
  if (tf === 'from_peak') {
    let peak = NaN;
    for (let j = 0; j <= k; j++) if (fin(v[j]) && (!fin(peak) || v[j] > peak)) peak = v[j];
    return chg(v[k], peak, mode);
  }
  if (tf === 'vs_pre') {
    if (s._base === undefined) s._base = vsPreBase(s);
    if (!s._base) return NaN;
    const b = s._base.get(preKey(s, p));
    return b === undefined ? NaN : chg(v[k], b, mode);
  }
  return NaN;
}
const toNums = (arr) => arr.map((x) => (x === null ? NaN : x));

// ---------------------------------------------------------------- endpoints
async function apiMeta() {
  const m = await meta();
  const out = Object.assign({}, m, { user: LOCAL_USER, can_admin: false, update: { running: false, log: [] } });
  delete out._byId;
  return out;
}

async function geonames(level) {
  const g = await geos(level);
  const names = {}, pop = {};
  for (const [gid, o] of Object.entries(g.rows)) {
    names[gid] = o.name;
    if (o.pop) pop[gid] = o.pop;
  }
  return { level, names, pop, bbox: level === 'zip' ? {} : g.bbox };
}

let searchIdx = null;
async function search(text) {
  text = (text || '').trim();
  if (text.length < 2 && !/^\d+$/.test(text)) return { results: [] };
  if (!searchIdx) searchIdx = await getFile('api/search.json');
  const t = normName(text);
  const toks = t.split(' ');
  const bonus = { state: 0.4, metro: 0.3, city: 0.25, county: 0.2, zip: 0 };
  const res = [];
  for (const [n, level, gid, disp, pop] of searchIdx) {
    let score = 0;
    if (level === 'zip' && /^\d+$/.test(t)) score = gid.startsWith(t) ? 3 : 0;
    else if (n === t) score = 4;
    else if (n.startsWith(t)) score = 3;
    else if ((' ' + n).includes(' ' + t)) score = 2;
    else if (toks.every((tok) => n.includes(tok))) score = 1;
    if (score) res.push([score + bonus[level], pop || 0, level, gid, disp]);
  }
  res.sort((a, b) => (b[0] - a[0]) || (b[1] - a[1]));
  const seen = new Set();
  const out = [];
  for (const [, , level, gid, disp] of res) {
    const key = level + '|' + gid + '|' + disp;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ level: level === 'city' ? 'county' : level, id: gid, name: disp, kind: level });
    if (out.length >= 15) break;
  }
  return { results: out };
}

async function snapshot(metric, tf, level) {
  try {
    const f = await part('map', level + '/' + metric);
    const e = f[tf];
    return e ? [e[0], e[1]] : [null, {}];
  } catch (e) { return [null, {}]; }
}

const histCache = new Map();
async function history(level, metric) {
  const key = level + '/' + metric;
  if (!histCache.has(key)) {
    histCache.set(key, part('hist', key).then((H) => {
      const s = {};
      for (const [gid, [start, vals]] of Object.entries(H.s)) s[gid] = { freq: H.freq, start, v: toNums(vals) };
      return { freq: H.freq, s };
    }));
    histCache.get(key).catch(() => histCache.delete(key));
  }
  return histCache.get(key);
}

async function mapLayer(q) {
  const metric = q.metric || 'zhvi';
  const tf = q.tf || 'level';
  const level = q.level || 'county';
  const m = await metricById(metric);
  if (!m) throw httpErr('unknown metric ' + metric, 400);
  if (!m.transforms.includes(tf)) throw httpErr('unknown view ' + tf + ' for ' + metric, 400);
  if (!q.date) {
    const [period, values] = await snapshot(metric, tf, level);
    return { metric, tf, level, period, values };
  }
  let H;
  try { H = await history(level, metric); } catch (e) { return { metric, tf, level, period: null, values: {} }; }
  const p = parsePeriod(H.freq, q.date);
  const values = {};
  for (const [gid, s] of Object.entries(H.s)) {
    const v = valueAt(s, tf, m.change, p);
    if (fin(v)) values[gid] = smartRound(v);
  }
  return { metric, tf, level, period: periodStr(H.freq, p), values };
}

async function dates(q) {
  const d = await getFile('api/dates.json').catch(() => ({}));
  return d[q.metric + '|' + q.level] || { freq: null, start: null, end: null };
}

async function regionFile(level, id) {
  try { return await part('region', level + '/' + id); } catch (e) { throw httpErr('region not found', 404); }
}

async function region(q) {
  const r = await regionFile(q.level, q.id);
  const out = Object.assign({}, r, { watched: isWatched(q.level, q.id) });
  delete out.series;
  return out;
}

async function series(q) {
  const level = q.level;
  const tf = q.tf || 'level';
  const r = await regionFile(level, q.id);
  const out = {};
  for (const mid of (q.metrics || 'zhvi').split(',')) {
    const raw = r.series && r.series[mid];
    const m = await metricById(mid);
    if (!raw || !m) continue;
    const s = { freq: raw[0], start: raw[1], v: toNums(raw[2]) };
    const t = tf !== 'level' && m.transforms.includes(tf) ? transform(s, tf, m.change) : s;
    if (!t) continue;
    const points = [];
    t.v.forEach((x, k) => { if (fin(x)) points.push([periodStr(t.freq, t.start + k), smartRound(x)]); });
    out[mid] = { freq: t.freq, points };
  }
  return { level, id: q.id, tf, series: out };
}

async function rankRows(q) {
  const level = q.level || 'metro';
  const cols = [];
  for (const c of (q.cols || 'zhvi:level').split(',')) {
    if (!c) continue;
    const [mid, tfRaw] = c.split(':');
    const m = await metricById(mid);
    const tf = tfRaw || 'level';
    if (m && m.transforms.includes(tf)) cols.push([mid, tf]);
  }
  if (!cols.length) throw httpErr('no valid columns', 400);
  cols.splice(16);
  const snaps = await Promise.all(cols.map(([mid, tf]) => snapshot(mid, tf, level)));
  const g = (await geos(level)).rows;
  const minPop = parseFloat(q.min_pop || 0) || 0;
  const text = normName(q.q || '');
  const ids = new Set(Object.keys(g));
  for (const [, d] of snaps) for (const k of Object.keys(d)) ids.add(k);
  const rows = [];
  for (const gid of ids) {
    const o = g[gid] || { name: gid };
    if (q.state && o.state !== q.state) continue;
    if (q.metro && o.metro !== q.metro) continue;
    if (q.county && o.county !== q.county) continue;
    if (q.lsad && o.lsad !== q.lsad) continue;
    if (minPop && (o.pop || 0) < minPop) continue;
    if (text && !normName(o.name).includes(text)) continue;
    const vals = snaps.map(([, d]) => (d[gid] === undefined ? null : d[gid]));
    if (vals.every((v) => v === null)) continue;
    rows.push({ id: gid, name: o.name || gid, state: o.state || null, pop: o.pop || null, v: vals });
  }
  const sort = q.sort;
  const desc = (q.desc === undefined ? '1' : q.desc) !== '0';
  let si = 0;
  if (sort) {
    const [smid, stf] = sort.split(':');
    cols.forEach(([mid, tf], i) => { if (mid === smid && tf === (stf || 'level')) si = i; });
  }
  const nullLast = (a, b, fa, fb) => (a === null) - (b === null) || (a === null ? 0 : (desc ? fb - fa : fa - fb));
  if (sort === 'name') rows.sort((a, b) => (desc ? -1 : 1) * a.name.localeCompare(b.name));
  else if (sort === 'pop') rows.sort((a, b) => nullLast(a.pop, b.pop, a.pop || 0, b.pop || 0));
  else rows.sort((a, b) => nullLast(a.v[si], b.v[si], a.v[si], b.v[si]));
  return { level, cols, snaps, rows };
}

async function rankings(q) {
  const { level, cols, snaps, rows } = await rankRows(q);
  const limit = Math.max(1, Math.min(1000, parseInt(q.limit || '100', 10) || 100));
  const offset = Math.max(0, parseInt(q.offset || '0', 10) || 0);
  return { level, cols: cols.map((c) => c.join(':')), periods: snaps.map((s) => s[0]), total: rows.length, offset,
    rows: rows.slice(offset, offset + limit) };
}

async function exportCsv(q) {
  const { cols, snaps, rows } = await rankRows(q);
  const m = await meta();
  const cell = (x) => { const s = x === null || x === undefined ? '' : String(x); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const head = ['id', 'name', 'state', 'population'];
  for (let i = 0; i < cols.length; i++) {
    const mm = await metricById(cols[i][0]);
    head.push(mm.name + ' (' + (m.catalog.transforms[cols[i][1]] || cols[i][1]) + ') [' + (snaps[i][0] || '') + ']');
  }
  const lines = [head.map(cell).join(',')];
  for (const r of rows) lines.push([r.id, r.name, r.state || '', r.pop || ''].concat(r.v).map(cell).join(','));
  return lines.join('\r\n') + '\r\n';
}

async function me() {
  return { user: LOCAL_USER, can_admin: false, users_exist: true, watchlist: watchItems(), views: viewItems() };
}

async function watchlist() {
  const items = watchItems().map((w) => Object.assign({}, w));
  for (const it of items) {
    const g = (await geos(it.level)).rows[it.id];
    it.name = g ? g.name : it.id;
  }
  return { watchlist: items };
}

// ---------------------------------------------------------------- public entry points
export async function staticGet(path) {
  const [p, qs] = path.split('?');
  const q = Object.fromEntries(new URLSearchParams(qs || ''));
  switch (p) {
    case '/api/meta': return apiMeta();
    case '/api/auth/me': return me();
    case '/api/watchlist': return watchlist();
    case '/api/update/status': return { running: false, log: [] };
    case '/api/geonames': return geonames(q.level || 'county');
    case '/api/search': return search(q.q);
    case '/api/map': return mapLayer(q);
    case '/api/dates': return dates(q);
    case '/api/series': return series(q);
    case '/api/region': return region(q);
    case '/api/rankings': return rankings(q);
    case '/api/export.csv': return exportCsv(q);
    case '/api/national': case '/api/sources': case '/api/methodology': case '/api/settings':
      return getFile('api/' + p.slice(5) + '.json');
    default: throw httpErr('Not available in the web version', 404);
  }
}

export async function staticPost(path, body) {
  body = body || {};
  if (path === '/api/watchlist' || path === '/api/watchlist/remove') {
    const items = watchItems().filter((w) => !(w.level === body.level && w.id === body.id));
    if (path === '/api/watchlist') items.unshift({ level: body.level, id: body.id, added: new Date().toISOString().slice(0, 10) });
    store.set('ha-watchlist', items);
    return { ok: true, watched: path === '/api/watchlist' };
  }
  if (path === '/api/views') {
    const items = viewItems();
    items.unshift({ id: Date.now(), name: body.name || 'Saved view', state: body.state || {},
      created: new Date().toISOString().slice(0, 16).replace('T', ' ') });
    store.set('ha-views', items);
    return { ok: true };
  }
  if (path === '/api/views/remove') {
    store.set('ha-views', viewItems().filter((v) => v.id !== body.id));
    return { ok: true };
  }
  if (path === '/api/auth/logout') return { ok: true };
  throw httpErr('This web version is read-only. Run Housing Atlas on your computer to update data or change settings.', 400);
}
