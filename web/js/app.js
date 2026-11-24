// App shell: boot, theme, navigation, search, update banner and the hash router.

import { api } from './api.js';
import { h, clear, debounce, parseQuery, toast } from './ui.js';
import { setMeta, STATE, LEVEL_NAMES } from './fmt.js';

const VIEWS = {
  map: () => import('./views/mapview.js'),
  region: () => import('./views/region.js'),
  rankings: () => import('./views/rankings.js'),
  compare: () => import('./views/compare.js'),
  national: () => import('./views/national.js'),
  watchlist: () => import('./views/account.js'),
  account: () => import('./views/account.js'),
  sources: () => import('./views/sources.js'),
  methodology: () => import('./views/methodology.js'),
};

export const APP = { meta: null, user: null, current: null, route: null };

export async function refreshMeta() {
  const meta = await api('/api/meta');
  APP.meta = meta;
  APP.user = meta.user;
  setMeta(meta);
  updateAccountButton();
  return meta;
}

export function navigate(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

function updateAccountButton() {
  const b = document.getElementById('account-btn');
  b.textContent = APP.user ? APP.user.username : 'Sign in';
}

function staticBanner() {
  const cfg = window.HA_STATIC;
  if (!cfg) return;
  const text = cfg.banner || ('Web version · data as of ' + ((APP.meta && APP.meta.last_update) || cfg.built || '').slice(0, 10));
  const b = h('div', { class: 'update-banner static-banner', role: 'note' }, h('span', null, text));
  const upd = document.getElementById('update-banner');
  upd.parentNode.insertBefore(b, upd);
  const fit = () => document.documentElement.style.setProperty('--static-banner', b.offsetHeight + 'px');
  fit();
  window.addEventListener('resize', fit);
}

// ---------------------------------------------------------------- theme
function setupTheme() {
  const btn = document.getElementById('theme-btn');
  btn.addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme')
      || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('ha-theme', next); } catch (e) { /* ignore */ }
    window.dispatchEvent(new CustomEvent('ha:theme'));
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => window.dispatchEvent(new CustomEvent('ha:theme')));
}

// ---------------------------------------------------------------- mobile menu
function setupMenu() {
  const btn = document.getElementById('menu-btn');
  const nav = document.getElementById('mainnav');
  btn.addEventListener('click', () => {
    const open = !nav.classList.contains('open');
    nav.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', String(open));
  });
  nav.addEventListener('click', (e) => { if (e.target.tagName === 'A') nav.classList.remove('open'); });
}

