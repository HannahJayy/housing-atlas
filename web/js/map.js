// Dependency-free slippy map: Web-Mercator canvas renderer for choropleth polygons
// with optional raster basemap tiles (CARTO / OpenStreetMap) underneath and labels on top.

const Q = 4194304; // 2^22 integer grid units per world (matches the server's encoding)
const TILE = 256;
const MAX_LAT = 85.05112878;

export function merc(lon, lat) {
  lat = Math.max(-MAX_LAT, Math.min(MAX_LAT, lat));
  const s = Math.sin(lat * Math.PI / 180);
  return [(lon + 180) / 360, 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)];
}

export function unmerc(x, y) {
  const n = Math.PI - 2 * Math.PI * y;
  return [x * 360 - 180, 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)))];
}

/** Decode the server's compact delta-encoded polygons into Path2D objects. */
export function decodeFeatures(json) {
  const out = [];
  for (const [id, bbox, rings] of json.f || []) {
    const path = new Path2D();
    for (const r of rings) {
      let x = r[0], y = r[1];
      path.moveTo(x, y);
      for (let i = 2; i < r.length; i += 2) {
        x += r[i]; y += r[i + 1];
        path.lineTo(x, y);
      }
      path.closePath();
    }
    out.push({ id, bbox, path });
  }
  return out;
}

const TILE_STYLES = {
  light: ['light_nolabels', 'light_only_labels'],
  dark: ['dark_nolabels', 'dark_only_labels'],
};

export class SlippyMap {
  constructor(el, opts = {}) {
    this.el = el;
    this.canvas = document.createElement('canvas');
    this.canvas.setAttribute('role', 'img');
    this.canvas.setAttribute('aria-label', opts.ariaLabel || 'Map');
    this.canvas.tabIndex = 0;
    el.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');
    this.z = opts.zoom ?? 3.6;
    [this.cx, this.cy] = merc(opts.lon ?? -96.5, opts.lat ?? 38.6);
    this.minZoom = 1.6;
    this.maxZoom = 14;
    this.basemap = opts.basemap || 'light';
    this.theme = { bg: '#f3f2ee', outline: 'rgba(255,255,255,0.75)', hover: '#0b0b0b', select: '#256abf',
      nodata: '#e6e5df', overlay: 'rgba(11,11,11,0.45)' };
    this.fillAlpha = 0.82;
    this.features = [];
    this.colors = new Map();
    this.overlays = [];
    this.hoverId = null;
    this.selectedId = null;
    this.tiles = new Map();
    this.onHover = opts.onHover || null;
    this.onClick = opts.onClick || null;
    this.onMoveEnd = opts.onMoveEnd || null;
    this._pointers = new Map();
    this._raf = null;
    this._anim = null;
    this._moveTimer = null;
    this._resize();
    this._ro = new ResizeObserver(() => { this._resize(); this.requestRender(); });
    this._ro.observe(el);
    this._bind();
    this.requestRender();
  }

  destroy() {
    this._ro.disconnect();
    if (this._raf) cancelAnimationFrame(this._raf);
    this.canvas.remove();
  }

  // ---------------------------------------------------------------- geometry
  get ws() { return TILE * Math.pow(2, this.z); }

  _resize() {
    const r = this.el.getBoundingClientRect();
    this.w = Math.max(1, r.width);
    this.h = Math.max(1, r.height);
    this.dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    this.canvas.width = Math.round(this.w * this.dpr);
    this.canvas.height = Math.round(this.h * this.dpr);
  }

  _xf() {
    const ws = this.ws;
    const s = ws / Q;
    return { ws, s, tx: this.w / 2 - this.cx * ws, ty: this.h / 2 - this.cy * ws };
  }

  screenToLonLat(px, py) {
    const ws = this.ws;
    return unmerc(this.cx + (px - this.w / 2) / ws, this.cy + (py - this.h / 2) / ws);
  }

  /** visible bounds in integer grid units */
  qBounds() {
    const { s, tx, ty } = this._xf();
    return [(-tx) / s, (-ty) / s, (this.w - tx) / s, (this.h - ty) / s];
  }

  getView() {
    const [lon, lat] = unmerc(this.cx, this.cy);
    return { lon: +lon.toFixed(4), lat: +lat.toFixed(4), z: +this.z.toFixed(2) };
  }

  setView(lon, lat, z) {
    [this.cx, this.cy] = merc(lon, lat);
    if (z !== undefined) this.z = Math.max(this.minZoom, Math.min(this.maxZoom, z));
    this._clamp();
    this.requestRender();
    this._moved();
  }

