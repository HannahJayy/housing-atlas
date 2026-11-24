"""Composite scores:
  * Price Forecast Score (0-100, monthly history) + calibrated 12-month forecast
  * Long-Term Growth Score (0-100, current)
  * Investor Score (0-100, current)
All weights are documented on the Methodology page and kept deliberately simple."""

import bisect
import math

from .db import SeriesWriter, set_meta
from .engine import Engine, last_transform, latest_value, transform
from .util import NAN, log, midx, midx_str, now_midx
from .sources.common import this_year

LEVELS = ["us", "state", "metro", "county", "zip"]
HIST_START = midx(2018, 1)

# factor: (weight, direction)  direction +1 = higher is bullish
FORECAST_FACTORS = {
    "mom3": (0.25, +1),
    "inv_vs_pre": (0.20, -1),
    "inv_yoy": (0.10, -1),
    "cut_yoy": (0.10, -1),
    "dom_yoy": (0.10, -1),
    "overval": (0.15, -1),
    "mos": (0.10, -1),
}
LONGTERM = {"pop5": (0.25, +1), "mig": (0.15, +1), "jobs": (0.15, +1), "inc5": (0.10, +1),
            "app10": (0.20, +1), "vti": (0.15, -1)}
INVESTOR = {"yield": (0.30, +1), "rentg": (0.15, +1), "overval": (0.15, -1), "fscore": (0.15, +1),
            "pop5": (0.10, +1), "vac": (0.075, -1), "tax": (0.075, -1)}


class Pct:
    """Percentile lookup against a (sub-sampled) sorted reference distribution."""

    def __init__(self, values, cap=200000):
        vals = [v for v in values if v == v and not math.isinf(v)]
        if len(vals) > cap:
            step = len(vals) / float(cap)
            vals = [vals[int(i * step)] for i in range(cap)]
        vals.sort()
        self.v = vals

    def __call__(self, x):
        if x != x or not self.v:
            return NAN
        return bisect.bisect_left(self.v, x) / float(len(self.v))


def _factor_series(eng, level):
    z = eng.stored_level("zhvi", level)
    inv = eng.stored_level("inventory", level)
    cut = eng.stored_level("price_cut_share", level)
    dom = eng.stored_level("dom", level)
    ov = eng.stored_level("overvalued", level)
    mos = eng.stored_level("rf_months_supply", level)
    out = {}
    for gid, zs in z.items():
        f = {}
        mom = [NAN] * len(zs.v)
        for k in range(3, len(zs.v)):
            a, b = zs.v[k], zs.v[k - 3]
            if a == a and b == b and b > 0:
                mom[k] = ((a / b) ** 4 - 1.0) * 100.0
        f["mom3"] = (zs.start, mom)
        if gid in inv:
            t = transform(inv[gid], "vs_pre", "pct")
            if t:
                f["inv_vs_pre"] = (t.start, t.v)
            t = transform(inv[gid], "yoy", "pct")
            if t:
                f["inv_yoy"] = (t.start, t.v)
        if gid in cut:
            t = transform(cut[gid], "yoy", "diff")
            if t:
                f["cut_yoy"] = (t.start, t.v)
        if gid in dom:
            t = transform(dom[gid], "yoy", "pct")
            if t:
                f["dom_yoy"] = (t.start, t.v)
        if gid in ov:
            f["overval"] = (ov[gid].start, ov[gid].v)
        if gid in mos:
            f["mos"] = (mos[gid].start, mos[gid].v)
        out[gid] = (zs, f)
    return out


def _val(fs, m):
    start, v = fs
    k = m - start
    return v[k] if 0 <= k < len(v) else NAN


