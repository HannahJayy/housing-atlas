"""Weekly automatic refresh while the server is running (plus catch-up if the computer
was off at the scheduled time). OS-level scheduling scripts live in /scripts."""

import threading
import time

from . import pipeline
from .config import load_config
from .db import connect, get_meta, set_meta
from .util import log


def _parse(ts):
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return 0


def next_run_text(cfg):
    sch = cfg.get("schedule") or {}
    if not sch.get("enabled"):
        return "Automatic updates are off"
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return "Every %s at %02d:00 (while the app is running)" % (days[int(sch.get("weekday", 6)) % 7],
                                                               int(sch.get("hour", 3)))


def _due(cfg, con):
    sch = cfg.get("schedule") or {}
    if not sch.get("enabled"):
        return False
    last = _parse(get_meta(con, "last_update") or "")
    if last == 0:
        return False  # first download is started by the user
    age = time.time() - last
    now = time.localtime()
    if age > 8 * 86400:
        return True  # missed a week (computer was off) - catch up
    return (now.tm_wday == int(sch.get("weekday", 6)) and now.tm_hour >= int(sch.get("hour", 3))
            and age > 6 * 86400)


def loop(stop_event):
    time.sleep(30)
    while not stop_event.is_set():
        try:
            cfg = load_config()
            con = connect()
            try:
                due = _due(cfg, con)
            finally:
                con.close()
            if due and not pipeline.STATE.running:
                log.info("scheduler: starting weekly update")
                pipeline.run_update(cfg=cfg)
        except Exception as e:  # never let the scheduler thread die
            log.warning("scheduler error: %s", e)
        stop_event.wait(600)


def start():
    ev = threading.Event()
    th = threading.Thread(target=loop, args=(ev,), daemon=True, name="scheduler")
    th.start()
    return ev
