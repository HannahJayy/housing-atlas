// Lightweight SVG line chart: 2px lines, hairline grid, end-dot with surface ring,
// crosshair + tooltip listing every series, keyboard-accessible.

import { h, s, clear } from './ui.js';
import { timeLabel } from './fmt.js';

function niceStep(range, count) {
  const raw = range / Math.max(1, count);
  const p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const n = raw / p;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * p;
}

export function niceTicks(min, max, count = 5) {
  if (!isFinite(min) || !isFinite(max)) return [];
  if (min === max) { const d = Math.abs(min) * 0.1 || 1; min -= d; max += d; }
  const step = niceStep(max - min, count);
  const out = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-9; v += step) out.push(+v.toPrecision(12));
  return out;
}

function cssVar(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

function bisectT(points, t) {
  let lo = 0, hi = points.length - 1;
  if (hi < 0) return -1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (points[mid][0] < t) lo = mid + 1; else hi = mid;
  }
  if (lo > 0 && Math.abs(points[lo - 1][0] - t) < Math.abs(points[lo][0] - t)) lo--;
  return lo;
}

export function lineChart(el, opts) {
  const state = { opts, ro: null, hoverT: null };
  const box = h('div', { class: 'chart-box' });
  clear(el).appendChild(box);
  const tip = h('div', { class: 'chart-tip', hidden: true });
  box.appendChild(tip);

  function render() {
    const o = state.opts;
    const W = Math.max(240, box.clientWidth || el.clientWidth || 600);
    const H = o.height || 220;
    const fmt = o.fmt || ((v) => String(v));
    const axisFmt = o.axisFmt || fmt;
    const series = (o.series || []).map((sr) => ({
      ...sr, points: (sr.points || []).filter((p) => p[1] !== null && p[1] !== undefined && isFinite(p[1])
        && (!o.range || p[0] >= o.range[0])),
    })).filter((sr) => sr.points.length);
    // keep only svg (remove previous svg, keep tooltip)
    for (const c of [...box.children]) if (c !== tip) c.remove();
    if (!series.length) {
      box.appendChild(h('div', { class: 'chart-empty' }, o.emptyText || 'No data for this period.'));
      return;
    }
    let tMin = Infinity, tMax = -Infinity, vMin = Infinity, vMax = -Infinity;
    for (const sr of series) for (const [t, v] of sr.points) {
      if (t < tMin) tMin = t; if (t > tMax) tMax = t;
      if (v < vMin) vMin = v; if (v > vMax) vMax = v;
    }
    if (o.range) { tMin = Math.min(tMin, o.range[0]); tMax = Math.max(tMax, o.range[1]); tMin = Math.max(tMin, o.range[0]); }
    if (o.zero) { vMin = Math.min(vMin, 0); vMax = Math.max(vMax, 0); }
    const pad = (vMax - vMin) * 0.06 || Math.abs(vMax) * 0.05 || 1;
    let y0 = vMin - pad, y1 = vMax + pad;
    if (vMin >= 0 && y0 < 0 && !o.zero) y0 = Math.max(0, y0);
    const yt = niceTicks(y0, y1, H < 180 ? 3 : 5);
    if (yt.length) { y0 = Math.min(y0, yt[0]); y1 = Math.max(y1, yt[yt.length - 1]); }
    const labelW = Math.max(...yt.map((v) => axisFmt(v).length)) * 6.6 + 10;
    const endLabel = series.length === 1 && o.endLabel !== false;
    const m = { l: Math.max(34, labelW), r: endLabel ? 64 : 14, t: 10, b: 24 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    if (tMax === tMin) tMax = tMin + 86400000 * 30;
    const X = (t) => m.l + (t - tMin) / (tMax - tMin) * iw;
    const Y = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * ih;
    const grid = cssVar('--grid', '#e1e0d9'), axis = cssVar('--axis', '#c3c2b7');
    const muted = cssVar('--muted', '#898781'), text = cssVar('--text', '#0b0b0b');
    const surface = cssVar('--surface', '#fcfcfb'), text2 = cssVar('--text-2', '#52514e');

    const svg = s('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, tabindex: 0, role: 'img',
      'aria-label': o.ariaLabel || 'Line chart' });
    // y grid + labels
    const gAxis = s('g', { class: 'axis', 'font-size': 11, fill: muted });
    for (const v of yt) {
      const y = Y(v);
      svg.appendChild(s('line', { x1: m.l, x2: W - m.r, y1: y, y2: y, stroke: (v === 0 && o.zero) ? axis : grid,
        'stroke-width': 1, 'shape-rendering': 'crispEdges' }));
      gAxis.appendChild(s('text', { x: m.l - 6, y: y + 3.5, 'text-anchor': 'end' }, axisFmt(v)));
    }
    // x ticks (years)
    const y0yr = new Date(tMin).getUTCFullYear(), y1yr = new Date(tMax).getUTCFullYear();
    const span = Math.max(1, y1yr - y0yr);
    const maxTicks = Math.max(2, Math.floor(iw / 62));
    const stepYr = [1, 2, 5, 10, 20, 25, 50].find((st) => span / st <= maxTicks) || 50;
    if (span <= 2 && iw > 300) {
      // short ranges: quarterly month ticks
      const d = new Date(tMin);
      let yy = d.getUTCFullYear(), mm = Math.floor(d.getUTCMonth() / 3) * 3 + 3;
      const MON = ['Jan', 'Apr', 'Jul', 'Oct'];
      for (let i = 0; i < 16; i++) {
        if (mm >= 12) { mm -= 12; yy++; }
        const t = Date.UTC(yy, mm, 1);
        if (t > tMax) break;
        if (t >= tMin) {
          gAxis.appendChild(s('text', { x: X(t), y: H - 6, 'text-anchor': 'middle' }, MON[mm / 3] + ' ' + String(yy).slice(2)));
        }
        mm += 3;
      }
    } else {
      for (let yr = Math.ceil(y0yr / stepYr) * stepYr; yr <= y1yr; yr += stepYr) {
        const t = Date.UTC(yr, 0, 1);
        if (t < tMin || t > tMax) continue;
        const x = X(t);
        svg.appendChild(s('line', { x1: x, x2: x, y1: H - m.b, y2: H - m.b + 4, stroke: axis, 'shape-rendering': 'crispEdges' }));
        gAxis.appendChild(s('text', { x, y: H - 6, 'text-anchor': 'middle' }, String(yr)));
      }
    }
    svg.appendChild(s('line', { x1: m.l, x2: W - m.r, y1: H - m.b + 0.5, y2: H - m.b + 0.5, stroke: axis,
      'shape-rendering': 'crispEdges' }));
    svg.appendChild(gAxis);
    // shaded bands (e.g. forecast window)
    for (const band of o.bands || []) {
      const xa = X(Math.max(tMin, band[0])), xb = X(Math.min(tMax, band[1]));
      if (xb > xa) svg.appendChild(s('rect', { x: xa, y: m.t, width: xb - xa, height: ih, fill: cssVar('--accent-wash', 'rgba(42,120,214,.1)') }));
    }
    // series
    const gap = o.gapMs || (86400000 * 75);
    series.forEach((sr, si) => {
      let d = '';
      let prevT = null;
      for (const [t, v] of sr.points) {
        const cmd = (prevT === null || t - prevT > (sr.gapMs || gap)) ? 'M' : 'L';
        d += cmd + X(t).toFixed(1) + ' ' + Y(v).toFixed(1);
        prevT = t;
      }
      if (series.length === 1 && o.area !== false) {
        const pts = sr.points;
        const base = Y(Math.max(y0, Math.min(y1, o.zero ? 0 : y0)));
        const ad = d + 'L' + X(pts[pts.length - 1][0]).toFixed(1) + ' ' + base + 'L' + X(pts[0][0]).toFixed(1) + ' ' + base + 'Z';
        if (!/M.*M/.test(d)) svg.appendChild(s('path', { d: ad, fill: sr.color, 'fill-opacity': 0.1, stroke: 'none' }));
      }
      svg.appendChild(s('path', { d, fill: 'none', stroke: sr.color, 'stroke-width': sr.width || 2,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'stroke-dasharray': sr.dash || null }));
      const last = sr.points[sr.points.length - 1];
      svg.appendChild(s('circle', { cx: X(last[0]), cy: Y(last[1]), r: 4, fill: sr.color, stroke: surface, 'stroke-width': 2 }));
      if (endLabel) {
        svg.appendChild(s('text', { x: X(last[0]) + 8, y: Y(last[1]) + 4, 'font-size': 12, 'font-weight': 650, fill: text },
          fmt(last[1])));
      }
    });
    // crosshair layer
    const cross = s('line', { y1: m.t, y2: H - m.b, stroke: axis, 'stroke-width': 1, visibility: 'hidden' });
    const dots = series.map((sr) => s('circle', { r: 4, fill: sr.color, stroke: surface, 'stroke-width': 2, visibility: 'hidden' }));
    svg.appendChild(cross);
    dots.forEach((d) => svg.appendChild(d));
    const hit = s('rect', { x: m.l, y: 0, width: iw, height: H, fill: 'transparent', style: 'cursor:crosshair' });
    svg.appendChild(hit);
    const allT = [...new Set(series.flatMap((sr) => sr.points.map((p) => p[0])))].sort((a, b) => a - b);

    function show(t) {
      if (t === null) {
        cross.setAttribute('visibility', 'hidden'); dots.forEach((d) => d.setAttribute('visibility', 'hidden'));
        tip.hidden = true; return;
      }
      const x = X(t);
      cross.setAttribute('x1', x); cross.setAttribute('x2', x); cross.setAttribute('visibility', 'visible');
      clear(tip);
      tip.appendChild(h('div', { class: 'date' }, timeLabel(t, o.freq)));
      series.forEach((sr, i) => {
        const idx = bisectT(sr.points, t);
        const p = sr.points[idx];
        const near = p && Math.abs(p[0] - t) <= (o.freq === 'A' ? 86400000 * 200 : o.freq === 'Q' ? 86400000 * 50 : 86400000 * 20);
        if (!near) { dots[i].setAttribute('visibility', 'hidden'); return; }
        dots[i].setAttribute('cx', X(p[0])); dots[i].setAttribute('cy', Y(p[1])); dots[i].setAttribute('visibility', 'visible');
        tip.appendChild(h('div', { class: 'r' }, h('i', { style: { background: sr.color } }), h('b', null, fmt(p[1])),
          series.length > 1 ? h('span', null, sr.name) : null));
      });
      tip.hidden = false;
      const bw = box.clientWidth;
      const tw = tip.offsetWidth;
      let left = x + 12;
      if (left + tw > bw) left = x - tw - 12;
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = (m.t + 4) + 'px';
    }
    const allTP = allT.map((v) => [v]);
    function nearestT(px) {
      const t = tMin + (px - m.l) / iw * (tMax - tMin);
      return allT[bisectT(allTP, t)];
    }
    hit.addEventListener('pointermove', (e) => {
      const r = svg.getBoundingClientRect();
      const px = (e.clientX - r.left) * (W / r.width);
      state.hoverT = nearestT(px);
      show(state.hoverT);
    });
    hit.addEventListener('pointerleave', () => { state.hoverT = null; show(null); });
    svg.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      e.preventDefault();
      let i = state.hoverT === null ? allT.length - 1 : allT.indexOf(state.hoverT);
      i = Math.max(0, Math.min(allT.length - 1, i + (e.key === 'ArrowRight' ? 1 : -1)));
      state.hoverT = allT[i];
      show(state.hoverT);
    });
    svg.addEventListener('blur', () => show(null));
    box.insertBefore(svg, tip);
  }

  render();
  state.ro = new ResizeObserver(() => { clearTimeout(state.rt); state.rt = setTimeout(render, 60); });
  state.ro.observe(box);
  return {
    update(newOpts) { state.opts = Object.assign({}, state.opts, newOpts); render(); },
    destroy() { state.ro.disconnect(); },
  };
}

