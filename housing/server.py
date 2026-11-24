"""Web server + JSON API (standard library only)."""

import bisect
import csv
import gzip
import io
import json
import os
import re
import threading
import time
import traceback
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import APP_NAME, __version__, auth, pipeline, scheduler, scores
from .config import DATA_DIR, WEB_DIR, load_config, save_config
from .db import get_meta, thread_conn
from .engine import Engine, last_transform, transform
from .geo.states import ABBR_TO_NAME
from .metrics import BY_ID, METRICS, TRANSFORMS, public_catalog
from .sources import SOURCE_ORDER, all_info
from .util import log, norm_name, parse_period, period_str, smart_round

LEVELS = ("us", "state", "metro", "county", "zip")
GEO_DIR = os.path.join(DATA_DIR, "geo")
CTYPES = {".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
          ".mjs": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
          ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8", ".webmanifest": "application/manifest+json",
          ".woff2": "font/woff2", ".md": "text/plain; charset=utf-8"}


class ApiError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


# ----------------------------------------------------------------------------
# caches (invalidated whenever a pipeline run finishes)
# ----------------------------------------------------------------------------

class Cache:
    def __init__(self):
        self.lock = threading.Lock()
        self.gen = None
        self.clear()

    def clear(self):
        self.snaps = {}
        self.sorted = {}
        self.geos = {}
        self.avail = None
        self.search = None
        self.hist = {}

    def check(self, con):
        gen = (get_meta(con, "last_derive"), get_meta(con, "last_update"))
        with self.lock:
            if gen != self.gen:
                self.clear()
                self.gen = gen

    def geo_level(self, con, level):
        g = self.geos.get(level)
        if g is None:
            g = {}
            for r in con.execute("SELECT geo_id,name,full_name,state,metro_id,county_id,city,lsad,population,"
                                 "lat,lon,minx,miny,maxx,maxy,has_shape FROM geos WHERE level=?", (level,)):
                g[r[0]] = {"id": r[0], "name": display_name(level, r), "full_name": r[2], "state": r[3],
                           "metro": r[4], "county": r[5], "city": r[6], "lsad": r[7], "pop": r[8],
                           "lat": r[9], "lon": r[10],
                           "bbox": [r[11], r[12], r[13], r[14]] if r[11] is not None else None, "shape": r[15]}
            self.geos[level] = g
        return g

    def snapshot(self, con, metric, tf, level):
        key = (metric, tf, level)
        if key not in self.snaps:
            row = con.execute("SELECT period, data FROM snap WHERE metric=? AND transform=? AND level=?",
                              key).fetchone()
            self.snaps[key] = (row[0], json.loads(row[1])) if row else (None, {})
            if len(self.snaps) > 400:
                self.snaps.pop(next(iter(self.snaps)))
        return self.snaps[key]

    def sorted_vals(self, con, metric, tf, level):
        key = (metric, tf, level)
        if key not in self.sorted:
            _, d = self.snapshot(con, metric, tf, level)
            self.sorted[key] = sorted(v for v in d.values() if v is not None)
        return self.sorted[key]

    def available(self, con, cfg):
        if self.avail is None:
            self.avail = Engine(con, cfg).available()
        return self.avail


CACHE = Cache()


def display_name(level, r):
    gid, name, full, st, city = r[0], r[1], r[2], r[3], r[6]
    if level == "zip":
        if city:
            return "%s - %s, %s" % (gid, city, st or "")
        return "ZIP %s%s" % (gid, (", " + st) if st else "")
    if level == "state":
        return ABBR_TO_NAME.get(gid, name or gid)
    if level == "us":
        return "United States"
    return name or gid


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def q1(q, key, default=None):
    v = q.get(key)
    return v[0] if v else default


def need_level(level):
    if level not in LEVELS:
        raise ApiError("unknown level")
    return level


def need_metric(mid):
    if mid not in BY_ID:
        raise ApiError("unknown metric %s" % mid)
    return BY_ID[mid]


def need_tf(m, tf):
    tf = tf or "level"
    if tf not in m["transforms"]:
        raise ApiError("transform %s not available for %s" % (tf, m["id"]))
    return tf


def series_points(s):
    return [[period_str(s.freq, p), smart_round(v)] for p, v in s.points()]


def mask(key):
    if not key:
        return ""
    return key[:3] + "..." + key[-2:] if len(key) > 6 else "***"


# ----------------------------------------------------------------------------
# API implementations
# ----------------------------------------------------------------------------

