"""Redfin Data Center - Housing Market Tracker (monthly; national/state/metro/county/ZIP)
and the weekly national tracker. https://www.redfin.com/news/data-center/"""

import json
import re
from array import array

from ..db import SeriesWriter, now_str
from ..geo.states import state_abbr
from ..util import NAN, log, midx, midx_str, now_midx, parse_month, to_float
from .common import open_text, pct_scale

S3 = "https://redfin-public-data.s3.us-west-2.amazonaws.com"
FILES = {
    "us": S3 + "/redfin_market_tracker/us_national_market_tracker.tsv000.gz",
    "state": S3 + "/redfin_market_tracker/state_market_tracker.tsv000.gz",
    "metro": S3 + "/redfin_market_tracker/redfin_metro_market_tracker.tsv000.gz",
    "county": S3 + "/redfin_market_tracker/county_market_tracker.tsv000.gz",
    "zip": S3 + "/redfin_market_tracker/zip_code_market_tracker.tsv000.gz",
}
WEEKLY = S3 + "/redfin_covid19/weekly_housing_market_data_most_recent.tsv000.gz"

# normalized column name -> our metric id
METRICS = {
    "median_sale_price": "rf_median_sale_price",
    "median_list_price": "rf_median_list_price",
    "median_ppsf": "rf_median_ppsf",
    "homes_sold": "rf_homes_sold",
    "pending_sales": "rf_pending_sales",
    "new_listings": "rf_new_listings",
    "inventory": "rf_inventory",
    "months_of_supply": "rf_months_supply",
    "median_dom": "rf_dom",
    "avg_sale_to_list": "rf_sale_to_list",
    "sold_above_list": "rf_sold_above_list",
    "price_drops": "rf_price_drops",
    "off_market_in_two_weeks": "rf_off_market_2wk",
}
SHARES = {"rf_sale_to_list", "rf_sold_above_list", "rf_price_drops", "rf_off_market_2wk"}
COUNTS = {"rf_homes_sold", "rf_pending_sales", "rf_new_listings", "rf_inventory"}

# Current (2025+) Redfin Data Center headers -> legacy names
ALIASES = {
    "median_sale_price_nsa": "median_sale_price",
    "median_sale_price_sa": "median_sale_price_sa",
    "median_new_listing_price": "median_list_price",
    "median_sale_price_per_sq_ft": "median_ppsf",
    "median_sale_price_per_sqft": "median_ppsf",
    "median_new_listing_price_per_sq_ft": "median_list_ppsf",
    "median_days_on_market": "median_dom",
    "average_sale_to_list_ratio": "avg_sale_to_list",
    "share_sold_above_original_list": "sold_above_list",
    "percent_off_market_in_two_weeks": "off_market_in_two_weeks",
    "region_name": "region",
    "region_id": "table_id",
    "seasonally_adjusted": "is_seasonally_adjusted",
}

INFO = {
    "id": "redfin",
    "name": "Redfin Data Center - Housing Market Tracker",
    "homepage": "https://www.redfin.com/news/data-center/",
    "description": "MLS-based monthly sales data: median sale price, homes sold, pending sales, new listings, "
                   "inventory, months of supply, median days on market, sale-to-list ratio, share sold above "
                   "list, price drops and share off market in two weeks. ZIP-level figures are 3-month rolling.",
    "frequency": "Monthly (mid-month) + weekly national tracker (Thursdays)",
    "metrics": sorted(METRICS.values()),
    "license": "Free to use with attribution to Redfin (Redfin Data Center)",
}

BASE_M = midx(2012, 1)


def file_list(cfg):
    out = [{"key": "redfin_%s" % lv, "url": u, "desc": "Market tracker (%s)" % lv} for lv, u in FILES.items()]
    out.append({"key": "redfin_weekly", "url": WEEKLY, "desc": "Weekly tracker (national & metro)"})
    return out


def norm_col(h):
    h = h.strip().strip('"').lower()
    h = re.sub(r"\(.*?\)", "", h)
    h = re.sub(r"[^a-z0-9]+", "_", h).strip("_")
    return ALIASES.get(h, h)


def _split(line):
    parts = line.rstrip("\r\n").split("\t")
    return [p.strip().strip('"') for p in parts]


