// Free local accounts: sign in / register, watchlist and saved map views.

import { api, post } from '../api.js';
import { h, clear, toast, buildQuery } from '../ui.js';
import { metric, fmtVal, fmtChange, deltaClass, LEVEL_NAMES } from '../fmt.js';
import { APP, refreshMeta, navigate } from '../app.js';

const WATCH_COLS = [['zhvi', null], ['zhvi', 'yoy'], ['overvalued', null], ['forecast_12m', null], ['inventory', 'vs_pre'],
  ['price_cut_share', null], ['dom', null], ['payment_to_income', null], ['rent', null]];

export async function render(root, params) {
  const page = h('div', { class: 'page' });
  root.appendChild(page);
  const me = await api('/api/auth/me');
  if (!me.user) return drawLogin(page, params.name === 'watchlist');
  if (params.name === 'watchlist') return drawWatchlist(page, me);
  if (me.user.local) return drawLocal(page, me);
  return drawAccount(page, me);
}

function drawLocal(page, me) {
  page.appendChild(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'My places'),
    h('p', null, 'No account needed in the web version: your watchlist and saved map views are kept in this browser on this device.'))));
  const views = h('div', { class: 'card' }, h('h2', null, 'Saved map views'));
  if (!me.views.length) views.appendChild(h('p', { class: 'muted' }, 'No saved views yet – use “Save view” in the map panel.'));
  for (const v of me.views) {
    views.appendChild(h('div', { class: 'row', style: { padding: '6px 0', borderBottom: '1px solid var(--grid)' } },
      h('a', { href: '#/map' + buildQuery(v.state || {}) }, v.name), h('span', { class: 'small muted' }, v.created), h('span', { class: 'spacer' }),
      h('button', { class: 'btn btn-small btn-ghost', type: 'button', onclick: async () => { await post('/api/views/remove', { id: v.id }); navigate('#/account'); } }, 'Delete')));
  }
  page.appendChild(views);
  page.appendChild(h('p', { style: { marginTop: '16px' } }, h('a', { class: 'btn', href: '#/watchlist' }, 'Open watchlist (' + me.watchlist.length + ')')));
  return null;
}

function drawLogin(page, fromWatchlist) {
  page.appendChild(h('div', { class: 'page-head' }, h('div', null, h('h1', null, fromWatchlist ? 'Watchlist' : 'Your account'),
    h('p', null, 'Accounts are free and stored only on this computer. Every metric is visible without an account; signing in lets you keep a watchlist and saved map views.'))));
  const mk = (mode) => {
    const user = h('input', { class: 'input', autocomplete: 'username', 'aria-label': 'Username' });
    const pass = h('input', { class: 'input', type: 'password', autocomplete: mode === 'login' ? 'current-password' : 'new-password', 'aria-label': 'Password' });
    const err = h('div', { class: 'small', style: { color: 'var(--bad)', minHeight: '18px' } });
    const form = h('form', { class: 'card', onsubmit: async (e) => {
      e.preventDefault();
      err.textContent = '';
      try {
        await post(mode === 'login' ? '/api/auth/login' : '/api/auth/register', { username: user.value, password: pass.value });
        await refreshMeta();
        toast(mode === 'login' ? 'Signed in' : 'Account created – welcome!');
        navigate(fromWatchlist ? '#/watchlist' : '#/account');
      } catch (ex) { err.textContent = ex.message; }
    } },
    h('h2', null, mode === 'login' ? 'Sign in' : 'Create a free account'),
    h('div', { class: 'grid', style: { gap: '10px' } },
      h('label', { class: 'field' }, 'Username', user),
      h('label', { class: 'field' }, 'Password' + (mode === 'login' ? '' : ' (6+ characters)'), pass),
      err,
      h('button', { class: 'btn btn-primary', type: 'submit' }, mode === 'login' ? 'Sign in' : 'Create account')),
    mode === 'register' && !APP.meta.users_exist ? h('p', { class: 'small muted', style: { marginTop: '8px' } }, 'The first account becomes the admin (can run updates and change settings from other devices).') : null);
    return form;
  };
  page.appendChild(h('div', { class: 'grid grid-2' }, mk('login'), mk('register')));
  return null;
}

