"""Zillow Research data (ZHVI home values, ZORI rents, forecasts, listings & sales metrics).
https://www.zillow.com/research/data/  - free for public use with attribution."""

import csv
import re
from collections import Counter, defaultdict

from ..db import SeriesWriter, trim
from ..geo.states import state_abbr
from ..util import NAN, log, norm_name, parse_month, to_float
from .common import open_text, pct_scale, upsert_geo

BASE = "https://files.zillowstatic.com/research/public_csvs/{dir}/{geo}_{stem}.csv"
GEO_PREFIX = {"state": "State", "metro": "Metro", "county": "County", "zip": "Zip"}

# metric, directory, file stem, levels, kind ('level' | 'share' (fraction->%), 'forecast')
DATASETS = [
    ("zhvi", "zhvi", "zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month", ["county", "metro", "state", "zip"], "level"),
    ("rent", "zori", "zori_uc_sfrcondomfr_sm_month", ["metro", "county", "zip", "state"], "level"),
    ("rent_houses", "zori", "zori_uc_sfr_sm_month", ["metro", "county", "zip"], "level"),
    ("rent_apartments", "zori", "zori_uc_mfr_sm_month", ["metro", "county", "zip"], "level"),
    ("zhvf_1y", "zhvf_growth", "zhvf_growth_uc_sfrcondo_tier_0.33_0.67_sm_sa_month", ["metro", "zip", "county", "state"], "forecast"),
    ("zhvi_sfr", "zhvi", "zhvi_uc_sfr_tier_0.33_0.67_sm_sa_month", ["metro", "county", "state"], "level"),
    ("zhvi_condo", "zhvi", "zhvi_uc_condo_tier_0.33_0.67_sm_sa_month", ["metro", "county", "state"], "level"),
    ("zhvi_bottom", "zhvi", "zhvi_uc_sfrcondo_tier_0.0_0.33_sm_sa_month", ["metro", "county", "state"], "level"),
    ("zhvi_top", "zhvi", "zhvi_uc_sfrcondo_tier_0.67_1.0_sm_sa_month", ["metro", "county", "state"], "level"),
    ("z_inventory", "invt_fs", "invt_fs_uc_sfrcondo_sm_month", ["metro"], "level"),
    ("z_new_listings", "new_listings", "new_listings_uc_sfrcondo_sm_month", ["metro"], "level"),
    ("z_new_pending", "new_pending", "new_pending_uc_sfrcondo_sm_month", ["metro"], "level"),
    ("z_list_price", "mlp", "mlp_uc_sfrcondo_sm_month", ["metro"], "level"),
    ("z_median_sale_price", "median_sale_price", "median_sale_price_uc_sfrcondo_sm_sa_month", ["metro"], "level"),
    ("z_sales_count", "sales_count_now", "sales_count_now_uc_sfrcondo_month", ["metro"], "level"),
    ("z_sale_to_list", "mean_sale_to_list", "mean_sale_to_list_uc_sfrcondo_sm_month", ["metro"], "share"),
    ("z_pct_above_list", "pct_sold_above_list", "pct_sold_above_list_uc_sfrcondo_sm_month", ["metro"], "share"),
    ("z_price_cut_share", "perc_listings_price_cut", "perc_listings_price_cut_uc_sfrcondo_sm_month", ["metro"], "share"),
    ("z_days_pending", "med_doz_pending", "med_doz_pending_uc_sfrcondo_sm_month", ["metro"], "level"),
    ("z_heat_index", "market_temp_index", "market_temp_index_uc_sfrcondo_month", ["metro"], "level"),
    ("z_new_con_sales", "new_con_sales_count_raw", "new_con_sales_count_raw_uc_sfrcondo_month", ["metro"], "level"),
    ("z_new_con_price", "new_con_median_sale_price", "new_con_median_sale_price_uc_sfrcondo_month", ["metro"], "level"),
    ("z_income_needed", "new_homeowner_income_needed",
     "new_homeowner_income_needed_downpayment_0.20_uc_sfrcondo_tier_0.33_0.67_sm_sa_month", ["metro"], "level"),
]
EXTENDED = {"zhvi_sfr", "zhvi_condo", "zhvi_bottom", "zhvi_top"}

INFO = {
    "id": "zillow",
    "name": "Zillow Research (Zillow Economic Data)",
    "homepage": "https://www.zillow.com/research/data/",
    "description": "Zillow Home Value Index (typical home value), Zillow Observed Rent Index, 1-year home value "
                   "forecasts, and listing/sales metrics (inventory, new listings, price cuts, days to pending, "
                   "sale-to-list, market heat, new construction).",
    "frequency": "Monthly (around the middle of each month)",
    "metrics": sorted({d[0] for d in DATASETS}),
    "license": "Free for public use with attribution to Zillow",
}

DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def url_for(dir_, level, stem):
    return BASE.format(dir=dir_, geo=GEO_PREFIX[level], stem=stem)