export function legend(series) {
  if (!series || series.length < 2) return null;
  return h('div', { class: 'chart-legend' }, series.map((sr) =>
    h('span', null, h('i', { style: { background: sr.color, height: sr.dash ? '0' : '2px',
      borderTop: sr.dash ? '2px dashed ' + sr.color : null } }), sr.name)));
}

export function sparkline(points, color, w = 64, hgt = 22) {
  const pts = (points || []).filter((p) => p[1] !== null && isFinite(p[1]));
  const svg = s('svg', { class: 'spark', width: w, height: hgt, viewBox: '0 0 ' + w + ' ' + hgt, 'aria-hidden': 'true' });
  if (pts.length < 2) return svg;
  const t0 = pts[0][0], t1 = pts[pts.length - 1][0];
  let v0 = Infinity, v1 = -Infinity;
  for (const p of pts) { v0 = Math.min(v0, p[1]); v1 = Math.max(v1, p[1]); }
  if (v0 === v1) { v0 -= 1; v1 += 1; }
  const X = (t) => 2 + (t - t0) / (t1 - t0 || 1) * (w - 6);
  const Y = (v) => 2 + (1 - (v - v0) / (v1 - v0)) * (hgt - 4);
  let d = '';
  pts.forEach((p, i) => { d += (i ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1); });
  svg.appendChild(s('path', { d, fill: 'none', stroke: color, 'stroke-width': 1.5, 'stroke-linejoin': 'round' }));
  const last = pts[pts.length - 1];
  svg.appendChild(s('circle', { cx: X(last[0]), cy: Y(last[1]), r: 2.5, fill: color }));
  return svg;
}
