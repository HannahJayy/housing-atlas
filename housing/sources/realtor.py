"""Realtor.com Economic Research - listing inventory core metrics & market hotness.
https://www.realtor.com/research/data/"""

import csv
from array import array

from ..db import SeriesWriter
from ..geo.states import state_abbr
from ..util import NAN, log, midx, midx_str, now_midx, parse_month, to_float
from .common import open_text, pct_scale

CORE = "https://econdata.s3-us-west-2.amazonaws.com/Reports/Core/RDC_Inventory_Core_Metrics_{geo}_History.csv"
HOT = "https://econdata.s3-us-west-2.amazonaws.com/Reports/Hotness/RDC_Inventory_Hotness_Metrics_{geo}_History.csv"
GEO = {"us": "Country", "state": "State", "metro": "Metro", "county": "County", "zip": "Zip"}

CORE_COLS = {
    "median_listing_price": ("list_price", False),
    "active_listing_count": ("inventory", False),
    "median_days_on_market": ("dom", False),
    "new_listing_count": ("new_listings", False),
    "price_increased_share": ("price_increase_share", True),
    "price_reduced_share": ("price_cut_share", True),
    "pending_listing_count": ("pending_listings", False),
    "median_listing_price_per_square_foot": ("list_ppsf", False),
    "median_square_feet": ("median_sqft", False),
    "average_listing_price": ("avg_list_price", False),
    "total_listing_count": ("total_listings", False),
    "pending_ratio": ("pending_ratio", True),
}
HOT_COLS = {
    "hotness_score": ("hotness_score", False),
    "supply_score": ("supply_score", False),
    "demand_score": ("demand_score", False),
    "page_view_count_per_property_vs_us": ("views_vs_us", False),
}

INFO = {
    "id": "realtor",
    "name": "Realtor.com Economic Research - Housing Inventory Data",
    "homepage": "https://www.realtor.com/research/data/",
    "description": "Monthly MLS-based listing data: active inventory, new and pending listings, median list "
                   "price and price/sq ft, days on market, share of listings with price cuts/increases, plus "
                   "the Market Hotness index (supply, demand and listing views).",
    "frequency": "Monthly (first week of each month)",
    "metrics": sorted({v[0] for v in CORE_COLS.values()} | {v[0] for v in HOT_COLS.values()}),
    "license": "Free to use with attribution to Realtor.com",
}

BASE_M = midx(2012, 1)


def file_list(cfg):
    out = [{"key": "realtor_core_%s" % lv, "url": CORE.format(geo=g), "desc": "Inventory core metrics (%s)" % lv}
           for lv, g in GEO.items()]
    out += [{"key": "realtor_hot_%s" % lv, "url": HOT.format(geo=GEO[lv]), "desc": "Market hotness (%s)" % lv}
            for lv in ("metro", "county", "zip")]
    return out


def _ff(s):
    try:
        return float(s)
    except ValueError:
        return to_float(s)


def _geo_id(level, row, idx, geo):
    if level == "us":
        return "US"
    if level == "state":
        for col in ("state_id", "state"):
            i = idx.get(col)
            if i is not None and i < len(row):
                st = state_abbr(row[i])
                if st:
                    return st
        return None
    if level == "metro":
        i = idx.get("cbsa_code")
        if i is None or i >= len(row):
            return None
        c = row[i].strip().split(".")[0]
        return c.zfill(5) if c.isdigit() else None
    if level == "county":
        i = idx.get("county_fips")
        if i is None or i >= len(row):
            return None
        c = row[i].strip().split(".")[0]
        return c.zfill(5) if c.isdigit() else None
    if level == "zip":
        i = idx.get("postal_code")
        if i is None or i >= len(row):
            return None
        z = row[i].strip().split(".")[0]
        return z.zfill(5) if z.isdigit() else None
    return None


