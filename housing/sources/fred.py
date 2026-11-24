"""Federal Reserve Bank of St. Louis (FRED) - national housing & macro series.
CSV downloads need no API key: https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES"""

import json
import time

from ..db import SeriesWriter, now_str
from ..util import log, midx, parse_month, to_float

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"

# sid, name, units, category
SERIES = [
    ("MORTGAGE30US", "30-Year Fixed Mortgage Rate (Freddie Mac PMMS)", "%", "Mortgage rates & credit"),
    ("MORTGAGE15US", "15-Year Fixed Mortgage Rate (Freddie Mac PMMS)", "%", "Mortgage rates & credit"),
    ("DGS10", "10-Year Treasury Yield (monthly avg)", "%", "Mortgage rates & credit"),
    ("FEDFUNDS", "Effective Federal Funds Rate", "%", "Mortgage rates & credit"),
    ("DRSFRMACBS", "Delinquency Rate on Single-Family Mortgages (banks)", "%", "Mortgage rates & credit"),
    ("MDSP", "Mortgage Debt Service Payments (% of disposable income)", "%", "Mortgage rates & credit"),
    ("CSUSHPINSA", "Case-Shiller U.S. National Home Price Index (NSA)", "Index Jan2000=100", "Home prices"),
    ("CSUSHPISA", "Case-Shiller U.S. National Home Price Index (SA)", "Index Jan2000=100", "Home prices"),
    ("MSPUS", "Median Sales Price of Houses Sold (Census/HUD)", "USD", "Home prices"),
    ("MSPNHSUS", "Median Sales Price of New Houses Sold", "USD", "Home prices"),
    ("ACTLISCOUUS", "Active Listings - U.S. (Realtor.com)", "Listings", "Inventory & sales"),
    ("NEWLISCOUUS", "New Listings - U.S. (Realtor.com)", "Listings", "Inventory & sales"),
    ("PENLISCOUUS", "Pending Listings - U.S. (Realtor.com)", "Listings", "Inventory & sales"),
    ("PRIREDCOUUS", "Listings with Price Reductions - U.S. (Realtor.com)", "Listings", "Inventory & sales"),
    ("MEDDAYONMARUS", "Median Days on Market - U.S. (Realtor.com)", "Days", "Inventory & sales"),
    ("MEDLISPRIUS", "Median Listing Price - U.S. (Realtor.com)", "USD", "Inventory & sales"),
    ("EXHOSLUSM495S", "Existing Home Sales (SAAR)", "Homes", "Inventory & sales"),
    ("HSN1F", "New One-Family Houses Sold (SAAR, thousands)", "Thousands", "Inventory & sales"),
    ("MSACSR", "Months' Supply of New Houses", "Months", "Inventory & sales"),
    ("HOUST", "Housing Starts - Total (SAAR, thousands)", "Thousands", "Construction"),
    ("HOUST1F", "Housing Starts - Single-Family (SAAR, thousands)", "Thousands", "Construction"),
    ("PERMIT", "Building Permits - Total (SAAR, thousands)", "Thousands", "Construction"),
    ("UNDCONTSA", "Housing Units Under Construction (SA, thousands)", "Thousands", "Construction"),
    ("COMPUTSA", "Housing Units Completed (SAAR, thousands)", "Thousands", "Construction"),
    ("RHORUSQ156N", "Homeownership Rate", "%", "Ownership & vacancy"),
    ("RRVRUSQ156N", "Rental Vacancy Rate", "%", "Ownership & vacancy"),
    ("RHVRUSQ156N", "Homeowner Vacancy Rate", "%", "Ownership & vacancy"),
    ("CPIAUCSL", "Consumer Price Index (All Items)", "Index 1982-84=100", "Economy & inflation"),
    ("CUSR0000SAH1", "CPI: Shelter", "Index 1982-84=100", "Economy & inflation"),
    ("CUSR0000SEHA", "CPI: Rent of Primary Residence", "Index 1982-84=100", "Economy & inflation"),
    ("UNRATE", "Unemployment Rate", "%", "Economy & inflation"),
    ("PAYEMS", "Nonfarm Payrolls (thousands)", "Thousands", "Economy & inflation"),
    ("MEHOINUSA646N", "Median Household Income (nominal)", "USD", "Economy & inflation"),
]
DAILY = {"DGS10"}

