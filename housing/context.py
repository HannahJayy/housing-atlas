"""Shared state handed to every data source during an update run."""

import re

from .geo.states import ABBR_TO_NAME, FIPS_TO_ABBR, state_abbr
from .util import log, norm_county, norm_name, short_metro_name


class GeoIndex:
    """Lookup tables that map each provider's naming conventions to our IDs:
    state = postal code, metro = CBSA code, county = 5-digit FIPS, zip = 5 digits."""

    def __init__(self, con):
        self.con = con
        self.reload()

    def reload(self):
        con = self.con
        self.counties = {}
        self.county_by_name = {}
        self.cbsa = {}
        self.cbsa_by_name = {}
        self.zips = set()
        for level, gid, name, full, st in con.execute(
                "SELECT level, geo_id, name, full_name, state FROM geos"):
            if level == "county":
                self.counties[gid] = (name, st)
                self._add_county_name(name, st, gid)
                if full:
                    self._add_county_name(full, st, gid)
            elif level == "metro":
                self.cbsa[gid] = (name, full)
                for n in (name, full, short_metro_name(full or name)):
                    self._add_cbsa_name(n, gid)
            elif level == "zip":
                self.zips.add(gid)
        # Extra county aliases from crosswalk tables (e.g. names spelled by PEP).
        for a, b, w in con.execute("SELECT a, b, w FROM xw WHERE kind='county_alias'"):
            st, nm = a.split("|", 1)
            self.county_by_name.setdefault((st, nm), b)
        self.county_cbsa = {a: b for a, b in con.execute("SELECT a, b FROM xw WHERE kind='county_cbsa'")}
        self.mdiv_cbsa = {a: b for a, b in con.execute("SELECT a, b FROM xw WHERE kind='mdiv_cbsa'")}
        self.zip_county = {a: b for a, b in con.execute("SELECT a, b FROM xw WHERE kind='zip_county'")}
        self.cbsa_alias = {a: b for a, b in con.execute("SELECT a, b FROM xw WHERE kind='cbsa_alias'")}

    # ------------------------------------------------------------------
    def _add_county_name(self, name, st, gid):
        if not name or not st:
            return
        base = name.split(",")[0]
        key = norm_county(base)
        if key:
            self.county_by_name.setdefault((st, key), gid)
            self.county_by_name.setdefault((st, key.replace(" ", "")), gid)

    def _add_cbsa_name(self, name, gid):
        if not name:
            return
        k = norm_name(name)
        self.cbsa_by_name.setdefault(k, gid)
        # "first city, first state" key
        short = short_metro_name(name)
        if short:
            self.cbsa_by_name.setdefault(norm_name(short), gid)

    # ------------------------------------------------------------------
    def county_fips(self, name, state=None):
        """'Travis County, TX' or ('Travis County','TX') -> '48453'."""
        if not name:
            return None
        st = state_abbr(state) if state else None
        base = name
        if "," in name:
            base, tail = name.rsplit(",", 1)
            st = st or state_abbr(tail.strip())
        if not st:
            return None
        key = norm_county(base)
        gid = self.county_by_name.get((st, key)) or self.county_by_name.get((st, key.replace(" ", "")))
        if gid:
            return gid
        # 'Baltimore City' vs 'Baltimore city' already normalized; try dropping 'city'.
        if key.endswith(" city"):
            return self.county_by_name.get((st, key[:-5].strip()))
        return None

    def cbsa_code(self, name=None, code=None):
        if code:
            c = str(code).strip().split(".")[0]
            if c.isdigit():
                c = c.zfill(5)
                if c in self.cbsa:
                    return c
                if c in self.mdiv_cbsa:
                    return self.mdiv_cbsa[c]
        if name:
            n = re.sub(r"(?i)\s*(metro(politan)?( statistical)?( area)?|micro(politan)?( statistical)?( area)?|msa)\s*$",
                       "", str(name)).strip()
            k = norm_name(n)
            if k in self.cbsa_alias:
                return self.cbsa_alias[k]
            gid = self.cbsa_by_name.get(k)
            if gid:
                return gid
            short = short_metro_name(n)
            if short:
                gid = self.cbsa_by_name.get(norm_name(short))
                if gid:
                    return gid
        return None

    def state_of_county(self, fips):
        return FIPS_TO_ABBR.get(str(fips)[:2])


class Context:
    def __init__(self, cfg, con, downloader, report=None, cancel_event=None, force=False):
        self.cfg = cfg
        self.con = con
        self.dl = downloader
        self._report = report
        self.cancel_event = cancel_event
        self.force = force
        self.geo = GeoIndex(con)
        self.results = {}
        self.previous = {}

    def unchanged(self, source, results):
        """True when every file came back '304 Not Modified' (or from the local cache) and the
        source loaded fine last time - then re-parsing would produce identical data."""
        if self.force or not results:
            return False
        if any(getattr(r, "status", None) not in ("not_modified", "cached") for r in results):
            return False
        prev = self.previous.get(source) or {}
        return bool(prev.get("last_success")) and prev.get("status") in ("ok", "warning")

    def report(self, msg):
        log.info(msg)
        if self._report:
            try:
                self._report(msg)
            except Exception:
                pass

    def source_cfg(self, name):
        return (self.cfg.get("sources") or {}).get(name, {})

    def levels(self, name):
        lv = self.source_cfg(name).get("levels")
        return set(lv) if lv else {"us", "state", "metro", "county", "zip"}

    def cancelled(self):
        return self.cancel_event is not None and self.cancel_event.is_set()


def state_name(abbr):
    return ABBR_TO_NAME.get(abbr, abbr)
