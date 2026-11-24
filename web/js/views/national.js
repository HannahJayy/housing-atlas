// National dashboard: mortgage rates, Case-Shiller, sales, construction, vacancy, inflation (FRED + Redfin weekly).

import { api } from '../api.js';
import { h, clear, seg } from '../ui.js';
import { lineChart } from '../chart.js';
import { periodToTime, SERIES_COLORS, periodLabel } from '../fmt.js';

const RANGES = [['1y', 1], ['5y', 5], ['10y', 10], ['20y', 20], ['max', 0]];
const ORDER = ['Mortgage rates & credit', 'Home prices', 'Inventory & sales', 'Redfin weekly (national)', 'Construction',
  'Ownership & vacancy', 'Economy & inflation'];

function fmtUnits(v, units) {
  if (v === null || v === undefined || !isFinite(v)) return '–';
  if (units === '%') return v.toFixed(2) + '%';
  if (units === 'USD') return '$' + Math.round(v).toLocaleString('en-US');
  if (units === 'Share' || units === 'Ratio') return (v <= 1.5 ? (v * 100).toFixed(1) + '%' : v.toFixed(1) + '%');
  if (units === 'Days') return Math.round(v) + ' days';
  if (units === 'Months') return v.toFixed(1) + ' mo';
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(2) + 'M';
  if (Math.abs(v) >= 1e4) return Math.round(v).toLocaleString('en-US');
  return v.toFixed(Math.abs(v) >= 100 ? 0 : 1);
}
function fmtAxis(v, units) {
  if (units === 'USD') return v >= 1000 ? '$' + Math.round(v / 1000) + 'K' : '$' + v;
  if (units === 'Share' || units === 'Ratio') return (v <= 1.5 ? Math.round(v * 100) : Math.round(v)) + '%';
  if (units === '%') return v + '%';
  if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (Math.abs(v) >= 1e4) return Math.round(v / 1000) + 'K';
  return String(v);
}

export async function render(root) {
  const page = h('div', { class: 'page' });
  root.appendChild(page);
  page.appendChild(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'National housing dashboard'),
    h('p', null, 'Mortgage rates, home prices, sales, construction and the economy for the whole U.S. For every regional metric at the national level, open the ',
      h('a', { href: '#/region/us/US' }, 'U.S. report'), '.'))));
  let data;
  try { data = await api('/api/national', { cache: true }); } catch (e) {
    page.appendChild(h('div', { class: 'card' }, e.message)); return null;
  }
  if (!data.series.length) {
    page.appendChild(h('div', { class: 'empty card' }, 'No national data yet. Run an update from the Data & Sources page.'));
    return null;
  }
  const st = { range: '10y' };
  const filters = h('div', { class: 'filters' });
  const body = h('div');
  page.append(filters, body);
  const charts = [];
  const drawFilters = () => {
    clear(filters).append(h('span', { class: 'small muted' }, 'Range'),
      seg(RANGES.map(([k]) => ({ value: k, label: k.toUpperCase() })), st.range, (v) => { st.range = v; drawFilters(); update(); }));
  };
  const rangeFor = () => {
    const yrs = (RANGES.find(([k]) => k === st.range) || [0, 10])[1];
    return yrs ? [Date.now() - yrs * 365.25 * 86400000, Date.now()] : null;
  };
  const update = () => { for (const c of charts) c.chart.update({ range: rangeFor() }); };
  drawFilters();
  const byCat = {};
  for (const s of data.series) (byCat[s.category] = byCat[s.category] || []).push(s);
  const cats = Object.keys(byCat).sort((a, b) => (ORDER.indexOf(a) + 1 || 99) - (ORDER.indexOf(b) + 1 || 99));
  const color = SERIES_COLORS()[0];
  for (const cat of cats) {
    body.appendChild(h('div', { class: 'section-title' }, h('h2', null, cat)));
    const grid = h('div', { class: 'grid grid-auto' });
    body.appendChild(grid);
    for (const s of byCat[cat]) {
      const pts = s.dates.map((d, i) => [periodToTime(d), s.values[i]]);
      const last = pts[pts.length - 1];
      let yearAgo = null;
      for (let i = pts.length - 1; i >= 0; i--) if (pts[i][0] <= last[0] - 365 * 86400000) { yearAgo = pts[i]; break; }
      const chg = yearAgo ? (s.units === '%' ? (last[1] - yearAgo[1]).toFixed(2) + ' pts' : ((last[1] / yearAgo[1] - 1) * 100).toFixed(1) + '%') : null;
      const card = h('div', { class: 'chart-card' });
      const box = h('div');
      card.append(h('div', { class: 'card-head' },
        h('div', null, h('h3', null, s.name), h('div', { class: 'sub' }, (s.src === 'fred' ? 'FRED' : 'Redfin') + ' · ' + s.id + ' · latest ' + periodLabel(s.dates[s.dates.length - 1]))),
        h('div', { class: 'latest' }, fmtUnits(last[1], s.units), chg ? h('span', { class: 'd muted' }, (chg.startsWith('-') ? '' : '+') + chg + ' 1-yr') : null)), box);
      grid.appendChild(card);
      const gap = s.freq === 'A' ? 86400000 * 800 : s.freq === 'Q' ? 86400000 * 200 : 86400000 * 75;
      charts.push({ chart: lineChart(box, { series: [{ name: s.name, color, points: pts, gapMs: gap }], freq: s.freq, height: 190, range: rangeFor(),
        fmt: (v) => fmtUnits(v, s.units), axisFmt: (v) => fmtAxis(v, s.units) }) });
    }
  }
  return { destroy() { for (const c of charts) c.chart.destroy(); } };
}
