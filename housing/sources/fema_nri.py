"""FEMA National Risk Index - county natural-hazard risk (optional; off by default).
If FEMA moves the file, paste the current 'Counties (Table)' CSV link from
https://hazards.fema.gov/nri/data-resources into Settings > URL overrides (key: fema_nri_counties)."""

import csv
import io
import zipfile

from ..db import SeriesWriter
from ..util import log, to_float
from .common import this_year

URL = "https://hazards.fema.gov/nri/Content/StaticDocuments/DataDownload//NRI_Table_Counties/NRI_Table_Counties.zip"

COLS = {
    "RISK_SCORE": "nri_risk",
    "EAL_VALT": "nri_eal",
    "HRCN_RISKS": "nri_hurricane",
    "WFIR_RISKS": "nri_wildfire",
    "RFLD_RISKS": "nri_flood",
    "CFLD_RISKS": "nri_coastal_flood",
    "HWAV_RISKS": "nri_heat",
    "TRND_RISKS": "nri_tornado",
    "ERQK_RISKS": "nri_earthquake",
}

INFO = {
    "id": "fema_nri",
    "name": "FEMA National Risk Index (optional)",
    "homepage": "https://hazards.fema.gov/nri/data-resources",
    "description": "County natural-hazard risk scores (overall, hurricane, wildfire, flooding, heat, tornado, "
                   "earthquake) and expected annual losses - useful context for insurance costs. Disabled by "
                   "default; enable it in Settings.",
    "frequency": "Roughly yearly",
    "metrics": sorted(COLS.values()),
    "license": "Public domain (U.S. Government work)",
}


def file_list(cfg):
    return [{"key": "fema_nri_counties", "url": URL, "desc": "NRI county table (zipped CSV)"}]


def run(ctx):
    ctx.report("FEMA: downloading National Risk Index")
    res = ctx.dl.fetch("fema_nri_counties", URL, "fema_nri")
    if not res.ok:
        raise RuntimeError("Download failed (%s). Check the current link on https://hazards.fema.gov/nri/data-resources"
                           % (res.error or res.status))
    rows = []
    with zipfile.ZipFile(res.path) as z:
        name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
        if not name:
            raise RuntimeError("No CSV inside NRI zip")
        text = z.read(name).decode("utf-8-sig", "replace")
    rdr = csv.DictReader(io.StringIO(text))
    year = this_year()
    con = ctx.con
    con.execute("BEGIN")
    con.execute("DELETE FROM series WHERE src='fema_nri'")
    w = SeriesWriter(con, "fema_nri")
    n = 0
    for r in rdr:
        fips = (r.get("STCOFIPS") or "").strip().zfill(5)
        if not fips.isdigit():
            continue
        for col, metric in COLS.items():
            v = to_float(r.get(col))
            if v == v:
                w.put(metric, "county", fips, "A", year, [v])
                n += 1
    w.flush()
    con.execute("COMMIT")
    return {"message": "%d values" % n, "ok": n > 0}