def api_meta(h, q):
    con = thread_conn()
    cfg = load_config()
    avail = CACHE.available(con, cfg)
    counts = {lv: n for lv, n in con.execute("SELECT level, COUNT(*) FROM geos GROUP BY level")}
    shapes = {lv: os.path.exists(os.path.join(GEO_DIR, lv + ".json")) for lv in ("state", "county", "metro")}
    shapes["zip"] = os.path.exists(os.path.join(GEO_DIR, "zip", "index.json"))
    latest = {}
    for metric in ("zhvi", "inventory", "rf_median_sale_price", "rent", "unemployment"):
        p, _ = CACHE.snapshot(con, metric, "level", "us" if metric != "unemployment" else "us")
        latest[metric] = p
    user = h.user()
    phone_on = RUNNING["host"] in ("0.0.0.0", "::")
    return {
        "app": APP_NAME, "version": __version__, "catalog": public_catalog(), "available": avail,
        "geo_counts": counts, "shapes": shapes, "latest": latest,
        "phone": {"enabled": phone_on, "urls": phone_urls(RUNNING["port"]) if phone_on else [],
                  "saved_host": (load_config().get("server") or {}).get("host", "127.0.0.1")},
        "last_update": get_meta(con, "last_update"), "last_derive": get_meta(con, "last_derive"),
        "has_data": bool(con.execute("SELECT 1 FROM snap LIMIT 1").fetchone()),
        "update": pipeline.STATE.snapshot(), "user": user, "can_admin": h.is_admin(),
        "users_exist": auth.user_count() > 0, "schedule": scheduler.next_run_text(cfg),
        "affordability": cfg.get("affordability"), "permits_label": get_meta(con, "permits_ttm_label"),
    }


def api_map(h, q):
    con = thread_conn()
    m = need_metric(q1(q, "metric", "zhvi"))
    tf = need_tf(m, q1(q, "tf"))
    level = need_level(q1(q, "level", "county"))
    date = q1(q, "date")
    if not date:
        period, data = CACHE.snapshot(con, m["id"], tf, level)
        return {"metric": m["id"], "tf": tf, "level": level, "period": period, "values": data}
    key = (m["id"], tf, level, date)
    if key in CACHE.hist:
        return CACHE.hist[key]
    eng = Engine(con, load_config())
    win = None
    if m["kind"] == "virtual":
        pm = parse_period("M", date)
        win = pm - 140 if pm is not None else None
    series = eng.level_series(m["id"], level, window_start=win)
    out = {}
    freq = None
    for gid, s in series.items():
        freq = s.freq
        p = parse_period(s.freq, date)
        if p is None:
            continue
        _, v = eng.value_at(s, tf, m["change"], p)
        if v == v:
            out[gid] = smart_round(v)
    res = {"metric": m["id"], "tf": tf, "level": level, "period": period_str(freq, parse_period(freq, date))
           if freq else date, "values": out}
    if len(CACHE.hist) > 60:
        CACHE.hist.pop(next(iter(CACHE.hist)))
    CACHE.hist[key] = res
    return res


def api_dates(h, q):
    con = thread_conn()
    m = need_metric(q1(q, "metric", "zhvi"))
    level = need_level(q1(q, "level", "county"))
    deps = [m["id"]] if m["kind"] != "virtual" else [d for d in m["deps"] if d != "property_tax_rate"][:1]
    row = con.execute("SELECT MIN(start), freq FROM series WHERE metric=? AND level=?", (deps[0], level)).fetchone()
    period, _ = CACHE.snapshot(con, m["id"], "level", level)
    if not row or row[0] is None or not period:
        return {"freq": None, "start": None, "end": None}
    return {"freq": row[1], "start": period_str(row[1], row[0]), "end": period}


def api_series(h, q):
    con = thread_conn()
    level = need_level(q1(q, "level"))
    gid = q1(q, "id")
    tf = q1(q, "tf", "level")
    eng = Engine(con, load_config())
    out = {}
    for mid in (q1(q, "metrics", "zhvi") or "").split(","):
        if mid not in BY_ID:
            continue
        m = BY_ID[mid]
        s = eng.series(mid, level, gid)
        if s is None:
            continue
        t = transform(s, tf, m["change"]) if tf != "level" and tf in m["transforms"] else s
        if t is None:
            continue
        out[mid] = {"freq": t.freq, "points": series_points(t)}
    return {"level": level, "id": gid, "tf": tf, "series": out}