class _Agg:
    """Combine metropolitan divisions into their parent metro (counts summed,
    medians/ratios weighted by homes sold or inventory - an approximation)."""

    def __init__(self):
        self.acc = {}

    def add(self, cbsa, m, rec):
        self.acc.setdefault((cbsa, m), []).append(rec)

    def results(self):
        for (cbsa, m), recs in self.acc.items():
            out = {}
            for metric in METRICS.values():
                vals = [(r.get(metric), r) for r in recs if r.get(metric) == r.get(metric) and r.get(metric) is not None]
                if not vals:
                    continue
                if metric in COUNTS:
                    out[metric] = sum(v for v, _ in vals)
                elif metric == "rf_months_supply":
                    continue
                else:
                    wkey = "rf_inventory" if metric in ("rf_median_list_price", "rf_dom", "rf_price_drops") else "rf_homes_sold"
                    num = den = 0.0
                    for v, r in vals:
                        w = r.get(wkey)
                        w = w if (w is not None and w == w and w > 0) else 1.0
                        num += v * w
                        den += w
                    if den:
                        out[metric] = num / den
            inv, sold = out.get("rf_inventory"), out.get("rf_homes_sold")
            if inv and sold:
                out["rf_months_supply"] = inv / sold
            yield cbsa, m, out


def parse_tracker(ctx, path, level, accept_sa=False):
    span = now_midx() - BASE_M + 3
    data = {m: {} for m in METRICS.values()}
    agg = _Agg()
    direct_metros = set()
    latest = None
    seen_sa = 0
    accepted = 0
    geo = ctx.geo
    unmatched = {}
    with open_text(path) as f:
        header_line = f.readline()
        header = [norm_col(h) for h in header_line.rstrip("\r\n").split("\t")]
        idx = {h: i for i, h in enumerate(header)}
        need = ["period_end", "region"]
        for n in need:
            if n not in idx:
                raise ValueError("Redfin file missing column '%s' (header starts: %s)" % (n, header[:10]))
        i_pe = idx["period_end"]
        i_reg = idx["region"]
        i_pt = idx.get("property_type")
        i_ptid = idx.get("property_type_id")
        i_sa = idx.get("is_seasonally_adjusted")
        i_st = idx.get("state_code")
        i_tid = idx.get("table_id")
        cols = [(idx[c], m) for c, m in METRICS.items() if c in idx]
        prefilter = i_pt is not None
        for line in f:
            if prefilter and ("ll Residential" not in line and "ll residential" not in line
                              and "LL RESIDENTIAL" not in line):
                continue
            p = _split(line)
            if len(p) <= i_reg:
                continue
            if i_pt is not None and p[i_pt].lower() != "all residential":
                continue
            if i_pt is None and i_ptid is not None and p[i_ptid] not in ("-1", ""):
                continue
            if i_sa is not None:
                sa = p[i_sa].lower() in ("true", "t", "1", "yes", "y")
                if sa:
                    seen_sa += 1
                    if not accept_sa:
                        continue
                elif accept_sa:
                    continue
            m = parse_month(p[i_pe])
            if m is None:
                continue
            k = m - BASE_M
            if k < 0 or k >= span:
                continue
            region = p[i_reg]
            via_div = None
            if level == "us":
                gid = "US"
            elif level == "state":
                gid = state_abbr(p[i_st] if i_st is not None else None) or state_abbr(region)
            elif level == "metro":
                code = p[i_tid] if i_tid is not None else None
                gid = None
                if code and code.isdigit():
                    c5 = code.zfill(5)
                    if c5 in geo.cbsa:
                        gid = c5
                    elif c5 in geo.mdiv_cbsa:
                        via_div = geo.mdiv_cbsa[c5]
                if gid is None and via_div is None:
                    gid = geo.cbsa_code(name=region)
            elif level == "county":
                gid = geo.county_fips(region, p[i_st] if i_st is not None else None)
            else:
                mm = re.search(r"(\d{5})", region)
                gid = mm.group(1) if mm else None
            if not gid and not via_div:
                if len(unmatched) < 200:
                    unmatched[region] = unmatched.get(region, 0) + 1
                continue
            accepted += 1
            if latest is None or m > latest:
                latest = m
            if via_div:
                rec = {}
                for ci, metric in cols:
                    if ci < len(p) and p[ci] != "":
                        v = to_float(p[ci])
                        if v == v:
                            rec[metric] = v
                agg.add(via_div, m, rec)
                continue
            if level == "metro":
                direct_metros.add(gid)
            for ci, metric in cols:
                if ci >= len(p):
                    continue
                s = p[ci]
                if s == "":
                    continue
                try:
                    v = float(s)
                except ValueError:
                    v = to_float(s)
                if v != v:
                    continue
                d = data[metric]
                arr = d.get(gid)
                if arr is None:
                    arr = array("f", [NAN]) * span
                    d[gid] = arr
                arr[k] = v
    if accepted == 0 and seen_sa and not accept_sa:
        log.info("  only seasonally-adjusted rows found; using them")
        return parse_tracker(ctx, path, level, accept_sa=True)
    # Metros reported only as divisions (e.g. New York, Los Angeles): build combined values.
    for cbsa, m, rec in agg.results():
        if cbsa in direct_metros:
            continue
        k = m - BASE_M
        for metric, v in rec.items():
            d = data[metric]
            arr = d.get(cbsa)
            if arr is None:
                arr = array("f", [NAN]) * span
                d[cbsa] = arr
            arr[k] = v
    # Shares: fraction -> percent (legacy files store 0.987; new ones may store 98.7)
    for metric in SHARES:
        geos = data.get(metric) or {}
        if not geos:
            continue
        sample = []
        for arr in list(geos.values())[:3000]:
            sample.extend(x for x in arr[-24:] if x == x)
        if pct_scale(sample) != 1.0:
            for gid in list(geos):
                geos[gid] = array("f", [x * 100.0 for x in geos[gid]])
    if unmatched:
        log.info("  Redfin %s regions not matched (sample): %s", level, ", ".join(list(unmatched)[:10]))
    return data, latest, list(unmatched)[:30]


