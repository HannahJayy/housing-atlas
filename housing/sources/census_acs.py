"""U.S. Census Bureau American Community Survey (ACS) 5-year estimates.

Two download modes:
  * Census Data API (fast, needs a free key: https://api.census.gov/data/key_signup.html)
  * ACS table-based Summary Files (no key; each table file covers every geography)
"""

import json
import urllib.parse

from ..db import SeriesWriter, decode, trim
from ..geo.states import FIPS_TO_ABBR
from ..util import NAN, log, to_float
from .common import open_text, this_year, upsert_geo

API = "https://api.census.gov/data/{y}/acs/acs5"
SF = "https://www2.census.gov/programs-surveys/acs/summary_file/{y}/table-based-SF/data/5YRData/acsdt5y{y}-{t}.dat"

# table -> list of column numbers needed
TABLES = {
    "b01003": [1],            # total population
    "b19013": [1],            # median household income
    "b25077": [1],            # median home value (owner-occupied)
    "b25064": [1],            # median gross rent
    "b25001": [1],            # housing units
    "b25002": [1, 2, 3],      # occupancy: total, occupied, vacant
    "b25003": [1, 2, 3],      # tenure: total, owner, renter
    "b25004": [1, 2, 3, 4, 5, 6, 7, 8],  # vacancy status
    "b25081": [1, 2],         # mortgage status: total, with mortgage
    "b25103": [1],            # median real estate taxes paid
    "b01002": [1],            # median age
    "b17001": [1, 2],         # poverty: total, below
    "b25035": [1],            # median year built
    "b25071": [1],            # median gross rent as % of income
    "b25105": [1],            # median monthly housing costs
}

INFO = {
    "id": "census_acs",
    "name": "U.S. Census Bureau - American Community Survey 5-Year Estimates",
    "homepage": "https://www.census.gov/programs-surveys/acs/data/summary-file.html",
    "description": "Median household income, median home value & rent, housing units, vacancy (rental, "
                   "homeowner, seasonal, 'other vacant'), homeownership, share of homes with a mortgage, "
                   "property taxes, median age, poverty, year built and rent burden for every state, county, "
                   "metro and ZIP code (ZCTA).",
    "frequency": "Yearly (each December)",
    "metrics": ["acs_income", "acs_value", "acs_rent", "housing_units", "vacancy_rate", "homeownership",
                "rental_vacancy", "homeowner_vacancy", "seasonal_pct", "shadow_inventory", "mortgaged_pct",
                "property_tax_rate", "acs_taxes", "median_age", "poverty_rate", "median_year_built",
                "rent_burden_acs", "housing_costs", "population (ZIP)"],
    "license": "Public domain (U.S. Government work)",
}

SUMLEV = {"010": "us", "040": "state", "050": "county", "310": "metro", "860": "zip"}


def file_list(cfg):
    y = this_year() - 2
    if cfg.get("census_api_key"):
        return [{"key": "acs_api", "url": API.format(y=y) + "?get=...&key=YOUR_KEY", "desc": "ACS 5-year via API"}]
    return [{"key": "acs_sf_%s" % t, "url": SF.format(y=y, t=t), "desc": "ACS table %s" % t.upper()} for t in TABLES]


def _geo_from_geoid(geoid):
    sl = geoid[:3]
    level = SUMLEV.get(sl)
    if not level:
        return None, None
    code = geoid.split("US", 1)[1] if "US" in geoid else ""
    if level == "us":
        return "us", "US"
    if level == "state":
        st = FIPS_TO_ABBR.get(code[:2])
        return ("state", st) if st else (None, None)
    if level in ("county", "metro", "zip"):
        return (level, code[:5]) if len(code) >= 5 else (None, None)
    return None, None


def _val(s):
    v = to_float(s)
    if v != v or v <= -100000000:
        return NAN
    return v