def market_label(metrics):
    mos = (metrics.get("rf_months_supply") or {}).get("v")
    if mos is not None:
        if mos < 4:
            return {"label": "Seller's market", "basis": "%.1f months of supply (Redfin)" % mos, "tone": "hot"}
        if mos > 6:
            return {"label": "Buyer's market", "basis": "%.1f months of supply (Redfin)" % mos, "tone": "cold"}
        return {"label": "Balanced market", "basis": "%.1f months of supply (Redfin)" % mos, "tone": "neutral"}
    heat = (metrics.get("z_heat_index") or metrics.get("hotness_score") or {}).get("v")
    if heat is not None:
        if heat >= 70:
            return {"label": "Seller's market", "basis": "market heat %d" % heat, "tone": "hot"}
        if heat <= 30:
            return {"label": "Buyer's market", "basis": "market heat %d" % heat, "tone": "cold"}
        return {"label": "Balanced market", "basis": "market heat %d" % heat, "tone": "neutral"}
    return None


def api_region(h, q):
    con = thread_conn()
    cfg = load_config()
    level = need_level(q1(q, "level"))
    gid = q1(q, "id")
    geos = CACHE.geo_level(con, level)
    geo = geos.get(gid)
    if geo is None:
        raise ApiError("region not found", 404)
    eng = Engine(con, cfg)
    avail = CACHE.available(con, cfg)
    metrics = {}
    for m in METRICS:
        if level not in avail.get(m["id"], []):
            continue
        s = eng.series(m["id"], level, gid)
        if s is None:
            continue
        p, v = s.last()
        if p is None:
            continue
        entry = {"p": period_str(s.freq, p), "v": smart_round(v), "t": {}}
        for tf in m["transforms"]:
            if tf == "level":
                continue
            tp, tv = last_transform(s, tf, m["change"])
            if tp == p and tv == tv:
                entry["t"][tf] = smart_round(tv)
        vals = CACHE.sorted_vals(con, m["id"], "level", level)
        if vals and len(vals) > 1:
            below = bisect.bisect_left(vals, v)
            entry["rank"] = len(vals) - bisect.bisect_right(vals, v) + 1
            entry["of"] = len(vals)
            entry["pct"] = round(below / float(len(vals) - 1), 3) if len(vals) > 1 else None
        metrics[m["id"]] = entry
    parents = []
    if level != "us":
        parents.append({"level": "us", "id": "US", "name": "United States"})
    if geo.get("state") and level in ("metro", "county", "zip"):
        parents.append({"level": "state", "id": geo["state"], "name": ABBR_TO_NAME.get(geo["state"], geo["state"])})
    if geo.get("metro") and level in ("county", "zip"):
        mg = CACHE.geo_level(con, "metro").get(geo["metro"])
        if mg:
            parents.append({"level": "metro", "id": geo["metro"], "name": mg["name"]})
    if geo.get("county") and level == "zip":
        cg = CACHE.geo_level(con, "county").get(geo["county"])
        if cg:
            parents.append({"level": "county", "id": geo["county"], "name": cg["name"]})
    children = {}
    if level == "us":
        children = {"state": len(CACHE.geo_level(con, "state")), "metro": len(CACHE.geo_level(con, "metro"))}
    elif level == "state":
        children = {"metro": sum(1 for g in CACHE.geo_level(con, "metro").values() if g["state"] == gid),
                    "county": sum(1 for g in CACHE.geo_level(con, "county").values() if g["state"] == gid)}
    elif level == "metro":
        children = {"county": sum(1 for g in CACHE.geo_level(con, "county").values() if g["metro"] == gid),
                    "zip": sum(1 for g in CACHE.geo_level(con, "zip").values() if g["metro"] == gid)}
    elif level == "county":
        children = {"zip": sum(1 for g in CACHE.geo_level(con, "zip").values() if g["county"] == gid)}
    return {"level": level, "id": gid, "name": geo["name"], "full_name": geo.get("full_name"),
            "state": geo.get("state"), "pop": geo.get("pop"), "lat": geo.get("lat"), "lon": geo.get("lon"),
            "bbox": geo.get("bbox"), "lsad": geo.get("lsad"), "city": geo.get("city"), "parents": parents,
            "children": children, "metrics": metrics, "market": market_label(metrics),
            "watched": h.is_watched(level, gid)}


