"""Series engine: loads stored series, computes virtual metrics (affordability, rent
ratios ...) and applies transforms (1-yr change, vs pre-pandemic, ...)."""

import json
import math

from .db import decode, decode_array
from .metrics import BY_ID
from .util import NAN, midx, now_midx

LAG = {"M": {"mom": 1, "yoy": 12, "chg_5y": 60, "chg_10y": 120},
       "Q": {"mom": 1, "yoy": 4, "chg_5y": 20, "chg_10y": 40},
       "A": {"mom": None, "yoy": 1, "chg_5y": 5, "chg_10y": 10}}
STALE = {"M": 4, "Q": 2, "A": 3}


class S:
    __slots__ = ("freq", "start", "v")

    def __init__(self, freq, start, v):
        self.freq = freq
        self.start = start
        self.v = v

    @property
    def end(self):
        return self.start + len(self.v) - 1

    def at(self, i):
        k = i - self.start
        if 0 <= k < len(self.v):
            return self.v[k]
        return NAN

    def last(self):
        for k in range(len(self.v) - 1, -1, -1):
            x = self.v[k]
            if x == x:
                return self.start + k, x
        return None, None

    def points(self):
        return [(self.start + k, x) for k, x in enumerate(self.v) if x == x]


def to_monthly_anchor(freq, i):
    if freq == "M":
        return i
    if freq == "Q":
        return (i // 4) * 12 + (i % 4) * 3 + 1
    return i * 12 + 6  # July


def aligned_monthly(s, lo, hi, flat=True):
    """Values of s for months lo..hi (interpolating Q/A series; flat beyond the ends)."""
    n = hi - lo + 1
    if s is None or n <= 0:
        return [NAN] * max(n, 0)
    if s.freq == "M":
        out = [NAN] * n
        for k in range(n):
            j = lo + k - s.start
            if 0 <= j < len(s.v):
                out[k] = s.v[j]
        return out
    pts = [(to_monthly_anchor(s.freq, i), x) for i, x in s.points()]
    if not pts:
        return [NAN] * n
    out = [NAN] * n
    j = 0
    for k in range(n):
        m = lo + k
        if m <= pts[0][0]:
            out[k] = pts[0][1] if (flat or m == pts[0][0]) else NAN
            continue
        if m >= pts[-1][0]:
            out[k] = pts[-1][1] if (flat or m == pts[-1][0]) else NAN
            continue
        while j < len(pts) - 2 and pts[j + 1][0] < m:
            j += 1
        (m0, v0), (m1, v1) = pts[j], pts[j + 1]
        if m1 == m0:
            out[k] = v1
        else:
            out[k] = v0 + (v1 - v0) * (m - m0) / (m1 - m0)
    return out


def latest_value(s):
    if s is None:
        return NAN
    return s.last()[1] if s.last()[1] is not None else NAN


def pmt(principal, annual_rate_pct, years):
    n = int(years * 12)
    r = annual_rate_pct / 1200.0
    if principal != principal or r != r:
        return NAN
    if r <= 0:
        return principal / n
    return principal * r / (1.0 - (1.0 + r) ** (-n))


# ----------------------------------------------------------------------------
# transforms
# ----------------------------------------------------------------------------

def _chg(a, b, mode):
    if a != a or b != b:
        return NAN
    if mode == "diff":
        return a - b
    if b == 0:
        return NAN
    return (a / b - 1.0) * 100.0


def transform(s, tf, mode="pct"):
    if s is None or tf in (None, "", "level"):
        return s
    v = s.v
    n = len(v)
    out = [NAN] * n
    if tf in ("mom", "yoy", "chg_5y", "chg_10y"):
        lag = LAG.get(s.freq, {}).get(tf)
        if not lag:
            return None
        for k in range(lag, n):
            out[k] = _chg(v[k], v[k - lag], mode)
        return S(s.freq, s.start, out)
    if tf == "from_peak":
        peak = NAN
        for k in range(n):
            x = v[k]
            if x == x and (peak != peak or x > peak):
                peak = x
            out[k] = _chg(x, peak, mode)
        return S(s.freq, s.start, out)
    if tf == "vs_pre":
        if s.freq == "M":
            base = {}
            for y in (2017, 2018, 2019):
                for mth in range(1, 13):
                    x = s.at(midx(y, mth))
                    if x == x:
                        base.setdefault(mth, []).append(x)
            bavg = {m: sum(xs) / len(xs) for m, xs in base.items() if xs}
            if not bavg:
                return None
            for k in range(n):
                mth = (s.start + k) % 12 + 1
                b = bavg.get(mth)
                if b is not None:
                    out[k] = _chg(v[k], b, mode)
            return S(s.freq, s.start, out)
        if s.freq == "Q":
            base = {}
            for y in (2017, 2018, 2019):
                for q in range(4):
                    x = s.at(y * 4 + q)
                    if x == x:
                        base.setdefault(q, []).append(x)
            bavg = {q: sum(xs) / len(xs) for q, xs in base.items() if xs}
            if not bavg:
                return None
            for k in range(n):
                b = bavg.get((s.start + k) % 4)
                if b is not None:
                    out[k] = _chg(v[k], b, mode)
            return S(s.freq, s.start, out)
        b = s.at(2019)
        if b != b:
            return None
        for k in range(n):
            out[k] = _chg(v[k], b, mode)
        return S(s.freq, s.start, out)
    return None


def _vs_pre_base(s):
    if s.freq == "M":
        out = {}
        for mth in range(1, 13):
            xs = [s.at(midx(y, mth)) for y in (2017, 2018, 2019)]
            xs = [x for x in xs if x == x]
            if xs:
                out[mth] = sum(xs) / len(xs)
        return out
    if s.freq == "Q":
        out = {}
        for q in range(4):
            xs = [s.at(y * 4 + q) for y in (2017, 2018, 2019)]
            xs = [x for x in xs if x == x]
            if xs:
                out[q] = sum(xs) / len(xs)
        return out
    b = s.at(2019)
    return {None: b} if b == b else {}


def last_transform(s, tf, mode="pct"):
    """(period, value) of the most recent point of transform(s, tf) - same result as
    transform(s, tf, mode).last() but without building the whole transformed series."""
    if s is None:
        return None, NAN
    v = s.v
    n = len(v)
    if tf in (None, "", "level"):
        for k in range(n - 1, -1, -1):
            if v[k] == v[k]:
                return s.start + k, v[k]
        return None, NAN
    if tf in ("mom", "yoy", "chg_5y", "chg_10y"):
        lag = LAG.get(s.freq, {}).get(tf)
        if not lag:
            return None, NAN
        for k in range(n - 1, lag - 1, -1):
            a = v[k]
            if a == a:
                b = v[k - lag]
                if b == b:
                    r = _chg(a, b, mode)
                    if r == r:
                        return s.start + k, r
        return None, NAN
    if tf == "from_peak":
        for k in range(n - 1, -1, -1):
            if v[k] == v[k]:
                peak = max(x for x in v[:k + 1] if x == x)
                return s.start + k, _chg(v[k], peak, mode)
        return None, NAN
    if tf == "vs_pre":
        base = _vs_pre_base(s)
        if not base:
            return None, NAN
        for k in range(n - 1, -1, -1):
            a = v[k]
            if a != a:
                continue
            p = s.start + k
            key = (p % 12 + 1) if s.freq == "M" else ((p % 4) if s.freq == "Q" else None)
            b = base.get(key)
            if b is not None:
                return p, _chg(a, b, mode)
        return None, NAN
    return None, NAN


def crop(s, start):
    """Drop points before `start` (monthly series only) - speeds up bulk virtual metrics."""
    if s is None or start is None or s.freq != "M" or s.start >= start:
        return s
    k = start - s.start
    if k >= len(s.v):
        return None
    return S(s.freq, start, s.v[k:])


# ----------------------------------------------------------------------------
# engine
# ----------------------------------------------------------------------------

class Engine:
    def __init__(self, con, cfg):
        self.con = con
        self.cfg = cfg
        self.aff = dict(cfg.get("affordability") or {})
        self._rates = None
        self._latest_rate = None
        self._parents = {}
        self._tax_cache = {}
        self._aland = {}

    # --- raw access -------------------------------------------------------
    def stored(self, metric, level, gid):
        row = self.con.execute("SELECT freq, start, vals FROM series WHERE metric=? AND level=? AND geo_id=?",
                               (metric, level, gid)).fetchone()
        if not row:
            return None
        return S(row[0], row[1], decode(row[2]))

    def stored_level(self, metric, level):
        out = {}
        for gid, freq, start, blob in self.con.execute(
                "SELECT geo_id, freq, start, vals FROM series WHERE metric=? AND level=?", (metric, level)):
            out[gid] = S(freq, start, decode_array(blob))
        return out

    def available(self):
        """{metric: [levels]} including virtual metrics whose inputs exist."""
        have = {}
        for metric, level in self.con.execute("SELECT DISTINCT metric, level FROM series"):
            have.setdefault(metric, set()).add(level)
        for m in BY_ID.values():
            if m["kind"] == "virtual":
                lv = None
                for d in m["deps"]:
                    if d == "property_tax_rate":
                        continue
                    s = have.get(d, set())
                    lv = s if lv is None else (lv & s)
                if lv:
                    have[m["id"]] = set(lv)
        return {k: sorted(v) for k, v in have.items()}

    # --- inputs for virtual metrics ---------------------------------------
    def rates(self):
        if self._rates is None:
            self._rates = {}
            row = self.con.execute("SELECT dates, vals FROM macro WHERE sid='MORTGAGE30US_M'").fetchone()
            if row:
                for d, v in zip(json.loads(row[0]), json.loads(row[1])):
                    self._rates[midx(int(d[:4]), int(d[5:7]))] = v
            row = self.con.execute("SELECT vals FROM macro WHERE sid='MORTGAGE30US'").fetchone()
            if row:
                vals = json.loads(row[0])
                self._latest_rate = vals[-1] if vals else None
        return self._rates

    def rate_at(self, m):
        ov = self.aff.get("rate_override_pct")
        if ov not in (None, ""):
            return float(ov)
        r = self.rates()
        if m in r:
            return r[m]
        if r:
            last = max(r)
            if m > last:
                return self._latest_rate if self._latest_rate is not None else r[last]
            first = min(r)
            if m < first:
                return r[first]
        return 6.5

    def parents(self, level):
        if level not in self._parents:
            d = {}
            for gid, st, metro, county in self.con.execute(
                    "SELECT geo_id, state, metro_id, county_id FROM geos WHERE level=?", (level,)):
                d[gid] = (st, metro, county)
            self._parents[level] = d
        return self._parents[level]

    def _tax_level(self, level):
        if level not in self._tax_cache:
            d = {}
            for gid, s in self.stored_level("property_tax_rate", level).items():
                v = latest_value(s)
                if v == v and 0 < v < 6:
                    d[gid] = v
            self._tax_cache[level] = d
        return self._tax_cache[level]

    def tax_rate(self, level, gid):
        v = self._tax_level(level).get(gid)
        if v is not None:
            return v
        st, metro, county = self.parents(level).get(gid, (None, None, None))
        if county:
            v = self._tax_level("county").get(county)
            if v is not None:
                return v
        if st:
            v = self._tax_level("state").get(st)
            if v is not None:
                return v
        v = self._tax_level("us").get("US")
        if v is not None:
            return v
        return float(self.aff.get("default_property_tax_pct") or 1.0)

    def aland(self, level, gid):
        if level not in self._aland:
            self._aland[level] = {g: a for g, a in self.con.execute(
                "SELECT geo_id, aland FROM geos WHERE level=?", (level,))}
        return self._aland[level].get(gid)

    # --- virtual metric math ----------------------------------------------
    def _payments(self, zhvi, level, gid, include_extras=True):
        a = self.aff
        down = float(a.get("down_payment_pct") or 0) / 100.0
        years = float(a.get("loan_years") or 30)
        ins = float(a.get("insurance_rate_pct") or 0) / 100.0
        pmi = float(a.get("pmi_rate_pct") or 0) / 100.0
        tax = self.tax_rate(level, gid) / 100.0 if include_extras else 0.0
        out = [NAN] * len(zhvi.v)
        for k, price in enumerate(zhvi.v):
            if price != price:
                continue
            m = zhvi.start + k
            loan = price * (1 - down)
            p = pmt(loan, self.rate_at(m), years)
            if include_extras:
                p += price * (tax + ins) / 12.0
                if down < 0.2 and pmi > 0:
                    p += loan * pmi / 12.0
            out[k] = p
        return S("M", zhvi.start, out)

    def compute_virtual(self, mid, level, gid, deps):
        a = self.aff
        g = deps.get
        if mid in ("payment", "payment_pi", "income_needed"):
            z = g("zhvi")
            if z is None:
                return None
            pay = self._payments(z, level, gid, include_extras=(mid != "payment_pi"))
            if mid == "income_needed":
                dti = float(a.get("affordable_dti_pct") or 30) / 100.0
                pay = S("M", pay.start, [x * 12.0 / dti if x == x else NAN for x in pay.v])
            return pay
        if mid in ("payment_to_income", "value_to_income", "rent_to_income"):
            base = g("rent") if mid == "rent_to_income" else g("zhvi")
            inc = g("income")
            if base is None or inc is None:
                return None
            if mid == "payment_to_income":
                base = self._payments(base, level, gid, True)
            incm = aligned_monthly(inc, base.start, base.end, flat=True)
            out = [NAN] * len(base.v)
            for k, x in enumerate(base.v):
                i = incm[k]
                if x == x and i == i and i > 0:
                    if mid == "payment_to_income":
                        out[k] = 100.0 * x / (i / 12.0)
                    elif mid == "value_to_income":
                        out[k] = x / i
                    else:
                        out[k] = 100.0 * x * 12.0 / i
            return S("M", base.start, out)
        if mid in ("price_to_rent", "gross_yield", "cap_rate", "buy_vs_rent"):
            z, r = g("zhvi"), g("rent")
            if z is None or r is None:
                return None
            lo, hi = max(z.start, r.start), min(z.end, r.end)
            if hi < lo:
                return None
            pay = self._payments(z, level, gid, True) if mid == "buy_vs_rent" else None
            exp = float(a.get("expense_ratio_pct") or 40) / 100.0
            out = []
            for m in range(lo, hi + 1):
                zv, rv = z.at(m), r.at(m)
                if zv != zv or rv != rv or zv <= 0 or rv <= 0:
                    out.append(NAN)
                    continue
                if mid == "price_to_rent":
                    out.append(zv / (rv * 12.0))
                elif mid == "gross_yield":
                    out.append(100.0 * rv * 12.0 / zv)
                elif mid == "cap_rate":
                    out.append(100.0 * rv * 12.0 * (1 - exp) / zv)
                else:
                    out.append(100.0 * (pay.at(m) - rv) / rv)
            return S("M", lo, out)
        if mid == "inventory_pct_houses":
            inv, hu = g("inventory"), g("housing_units")
            if inv is None or hu is None:
                return None
            hum = aligned_monthly(hu, inv.start, inv.end, flat=True)
            return S("M", inv.start, [100.0 * x / h if (x == x and h == h and h > 0) else NAN
                                      for x, h in zip(inv.v, hum)])
        if mid == "permits_pct":
            p, hu = g("permits"), g("housing_units")
            if p is None or hu is None:
                return None
            hv = latest_value(hu)
            if hv != hv or hv <= 0:
                return None
            return S("A", p.start, [100.0 * x / hv if x == x else NAN for x in p.v])
        if mid == "pop_density":
            p = g("population")
            area = self.aland(level, gid)
            if p is None or not area:
                return None
            return S("A", p.start, [x / area if x == x else NAN for x in p.v])
        return None

    def _deps_of(self, mid):
        m = BY_ID[mid]
        return [d for d in m["deps"] if d != "property_tax_rate"] + (
            ["housing_units"] if mid == "permits_pct" else [])

    # --- public -----------------------------------------------------------
    def series(self, mid, level, gid):
        m = BY_ID.get(mid)
        if m is None:
            return None
        if m["kind"] != "virtual":
            return self.stored(mid, level, gid)
        deps = {d: self.stored(d, level, gid) for d in set(self._deps_of(mid))}
        return self.compute_virtual(mid, level, gid, deps)

    def level_series(self, mid, level, window_start=None):
        """All regions' series for a metric. window_start (month index) limits how much
        history virtual metrics compute - enough for latest values / recent changes."""
        m = BY_ID.get(mid)
        if m is None:
            return {}
        if m["kind"] != "virtual":
            return self.stored_level(mid, level)
        deps = {d: self.stored_level(d, level) for d in set(self._deps_of(mid))}
        primary = deps.get(m["deps"][0], {}) if m["deps"] else {}
        out = {}
        for gid in primary:
            dd = {k: crop(v.get(gid), window_start) for k, v in deps.items()}
            s = self.compute_virtual(mid, level, gid, dd)
            if s is not None:
                out[gid] = s
        return out

    def value_at(self, s, tf, mode, period=None):
        t = transform(s, tf, mode) if tf and tf != "level" else s
        if t is None:
            return None, NAN
        if period is None:
            return t.last()
        return period, t.at(period)
