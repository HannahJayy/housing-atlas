"""Federal Housing Finance Agency (FHFA) House Price Index - repeat-sales index for the U.S.,
states and metro areas. https://www.fhfa.gov/data/hpi/datasets"""

import csv
import io

from ..db import SeriesWriter
from ..geo.states import state_abbr
from ..util import log, midx, to_float
from .common import read_text

URL = "https://www.fhfa.gov/hpi/download/monthly/hpi_master.csv"

INFO = {
    "id": "fhfa",
    "name": "FHFA House Price Index (HPI)",
    "homepage": "https://www.fhfa.gov/data/hpi/datasets",
    "description": "Repeat-sales house price index (Fannie Mae / Freddie Mac mortgages): monthly purchase-only "
                   "index for the U.S., and quarterly indexes for states and ~400 metro areas.",
    "frequency": "Monthly (last Tuesday) / quarterly",
    "metrics": ["fhfa_hpi"],
    "license": "Public domain (U.S. Government work)",
}


def file_list(cfg):
    return [{"key": "fhfa_master", "url": URL, "desc": "HPI master file (all indexes)"}]


def run(ctx):
    ctx.report("FHFA: downloading House Price Index master file")
    res = ctx.dl.fetch("fhfa_master", URL, "fhfa")
    if not res.ok:
        raise RuntimeError("FHFA download failed: %s" % (res.error or res.status))
    if ctx.unchanged("fhfa", [res]):
        return {"unchanged": True, "ok": True, "message": "unchanged"}
    text = read_text(res.path)
    rdr = csv.DictReader(io.StringIO(text))
    # (level, gid) -> {(rank, freq): {period: value}}
    cands = {}
    for r in rdr:
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        typ, flavor, freq, lvl = r.get("hpi_type", ""), r.get("hpi_flavor", ""), r.get("frequency", ""), r.get("level", "")
        if typ != "traditional":
            continue
        pid = r.get("place_id", "")
        lvl_l = lvl.lower()
        if lvl_l.startswith("usa"):
            if pid.upper() not in ("USA", "USA0", "US"):
                continue
            level, gid = "us", "US"
        elif lvl_l == "state":
            level, gid = "state", state_abbr(pid)
        elif lvl_l == "msa":
            level, gid = "metro", ctx.geo.cbsa_code(code=pid) if pid.isdigit() else None
            if gid and pid.zfill(5) != gid:
                continue  # skip metropolitan divisions
        else:
            continue
        if not gid:
            continue
        try:
            yr = int(r.get("yr"))
            per = int(r.get("period"))
        except (TypeError, ValueError):
            continue
        v = to_float(r.get("index_sa"))
        if v != v:
            v = to_float(r.get("index_nsa"))
        if v != v:
            continue
        rank = (0 if flavor == "purchase-only" else 1, 0 if freq == "monthly" else 1)
        f = "M" if freq == "monthly" else "Q"
        idx = midx(yr, per) if f == "M" else yr * 4 + per - 1
        cands.setdefault((level, gid), {}).setdefault((rank, f), {})[idx] = v
    con = ctx.con
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM series WHERE src='fhfa'")
        w = SeriesWriter(con, "fhfa")
        n = 0
        for (level, gid), opts in cands.items():
            (rank, f), pts = sorted(opts.items(), key=lambda kv: kv[0][0])[0]
            lo, hi = min(pts), max(pts)
            w.put("fhfa_hpi", level, gid, f, lo, [pts.get(i, float("nan")) for i in range(lo, hi + 1)])
            n += 1
        w.flush()
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return {"message": "%d index series" % n, "details": {"series": n}, "ok": n > 0}
