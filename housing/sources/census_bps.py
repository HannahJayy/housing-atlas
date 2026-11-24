"""U.S. Census Bureau Building Permits Survey (BPS) - new housing units authorized.
County files are summed to metros, states and the U.S."""

import time

from ..util import log, to_float
from .common import Store, read_text, replace_source_series, this_year

URL_A = "https://www2.census.gov/econ/bps/County/co{y}a.txt"
URL_Y = "https://www2.census.gov/econ/bps/County/co{yy}{mm}y.txt"

INFO = {
    "id": "census_bps",
    "name": "U.S. Census Bureau - Building Permits Survey",
    "homepage": "https://www.census.gov/construction/bps/",
    "description": "New privately-owned housing units authorized by building permits, by county (summed to "
                   "metros, states and the nation). The latest year is a trailing-12-month total built from the "
                   "newest monthly year-to-date file.",
    "frequency": "Monthly (county year-to-date files) + annual",
    "metrics": ["permits", "permits_sf", "permits_mf"],
    "license": "Public domain (U.S. Government work)",
}


def file_list(cfg):
    y = this_year()
    return [{"key": "bps_annual", "url": URL_A.format(y=y - 1), "desc": "Annual county permits (each year)"},
            {"key": "bps_ytd", "url": URL_Y.format(yy="%02d" % (y % 100), mm="09"),
             "desc": "Monthly year-to-date county permits (newest month found)"}]


def parse_bps(path):
    """-> {county_fips: (total_units, single_family_units)}"""
    out = {}
    text = read_text(path)
    for line in text.splitlines():
        p = [x.strip() for x in line.split(",")]
        if len(p) < 18 or not p[0].isdigit():
            continue
        st, co = p[1], p[2]
        if not (st.isdigit() and co.isdigit()):
            continue
        fips = st.zfill(2) + co.zfill(3)
        try:
            sf = to_float(p[7])
            u2 = to_float(p[10])
            u34 = to_float(p[13])
            u5 = to_float(p[16])
        except IndexError:
            continue
        vals = [x if x == x else 0.0 for x in (sf, u2, u34, u5)]
        out[fips] = (sum(vals), vals[0])
    return out


def run(ctx):
    con = ctx.con
    hist = int(ctx.source_cfg("census_bps").get("history_years", 15))
    y_now = this_year()
    annual = {}
    for y in range(y_now - hist, y_now):
        if ctx.cancelled():
            raise RuntimeError("cancelled")
        ctx.report("Building permits: annual %d" % y)
        res = ctx.dl.fetch("bps_annual_%d" % y, URL_A.format(y=y), "census_bps", quiet_missing=True,
                           max_age_hours=24 * 30 if y < y_now - 2 else None)
        if res.ok:
            try:
                annual[y] = parse_bps(res.path)
            except Exception as e:
                log.warning("  could not parse %s: %s", res.path, e)
    if not annual:
        raise RuntimeError("No building permit files could be downloaded")

    # newest year-to-date file (current year, or previous year if January/February)
    ytd = None
    for y in (y_now, y_now - 1):
        for mth in range(12, 0, -1):
            if y == y_now and mth > time.localtime().tm_mon:
                continue
            url = URL_Y.format(yy="%02d" % (y % 100), mm="%02d" % mth)
            res = ctx.dl.fetch("bps_ytd", url, "census_bps", quiet_missing=True)
            if res.ok:
                ytd = (y, mth, parse_bps(res.path))
                break
        if ytd:
            break
    ttm_label = None
    ttm = None
    if ytd:
        y, mth, cur = ytd
        if mth == 12:
            annual[y] = cur
        else:
            prev_url = URL_Y.format(yy="%02d" % ((y - 1) % 100), mm="%02d" % mth)
            res = ctx.dl.fetch("bps_ytd_prev", prev_url, "census_bps", quiet_missing=True)
            if res.ok and (y - 1) in annual:
                prev = parse_bps(res.path)
                ttm = {}
                keys = set(annual[y - 1]) | set(cur) | set(prev)
                for k in keys:
                    a = annual[y - 1].get(k, (0.0, 0.0))
                    c = cur.get(k, (0.0, 0.0))
                    p = prev.get(k, (0.0, 0.0))
                    ttm[k] = (max(0.0, a[0] + c[0] - p[0]), max(0.0, a[1] + c[1] - p[1]))
                annual[y] = ttm
                ttm_label = "%d (12 months through %d-%02d)" % (y, y, mth)

    store = Store("A")
    county_cbsa = ctx.geo.county_cbsa
    for y, data in annual.items():
        agg = {}
        for fips, (tot, sf) in data.items():
            store.add("permits", "county", fips, y, tot)
            store.add("permits_sf", "county", fips, y, sf)
            store.add("permits_mf", "county", fips, y, tot - sf)
            keys = [("us", "US"), ("state", ctx.geo.state_of_county(fips))]
            if fips in county_cbsa:
                keys.append(("metro", county_cbsa[fips]))
            for lv, gid in keys:
                if not gid:
                    continue
                a = agg.setdefault((lv, gid), [0.0, 0.0])
                a[0] += tot
                a[1] += sf
        for (lv, gid), (tot, sf) in agg.items():
            store.add("permits", lv, gid, y, tot)
            store.add("permits_sf", lv, gid, y, sf)
            store.add("permits_mf", lv, gid, y, tot - sf)
    n = replace_source_series(con, "census_bps", [(store, "A")])
    from ..db import set_meta
    set_meta(con, "permits_ttm_label", ttm_label)
    latest = max(annual)
    return {"message": "%d years of county permits (%d series)%s" % (
        len(annual), n, ("; latest = " + ttm_label) if ttm_label else ""),
            "details": {"years": sorted(annual), "ttm": ttm_label}, "ok": n > 0, "latest": ttm_label or str(latest)}