INFO = {
    "id": "fred",
    "name": "FRED - Federal Reserve Bank of St. Louis",
    "homepage": "https://fred.stlouisfed.org/",
    "description": "National series: Freddie Mac 30/15-year mortgage rates, Treasury & Fed funds rates, "
                   "Case-Shiller index, new/existing home sales, housing starts & permits, vacancy and "
                   "homeownership rates, mortgage delinquencies, CPI shelter, payrolls and unemployment.",
    "frequency": "Weekly (mortgage rates every Thursday) to quarterly",
    "metrics": [s[0] for s in SERIES],
    "license": "Varies by series; FRED data is free for personal use (see each series' notes)",
}


def file_list(cfg):
    return [{"key": "fred_" + s[0], "url": URL.format(sid=s[0]), "desc": s[1]} for s in SERIES]


def parse_csv(text):
    pts = []
    lines = text.splitlines()
    for line in lines[1:]:
        p = line.split(",")
        if len(p) < 2:
            continue
        d = p[0].strip()
        v = to_float(p[1])
        if v == v and len(d) >= 10:
            pts.append((d[:10], v))
    return pts


def monthly_avg(pts):
    acc = {}
    for d, v in pts:
        k = d[:7]
        a = acc.setdefault(k, [0.0, 0])
        a[0] += v
        a[1] += 1
    return [(k + "-01", a[0] / a[1]) for k, a in sorted(acc.items())]


def guess_freq(pts):
    if len(pts) < 3:
        return "M"
    from datetime import date
    def dd(s):
        return date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    gaps = sorted((dd(pts[i + 1][0]) - dd(pts[i][0])).days for i in range(max(0, len(pts) - 30), len(pts) - 1))
    g = gaps[len(gaps) // 2] if gaps else 30
    if g <= 3:
        return "D"
    if g <= 8:
        return "W"
    if g <= 40:
        return "M"
    if g <= 100:
        return "Q"
    return "A"


def run(ctx):
    con = ctx.con
    ok, failed = [], []
    for sid, name, units, cat in SERIES:
        if ctx.cancelled():
            raise RuntimeError("cancelled")
        ctx.report("FRED: %s" % sid)
        text, res = ctx.dl.get_text("fred_" + sid, URL.format(sid=sid), "fred", dest_name=sid + ".csv")
        if not text:
            failed.append(sid)
            continue
        pts = parse_csv(text)
        if not pts:
            failed.append(sid)
            continue
        freq = guess_freq(pts)
        if sid in DAILY or freq == "D":
            pts = monthly_avg(pts)
            freq = "M"
        con.execute("INSERT OR REPLACE INTO macro(sid,name,units,freq,src,category,dates,vals,updated) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (sid, name, units, freq, "fred", cat, json.dumps([d for d, _ in pts]),
                     json.dumps([round(v, 4) for _, v in pts]), now_str()))
        if sid == "MORTGAGE30US":
            mpts = monthly_avg(pts)
            con.execute("INSERT OR REPLACE INTO macro(sid,name,units,freq,src,category,dates,vals,updated) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        ("MORTGAGE30US_M", "30-Year Mortgage Rate (monthly average)", "%", "M", "fred", "_internal",
                         json.dumps([d for d, _ in mpts]), json.dumps([round(v, 4) for _, v in mpts]), now_str()))
        if sid in ("UNRATE", "PAYEMS"):
            # national series stored like regional ones so they line up with states/metros
            metric, scale = ("unemployment", 1.0) if sid == "UNRATE" else ("payroll_jobs", 1000.0)
            con.execute("DELETE FROM series WHERE metric=? AND level='us' AND src='fred'", (metric,))
            w = SeriesWriter(con, "fred")
            data = {}
            for d, v in pts:
                m = parse_month(d)
                if m is not None:
                    data[m] = v * scale
            if data:
                lo, hi = min(data), max(data)
                w.put(metric, "us", "US", "M", lo, [data.get(i, float("nan")) for i in range(lo, hi + 1)])
                w.flush()
        ok.append(sid)
        time.sleep(0.2)
    if not ok:
        raise RuntimeError("Could not download any FRED series")
    latest = None
    row = con.execute("SELECT dates FROM macro WHERE sid='MORTGAGE30US'").fetchone()
    if row:
        latest = json.loads(row[0])[-1]
    return {"message": "%d series%s" % (len(ok), ("; unavailable: " + ", ".join(failed)) if failed else ""),
            "details": {"ok": ok, "failed": failed}, "ok": True, "latest": latest, "warn": bool(failed)}
