"""U.S. Census Bureau Population Estimates Program (PEP): population & migration for
states, counties and metros, plus the official county -> metro (CBSA) crosswalk."""

import re

from ..geo.states import FIPS_TO_ABBR
from ..util import NAN, log, norm_county, short_metro_name, to_float
from .common import Store, csv_dicts, newest_available, replace_source_series, this_year, upsert_geo

BASE = "https://www2.census.gov/programs-surveys/popest/datasets"
COUNTY_URL = BASE + "/2020-{y}/counties/totals/co-est{y}-alldata.csv"
METRO_URL = BASE + "/2020-{y}/metro/totals/cbsa-est{y}-alldata.csv"
COUNTY_2019 = BASE + "/2010-2019/counties/totals/co-est2019-alldata.csv"
METRO_2019 = BASE + "/2010-2019/metro/totals/cbsa-est2019-alldata.csv"
HU_URL = "https://www2.census.gov/programs-surveys/popest/tables/2020-{y}/housing/totals/CO-EST{y}-HU.xlsx"

INFO = {
    "id": "census_pep",
    "name": "U.S. Census Bureau - Population Estimates (PEP)",
    "homepage": "https://www.census.gov/programs-surveys/popest/data/data-sets.html",
    "description": "Annual July 1 population estimates and the components of change (net, domestic and "
                   "international migration) for every state, county and metro area, plus annual county "
                   "housing-unit estimates (the housing-stock growth rate); also provides the official list of "
                   "counties that make up each metro area.",
    "frequency": "Yearly (population each March; housing units each May)",
    "metrics": ["population", "net_migration", "domestic_migration", "intl_migration", "migration_rate",
                "natural_change", "housing_units_est"],
    "license": "Public domain (U.S. Government work)",
}


def file_list(cfg):
    y = this_year() - 1
    return [
        {"key": "pep_county", "url": COUNTY_URL.format(y=y), "desc": "County & state totals (newest vintage found)"},
        {"key": "pep_metro", "url": METRO_URL.format(y=y), "desc": "Metro/micro totals + county membership"},
        {"key": "pep_county_2019", "url": COUNTY_2019, "desc": "2010-2019 county history"},
        {"key": "pep_metro_2019", "url": METRO_2019, "desc": "2010-2019 metro history"},
        {"key": "pep_housing_units", "url": HU_URL.format(y=y), "desc": "County housing unit estimates (XLSX)"},
    ]


def load_housing_units(ctx, vintage, store):
    """CO-EST{V}-HU.xlsx: '.Autauga County, Alabama' rows x years -> housing_units_est (summed upward)."""
    from .xlsx import read_rows
    from ..geo.states import NAME_TO_ABBR
    from ..util import norm_name
    res = None
    for y in (vintage, vintage - 1):
        res = ctx.dl.fetch("pep_housing_units", HU_URL.format(y=y), "census_pep", quiet_missing=True)
        if res.ok:
            break
    if not res or not res.ok:
        return 0
    rows = read_rows(res.path)
    header_i, years = None, {}
    def as_year(v):
        if isinstance(v, float) and v == int(v) and 2000 <= v <= 2100:
            return int(v)
        if isinstance(v, str) and v.strip().isdigit() and 2000 <= int(v.strip()) <= 2100:
            return int(v.strip())
        return None
    for i, r in enumerate(rows[:15]):
        ys = {j: as_year(v) for j, v in enumerate(r) if as_year(v)}
        if len(ys) >= 2:
            header_i, years = i, ys
            break
    if header_i is None:
        log.warning("  housing unit table: year header not found")
        return 0
    agg = {}
    n = 0
    for r in rows[header_i + 1:]:
        if not r or not isinstance(r[0], str) or not r[0].startswith("."):
            continue
        name = r[0].lstrip(".").strip()
        if "," not in name:
            continue
        county, state = name.rsplit(",", 1)
        st = NAME_TO_ABBR.get(norm_name(state))
        fips = ctx.geo.county_fips(county, st) if st else None
        if not fips:
            continue
        for j, y in years.items():
            v = r[j] if j < len(r) else None
            if isinstance(v, float):
                store.add("housing_units_est", "county", fips, y, v)
                n += 1
                keys = [("us", "US"), ("state", st)]
                if fips in ctx.geo.county_cbsa:
                    keys.append(("metro", ctx.geo.county_cbsa[fips]))
                for k in keys:
                    agg[(k, y)] = agg.get((k, y), 0.0) + v
    for ((lv, gid), y), v in agg.items():
        store.add("housing_units_est", lv, gid, y, v)
    return n