def parse_weekly(path):
    """National rows of the weekly tracker -> {column: [(date, value), ...]}"""
    out = {}
    with open_text(path) as f:
        header = [norm_col(h) for h in f.readline().rstrip("\r\n").split("\t")]
        idx = {h: i for i, h in enumerate(header)}
        i_rt = idx.get("region_type")
        i_rn = idx.get("region_name", idx.get("region"))
        i_end = idx.get("period_end")
        i_dur = idx.get("duration")
        if i_end is None:
            return out
        wanted = [c for c in ("median_sale_price", "median_new_listing_price", "pending_sales", "active_listings",
                              "adjusted_average_new_listings", "total_new_listings", "median_days_on_market",
                              "percent_active_listings_with_price_drops", "months_of_supply",
                              "average_sale_to_list_ratio", "off_market_in_two_weeks", "total_homes_sold",
                              "age_of_inventory", "median_list_ppsf") if c in idx]
        for line in f:
            p = _split(line)
            if len(p) <= i_end:
                continue
            rt = p[i_rt].lower() if i_rt is not None and i_rt < len(p) else ""
            rn = p[i_rn].lower() if i_rn is not None and i_rn < len(p) else ""
            if not ("national" in rt or rn in ("national", "united states", "us")):
                continue
            if i_dur is not None and i_dur < len(p) and p[i_dur] and "4" not in p[i_dur]:
                continue
            d = p[i_end][:10]
            for c in wanted:
                v = to_float(p[idx[c]]) if idx[c] < len(p) else NAN
                if v == v:
                    out.setdefault(c, {})[d] = v
    return {c: sorted(v.items()) for c, v in out.items()}


