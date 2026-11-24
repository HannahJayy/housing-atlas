// Formatting, periods and color scales.

export const STATE = { meta: null, byId: {}, cats: [], transforms: {}, available: {} };

export function setMeta(meta) {
  STATE.meta = meta;
  STATE.byId = {};
  for (const m of meta.catalog.metrics) STATE.byId[m.id] = m;
  STATE.cats = meta.catalog.categories;
  STATE.transforms = meta.catalog.transforms;
  STATE.available = meta.available || {};
}

export const LEVEL_NAMES = { us: 'U.S.', state: 'State', metro: 'Metro', county: 'County', zip: 'ZIP' };
export const LEVEL_PLURAL = { us: 'U.S.', state: 'States', metro: 'Metros', county: 'Counties', zip: 'ZIP codes' };
export const SRC_NAMES = {
  zillow: 'Zillow', realtor: 'Realtor.com', redfin: 'Redfin', census_acs: 'Census ACS', census_pep: 'Census PEP',
  census_bps: 'Census Building Permits', bea: 'BEA', bls: 'BLS', fred: 'FRED', fhfa: 'FHFA', fema_nri: 'FEMA',
  derived: 'Calculated',
};

export function metric(id) { return STATE.byId[id]; }
export function availableAt(id, level) { return (STATE.available[id] || []).includes(level); }

// ------------------------------------------------------------------ periods
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function periodToTime(p) {
  if (p === null || p === undefined) return null;
  p = String(p);
  let m = p.match(/^(\d{4})-(\d{2})$/);
  if (m) return Date.UTC(+m[1], +m[2] - 1, 15);
  m = p.match(/^(\d{4})-Q([1-4])$/);
  if (m) return Date.UTC(+m[1], (+m[2] - 1) * 3 + 1, 15);
  m = p.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return Date.UTC(+m[1], +m[2] - 1, +m[3]);
  m = p.match(/^(\d{4})$/);
  if (m) return Date.UTC(+m[1], 6, 1);
  return null;
}

export function periodLabel(p) {
  if (!p) return '';
  p = String(p);
  let m = p.match(/^(\d{4})-(\d{2})$/);
  if (m) return MON[+m[2] - 1] + ' ' + m[1];
  m = p.match(/^(\d{4})-Q([1-4])$/);
  if (m) return 'Q' + m[2] + ' ' + m[1];
  m = p.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return MON[+m[2] - 1] + ' ' + (+m[3]) + ', ' + m[1];
  return p;
}

export function timeLabel(t, freq) {
  const d = new Date(t);
  if (freq === 'A') return String(d.getUTCFullYear());
  if (freq === 'Q') return 'Q' + (Math.floor(d.getUTCMonth() / 3) + 1) + ' ' + d.getUTCFullYear();
  if (freq === 'W' || freq === 'D') return MON[d.getUTCMonth()] + ' ' + d.getUTCDate() + ', ' + d.getUTCFullYear();
  return MON[d.getUTCMonth()] + ' ' + d.getUTCFullYear();
}

// ------------------------------------------------------------------ numbers
function compactNum(v, digits = 1) {
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(a >= 1e10 ? 0 : digits).replace(/\.0$/, '') + 'B';
  if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : digits).replace(/\.0$/, '') + 'M';
  if (a >= 1e4) return (v / 1e3).toFixed(0) + 'K';
  if (a >= 1e3) return (v / 1e3).toFixed(digits).replace(/\.0$/, '') + 'K';
  return fixedSmart(v);
}

function fixedSmart(v) {
  const a = Math.abs(v);
  if (a >= 100) return Math.round(v).toLocaleString('en-US');
  if (a >= 10) return v.toFixed(1).replace(/\.0$/, '');
  if (a >= 1) return v.toFixed(2).replace(/0$/, '').replace(/\.0$/, '');
  if (a === 0) return '0';
  return v.toPrecision(2);
}