def parse_long(path, level, colmap):
    """Returns ({metric: {geo: array}}, latest_month)."""
    span = now_midx() - BASE_M + 3
    out = {m: {} for m, _ in colmap.values()}
    latest = None
    with open_text(path) as f:
        rdr = csv.reader(f)
        header = [h.strip().lower() for h in next(rdr)]
        idx = {h: i for i, h in enumerate(header)}
        mi = idx.get("month_date_yyyymm")
        if mi is None:
            mi = idx.get("month_date")
        if mi is None:
            raise ValueError("no month column in %s" % path)
        cols = [(idx[c], m) for c, (m, share) in colmap.items() if c in idx]
        if not cols:
            raise ValueError("no known metric columns in %s (header: %s)" % (path, header[:8]))
        for row in rdr:
            if len(row) <= mi:
                continue
            m = parse_month(row[mi])
            if m is None:
                continue  # footer / notes
            k = m - BASE_M
            if k < 0 or k >= span:
                continue
            gid = _geo_id(level, row, idx, None)
            if not gid:
                continue
            if latest is None or m > latest:
                latest = m
            for ci, metric in cols:
                if ci >= len(row):
                    continue
                s = row[ci]
                if s == "":
                    continue
                v = _ff(s)
                if v != v:
                    continue
                d = out[metric]
                arr = d.get(gid)
                if arr is None:
                    arr = array("f", [NAN]) * span
                    d[gid] = arr
                arr[k] = v
    # fractions -> percent
    for c, (metric, share) in colmap.items():
        if share and out.get(metric):
            sample = []
            for arr in list(out[metric].values())[:3000]:
                sample.extend(x for x in arr[-30:] if x == x)
            scale = pct_scale(sample)
            if scale != 1.0:
                for gid, arr in out[metric].items():
                    out[metric][gid] = array("f", [x * scale for x in arr])
    return out, latest


def run(ctx):
    con = ctx.con
    levels = ctx.levels("realtor")
    want = [("core", lv) for lv in GEO if lv in levels]
    if ctx.source_cfg("realtor").get("hotness", True):
        want += [("hot", lv) for lv in ("metro", "county", "zip") if lv in levels]
    files = {}
    problems = []
    for i, (kind, lv) in enumerate(want):
        if ctx.cancelled():
            raise RuntimeError("cancelled")
        url = (CORE if kind == "core" else HOT).format(geo=GEO[lv])
        ctx.report("Realtor.com: downloading %s (%s) [%d/%d]" % (kind, lv, i + 1, len(want)))
        res = ctx.dl.fetch("realtor_%s_%s" % (kind, lv), url, "realtor")
        if res.ok:
            files[(kind, lv)] = res
        else:
            problems.append("%s/%s: %s" % (kind, lv, res.error or res.status))

    if ctx.unchanged("realtor", list(files.values())):
        return {"unchanged": True, "ok": True, "message": "unchanged"}
    stats = {}
    latest = None
    for (kind, lv), res in files.items():
        if ctx.cancelled():
            raise RuntimeError("cancelled")
        ctx.report("Realtor.com: loading %s (%s)" % (kind, lv))
        try:
            data, lt = parse_long(res.path, lv, CORE_COLS if kind == "core" else HOT_COLS)
        except Exception as e:
            log.exception("  realtor parse failed")
            problems.append("%s/%s parse error: %s" % (kind, lv, e))
            continue
        if lt is not None and kind == "core":
            latest = max(latest or lt, lt)
        con.execute("BEGIN")
        try:
            w = SeriesWriter(con, "realtor")
            n = 0
            for metric, geos in data.items():
                if not geos:
                    continue
                con.execute("DELETE FROM series WHERE metric=? AND level=? AND src='realtor'", (metric, lv))
                for gid, arr in geos.items():
                    w.put(metric, lv, gid, "M", BASE_M, arr.tolist())
                    n += 1
            w.flush()
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        stats["%s/%s" % (kind, lv)] = n
        del data
    msg = "%d files loaded" % len(stats)
    if problems:
        msg += "; %d problems" % len(problems)
    if not stats:
        msg += (". No files could be loaded. The provider may have moved its downloads - see the Data & Sources page for the URLs and paste new links under Settings > Advanced: download URL overrides.")
    return {"message": msg, "details": {"loaded": stats, "problems": problems}, "ok": bool(stats),
            "latest": midx_str(latest) if latest else None, "warn": bool(problems)}