  _clamp() {
    this.cy = Math.max(0, Math.min(1, this.cy));
    this.cx = Math.max(0, Math.min(1, this.cx));
  }

  fitBounds(b, opts = {}) {
    // b = [minLon, minLat, maxLon, maxLat]
    if (!b || b.some((v) => v === null || v === undefined || !isFinite(v))) return;
    const [x0, y1] = merc(b[0], b[1]);
    const [x1, y0] = merc(b[2], b[3]);
    const pad = opts.padding ?? 40;
    const dx = Math.max(1e-9, x1 - x0), dy = Math.max(1e-9, y1 - y0);
    const zx = Math.log2((this.w - pad * 2 - (opts.leftInset || 0)) / (dx * TILE));
    const zy = Math.log2((this.h - pad * 2) / (dy * TILE));
    const z = Math.max(this.minZoom, Math.min(opts.maxZoom ?? 11, Math.min(zx, zy)));
    let cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    if (opts.leftInset) cx -= (opts.leftInset / 2) / (TILE * Math.pow(2, z));
    this.flyTo(cx, cy, z, opts.duration ?? 450);
  }

  flyTo(cx, cy, z, duration = 400) {
    if (!(duration > 0)) {
      this.cx = cx; this.cy = cy; this.z = Math.max(this.minZoom, Math.min(this.maxZoom, z));
      this._clamp(); this.requestRender(); this._moved();
      return;
    }
    const from = { cx: this.cx, cy: this.cy, z: this.z };
    const t0 = performance.now();
    this._anim = (now) => {
      const t = Math.min(1, (now - t0) / duration);
      const e = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      this.cx = from.cx + (cx - from.cx) * e;
      this.cy = from.cy + (cy - from.cy) * e;
      this.z = from.z + (z - from.z) * e;
      if (t >= 1) { this._anim = null; this._moved(); }
      return t < 1;
    };
    this.requestRender();
  }

  zoomAround(px, py, z2, animate = false) {
    z2 = Math.max(this.minZoom, Math.min(this.maxZoom, z2));
    const ws = this.ws;
    const wx = this.cx + (px - this.w / 2) / ws;
    const wy = this.cy + (py - this.h / 2) / ws;
    const ws2 = TILE * Math.pow(2, z2);
    const cx2 = wx - (px - this.w / 2) / ws2;
    const cy2 = wy - (py - this.h / 2) / ws2;
    if (animate) this.flyTo(cx2, cy2, z2, 250);
    else {
      this.z = z2; this.cx = cx2; this.cy = cy2; this._clamp();
      this.requestRender(); this._moved();
    }
  }

  zoomBy(d) { this.zoomAround(this.w / 2, this.h / 2, this.z + d, true); }

  _moved() {
    clearTimeout(this._moveTimer);
    this._moveTimer = setTimeout(() => { if (this.onMoveEnd) this.onMoveEnd(this.getView()); }, 180);
  }

  // ---------------------------------------------------------------- data
  setFeatures(features) { this.features = features || []; this.requestRender(); }
  setColors(map) { this.colors = map; this.requestRender(); }
  setOverlays(list) { this.overlays = list || []; this.requestRender(); }
  setBasemap(b) { this.basemap = b; this.requestRender(); }
  setTheme(t) { Object.assign(this.theme, t); this.requestRender(); }
  setSelected(id) { this.selectedId = id; this.requestRender(); }

  // ---------------------------------------------------------------- render
  requestRender() {
    if (this._raf) return;
    this._raf = requestAnimationFrame((now) => {
      this._raf = null;
      if (this._anim && this._anim(now)) this.requestRender();
      this.render();
    });
  }

