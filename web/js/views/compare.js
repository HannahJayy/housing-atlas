// Compare up to 6 regions on any metric.

import { api } from '../api.js';
import { h, clear, seg, buildQuery, debounce, toast } from '../ui.js';
import { lineChart, legend } from '../chart.js';
import { openMetricPicker } from '../picker.js';
import { STATE, metric, fmtAny, fmtVal, fmtChange, deltaClass, LEVEL_NAMES, periodToTime, SERIES_COLORS, periodLabel } from '../fmt.js';

const MAX = 6;
const TABLE_METRICS = ['zhvi', 'overvalued', 'forecast_12m', 'forecast_score', 'longterm_score', 'investor_score',
  'inventory', 'price_cut_share', 'dom', 'rf_months_supply', 'payment', 'payment_to_income', 'value_to_income',
  'rent', 'price_to_rent', 'cap_rate', 'population', 'migration_rate', 'acs_income', 'unemployment',
  'property_tax_rate', 'permits_pct', 'vacancy_rate'];
const RANGES = [['3y', 3], ['5y', 5], ['10y', 10], ['max', 0]];

export async function render(root, params) {
  const q = params.query;
  const st = {
    items: [], metric: q.metric || 'zhvi', tf: q.tf || 'level', range: q.range || '10y',
  };
  const raw = (q.items || '').split(',').filter(Boolean).slice(0, MAX);
  raw.forEach((s, i) => { const [level, ...rest] = s.split(':'); st.items.push({ level, id: rest.join(':'), slot: i }); });
  if (!metric(st.metric)) st.metric = 'zhvi';

  const page = h('div', { class: 'page' });
  root.appendChild(page);
  page.appendChild(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Compare markets'),
    h('p', null, 'Add up to six states, metros, counties or ZIP codes and compare any metric over time.'))));
  const addRow = h('div', { class: 'row', style: { marginBottom: '10px' } });
  const controls = h('div', { class: 'filters' });
  const chartCard = h('div', { class: 'chart-card' });
  const tableBox = h('div', { style: { marginTop: '16px' } });
  page.append(addRow, controls, chartCard, tableBox);

  const regions = {};
  async function info(it) {
    const k = it.level + ':' + it.id;
    if (!regions[k]) {
      try { regions[k] = await api('/api/region?level=' + it.level + '&id=' + encodeURIComponent(it.id), { cache: true }); } catch (e) { regions[k] = null; }
    }
    return regions[k];
  }

  function sync() {
    history.replaceState(null, '', '#/compare' + buildQuery({ items: st.items.map((i) => i.level + ':' + i.id).join(','),
      metric: st.metric, tf: st.tf === 'level' ? null : st.tf, range: st.range === '10y' ? null : st.range }));
  }

  function drawAdd() {
    clear(addRow);
    const colors = SERIES_COLORS();
    for (const it of st.items) {
      const r = regions[it.level + ':' + it.id];
      addRow.appendChild(h('span', { class: 'chip' }, h('i', { style: { display: 'inline-block', width: '10px', height: '10px', borderRadius: '3px', background: colors[it.slot] } }),
        (r ? r.name : it.id) + ' · ' + LEVEL_NAMES[it.level],
        h('button', { type: 'button', 'aria-label': 'Remove', style: { border: 0, background: 'none', cursor: 'pointer', color: 'inherit' },
          onclick: () => { st.items = st.items.filter((x) => x !== it); refresh(); } }, '×')));
    }
    if (st.items.length < MAX) {
      const wrap = h('div', { style: { position: 'relative' } });
      const input = h('input', { class: 'input', type: 'search', placeholder: '+ Add a region…', style: { width: '240px' }, 'aria-label': 'Add a region' });
      const list = h('div', { class: 'search-results', hidden: true, style: { top: '38px', width: '320px' } });
      input.addEventListener('input', debounce(async () => {
        const t = input.value.trim();
        if (t.length < 2) { list.hidden = true; return; }
        const res = await api('/api/search?q=' + encodeURIComponent(t), { cache: true });
        clear(list);
        for (const r of res.results) {
          list.appendChild(h('button', { type: 'button', onmousedown: (e) => {
            e.preventDefault();
            if (st.items.some((x) => x.level === r.level && x.id === r.id)) { toast('Already added'); return; }
            const used = new Set(st.items.map((x) => x.slot));
            let slot = 0; while (used.has(slot)) slot++;
            st.items.push({ level: r.level, id: r.id, slot });
            input.value = ''; list.hidden = true; refresh();
          } }, h('span', { class: 'kind' }, LEVEL_NAMES[r.level] || r.kind), h('span', null, r.name)));
        }
        list.hidden = !res.results.length;
      }, 160));
      input.addEventListener('blur', () => setTimeout(() => { list.hidden = true; }, 150));
      wrap.append(input, list);
      addRow.appendChild(wrap);
    }
  }

  function drawControls() {
    const m = metric(st.metric);
    clear(controls);
    controls.append(
      h('button', { class: 'metric-btn', type: 'button', style: { width: 'auto' }, onclick: () => openMetricPicker({ current: st.metric,
        onPick: (id) => { st.metric = id; if (!metric(id).transforms.includes(st.tf)) st.tf = 'level'; refresh(); } }) },
        h('span', { class: 'name' }, m.name), h('span', { 'aria-hidden': 'true' }, ' ▾')),
      seg(m.transforms.filter((t) => t !== 'from_peak').map((t) => ({ value: t, label: STATE.transforms[t] })), st.tf, (v) => { st.tf = v; refresh(); }),
      seg(RANGES.map(([k]) => ({ value: k, label: k.toUpperCase() })), st.range, (v) => { st.range = v; refresh(false); }));
  }

  async function drawChart() {
    const m = metric(st.metric);
    clear(chartCard);
    chartCard.appendChild(h('div', { class: 'card-head' }, h('div', null, h('h3', null, m.name + (st.tf !== 'level' ? ' · ' + STATE.transforms[st.tf] : '')),
      h('div', { class: 'sub' }, m.desc))));
    if (!st.items.length) { chartCard.appendChild(h('div', { class: 'empty' }, 'Add regions above to compare them.')); return; }
    const colors = SERIES_COLORS();
    const series = [];
    let freq = 'M';
    await Promise.all(st.items.map(async (it) => {
      try {
        const r = await api('/api/series?level=' + it.level + '&id=' + encodeURIComponent(it.id) + '&metrics=' + st.metric + '&tf=' + st.tf, { cache: true });
        const sr = r.series[st.metric];
        const info_ = regions[it.level + ':' + it.id];
        if (sr) { freq = sr.freq; series.push({ slot: it.slot, name: info_ ? info_.name : it.id, color: colors[it.slot], points: sr.points.map(([p, v]) => [periodToTime(p), v]) }); }
      } catch (e) { /* ignore */ }
    }));
    series.sort((a, b) => a.slot - b.slot);
    const yrs = (RANGES.find(([k]) => k === st.range) || [0, 10])[1];
    const lg = legend(series);
    if (lg) chartCard.appendChild(lg);
    const box = h('div');
    chartCard.appendChild(box);
    if (!series.length) { box.appendChild(h('div', { class: 'empty' }, 'None of these regions have this metric.')); return; }
    lineChart(box, { series, freq, height: 320, zero: st.tf !== 'level', endLabel: false,
      range: yrs ? [Date.now() - yrs * 365.25 * 86400000, Date.now()] : null,
      fmt: (v) => fmtAny(v, m, st.tf), axisFmt: (v) => fmtAny(v, m, st.tf, { compact: true, short: true }) });
  }

  function drawTable() {
    clear(tableBox);
    if (!st.items.length) return;
    const infos = st.items.map((it) => regions[it.level + ':' + it.id]).filter(Boolean);
    const rows = [];
    for (const mid of TABLE_METRICS) {
      const m = metric(mid);
      if (!m || !infos.some((r) => r.metrics[mid])) continue;
      rows.push(h('tr', null, h('td', { title: m.desc }, m.name), infos.map((r) => {
        const e = r.metrics[mid];
        return h('td', { class: 'num' }, e ? fmtVal(e.v, m) : '–',
          e && e.t.yoy !== undefined && m.change === 'pct' ? h('span', { class: 'small ' + deltaClass(e.t.yoy, m), style: { marginLeft: '6px' } }, fmtChange(e.t.yoy, m, 'yoy', { short: true })) : null);
      })));
    }
    tableBox.appendChild(h('div', { class: 'table-wrap' }, h('table', { class: 'data' },
      h('thead', null, h('tr', null, h('th', null, 'Metric'), infos.map((r) => h('th', { class: 'num' }, h('a', { href: '#/region/' + r.level + '/' + encodeURIComponent(r.id) }, r.name))))),
      h('tbody', null, rows))));
  }

  async function refresh(full = true) {
    sync();
    await Promise.all(st.items.map(info));
    drawAdd();
    drawControls();
    await drawChart();
    if (full) drawTable();
  }
  await refresh();
  return null;
}
