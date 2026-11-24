"""Latest-value snapshots for every metric x transform x geography level.
These power the map coloring and the rankings table (one row read per layer)."""

import json
from collections import Counter

from .engine import STALE, Engine, last_transform
from .metrics import METRICS
from .util import log, now_midx, period_str, smart_round

LEVELS = ["us", "state", "metro", "county", "zip"]


def build(con, cfg, report=None, metrics=None, levels=None):
    eng = Engine(con, cfg)
    avail = eng.available()
    rows = []
    total = 0
    written = set()
    for m in METRICS:
        mid = m["id"]
        if metrics and mid not in metrics:
            continue
        for level in (levels or LEVELS):
            if level not in avail.get(mid, []):
                continue
            win = (now_midx() - 140) if m["kind"] == "virtual" else None
            data = eng.level_series(mid, level, window_start=win)
            if not data:
                continue
            freq = next(iter(data.values())).freq
            for tf in m["transforms"]:
                vals = {}
                periods = Counter()
                for gid, s in data.items():
                    p, v = last_transform(s, tf, m["change"])
                    if p is None or v != v:
                        continue
                    vals[gid] = (p, v)
                    periods[p] += 1
                if not vals:
                    continue
                maxp = max(periods)
                # use the most recent period that has broad coverage (avoids one early reporter)
                if len(vals) > 20:
                    cutoff = 0.5 * max(periods.values())
                    for p in sorted(periods, reverse=True):
                        if periods[p] >= cutoff or p == min(periods):
                            maxp = p
                            break
                lag = STALE.get(freq, 3)
                d = {g: smart_round(v) for g, (p, v) in vals.items() if maxp - lag <= p <= maxp}
                d = {g: v for g, v in d.items() if v is not None}
                if not d:
                    continue
                rows.append((mid, tf, level, period_str(freq, maxp), len(d), json.dumps(d, separators=(",", ":"))))
                written.add((mid, tf, level))
                total += 1
            if report:
                report("Building map layers: %s (%s)" % (m["name"], level))
        if len(rows) > 50:
            _flush(con, rows)
            rows = []
    _flush(con, rows)
    if not metrics and not levels:
        stale = [k for k in con.execute("SELECT metric, transform, level FROM snap") if tuple(k) not in written]
        if stale:
            con.execute("BEGIN")
            con.executemany("DELETE FROM snap WHERE metric=? AND transform=? AND level=?", stale)
            con.execute("COMMIT")
    log.info("  snapshots: %d layers", total)
    return total


def _flush(con, rows):
    if not rows:
        return
    con.execute("BEGIN")
    con.executemany("INSERT OR REPLACE INTO snap(metric,transform,level,period,n,data) VALUES(?,?,?,?,?,?)", rows)
    con.execute("COMMIT")