export function fmtVal(v, m, opts = {}) {
  if (v === null || v === undefined || Number.isNaN(v)) return '–';
  const f = typeof m === 'string' ? m : (m ? m.fmt : 'num');
  const compact = !!opts.compact;
  switch (f) {
    case 'usd': {
      const a = Math.abs(v);
      if (compact && a >= 1000) return (v < 0 ? '-$' : '$') + compactNum(a);
      if (a >= 100) return (v < 0 ? '-$' : '$') + Math.round(a).toLocaleString('en-US');
      return (v < 0 ? '-$' : '$') + a.toFixed(2);
    }
    case 'pct': return (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1)) + '%';
    case 'days': return Math.round(v) + (compact ? 'd' : ' days');
    case 'months': return v.toFixed(1) + (compact ? '' : ' mo');
    case 'ratio': return (Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2)) + '×';
    case 'score': return String(Math.round(v));
    case 'year': return String(Math.round(v));
    default:
      if (compact) return compactNum(v);
      return Math.abs(v) >= 100 ? Math.round(v).toLocaleString('en-US') : fixedSmart(v);
  }
}

export function isChangeTf(tf) { return tf && tf !== 'level'; }

export function fmtChange(v, m, tf, opts = {}) {
  if (v === null || v === undefined || Number.isNaN(v)) return '–';
  const a = Math.abs(v);
  // no sign when the value rounds to zero at the precision we display
  const intLike = m && m.change !== 'pct' && ['days', 'score', 'year'].includes(m.fmt);
  const shown = intLike ? Math.round(a) : Math.round(a * 10) / 10;
  const sign = shown === 0 ? '' : (v > 0 ? '+' : '−');
  if (!m || m.change === 'pct') return sign + (a >= 100 ? a.toFixed(0) : a.toFixed(1)) + '%';
  switch (m.fmt) {
    case 'pct': return sign + a.toFixed(1) + (opts.short ? ' pt' : ' pts');
    case 'days': return sign + Math.round(a) + (opts.short ? 'd' : ' days');
    case 'months': return sign + a.toFixed(1) + ' mo';
    case 'usd': return sign + fmtVal(a, 'usd', { compact: true });
    case 'ratio': return sign + a.toFixed(2);
    case 'score': case 'year': return sign + Math.round(a);
    default: return sign + fmtVal(a, 'num', { compact: true });
  }
}

export function fmtAny(v, m, tf, opts) {
  return isChangeTf(tf) ? fmtChange(v, m, tf, opts) : fmtVal(v, m, opts);
}

// up/down coloring for deltas: 'pos' (bullish/green), 'neg' (bearish/red) or ''
export function deltaClass(v, m) {
  if (v === null || v === undefined || Number.isNaN(v) || v === 0 || !m || !m.polarity) return '';
  return (v > 0) === (m.polarity > 0) ? 'pos' : 'neg';
}

export function fmtPop(v) {
  if (!v) return '–';
  return compactNum(v);
}

// ------------------------------------------------------------------ color scales
const BLUE = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b'];
const RED = ['#fbd3cf', '#f6aaa3', '#ee7b72', '#e34948', '#c0302f', '#962221', '#6e1716'];

