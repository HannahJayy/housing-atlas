"""Bureau of Labor Statistics - Local Area Unemployment Statistics (LAUS): unemployment rate, employment and
labor force for states, metros and counties; Current Employment Statistics (CES): nonfarm payroll jobs for
states and metros via the public BLS API."""

from ..geo.states import FIPS_TO_ABBR
from ..util import log, midx, midx_str, parse_month, to_float
from .common import Store, open_text, replace_source_series

COUNTY14 = "https://www.bls.gov/web/metro/laucntycur14.txt"
METRO = "https://download.bls.gov/pub/time.series/la/la.data.60.Metro"
STATES = "https://download.bls.gov/pub/time.series/la/la.data.3.AllStatesS"
COUNTY_ALL = "https://download.bls.gov/pub/time.series/la/la.data.64.County"
CES_API_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
CES_API_V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

MEASURE = {"03": "unemployment", "05": "employment", "06": "labor_force"}

INFO = {
    "id": "bls",
    "name": "U.S. Bureau of Labor Statistics - Unemployment (LAUS) & Payroll Jobs (CES)",
    "homepage": "https://www.bls.gov/lau/",
    "description": "Monthly unemployment rate, number employed and labor force for every state "
                   "(seasonally adjusted), metro area and county (not seasonally adjusted), plus total nonfarm "
                   "payroll jobs for every state and metro area from the BLS API (no key needed; a free key raises "
                   "the daily limit). BLS asks automated downloaders to include a contact e-mail - set one in "
                   "Settings if downloads are refused.",
    "frequency": "Monthly",
    "metrics": ["unemployment", "employment", "labor_force", "payroll_jobs"],
    "license": "Public domain (U.S. Government work)",
}


def file_list(cfg):
    out = [{"key": "bls_county14", "url": COUNTY14, "desc": "Counties, latest 14 months"},
           {"key": "bls_metro", "url": METRO, "desc": "Metro areas, full history"},
           {"key": "bls_states", "url": STATES, "desc": "States (seasonally adjusted), full history"}]
    if (cfg.get("sources", {}).get("bls", {}) or {}).get("county_history"):
        out.append({"key": "bls_county_all", "url": COUNTY_ALL, "desc": "Counties, full history (large)"})
    out.append({"key": "bls_ces_api", "url": CES_API_V2 if cfg.get("bls_api_key") else CES_API_V1,
                "desc": "Payroll jobs (CES) for metros & states via the BLS API (replies cached 6 days; ~18 of the "
                        "25 requests/day allowed without a free key)"})
    return out


def _metro_states(full_name, primary):
    """'Philadelphia-Camden-Wilmington, PA-NJ-DE-MD' -> ['PA', 'NJ', 'DE', 'MD'] (primary first)."""
    out = [primary] if primary else []
    if full_name and "," in full_name:
        for st in full_name.rsplit(",", 1)[1].strip().split()[0].split("-"):
            st = st.strip().upper()
            if len(st) == 2 and st not in out:
                out.append(st)
    return out