def forecast(con, cfg, report=None):
    eng = Engine(con, cfg)
    results = {}
    calib_pairs = []
    level_data = {}
    for level in LEVELS:
        if report:
            report("Scoring price forecast (%s)" % level)
        data = _factor_series(eng, level)
        if not data:
            continue
        latest = max(zs.end for zs, _ in data.values())
        # reference distributions (pooled over regions and months since 2018)
        ref = {}
        for fname in FORECAST_FACTORS:
            vals = []
            for zs, f in data.values():
                if fname in f:
                    st, v = f[fname]
                    lo = max(HIST_START, st)
                    vals.extend(v[lo - st:])
            if len(vals) >= 30:
                ref[fname] = Pct(vals)
        scores = {}
        for gid, (zs, f) in data.items():
            sc = []
            for m in range(max(HIST_START, zs.start + 3), latest + 1):
                num = den = 0.0
                cnt = 0
                for fname, (wt, sign) in FORECAST_FACTORS.items():
                    if fname not in f or fname not in ref:
                        continue
                    p = ref[fname](_val(f[fname], m))
                    if p != p:
                        continue
                    num += wt * (p if sign > 0 else 1.0 - p)
                    den += wt
                    cnt += 1
                sc.append(100.0 * num / den if (cnt >= 3 and den > 0) else NAN)
            scores[gid] = (max(HIST_START, zs.start + 3), sc)
            if level in ("county", "metro"):
                st, sv = scores[gid]
                for k, s in enumerate(sv):
                    m = st + k
                    if s != s or m + 12 > zs.end:
                        continue
                    a, b = zs.at(m), zs.at(m + 12)
                    if a == a and b == b and a > 0:
                        calib_pairs.append((s, (b / a - 1.0) * 100.0))
        level_data[level] = scores
    # calibration: fwd12 = a + b*(score-50)
    a, b, r2 = 3.0, 0.25, None
    if len(calib_pairs) >= 200:
        xs = [s - 50.0 for s, _ in calib_pairs]
        ys = [y for _, y in calib_pairs]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx > 0:
            b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
            a = my - b * mx
            ss_tot = sum((y - my) ** 2 for y in ys)
            ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
            r2 = 1 - ss_res / ss_tot if ss_tot else None
        if b <= 0:  # guard against a nonsensical slope
            b = 0.1
    set_meta(con, "forecast_calibration", {"intercept": a, "slope": b, "r2": r2, "n": len(calib_pairs)})
    con.execute("BEGIN")
    con.execute("DELETE FROM series WHERE metric IN ('forecast_score','forecast_12m') AND src='derived'")
    w = SeriesWriter(con, "derived")
    for level, scores in level_data.items():
        for gid, (st, sv) in scores.items():
            w.put("forecast_score", level, gid, "M", st, sv)
            w.put("forecast_12m", level, gid, "M", st,
                  [max(-25.0, min(25.0, a + b * (s - 50.0))) if s == s else NAN for s in sv])
        results[level] = len(scores)
    w.flush()
    con.execute("COMMIT")
    log.info("  forecast scores %s; calibration a=%.2f b=%.3f r2=%s n=%d", results, a, b,
             ("%.3f" % r2) if r2 is not None else "-", len(calib_pairs))
    return results


def _latest_map(eng, metric, level, tf=None, mode="pct", min_period=None):
    out = {}
    win = now_midx() - 30 if not tf else None
    for gid, s in eng.level_series(metric, level, window_start=win).items():
        p, v = last_transform(s, tf, mode)
        if p is not None and v == v:
            out[gid] = v
    return out


def _score_table(factors, table):
    """table: {gid: {factor: value}} -> {gid: score}"""
    ref = {}
    for f in factors:
        vals = [row[f] for row in table.values() if f in row and row[f] == row[f]]
        if len(vals) >= 5:
            ref[f] = Pct(vals)
    out = {}
    for gid, row in table.items():
        num = den = 0.0
        cnt = 0
        for f, (wt, sign) in factors.items():
            if f not in ref or f not in row:
                continue
            p = ref[f](row[f])
            if p != p:
                continue
            num += wt * (p if sign > 0 else 1 - p)
            den += wt
            cnt += 1
        if cnt >= 3 and den > 0:
            out[gid] = 100.0 * num / den
    return out


