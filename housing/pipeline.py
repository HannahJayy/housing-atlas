"""Update orchestration: download every enabled source, then compute derived
metrics, scores and map snapshots. Used by the CLI, the UI button and the scheduler."""

import json
import os
import threading
import time
import traceback

from . import derive, scores, snapshot
from .config import DATA_DIR, load_config
from .context import Context
from .db import connect, get_meta, now_str, set_meta, set_status
from .download import Cancelled, Downloader
from .sources import SOURCE_ORDER, get_module
from .util import Timer, log

LOCK = os.path.join(DATA_DIR, "update.lock")
RAW_DIR = os.path.join(DATA_DIR, "raw")
GEO_DIR = os.path.join(DATA_DIR, "geo")

# Re-process slow-changing sources at most this often (days) unless forced.
REFRESH_DAYS = {"boundaries": 120, "census_pep": 30, "census_acs": 30, "bea": 30, "fema_nri": 60}


class UpdateState:
    """Shared, thread-safe progress info (read by the web UI)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.started = None
        self.finished = None
        self.step = None
        self.message = ""
        self.lines = []
        self.result = None
        self.cancel = threading.Event()

    def report(self, msg):
        with self.lock:
            self.message = msg
            self.lines.append("%s  %s" % (time.strftime("%H:%M:%S"), msg))
            self.lines = self.lines[-300:]

    def snapshot(self):
        with self.lock:
            return {"running": self.running, "started": self.started, "finished": self.finished,
                    "step": self.step, "message": self.message, "log": list(self.lines[-120:]),
                    "result": self.result}


STATE = UpdateState()


def _pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        # never use os.kill on Windows (it terminates the process); ask the OS instead
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_lock():
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(LOCK):
        age = time.time() - os.path.getmtime(LOCK)
        if age < 6 * 3600:
            try:
                with open(LOCK) as f:
                    pid = int(f.read().strip() or 0)
            except Exception:
                pid = 0
            if pid != os.getpid() and _pid_alive(pid):
                return False
    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))
    return True


def _release_lock():
    try:
        os.remove(LOCK)
    except OSError:
        pass


def _due(con, name, force):
    if force:
        return True
    days = REFRESH_DAYS.get(name)
    if not days:
        return True
    if name == "boundaries" and not os.path.exists(os.path.join(GEO_DIR, "county.json")):
        return True
    row = con.execute("SELECT last_success FROM source_status WHERE source=?", (name,)).fetchone()
    if not row or not row[0]:
        return True
    try:
        t = time.mktime(time.strptime(row[0], "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return True
    return (time.time() - t) > days * 86400


def run_update(sources=None, force=False, skip_derive=False, cfg=None, state=None):
    """Run an update. sources: list of source ids (default: all enabled)."""
    state = state or STATE
    cfg = cfg or load_config()
    if not _acquire_lock():
        msg = "Another update is already running."
        state.report(msg)
        return {"ok": False, "message": msg}
    with state.lock:
        state.running = True
        state.started = now_str()
        state.finished = None
        state.result = None
        state.lines = []
        state.cancel.clear()
    t = Timer()
    con = connect()
    summary = {}
    try:
        dl = Downloader(cfg, con, RAW_DIR, cancel_event=state.cancel, progress=state.report)
        ctx = Context(cfg, con, dl, report=state.report, cancel_event=state.cancel, force=force)
        for row in con.execute("SELECT source,status,last_success,message,details FROM source_status"):
            ctx.previous[row[0]] = {"status": row[1], "last_success": row[2], "message": row[3], "details": row[4]}
        requested = set(sources) if sources else None
        order = []
        for name in SOURCE_ORDER:
            scfg = (cfg.get("sources") or {}).get(name, {})
            if requested is not None and name not in requested:
                continue
            if requested is None and not scfg.get("enabled", True):
                continue
            order.append(name)
        # Geography must exist before anything else can be matched.
        has_geo = con.execute("SELECT COUNT(*) FROM geos WHERE level='county'").fetchone()[0] > 0
        if not has_geo:
            for need in ("census_pep", "boundaries"):
                if need not in order:
                    order.insert(0, need)
            order.sort(key=SOURCE_ORDER.index)
        for name in order:
            if state.cancel.is_set():
                raise Cancelled()
            if not _due(con, name, force or (requested is not None)):
                summary[name] = "skipped (refreshed recently)"
                continue
            with state.lock:
                state.step = name
            mod = get_module(name)
            state.report("=== %s ===" % mod.INFO["name"])
            set_status(con, name, "running", "Updating...")
            st = Timer()
            try:
                res = mod.run(ctx) or {}
                if res.get("unchanged"):
                    prev = ctx.previous.get(name) or {}
                    try:
                        pdet = json.loads(prev.get("details") or "{}")
                    except ValueError:
                        pdet = {}
                    msg = (prev.get("message") or "").replace(" (no new files this run)", "") + " (no new files this run)"
                    set_status(con, name, prev.get("status") or "ok", msg, pdet, success=True)
                    summary[name] = "unchanged"
                    state.report("%s: no new files since the last update - kept existing data" % name)
                    continue
                ok = res.get("ok", True)
                status = "ok" if ok and not res.get("warn") else ("warning" if ok else "failed")
                details = dict(res.get("details") or {})
                details["latest_period"] = res.get("latest")
                details["seconds"] = round(time.time() - st.t0, 1)
                set_status(con, name, status, res.get("message", ""), details, success=ok)
                summary[name] = "%s: %s" % (status, res.get("message", ""))
                state.report("%s finished in %s: %s" % (name, st, res.get("message", "")))
            except Cancelled:
                set_status(con, name, "failed", "Cancelled")
                raise
            except Exception as e:
                log.error("source %s failed: %s\n%s", name, e, traceback.format_exc())
                set_status(con, name, "failed", str(e)[:500], {"trace": traceback.format_exc()[-2000:]})
                summary[name] = "failed: %s" % e
                state.report("%s FAILED: %s" % (name, e))
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
            ctx.geo.reload()
            # First run: publish home-value layers as soon as Zillow is in, so the map is usable
            # while the remaining (slower) sources download.
            if name == "zillow" and not skip_derive and con.execute("SELECT COUNT(*) FROM snap").fetchone()[0] == 0:
                try:
                    state.report("Publishing first map layers (home values, rents)...")
                    finalize_geos(con)
                    snapshot.build(con, cfg, None, metrics=["zhvi", "zhvi_sfr", "zhvi_condo", "rent"])
                    set_meta(con, "last_derive", now_str())
                except Exception as e:
                    log.warning("early snapshot failed: %s", e)
        if not skip_derive:
            with state.lock:
                state.step = "derive"
            state.report("=== Computing derived metrics ===")
            try:
                finalize_geos(con)
                derive.run(con, cfg, state.report)
                scores.run(con, cfg, state.report)
                snapshot.build(con, cfg, state.report)
                set_meta(con, "last_derive", now_str())
                summary["derived"] = "ok"
            except Cancelled:
                raise
            except Exception as e:
                log.error("derive failed: %s\n%s", e, traceback.format_exc())
                summary["derived"] = "failed: %s" % e
                state.report("Derived metrics FAILED: %s" % e)
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
        set_meta(con, "last_update", now_str())
        try:
            con.execute("PRAGMA incremental_vacuum")
        except Exception:
            pass
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        result = {"ok": True, "message": "Update finished in %s" % t, "summary": summary}
        state.report(result["message"])
        return result
    except Cancelled:
        state.report("Update cancelled.")
        return {"ok": False, "message": "cancelled", "summary": summary}
    except Exception as e:
        log.error("update failed: %s\n%s", e, traceback.format_exc())
        state.report("Update failed: %s" % e)
        return {"ok": False, "message": str(e), "summary": summary}
    finally:
        with state.lock:
            state.running = False
            state.finished = now_str()
            state.step = None
        try:
            con.close()
        except Exception:
            pass
        _release_lock()


def finalize_geos(con):
    """Fill parent links/names that depend on several sources."""
    con.execute("BEGIN")
    con.execute("UPDATE geos SET metro_id=(SELECT b FROM xw WHERE kind='county_cbsa' AND a=geos.geo_id) "
                "WHERE level='county' AND metro_id IS NULL")
    con.execute("UPDATE geos SET county_id=(SELECT b FROM xw WHERE kind='zip_county' AND a=geos.geo_id) "
                "WHERE level='zip' AND county_id IS NULL")
    con.execute("UPDATE geos SET metro_id=(SELECT g.metro_id FROM geos g WHERE g.level='county' "
                "AND g.geo_id=geos.county_id) WHERE level='zip' AND metro_id IS NULL")
    con.execute("UPDATE geos SET state=(SELECT g.state FROM geos g WHERE g.level='county' "
                "AND g.geo_id=geos.county_id) WHERE level='zip' AND state IS NULL")
    # regions that only appear in data files (no shape) still need a readable name
    con.execute("UPDATE geos SET name=geo_id WHERE name IS NULL")
    con.execute("COMMIT")


def start_background_update(sources=None, force=False):
    if STATE.running:
        return False
    th = threading.Thread(target=run_update, kwargs={"sources": sources, "force": force}, daemon=True,
                          name="update")
    th.start()
    return True


def rebuild_derived(cfg=None):
    """Recompute derived metrics + snapshots only (e.g. after Settings changed)."""
    cfg = cfg or load_config()
    con = connect()
    try:
        derive.run(con, cfg, STATE.report)
        scores.run(con, cfg, STATE.report)
        snapshot.build(con, cfg, STATE.report)
    finally:
        con.close()
