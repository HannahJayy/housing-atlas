// Searchable metric picker (modal), grouped by category.

import { h, clear } from './ui.js';
import { STATE, availableAt, SRC_NAMES } from './fmt.js';

export function openMetricPicker({ level, current, onPick, title }) {
  const back = h('div', { class: 'picker-back', role: 'dialog', 'aria-modal': 'true', 'aria-label': title || 'Choose a metric' });
  const input = h('input', { class: 'input', type: 'search', placeholder: 'Search metrics (e.g. inventory, rent, overvalued)…', 'aria-label': 'Search metrics' });
  const body = h('div', { class: 'picker-body' });
  const close = () => { back.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);
  back.addEventListener('click', (e) => { if (e.target === back) close(); });

  function draw() {
    clear(body);
    const q = input.value.trim().toLowerCase();
    let shown = 0;
    const named = new Set();
    if (q) {
      const best = STATE.meta.catalog.metrics.filter((m) => m.name.toLowerCase().includes(q) && (!level || availableAt(m.id, level)));
      if (best.length) {
        body.appendChild(h('div', { class: 'picker-cat' }, 'Best matches'));
        for (const m of best) {
          named.add(m.id);
          body.appendChild(h('button', { type: 'button', class: 'picker-item' + (m.id === current ? ' on' : ''), title: m.desc,
            onclick: () => { close(); onPick(m.id); } }, h('div', { class: 't' }, m.name), h('div', { class: 's' }, SRC_NAMES[m.src] || m.src)));
          shown++;
        }
      }
    }
    for (const cat of STATE.cats) {
      const items = STATE.meta.catalog.metrics.filter((m) => m.cat === cat.id && !named.has(m.id) && (!q
        || m.name.toLowerCase().includes(q) || m.desc.toLowerCase().includes(q) || (SRC_NAMES[m.src] || '').toLowerCase().includes(q)));
      if (q) items.sort((a, b) => (b.name.toLowerCase().includes(q) ? 1 : 0) - (a.name.toLowerCase().includes(q) ? 1 : 0));
      const avail = items.filter((m) => !level || availableAt(m.id, level));
      const unavailable = items.filter((m) => level && !availableAt(m.id, level) && (STATE.available[m.id] || []).length);
      if (!avail.length && !unavailable.length) continue;
      body.appendChild(h('div', { class: 'picker-cat' }, cat.name));
      for (const m of [...avail, ...unavailable]) {
        const ok = !level || availableAt(m.id, level);
        const lv = (STATE.available[m.id] || []).join(', ');
        body.appendChild(h('button', {
          type: 'button', class: 'picker-item' + (m.id === current ? ' on' : ''), disabled: ok ? null : true,
          title: ok ? m.desc : 'Not available at this geography (available: ' + lv + ')',
          onclick: () => { close(); onPick(m.id); },
        }, h('div', { class: 't' }, m.name), h('div', { class: 's' }, (SRC_NAMES[m.src] || m.src) + (ok ? '' : ' · not at this level'))));
        shown++;
      }
    }
    if (!shown) body.appendChild(h('div', { class: 'muted', style: { padding: '20px' } }, 'No metrics match. Data may not be downloaded yet.'));
  }
  input.addEventListener('input', draw);
  back.appendChild(h('div', { class: 'picker' },
    h('div', { class: 'picker-head' }, input, h('button', { class: 'btn', type: 'button', onclick: close }, 'Close')),
    body));
  document.body.appendChild(back);
  draw();
  setTimeout(() => input.focus(), 30);
}
