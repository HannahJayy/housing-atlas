"""U.S. Census Bureau cartographic boundary files -> compact map geometry + region list."""

import gzip
import json
import os
import time

from ..config import DATA_DIR
from ..geo.shapefile import iter_zipped_shapefile
from ..geo.simplify import encode_rings, merc, point_in_rings, process_rings, qbbox, unmerc
from ..geo.states import ABBR_TO_NAME, FIPS_TO_ABBR, state_abbr
from ..util import Timer, log, short_metro_name

GEO_DIR = os.path.join(DATA_DIR, "geo")
TIGER = "https://www2.census.gov/geo/tiger/GENZ{y}/shp/cb_{y}_us_{layer}.zip"
ZCTA_REL = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt"

INFO = {
    "id": "boundaries",
    "name": "U.S. Census Bureau - Cartographic Boundary Files",
    "homepage": "https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html",
    "description": "State, county, metro (CBSA) and ZIP code (ZCTA) shapes used to draw the map, plus the "
                   "official ZCTA-to-county relationship file used to place each ZIP inside a county/metro.",
    "frequency": "Yearly (new vintage each spring)",
    "metrics": [],
    "license": "Public domain (U.S. Government work)",
}

SKIP_STATE_FIPS = {"60", "66", "69", "78", "64", "68", "70", "74", "81", "84", "86", "67", "89", "71", "76", "95", "79"}

TOL = {"state": 1.2e-5, "county": 3.5e-6, "metro": 3.5e-6, "zip": 6e-7}
MIN_AREA = {"state": 4e-10, "county": 4e-11, "metro": 4e-11, "zip": 2e-12}


def file_list(cfg):
    y = time.localtime().tm_year - 1
    return [
        {"key": "tiger_state", "url": TIGER.format(y=y, layer="state_20m"), "desc": "State shapes (newest vintage found)"},
        {"key": "tiger_county", "url": TIGER.format(y=y, layer="county_5m"), "desc": "County shapes"},
        {"key": "tiger_cbsa", "url": TIGER.format(y=y, layer="cbsa_5m"), "desc": "Metro/micro area (CBSA) shapes"},
        {"key": "tiger_zcta", "url": TIGER.format(y=2020, layer="zcta520_500k"), "desc": "ZIP code (ZCTA) shapes"},
        {"key": "zcta_county_rel", "url": ZCTA_REL, "desc": "ZCTA-to-county relationship file"},
    ]


