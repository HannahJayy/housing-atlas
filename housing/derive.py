"""Pipeline-computed metrics: current-year income model, overvaluation (income- and
trend-based), and the 2007-2012 crash depth."""

import math

from .db import SeriesWriter
from .engine import Engine, S, aligned_monthly
from .util import NAN, log, midx, now_midx
from .sources.common import this_year

LEVELS = ["us", "state", "metro", "county", "zip"]
BASE_LO, BASE_HI = midx(2000, 1), midx(2019, 12)


def _growth_index(s, cy):
    """Annual pcpi series -> {year: value} extended to the current year with recent growth."""
    if s is None:
        return None
    pts = {y: v for y, v in s.points() if v > 0}
    if len(pts) < 3:
        return None
    last = max(pts)
    base = pts.get(last - 3)
    g = (pts[last] / base) ** (1.0 / 3) - 1 if base else 0.03
    g = max(-0.02, min(0.08, g))
    for y in range(last + 1, cy + 1):
        pts[y] = pts[y - 1] * (1 + g)
    return pts


def build_income(con, cfg, report=None):
    eng = Engine(con, cfg)
    cy = this_year()
    pc = {lv: {g: _growth_index(s, cy) for g, s in eng.stored_level("pcpi", lv).items()}
          for lv in ("us", "state", "metro", "county")}
    us_idx = pc["us"].get("US")
    parents = {lv: eng.parents(lv) for lv in LEVELS}
    con.execute("BEGIN")
    con.execute("DELETE FROM series WHERE metric='income' AND src='derived'")
    w = SeriesWriter(con, "derived")
    n = 0
    for lv in LEVELS:
        for gid, s in eng.stored_level("acs_income", lv).items():
            ya, va = s.last()
            if ya is None or va != va or va <= 0:
                continue
            st, metro, county = parents[lv].get(gid, (None, None, None))
            chain = []
            if lv in pc:
                chain.append(pc[lv].get(gid))
            if county:
                chain.append(pc["county"].get(county))
            if metro:
                chain.append(pc["metro"].get(metro))
            if st:
                chain.append(pc["state"].get(st))
            chain.append(us_idx)
            idx = next((c for c in chain if c and ya in c), None)
            if idx is None:
                vals = {y: va for y in range(ya, cy + 1)}
            else:
                vals = {y: va * idx[y] / idx[ya] for y in idx if y >= 1990}
            lo, hi = min(vals), max(vals)
            w.put("income", lv, gid, "A", lo, [vals.get(y, NAN) for y in range(lo, hi + 1)])
            n += 1
    w.flush()
    con.execute("COMMIT")
    log.info("  income model: %d series", n)
    return n


def _ols(xs, ys):
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return my - b * mx, b


def build_overvaluation(con, cfg, report=None):
    eng = Engine(con, cfg)
    con.execute("BEGIN")
    con.execute("DELETE FROM series WHERE metric IN ('overvalued','overvalued_income','overvalued_trend',"
                "'gfc_crash') AND src='derived'")
    w = SeriesWriter(con, "derived")
    counts = {}
    for lv in LEVELS:
        if report:
            report("Computing overvaluation (%s)" % lv)
        inc_level = eng.stored_level("income", lv)
        for gid, z in eng.stored_level("zhvi", lv).items():
            n = len(z.v)
            # --- trend method
            ot = None
            xs, ys = [], []
            for k, v in enumerate(z.v):
                m = z.start + k
                if BASE_LO <= m <= BASE_HI and v == v and v > 0:
                    xs.append(m - BASE_LO)
                    ys.append(math.log(v))
            if len(xs) >= 120:
                fit = _ols(xs, ys)
                if fit:
                    a, b = fit
                    ot = [NAN] * n
                    for k, v in enumerate(z.v):
                        if v == v and v > 0:
                            ot[k] = (v / math.exp(a + b * (z.start + k - BASE_LO)) - 1.0) * 100.0
            # --- income method
            oi = None
            inc = inc_level.get(gid)
            if inc is not None:
                incm = aligned_monthly(inc, z.start, z.end, flat=True)
                ratios = []
                for y in range(2000, 2020):
                    vals = [z.at(midx(y, mth)) for mth in range(1, 13)]
                    vals = [x for x in vals if x == x]
                    if len(vals) < 6:
                        continue
                    iy = inc.at(y) if inc.freq == "A" else NAN
                    if iy != iy:
                        k = midx(y, 7) - z.start
                        iy = incm[k] if 0 <= k < n else NAN
                    if iy == iy and iy > 0:
                        ratios.append(sum(vals) / len(vals) / iy)
                if len(ratios) >= 6:
                    base = sum(ratios) / len(ratios)
                    oi = [NAN] * n
                    for k, v in enumerate(z.v):
                        i = incm[k]
                        if v == v and i == i and i > 0:
                            oi[k] = ((v / i) / base - 1.0) * 100.0
            comp = None
            if ot or oi:
                comp = [NAN] * n
                for k in range(n):
                    a1 = ot[k] if ot else NAN
                    a2 = oi[k] if oi else NAN
                    vv = [x for x in (a1, a2) if x == x]
                    if vv:
                        comp[k] = sum(vv) / len(vv)
            if ot:
                w.put("overvalued_trend", lv, gid, "M", z.start, ot)
            if oi:
                w.put("overvalued_income", lv, gid, "M", z.start, oi)
            if comp:
                w.put("overvalued", lv, gid, "M", z.start, comp)
                counts[lv] = counts.get(lv, 0) + 1
            # --- 2007-2012 crash depth
            pk_v, pk_m = NAN, None
            for m in range(midx(2004, 1), midx(2008, 12) + 1):
                v = z.at(m)
                if v == v and (pk_v != pk_v or v > pk_v):
                    pk_v, pk_m = v, m
            if pk_m is not None:
                tr = NAN
                for m in range(pk_m, midx(2013, 12) + 1):
                    v = z.at(m)
                    if v == v and (tr != tr or v < tr):
                        tr = v
                if tr == tr and z.start <= midx(2005, 1):
                    w.put("gfc_crash", lv, gid, "A", 2012, [(tr / pk_v - 1.0) * 100.0])
    w.flush()
    con.execute("COMMIT")
    log.info("  overvaluation: %s", counts)
    return counts


def run(con, cfg, report=None):
    build_income(con, cfg, report)
    return build_overvaluation(con, cfg, report)