async function drawAccount(page, me) {
  page.appendChild(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Hi, ' + me.user.username),
    h('p', null, me.user.is_admin ? 'Admin account – you can run updates and change settings from any device.' : 'Standard account.')),
    h('button', { class: 'btn', type: 'button', onclick: async () => { await post('/api/auth/logout', {}); await refreshMeta(); navigate('#/account'); } }, 'Sign out')));
  const views = h('div', { class: 'card' }, h('h2', null, 'Saved map views'));
  if (!me.views.length) views.appendChild(h('p', { class: 'muted' }, 'No saved views yet – use “Save view” in the map panel.'));
  for (const v of me.views) {
    views.appendChild(h('div', { class: 'row', style: { padding: '6px 0', borderBottom: '1px solid var(--grid)' } },
      h('a', { href: '#/map' + buildQuery(v.state || {}) }, v.name), h('span', { class: 'small muted' }, v.created), h('span', { class: 'spacer' }),
      h('button', { class: 'btn btn-small btn-ghost', type: 'button', onclick: async () => { await post('/api/views/remove', { id: v.id }); navigate('#/account'); location.reload(); } }, 'Delete')));
  }
  const oldp = h('input', { class: 'input', type: 'password', autocomplete: 'current-password' });
  const newp = h('input', { class: 'input', type: 'password', autocomplete: 'new-password' });
  const pw = h('form', { class: 'card', onsubmit: async (e) => {
    e.preventDefault();
    try { await post('/api/auth/password', { old: oldp.value, new: newp.value }); toast('Password changed'); oldp.value = newp.value = ''; } catch (ex) { toast(ex.message); }
  } }, h('h2', null, 'Change password'), h('div', { class: 'grid', style: { gap: '10px' } },
    h('label', { class: 'field' }, 'Current password', oldp), h('label', { class: 'field' }, 'New password', newp),
    h('button', { class: 'btn', type: 'submit' }, 'Update password')));
  page.appendChild(h('div', { class: 'grid grid-2' }, views, pw));
  page.appendChild(h('p', { style: { marginTop: '16px' } }, h('a', { class: 'btn', href: '#/watchlist' }, 'Open watchlist (' + me.watchlist.length + ')')));
  return null;
}

async function drawWatchlist(page, me) {
  page.appendChild(h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Watchlist'),
    h('p', null, 'Markets you follow. Add places with the ☆ Watch button on any map popup or region report.'))));
  const res = await api('/api/watchlist');
  if (!res.watchlist.length) {
    page.appendChild(h('div', { class: 'empty card' }, 'Your watchlist is empty. Search for a place and click “☆ Add to watchlist”.'));
    return null;
  }
  const infos = await Promise.all(res.watchlist.map((w) => api('/api/region?level=' + w.level + '&id=' + encodeURIComponent(w.id), { cache: true }).catch(() => null)));
  const rows = res.watchlist.map((w, i) => {
    const r = infos[i];
    return h('tr', { class: 'clickable', onclick: () => navigate('#/region/' + w.level + '/' + encodeURIComponent(w.id)) },
      h('td', null, r ? r.name : w.name), h('td', { class: 'muted' }, LEVEL_NAMES[w.level]),
      WATCH_COLS.map(([mid, tf]) => {
        const m = metric(mid);
        const e = r && r.metrics[mid];
        if (!e) return h('td', { class: 'num' }, '–');
        const v = tf ? e.t[tf] : e.v;
        return h('td', { class: 'num ' + (tf ? deltaClass(v, m) : '') }, v === undefined ? '–' : (tf ? fmtChange(v, m, tf, { short: true }) : fmtVal(v, m)));
      }),
      h('td', null, h('button', { class: 'btn btn-small btn-ghost', type: 'button', onclick: async (e) => {
        e.stopPropagation();
        await post('/api/watchlist/remove', { level: w.level, id: w.id });
        navigate('#/watchlist');
      } }, 'Remove')));
  });
  page.appendChild(h('div', { class: 'table-wrap' }, h('table', { class: 'data' },
    h('thead', null, h('tr', null, h('th', null, 'Place'), h('th', null, 'Level'),
      WATCH_COLS.map(([mid, tf]) => h('th', { class: 'num' }, (metric(mid).short || metric(mid).name) + (tf === 'yoy' ? ' 1-yr' : tf === 'vs_pre' ? ' vs 2019' : ''))), h('th', null, ''))),
    h('tbody', null, rows))));
  const items = res.watchlist.slice(0, 6).map((w) => w.level + ':' + w.id).join(',');
  page.appendChild(h('p', { style: { marginTop: '12px' } }, h('a', { class: 'btn', href: '#/compare?items=' + encodeURIComponent(items) }, 'Compare these on a chart')));
  return null;
}