def _find_year(ctx, layer, start=None):
    y0 = start or time.localtime().tm_year
    for y in range(y0, y0 - 6, -1):
        url = TIGER.format(y=y, layer=layer)
        if ctx.dl.exists("tiger_" + layer, url):
            return y, url
    return None, None


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    with open(path + ".tmp", "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)
    with gzip.open(path + ".gz.tmp", "wb", compresslevel=6) as f:
        f.write(data)
    os.replace(path + ".gz.tmp", path + ".gz")
    return len(data)


def _upsert(con, rows):
    con.executemany(
        "INSERT INTO geos(level,geo_id,name,full_name,state,lsad,lat,lon,minx,miny,maxx,maxy,aland,has_shape) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1) "
        "ON CONFLICT(level,geo_id) DO UPDATE SET name=COALESCE(excluded.name,name), "
        "full_name=COALESCE(excluded.full_name,full_name), state=COALESCE(excluded.state,state), "
        "lsad=COALESCE(excluded.lsad,lsad), lat=excluded.lat, lon=excluded.lon, minx=excluded.minx, "
        "miny=excluded.miny, maxx=excluded.maxx, maxy=excluded.maxy, aland=COALESCE(excluded.aland,aland), "
        "has_shape=1", rows)


def _lonlat_bbox(b):
    lon0, lat0 = unmerc(b[0], b[3])
    lon1, lat1 = unmerc(b[2], b[1])
    return lon0, lat0, lon1, lat1


def _process_layer(ctx, level, zip_path, keep_rings=False):
    """Returns (features, rows, rings_by_id)."""
    feats = []
    rows = []
    kept = {}
    t = Timer()
    n = 0
    for attrs, rings in iter_zipped_shapefile(zip_path):
        if ctx.cancelled():
            raise RuntimeError("cancelled")
        n += 1
        a = {k.upper(): v for k, v in attrs.items()}
        stfp = str(a.get("STATEFP") or "").zfill(2) if a.get("STATEFP") not in (None, "") else ""
        if stfp and stfp in SKIP_STATE_FIPS:
            continue
        if level == "state":
            gid = a.get("STUSPS") or FIPS_TO_ABBR.get(stfp)
            if not gid or gid not in ABBR_TO_NAME:
                continue
            name = a.get("NAME") or ABBR_TO_NAME[gid]
            full, st, lsad = name, gid, None
        elif level == "county":
            gid = str(a.get("GEOID") or (stfp + str(a.get("COUNTYFP") or "").zfill(3)))
            if len(gid) != 5 or gid[:2] in SKIP_STATE_FIPS:
                continue
            st = a.get("STUSPS") or FIPS_TO_ABBR.get(gid[:2])
            if not st:
                continue
            base = a.get("NAMELSAD") or a.get("NAME") or gid
            name = "%s, %s" % (base, st)
            full, lsad = name, None
        elif level == "metro":
            gid = str(a.get("CBSAFP") or a.get("GEOID") or "").zfill(5)
            if not gid.strip("0"):
                continue
            full = a.get("NAME") or gid
            name = short_metro_name(full)
            st = state_abbr(full.rsplit(",", 1)[-1].strip().split("-")[0]) if "," in full else None
            lsad = {"M1": "metro", "M2": "micro"}.get(a.get("LSAD"), a.get("LSAD"))
        else:  # zip
            gid = str(a.get("ZCTA5CE20") or a.get("ZCTA5CE10") or a.get("GEOID20") or a.get("GEOID") or "").zfill(5)
            if not gid.isdigit():
                continue
            name = full = gid
            st, lsad = None, None
        merc_rings, bbox, cen = process_rings(rings, TOL[level], MIN_AREA[level])
        if not merc_rings:
            continue
        enc = encode_rings(merc_rings)
        if not enc:
            continue
        aland = a.get("ALAND") or a.get("ALAND20") or a.get("ALAND10")
        aland_sqmi = (float(aland) / 2589988.11) if aland not in (None, "") else None
        lon0, lat0, lon1, lat1 = _lonlat_bbox(bbox)  # lat0 = south edge, lat1 = north edge
        rows.append((level, gid, name, full, st, lsad, cen[1], cen[0], lon0, lat0, lon1, lat1, aland_sqmi))
        feats.append([gid, qbbox(bbox), enc])
        if keep_rings:
            kept[gid] = (bbox, merc_rings)
    log.info("  %s: %d shapes read, %d kept (%s)", level, n, len(feats), t)
    return feats, rows, kept


def run(ctx):
    con = ctx.con
    os.makedirs(GEO_DIR, exist_ok=True)
    summary = {}
    con.execute("INSERT OR IGNORE INTO geos(level,geo_id,name,full_name,state) VALUES('us','US','United States','United States',NULL)")

    year, _ = _find_year(ctx, "county_5m")
    if year is None:
        year, _ = _find_year(ctx, "county_20m")
    if year is None:
        raise RuntimeError("Could not reach the Census boundary files (www2.census.gov).")
    ctx.report("Boundaries: using Census %d cartographic boundary files" % year)

    layers = [("state", ["state_20m", "state_5m"]), ("county", ["county_5m", "county_20m"]),
              ("metro", ["cbsa_5m", "cbsa_20m"])]
    county_rings = {}
    for level, names in layers:
        res = None
        for layer in names:
            res = ctx.dl.fetch("tiger_" + layer.split("_")[0], TIGER.format(y=year, layer=layer), "boundaries")
            if res.ok:
                break
        if not res or not res.ok:
            log.warning("  could not download %s boundaries", level)
            summary[level] = "failed"
            continue
        ctx.report("Boundaries: processing %s shapes" % level)
        feats, rows, kept = _process_layer(ctx, level, res.path, keep_rings=(level == "county"))
        if level == "county":
            county_rings = kept
        size = _write_json(os.path.join(GEO_DIR, level + ".json"),
                           {"v": 1, "level": level, "q": 22, "year": year, "f": feats})
        con.execute("BEGIN")
        _upsert(con, rows)
        con.execute("COMMIT")
        summary[level] = "%d shapes (%.1f MB)" % (len(feats), size / 1e6)

    # ZIP codes (ZCTA). Newest file is the 2020 vintage (ZCTAs are redrawn each decennial census).
    zip_centroids = {}
    if ctx.source_cfg("boundaries").get("zip_shapes", True):
        res = None
        for y in (year, 2020):
            res = ctx.dl.fetch("tiger_zcta", TIGER.format(y=y, layer="zcta520_500k"), "boundaries",
                               quiet_missing=True)
            if res.ok:
                break
        if res and res.ok:
            ctx.report("Boundaries: processing ZIP code shapes (this takes a few minutes the first time)")
            feats, rows, _ = _process_layer(ctx, "zip", res.path)
            groups = {}
            for f in feats:
                groups.setdefault(f[0][:3], []).append(f)
            index = {}
            zdir = os.path.join(GEO_DIR, "zip")
            os.makedirs(zdir, exist_ok=True)
            total = 0
            for z3, fs in groups.items():
                bx = [min(f[1][0] for f in fs), min(f[1][1] for f in fs),
                      max(f[1][2] for f in fs), max(f[1][3] for f in fs)]
                index[z3] = bx
                total += _write_json(os.path.join(zdir, z3 + ".json"), {"v": 1, "level": "zip", "q": 22, "f": fs})
            _write_json(os.path.join(zdir, "index.json"), {"v": 1, "q": 22, "chunks": index})
            con.execute("BEGIN")
            _upsert(con, rows)
            con.execute("COMMIT")
            for r in rows:
                zip_centroids[r[1]] = (r[7], r[6])  # lon, lat
            summary["zip"] = "%d shapes in %d chunks (%.1f MB)" % (len(feats), len(groups), total / 1e6)
        else:
            summary["zip"] = "failed"

    # ZIP -> county assignment (largest land-area overlap), with a point-in-polygon fallback.
    res = ctx.dl.fetch("zcta_county_rel", ZCTA_REL, "boundaries")
    county_ids = {r[0] for r in con.execute("SELECT geo_id FROM geos WHERE level='county'")}
    assign = {}
    if res.ok:
        best = {}
        with open(res.path, "r", encoding="utf-8-sig", errors="replace") as f:
            header = f.readline().strip().split("|")
            idx = {h.strip().upper(): i for i, h in enumerate(header)}
            iz = idx.get("GEOID_ZCTA5_20")
            ic = idx.get("GEOID_COUNTY_20")
            ia = idx.get("AREALAND_PART")
            if iz is None or ic is None:
                log.warning("  unexpected ZCTA relationship header: %s", header[:6])
            else:
                for line in f:
                    p = line.rstrip("\n").split("|")
                    if len(p) <= max(iz, ic):
                        continue
                    z, c = p[iz].strip(), p[ic].strip()
                    if not z or not c:
                        continue
                    try:
                        area = float(p[ia]) if ia is not None and p[ia] else 0.0
                    except ValueError:
                        area = 0.0
                    if z not in best or area > best[z][1]:
                        best[z] = (c, area)
        for z, (c, a) in best.items():
            assign[z] = c
    # Fallback for ZIPs whose county isn't in the current county list (e.g. Connecticut's
    # 2022 switch to planning regions) or that are missing from the relationship file.
    fixed = 0
    if county_rings:
        cells = {}
        for cid, (bb, rings) in county_rings.items():
            cells[cid] = (bb, rings)
        for z, (lon, lat) in zip_centroids.items():
            c = assign.get(z)
            if c in county_ids:
                continue
            x, y = merc(lon, lat)
            for cid, (bb, rings) in cells.items():
                if bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3] and point_in_rings(x, y, rings):
                    assign[z] = cid
                    fixed += 1
                    break
    if assign:
        con.execute("BEGIN")
        con.execute("DELETE FROM xw WHERE kind='zip_county'")
        con.executemany("INSERT OR REPLACE INTO xw(kind,a,b,w) VALUES('zip_county',?,?,1)", list(assign.items()))
        con.execute("UPDATE geos SET county_id=(SELECT b FROM xw WHERE kind='zip_county' AND a=geos.geo_id) "
                    "WHERE level='zip'")
        con.execute("UPDATE geos SET state=COALESCE(state,(SELECT state FROM geos g2 WHERE g2.level='county' "
                    "AND g2.geo_id=geos.county_id)) WHERE level='zip'")
        con.execute("COMMIT")
        summary["zip_county"] = "%d ZIPs assigned (%d via point-in-polygon)" % (len(assign), fixed)
    ctx.geo.reload()
    return {"message": "; ".join("%s: %s" % kv for kv in summary.items()), "details": summary,
            "ok": summary.get("county") not in (None, "failed")}
