"""Export Housing Atlas as a static web app: the regular web files plus every API answer pre-built as JSON,
so it runs on any static web host (GitHub Pages, Netlify, a USB stick served by any web server) with no
Python server. The browser does searching, ranking, CSV export and the 1-year/5-year change math itself.

    python app.py export-static [out_dir] [--bundle] [--preview] [--history state,metro,county]

--bundle   packs the map layers, region reports and history into three files (small datasets only)
--preview  marks the build as a sample-data preview (shows a banner, no basemap tiles, copy instead of download)
"""

import json
import os
import shutil
import time

from . import __version__
from . import server as srv
from .config import WEB_DIR, load_config
from .db import get_meta, thread_conn
from .engine import Engine, last_transform
from .geo.states import ABBR_TO_NAME
from .metrics import METRICS
from .util import log, period_str, smart_round

LEVELS = ("us", "state", "metro", "county", "zip")
DEFAULT_HISTORY = ("us", "state", "metro", "county")


class _NoUser:
    """Stands in for an HTTP request when calling the server's API functions."""

    def user(self):
        return None

    def is_admin(self):
        return False

    def is_watched(self, level, gid):
        return False


def _fine(x):
    """One digit more than smart_round, so changes computed in the browser match the server's."""
    a = abs(x)
    if a >= 100000:
        return int(round(x))
    if a >= 1000:
        return round(x, 1)
    if a >= 100:
        return round(x, 2)
    if a >= 1:
        return round(x, 3)
    if a >= 0.01:
        return round(x, 5)
    return round(x, 7)


def _vals(seq):
    """float sequence -> JSON-ready list (NaN -> None), trimmed of empty ends. Returns (offset, list)."""
    v = list(seq)
    k0 = 0
    while k0 < len(v) and v[k0] != v[k0]:
        k0 += 1
    k1 = len(v) - 1
    while k1 >= k0 and v[k1] != v[k1]:
        k1 -= 1
    return k0, [_fine(float(x)) if x == x else None for x in v[k0:k1 + 1]]