def file_list(cfg):
    out = []
    for metric, d, stem, levels, kind in DATASETS:
        for lv in levels:
            out.append({"key": "zillow_%s_%s" % (metric, lv), "url": url_for(d, lv, stem),
                        "desc": "%s (%s)" % (metric, lv)})
    return out


def iter_wide(path):
    """Yield (meta dict, start month idx, values list) from a Zillow wide CSV."""
    with open_text(path) as f:
        rdr = csv.reader(f)
        header = next(rdr)
        dates = []
        meta_cols = []
        for i, h in enumerate(header):
            h = h.strip()
            if DATE_RE.match(h):
                dates.append((i, parse_month(h)))
            else:
                meta_cols.append((i, h))
        if not dates:
            return
        dates.sort(key=lambda x: x[1])
        start = dates[0][1]
        span = dates[-1][1] - start + 1
        for row in rdr:
            if not row:
                continue
            meta = {h: (row[i].strip() if i < len(row) else "") for i, h in meta_cols}
            vals = [NAN] * span
            for i, m in dates:
                if i < len(row) and row[i] != "":
                    vals[m - start] = to_float(row[i])
            yield meta, start, vals


def iter_forecast(path):
    """ZHVF files: meta..., BaseDate, then 3 horizon columns. Yield (meta, base_idx, 1y forecast)."""
    with open_text(path) as f:
        rdr = csv.reader(f)
        header = [h.strip() for h in next(rdr)]
        dates = [(i, parse_month(h)) for i, h in enumerate(header) if DATE_RE.match(h)]
        if not dates:
            return
        last_col = max(dates, key=lambda x: x[1])[0]
        bi = header.index("BaseDate") if "BaseDate" in header else None
        meta_cols = [(i, h) for i, h in enumerate(header) if not DATE_RE.match(h)]
        for row in rdr:
            if not row:
                continue
            meta = {h: (row[i].strip() if i < len(row) else "") for i, h in meta_cols}
            base = parse_month(row[bi]) if bi is not None and bi < len(row) else None
            if base is None:
                base = min(d[1] for d in dates) - 1
            v = to_float(row[last_col]) if last_col < len(row) else NAN
            yield meta, base, v


class Resolver:
    def __init__(self, ctx):
        self.ctx = ctx
        self.geo = ctx.geo
        self.metro_votes = defaultdict(Counter)
        self.metro_map = {}
        self.unmatched = Counter()

    def learn_from_county(self, meta, fips):
        m = meta.get("Metro") or ""
        cbsa = self.geo.county_cbsa.get(fips)
        if m and cbsa:
            self.metro_votes[norm_name(m)][cbsa] += 1

    def finalize_votes(self):
        for name, cnt in self.metro_votes.items():
            self.metro_map[name] = cnt.most_common(1)[0][0]

    def county(self, meta):
        st = (meta.get("StateCodeFIPS") or "").split(".")[0]
        co = (meta.get("MunicipalCodeFIPS") or "").split(".")[0]
        if st.isdigit() and co.isdigit():
            return st.zfill(2) + co.zfill(3)
        return self.geo.county_fips(meta.get("RegionName"), meta.get("State") or meta.get("StateName"))

    def metro(self, meta):
        name = meta.get("RegionName") or ""
        k = norm_name(name)
        if k in self.metro_map:
            return self.metro_map[k]
        c = self.geo.cbsa_code(name=name)
        if c:
            self.metro_map[k] = c
            return c
        self.unmatched[name] += 1
        return None

    def resolve(self, level, meta):
        rtype = (meta.get("RegionType") or "").lower()
        if rtype == "country" or meta.get("RegionName") == "United States":
            return "us", "US"
        if level == "state":
            st = state_abbr(meta.get("RegionName")) or state_abbr(meta.get("StateName"))
            return ("state", st) if st else (None, None)
        if level == "metro":
            return "metro", self.metro(meta)
        if level == "county":
            return "county", self.county(meta)
        if level == "zip":
            z = (meta.get("RegionName") or "").split(".")[0]
            return ("zip", z.zfill(5)) if z.isdigit() else (None, None)
        return None, None


