"""SQLite storage. Time series are stored compactly as float32 arrays (one row per
metric/level/region), which keeps 30,000 ZIP codes x 25 years manageable."""

import json
import math
import os
import sqlite3
import sys
import threading
import time
from array import array

from .config import DATA_DIR

NAN = float("nan")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS geos(
  level TEXT NOT NULL, geo_id TEXT NOT NULL, name TEXT, full_name TEXT, state TEXT,
  metro_id TEXT, county_id TEXT, city TEXT, lsad TEXT,
  lat REAL, lon REAL, minx REAL, miny REAL, maxx REAL, maxy REAL,
  aland REAL, population REAL, has_shape INTEGER DEFAULT 0,
  PRIMARY KEY(level, geo_id)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS series(
  id INTEGER PRIMARY KEY,
  metric TEXT NOT NULL, level TEXT NOT NULL, geo_id TEXT NOT NULL,
  freq TEXT NOT NULL, start INTEGER NOT NULL, vals BLOB NOT NULL, src TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS series_key ON series(metric, level, geo_id);
CREATE INDEX IF NOT EXISTS series_src ON series(src);
CREATE TABLE IF NOT EXISTS snap(
  metric TEXT NOT NULL, transform TEXT NOT NULL, level TEXT NOT NULL,
  period TEXT, n INTEGER, data TEXT,
  PRIMARY KEY(metric, transform, level)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS macro(
  sid TEXT PRIMARY KEY, name TEXT, units TEXT, freq TEXT, src TEXT,
  category TEXT, dates TEXT, vals TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS xw(
  kind TEXT NOT NULL, a TEXT NOT NULL, b TEXT NOT NULL, w REAL,
  PRIMARY KEY(kind, a, b)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS source_status(
  source TEXT PRIMARY KEY, status TEXT, last_attempt TEXT, last_success TEXT,
  message TEXT, details TEXT);
CREATE TABLE IF NOT EXISTS files(
  url TEXT PRIMARY KEY, path TEXT, status TEXT, http INTEGER, bytes INTEGER,
  fetched TEXT, modified TEXT, etag TEXT, source TEXT, key TEXT);
"""

DB_PATH = os.path.join(DATA_DIR, "housing.db")

_BIG = sys.byteorder == "big"


def connect(path=None, readonly=False):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    con = sqlite3.connect(path, timeout=60, check_same_thread=False, isolation_level=None)
    if new:
        con.execute("PRAGMA auto_vacuum=INCREMENTAL")  # lets updates hand freed space back to disk
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA cache_size=-65536")
    con.execute("PRAGMA temp_store=MEMORY")
    if not readonly:
        con.executescript(SCHEMA)
    return con


_tls = threading.local()


def thread_conn():
    """One connection per server thread (SQLite connections aren't shareable safely)."""
    con = getattr(_tls, "con", None)
    if con is None:
        con = connect(readonly=False)
        _tls.con = con
    return con


# ----------------------------------------------------------------------------
# Series encoding
# ----------------------------------------------------------------------------

def encode(values):
    arr = array("f", [(v if (v is not None and v == v) else NAN) for v in values])
    if _BIG:
        arr.byteswap()
    return arr.tobytes()


def decode_array(blob):
    """float32 array (4 bytes/value) - used for bulk loads to keep memory low."""
    arr = array("f")
    arr.frombytes(blob)
    if _BIG:
        arr.byteswap()
    return arr


def decode(blob):
    return decode_array(blob).tolist()


def trim(start, values):
    """Drop leading/trailing missing values. Returns (start, values) or (None, None)."""
    n = len(values)
    i = 0
    while i < n and not (values[i] == values[i]):
        i += 1
    if i == n:
        return None, None
    j = n - 1
    while j > i and not (values[j] == values[j]):
        j -= 1
    return start + i, values[i:j + 1]


class SeriesWriter:
    """Buffered bulk writer for the series table."""

    def __init__(self, con, src, batch=2000):
        self.con = con
        self.src = src
        self.batch = batch
        self.rows = []
        self.count = 0

    def put(self, metric, level, geo_id, freq, start, values):
        if start is None or not values:
            return
        s, v = trim(start, values)
        if s is None:
            return
        self.rows.append((metric, level, geo_id, freq, s, encode(v), self.src))
        if len(self.rows) >= self.batch:
            self.flush()

    def flush(self):
        if self.rows:
            self.con.executemany(
                "INSERT OR REPLACE INTO series(metric,level,geo_id,freq,start,vals,src) VALUES(?,?,?,?,?,?,?)",
                self.rows)
            self.count += len(self.rows)
            self.rows = []


def put_dict_series(writer, metric, level, freq, data):
    """data: {geo_id: {period_idx: value}} -> writes one contiguous series per geo."""
    for geo, pts in data.items():
        if not pts:
            continue
        lo, hi = min(pts), max(pts)
        vals = [NAN] * (hi - lo + 1)
        for k, v in pts.items():
            vals[k - lo] = v
        writer.put(metric, level, geo, freq, lo, vals)


def delete_source(con, src):
    con.execute("DELETE FROM series WHERE src=?", (src,))


def get_meta(con, key, default=None):
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except Exception:
        return row[0]


def set_meta(con, key, value):
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, json.dumps(value)))


def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def set_status(con, source, status, message="", details=None, success=False):
    now = now_str()
    row = con.execute("SELECT last_success FROM source_status WHERE source=?", (source,)).fetchone()
    last_success = now if success else (row[0] if row else None)
    con.execute(
        "INSERT OR REPLACE INTO source_status(source,status,last_attempt,last_success,message,details) VALUES(?,?,?,?,?,?)",
        (source, status, now, last_success, message, json.dumps(details or {})))