// ---------------------------------------------------------------- search
function setupSearch() {
  const input = document.getElementById('search');
  const box = document.getElementById('search-results');
  let results = [];
  let active = -1;
  const KIND = { state: 'State', metro: 'Metro', county: 'County', zip: 'ZIP', city: 'City' };
  const close = () => { box.hidden = true; active = -1; };
  const choose = (r) => {
    close();
    input.value = '';
    input.blur();
    const ev = new CustomEvent('ha:select-region', { detail: r, cancelable: true });
    if (window.dispatchEvent(ev)) navigate('#/region/' + r.level + '/' + encodeURIComponent(r.id));
  };
  const renderResults = () => {
    clear(box);
    if (!results.length) {
      box.appendChild(h('div', { class: 'muted', style: { padding: '10px 12px' } }, 'No matches'));
    }
    results.forEach((r, i) => {
      box.appendChild(h('button', { type: 'button', class: i === active ? 'active' : '', role: 'option',
        onmousedown: (e) => { e.preventDefault(); choose(r); } },
        h('span', { class: 'kind' }, KIND[r.kind] || LEVEL_NAMES[r.level]), h('span', null, r.name)));
    });
    box.hidden = false;
  };
  const run = debounce(async () => {
    const q = input.value.trim();
    if (q.length < 2) { close(); return; }
    try {
      const res = await api('/api/search?q=' + encodeURIComponent(q), { cache: true });
      results = res.results || [];
      active = results.length ? 0 : -1;
      renderResults();
    } catch (e) { close(); }
  }, 160);
  input.addEventListener('input', run);
  input.addEventListener('keydown', (e) => {
    if (box.hidden) return;
    if (e.key === 'ArrowDown') { active = Math.min(results.length - 1, active + 1); renderResults(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { active = Math.max(0, active - 1); renderResults(); e.preventDefault(); }
    else if (e.key === 'Enter' && results[active]) { choose(results[active]); e.preventDefault(); }
    else if (e.key === 'Escape') close();
  });
  input.addEventListener('blur', () => setTimeout(close, 120));
}

// ---------------------------------------------------------------- update banner
let pollTimer = null;
let wasRunning = false;
let pollCount = 0;
export async function pollUpdate(force) {
  clearTimeout(pollTimer);
  let st;
  try { st = await api('/api/update/status'); } catch (e) { pollTimer = setTimeout(pollUpdate, 8000); return; }
  const banner = document.getElementById('update-banner');
  if (st.running) {
    clear(banner);
    banner.appendChild(h('span', { class: 'spinner' }));
    banner.appendChild(h('span', null, h('b', null, 'Updating data… '), st.message || ''));
    banner.appendChild(h('span', { class: 'spacer' }));
    banner.appendChild(h('a', { href: '#/sources' }, 'Details'));
    banner.hidden = false;
    document.body.classList.add('updating');
    wasRunning = true;
    window.dispatchEvent(new CustomEvent('ha:update-progress', { detail: st }));
    // during the very first download, show the map as soon as the first layers are published
    if (APP.meta && !APP.meta.has_data && (++pollCount % 8 === 0)) {
      try {
        const had = APP.meta.has_data;
        await refreshMeta();
        if (!had && APP.meta.has_data && APP.route && APP.route.name === 'map') route();
      } catch (e) { /* ignore */ }
    }
    pollTimer = setTimeout(pollUpdate, 2500);
  } else {
    banner.hidden = true;
    document.body.classList.remove('updating');
    if (wasRunning) {
      wasRunning = false;
      toast('Data update finished');
      await refreshMeta();
      window.dispatchEvent(new CustomEvent('ha:data-updated', { detail: st }));
      route();
    }
    if (force) pollTimer = setTimeout(pollUpdate, 2500);
  }
  window.dispatchEvent(new CustomEvent('ha:banner'));
}

// ---------------------------------------------------------------- router
async function route() {
  const raw = location.hash.replace(/^#\/?/, '') || 'map';
  const [pathPart, query] = raw.split('?');
  const parts = pathPart.split('/').map(decodeURIComponent);
  const name = VIEWS[parts[0]] ? parts[0] : 'map';
  for (const a of document.querySelectorAll('#mainnav a')) a.classList.toggle('active', a.dataset.nav === name);
  const view = document.getElementById('view');
  const params = { name, parts: parts.slice(1), query: parseQuery(query) };
  if (APP.current && APP.current.destroy) {
    try { APP.current.destroy(); } catch (e) { /* ignore */ }
  }
  APP.current = null;
  const sameView = APP.route && APP.route.name === name && name === 'map';
  APP.route = params;
  try {
    const mod = await VIEWS[name]();
    if (APP.route !== params) return; // a newer navigation happened
    clear(view);
    APP.current = (await mod.render(view, params, APP)) || null;
    if (!sameView) window.scrollTo(0, 0);
  } catch (e) {
    console.error(e);
    clear(view).appendChild(h('div', { class: 'page' }, h('div', { class: 'card' }, h('h2', null, 'Something went wrong'),
      h('p', { class: 'secondary' }, String(e.message || e)))));
  }
}

async function boot() {
  setupTheme();
  setupMenu();
  setupSearch();
  try {
    await refreshMeta();
  } catch (e) {
    clear(document.getElementById('view')).appendChild(h('div', { class: 'page' }, h('div', { class: 'card' },
      h('h2', null, 'Cannot reach the Housing Atlas server'), h('p', null, String(e.message)))));
    return;
  }
  staticBanner();
  window.addEventListener('hashchange', route);
  await route();
  if (!window.HA_STATIC) pollUpdate();
}

boot();
export { route, STATE };