  render() {
    const ctx = this.ctx;
    const dpr = this.dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalAlpha = 1;
    ctx.fillStyle = this.theme.bg;
    ctx.fillRect(0, 0, this.w, this.h);
    const styles = TILE_STYLES[this.basemap];
    if (styles) this._drawTiles(styles[0]);

    const { s, tx, ty } = this._xf();
    const qx0 = (-tx) / s, qy0 = (-ty) / s, qx1 = (this.w - tx) / s, qy1 = (this.h - ty) / s;
    ctx.setTransform(dpr * s, 0, 0, dpr * s, dpr * tx, dpr * ty);
    const visible = [];
    for (const f of this.features) {
      const b = f.bbox;
      if (b[2] < qx0 || b[0] > qx1 || b[3] < qy0 || b[1] > qy1) continue;
      visible.push(f);
    }
    // fills grouped by color (fewer state changes)
    const groups = new Map();
    for (const f of visible) {
      const c = this.colors.get(f.id) || this.theme.nodata;
      let g = groups.get(c);
      if (!g) { g = []; groups.set(c, g); }
      g.push(f);
    }
    ctx.globalAlpha = this.fillAlpha;
    for (const [c, fs] of groups) {
      ctx.fillStyle = c;
      for (const f of fs) ctx.fill(f.path, 'evenodd');
    }
    ctx.globalAlpha = 1;
    // outlines (skip features smaller than ~2px)
    ctx.lineJoin = 'round';
    ctx.strokeStyle = this.theme.outline;
    ctx.lineWidth = 0.6 / s;
    const minSize = 2 / s;
    for (const f of visible) {
      const b = f.bbox;
      if (b[2] - b[0] < minSize && b[3] - b[1] < minSize) continue;
      ctx.stroke(f.path);
    }
    for (const ov of this.overlays) {
      ctx.strokeStyle = ov.color || this.theme.overlay;
      ctx.lineWidth = (ov.width || 1.2) / s;
      for (const f of ov.features) {
        const b = f.bbox;
        if (b[2] < qx0 || b[0] > qx1 || b[3] < qy0 || b[1] > qy1) continue;
        ctx.stroke(f.path);
      }
    }
    const byId = (id) => this.features.find((f) => f.id === id);
    if (this.selectedId) {
      const f = byId(this.selectedId);
      if (f) { ctx.strokeStyle = this.theme.select; ctx.lineWidth = 3 / s; ctx.stroke(f.path); }
    }
    if (this.hoverId && this.hoverId !== this.selectedId) {
      const f = byId(this.hoverId);
      if (f) { ctx.strokeStyle = this.theme.hover; ctx.lineWidth = 1.8 / s; ctx.stroke(f.path); }
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (styles) this._drawTiles(styles[1]);
  }

  _tileUrl(style, z, x, y) {
    const sub = 'abcd'[(x + y) % 4];
    const r = this.dpr > 1.2 ? '@2x' : '';
    return 'https://' + sub + '.basemaps.cartocdn.com/' + style + '/' + z + '/' + x + '/' + y + r + '.png';
  }

  _tile(style, z, x, y, create = true) {
    const key = style + '/' + z + '/' + x + '/' + y;
    let t = this.tiles.get(key);
    if (t) {
      this.tiles.delete(key);
      this.tiles.set(key, t); // LRU touch
      return t;
    }
    if (!create) return null;
    t = new Image();
    t.decoding = 'async';
    t.onload = () => { t.ok = true; this.requestRender(); };
    t.onerror = () => { t.failed = true; };
    t.src = this._tileUrl(style, z, x, y);
    this.tiles.set(key, t);
    if (this.tiles.size > 500) this.tiles.delete(this.tiles.keys().next().value);
    return t;
  }

  _drawTiles(style) {
    const ctx = this.ctx;
    const tz = Math.max(0, Math.min(19, Math.round(this.z)));
    const n = Math.pow(2, tz);
    const ws = this.ws;
    const tsize = ws / n;
    const left = this.cx * ws - this.w / 2;
    const top = this.cy * ws - this.h / 2;
    const x0 = Math.floor(left / tsize), x1 = Math.floor((left + this.w) / tsize);
    const y0 = Math.max(0, Math.floor(top / tsize)), y1 = Math.min(n - 1, Math.floor((top + this.h) / tsize));
    for (let y = y0; y <= y1; y++) {
      for (let x = x0; x <= x1; x++) {
        const xx = ((x % n) + n) % n;
        const px = x * tsize - left, py = y * tsize - top;
        const img = this._tile(style, tz, xx, y);
        if (img.ok) { ctx.drawImage(img, px, py, tsize + 0.6, tsize + 0.6); continue; }
        for (let d = 1; d <= 5 && tz - d >= 0; d++) {
          const f = Math.pow(2, d);
          const p = this._tile(style, tz - d, Math.floor(xx / f), Math.floor(y / f), false);
          if (p && p.ok) {
            const sw = p.naturalWidth / f;
            ctx.drawImage(p, (xx % f) * sw, (y % f) * sw, sw, sw, px, py, tsize + 0.6, tsize + 0.6);
            break;
          }
        }
      }
    }
  }

  // ---------------------------------------------------------------- hit testing
  hitTest(px, py) {
    const { s, tx, ty } = this._xf();
    const qx = (px - tx) / s, qy = (py - ty) / s;
    const ctx = this.ctx;
    ctx.save();
    ctx.setTransform(this.dpr * s, 0, 0, this.dpr * s, this.dpr * tx, this.dpr * ty);
    let hit = null;
    for (let i = this.features.length - 1; i >= 0; i--) {
      const f = this.features[i];
      const b = f.bbox;
      if (qx < b[0] || qx > b[2] || qy < b[1] || qy > b[3]) continue;
      if (ctx.isPointInPath(f.path, px * this.dpr, py * this.dpr, 'evenodd')) { hit = f.id; break; }
    }
    ctx.restore();
    return hit;
  }

  // ---------------------------------------------------------------- events
  _bind() {
    const c = this.canvas;
    let down = null;
    let pinch = null;
    let hoverRaf = null;
    const pos = (e) => { const r = c.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };

    c.addEventListener('pointerdown', (e) => {
      c.setPointerCapture(e.pointerId);
      this._pointers.set(e.pointerId, pos(e));
      if (this._pointers.size === 1) {
        const [x, y] = pos(e);
        down = { x, y, cx: this.cx, cy: this.cy, moved: false, t: performance.now() };
      } else if (this._pointers.size === 2) {
        const [a, b] = [...this._pointers.values()];
        pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), z: this.z };
        down = null;
      }
    });
    c.addEventListener('pointermove', (e) => {
      const p = pos(e);
      if (this._pointers.has(e.pointerId)) this._pointers.set(e.pointerId, p);
      if (pinch && this._pointers.size === 2) {
        const [a, b] = [...this._pointers.values()];
        const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (pinch.d > 0) this.zoomAround((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, pinch.z + Math.log2(d / pinch.d));
        return;
      }
      if (down) {
        const dx = p[0] - down.x, dy = p[1] - down.y;
        if (!down.moved && Math.hypot(dx, dy) > 4) { down.moved = true; this.el.classList.add('dragging'); }
        if (down.moved) {
          const ws = this.ws;
          this.cx = down.cx - dx / ws;
          this.cy = down.cy - dy / ws;
          this._clamp();
          this.requestRender();
          this._moved();
        }
        return;
      }
      if (e.pointerType === 'mouse' && this.onHover) {
        if (hoverRaf) return;
        hoverRaf = requestAnimationFrame(() => {
          hoverRaf = null;
          const id = this.hitTest(p[0], p[1]);
          if (id !== this.hoverId) { this.hoverId = id; this.requestRender(); }
          this.onHover(id, p[0], p[1]);
        });
      }
    });
    const end = (e) => {
      const had = this._pointers.has(e.pointerId);
      this._pointers.delete(e.pointerId);
      if (this._pointers.size < 2) pinch = null;
      this.el.classList.remove('dragging');
      if (had && down && !down.moved && e.type === 'pointerup') {
        const [x, y] = pos(e);
        const id = this.hitTest(x, y);
        if (this.onClick) this.onClick(id, x, y);
      }
      if (this._pointers.size === 0) down = null;
    };
    c.addEventListener('pointerup', end);
    c.addEventListener('pointercancel', end);
    c.addEventListener('pointerleave', () => {
      if (this.hoverId) { this.hoverId = null; this.requestRender(); }
      if (this.onHover) this.onHover(null);
    });
    c.addEventListener('wheel', (e) => {
      e.preventDefault();
      const [x, y] = pos(e);
      let d = e.deltaY;
      if (e.deltaMode === 1) d *= 33;
      else if (e.deltaMode === 2) d *= 400;
      const step = Math.max(-1, Math.min(1, -d / 300));
      this.zoomAround(x, y, this.z + step);
    }, { passive: false });
    c.addEventListener('dblclick', (e) => {
      const [x, y] = pos(e);
      this.zoomAround(x, y, this.z + (e.shiftKey ? -1 : 1), true);
    });
    c.addEventListener('keydown', (e) => {
      const ws = this.ws;
      const k = e.key;
      if (k === '+' || k === '=') this.zoomBy(1);
      else if (k === '-' || k === '_') this.zoomBy(-1);
      else if (k === 'ArrowLeft') { this.cx -= 80 / ws; this.requestRender(); this._moved(); }
      else if (k === 'ArrowRight') { this.cx += 80 / ws; this.requestRender(); this._moved(); }
      else if (k === 'ArrowUp') { this.cy -= 80 / ws; this.requestRender(); this._moved(); }
      else if (k === 'ArrowDown') { this.cy += 80 / ws; this.requestRender(); this._moved(); }
      else return;
      e.preventDefault();
    });
  }
}