def _rank_rows(con, q, limit_default=100):
    level = need_level(q1(q, "level", "metro"))
    cols = []
    for c in (q1(q, "cols") or "zhvi:level").split(","):
        if not c:
            continue
        mid, _, tf = c.partition(":")
        if mid not in BY_ID:
            continue
        tf = tf or "level"
        if tf not in BY_ID[mid]["transforms"]:
            continue
        cols.append((mid, tf))
    cols = cols[:16]
    if not cols:
        raise ApiError("no valid columns")
    snaps = [CACHE.snapshot(con, mid, tf, level) for mid, tf in cols]
    geos = CACHE.geo_level(con, level)
    state = q1(q, "state")
    metro = q1(q, "metro")
    county = q1(q, "county")
    lsad = q1(q, "lsad")
    try:
        min_pop = float(q1(q, "min_pop") or 0)
    except ValueError:
        min_pop = 0
    text = norm_name(q1(q, "q") or "")
    ids = set(geos)
    for _, d in snaps:
        ids |= set(d)
    rows = []
    for gid in ids:
        g = geos.get(gid) or {"name": gid, "state": None, "pop": None, "metro": None, "county": None, "lsad": None}
        if state and g.get("state") != state:
            continue
        if metro and g.get("metro") != metro:
            continue
        if county and g.get("county") != county:
            continue
        if lsad and g.get("lsad") != lsad:
            continue
        if min_pop and (g.get("pop") or 0) < min_pop:
            continue
        if text and text not in norm_name(g.get("name")):
            continue
        vals = [d.get(gid) for _, d in snaps]
        if all(v is None for v in vals):
            continue
        rows.append({"id": gid, "name": g.get("name") or gid, "state": g.get("state"), "pop": g.get("pop"),
                     "v": vals})
    sort = q1(q, "sort")
    desc = q1(q, "desc", "1") != "0"
    si = 0
    if sort:
        mid, _, tf = sort.partition(":")
        for i, c in enumerate(cols):
            if c == (mid, tf or "level"):
                si = i
    if sort == "name":
        rows.sort(key=lambda r: r["name"], reverse=desc)
    elif sort == "pop":
        rows.sort(key=lambda r: (r["pop"] is None, -(r["pop"] or 0) if desc else (r["pop"] or 0)))
    else:
        rows.sort(key=lambda r: (r["v"][si] is None, -(r["v"][si] or 0) if desc else (r["v"][si] or 0)))
    return level, cols, snaps, rows


def api_rankings(h, q):
    con = thread_conn()
    level, cols, snaps, rows = _rank_rows(con, q)
    try:
        limit = max(1, min(1000, int(q1(q, "limit") or 100)))
        offset = max(0, int(q1(q, "offset") or 0))
    except ValueError:
        limit, offset = 100, 0
    return {"level": level, "cols": ["%s:%s" % c for c in cols], "periods": [s[0] for s in snaps],
            "total": len(rows), "offset": offset, "rows": rows[offset:offset + limit]}


def api_export(h, q):
    con = thread_conn()
    level, cols, snaps, rows = _rank_rows(con, q)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "name", "state", "population"] + [
        "%s (%s) [%s]" % (BY_ID[m]["name"], TRANSFORMS.get(tf, tf), p) for (m, tf), (p, _) in zip(cols, snaps)])
    for r in rows:
        w.writerow([r["id"], r["name"], r["state"] or "", r["pop"] or ""] + ["" if v is None else v for v in r["v"]])
    return buf.getvalue()


def build_search_index(con):
    """[(normalized name, level, id, display name, population)] for states, metros, counties, ZIPs and cities."""
    idx = []
    for level in ("state", "metro", "county", "zip"):
        for gid, g in CACHE.geo_level(con, level).items():
            names = [g["name"]]
            if level == "metro" and g.get("full_name"):
                names.append(g["full_name"])
            if level == "state":
                names.append(gid)
            for n in names:
                idx.append((norm_name(n), level, gid, g["name"], g.get("pop") or 0))
    # cities (from ZIP data) -> their county
    cities = {}
    for gid, g in CACHE.geo_level(con, "zip").items():
        if g.get("city") and g.get("state"):
            k = (g["city"], g["state"])
            c = cities.setdefault(k, {"zips": 0, "pop": 0, "county": {}})
            c["zips"] += 1
            c["pop"] += g.get("pop") or 0
            if g.get("county"):
                c["county"][g["county"]] = c["county"].get(g["county"], 0) + 1
    for (city, st), c in cities.items():
        if c["county"]:
            county = max(c["county"], key=c["county"].get)
            idx.append((norm_name("%s %s" % (city, st)), "city", county, "%s, %s (city - %d ZIPs)" % (
                city, st, c["zips"]), c["pop"]))
    return idx