def load_summary_files(ctx, year):
    """Returns {(level, gid): {var: value}} where var like 'b25004_3'."""
    raw = {}
    for i, (t, cols) in enumerate(TABLES.items()):
        if ctx.cancelled():
            raise RuntimeError("cancelled")
        ctx.report("Census ACS: downloading table %s [%d/%d] (no API key -> summary files)" % (
            t.upper(), i + 1, len(TABLES)))
        res = ctx.dl.fetch("acs_sf_%s" % t, SF.format(y=year, t=t), "census_acs")
        if not res.ok:
            log.warning("  ACS table %s unavailable: %s", t, res.error)
            continue
        with open_text(res.path) as f:
            header = f.readline().rstrip("\r\n").split("|")
            hidx = {h.strip().upper(): j for j, h in enumerate(header)}
            gi = hidx.get("GEO_ID", 0)
            want = []
            for c in cols:
                name = "%s_E%03d" % (t.upper(), c)
                if name in hidx:
                    want.append((hidx[name], "%s_%d" % (t, c)))
            if not want:
                log.warning("  ACS table %s: expected columns not found (header %s)", t, header[:4])
                continue
            for line in f:
                if line[:3] not in SUMLEV:
                    continue
                p = line.rstrip("\r\n").split("|")
                level, gid = _geo_from_geoid(p[gi])
                if not gid:
                    continue
                d = raw.setdefault((level, gid), {})
                for j, var in want:
                    if j < len(p):
                        d[var] = _val(p[j])
    return raw


def load_api(ctx, year, key):
    raw = {}
    variables = []
    for t, cols in TABLES.items():
        for c in cols:
            variables.append(("%s_%03dE" % (t.upper(), c), "%s_%d" % (t, c)))
    geos = [("us", "us:1"), ("state", "state:*"), ("county", "county:*"),
            ("metro", "metropolitan statistical area/micropolitan statistical area:*"),
            ("zip", "zip code tabulation area:*")]
    chunks = [variables[i:i + 45] for i in range(0, len(variables), 45)]
    for level, forclause in geos:
        for chunk in chunks:
            if ctx.cancelled():
                raise RuntimeError("cancelled")
            q = urllib.parse.urlencode({"get": ",".join(v for v, _ in chunk), "for": forclause, "key": key})
            url = API.format(y=year) + "?" + q
            ctx.report("Census ACS API: %s (%d variables)" % (level, len(chunk)))
            text, res = ctx.dl.get_text("acs_api", url, "census_acs",
                                        dest_name="acs%s_%s_%d.json" % (year, level, chunks.index(chunk)))
            if not text:
                raise RuntimeError("ACS API request failed (%s). Check your Census API key." % (res.error,))
            try:
                rows = json.loads(text)
            except ValueError:
                raise RuntimeError("ACS API returned non-JSON (invalid key?): %s" % text[:200])
            header = rows[0]
            hidx = {h: i for i, h in enumerate(header)}
            for r in rows[1:]:
                if level == "us":
                    gid = "US"
                elif level == "state":
                    gid = FIPS_TO_ABBR.get(r[hidx["state"]])
                elif level == "county":
                    gid = r[hidx["state"]] + r[hidx["county"]]
                elif level == "metro":
                    gid = r[hidx[header[-1]]]
                else:
                    gid = r[hidx[header[-1]]]
                if not gid:
                    continue
                d = raw.setdefault((level, gid), {})
                for v, var in chunk:
                    if v in hidx:
                        d[var] = _val(r[hidx[v]])
    return raw


def _ratio(a, b, scale=100.0):
    if a is None or b is None or a != a or b != b or b <= 0:
        return NAN
    return scale * a / b