def run(ctx):
    con = ctx.con
    scfg = ctx.source_cfg("zillow")
    levels = ctx.levels("zillow")
    extended = scfg.get("extended", True)
    want = []
    for metric, d, stem, lvls, kind in DATASETS:
        if metric in EXTENDED and not extended:
            continue
        for lv in lvls:
            if lv in levels or (lv == "metro" and "us" in levels):
                want.append((metric, d, stem, lv, kind))

    # ---- phase 1: downloads ----
    files = {}
    failed = []
    for i, (metric, d, stem, lv, kind) in enumerate(want):
        if ctx.cancelled():
            raise RuntimeError("cancelled")
        ctx.report("Zillow: downloading %s (%s) [%d/%d]" % (metric, lv, i + 1, len(want)))
        res = ctx.dl.fetch("zillow_%s_%s" % (metric, lv), url_for(d, lv, stem), "zillow",
                           quiet_missing=(lv in ("state", "county") and metric not in ("zhvi",)))
        if res.ok:
            files[(metric, lv)] = res
        elif res.status == "missing" and lv in ("state", "county") and metric != "zhvi":
            pass  # not every Zillow dataset exists for every geography
        else:
            failed.append("%s/%s: %s" % (metric, lv, res.error or res.status))

    if ctx.unchanged("zillow", list(files.values())):
        return {"unchanged": True, "ok": True, "message": "unchanged"}

    # ---- phase 2: parse & store ----
    resolver = Resolver(ctx)
    # County ZHVI first: teaches us how Zillow names metros (vote by county membership).
    if ("zhvi", "county") in files:
        for meta, start, vals in iter_wide(files[("zhvi", "county")].path):
            fips = resolver.county(meta)
            if fips:
                resolver.learn_from_county(meta, fips)
        resolver.finalize_votes()
    # Zillow metro names -> CBSA aliases (shared with other sources).
    order = sorted(files.keys(), key=lambda k: (0 if k == ("zhvi", "county") else 1))
    con.execute("BEGIN")
    stats = {}
    latest = None
    try:
        w = SeriesWriter(con, "zillow")
        for metric, lv in order:
            res = files[(metric, lv)]
            kind = next(d[4] for d in DATASETS if d[0] == metric)
            ctx.report("Zillow: loading %s (%s)" % (metric, lv))
            rows = []
            try:
                if kind == "forecast":
                    vals_all = []
                    for meta, base, v in iter_forecast(res.path):
                        level, gid = resolver.resolve(lv, meta)
                        if gid and v == v:
                            rows.append((level, gid, base, [v]))
                            vals_all.append(v)
                    scale = 100.0 if (vals_all and max(abs(x) for x in vals_all) < 0.5) else 1.0
                    if scale != 1.0:
                        rows = [(a, b, c, [x * scale for x in d]) for a, b, c, d in rows]
                else:
                    sample = []
                    for meta, start, vals in iter_wide(res.path):
                        level, gid = resolver.resolve(lv, meta)
                        if not gid:
                            continue
                        rows.append((level, gid, start, vals))
                        if kind == "share" and len(sample) < 20000:
                            sample.extend(v for v in vals[-24:] if v == v)
                        if lv == "zip" and metric == "zhvi":
                            city = meta.get("City") or None
                            st = state_abbr(meta.get("State") or meta.get("StateName"))
                            if city or st:
                                upsert_geo(con, "zip", gid, city=city, state=st)
                    if kind == "share":
                        scale = pct_scale(sample)
                        if scale != 1.0:
                            rows = [(a, b, c, [x * scale for x in d]) for a, b, c, d in rows]
            except Exception as e:
                log.exception("  failed to parse %s", res.path)
                failed.append("%s/%s parse error: %s" % (metric, lv, e))
                continue
            if not rows:
                failed.append("%s/%s: no rows recognized" % (metric, lv))
                continue
            levels_in = {r[0] for r in rows}
            for level in levels_in:
                con.execute("DELETE FROM series WHERE metric=? AND level=? AND src='zillow'", (metric, level))
            seen = set()
            for level, gid, start, vals in rows:
                if (level, gid) in seen:
                    continue  # duplicate region rows (rare) - keep the first (largest SizeRank first)
                seen.add((level, gid))
                w.put(metric, level, gid, "M", start, vals)
                s, v = trim(start, vals)
                if s is not None and metric == "zhvi":
                    end = s + len(v) - 1
                    latest = max(latest or end, end)
            w.flush()
            stats["%s/%s" % (metric, lv)] = len(seen)
        # Remember Zillow's metro spellings for other sources (Redfin uses similar names).
        con.executemany("INSERT OR REPLACE INTO xw(kind,a,b,w) VALUES('cbsa_alias',?,?,1)",
                        [(k, v) for k, v in resolver.metro_map.items() if v])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    if resolver.unmatched:
        log.info("  Zillow metros without a CBSA match (first 15): %s",
                 ", ".join(list(resolver.unmatched)[:15]))
    from ..util import midx_str
    msg = "%d datasets loaded" % len(stats)
    if failed:
        msg += "; %d problems" % len(failed)
    if not stats:
        msg += (". No files could be loaded. The provider may have moved its downloads - see the Data & Sources page for the URLs and paste new links under Settings > Advanced: download URL overrides.")
    return {"message": msg, "details": {"loaded": stats, "problems": failed[:50],
                                         "unmatched_metros": list(resolver.unmatched)[:50]},
            "ok": bool(stats), "latest": midx_str(latest) if latest else None,
            "warn": bool(failed)}
