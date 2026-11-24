// Small DOM helpers. All text goes through textContent (never innerHTML) so data
// coming from files/APIs can't inject markup.

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked') el.checked = !!v;
      else if (k === 'html') throw new Error('html attr not allowed');
      else el.setAttribute(k, v === true ? '' : v);
    }
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else if (c instanceof Node) el.appendChild(c);
    else el.appendChild(document.createTextNode(String(c)));
  }
}

const SVGNS = 'http://www.w3.org/2000/svg';
export function s(tag, attrs, ...children) {
  const el = document.createElementNS(SVGNS, tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

let toastTimer = null;
export function toast(msg, ms = 2600) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, ms);
}

export function debounce(fn, ms) {
  let t = null;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

export function parseQuery(str) {
  const out = {};
  new URLSearchParams(str || '').forEach((v, k) => { out[k] = v; });
  return out;
}

export function buildQuery(obj) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(obj)) if (v !== null && v !== undefined && v !== '') p.set(k, v);
  const q = p.toString();
  return q ? '?' + q : '';
}

export function seg(options, value, onChange, opts = {}) {
  const wrap = h('div', { class: 'seg', role: 'group', 'aria-label': opts.label || null });
  for (const o of options) {
    const b = h('button', {
      type: 'button', class: o.value === value ? 'on' : '', disabled: o.disabled || null,
      title: o.title || null, 'aria-pressed': o.value === value ? 'true' : 'false',
      onclick: () => { if (!o.disabled) onChange(o.value); },
    }, o.label);
    wrap.appendChild(b);
  }
  return wrap;
}

export function spinner() { return h('span', { class: 'spinner' }); }

export function downloadText(name, text, type = 'text/csv') {
  if (window.HA_STATIC && window.HA_STATIC.preview) {
    // the preview runs in a sandboxed frame that blocks downloads - copy instead
    const done = () => toast('Copied ' + name + ' to the clipboard (downloads are blocked in this preview)');
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, () => toast('Downloads and copying are blocked in this preview'));
    } else toast('Downloads are blocked in this preview');
    return;
  }
  const blob = new Blob([text], { type });
  const a = h('a', { href: URL.createObjectURL(blob), download: name });
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}
