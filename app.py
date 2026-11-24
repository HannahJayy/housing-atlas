#!/usr/bin/env python3
"""Housing Atlas - self-hosted housing market data explorer.

  python app.py                 start the website (opens your browser)
  python app.py serve --host 0.0.0.0     also reachable from your phone on the same Wi-Fi
  python app.py update          download/refresh all data now (same as the button in the app)
  python app.py update --only zillow,realtor   refresh selected sources
  python app.py status          show data source status
  python app.py install-schedule   register a weekly update with Windows Task Scheduler / cron
  python app.py rebuild         recompute derived metrics and map layers only

Requires only Python 3.8+ (no extra packages).
"""

import argparse
import os
import subprocess
import sys

if sys.version_info < (3, 8):
    sys.exit("Housing Atlas needs Python 3.8 or newer (you have %s)." % sys.version.split()[0])

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from housing import APP_NAME, __version__  # noqa: E402
from housing.config import DATA_DIR, load_config  # noqa: E402
from housing.util import setup_logging  # noqa: E402


def cmd_serve(args):
    cfg = load_config()
    host = args.host or cfg["server"].get("host", "127.0.0.1")
    port = args.port or int(cfg["server"].get("port", 8765))
    from housing import pipeline
    from housing.db import connect
    from housing.server import serve
    con = connect()
    empty = con.execute("SELECT 1 FROM snap LIMIT 1").fetchone() is None
    con.close()
    if empty and not getattr(args, "no_auto_update", False):
        print("\nFirst run: downloading housing data in the background (roughly 15-45 minutes, a few GB).")
        print("You can use the website meanwhile - progress shows at the top of the page.\n")
        pipeline.start_background_update()
    serve(host, port, open_browser=(not args.no_browser and cfg["server"].get("open_browser", True)))


def cmd_update(args):
    from housing import pipeline
    sources = [s.strip() for s in args.only.split(",")] if args.only else None
    res = pipeline.run_update(sources=sources, force=args.force)
    print()
    print(res.get("message"))
    for k, v in (res.get("summary") or {}).items():
        print("  %-12s %s" % (k, v))
    return 0 if res.get("ok") else 1


def cmd_status(args):
    from housing.db import connect, get_meta
    con = connect()
    print("%s %s - data folder: %s" % (APP_NAME, __version__, DATA_DIR))
    print("Last update: %s" % (get_meta(con, "last_update") or "never"))
    for src, status, last, ok, msg in con.execute(
            "SELECT source, status, last_attempt, last_success, message FROM source_status"):
        print("  %-11s %-8s last ok %-19s %s" % (src, status, ok or "-", (msg or "")[:90]))


def cmd_rebuild(args):
    from housing import pipeline
    pipeline.rebuild_derived()
    print("Derived metrics and map layers rebuilt.")


def cmd_export_static(args):
    from housing import static_export
    default_hist = static_export.DEFAULT_HISTORY
    hist = tuple(x.strip() for x in args.history.split(",") if x.strip()) if args.history else default_hist
    res = static_export.export(os.path.abspath(args.out), bundle=args.bundle, preview=args.preview, history=hist,
                               report=print, hosted=args.hosted, max_mb=args.max_mb)
    print("Open it from any static web host, or test it locally with:\n  python -m http.server 8800 --directory \"%s\""
          "\nthen visit http://127.0.0.1:8800" % res["out"])


def cmd_install_schedule(args):
    cfg = load_config()
    sch = cfg.get("schedule") or {}
    hour = int(sch.get("hour", 3))
    wd = int(sch.get("weekday", 6))
    py = sys.executable
    script = os.path.join(ROOT, "app.py")
    if os.name == "nt":
        days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
        cmd = ["schtasks", "/Create", "/F", "/SC", "WEEKLY", "/D", days[wd], "/ST", "%02d:00" % hour,
               "/TN", "HousingAtlasWeeklyUpdate", "/TR", '"%s" "%s" update' % (py, script)]
        print("Running:", " ".join(cmd))
        if getattr(args, "dry_run", False):
            return 0
        r = subprocess.run(cmd)
        print("Done." if r.returncode == 0 else "schtasks failed - try running this terminal as Administrator.")
        return r.returncode
    cron_day = (wd + 1) % 7  # cron: 0=Sunday
    line = '0 %d * * %d cd "%s" && "%s" "%s" update >> "%s" 2>&1  # HousingAtlas' % (
        hour, cron_day, ROOT, py, script, os.path.join(DATA_DIR, "logs", "cron.log"))
    if getattr(args, "dry_run", False):
        print("Would add this cron line:\n  " + line)
        return 0
    try:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        print("crontab not found. Add this line to your scheduler manually:\n" + line)
        return 1
    lines = [l for l in cur.splitlines() if "# HousingAtlas" not in l]
    lines.append(line)
    r = subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True)
    print("Installed weekly cron job:\n  " + line if r.returncode == 0 else "Could not install cron job.")
    return r.returncode


def main():
    p = argparse.ArgumentParser(description="%s - self-hosted housing market data" % APP_NAME)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="start the website (default)")
    s.add_argument("--host", default=None, help="127.0.0.1 (this computer only) or 0.0.0.0 (your network)")
    s.add_argument("--port", type=int, default=None)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--no-auto-update", action="store_true", help="don't start the first download automatically")
    u = sub.add_parser("update", help="download / refresh data")
    u.add_argument("--only", default=None, help="comma-separated source ids, e.g. zillow,realtor")
    u.add_argument("--force", action="store_true", help="re-process yearly sources too")
    sub.add_parser("status", help="show data source status")
    sub.add_parser("rebuild", help="recompute derived metrics & map layers")
    ex = sub.add_parser("export-static", help="write a static copy of the website that needs no Python server")
    ex.add_argument("out", nargs="?", default="site", help="output folder (default: ./site)")
    ex.add_argument("--bundle", action="store_true", help="pack data into a few large files (small datasets)")
    ex.add_argument("--preview", action="store_true", help="label the copy as a sample-data preview")
    ex.add_argument("--history", default=None, help="levels with a map time slider (default us,state,metro,county)")
    ex.add_argument("--hosted", action="store_true",
                    help="fit a free static host such as GitHub Pages (trims ZIP-code history to stay under --max-mb)")
    ex.add_argument("--max-mb", type=int, default=900, help="size limit for --hosted (default 900)")
    sch = sub.add_parser("install-schedule", help="register a weekly update with the OS scheduler")
    sch.add_argument("--dry-run", action="store_true", help="only print what would be installed")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    setup_logging(os.path.join(DATA_DIR, "logs"), verbose=args.verbose)
    if args.cmd in (None, "serve"):
        if args.cmd is None:
            args.host, args.port, args.no_browser, args.no_auto_update = None, None, False, False
        return cmd_serve(args)
    return {"update": cmd_update, "status": cmd_status, "rebuild": cmd_rebuild, "export-static": cmd_export_static,
            "install-schedule": cmd_install_schedule}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main() or 0)
