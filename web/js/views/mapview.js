// Interactive choropleth map page.

import { api, post, geo } from '../api.js';
import { h, clear, seg, toast, debounce, buildQuery } from '../ui.js';
import { SlippyMap, decodeFeatures } from '../map.js';
import { lineChart } from '../chart.js';
import { openMetricPicker } from '../picker.js';
import {
  STATE, metric, availableAt, fmtAny, fmtVal, fmtChange, deltaClass, makeScale, legendItems, isDark,
  LEVEL_NAMES, LEVEL_PLURAL, SRC_NAMES, periodLabel, periodToTime, fmtPop,
} from '../fmt.js';
import { APP, navigate, pollUpdate } from '../app.js';

const LEVELS = ['state', 'metro', 'county', 'zip'];
const ZIP_MIN_ZOOM = 7;
const KEY_METRICS = ['zhvi', 'overvalued', 'forecast_12m', 'inventory', 'price_cut_share', 'dom', 'payment',
  'payment_to_income', 'rent', 'population'];

export async function render(root, params, app) {
  const meta = app.meta;
  const q = params.query;
  const saved = (() => { try { return JSON.parse(localStorage.getItem('ha-map') || '{}'); } catch (e) { return {}; } })();
  const st = {
    metric: q.metric || saved.metric || 'zhvi',
    tf: q.tf || saved.tf || null,
    level: q.level || saved.level || 'county',
    date: q.date || null,
    basemap: (window.HA_STATIC && window.HA_STATIC.basemap === false) ? 'none' : (q.basemap || saved.basemap || 'auto'),
    values: {}, period: null, scale: null, names: {}, pops: {}, selected: null,
  };
  if (!metric(st.metric)) st.metric = 'zhvi';
  if (!LEVELS.includes(st.level)) st.level = 'county';
  const m0 = metric(st.metric);
  if (!st.tf || !m0.transforms.includes(st.tf)) st.tf = st.metric === 'zhvi' && !q.tf && !saved.tf ? 'yoy' : m0.default_tf;

  const page = h('div', { class: 'map-page' + (document.getElementById('update-banner').hidden ? '' : ' with-banner') });
  const canvasBox = h('div', { class: 'map-canvas' });
  const panel = h('div', { class: 'map-panel' });
  const tip = h('div', { class: 'map-tip', hidden: true });
  const msg = h('div', { class: 'map-msg', hidden: true });
  const drawer = h('div', { class: 'region-drawer', hidden: true });
  const attrib = h('div', { class: 'map-attrib' });
  const tools = h('div', { class: 'map-tools' },
    h('button', { type: 'button', title: 'Zoom in', 'aria-label': 'Zoom in', onclick: () => map.zoomBy(1) }, '+'),
    h('button', { type: 'button', title: 'Zoom out', 'aria-label': 'Zoom out', onclick: () => map.zoomBy(-1) }, '−'),
    h('button', { type: 'button', title: 'Reset view', 'aria-label': 'Reset view', style: { fontSize: '14px' },
      onclick: () => map.fitBounds([-125, 24.5, -66.5, 49.5], { leftInset: window.innerWidth > 720 ? 350 : 0 }) }, '⤢'));
  page.append(canvasBox, panel, tools, tip, msg, drawer, attrib);
  if (window.innerWidth <= 720 && !q.metric) panel.classList.add('collapsed');
  root.appendChild(page);

  const view = { lon: +q.lon || saved.lon || -96.5, lat: +q.lat || saved.lat || 38.6, z: +q.z || saved.z || null };
  const map = new SlippyMap(canvasBox, {
    lon: view.lon, lat: view.lat, zoom: view.z || (window.innerWidth < 720 ? 2.6 : 3.7),
    ariaLabel: 'Choropleth map of housing data',
    onHover: (id, x, y) => showTip(id, x, y),
    onClick: (id) => { if (id) openRegion(st.level, id); else closeDrawer(); },
    onMoveEnd: () => { syncUrl(); if (st.level === 'zip') loadZipChunks(); },
  });
  applyTheme();

  // ------------------------------------------------------------------ data loading
  const featureCache = {};
  let zipIndex = null;
  const zipChunks = new Map();
  let stateOverlay = null;

  async function loadShapes() {
    msg.hidden = true;
    if (!meta.shapes || !meta.shapes.county) {
      map.setFeatures([]);
      showMsg('Map shapes not downloaded yet');
      return;
    }
    if (!stateOverlay) {
      try { stateOverlay = decodeFeatures(await geo('/geo/state.json')); } catch (e) { stateOverlay = []; }
    }
    map.setOverlays(st.level === 'state' ? [] : [{ features: stateOverlay, width: st.level === 'zip' ? 1.4 : 1.1 }]);
    if (st.level === 'zip') {
      map.setFeatures([]);
      if (!zipIndex) {
        try { zipIndex = (await geo('/geo/zip/index.json')).chunks; } catch (e) { zipIndex = {}; }
      }
      loadZipChunks();
      return;
    }
    if (!featureCache[st.level]) {
      showMsg('Loading ' + LEVEL_PLURAL[st.level].toLowerCase() + '…');
      try { featureCache[st.level] = decodeFeatures(await geo('/geo/' + st.level + '.json')); } catch (e) { featureCache[st.level] = []; }
      msg.hidden = true;
    }
    map.setFeatures(featureCache[st.level]);
  }

  let zipLoading = 0;
  async function loadZipChunks() {
    if (st.level !== 'zip' || !zipIndex) return;
    if (map.z < ZIP_MIN_ZOOM) {
      map.setFeatures([]);
      showMsg('Zoom in to see ZIP codes (or search for one)');
      return;
    }
    const [x0, y0, x1, y1] = map.qBounds();
    const need = Object.entries(zipIndex).filter(([k, b]) => !(b[2] < x0 || b[0] > x1 || b[3] < y0 || b[1] > y1)).map(([k]) => k);
    const missing = need.filter((k) => !zipChunks.has(k)).slice(0, 40);
    const updateFeatures = () => {
      const feats = [];
      for (const k of need) { const f = zipChunks.get(k); if (f && f.length) feats.push(...f); }
      map.setFeatures(feats);
    };
    if (missing.length) {
      showMsg('Loading ZIP codes…');
      zipLoading++;
      await Promise.all(missing.map(async (k) => {
        zipChunks.set(k, []);
        try { zipChunks.set(k, decodeFeatures(await geo('/geo/zip/' + k + '.json'))); } catch (e) { zipChunks.delete(k); }
      }));
      zipLoading--;
    }
    if (!zipLoading) msg.hidden = true;
    updateFeatures();
  }

  async function loadNames() {
    if (st.names[st.level]) return;
    try {
      const r = await api('/api/geonames?level=' + st.level, { cache: true });
      st.names[st.level] = r.names;
      st.pops[st.level] = r.pop;
    } catch (e) { st.names[st.level] = {}; st.pops[st.level] = {}; }
  }

  let reqId = 0;
  async function loadValues() {
    const id = ++reqId;
    const m = metric(st.metric);
    if (!availableAt(st.metric, st.level)) {
      st.values = {}; st.period = null; colorize(); drawPanel();
      return;
    }
    const url = '/api/map' + buildQuery({ metric: st.metric, tf: st.tf, level: st.level, date: st.date });
    canvasBox.style.opacity = '0.75';
    try {
      const r = await api(url, { cache: true });
      if (id !== reqId) return;
      st.values = r.values || {};
      st.period = r.period;
    } catch (e) {
      st.values = {}; st.period = null;
      toast(e.message);
    }
    canvasBox.style.opacity = '';
    colorize();
    drawPanel();
  }

  function colorize() {
    const m = metric(st.metric);
    st.scale = makeScale(Object.values(st.values), m, st.tf);
    const colors = new Map();
    for (const [gid, v] of Object.entries(st.values)) {
      const c = st.scale.color(v);
      if (c) colors.set(gid, c);
    }
    map.setTheme({ nodata: st.scale.nodata });
    map.setColors(colors);
  }

  // ------------------------------------------------------------------ panel
  function drawPanel() {
    const m = metric(st.metric);
    clear(panel);
    const collapsed = panel.classList.contains('collapsed');
    panel.appendChild(h('div', { class: 'panel-title' },
      h('h2', null, 'Housing map'),
      h('button', { class: 'btn btn-small panel-toggle', type: 'button',
        onclick: () => { panel.classList.toggle('collapsed'); drawPanel(); } }, collapsed ? 'Show controls' : 'Hide')));
    if (!meta.has_data) {
      panel.appendChild(welcomeBlock());
      return;
    }
    panel.appendChild(h('button', { class: 'metric-btn', type: 'button', onclick: () => openMetricPicker({
      level: st.level, current: st.metric, onPick: (id) => setMetric(id) }) },
      h('span', null, h('div', { class: 'name' }, m.name),
        h('div', { class: 'cat' }, (STATE.cats.find((c) => c.id === m.cat) || {}).name + ' · ' + (SRC_NAMES[m.src] || m.src))),
      h('span', { 'aria-hidden': 'true' }, '▾')));
    panel.appendChild(seg(m.transforms.map((t) => ({ value: t, label: STATE.transforms[t] || t })), st.tf,
      (v) => { st.tf = v; st.date = null; update(); }, { label: 'Measure' }));
    panel.appendChild(seg(LEVELS.map((l) => ({ value: l, label: LEVEL_NAMES[l], disabled: !availableAt(st.metric, l),
      title: availableAt(st.metric, l) ? null : 'Not available for ' + LEVEL_PLURAL[l] })), st.level,
      (v) => setLevel(v), { label: 'Geography' }));
    panel.appendChild(h('div', { class: 'metric-desc' }, m.desc));
    if (!availableAt(st.metric, st.level)) {
      panel.appendChild(h('div', { class: 'card', style: { padding: '10px' } },
        'This metric isn’t available for ' + LEVEL_PLURAL[st.level].toLowerCase() + '. Available: ' +
        (STATE.available[st.metric] || []).map((l) => LEVEL_PLURAL[l]).join(', ') + '.'));
      return;
    }
    // legend
    const leg = h('div', { class: 'legend' });
    const items = st.scale ? legendItems(st.scale, m, st.tf) : [];
    const cls = h('div', { class: 'classes' });
    for (const it of items) cls.append(h('span', { class: 'sw', style: { background: it.color } }), h('span', null, it.label));
    cls.append(h('span', { class: 'sw', style: { background: st.scale ? st.scale.nodata : '#ddd' } }), h('span', { class: 'muted' }, 'No data'));
    leg.append(h('div', { class: 'row' }, h('b', null, STATE.transforms[st.tf]), h('span', { class: 'spacer' }),
      h('span', { class: 'muted small' }, st.period ? periodLabel(st.period) : '')), cls);
    panel.appendChild(leg);
    // stats
    const vals = Object.values(st.values).filter((v) => v !== null && isFinite(v)).sort((a, b) => a - b);
    if (vals.length) {
      const med = vals[Math.floor(vals.length / 2)];
      panel.appendChild(h('div', { class: 'map-stats' },
        h('div', null, 'Median', h('b', null, fmtAny(med, m, st.tf, { compact: true }))),
        h('div', null, 'Lowest', h('b', null, fmtAny(vals[0], m, st.tf, { compact: true }))),
        h('div', null, 'Highest', h('b', null, fmtAny(vals[vals.length - 1], m, st.tf, { compact: true })))));
      panel.appendChild(topList(m));
    }
    panel.appendChild(timeControl());
    if (!(window.HA_STATIC && window.HA_STATIC.basemap === false)) {
      panel.appendChild(h('div', { class: 'row' }, h('span', { class: 'small muted' }, 'Basemap'),
        seg([{ value: 'auto', label: 'Auto' }, { value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' },
          { value: 'none', label: 'None' }], st.basemap, (v) => { st.basemap = v; applyTheme(); syncUrl(); drawPanel(); })));
    }
    const actions = h('div', { class: 'row' },
      h('a', { class: 'btn btn-small', href: '#/rankings' + buildQuery({ level: st.level, cols: st.metric + ':' + st.tf, sort: st.metric + ':' + st.tf }) }, 'Rank these'),
      APP.user ? h('button', { class: 'btn btn-small', type: 'button', onclick: saveView }, 'Save view') : null);
    panel.appendChild(actions);
  }

  function topList(m) {
    const names = st.names[st.level] || {};
    const entries = Object.entries(st.values).filter(([, v]) => v !== null && isFinite(v));
    if (entries.length < 6) return h('div');
    entries.sort((a, b) => b[1] - a[1]);
    const mk = (title, list) => h('div', null, h('div', { class: 'small muted', style: { fontWeight: 650, margin: '2px 0' } }, title),
      h('div', { class: 'kv' }, list.flatMap(([gid, v]) => [
        h('a', { class: 'k', href: '#', onclick: (e) => { e.preventDefault(); openRegion(st.level, gid, true); } }, names[gid] || gid),
        h('span', { class: 'v' }, fmtAny(v, m, st.tf, { compact: true }))])));
    const det = h('details', null, h('summary', { class: 'small', style: { cursor: 'pointer', color: 'var(--accent)' } }, 'Highest & lowest'),
      h('div', { class: 'grid', style: { gap: '8px', marginTop: '6px' } }, mk('Highest', entries.slice(0, 5)), mk('Lowest', entries.slice(-5).reverse())));
    return det;
  }

  let dates = null;
  function timeControl() {
    const box = h('div', null);
    const m = metric(st.metric);
    const row = h('div', { class: 'time-row' });
    box.appendChild(h('div', { class: 'small muted', style: { fontWeight: 650 } }, 'History'));
    box.appendChild(row);
    const fill = async () => {
      if (!dates || dates.key !== st.metric + st.level) {
        try { dates = await api('/api/dates?metric=' + st.metric + '&level=' + st.level, { cache: true }); dates.key = st.metric + st.level; } catch (e) { dates = null; }
      }
      clear(row);
      if (!dates || !dates.start || !dates.end) { row.appendChild(h('span', { class: 'small muted' }, 'No history')); return; }
      const toIdx = (p) => {
        if (dates.freq === 'A') return +p.slice(0, 4);
        if (dates.freq === 'Q') { const [y, qq] = p.split('-Q'); return +y * 4 + (+qq - 1); }
        const [y, mm] = p.split('-'); return +y * 12 + (+mm - 1);
      };
      const toStr = (i) => {
        if (dates.freq === 'A') return String(i);
        if (dates.freq === 'Q') return Math.floor(i / 4) + '-Q' + (i % 4 + 1);
        return Math.floor(i / 12) + '-' + String(i % 12 + 1).padStart(2, '0');
      };
      const lo = toIdx(dates.start), hi = toIdx(dates.end);
      const cur = st.date ? toIdx(st.date) : hi;
      const label = h('span', { class: 'small tabular', style: { minWidth: '70px', textAlign: 'right' } }, st.date ? periodLabel(st.date) : 'Latest');
      const slider = h('input', { type: 'range', min: lo, max: hi, value: cur, 'aria-label': 'Map date' });
      const go = debounce(() => { const v = +slider.value; st.date = v >= hi ? null : toStr(v); update(false); }, 250);
      slider.addEventListener('input', () => { const v = +slider.value; label.textContent = v >= hi ? 'Latest' : periodLabel(toStr(v)); go(); });
      let playing = null;
      const play = h('button', { class: 'btn btn-small', type: 'button', title: 'Animate through history', onclick: () => {
        if (playing) { clearInterval(playing); playing = null; play.textContent = '▶'; return; }
        play.textContent = '❚❚';
        let v = (+slider.value >= hi) ? lo : +slider.value;
        const step = dates.freq === 'M' ? 6 : 1;
        playing = setInterval(() => {
          v = Math.min(hi, v + step);
          slider.value = v; label.textContent = v >= hi ? 'Latest' : periodLabel(toStr(v));
          st.date = v >= hi ? null : toStr(v);
          update(false);
          if (v >= hi) { clearInterval(playing); playing = null; play.textContent = '▶'; }
        }, 900);
      } }, '▶');
      row.append(play, slider, label);
    };
    fill();
    return box;
  }

  function welcomeBlock() {
    const running = meta.update && meta.update.running;
    return h('div', { class: 'card', style: { padding: '12px' } },
      h('h3', null, 'Welcome! Let’s download the data'),
      h('p', { class: 'secondary small' }, 'Housing Atlas pulls free public data from Zillow, Redfin, Realtor.com, the Census Bureau, BLS, BEA, FHFA and FRED, then builds every map layer on your computer. The first download is a few GB and takes roughly 15–45 minutes; weekly refreshes are much faster.'),
      meta.can_admin
        ? h('button', { class: 'btn btn-primary', type: 'button', disabled: running ? true : null, onclick: async (e) => {
          e.target.disabled = true;
          try { await post('/api/update', {}); toast('Download started – you can keep using the app'); pollUpdate(true); } catch (err) { toast(err.message); e.target.disabled = false; }
        } }, running ? 'Download in progress…' : 'Download data now')
        : h('p', { class: 'small' }, 'Ask the admin of this server to run the first update.'),
      h('p', { class: 'small muted', style: { marginTop: '8px' } }, 'Progress is shown at the top of the page and on the ', h('a', { href: '#/sources' }, 'Data & Sources'), ' page.'));
  }

  // ------------------------------------------------------------------ tooltip & drawer
  function showTip(id, x, y) {
    if (!id) { tip.hidden = true; return; }
    const m = metric(st.metric);
    const names = st.names[st.level] || {};
    const v = st.values[id];
    clear(tip);
    tip.appendChild(h('div', { class: 'n' }, names[id] || id));
    tip.appendChild(h('div', { class: 'v' }, v === undefined ? 'No data' : fmtAny(v, m, st.tf)));
    const sub = [m.short || m.name];
    if (st.tf !== 'level') sub.push(STATE.transforms[st.tf]);
    tip.appendChild(h('div', { class: 'small muted' }, sub.join(' · ')));
    if (v !== undefined) {
      const vals = Object.values(st.values);
      const rank = vals.filter((x) => x > v).length + 1;
      tip.appendChild(h('div', { class: 'small muted' }, 'Rank ' + rank.toLocaleString() + ' of ' + vals.length.toLocaleString() + ' (highest = 1)'));
    }
    tip.hidden = false;
    const W = page.clientWidth;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    tip.style.left = Math.min(W - tw - 8, x + 14) + 'px';
    tip.style.top = Math.max(8, y - th - 10) + 'px';
  }

  function closeDrawer() { drawer.hidden = true; st.selected = null; map.setSelected(null); }

  async function openRegion(level, id, fly) {
    st.selected = id;
    map.setSelected(id);
    drawer.hidden = false;
    clear(drawer).appendChild(h('div', { class: 'muted' }, 'Loading…'));
    let r;
    try { r = await api('/api/region?level=' + level + '&id=' + encodeURIComponent(id)); } catch (e) {
      clear(drawer).appendChild(h('div', null, 'No data for this region.'));
      return;
    }
    if (fly && r.bbox) map.fitBounds(r.bbox, { leftInset: window.innerWidth > 720 ? 350 : 0, maxZoom: level === 'zip' ? 12 : 10 });
    clear(drawer);
    drawer.appendChild(h('button', { class: 'icon-btn close', type: 'button', 'aria-label': 'Close', onclick: closeDrawer }, '✕'));
    drawer.appendChild(h('div', { class: 'badge' }, LEVEL_NAMES[level] + (r.pop ? ' · pop. ' + fmtPop(r.pop) : '')));
    drawer.appendChild(h('h2', { style: { margin: '2px 30px 6px 0' } }, r.name));
    if (r.market) drawer.appendChild(h('span', { class: 'chip ' + (r.market.tone || ''), title: r.market.basis }, r.market.label));
    const cur = metric(st.metric);
    const ce = r.metrics[st.metric];
    const chartBox = h('div', { style: { marginTop: '10px' } });
    drawer.appendChild(h('div', { class: 'small muted', style: { marginTop: '10px' } }, cur.name));
    if (ce) {
      drawer.appendChild(h('div', { style: { fontSize: '20px', fontWeight: 700 } }, fmtVal(ce.v, cur),
        ce.t && ce.t.yoy !== undefined ? h('span', { class: 'small ' + deltaClass(ce.t.yoy, cur), style: { marginLeft: '8px' } },
          fmtChange(ce.t.yoy, cur, 'yoy') + ' 1-yr') : null));
    }
    drawer.appendChild(chartBox);
    const kv = h('div', { class: 'kv', style: { marginTop: '10px' } });
    for (const k of KEY_METRICS) {
      const e = r.metrics[k];
      const mm = metric(k);
      if (!e || !mm || k === st.metric) continue;
      kv.append(h('span', { class: 'k' }, mm.short || mm.name),
        h('span', { class: 'v' }, fmtVal(e.v, mm), e.t && e.t.yoy !== undefined && mm.change === 'pct'
          ? h('span', { class: 'd ' + deltaClass(e.t.yoy, mm) }, fmtChange(e.t.yoy, mm, 'yoy', { short: true })) : null));
    }
    drawer.appendChild(kv);
    const watchBtn = h('button', { class: 'btn btn-small' + (r.watched ? ' watching' : ''), type: 'button', onclick: async () => {
      if (!APP.user) { toast('Create a free account to save a watchlist'); navigate('#/account'); return; }
      try {
        await post(r.watched ? '/api/watchlist/remove' : '/api/watchlist', { level, id });
        r.watched = !r.watched;
        watchBtn.classList.toggle('watching', r.watched);
        watchBtn.textContent = r.watched ? '★ Watching' : '☆ Watch';
      } catch (e) { toast(e.message); }
    } }, r.watched ? '★ Watching' : '☆ Watch');
    drawer.appendChild(h('div', { class: 'row', style: { marginTop: '12px' } },
      h('a', { class: 'btn btn-primary btn-small', href: '#/region/' + level + '/' + encodeURIComponent(id) }, 'Full report'),
      watchBtn,
      h('a', { class: 'btn btn-small', href: '#/compare?items=' + level + ':' + encodeURIComponent(id) }, 'Compare')));
    try {
      const s = await api('/api/series?level=' + level + '&id=' + encodeURIComponent(id) + '&metrics=' + st.metric + '&tf=' + st.tf);
      const ser = s.series[st.metric];
      if (ser && ser.points.length > 1) {
        const pts = ser.points.map(([p, v]) => [periodToTime(p), v]);
        const t1 = pts[pts.length - 1][0];
        lineChart(chartBox, { height: 140, freq: ser.freq, zero: st.tf !== 'level',
          range: [t1 - 86400000 * 365.25 * 10, t1], endLabel: false,
          series: [{ name: cur.name, color: getComputedStyle(document.documentElement).getPropertyValue('--s1').trim(), points: pts }],
          fmt: (v) => fmtAny(v, cur, st.tf), axisFmt: (v) => fmtAny(v, cur, st.tf, { compact: true, short: true }) });
      }
    } catch (e) { /* chart optional */ }
  }

  // ------------------------------------------------------------------ actions
  function showMsg(t) { msg.textContent = t; msg.hidden = false; }

  function applyTheme() {
    const dark = isDark();
    const b = st.basemap === 'auto' ? (dark ? 'dark' : 'light') : st.basemap;
    map.setBasemap(b);
    map.setTheme(dark
      ? { bg: '#151514', outline: 'rgba(13,13,13,0.85)', hover: '#f0efec', select: '#3987e5', overlay: 'rgba(240,239,236,0.45)' }
      : { bg: '#f3f2ee', outline: 'rgba(255,255,255,0.8)', hover: '#0b0b0b', select: '#256abf', overlay: 'rgba(11,11,11,0.5)' });
    map.fillAlpha = b === 'none' ? 1 : 0.8;
    attrib.textContent = b === 'none' ? 'Boundaries: U.S. Census Bureau' : 'Basemap © OpenStreetMap contributors © CARTO · Boundaries: U.S. Census Bureau';
    if (st.scale) colorize();
  }

  function syncUrl() {
    const v = map.getView();
    const qs = buildQuery({ metric: st.metric, tf: st.tf, level: st.level, date: st.date,
      basemap: st.basemap === 'auto' ? null : st.basemap, lat: v.lat, lon: v.lon, z: v.z });
    history.replaceState(null, '', '#/map' + qs);
    try { localStorage.setItem('ha-map', JSON.stringify({ metric: st.metric, tf: st.tf, level: st.level, basemap: st.basemap, lat: v.lat, lon: v.lon, z: v.z })); } catch (e) { /* ignore */ }
  }

  function setMetric(id) {
    const m = metric(id);
    st.metric = id;
    st.tf = m.transforms.includes(st.tf) ? st.tf : m.default_tf;
    st.date = null;
    if (!availableAt(id, st.level)) {
      const alt = LEVELS.find((l) => availableAt(id, l) && l !== 'zip') || LEVELS.find((l) => availableAt(id, l));
      if (alt) { st.level = alt; loadShapes(); loadNames(); }
    }
    update();
  }

  function setLevel(l) {
    st.level = l;
    st.date = null;
    closeDrawer();
    if (l === 'zip' && map.z < ZIP_MIN_ZOOM) toast('Zoom in (or search a city/ZIP) to see ZIP codes');
    loadShapes();
    loadNames().then(() => drawPanel());
    update();
  }

  async function saveView() {
    const def = metric(st.metric).name + ' – ' + LEVEL_PLURAL[st.level];
    // the web preview runs in a frame where prompt() is blocked: save with the default name there
    const name = (window.HA_STATIC && window.HA_STATIC.preview) ? def : prompt('Name this view', def);
    if (!name) return;
    const v = map.getView();
    try {
      await post('/api/views', { name, state: { metric: st.metric, tf: st.tf, level: st.level, date: st.date, lat: v.lat, lon: v.lon, z: v.z } });
      toast('View saved to your account');
    } catch (e) { toast(e.message); }
  }

  async function update(redraw = true) {
    syncUrl();
    if (redraw) drawPanel();
    await loadValues();
  }

  // search results jump to the region on the map
  const onSelect = (e) => {
    const r = e.detail;
    e.preventDefault();
    const target = r.level === 'state' ? (st.level === 'state' ? 'state' : st.level) : r.level;
    if (target !== st.level && availableAt(st.metric, target)) setLevel(target);
    else if (target !== st.level && r.level !== 'state') setLevel(target);
    openRegion(r.level, r.id, true);
    if (r.level === 'state' && st.level !== 'state') { map.setSelected(null); }
  };
  const onTheme = () => applyTheme();
  const onBanner = () => page.classList.toggle('with-banner', !document.getElementById('update-banner').hidden);
  window.addEventListener('ha:select-region', onSelect);
  window.addEventListener('ha:theme', onTheme);
  window.addEventListener('ha:banner', onBanner);

  drawPanel();
  await Promise.all([loadShapes(), loadNames()]);
  if (!view.z) map.fitBounds([-125, 24.5, -66.5, 49.5], { leftInset: window.innerWidth > 720 ? 350 : 0, duration: 0 });
  await update();
  if (params.query.select) {
    const [lv, gid] = params.query.select.split(':');
    if (lv && gid) openRegion(lv, gid, true);
  }

  return {
    destroy() {
      window.removeEventListener('ha:select-region', onSelect);
      window.removeEventListener('ha:theme', onTheme);
      window.removeEventListener('ha:banner', onBanner);
      map.destroy();
    },
  };
}
