"""Small shared helpers: dates, number parsing, names, logging."""

import logging
import math
import os
import re
import sys
import time
import unicodedata

NAN = float("nan")

log = logging.getLogger("housing")


def setup_logging(log_dir=None, verbose=False):
    """Configure console + (optional) file logging. Safe to call more than once."""
    root = logging.getLogger("housing")
    if getattr(root, "_configured", False):
        return root
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    # Windows consoles can choke on non-ASCII; never let logging crash the app.
    try:
        sh.stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    root.addHandler(sh)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.FileHandler(os.path.join(log_dir, "housing.log"), encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    root._configured = True  # type: ignore[attr-defined]
    return root


# ----------------------------------------------------------------------------
# Period indexes
#   Monthly 'M':  idx = year*12 + (month-1)
#   Quarterly 'Q': idx = year*4 + (quarter-1)
#   Annual 'A':   idx = year
# ----------------------------------------------------------------------------

def midx(year, month):
    return int(year) * 12 + int(month) - 1


def midx_parts(i):
    return i // 12, i % 12 + 1


def midx_str(i):
    y, m = midx_parts(i)
    return "%04d-%02d" % (y, m)


def period_str(freq, i):
    if i is None:
        return None
    if freq == "M":
        return midx_str(i)
    if freq == "Q":
        return "%04d-Q%d" % (i // 4, i % 4 + 1)
    return "%04d" % i


def parse_period(freq, s):
    """Inverse of period_str."""
    if s is None or s == "":
        return None
    s = str(s)
    if freq == "M":
        return parse_month(s)
    if freq == "Q":
        m = re.match(r"^(\d{4})-?Q([1-4])$", s)
        if m:
            return int(m.group(1)) * 4 + int(m.group(2)) - 1
        mi = parse_month(s)
        return None if mi is None else (mi // 12) * 4 + (mi % 12) // 3
    m = re.match(r"^(\d{4})", s)
    return int(m.group(1)) if m else None


_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_month(s):
    """Parse many date spellings into a monthly index. Returns None if unparseable.

    Accepts: 2024-05-31, 2024-05, 202405, 5/31/2024, 2024/05/31, May-24, May 2024.
    """
    if s is None:
        return None
    s = str(s).strip().strip('"').strip()
    if not s:
        return None
    m = re.match(r"^(\d{4})[-/](\d{1,2})(?:[-/]\d{1,2})?(?:[ T].*)?$", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return midx(y, mo)
        return None
    m = re.match(r"^(\d{4})(\d{2})$", s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return midx(y, mo)
        return None
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        return midx(int(m.group(3)), int(m.group(1)))
    m = re.match(r"^([A-Za-z]{3})[A-Za-z]*[-\s'](\d{2,4})", s)
    if m and m.group(1).lower() in _MONTHS:
        y = int(m.group(2))
        if y < 100:
            y += 2000 if y < 70 else 1900
        return midx(y, _MONTHS[m.group(1).lower()])
    return None


def month_to_quarter(mi):
    return (mi // 12) * 4 + (mi % 12) // 3


def now_midx():
    t = time.localtime()
    return midx(t.tm_year, t.tm_mon)


# ----------------------------------------------------------------------------
# Numbers
# ----------------------------------------------------------------------------

_MISSING = {"", "na", "n/a", "nan", ".", "null", "none", "(na)", "(d)", "(nm)", "(l)",
            "(x)", "-", "--", "***", "**", "*", "(s)", "nd", "#n/a", "inf", "-inf"}


def to_float(s):
    """Parse a messy number string -> float or NaN."""
    if s is None:
        return NAN
    if isinstance(s, (int, float)):
        f = float(s)
        return f if math.isfinite(f) else NAN
    t = s.strip().strip('"').strip()
    if t.lower() in _MISSING:
        return NAN
    t = t.replace(",", "").replace("$", "").replace("%", "")
    if t.endswith("(p)") or t.endswith("(P)"):
        t = t[:-3].strip()
    try:
        f = float(t)
    except ValueError:
        return NAN
    return f if math.isfinite(f) else NAN


def isnan(x):
    return x is None or (isinstance(x, float) and x != x)


def finite(x):
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def median(vals):
    v = sorted(x for x in vals if finite(x))
    if not v:
        return NAN
    n = len(v)
    return v[n // 2] if n % 2 else 0.5 * (v[n // 2 - 1] + v[n // 2])


def mean(vals):
    v = [x for x in vals if finite(x)]
    return sum(v) / len(v) if v else NAN


def percentile_sorted(sorted_vals, q):
    """q in [0,1] on an already sorted list (linear interpolation)."""
    n = len(sorted_vals)
    if n == 0:
        return NAN
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def clean_json_number(x, digits=None):
    if x is None:
        return None
    if isinstance(x, float):
        if x != x or x in (float("inf"), float("-inf")):
            return None
        if digits is not None:
            return round(x, digits)
    return x


def smart_round(x):
    """Round to a sensible number of significant digits for JSON payloads."""
    if x is None or not isinstance(x, float):
        return x
    if x != x or math.isinf(x):
        return None
    a = abs(x)
    if a >= 1000:
        return round(x)
    if a >= 100:
        return round(x, 1)
    if a >= 1:
        return round(x, 2)
    if a >= 0.01:
        return round(x, 4)
    return round(x, 6)


# ----------------------------------------------------------------------------
# Names
# ----------------------------------------------------------------------------

def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


_COUNTY_WORDS = re.compile(
    r"\b(county|parish|borough|census area|city and borough|municipality|municipio|planning region)\b")


def norm_name(s):
    """Normalize a place name for fuzzy-but-safe matching."""
    if s is None:
        return ""
    s = strip_accents(str(s)).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\bsaint\b", "st", s)
    s = re.sub(r"\bste\.?\b", "ste", s)
    s = re.sub(r"\bst\.", "st", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_county(s):
    """Normalize a county name, dropping the 'County'/'Parish' suffix but keeping 'city'."""
    s = norm_name(s)
    s = _COUNTY_WORDS.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def short_metro_name(full_name):
    """'Austin-Round Rock-San Marcos, TX' -> 'Austin, TX'.
    'Louisville/Jefferson County, KY-IN' -> 'Louisville, KY'."""
    if not full_name:
        return full_name
    name = re.sub(r"\s+(Metro|Micro)(politan)?( Statistical)?( Area)?$", "", full_name.strip())
    if "," in name:
        cities, states = name.rsplit(",", 1)
        city = cities.split("-")[0].split("/")[0].strip()
        st = states.strip().split("-")[0].strip()
        return "%s, %s" % (city, st)
    return name


def human_bytes(n):
    try:
        n = float(n)
    except Exception:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (n, unit)
        n /= 1024.0
    return "%.1f TB" % n


class Timer:
    def __init__(self):
        self.t0 = time.time()

    def __str__(self):
        return "%.1fs" % (time.time() - self.t0)