def fetch_payroll(ctx):
    """Total nonfarm payroll jobs for every metropolitan area and state via the BLS API (CES program).
    Series ids: SMU{state}{cbsa}0000000001 (metros, not seasonally adjusted, thousands) and
    SMS{state}000000000000001 (states, seasonally adjusted). Replies are cached for 6 days so a weekly
    update uses ~18 of the 25 requests/day allowed without a key. Returns (store, values, note)."""
    import hashlib
    import os
    import time as _t
    from ..geo.states import ABBR_TO_FIPS
    from .common import this_year
    key = (ctx.cfg.get("bls_api_key") or "").strip()
    url = CES_API_V2 if key else CES_API_V1
    per, years, budget = (50, 19, 400) if key else (25, 9, 24)
    store = Store("M")
    metros = []
    for gid, st, lsad, full in ctx.con.execute(
            "SELECT geo_id, state, lsad, full_name FROM geos WHERE level='metro'"):
        if lsad == "metro":
            metros.append((gid, [x for x in _metro_states(full, st) if x in ABBR_TO_FIPS]))
    first = {}
    for st, fips in ABBR_TO_FIPS.items():
        first["SMS%s000000000000001" % fips] = ("state", st)
    for gid, sts in metros:
        if sts:
            first["SMU%s%s0000000001" % (ABBR_TO_FIPS[sts[0]], gid)] = ("metro", gid)
    y1 = this_year()
    state = {"got": 0, "queries": 0, "note": None, "found": set(), "cached": 0, "bytes": 0, "files": set()}

    def run_batches(ids):
        sids = sorted(ids)
        for b in range(0, len(sids), per):
            if ctx.cancelled():
                raise RuntimeError("cancelled")
            batch = sids[b:b + per]
            payload = {"seriesid": batch, "startyear": str(y1 - years), "endyear": str(y1)}
            tag = hashlib.md5(("%s|%s|%s" % (",".join(batch), y1 - years, y1)).encode()).hexdigest()[:12]
            name = "ces_%s.json" % tag
            state["files"].add(name)
            path = ctx.dl.local_path("bls", url, name)
            fresh = (not ctx.force and os.path.exists(path)
                     and (_t.time() - os.path.getmtime(path)) < 6 * 86400)
            if not fresh and state["queries"] >= budget:
                state["note"] = ("payroll jobs: skipped some areas to stay within the BLS API daily limit - add a free "
                                 "BLS API key in Settings (data.bls.gov/registrationEngine)")
                return False
            if key:
                payload["registrationkey"] = key
            res, err, cached = ctx.dl.post_json("bls_ces_api", url, payload, "bls", name,
                                                max_age_hours=None if ctx.force else 6 * 24)
            if not cached:
                state["queries"] += 1
            else:
                state["cached"] += 1
            if res is None:
                state["note"] = "payroll jobs: BLS API unreachable (%s)" % err
                state["aborted"] = True
                return False
            status = res.get("status")
            msgs = [m for m in (res.get("message") or []) if "does not exist" not in m.lower()
                    and "no data available" not in m.lower()]
            if status != "REQUEST_SUCCEEDED":
                note = "payroll jobs: BLS API said " + ("; ".join(msgs) or status or "error")[:240]
                low = note.lower()
                try:
                    os.remove(path)  # never keep an error reply in the cache
                except OSError:
                    pass
                if "threshold" in low or "limit" in low or "key" in low:
                    state["note"] = note + " - add a free BLS API key in Settings or wait until tomorrow."
                    state["aborted"] = True
                    return False
                state["note"] = note
                continue
            for ser in (res.get("Results") or {}).get("series", []):
                target = ids.get(ser.get("seriesID"))
                if not target:
                    continue
                n0 = state["got"]
                for d in ser.get("data", []):
                    pcode = d.get("period", "")
                    if not pcode.startswith("M") or pcode == "M13":
                        continue
                    v = to_float(d.get("value"))
                    if v == v:
                        store.add("payroll_jobs", target[0], target[1], midx(int(d["year"]), int(pcode[1:])),
                                  v * 1000.0)
                        state["got"] += 1
                if state["got"] > n0:
                    state["found"].add(target)
            if not cached:
                _t.sleep(0.25)
        return True

    ok = run_batches(first)
    if ok:
        # interstate metros missing under their principal state: try the other states in the name
        retry = {}
        for gid, sts in metros:
            if ("metro", gid) not in state["found"] and len(sts) > 1:
                for st in sts[1:]:
                    retry["SMU%s%s0000000001" % (ABBR_TO_FIPS[st], gid)] = ("metro", gid)
        if retry:
            run_batches(retry)
    # one bookkeeping row for the Data & Sources page; drop cache files from older runs
    d = os.path.dirname(ctx.dl.local_path("bls", url, "x"))
    for fn in ([] if state.get("aborted") else os.listdir(d)):
        if fn.startswith("ces_") and fn.endswith(".json") and fn not in state["files"]:
            try:
                os.remove(os.path.join(d, fn))
            except OSError:
                pass
    total = sum(os.path.getsize(os.path.join(d, f)) for f in state["files"] if os.path.exists(os.path.join(d, f)))
    ctx.dl._record(ctx.dl.resolve("bls_ces_api", url), d, "cached" if not state["queries"] else "downloaded",
                   200 if state["got"] else None, total, source="bls", key="bls_ces_api")
    log.info("  BLS API: %d requests (%d cached), %d areas with payroll data", state["queries"], state["cached"],
             len(state["found"]))
    return store, state["got"], state["note"]