COMPONENTS = {
    "POPESTIMATE": "population",
    "NETMIG": "net_migration",
    "DOMESTICMIG": "domestic_migration",
    "INTERNATIONALMIG": "intl_migration",
    "NATURALCHG": "natural_change",
}


def _year_cols(header):
    out = []
    for h in header:
        m = re.match(r"^(POPESTIMATE|NETMIG|DOMESTICMIG|INTERNATIONALMIG|NATURALCHG)(\d{4})$", h.strip().upper())
        if m:
            out.append((h, COMPONENTS[m.group(1)], int(m.group(2))))
    return out


def _add_row(store, level, gid, row, ycols, first_component_year):
    for col, metric, year in ycols:
        if metric != "population" and year < first_component_year:
            continue  # partial-year components (e.g. Apr-Jul 2020)
        store.add(metric, level, gid, year, to_float(row.get(col)))


def run(ctx):
    con = ctx.con
    store = Store("A")
    details = {}
    years = list(range(this_year(), this_year() - 5, -1))
    vy, county_url = newest_available(ctx, "pep_county", COUNTY_URL, years)
    if not county_url:
        raise RuntimeError("Could not find a Census population estimates county file")
    details["vintage"] = vy

    # --- history 2010-2019 first (newer data overwrites overlapping years) ---
    for key, url, kind in (("pep_county_2019", COUNTY_2019, "county"), ("pep_metro_2019", METRO_2019, "metro")):
        res = ctx.dl.fetch(key, url, "census_pep")
        if not res.ok:
            continue
        header, rows = csv_dicts(res.path)
        ycols = _year_cols(header)
        for r in rows:
            if kind == "county":
                sl = (r.get("SUMLEV") or "").strip().zfill(3)
                if sl == "050":
                    gid = r["STATE"].zfill(2) + r["COUNTY"].zfill(3)
                    _add_row(store, "county", gid, r, ycols, 2011)
                elif sl == "040":
                    st = FIPS_TO_ABBR.get(r["STATE"].zfill(2))
                    if st:
                        _add_row(store, "state", st, r, ycols, 2011)
            else:
                lsad = (r.get("LSAD") or "").lower()
                if "statistical area" in lsad and "combined" not in lsad:
                    _add_row(store, "metro", (r.get("CBSA") or "").strip().zfill(5), r, ycols, 2011)

    # --- current vintage: counties & states ---
    res = ctx.dl.fetch("pep_county", county_url, "census_pep")
    if not res.ok:
        raise RuntimeError("Download failed: %s" % county_url)
    header, rows = csv_dicts(res.path)
    ycols = _year_cols(header)
    aliases = []
    con.execute("BEGIN")
    for r in rows:
        sl = (r.get("SUMLEV") or "").strip().zfill(3)
        stf = (r.get("STATE") or "").strip().zfill(2)
        st = FIPS_TO_ABBR.get(stf)
        if not st:
            continue
        if sl == "040":
            _add_row(store, "state", st, r, ycols, 2021)
            upsert_geo(con, "state", st, name=r.get("STNAME"), full_name=r.get("STNAME"), state=st)
        elif sl == "050":
            gid = stf + (r.get("COUNTY") or "").zfill(3)
            _add_row(store, "county", gid, r, ycols, 2021)
            cname = (r.get("CTYNAME") or "").strip()
            upsert_geo(con, "county", gid, name="%s, %s" % (cname, st), full_name="%s, %s" % (cname, st), state=st)
            aliases.append(("%s|%s" % (st, norm_county(cname)), gid))
    con.executemany("INSERT OR REPLACE INTO xw(kind,a,b,w) VALUES('county_alias',?,?,1)", aliases)
    con.execute("COMMIT")

    # --- metros + crosswalks ---
    my, metro_url = newest_available(ctx, "pep_metro", METRO_URL, [vy] + [y for y in years if y != vy])
    county_cbsa, mdiv_cbsa = {}, {}
    if metro_url:
        res = ctx.dl.fetch("pep_metro", metro_url, "census_pep")
        if res.ok:
            header, rows = csv_dicts(res.path)
            ycols = _year_cols(header)
            con.execute("BEGIN")
            for r in rows:
                lsad = (r.get("LSAD") or "").strip().lower()
                cbsa = (r.get("CBSA") or "").strip().zfill(5)
                if not cbsa.strip("0"):
                    continue
                if lsad in ("metropolitan statistical area", "micropolitan statistical area"):
                    _add_row(store, "metro", cbsa, r, ycols, 2021)
                    full = (r.get("NAME") or "").strip()
                    st = None
                    if "," in full:
                        st = full.rsplit(",", 1)[1].strip().split("-")[0]
                    upsert_geo(con, "metro", cbsa, name=short_metro_name(full), full_name=full,
                               lsad="metro" if lsad.startswith("metro") else "micro", state=st)
                elif lsad == "metropolitan division":
                    md = (r.get("MDIV") or "").strip().zfill(5)
                    if md.strip("0"):
                        mdiv_cbsa[md] = cbsa
                elif lsad.startswith("county"):
                    stcou = (r.get("STCOU") or "").strip().zfill(5)
                    if stcou.strip("0"):
                        county_cbsa[stcou] = cbsa
            con.execute("DELETE FROM xw WHERE kind IN ('county_cbsa','mdiv_cbsa')")
            con.executemany("INSERT OR REPLACE INTO xw(kind,a,b,w) VALUES('county_cbsa',?,?,1)", list(county_cbsa.items()))
            con.executemany("INSERT OR REPLACE INTO xw(kind,a,b,w) VALUES('mdiv_cbsa',?,?,1)", list(mdiv_cbsa.items()))
            con.execute("UPDATE geos SET metro_id=(SELECT b FROM xw WHERE kind='county_cbsa' AND a=geos.geo_id) "
                        "WHERE level='county'")
            con.execute("UPDATE geos SET metro_id=(SELECT g.metro_id FROM geos g WHERE g.level='county' "
                        "AND g.geo_id=geos.county_id) WHERE level='zip'")
            con.execute("COMMIT")
            details["metro_vintage"] = my
    details["counties_in_metros"] = len(county_cbsa)

    # --- U.S. totals = sum of states; migration rate per 100 residents ---
    st_data = store.data
    pop = st_data.get("population", {})
    for metric in ("population", "net_migration", "domestic_migration", "intl_migration", "natural_change"):
        states = st_data.get(metric, {}).get("state", {})
        tot = {}
        cnt = {}
        for gid, pts in states.items():
            for y, v in pts.items():
                tot[y] = tot.get(y, 0.0) + v
                cnt[y] = cnt.get(y, 0) + 1
        for y, v in tot.items():
            if cnt[y] >= 50:
                store.add(metric, "us", "US", y, v)
    for level, geos in st_data.get("net_migration", {}).items():
        for gid, pts in geos.items():
            ppts = pop.get(level, {}).get(gid, {})
            for y, v in pts.items():
                p = ppts.get(y)
                if p:
                    store.add("migration_rate", level, gid, y, 100.0 * v / p)

    # latest population onto the geos table (used for filters & weighting)
    con.execute("BEGIN")
    for level, geos in pop.items():
        for gid, pts in geos.items():
            if pts:
                y = max(pts)
                upsert_geo(con, level, gid)
                con.execute("UPDATE geos SET population=? WHERE level=? AND geo_id=?", (pts[y], level, gid))
    con.execute("COMMIT")

    ctx.geo.reload()
    try:
        hu = load_housing_units(ctx, vy, store)
        details["housing_unit_values"] = hu
    except Exception as e:
        log.warning("  housing unit estimates failed: %s", e)
    n = replace_source_series(con, "census_pep", [(store, "A")])
    ctx.geo.reload()
    details["series"] = n
    return {"message": "Vintage %s: %d series; %d counties mapped to metros" % (vy, n, len(county_cbsa)),
            "details": details, "ok": n > 0, "latest": str(vy)}
