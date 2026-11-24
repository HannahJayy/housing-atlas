// Region report: key stats, every available metric as a chart, child regions and a full data table.

import { api, post } from '../api.js';
import { h, clear, seg, toast, buildQuery, downloadText } from '../ui.js';
import { lineChart, legend, sparkline } from '../chart.js';
import {
  STATE, metric, fmtVal, fmtChange, fmtAny, deltaClass, periodLabel, periodToTime, LEVEL_NAMES, LEVEL_PLURAL,
  SRC_NAMES, fmtPop, SERIES_COLORS,
} from '../fmt.js';
import { APP, navigate } from '../app.js';

const TILES = ['zhvi', 'overvalued', 'forecast_12m', 'forecast_score', 'inventory', 'price_cut_share', 'dom',
  'payment', 'payment_to_income', 'value_to_income', 'rent', 'cap_rate', 'rf_months_supply', 'population',
  'unemployment', 'permits_pct'];
const TILE_TF = { inventory: 'vs_pre', population: 'yoy' };
const TF_SHORT = { vs_pre: 'vs 2017-19', yoy: '1-yr change', chg_5y: '5-yr change' };
const OPEN_CATS = ['prices', 'valuation', 'afford', 'inventory'];
const RANGES = [['1y', 1], ['3y', 3], ['5y', 5], ['10y', 10], ['max', 0]];