def parse_timeseries(path, store, kind, min_year=1990):
    n = 0
    with open_text(path) as f:
        f.readline()  # header
        for line in f:
            p = line.split()
            if len(p) < 4:
                continue
            sid, year, period, val = p[0], p[1], p[2], p[3]
            if not period.startswith("M") or period == "M13" or not year.isdigit():
                continue
            if int(year) < min_year:
                continue
            measure = sid[-2:]
            metric = MEASURE.get(measure)
            if not metric:
                continue
            if kind == "metro":
                if sid[3:5] != "MT":
                    continue
                gid = sid[7:12]
                level = "metro"
            elif kind == "state":
                if sid[3:5] != "ST":
                    continue
                gid = FIPS_TO_ABBR.get(sid[5:7])
                level = "state"
                if not gid:
                    continue
            else:
                if sid[3:5] != "CN":
                    continue
                gid = sid[5:10]
                level = "county"
            v = to_float(val)
            if v != v:
                continue
            store.add(metric, level, gid, midx(int(year), int(period[1:])), v)
            n += 1
    return n


def parse_county14(path, store):
    n = 0
    with open_text(path) as f:
        for line in f:
            if "|" not in line:
                continue
            p = [x.strip() for x in line.split("|")]
            if len(p) < 9:
                continue
            st, co = p[1], p[2]
            if not (st.isdigit() and co.isdigit()):
                continue
            m = parse_month(p[4].replace("(p)", "").replace("(P)", "").strip())
            if m is None:
                continue
            fips = st.zfill(2) + co.zfill(3)
            lf, emp, rate = to_float(p[5]), to_float(p[6]), to_float(p[8])
            for metric, v in (("labor_force", lf), ("employment", emp), ("unemployment", rate)):
                if v == v:
                    store.add(metric, "county", fips, m, v)
                    n += 1
    return n


def run(ctx):
    store = Store("M")
    stats = {}
    problems = []
    jobs = [("bls_states", STATES, "state"), ("bls_metro", METRO, "metro")]
    if ctx.source_cfg("bls").get("county_history"):
        jobs.append(("bls_county_all", COUNTY_ALL, "county"))
    for key, url, kind in jobs:
        if ctx.cancelled():
            raise RuntimeError("cancelled")
        ctx.report("BLS: downloading %s unemployment data" % kind)
        res = ctx.dl.fetch(key, url, "bls")
        if not res.ok:
            problems.append("%s: %s" % (kind, res.error or res.status))
            continue
        try:
            stats[kind] = parse_timeseries(res.path, store, kind)
        except Exception as e:
            problems.append("%s parse error: %s" % (kind, e))
    ctx.report("BLS: downloading county unemployment (latest 14 months)")
    res = ctx.dl.fetch("bls_county14", COUNTY14, "bls")
    if res.ok:
        try:
            stats["county14"] = parse_county14(res.path, store)
        except Exception as e:
            problems.append("county parse error: %s" % e)
    else:
        problems.append("county: %s" % (res.error or res.status))
    payroll = None
    if ctx.source_cfg("bls").get("payroll", True):
        ctx.report("BLS: payroll jobs for metros & states (BLS API)")
        try:
            payroll, got, note = fetch_payroll(ctx)
            stats["payroll"] = got
            if note:
                problems.append(note)
        except RuntimeError:
            raise
        except Exception as e:
            log.exception("payroll jobs failed")
            problems.append("payroll jobs: %s" % e)
    if not stats or not any(stats.values()):
        hint = "" if ctx.cfg.get("contact_email") else (
            " BLS refuses anonymous downloads - add your e-mail under Settings > Contact e-mail.")
        raise RuntimeError("No BLS data downloaded (%s).%s" % ("; ".join(problems), hint))
    latest = None
    for lv in store.data.get("unemployment", {}).values():
        for pts in lv.values():
            if pts:
                latest = max(latest or max(pts), max(pts))
    n = replace_source_series(ctx.con, "bls", [(store, "M")]) if any(
        v for k, v in stats.items() if k != "payroll") else 0
    if payroll is not None and stats.get("payroll"):
        # stored under their own tag so a failed API call keeps last week's payroll numbers
        n += replace_source_series(ctx.con, "bls_ces", [(payroll, "M")])
    return {"message": "%d series%s" % (n, ("; problems: " + "; ".join(problems)) if problems else ""),
            "details": {"rows": stats, "problems": problems}, "ok": n > 0,
            "latest": midx_str(latest) if latest else None, "warn": bool(problems)}