class _Writer:
    def __init__(self, out, bundle, compress=False):
        self.out = out
        self.bundle = bundle
        self.compress = compress
        self.parts = {}
        self.files = 0
        self.bytes = 0

    def write(self, rel, obj):
        """Write api/... JSON; with compress, as rel + '.gz' (the browser unpacks it), about 5x smaller."""
        path = os.path.join(self.out, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = json.dumps(obj, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if self.compress:
            import gzip
            data = gzip.compress(data, 6, mtime=0)
            path += ".gz"
        with open(path, "wb") as f:
            f.write(data)
        self.files += 1
        self.bytes += len(data)

    def part(self, kind, key, obj):
        """map / region / hist entries ("<level>/<id>"): one file each, or with --bundle one file per kind and
        level (api/<kind>-<level>.json) so a phone only downloads the level it is looking at."""
        if self.bundle:
            self.parts.setdefault("%s-%s" % (kind, key.split("/", 1)[0]), {})[key] = obj
        else:
            self.write("api/%s/%s.json" % (kind, key), obj)

    def flush(self):
        for name, d in self.parts.items():
            self.write("api/%s.json" % name, d)
        self.parts = {}


def _copy_web(out, cfg_js):
    shutil.copytree(WEB_DIR, out, dirs_exist_ok=True)
    with open(os.path.join(WEB_DIR, "index.html"), encoding="utf-8") as f:
        html = f.read()
    html = html.replace(", viewport-fit=cover", "")
    if cfg_js.get("preview"):
        html = html.replace("<title>Housing Atlas</title>", "<title>Housing Atlas preview</title>")
    if cfg_js.get("hosted"):
        # a personal copy: ask search engines not to list it
        html = html.replace("<meta charset=\"utf-8\">", "<meta charset=\"utf-8\">\n  <meta name=\"robots\" content=\"noindex, nofollow\">")
    tag = '<script type="module" src="js/app.js"></script>'
    html = html.replace(tag, "<script>window.HA_STATIC = %s;</script>\n  %s" % (json.dumps(cfg_js), tag))
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


def _copy_geo(out):
    src = srv.GEO_DIR
    n = 0
    for root, _dirs, files in os.walk(src):
        for fn in files:
            if not fn.endswith(".json"):
                continue
            rel = os.path.relpath(os.path.join(root, fn), src)
            dest = os.path.join(out, "geo", rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(os.path.join(root, fn), dest)
            n += 1
    return n


def _children_counts(con):
    cnt = {lv: {} for lv in LEVELS}
    geo = {lv: srv.CACHE.geo_level(con, lv) for lv in LEVELS}
    for g in geo["metro"].values():
        if g.get("state"):
            cnt["state"].setdefault(g["state"], {}).setdefault("metro", 0)
            cnt["state"][g["state"]]["metro"] += 1
    for g in geo["county"].values():
        if g.get("state"):
            d = cnt["state"].setdefault(g["state"], {})
            d["county"] = d.get("county", 0) + 1
        if g.get("metro"):
            d = cnt["metro"].setdefault(g["metro"], {})
            d["county"] = d.get("county", 0) + 1
    for g in geo["zip"].values():
        if g.get("metro"):
            d = cnt["metro"].setdefault(g["metro"], {})
            d["zip"] = d.get("zip", 0) + 1
        if g.get("county"):
            d = cnt["county"].setdefault(g["county"], {})
            d["zip"] = d.get("zip", 0) + 1
    cnt["us"]["US"] = {"state": len(geo["state"]), "metro": len(geo["metro"])}
    return cnt, geo


def _regions(con, cfg, eng, w, report, levels=LEVELS, min_year=None):
    """One report per region: the same answer as /api/region plus every metric's series (from min_year[level]
    on, when given; the latest values and ranks always use the full history)."""
    import bisect
    avail = srv.CACHE.available(con, cfg)
    children, geo = _children_counts(con)
    total = 0
    for level in levels:
        cut = (min_year or {}).get(level)
        mids = [m for m in METRICS if level in avail.get(m["id"], [])]
        sorted_vals = {m["id"]: srv.CACHE.sorted_vals(con, m["id"], "level", level) for m in mids}
        report("Exporting %d %s reports" % (len(geo[level]), level))
        for gid, g in geo[level].items():
            metrics, series = {}, {}
            for m in mids:
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
                vals = sorted_vals[m["id"]]
                if vals and len(vals) > 1:
                    below = bisect.bisect_left(vals, v)
                    entry["rank"] = len(vals) - bisect.bisect_right(vals, v) + 1
                    entry["of"] = len(vals)
                    entry["pct"] = round(below / float(len(vals) - 1), 3)
                metrics[m["id"]] = entry
                off, vv = _vals(s.v)
                start = s.start + off
                if cut is not None:
                    ci = cut * 12 if s.freq == "M" else cut * 4 if s.freq == "Q" else cut
                    if start < ci:
                        vv = vv[ci - start:]
                        start = ci
                if vv:
                    series[m["id"]] = [s.freq, start, vv]
            parents = []
            if level != "us":
                parents.append({"level": "us", "id": "US", "name": "United States"})
            if g.get("state") and level in ("metro", "county", "zip"):
                parents.append({"level": "state", "id": g["state"], "name": ABBR_TO_NAME.get(g["state"], g["state"])})
            if g.get("metro") and level in ("county", "zip") and g["metro"] in geo["metro"]:
                parents.append({"level": "metro", "id": g["metro"], "name": geo["metro"][g["metro"]]["name"]})
            if g.get("county") and level == "zip" and g["county"] in geo["county"]:
                parents.append({"level": "county", "id": g["county"], "name": geo["county"][g["county"]]["name"]})
            w.part("region", "%s/%s" % (level, gid), {
                "level": level, "id": gid, "name": g["name"], "full_name": g.get("full_name"), "state": g.get("state"),
                "pop": g.get("pop"), "lat": g.get("lat"), "lon": g.get("lon"), "bbox": g.get("bbox"),
                "lsad": g.get("lsad"), "city": g.get("city"), "parents": parents,
                "children": children[level].get(gid, {}) if level != "zip" else {}, "metrics": metrics,
                "market": srv.market_label(metrics), "watched": False, "series": series})
            total += 1
    return total


def _dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            total += os.path.getsize(os.path.join(root, fn))
    return total


def export(out_dir, bundle=False, preview=False, history=DEFAULT_HISTORY, report=None, hosted=False, max_mb=900):
    """hosted=True builds a copy for a free static host such as GitHub Pages (which allows 1 GB): map history
    for the U.S., states and metros, and ZIP-code reports trimmed to as many recent years as fit in max_mb."""
    report = report or (lambda msg: log.info(msg))
    if hosted:
        bundle = False
    compress = bool(hosted)
    t0 = time.time()
    con = thread_conn()
    srv.CACHE.check(con)
    cfg = load_config()
    if not con.execute("SELECT 1 FROM snap LIMIT 1").fetchone():
        raise RuntimeError("No data yet - run `python app.py update` first.")
    eng = Engine(con, cfg)
    h = _NoUser()
    os.makedirs(out_dir, exist_ok=True)
    built = time.strftime("%Y-%m-%d %H:%M")
    if hosted and os.path.isdir(os.path.join(out_dir, "api")):
        shutil.rmtree(os.path.join(out_dir, "api"))  # start clean so old files don't count against the limit
    _copy_web(out_dir, {"bundle": bool(bundle), "preview": bool(preview), "basemap": not preview, "built": built,
                        "version": __version__, "history": list(history), "hosted": bool(hosted), "gz": compress,
                        "banner": ("Sample-data preview \u00b7 real maps and numbers load when you run it on your "
                                   "computer") if preview else None})
    report("Copying map shapes")
    n_geo = _copy_geo(out_dir)
    w = _Writer(out_dir, bundle, compress)

    report("Writing app info, national series, sources and methodology")
    meta = srv.api_meta(h, {})
    meta.update({"static": {"built": built, "version": __version__, "preview": bool(preview)},
                 "update": {"running": False, "log": []}, "user": None, "can_admin": False, "users_exist": True,
                 "schedule": "Data as of " + (meta.get("last_update") or built)})
    w.write("api/meta.json", meta)
    w.write("api/national.json", srv.api_national(h, {}))
    sources = srv.api_sources(h, {})
    sources["update"] = {"running": False, "log": []}
    w.write("api/sources.json", sources)
    w.write("api/methodology.json", srv.api_methodology(h, {}))
    settings = srv.api_settings_get(h, {})
    for k in ("data_dir", "census_api_key", "bea_api_key", "bls_api_key", "url_overrides", "server"):
        settings.pop(k, None)
    w.write("api/settings.json", settings)

    report("Writing place names and the search index")
    fields = ["name", "state", "metro", "county", "lsad", "pop", "city"]
    for level in LEVELS:
        g = srv.CACHE.geo_level(con, level)
        w.write("api/geos/%s.json" % level, {
            "f": fields, "r": {gid: [x.get(k) for k in fields] for gid, x in g.items()},
            "bbox": {gid: x["bbox"] for gid, x in g.items() if x.get("bbox")} if level != "zip" else {}})
    w.write("api/search.json", [list(r) for r in srv.build_search_index(con)])

    report("Writing map layers")
    layers = {}
    for metric, tf, level, period, data in con.execute("SELECT metric, transform, level, period, data FROM snap"):
        layers.setdefault((level, metric), {})[tf] = [period, json.loads(data)]
    for (level, metric), d in layers.items():
        w.part("map", "%s/%s" % (level, metric), d)

    report("Writing map history")
    dates = {}
    avail = srv.CACHE.available(con, cfg)
    for level in history:
        for m in METRICS:
            if level not in avail.get(m["id"], []) or (level, m["id"]) not in layers:
                continue
            d = srv.api_dates(h, {"metric": [m["id"]], "level": [level]})
            if not d.get("start"):
                continue
            ser = eng.level_series(m["id"], level)
            out, freq = {}, None
            for gid, s in ser.items():
                off, vv = _vals(s.v)
                if vv:
                    out[gid] = [s.start + off, vv]
                    freq = s.freq
            if out:
                w.part("hist", "%s/%s" % (level, m["id"]), {"freq": freq, "s": out})
                dates["%s|%s" % (m["id"], level)] = d
    w.write("api/dates.json", dates)
    w.flush()

    if not hosted:
        n_regions = _regions(con, cfg, eng, w, report)
        w.flush()
    else:
        n_regions = _regions(con, cfg, eng, w, report, levels=("us", "state", "metro", "county"))
        w.flush()
        budget = max_mb * 1e6
        other = _dir_size(out_dir)
        zdir = os.path.join(out_dir, "api", "region", "zip")
        this_year = int(time.strftime("%Y"))
        years = None  # full history first; trimmed only if the site would be too big
        while True:
            shutil.rmtree(zdir, ignore_errors=True)
            cut = {"zip": this_year - years + 1} if years else None
            n_zip = _regions(con, cfg, eng, w, report, levels=("zip",), min_year=cut)
            total = _dir_size(out_dir)
            report("ZIP-code reports with %s: site is %.0f MB (limit %d MB)" % (
                "%d years of history" % years if years else "full history", total / 1e6, max_mb))
            if total <= budget or (years or 99) <= 2:
                break
            span = years or (this_year - 1999)
            fit = int(span * (budget - other) / max(1.0, total - other) * 0.8)
            years = max(2, min(span - 1, fit))
        if total > budget:
            shutil.rmtree(zdir, ignore_errors=True)
            n_zip = 0
            report("ZIP-code reports left out to stay under %d MB (ZIP codes still show on the map)" % max_mb)
        n_regions += n_zip
    if hosted:
        w.bytes = _dir_size(os.path.join(out_dir, "api"))
        w.files = sum(len(f) for _r, _d, f in os.walk(os.path.join(out_dir, "api")))
    secs = time.time() - t0
    msg = ("Static web app written to %s: %d map layers, %d region reports, %d shape files, %d data files "
           "(%.1f MB) in %.0fs" % (out_dir, sum(len(d) for d in layers.values()), n_regions, n_geo, w.files,
                                   w.bytes / 1e6, secs))
    report(msg)
    return {"out": out_dir, "regions": n_regions, "files": w.files, "bytes": w.bytes, "seconds": secs,
            "last_update": get_meta(con, "last_update")}