export async function render(root, params, app) {
  const level = params.parts[0];
  const id = params.parts.slice(1).join('/');
  const page = h('div', { class: 'page' });
  root.appendChild(page);
  page.appendChild(h('div', { class: 'muted' }, 'Loading…'));
  let r;
  try {
    r = await api('/api/region?level=' + encodeURIComponent(level) + '&id=' + encodeURIComponent(id));
  } catch (e) {
    clear(page).appendChild(h('div', { class: 'card' }, h('h2', null, 'Region not found'),
      h('p', { class: 'secondary' }, 'No data for ' + level + ' ' + id + '. If you just installed the app, run the first data download on the Data & Sources page.')));
    return null;
  }
  const saved = (() => { try { return JSON.parse(localStorage.getItem('ha-region') || '{}'); } catch (e) { return {}; } })();
  const st = { range: saved.range || '10y', tf: 'level', compare: saved.compare || ['us'], series: {}, parentSeries: {} };
  const metricIds = Object.keys(r.metrics);
  const charts = [];

  // ---------------------------------------------------------------- header
  clear(page);
  const crumbs = h('div', { class: 'crumbs' });
  for (const p of r.parents) {
    crumbs.append(h('a', { href: '#/region/' + p.level + '/' + encodeURIComponent(p.id) }, p.name), h('span', null, '›'));
  }
  crumbs.append(h('span', null, LEVEL_NAMES[level]));
  const watchBtn = h('button', { class: 'btn' + (r.watched ? ' watching' : ''), type: 'button', onclick: async () => {
    if (!APP.user) { toast('Create a free account to keep a watchlist'); navigate('#/account'); return; }
    try {
      await post(r.watched ? '/api/watchlist/remove' : '/api/watchlist', { level, id });
      r.watched = !r.watched;
      watchBtn.classList.toggle('watching', r.watched);
      watchBtn.textContent = r.watched ? '★ Watching' : '☆ Add to watchlist';
    } catch (e) { toast(e.message); }
  } }, r.watched ? '★ Watching' : '☆ Add to watchlist');
  const facts = [];
  if (r.pop) facts.push('Population ' + Math.round(r.pop).toLocaleString());
  if (r.lsad) facts.push(r.lsad === 'micro' ? 'Micropolitan area' : 'Metropolitan area');
  if (r.full_name && r.full_name !== r.name && level === 'metro') facts.push(r.full_name);
  page.appendChild(h('div', { class: 'region-head' },
    h('div', null, crumbs, h('h1', null, r.name),
      h('div', { class: 'row secondary small' }, facts.join(' · '),
        r.market ? h('span', { class: 'chip ' + (r.market.tone || ''), title: r.market.basis }, r.market.label) : null)),
    h('div', { class: 'row' },
      h('a', { class: 'btn', href: '#/map' + buildQuery({ level: level === 'us' ? 'state' : level, select: level !== 'us' ? level + ':' + id : null }) }, 'View on map'),
      h('a', { class: 'btn', href: '#/compare?items=' + level + ':' + encodeURIComponent(id) }, 'Compare'),
      watchBtn)));

  // ---------------------------------------------------------------- key stat tiles
  const tiles = h('div', { class: 'tiles' });
  page.appendChild(tiles);
  function drawTiles() {
    clear(tiles);
    const colors = SERIES_COLORS();
    for (const mid of TILES) {
      const e = r.metrics[mid];
      const m = metric(mid);
      if (!e || !m) continue;
      const tf = TILE_TF[mid];
      const val = tf && e.t[tf] !== undefined ? fmtChange(e.t[tf], m, tf) : fmtVal(e.v, m);
      const lbl = tf ? (m.short || m.name) + ' (' + (TF_SHORT[tf] || STATE.transforms[tf]) + ')' : (m.short || m.name);
      const dTf = mid === 'population' ? 'chg_5y' : 'yoy';
      const d = e.t[dTf];
      const ser = st.series[mid];
      tiles.appendChild(h('div', { class: 'tile', tabindex: 0, role: 'button', title: m.desc,
        onclick: () => { const el = document.getElementById('chart-' + mid); if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); } } },
        h('div', { class: 'lbl' }, lbl),
        h('div', { class: 'val' }, val),
        d !== undefined && !(tf === dTf) ? h('div', { class: 'dl ' + deltaClass(d, m) }, fmtChange(d, m, dTf) + ' ' + (dTf === 'yoy' ? 'in 1 yr' : 'in 5 yrs')) : h('div', { class: 'dl muted' }, periodLabel(e.p)),
        e.rank ? h('div', { class: 'rk' }, '#' + e.rank.toLocaleString() + ' of ' + e.of.toLocaleString() + ' ' + LEVEL_PLURAL[level].toLowerCase()) : null,
        ser && ser.points.length > 3 ? sparkline(ser.points.slice(-60).map(([p, v]) => [periodToTime(p), v]), colors[0]) : null));
    }
  }
  drawTiles();

  // ---------------------------------------------------------------- filters (scope every chart below)
  const filters = h('div', { class: 'filters' });
  page.appendChild(filters);
  const parents = r.parents.filter((p) => ['us', 'state', 'metro'].includes(p.level));
  function drawFilters() {
    clear(filters);
    filters.append(h('span', { class: 'small muted' }, 'Range'),
      seg(RANGES.map(([k]) => ({ value: k, label: k.toUpperCase() })), st.range, (v) => { st.range = v; persist(); drawFilters(); redrawCharts(); }),
      h('span', { class: 'small muted' }, 'Show'),
      seg([{ value: 'level', label: 'Values' }, { value: 'yoy', label: '1-yr change' }], st.tf, (v) => { st.tf = v; drawFilters(); Promise.all([loadAll(), loadParents()]).then(redrawCharts); }));
    if (parents.length) {
      filters.append(h('span', { class: 'small muted' }, 'Compare with'));
      const wrap = h('div', { class: 'seg' });
      for (const p of parents) {
        const on = st.compare.includes(p.level);
        wrap.appendChild(h('button', { type: 'button', class: on ? 'on' : '', 'aria-pressed': on ? 'true' : 'false', onclick: () => {
          st.compare = on ? st.compare.filter((x) => x !== p.level) : [...st.compare, p.level];
          persist(); drawFilters(); loadParents().then(redrawCharts);
        } }, p.level === 'us' ? 'U.S.' : p.name));
      }
      filters.appendChild(wrap);
    }
    filters.append(h('span', { class: 'spacer' }),
      h('button', { class: 'btn btn-small', type: 'button', onclick: exportCsv }, 'Download CSV'));
  }
  function persist() { try { localStorage.setItem('ha-region', JSON.stringify({ range: st.range, compare: st.compare })); } catch (e) { /* ignore */ } }
  drawFilters();

  // ---------------------------------------------------------------- data
  async function loadAll() {
    const res = await api('/api/series?level=' + level + '&id=' + encodeURIComponent(id) + '&metrics=' + metricIds.join(',') + '&tf=' + st.tf, { cache: true });
    st.series = res.series;
  }
  async function loadParents() {
    st.parentSeries = {};
    await Promise.all(parents.filter((p) => st.compare.includes(p.level)).map(async (p) => {
      try {
        const res = await api('/api/series?level=' + p.level + '&id=' + encodeURIComponent(p.id) + '&metrics=' + metricIds.join(',') + '&tf=' + st.tf, { cache: true });
        st.parentSeries[p.level] = { name: p.level === 'us' ? 'United States' : p.name, series: res.series };
      } catch (e) { /* ignore */ }
    }));
  }

  // ---------------------------------------------------------------- chart sections
  const sections = h('div');
  page.appendChild(sections);
  function rangeFor() {
    const yrs = (RANGES.find(([k]) => k === st.range) || [0, 10])[1];
    if (!yrs) return null;
    const now = Date.now();
    return [now - yrs * 365.25 * 86400000, now];
  }
  function chartCard(mid) {
    const m = metric(mid);
    const e = r.metrics[mid];
    const card = h('div', { class: 'chart-card', id: 'chart-' + mid });
    const latest = e ? h('div', { class: 'latest' }, fmtVal(e.v, m),
      e.t.yoy !== undefined ? h('span', { class: 'd ' + deltaClass(e.t.yoy, m) }, fmtChange(e.t.yoy, m, 'yoy') + ' 1-yr') : null) : null;
    const tableBtn = h('button', { class: 'btn btn-small btn-ghost', type: 'button' }, 'Table');
    card.appendChild(h('div', { class: 'card-head' },
      h('div', null, h('h3', { title: m.desc }, m.name),
        h('div', { class: 'sub' }, (SRC_NAMES[m.src] || m.src) + (e ? ' · ' + periodLabel(e.p) : '') +
          (e && e.rank ? ' · #' + e.rank.toLocaleString() + ' of ' + e.of.toLocaleString() : ''))),
      latest));
    const legendBox = h('div');
    const box = h('div');
    const tableBox = h('div', { class: 'mini-table', hidden: true });
    card.append(legendBox, box, tableBox,
      h('div', { class: 'row', style: { marginTop: '4px' } }, tableBtn,
        h('a', { class: 'btn btn-small btn-ghost', href: '#/map' + buildQuery({ metric: mid, level: level === 'us' ? 'state' : level, select: level !== 'us' ? level + ':' + id : null }) }, 'Map'),
        h('a', { class: 'btn btn-small btn-ghost', href: '#/rankings' + buildQuery({ level: level === 'us' ? 'state' : level, cols: mid + ':level', sort: mid + ':level' }) }, 'Rank'),
        h('span', { class: 'spacer' }), h('span', { class: 'small muted', title: m.desc }, 'ⓘ')));
    tableBtn.addEventListener('click', () => {
      tableBox.hidden = !tableBox.hidden;
      tableBtn.textContent = tableBox.hidden ? 'Table' : 'Hide table';
      if (!tableBox.hidden) fillTable(tableBox, mid);
    });
    const obj = { mid, card, box, legendBox, chart: null };
    charts.push(obj);
    drawChart(obj);
    return card;
  }
  function seriesFor(mid) {
    const colors = SERIES_COLORS();
    const out = [];
    const own = st.series[mid];
    if (own) out.push({ name: r.name, color: colors[0], points: own.points.map(([p, v]) => [periodToTime(p), v]), freq: own.freq });
    // color follows the entity (metro / state / U.S. keep their hue when others are toggled)
    const slot = { metro: 1, state: 2, us: 3 };
    for (const p of ['metro', 'state', 'us']) {
      const ps = st.parentSeries[p];
      if (!ps || !ps.series[mid]) continue;
      out.push({ name: ps.name, color: colors[slot[p]], points: ps.series[mid].points.map(([pp, v]) => [periodToTime(pp), v]) });
    }
    return out;
  }
  function drawChart(obj) {
    const m = metric(obj.mid);
    const ser = seriesFor(obj.mid);
    const freq = (st.series[obj.mid] || {}).freq || 'M';
    clear(obj.legendBox);
    const lg = legend(ser);
    if (lg) obj.legendBox.appendChild(lg);
    const tf = st.tf;
    const opts = {
      series: ser, freq, height: 200, zero: tf !== 'level' || ['overvalued', 'overvalued_income', 'overvalued_trend', 'forecast_12m', 'buy_vs_rent', 'net_migration', 'migration_rate'].includes(obj.mid),
      range: freq === 'A' && st.range === '1y' ? rangeForAnnual() : (freq === 'A' && st.range === '3y' ? rangeForAnnual(4) : rangeFor()),
      fmt: (v) => fmtAny(v, m, tf), axisFmt: (v) => fmtAny(v, m, tf, { compact: true, short: true }),
      ariaLabel: m.name + ' for ' + r.name,
      emptyText: tf !== 'level' && m.transforms.indexOf('yoy') < 0 ? 'No 1-year change for this metric.' : 'No data in this range.',
    };
    if (obj.chart) obj.chart.update(opts);
    else obj.chart = lineChart(obj.box, opts);
  }
  function rangeForAnnual(yrs = 3) { const now = Date.now(); return [now - yrs * 365.25 * 86400000, now]; }
  function redrawCharts() { for (const c of charts) drawChart(c); drawTiles(); }
  function fillTable(box, mid) {
    clear(box);
    const m = metric(mid);
    const own = st.series[mid];
    if (!own) { box.appendChild(h('div', { class: 'muted small' }, 'No data')); return; }
    const pts = own.points.slice(-36).reverse();
    box.appendChild(h('table', { class: 'data' }, h('thead', null, h('tr', null, h('th', null, 'Period'), h('th', { class: 'num' }, st.tf === 'level' ? 'Value' : '1-yr change'))),
      h('tbody', null, pts.map(([p, v]) => h('tr', null, h('td', null, periodLabel(p)), h('td', { class: 'num' }, fmtAny(v, m, st.tf)))))));
  }

  function drawSections() {
    clear(sections);
    for (const cat of STATE.cats) {
      const mids = STATE.meta.catalog.metrics.filter((m) => m.cat === cat.id && r.metrics[m.id]).map((m) => m.id);
      if (!mids.length) continue;
      const open = OPEN_CATS.includes(cat.id);
      const grid = h('div', { class: 'grid grid-auto' });
      const det = h('details', { open: open ? true : null },
        h('summary', { class: 'section-title', style: { cursor: 'pointer', listStyle: 'none' } },
          h('h2', null, cat.name), h('span', { class: 'chip' }, mids.length + ' metric' + (mids.length > 1 ? 's' : '')),
          h('span', { class: 'small muted' }, open ? '' : 'click to expand')),
        grid);
      let built = false;
      const build = () => { if (built) return; built = true; for (const mid of mids) grid.appendChild(chartCard(mid)); };
      if (open) build();
      det.addEventListener('toggle', () => { if (det.open) build(); });
      sections.appendChild(det);
    }
  }

  // ---------------------------------------------------------------- children & full table
  const childBox = h('div');
  const allBox = h('div');
  page.append(childBox, allBox);

  async function drawChildren() {
    const kinds = Object.entries(r.children || {}).filter(([, n]) => n > 0);
    if (!kinds.length) return;
    clear(childBox);
    childBox.appendChild(h('div', { class: 'section-title' }, h('h2', null, 'Inside ' + r.name)));
    let kind = kinds[0][0];
    const segBox = h('div');
    const tableBox = h('div');
    childBox.append(segBox, tableBox);
    const cols = ['zhvi:level', 'zhvi:yoy', 'overvalued:level', 'forecast_12m:level', 'inventory:vs_pre', 'price_cut_share:level', 'dom:level', 'rent:level'];
    async function load() {
      clear(segBox).appendChild(seg(kinds.map(([k, n]) => ({ value: k, label: LEVEL_PLURAL[k] + ' (' + n + ')' })), kind, (v) => { kind = v; load(); }));
      const filter = level === 'us' ? {} : (level === 'state' ? { state: id } : (level === 'metro' ? { metro: id } : { county: id }));
      const qs = buildQuery(Object.assign({ level: kind, cols: cols.join(','), sort: 'pop', limit: 200 }, filter));
      let res;
      try { res = await api('/api/rankings' + qs, { cache: true }); } catch (e) { return; }
      const ms = res.cols.map((c) => { const [mid, tf] = c.split(':'); return { m: metric(mid), tf }; });
      clear(tableBox).appendChild(h('div', { class: 'table-wrap' }, h('table', { class: 'data' },
        h('thead', null, h('tr', null, h('th', null, 'Name'), h('th', { class: 'num' }, 'Population'),
          ms.map(({ m, tf }) => h('th', { class: 'num', title: m.desc }, (m.short || m.name) + (tf !== 'level' ? ' (' + STATE.transforms[tf] + ')' : ''))))),
        h('tbody', null, res.rows.map((row) => h('tr', { class: 'clickable', onclick: () => navigate('#/region/' + kind + '/' + encodeURIComponent(row.id)) },
          h('td', null, row.name), h('td', { class: 'num' }, fmtPop(row.pop)),
          row.v.map((v, i) => h('td', { class: 'num ' + (ms[i].tf !== 'level' ? deltaClass(v, ms[i].m) : '') }, fmtAny(v, ms[i].m, ms[i].tf, { compact: true })))))))));
      if (res.total > res.rows.length) tableBox.appendChild(h('p', { class: 'small muted' }, 'Showing the ' + res.rows.length + ' largest of ' + res.total + '. ',
        h('a', { href: '#/rankings' + buildQuery(Object.assign({ level: kind, cols: cols.join(',') }, filter)) }, 'See all in Rankings')));
    }
    load();
  }

  function drawAllTable() {
    clear(allBox);
    allBox.appendChild(h('div', { class: 'section-title' }, h('h2', null, 'Every metric for ' + r.name),
      h('span', { class: 'chip' }, metricIds.length + ' metrics')));
    const rows = [];
    for (const cat of STATE.cats) {
      const ms = STATE.meta.catalog.metrics.filter((m) => m.cat === cat.id && r.metrics[m.id]);
      if (!ms.length) continue;
      rows.push(h('tr', { class: 'cat' }, h('td', { colspan: 7 }, cat.name)));
      for (const m of ms) {
        const e = r.metrics[m.id];
        const pct = e.pct !== undefined && e.pct !== null ? e.pct : null;
        rows.push(h('tr', null,
          h('td', { class: 'name', title: m.desc }, m.name),
          h('td', { class: 'num' }, fmtVal(e.v, m)),
          h('td', { class: 'num ' + deltaClass(e.t.yoy, m) }, e.t.yoy !== undefined ? fmtChange(e.t.yoy, m, 'yoy', { short: true }) : '–'),
          h('td', { class: 'num ' + deltaClass(e.t.vs_pre, m) }, e.t.vs_pre !== undefined ? fmtChange(e.t.vs_pre, m, 'vs_pre', { short: true }) : '–'),
          h('td', { class: 'num' }, e.rank ? e.rank.toLocaleString() + ' / ' + e.of.toLocaleString() : '–'),
          h('td', null, pct !== null ? h('span', { class: 'rankbar', title: 'Percentile ' + Math.round(pct * 100) }, h('i', { style: { width: Math.round(pct * 100) + '%' } })) : null),
          h('td', { class: 'small muted' }, (SRC_NAMES[m.src] || m.src) + ' · ' + periodLabel(e.p))));
      }
    }
    allBox.appendChild(h('div', { class: 'table-wrap all-metrics' }, h('table', { class: 'data' },
      h('thead', null, h('tr', null, h('th', null, 'Metric'), h('th', { class: 'num' }, 'Latest'), h('th', { class: 'num' }, '1-yr change'),
        h('th', { class: 'num' }, 'vs 2017-19'), h('th', { class: 'num' }, 'Rank (1 = highest)'), h('th', null, 'Percentile'), h('th', null, 'Source · period'))),
      h('tbody', null, rows))));
    const used = [...new Set(metricIds.map((mid) => metric(mid).src))].map((s) => SRC_NAMES[s] || s);
    allBox.appendChild(h('p', { class: 'small muted', style: { marginTop: '10px' } }, 'Sources: ' + used.join(', ') + '. ',
      h('a', { href: '#/sources' }, 'Details & download links'), ' · ', h('a', { href: '#/methodology' }, 'How metrics are calculated')));
  }

  function exportCsv() {
    const lines = [['metric', 'period', 'value'].join(',')];
    for (const mid of metricIds) {
      const sr = st.series[mid];
      if (!sr) continue;
      for (const [p, v] of sr.points) lines.push([JSON.stringify(metric(mid).name), p, v].join(','));
    }
    downloadText('housing-atlas-' + level + '-' + id + '.csv', lines.join('\n'));
  }

  try { await Promise.all([loadAll(), loadParents()]); } catch (e) { toast(e.message); }
  drawTiles();
  drawSections();
  drawAllTable();
  drawChildren();
  return { destroy() { for (const c of charts) if (c.chart) c.chart.destroy(); } };
}
