"""Bureau of Economic Analysis (BEA) - personal income by county, metro and state (CAINC1).
Used for long-run income history (1969+), which anchors the overvaluation model."""

import csv
import io
import json
import zipfile

from ..geo.states import FIPS_TO_ABBR
from ..util import log, to_float
from .common import Store, replace_source_series

ZIP_URL = "https://apps.bea.gov/regional/zip/CAINC1.zip"
API_URL = ("https://apps.bea.gov/api/data/?UserID={key}&method=GetData&datasetname=Regional"
           "&TableName=CAINC1&LineCode=3&GeoFips={geo}&Year=ALL&ResultFormat=json")

INFO = {
    "id": "bea",
    "name": "U.S. Bureau of Economic Analysis - Personal Income (CAINC1)",
    "homepage": "https://apps.bea.gov/regional/downloadzip.htm",
    "description": "Per-capita personal income for every county, metro and state since 1969. Its growth rate "
                   "extends Census median household income back (and forward) in time, which powers the "
                   "income-based overvaluation and affordability history.",
    "frequency": "Yearly (counties/metros each November; states quarterly)",
    "metrics": ["pcpi", "personal_income"],
    "license": "Public domain (U.S. Government work)",
}


def file_list(cfg):
    return [{"key": "bea_cainc1", "url": ZIP_URL, "desc": "CAINC1 all areas (zipped CSV)"}]


def _classify(fips, name):
    f = fips.strip().strip('"').strip()
    if not f.isdigit():
        return None, None
    f = f.zfill(5)
    if f == "00000":
        return "us", "US"
    nm = name or ""
    if "Metropolitan Statistical Area" in nm or "Micropolitan Statistical Area" in nm:
        return "metro", f
    if "Combined Statistical Area" in nm or "Metropolitan Portion" in nm or "Nonmetropolitan" in nm:
        return None, None
    if f.endswith("000"):
        st = FIPS_TO_ABBR.get(f[:2])
        return ("state", st) if st else (None, None)
    if f[:2] in FIPS_TO_ABBR:
        return "county", f
    return None, None


def parse_zip(path, store):
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        all_areas = [n for n in names if "ALL_AREAS" in n.upper()]
        targets = all_areas or names
        n = 0
        for name in targets:
            raw = z.read(name)
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            rdr = csv.reader(io.StringIO(text))
            header = [h.strip() for h in next(rdr)]
            hidx = {h: i for i, h in enumerate(header)}
            years = [(i, int(h)) for i, h in enumerate(header) if h.isdigit() and len(h) == 4]
            gi, ni, li = hidx.get("GeoFIPS"), hidx.get("GeoName"), hidx.get("LineCode")
            if gi is None or li is None:
                continue
            for r in rdr:
                if len(r) <= li:
                    continue
                lc = r[li].strip()
                if lc not in ("1", "3"):
                    continue
                level, gid = _classify(r[gi], r[ni] if ni is not None else "")
                if not gid:
                    continue
                metric = "pcpi" if lc == "3" else "personal_income"
                for i, y in years:
                    if i < len(r):
                        v = to_float(r[i])
                        if v == v:
                            if metric == "personal_income":
                                v *= 1000.0
                            store.add(metric, level, gid, y, v)
                            n += 1
        return n


def parse_api(ctx, key, store):
    n = 0
    for geo in ("STATE", "COUNTY", "MSA"):
        text, res = ctx.dl.get_text("bea_api", API_URL.format(key=key, geo=geo), "bea",
                                    dest_name="cainc1_%s.json" % geo.lower())
        if not text:
            continue
        try:
            data = json.loads(text)["BEAAPI"]["Results"]["Data"]
        except Exception:
            log.warning("  unexpected BEA API response for %s", geo)
            continue
        for d in data:
            level, gid = _classify(d.get("GeoFips", ""), d.get("GeoName", "") + (
                " (Metropolitan Statistical Area)" if geo == "MSA" else ""))
            if not gid:
                continue
            try:
                y = int(str(d.get("TimePeriod"))[:4])
            except ValueError:
                continue
            v = to_float(d.get("DataValue"))
            if v == v:
                store.add("pcpi", level, gid, y, v)
                n += 1
    return n


def run(ctx):
    store = Store("A")
    ctx.report("BEA: downloading county/metro personal income (CAINC1)")
    res = ctx.dl.fetch("bea_cainc1", ZIP_URL, "bea")
    if ctx.unchanged("bea", [res]):
        return {"unchanged": True, "ok": True, "message": "unchanged"}
    n = 0
    if res.ok:
        try:
            n = parse_zip(res.path, store)
        except Exception as e:
            log.warning("  CAINC1 zip parse failed: %s", e)
    key = (ctx.cfg.get("bea_api_key") or "").strip()
    if n == 0 and key:
        ctx.report("BEA: zip unavailable, using BEA API")
        n = parse_api(ctx, key, store)
    if n == 0:
        raise RuntimeError("BEA personal income could not be downloaded (%s). Optional: add a free BEA API key "
                           "in Settings." % (res.error or res.status))
    latest = max((y for lv in store.data.get("pcpi", {}).values() for pts in lv.values() for y in pts), default=None)
    cnt = replace_source_series(ctx.con, "bea", [(store, "A")])
    return {"message": "%d series through %s" % (cnt, latest), "details": {"latest_year": latest},
            "ok": cnt > 0, "latest": str(latest)}
