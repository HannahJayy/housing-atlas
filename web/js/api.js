// Thin fetch wrappers with a small response cache. In the static web version (window.HA_STATIC, written by
// `python app.py export-static`) the same calls are answered from pre-built files by static.js.

import { staticGet, staticPost } from './static.js';

export const STATIC = window.HA_STATIC || null;
const cache = new Map();

export async function api(path, { cache: useCache = false } = {}) {
  if (useCache && cache.has(path)) return cache.get(path);
  const p = STATIC ? staticGet(path) : fetch(path, { credentials: 'same-origin' }).then(async (r) => {
    let data = null;
    try { data = await r.json(); } catch (e) { /* non-JSON */ }
    if (!r.ok) {
      const err = new Error((data && data.error) || ('HTTP ' + r.status));
      err.status = r.status;
      throw err;
    }
    return data;
  });
  if (useCache) {
    cache.set(path, p);
    p.catch(() => cache.delete(path));
    if (cache.size > 300) cache.delete(cache.keys().next().value);
  }
  return p;
}

export async function post(path, body) {
  if (STATIC) return staticPost(path, body);
  const r = await fetch(path, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
  });
  let data = null;
  try { data = await r.json(); } catch (e) { /* ignore */ }
  if (!r.ok) {
    const err = new Error((data && data.error) || ('HTTP ' + r.status));
    err.status = r.status;
    throw err;
  }
  return data;
}

export function clearCache() { cache.clear(); }

// Text endpoints (CSV export).
export async function apiText(path) {
  if (STATIC) return staticGet(path);
  const r = await fetch(path, { credentials: 'same-origin' });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.text();
}

const geoCache = new Map();
export function geo(path) {
  if (!geoCache.has(path)) {
    const p = fetch(STATIC ? path.replace(/^\//, '') : path).then((r) => { if (!r.ok) throw new Error('shapes missing'); return r.json(); });
    p.catch(() => geoCache.delete(path));
    geoCache.set(path, p);
  }
  return geoCache.get(path);
}