def run(ctx):
    con = ctx.con
    levels = ctx.levels("redfin")
    files = {}
    problems = []
    lv_list = [lv for lv in ("us", "state", "metro", "county", "zip") if lv in levels]
    for i, lv in enumerate(lv_list):
        if ctx.cancelled():
            raise RuntimeError("cancelled")
        ctx.report("Redfin: downloading %s tracker [%d/%d] (the ZIP file is large)" % (lv, i + 1, len(lv_list)))
        res = ctx.dl.fetch("redfin_%s" % lv, FILES[lv], "redfin")
        if res.ok:
            files[lv] = res
        else:
            problems.append("%s: %s" % (lv, res.error or res.status))
    monthly_unchanged = ctx.unchanged("redfin", list(files.values()))
    stats = {}
    latest = None
    unmatched_all = {}
    for lv, res in ([] if monthly_unchanged else files.items()):
        if ctx.cancelled():
            raise RuntimeError("cancelled")
        ctx.report("Redfin: loading %s tracker" % lv)
        try:
            data, lt, unmatched = parse_tracker(ctx, res.path, lv)
        except Exception as e:
            log.exception("  redfin parse failed")
            problems.append("%s parse error: %s" % (lv, e))
            continue
        if unmatched:
            unmatched_all[lv] = unmatched
        if lt is not None:
            latest = max(latest or lt, lt)
        con.execute("BEGIN")
        try:
            w = SeriesWriter(con, "redfin")
            n = 0
            for metric, geos in data.items():
                if not geos:
                    continue
                con.execute("DELETE FROM series WHERE metric=? AND level=? AND src='redfin'", (metric, lv))
                for gid, arr in geos.items():
                    w.put(metric, lv, gid, "M", BASE_M, arr.tolist())
                    n += 1
            w.flush()
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        stats[lv] = n
        del data
    # Weekly national tracker -> macro table
    if ctx.source_cfg("redfin").get("weekly", True):
        res = ctx.dl.fetch("redfin_weekly", WEEKLY, "redfin")
        if res.ok:
            try:
                weekly = parse_weekly(res.path)
                names = {
                    "median_sale_price": ("Median sale price (4-wk, Redfin weekly)", "USD"),
                    "median_new_listing_price": ("Median new-listing price (4-wk)", "USD"),
                    "pending_sales": ("Pending sales (4-wk)", "Homes"),
                    "active_listings": ("Active listings (4-wk)", "Homes"),
                    "adjusted_average_new_listings": ("New listings, weekly avg (4-wk)", "Homes"),
                    "total_new_listings": ("New listings (4-wk)", "Homes"),
                    "median_days_on_market": ("Median days on market (4-wk)", "Days"),
                    "percent_active_listings_with_price_drops": ("Share of listings with price drops (4-wk)", "Share"),
                    "months_of_supply": ("Months of supply (4-wk)", "Months"),
                    "average_sale_to_list_ratio": ("Sale-to-list ratio (4-wk)", "Ratio"),
                    "off_market_in_two_weeks": ("Share off market in 2 weeks (4-wk)", "Share"),
                    "total_homes_sold": ("Homes sold (4-wk)", "Homes"),
                    "age_of_inventory": ("Age of inventory (4-wk)", "Days"),
                }
                for c, pts in weekly.items():
                    if len(pts) < 10:
                        continue
                    name, units = names.get(c, (c, ""))
                    con.execute("INSERT OR REPLACE INTO macro(sid,name,units,freq,src,category,dates,vals,updated) "
                                "VALUES(?,?,?,?,?,?,?,?,?)",
                                ("redfin_weekly_" + c, name, units, "W", "redfin", "Redfin weekly (national)",
                                 json.dumps([d for d, _ in pts]), json.dumps([v for _, v in pts]), now_str()))
                stats["weekly"] = len(weekly)
            except Exception as e:
                log.exception("  weekly parse failed")
                problems.append("weekly parse error: %s" % e)
        else:
            problems.append("weekly: %s" % (res.error or res.status))
    if monthly_unchanged:
        return {"unchanged": True, "ok": True, "message": "unchanged"}
    msg = "%d files loaded" % len([k for k in stats if k != "weekly"])
    if problems:
        msg += "; %d problems" % len(problems)
    if not stats:
        msg += (". No files could be loaded. The provider may have moved its downloads - see the Data & Sources page for the URLs and paste new links under Settings > Advanced: download URL overrides.")
    return {"message": msg, "details": {"loaded": stats, "problems": problems, "unmatched": unmatched_all},
            "ok": any(k != "weekly" for k in stats), "latest": midx_str(latest) if latest else None,
            "warn": bool(problems)}