def api_search(h, q):
    con = thread_conn()
    text = (q1(q, "q") or "").strip()
    if len(text) < 2 and not text.isdigit():
        return {"results": []}
    if CACHE.search is None:
        CACHE.search = build_search_index(con)
    t = norm_name(text)
    res = []
    for n, level, gid, disp, pop in CACHE.search:
        if level == "zip" and t.isdigit():
            score = 3 if gid.startswith(t) else 0
        elif n == t:
            score = 4
        elif n.startswith(t):
            score = 3
        elif (" " + t) in (" " + n):
            score = 2
        elif all(tok in n for tok in t.split()):
            score = 1
        else:
            score = 0
        if score:
            lv_bonus = {"state": 0.4, "metro": 0.3, "city": 0.25, "county": 0.2, "zip": 0}[level]
            res.append((score + lv_bonus, pop, level, gid, disp))
    res.sort(key=lambda r: (-r[0], -r[1]))
    seen = set()
    out = []
    for score, pop, level, gid, disp in res:
        key = (level, gid, disp)
        if key in seen:
            continue
        seen.add(key)
        out.append({"level": "county" if level == "city" else level, "id": gid, "name": disp,
                    "kind": level})
        if len(out) >= 15:
            break
    return {"results": out}


def api_national(h, q):
    con = thread_conn()
    out = []
    for sid, name, units, freq, src, cat, dates, vals in con.execute(
            "SELECT sid,name,units,freq,src,category,dates,vals FROM macro WHERE category != '_internal' "
            "ORDER BY category, name"):
        out.append({"id": sid, "name": name, "units": units, "freq": freq, "src": src, "category": cat,
                    "dates": json.loads(dates), "values": json.loads(vals)})
    return {"series": out}


def api_sources(h, q):
    con = thread_conn()
    cfg = load_config()
    status = {r[0]: {"status": r[1], "last_attempt": r[2], "last_success": r[3], "message": r[4],
                     "details": json.loads(r[5] or "{}")} for r in con.execute("SELECT * FROM source_status")}
    files = {}
    for url, path, st, http, size, fetched, modified, etag, src, key in con.execute(
            "SELECT url,path,status,http,bytes,fetched,modified,etag,source,key FROM files ORDER BY fetched DESC"):
        files.setdefault(src, []).append({"url": url, "status": st, "http": http, "bytes": size, "fetched": fetched,
                                          "modified": modified, "key": key})
    out = []
    for info in all_info(cfg):
        sid = info["id"]
        st = status.get(sid, {})
        if "details" in st and "trace" in st["details"]:
            st = dict(st)
            st["details"] = {k: v for k, v in st["details"].items() if k != "trace"}
        out.append(dict(info, status=st, downloads=files.get(sid, [])[:80],
                        enabled=(cfg.get("sources", {}).get(sid, {}) or {}).get("enabled", True)))
    extra = [
        {"name": "Orchard (orchard.com)", "url": "https://orchard.com/blog",
         "note": "Publishes market analyses (e.g. new-construction permit rankings) but no downloadable dataset. "
                 "The permit data behind those posts comes from the Census Building Permits Survey, included here."},
        {"name": "Apartment List Rent Estimates", "url": "https://www.apartmentlist.com/research/category/data-rent-estimates",
         "note": "Free monthly CSV of rents & vacancy by metro/city. Link changes every month, so it isn't automated "
                 "yet - Zillow ZORI covers rents here."},
        {"name": "HUD Fair Market Rents", "url": "https://www.huduser.gov/portal/datasets/fmr.html",
         "note": "Free with a HUD API token; useful for Section 8 rent benchmarks. Not automated."},
        {"name": "NAR / ICE / CoreLogic / ATTOM / Parcl Labs / Altos", "url": "https://www.parcllabs.com/",
         "note": "Paid or license-restricted data. Not included."},
    ]
    return {"sources": out, "other": extra, "update": pipeline.STATE.snapshot(),
            "schedule": cfg.get("schedule"), "schedule_text": scheduler.next_run_text(cfg),
            "last_update": get_meta(con, "last_update")}


SAFE_SETTINGS = ("contact_email", "schedule", "affordability", "sources", "url_overrides", "server")
API_KEYS = ("census_api_key", "bea_api_key", "bls_api_key")


def api_settings_get(h, q):
    cfg = load_config()
    out = {k: cfg.get(k) for k in SAFE_SETTINGS}
    out["census_api_key"] = mask(cfg.get("census_api_key"))
    out["bea_api_key"] = mask(cfg.get("bea_api_key"))
    out["bls_api_key"] = mask(cfg.get("bls_api_key"))
    out["data_dir"] = DATA_DIR
    return out