def derive(d):
    g = d.get
    out = {
        "acs_population": g("b01003_1", NAN),
        "acs_income": g("b19013_1", NAN),
        "acs_value": g("b25077_1", NAN),
        "acs_rent": g("b25064_1", NAN),
        "housing_units": g("b25001_1", NAN),
        "vacancy_rate": _ratio(g("b25002_3"), g("b25002_1")),
        "homeownership": _ratio(g("b25003_2"), g("b25003_1")),
        "mortgaged_pct": _ratio(g("b25081_2"), g("b25081_1")),
        "acs_taxes": g("b25103_1", NAN),
        "property_tax_rate": _ratio(g("b25103_1"), g("b25077_1")),
        "median_age": g("b01002_1", NAN),
        "poverty_rate": _ratio(g("b17001_2"), g("b17001_1")),
        "median_year_built": g("b25035_1", NAN),
        "rent_burden_acs": g("b25071_1", NAN),
        "housing_costs": g("b25105_1", NAN),
        "seasonal_pct": _ratio(g("b25004_6"), g("b25001_1") or g("b25002_1")),
        "shadow_inventory": _ratio(g("b25004_8"), g("b25001_1") or g("b25002_1")),
    }
    renter = g("b25003_3")
    owner = g("b25003_2")
    for_rent, rented = g("b25004_2"), g("b25004_3")
    for_sale, sold = g("b25004_4"), g("b25004_5")
    if renter is not None and for_rent is not None:
        out["rental_vacancy"] = _ratio(for_rent, renter + for_rent + (rented or 0))
    if owner is not None and for_sale is not None:
        out["homeowner_vacancy"] = _ratio(for_sale, owner + for_sale + (sold or 0))
    if out["median_year_built"] == out["median_year_built"] and out["median_year_built"] < 1900:
        out["median_year_built"] = NAN  # 0 / sentinel values
    return out


def _find_year(ctx, key):
    cfg_year = ctx.source_cfg("census_acs").get("year")
    if cfg_year:
        return int(cfg_year)
    for y in range(this_year() - 1, this_year() - 6, -1):
        if key:
            url = API.format(y=y) + "?" + urllib.parse.urlencode({"get": "NAME", "for": "us:1", "key": key})
            text, res = ctx.dl.get_text("acs_api_probe", url, "census_acs", dest_name="probe_%d.json" % y)
            if text and text.strip().startswith("["):
                return y
        else:
            if ctx.dl.exists("acs_sf_b01003", SF.format(y=y, t="b01003")):
                return y
    return None


def run(ctx):
    con = ctx.con
    key = (ctx.cfg.get("census_api_key") or "").strip()
    mode = ctx.source_cfg("census_acs").get("mode", "auto")
    use_api = bool(key) and mode in ("auto", "api")
    year = _find_year(ctx, key if use_api else None)
    if not year:
        raise RuntimeError("Could not find a published ACS 5-year release")
    ctx.report("Census ACS: using %d 5-year estimates (%s)" % (year, "API" if use_api else "summary files"))
    raw = load_api(ctx, year, key) if use_api else load_summary_files(ctx, year)
    if not raw:
        raise RuntimeError("No ACS data parsed")

    # Merge into existing history (each yearly run adds a point).
    con.execute("BEGIN")
    try:
        existing = {}
        for metric, level, gid, freq, start, blob in con.execute(
                "SELECT metric, level, geo_id, freq, start, vals FROM series WHERE src='census_acs'"):
            existing[(metric, level, gid)] = (start, decode(blob))
        con.execute("DELETE FROM series WHERE src='census_acs'")
        w = SeriesWriter(con, "census_acs")
        written = set()
        n = 0
        for (level, gid), d in raw.items():
            vals = derive(d)
            for metric, v in vals.items():
                if v != v:
                    continue
                mname = metric
                if metric == "acs_population":
                    if level != "zip":
                        continue
                    mname = "population"
                pts = {}
                old = existing.get((mname, level, gid))
                if old:
                    for i, ov in enumerate(old[1]):
                        if ov == ov:
                            pts[old[0] + i] = ov
                pts[year] = v
                lo, hi = min(pts), max(pts)
                arr = [NAN] * (hi - lo + 1)
                for k, x in pts.items():
                    arr[k - lo] = x
                w.put(mname, level, gid, "A", lo, arr)
                written.add((mname, level, gid))
                n += 1
            if level == "zip":
                pop = vals.get("acs_population")
                if pop == pop:
                    upsert_geo(con, "zip", gid, population=pop)
        # keep older history for regions/metrics not present this time
        for (metric, level, gid), (start, vals) in existing.items():
            if (metric, level, gid) not in written:
                w.put(metric, level, gid, "A", start, vals)
        w.flush()
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    levels = {}
    for (level, gid) in raw:
        levels[level] = levels.get(level, 0) + 1
    return {"message": "ACS %d: %d regions (%s)" % (year, len(raw), ", ".join("%s %d" % kv for kv in levels.items())),
            "details": {"year": year, "mode": "api" if use_api else "summary_files", "regions": levels},
            "ok": n > 0, "latest": str(year)}