def _jobs_growth(eng, level):
    """1-year job growth: payroll jobs (BLS CES, metros/states) where published, else employed residents (LAUS)."""
    jobs = _latest_map(eng, "employment", level, "yoy", "pct")
    if level in ("metro", "state", "us"):
        jobs.update(_latest_map(eng, "payroll_jobs", level, "yoy", "pct"))
    return jobs


def long_term_and_investor(con, cfg, report=None):
    eng = Engine(con, cfg)
    year = this_year()
    by_level = {}
    for level in ("county", "metro", "state", "us"):
        by_level[level] = {
            "pop5": _latest_map(eng, "population", level, "chg_5y", "pct"),
            "mig": _latest_map(eng, "migration_rate", level),
            "jobs": _jobs_growth(eng, level),
            "inc5": _latest_map(eng, "pcpi", level, "chg_5y", "pct"),
        }
    con.execute("BEGIN")
    con.execute("DELETE FROM series WHERE metric IN ('longterm_score','investor_score') AND src='derived'")
    w = SeriesWriter(con, "derived")
    counts = {}
    for level in LEVELS:
        if report:
            report("Scoring long-term growth & investor appeal (%s)" % level)
        parents = eng.parents(level)
        app10 = _latest_map(eng, "zhvi", level, "chg_10y", "pct")
        vti = _latest_map(eng, "value_to_income", level)
        gy = _latest_map(eng, "gross_yield", level)
        rentg = _latest_map(eng, "rent", level, "yoy", "pct")
        ov = _latest_map(eng, "overvalued", level)
        fs = _latest_map(eng, "forecast_score", level)
        vac = _latest_map(eng, "rental_vacancy", level) or _latest_map(eng, "vacancy_rate", level)
        own = by_level.get(level, {})
        geos = set(app10) | set(vti) | set(gy) | set(own.get("pop5", {}))

        def fallback(key, gid):
            if key in own and gid in own[key]:
                return own[key][gid]
            st, metro, county = parents.get(gid, (None, None, None))
            for lv, pid in (("county", county), ("metro", metro), ("state", st)):
                if pid and pid in by_level[lv].get(key, {}):
                    return by_level[lv][key][pid]
            return NAN

        lt, inv = {}, {}
        for gid in geos:
            lt[gid] = {"pop5": fallback("pop5", gid), "mig": fallback("mig", gid), "jobs": fallback("jobs", gid),
                       "inc5": fallback("inc5", gid), "app10": app10.get(gid, NAN), "vti": vti.get(gid, NAN)}
            inv[gid] = {"yield": gy.get(gid, NAN), "rentg": rentg.get(gid, NAN), "overval": ov.get(gid, NAN),
                        "fscore": fs.get(gid, NAN), "pop5": fallback("pop5", gid), "vac": vac.get(gid, NAN),
                        "tax": eng.tax_rate(level, gid)}
        if level == "us":
            # a single region can't be ranked against peers - use the state average instead
            continue
        lts = _score_table(LONGTERM, lt)
        invs = _score_table(INVESTOR, inv)
        for gid, v in lts.items():
            w.put("longterm_score", level, gid, "A", year, [v])
        for gid, v in invs.items():
            w.put("investor_score", level, gid, "A", year, [v])
        counts[level] = (len(lts), len(invs))
        if level == "state":
            pops = {g: p for g, p in con.execute("SELECT geo_id, population FROM geos WHERE level='state'")}
            for name, d in (("longterm_score", lts), ("investor_score", invs)):
                num = sum(v * (pops.get(g) or 0) for g, v in d.items())
                den = sum((pops.get(g) or 0) for g in d)
                if den > 0:
                    w.put(name, "us", "US", "A", year, [num / den])
    w.flush()
    con.execute("COMMIT")
    log.info("  long-term / investor scores: %s", counts)
    return counts


def run(con, cfg, report=None):
    forecast(con, cfg, report)
    return long_term_and_investor(con, cfg, report)
