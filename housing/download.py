"""HTTP downloads with conditional requests (ETag / Last-Modified), retries and
progress reporting. Only uses urllib from the standard library."""

import email.utils
import os
import re
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from . import __version__
from .db import now_str
from .util import human_bytes, log


class DownloadResult:
    def __init__(self, url, path=None, status="failed", http=None, size=0, error=None):
        self.url = url
        self.path = path
        self.status = status  # downloaded | not_modified | cached | failed | missing
        self.http = http
        self.size = size
        self.error = error

    @property
    def ok(self):
        return self.status in ("downloaded", "not_modified", "cached") and self.path and os.path.exists(self.path)

    def __repr__(self):
        return "<Download %s %s %s>" % (self.status, self.http, self.url)


class Cancelled(Exception):
    pass


def _ssl_context():
    ctx = None
    try:
        import certifi  # optional, not required
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    return ctx


class Downloader:
    def __init__(self, cfg, con, raw_dir, cancel_event=None, progress=None):
        self.cfg = cfg
        self.con = con
        self.raw_dir = raw_dir
        self.cancel_event = cancel_event
        self.progress = progress  # callable(message)
        self.timeout = float(cfg.get("download", {}).get("timeout", 120))
        self.retries = int(cfg.get("download", {}).get("retries", 3))
        email_addr = (cfg.get("contact_email") or "").strip()
        contact = (" contact: %s" % email_addr) if email_addr else ""
        self.user_agent = "Mozilla/5.0 (compatible; HousingAtlas/%s; personal housing research;%s)" % (
            __version__, contact)
        self.ctx = _ssl_context()
        os.makedirs(raw_dir, exist_ok=True)

    # ------------------------------------------------------------------
    def resolve(self, key, url):
        """Apply user URL overrides (by key) and rewrite rules (testing/mirrors)."""
        url = (self.cfg.get("url_overrides") or {}).get(key) or url
        for rule in self.cfg.get("url_rewrite") or []:
            try:
                prefix, repl = rule
            except Exception:
                continue
            if url.startswith(prefix):
                url = repl + url[len(prefix):]
        return url

    def _check_cancel(self):
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise Cancelled()

    def _headers(self, extra=None):
        h = {"User-Agent": self.user_agent, "Accept": "*/*"}
        if extra:
            h.update(extra)
        return h

    def _record(self, url, path, status, http, size, modified=None, etag=None, source=None, key=None):
        try:
            self.con.execute(
                "INSERT OR REPLACE INTO files(url,path,status,http,bytes,fetched,modified,etag,source,key) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (url, path, status, http, size, now_str(), modified, etag, source, key))
        except Exception as e:  # never fail a download because of bookkeeping
            log.debug("could not record file %s: %s", url, e)

    def _previous(self, url):
        try:
            return self.con.execute(
                "SELECT path, modified, etag FROM files WHERE url=?", (url,)).fetchone()
        except Exception:
            return None

    def local_path(self, source, url, dest_name=None):
        name = dest_name or os.path.basename(urllib.parse.urlparse(url).path) or "download"
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        d = os.path.join(self.raw_dir, source)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, name)

    # ------------------------------------------------------------------
    def fetch(self, key, url, source, dest_name=None, conditional=True, quiet_missing=False,
              max_age_hours=None):
        """Download url to data/raw/<source>/<name>. Returns DownloadResult."""
        url = self.resolve(key, url)
        dest = self.local_path(source, url, dest_name)
        prev = self._previous(url)
        have_local = os.path.exists(dest) and os.path.getsize(dest) > 0

        if have_local and max_age_hours is not None:
            age_h = (time.time() - os.path.getmtime(dest)) / 3600.0
            if age_h < max_age_hours:
                return DownloadResult(url, dest, "cached", None, os.path.getsize(dest))

        headers = {}
        if conditional and have_local and prev:
            if prev[2]:
                headers["If-None-Match"] = prev[2]
            if prev[1]:
                headers["If-Modified-Since"] = prev[1]

        last_err = None
        for attempt in range(self.retries + 1):
            self._check_cancel()
            try:
                req = urllib.request.Request(url, headers=self._headers(headers))
                with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as resp:
                    http = resp.status
                    total = resp.headers.get("Content-Length")
                    total = int(total) if total and total.isdigit() else None
                    modified = resp.headers.get("Last-Modified")
                    etag = resp.headers.get("ETag")
                    tmp = dest + ".part"
                    got = 0
                    last_report = time.time()
                    with open(tmp, "wb") as f:
                        while True:
                            self._check_cancel()
                            chunk = resp.read(1024 * 256)
                            if not chunk:
                                break
                            f.write(chunk)
                            got += len(chunk)
                            if self.progress and time.time() - last_report > 2:
                                last_report = time.time()
                                pct = (" (%.0f%%)" % (100.0 * got / total)) if total else ""
                                self.progress("Downloading %s: %s%s" % (
                                    os.path.basename(dest), human_bytes(got), pct))
                    if total is not None and got < total:
                        raise IOError("incomplete download (%d of %d bytes)" % (got, total))
                    os.replace(tmp, dest)
                    self._record(url, dest, "downloaded", http, got, modified, etag, source, key)
                    log.info("  downloaded %s (%s)", url, human_bytes(got))
                    return DownloadResult(url, dest, "downloaded", http, got)
            except urllib.error.HTTPError as e:
                if e.code == 304 and have_local:
                    self._record(url, dest, "not_modified", 304, os.path.getsize(dest),
                                 prev[1] if prev else None, prev[2] if prev else None, source, key)
                    log.info("  not modified: %s", url)
                    return DownloadResult(url, dest, "not_modified", 304, os.path.getsize(dest))
                last_err = "HTTP %s %s" % (e.code, e.reason)
                if e.code in (400, 401, 403, 404, 410):
                    status = "missing" if e.code in (404, 410) else "failed"
                    if not quiet_missing:
                        log.warning("  %s: %s", last_err, url)
                    self._record(url, dest if have_local else None, status, e.code, 0, source=source, key=key)
                    res = DownloadResult(url, dest if have_local else None, status, e.code, 0, last_err)
                    return res
            except Cancelled:
                raise
            except (urllib.error.URLError, socket.timeout, ConnectionError, IOError, ssl.SSLError) as e:
                last_err = str(getattr(e, "reason", e))
                if "CERTIFICATE_VERIFY_FAILED" in last_err:
                    last_err += (" -- On macOS run 'Install Certificates.command' from your Python "
                                 "folder (Applications/Python 3.x), or `pip install certifi`.")
                    break
            except Exception as e:  # pragma: no cover - defensive
                last_err = repr(e)
            if attempt < self.retries:
                wait = 2 ** attempt * 2
                log.info("  retrying in %ss (%s): %s", wait, last_err, url)
                time.sleep(wait)
        log.warning("  FAILED %s: %s", url, last_err)
        self._record(url, dest if have_local else None, "failed", None, 0, source=source, key=key)
        # Fall back to the last good local copy if we have one.
        if have_local:
            return DownloadResult(url, dest, "cached", None, os.path.getsize(dest), last_err)
        return DownloadResult(url, None, "failed", None, 0, last_err)

    def exists(self, key, url):
        """Cheap existence probe (HEAD, falling back to a 1-byte ranged GET)."""
        url = self.resolve(key, url)
        for method, extra in (("HEAD", {}), ("GET", {"Range": "bytes=0-0"})):
            try:
                req = urllib.request.Request(url, method=method, headers=self._headers(extra))
                with urllib.request.urlopen(req, timeout=min(self.timeout, 30), context=self.ctx) as resp:
                    return resp.status in (200, 206)
            except urllib.error.HTTPError as e:
                if e.code in (404, 410):
                    return False
                if e.code in (405, 501) and method == "HEAD":
                    continue
                if method == "GET":
                    return False
            except Exception:
                if method == "GET":
                    return False
        return False

    def post_json(self, key, url, payload, source, dest_name, max_age_hours=None):
        """POST a JSON body and cache the JSON reply under data/raw/<source>/<dest_name>.
        Returns (parsed_json or None, error_message, from_cache)."""
        import json as _json
        url = self.resolve(key, url)
        dest = self.local_path(source, url, dest_name)
        if max_age_hours is not None and os.path.exists(dest):
            if (time.time() - os.path.getmtime(dest)) / 3600.0 < max_age_hours:
                try:
                    with open(dest, "r", encoding="utf-8") as f:
                        return _json.load(f), None, True
                except ValueError:
                    pass
        self._check_cancel()
        try:
            data = _json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST",
                                         headers=self._headers({"Content-Type": "application/json"}))
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as resp:
                body = resp.read()
            parsed = _json.loads(body.decode("utf-8"))
        except Exception as e:
            return None, str(getattr(e, "reason", e)), False
        with open(dest + ".tmp", "wb") as f:
            f.write(body)
        os.replace(dest + ".tmp", dest)
        return parsed, None, False

    def get_text(self, key, url, source, dest_name=None, conditional=False, encoding="utf-8"):
        res = self.fetch(key, url, source, dest_name=dest_name, conditional=conditional, quiet_missing=True)
        if not res.ok:
            return None, res
        with open(res.path, "rb") as f:
            data = f.read()
        try:
            return data.decode(encoding), res
        except UnicodeDecodeError:
            return data.decode("latin-1"), res


def http_date(ts=None):
    return email.utils.formatdate(ts, usegmt=True)
