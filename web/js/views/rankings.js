// Sortable rankings table for any combination of metrics.

import { api, apiText } from '../api.js';
import { h, clear, seg, buildQuery, debounce, downloadText, toast } from '../ui.js';
import { openMetricPicker } from '../picker.js';
import { STATE, metric, fmtAny, deltaClass, LEVEL_NAMES, LEVEL_PLURAL, periodLabel, fmtPop, availableAt } from '../fmt.js';
import { navigate } from '../app.js';

const LEVELS = ['state', 'metro', 'county', 'zip'];
const DEFAULT_COLS = ['zhvi:level', 'zhvi:yoy', 'overvalued:level', 'forecast_12m:level', 'inventory:vs_pre',
  'price_cut_share:level', 'dom:level', 'payment_to_income:level', 'rent:level', 'cap_rate:level'];
const STATES = [['', 'All states']];

export async function render(root, params) {
  const q = params.query;
  const st = {
    level: LEVELS.includes(q.level) ? q.level : 'metro',
    cols: (q.cols || DEFAULT_COLS.join(',')).split(',').filter((c) => metric(c.split(':')[0])),
    sort: q.sort || null, desc: q.desc !== '0', state: q.state || '', lsad: q.lsad || '',
    minPop: q.min_pop || '', text: q.q || '', offset: +q.offset || 0, limit: 100,
  };
  if (!st.cols.length) st.cols = DEFAULT_COLS.slice();
  if (!st.sort) st.sort = st.cols[0];

  const page = h('div', { class: 'page' });
  root.appendChild(page);
  page.appendChild(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Rankings'),
    h('p', null, 'Sort and filter every state, metro, county or ZIP code by any metric. Click a row for the full report.'))));
  const controls = h('div', { class: 'filters' });
  const colsRow = h('div', { class: 'row', style: { margin: '6px 0 12px' } });
  const tableBox = h('div');
  page.append(controls, colsRow, tableBox);

  // state list from geonames (states level)
  if (STATES.length === 1) {
    try {
      const r = await api('/api/geonames?level=state', { cache: true });
      Object.entries(r.names).sort((a, b) => a[1].localeCompare(b[1])).forEach(([k, v]) => STATES.push([k, v]));
    } catch (e) { /* ignore */ }
  }

  function sync() {
    history.replaceState(null, '', '#/rankings' + buildQuery({ level: st.level, cols: st.cols.join(','), sort: st.sort,
      desc: st.desc ? null : '0', state: st.state, lsad: st.lsad, min_pop: st.minPop, q: st.text, offset: st.offset || null }));
  }

  function drawControls() {
    clear(controls);
    controls.append(seg(LEVELS.map((l) => ({ value: l, label: LEVEL_PLURAL[l] })), st.level, (v) => { st.level = v; st.offset = 0; drawControls(); load(); }));
    if (st.level !== 'state') {
      const sel = h('select', { class: 'input', 'aria-label': 'State filter', onchange: (e) => { st.state = e.target.value; st.offset = 0; load(); } },
        STATES.map(([k, v]) => h('option', { value: k, selected: k === st.state ? true : null }, v)));
      controls.appendChild(sel);
    }
    if (st.level === 'metro') {
      controls.appendChild(seg([{ value: '', label: 'All' }, { value: 'metro', label: 'Metro' }, { value: 'micro', label: 'Micro' }], st.lsad,
        (v) => { st.lsad = v; st.offset = 0; drawControls(); load(); }));
    }
    const pops = [['', 'Any size'], ['10000', '10K+'], ['50000', '50K+'], ['100000', '100K+'], ['250000', '250K+'], ['1000000', '1M+']];
    controls.appendChild(h('select', { class: 'input', 'aria-label': 'Minimum population', onchange: (e) => { st.minPop = e.target.value; st.offset = 0; load(); } },
      pops.map(([k, v]) => h('option', { value: k, selected: k === st.minPop ? true : null }, v))));
    const search = h('input', { class: 'input', type: 'search', placeholder: 'Filter by name', value: st.text, 'aria-label': 'Filter by name' });
    search.addEventListener('input', debounce(() => { st.text = search.value; st.offset = 0; load(); }, 250));
    controls.appendChild(search);
    controls.append(h('span', { class: 'spacer' }),
      h('button', { class: 'btn btn-small', type: 'button', onclick: async () => {
        try {
          const text = await apiText('/api/export.csv' + buildQuery({ level: st.level, cols: st.cols.join(','), sort: st.sort,
            desc: st.desc ? '1' : '0', state: st.state, lsad: st.lsad, min_pop: st.minPop, q: st.text }));
          downloadText('housing-atlas-' + st.level + '.csv', text);
        } catch (e) { toast(e.message); }
      } }, 'Download CSV'));
  }

  function drawCols() {
    clear(colsRow);
    colsRow.appendChild(h('span', { class: 'small muted' }, 'Columns'));
    st.cols.forEach((c, i) => {
      const [mid, tf] = c.split(':');
      const m = metric(mid);
      const chip = h('span', { class: 'chip', title: m.desc + (availableAt(mid, st.level) ? '' : ' (not available at this level)'),
        style: availableAt(mid, st.level) ? null : { opacity: 0.5 } }, m.short || m.name);
      if (m.transforms.length > 1) {
        chip.appendChild(h('select', { 'aria-label': 'Measure for ' + m.name, style: { border: 0, background: 'transparent', fontSize: '12px', color: 'inherit' },
          onchange: (e) => { const old = st.cols[i]; st.cols[i] = mid + ':' + e.target.value; if (st.sort === old) st.sort = st.cols[i]; drawCols(); load(); } },
          m.transforms.map((t) => h('option', { value: t, selected: t === (tf || 'level') ? true : null }, STATE.transforms[t]))));
      }
      chip.appendChild(h('button', { type: 'button', 'aria-label': 'Remove column', style: { border: 0, background: 'none', cursor: 'pointer', color: 'inherit', padding: '0 0 0 4px' },
        onclick: () => { st.cols.splice(i, 1); if (!st.cols.length) st.cols = ['zhvi:level']; drawCols(); load(); } }, '×'));
      colsRow.appendChild(chip);
    });
    colsRow.appendChild(h('button', { class: 'btn btn-small', type: 'button', onclick: () => openMetricPicker({
      level: st.level, onPick: (mid) => { const c = mid + ':' + metric(mid).default_tf; if (!st.cols.includes(c)) st.cols.push(c); st.sort = c; drawCols(); load(); },
    }) }, '+ Add column'));
    colsRow.appendChild(h('button', { class: 'btn btn-small btn-ghost', type: 'button', onclick: () => { st.cols = DEFAULT_COLS.slice(); st.sort = st.cols[0]; drawCols(); load(); } }, 'Reset'));
  }

  let req = 0;
  async function load() {
    sync();
    const id = ++req;
    tableBox.style.opacity = '0.6';
    let res;
    try {
      res = await api('/api/rankings' + buildQuery({ level: st.level, cols: st.cols.join(','), sort: st.sort, desc: st.desc ? '1' : '0',
        state: st.state, lsad: st.lsad, min_pop: st.minPop, q: st.text, limit: st.limit, offset: st.offset }));
    } catch (e) {
      tableBox.style.opacity = '';
      clear(tableBox).appendChild(h('div', { class: 'card' }, e.message));
      return;
    }
    if (id !== req) return;
    tableBox.style.opacity = '';
    const ms = res.cols.map((c) => { const [mid, tf] = c.split(':'); return { c, m: metric(mid), tf }; });
    const th = (label, key, cls, title) => h('th', { class: 'sortable ' + (cls || '') + (st.sort === key ? ' sorted' : ''), title: title || null,
      onclick: () => { if (st.sort === key) st.desc = !st.desc; else { st.sort = key; st.desc = key !== 'name'; } st.offset = 0; load(); } },
      label + (st.sort === key ? (st.desc ? ' ↓' : ' ↑') : ''));
    const table = h('table', { class: 'data' },
      h('thead', null, h('tr', null, h('th', { class: 'num' }, '#'), th('Name', 'name'), th('Population', 'pop', 'num'),
        ms.map(({ c, m, tf }, i) => th((m.short || m.name) + (tf !== 'level' ? ' · ' + STATE.transforms[tf] : ''), c, 'num',
          m.desc + (res.periods[i] ? ' (' + periodLabel(res.periods[i]) + ')' : ''))))),
      h('tbody', null, res.rows.map((row, i) => h('tr', { class: 'clickable', onclick: () => navigate('#/region/' + st.level + '/' + encodeURIComponent(row.id)) },
        h('td', { class: 'num muted' }, String(res.offset + i + 1)),
        h('td', null, row.name),
        h('td', { class: 'num' }, fmtPop(row.pop)),
        row.v.map((v, j) => h('td', { class: 'num ' + (ms[j].tf !== 'level' ? deltaClass(v, ms[j].m) : '') }, fmtAny(v, ms[j].m, ms[j].tf)))))));
    clear(tableBox).appendChild(h('div', { class: 'table-wrap', style: { maxHeight: '70vh' } }, table));
    const pages = Math.ceil(res.total / st.limit);
    const pg = Math.floor(st.offset / st.limit) + 1;
    tableBox.appendChild(h('div', { class: 'pager' },
      h('span', { class: 'small muted' }, res.total.toLocaleString() + ' ' + LEVEL_PLURAL[st.level].toLowerCase()),
      h('button', { class: 'btn btn-small', type: 'button', disabled: pg <= 1 ? true : null, onclick: () => { st.offset = Math.max(0, st.offset - st.limit); load(); } }, '‹ Prev'),
      h('span', { class: 'small' }, 'Page ' + pg + ' of ' + Math.max(1, pages)),
      h('button', { class: 'btn btn-small', type: 'button', disabled: pg >= pages ? true : null, onclick: () => { st.offset += st.limit; load(); } }, 'Next ›')));
    if (!res.rows.length) tableBox.appendChild(h('div', { class: 'empty' }, 'No regions match these filters (or data hasn’t been downloaded yet).'));
  }

  drawControls();
  drawCols();
  await load();
  return null;
}