export function isDark() {
  const t = document.documentElement.getAttribute('data-theme');
  if (t) return t === 'dark';
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function niceRound(x) {
  if (!isFinite(x) || x === 0) return x;
  const a = Math.abs(x);
  const p = Math.pow(10, Math.floor(Math.log10(a)) - 1);
  return Math.round(x / p) * p;
}

function quantile(sorted, q) {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

/** Build a 7-class (or fewer) choropleth scale for the given values. */
export function makeScale(values, m, tf) {
  const vals = values.filter((v) => v !== null && v !== undefined && isFinite(v)).sort((a, b) => a - b);
  const dark = isDark();
  const nodata = dark ? '#2a2a28' : '#e6e5df';
  if (!vals.length) return { type: 'none', breaks: [], colors: [], nodata, color: () => null };
  const p05 = quantile(vals, 0.05), p95 = quantile(vals, 0.95);
  const diverging = isChangeTf(tf) || (p05 < 0 && p95 > 0) || ['overvalued', 'overvalued_income',
    'overvalued_trend', 'forecast_12m', 'zhvf_1y', 'buy_vs_rent'].includes(m && m.id);
  const pol = (m && m.polarity) || 0;
  if (diverging && (p05 < 0 || p95 > 0)) {
    const a = Math.max(Math.abs(p05), Math.abs(p95)) || 1;
    let b1 = niceRound(a * 0.12), b2 = niceRound(a * 0.45), b3 = niceRound(a * 0.8);
    if (b1 >= b2) b2 = b1 * 2;
    if (b2 >= b3) b3 = b2 * 1.6;
    const breaks = [-b3, -b2, -b1, b1, b2, b3];
    const neg = [RED[5], RED[3], RED[1]];
    const posC = [BLUE[1], BLUE[3], BLUE[5]];
    const mid = dark ? '#383835' : '#f0efec';
    let lowArm = neg, highArm = posC;
    if (pol < 0) { lowArm = [BLUE[5], BLUE[3], BLUE[1]]; highArm = [RED[1], RED[3], RED[5]]; }
    if (dark) {  // extremes glow, near-zero recedes into the dark surface
      lowArm = pol < 0 ? [BLUE[1], BLUE[3], BLUE[5]] : [RED[1], RED[3], RED[5]];
      highArm = pol < 0 ? [RED[5], RED[3], RED[1]] : [BLUE[5], BLUE[3], BLUE[1]];
    }
    const colors = [...lowArm, mid, ...highArm];
    return finalize({ type: 'diverging', breaks, colors, nodata, min: vals[0], max: vals[vals.length - 1] });
  }
  // sequential quantiles
  const ramp = pol < 0 ? RED : BLUE;
  const uniq = [...new Set(vals)];
  const k = Math.min(7, Math.max(1, uniq.length));
  const breaks = [];
  for (let i = 1; i < k; i++) breaks.push(quantile(vals, i / k));
  const cleaned = [];
  for (const b of breaks) if (!cleaned.length || b > cleaned[cleaned.length - 1]) cleaned.push(b);
  let colors = cleaned.length + 1 === 7 ? ramp.slice() : pickSteps(ramp, cleaned.length + 1);
  // dark mode: low values recede into the dark surface, high values are the brightest step
  if (dark) colors = colors.slice().reverse();
  return finalize({ type: 'sequential', breaks: cleaned, colors, nodata, min: vals[0], max: vals[vals.length - 1] });
}

function pickSteps(ramp, n) {
  if (n <= 1) return [ramp[3]];
  const out = [];
  for (let i = 0; i < n; i++) out.push(ramp[Math.round(i * (ramp.length - 1) / (n - 1))]);
  return out;
}

function finalize(sc) {
  sc.color = (v) => {
    if (v === null || v === undefined || !isFinite(v)) return null;
    let i = 0;
    while (i < sc.breaks.length && v >= sc.breaks[i]) i++;
    return sc.colors[Math.min(i, sc.colors.length - 1)];
  };
  return sc;
}

export function legendItems(sc, m, tf) {
  const f = (v) => fmtAny(v, m, tf, { compact: true, short: true });
  const items = [];
  const b = sc.breaks;
  for (let i = 0; i < sc.colors.length; i++) {
    let label;
    if (b.length === 0) label = 'All values';
    else if (i === 0) label = '< ' + f(b[0]);
    else if (i === sc.colors.length - 1) label = '≥ ' + f(b[b.length - 1]);
    else label = f(b[i - 1]) + ' to ' + f(b[i]);
    items.push({ color: sc.colors[i], label });
  }
  return items;
}

export const SERIES_COLORS = () => {
  const cs = getComputedStyle(document.documentElement);
  return ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'].map((v) => cs.getPropertyValue(v).trim() || '#2a78d6');
};