def api_settings_post(h, body):
    if not h.is_admin():
        raise ApiError("Only the admin (or this computer) can change settings.", 403)
    cfg = load_config()
    old_aff = json.dumps(cfg.get("affordability"), sort_keys=True)
    for k in SAFE_SETTINGS + API_KEYS:
        if k not in body:
            continue
        v = body[k]
        if k in API_KEYS and isinstance(v, str) and v and v == mask(cfg.get(k)):
            continue  # masked value sent back unchanged
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            merged = dict(cfg[k])
            for kk, vv in v.items():
                if isinstance(vv, dict) and isinstance(merged.get(kk), dict):
                    merged[kk] = dict(merged[kk], **vv)
                else:
                    merged[kk] = vv
            cfg[k] = merged
        else:
            cfg[k] = v
    save_config(cfg)
    rebuild = json.dumps(cfg.get("affordability"), sort_keys=True) != old_aff
    if rebuild and not pipeline.STATE.running:
        def work():
            try:
                pipeline.STATE.report("Recomputing affordability layers with new assumptions...")
                from . import snapshot
                from .db import connect, set_meta
                con = connect()
                snapshot.build(con, load_config(), None)
                scores.long_term_and_investor(con, load_config(), None)
                set_meta(con, "last_derive", time.strftime("%Y-%m-%d %H:%M:%S"))
                con.close()
                pipeline.STATE.report("Affordability layers updated.")
            except Exception as e:
                log.warning("rebuild failed: %s", e)
        threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "rebuilding": rebuild}


def api_methodology(h, q):
    con = thread_conn()
    cfg = load_config()
    return {"calibration": get_meta(con, "forecast_calibration"), "affordability": cfg.get("affordability"),
            "forecast_factors": scores.FORECAST_FACTORS, "longterm_factors": scores.LONGTERM,
            "investor_factors": scores.INVESTOR, "permits_label": get_meta(con, "permits_ttm_label")}


