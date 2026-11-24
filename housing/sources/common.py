"""Helpers shared by source modules."""

import csv
import gzip
import io
import os
import time

from ..db import SeriesWriter, delete_source, put_dict_series
from ..util import log


def read_text(path):
    """Read a whole text file, tolerating UTF-8 (with BOM) or Latin-1."""
    with open(path, "rb") as f:
        data = f.read()
    if path.endswith(".gz") or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", "replace")


def open_text(path):
    """Open (possibly gzipped) text file for streaming."""
    with open(path, "rb") as f:
        magic = f.read(2)
    raw = gzip.open(path, "rb") if magic == b"\x1f\x8b" else open(path, "rb")
    return io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")


def csv_dicts(path, delimiter=","):
    text = read_text(path)
    rdr = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(rdr)
    except StopIteration:
        return [], []
    header = [h.strip() for h in header]
    rows = []
    for r in rdr:
        if not r:
            continue
        rows.append(dict(zip(header, r)))
    return header, rows


def upsert_geo(con, level, geo_id, **fields):
    """Insert a geography row or fill in missing fields (never blanks existing values)."""
    cols = ["level", "geo_id"] + list(fields.keys())
    vals = [level, geo_id] + list(fields.values())
    sets = ", ".join("%s=COALESCE(excluded.%s,%s)" % (k, k, k) for k in fields) or "level=level"
    con.execute("INSERT INTO geos(%s) VALUES(%s) ON CONFLICT(level,geo_id) DO UPDATE SET %s"
                % (",".join(cols), ",".join("?" * len(cols)), sets), vals)


def set_geo_field(con, level, geo_id, field, value, overwrite=True):
    upsert_geo(con, level, geo_id)
    if overwrite:
        con.execute("UPDATE geos SET %s=? WHERE level=? AND geo_id=?" % field, (value, level, geo_id))
    else:
        con.execute("UPDATE geos SET %s=COALESCE(%s,?) WHERE level=? AND geo_id=?" % (field, field),
                    (value, level, geo_id))


class Store:
    """Collects {metric: {level: {geo: {period: value}}}} then writes it in one go."""

    def __init__(self, freq="M"):
        self.freq = freq
        self.data = {}

    def add(self, metric, level, geo, period, value):
        if value is None or value != value:
            return
        self.data.setdefault(metric, {}).setdefault(level, {}).setdefault(geo, {})[period] = value

    def count(self):
        return sum(len(g) for m in self.data.values() for l in m.values() for g in l.values())

    def write(self, writer, freq=None):
        n = 0
        for metric, levels in self.data.items():
            for level, geos in levels.items():
                put_dict_series(writer, metric, level, freq or self.freq, geos)
                n += len(geos)
        return n


def replace_source_series(con, src, stores_and_freqs, extra_rows=None):
    """Atomically replace every series of a source with freshly parsed data."""
    con.execute("BEGIN")
    try:
        delete_source(con, src)
        w = SeriesWriter(con, src)
        for store, freq in stores_and_freqs:
            store.write(w, freq)
        if extra_rows:
            for row in extra_rows:
                w.put(*row)
        w.flush()
        con.execute("COMMIT")
        return w.count
    except Exception:
        con.execute("ROLLBACK")
        raise


def newest_available(ctx, key, url_fmt, years, **fmt):
    """Return (year, url) for the newest URL that exists among candidate years."""
    for y in years:
        url = url_fmt.format(y=y, yy="%02d" % (y % 100), **fmt)
        if ctx.dl.exists(key, url):
            return y, url
    return None, None


def this_year():
    return time.localtime().tm_year


def pct_scale(values):
    """Detect whether a share is stored as a fraction (0.25) or percent (25) -> multiplier."""
    vals = sorted(abs(v) for v in values if v == v)
    if not vals:
        return 1.0
    p90 = vals[int(0.9 * (len(vals) - 1))]
    return 100.0 if p90 <= 1.5 else 1.0


def file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def log_skip(what, why):
    log.warning("  skipped %s: %s", what, why)