# ----------------------------------------------------------------------------
# HTTP handler
# ----------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "HousingAtlas/" + __version__
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if os.environ.get("HOUSING_ATLAS_ACCESS_LOG"):
            log.info("%s %s", self.address_string(), fmt % args)

    # --- auth helpers
    def token(self):
        c = cookies.SimpleCookie()
        try:
            c.load(self.headers.get("Cookie") or "")
        except cookies.CookieError:
            return None
        m = c.get("ha_session")
        return m.value if m else None

    def user(self):
        if not hasattr(self, "_user"):
            self._user = auth.user_for(self.token())
        return self._user

    def is_local(self):
        ip = self.client_address[0]
        return ip in ("127.0.0.1", "::1", "localhost") or ip.startswith("127.") or ip == "::ffff:127.0.0.1"

    def is_admin(self):
        u = self.user()
        return self.is_local() or bool(u and u.get("is_admin"))

    def is_watched(self, level, gid):
        u = self.user()
        if not u:
            return False
        return any(w["level"] == level and w["id"] == gid for w in auth.watchlist(u["id"]))

    # --- responses
    def send_body(self, body, ctype, status=200, extra_headers=None, cache=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        gz = "gzip" in (self.headers.get("Accept-Encoding") or "") and len(body) > 1400 and (
            ctype.startswith(("application/json", "text/", "application/javascript", "image/svg")))
        if gz:
            body = gzip.compress(body, 5)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Cache-Control", cache or "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, obj, status=200, extra_headers=None):
        self.send_body(json.dumps(obj, separators=(",", ":"), allow_nan=False), "application/json; charset=utf-8",
                       status, extra_headers)

    def send_file(self, path, cache="no-cache"):
        ext = os.path.splitext(path)[1].lower()
        ctype = CTYPES.get(ext, "application/octet-stream")
        st = os.stat(path)
        etag = '"%x-%x"' % (int(st.st_mtime), st.st_size)
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        pre_gz = path + ".gz"
        if ext == ".json" and os.path.exists(pre_gz) and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            with open(pre_gz, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_body(body, ctype, 200, {"ETag": etag}, cache=cache)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            raise ApiError("request too large", 413)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            raise ApiError("invalid JSON")

    # --- routing
    def do_HEAD(self):
        self.do_GET()

    def _reset(self):
        # keep-alive connections reuse this handler instance: never carry a user across requests
        self.__dict__.pop("_user", None)

    def do_GET(self):
        self._reset()
        u = urllib.parse.urlparse(self.path)
        path, q = u.path, urllib.parse.parse_qs(u.query)
        try:
            if path.startswith("/api/"):
                con = thread_conn()
                CACHE.check(con)
                route = GET_ROUTES.get(path)
                if route is None:
                    raise ApiError("not found", 404)
                if path == "/api/export.csv":
                    text = api_export(self, q)
                    self.send_body(text, "text/csv; charset=utf-8", 200,
                                   {"Content-Disposition": 'attachment; filename="housing-atlas-%s.csv"' %
                                                           (q1(q, "level", "data"))})
                    return
                self.send_json(route(self, q))
                return
            if path.startswith("/geo/"):
                rel = path[len("/geo/"):]
                if not re.match(r"^[a-z]+(/[0-9a-z]+)?\.json$", rel):
                    raise ApiError("not found", 404)
                full = os.path.join(GEO_DIR, *rel.split("/"))
                if not os.path.exists(full):
                    raise ApiError("map shapes not downloaded yet", 404)
                self.send_file(full, cache="max-age=3600")
                return
            self.serve_static(path)
        except ApiError as e:
            self.send_json({"error": str(e)}, e.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log.error("GET %s failed: %s\n%s", self.path, e, traceback.format_exc())
            try:
                self.send_json({"error": "server error: %s" % e}, 500)
            except Exception:
                pass

    def serve_static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        rel = urllib.parse.unquote(path).lstrip("/")
        full = os.path.realpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(os.path.realpath(WEB_DIR)) or not os.path.isfile(full):
            # client-side routes fall back to the app shell
            full = os.path.join(WEB_DIR, "index.html")
        self.send_file(full)

    def _same_origin(self):
        """Block cross-site requests (another website trying to drive this local app):
        POSTs must be JSON and, when the browser sends an Origin, it must be this server."""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return False
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host") or ""
            if urllib.parse.urlparse(origin).netloc != host:
                return False
        return True

    def do_POST(self):
        self._reset()
        u = urllib.parse.urlparse(self.path)
        path = u.path
        try:
            if not self._same_origin():
                raise ApiError("cross-site request blocked", 403)
            con = thread_conn()
            CACHE.check(con)
            body = self.read_json()
            if path == "/api/auth/register":
                tok = auth.register(body.get("username"), body.get("password"))
                self.send_json({"ok": True, "user": auth.user_for(tok)}, extra_headers=self._cookie(tok))
                return
            if path == "/api/auth/login":
                tok = auth.login(body.get("username"), body.get("password"))
                self.send_json({"ok": True, "user": auth.user_for(tok)}, extra_headers=self._cookie(tok))
                return
            if path == "/api/auth/logout":
                auth.logout(self.token())
                self.send_json({"ok": True}, extra_headers={
                    "Set-Cookie": "ha_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})
                return
            if path == "/api/auth/password":
                usr = self.require_user()
                auth.change_password(usr["id"], body.get("old"), body.get("new"))
                self.send_json({"ok": True})
                return
            if path == "/api/user/settings":
                usr = self.require_user()
                auth.save_user_settings(usr["id"], body.get("settings") or {})
                self.send_json({"ok": True})
                return
            if path == "/api/watchlist":
                usr = self.require_user()
                lv = need_level(body.get("level"))
                auth.watch_add(usr["id"], lv, str(body.get("id")), body.get("note"))
                self.send_json({"ok": True, "watchlist": auth.watchlist(usr["id"])})
                return
            if path == "/api/watchlist/remove":
                usr = self.require_user()
                auth.watch_remove(usr["id"], body.get("level"), str(body.get("id")))
                self.send_json({"ok": True, "watchlist": auth.watchlist(usr["id"])})
                return
            if path == "/api/views":
                usr = self.require_user()
                auth.view_add(usr["id"], body.get("name"), body.get("state") or {})
                self.send_json({"ok": True, "views": auth.views(usr["id"])})
                return
            if path == "/api/views/remove":
                usr = self.require_user()
                auth.view_remove(usr["id"], int(body.get("id") or 0))
                self.send_json({"ok": True, "views": auth.views(usr["id"])})
                return
            if path == "/api/update":
                if not self.is_admin():
                    raise ApiError("Only the admin (or this computer) can start updates.", 403)
                srcs = [s for s in (body.get("sources") or []) if s in SOURCE_ORDER] or None
                started = pipeline.start_background_update(srcs, force=bool(body.get("force")))
                self.send_json({"ok": started, "message": "started" if started else "already running"})
                return
            if path == "/api/update/cancel":
                if not self.is_admin():
                    raise ApiError("not allowed", 403)
                pipeline.STATE.cancel.set()
                self.send_json({"ok": True})
                return
            if path == "/api/settings":
                self.send_json(api_settings_post(self, body))
                return
            raise ApiError("not found", 404)
        except auth.AuthError as e:
            self.send_json({"error": str(e)}, 400)
        except ApiError as e:
            self.send_json({"error": str(e)}, e.status)
        except Exception as e:
            log.error("POST %s failed: %s\n%s", self.path, e, traceback.format_exc())
            self.send_json({"error": "server error: %s" % e}, 500)

    def require_user(self):
        u = self.user()
        if not u:
            raise ApiError("Please log in (accounts are free).", 401)
        return u

    def _cookie(self, tok):
        return {"Set-Cookie": "ha_session=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Lax" % (
            tok, auth.SESSION_DAYS * 86400)}


def api_me(h, q):
    u = h.user()
    out = {"user": u, "can_admin": h.is_admin(), "users_exist": auth.user_count() > 0}
    if u:
        out["watchlist"] = auth.watchlist(u["id"])
        out["views"] = auth.views(u["id"])
    return out


def api_watchlist(h, q):
    u = h.require_user()
    con = thread_conn()
    items = auth.watchlist(u["id"])
    for it in items:
        g = CACHE.geo_level(con, it["level"]).get(it["id"]) if it["level"] in LEVELS else None
        it["name"] = g["name"] if g else it["id"]
    return {"watchlist": items}


def api_update_status(h, q):
    return pipeline.STATE.snapshot()


def api_geonames(h, q):
    con = thread_conn()
    level = need_level(q1(q, "level", "county"))
    geos = CACHE.geo_level(con, level)
    return {"level": level, "names": {g: v["name"] for g, v in geos.items()},
            "pop": {g: v["pop"] for g, v in geos.items() if v.get("pop")},
            "bbox": {g: v["bbox"] for g, v in geos.items() if v.get("bbox")} if level != "zip" else {}}


GET_ROUTES = {
    "/api/meta": api_meta,
    "/api/map": api_map,
    "/api/dates": api_dates,
    "/api/series": api_series,
    "/api/region": api_region,
    "/api/rankings": api_rankings,
    "/api/export.csv": api_export,
    "/api/search": api_search,
    "/api/national": api_national,
    "/api/sources": api_sources,
    "/api/settings": api_settings_get,
    "/api/methodology": api_methodology,
    "/api/auth/me": api_me,
    "/api/watchlist": api_watchlist,
    "/api/update/status": api_update_status,
    "/api/geonames": api_geonames,
}


RUNNING = {"host": "127.0.0.1", "port": 8765}


def phone_urls(port):
    """Addresses a phone can use to reach this computer: its home-network (Wi-Fi/LAN) address, plus its
    Tailscale address when Tailscale is installed (reachable from anywhere)."""
    import socket

    def kind(ip):
        try:
            a, b = (int(x) for x in ip.split(".")[:2])
        except ValueError:
            return None
        if a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168):
            return "wifi"
        if a == 100 and 64 <= b <= 127:
            return "tailscale"
        return None
    primary = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent; picks the interface with the default route
        primary = s.getsockname()[0]
        s.close()
    except OSError:
        pass
    others = []
    try:
        others = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    out = []
    lan = primary if kind(primary or "") == "wifi" else next((ip for ip in others if kind(ip) == "wifi"), None)
    if lan:
        out.append({"url": "http://%s:%d" % (lan, port), "kind": "wifi"})
    for ip in [primary] + others:
        if ip and kind(ip) == "tailscale" and not any(ip in u["url"] for u in out):
            out.append({"url": "http://%s:%d" % (ip, port), "kind": "tailscale"})
    return out


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(host="127.0.0.1", port=8765, open_browser=False, with_scheduler=True):
    httpd = Server((host, port), Handler)
    RUNNING.update(host=host, port=port)
    url = "http://%s:%d/" % ("localhost" if host in ("0.0.0.0", "127.0.0.1", "::") else host, port)
    log.info("%s %s running at %s  (Ctrl+C to stop)", APP_NAME, __version__, url)
    if host == "0.0.0.0":
        urls = phone_urls(port)
        for u in urls:
            log.info("On your phone (%s), open:  %s", "with Tailscale" if u["kind"] == "tailscale" else "same Wi-Fi",
                     u["url"])
        if not urls:
            log.info("Phones on your network can connect - open http://<this-computer's-IP>:%d on your phone", port)
    if with_scheduler:
        scheduler.start()
    if open_browser:
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("stopping")
    finally:
        httpd.server_close()
