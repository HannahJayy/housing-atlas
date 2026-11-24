"""Projection (Web Mercator), line simplification and compact encoding of polygons
for the browser map."""

import math

QBITS = 22            # integer grid = world pixels at zoom 14
QSCALE = float(1 << QBITS)
MAX_LAT = 85.05112878


def merc(lon, lat):
    """lon/lat (degrees) -> normalized Web Mercator (x may be slightly < 0 west of -180)."""
    lat = max(-MAX_LAT, min(MAX_LAT, lat))
    x = (lon + 180.0) / 360.0
    s = math.sin(math.radians(lat))
    y = 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    return x, y


def unmerc(x, y):
    lon = x * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * y
    lat = math.degrees(math.atan(0.5 * (math.exp(n) - math.exp(-n))))
    return lon, lat


def _radial(pts, tol2):
    """Fast pre-pass: drop points closer than tol to the previously kept point."""
    if len(pts) <= 4:
        return pts
    out = [pts[0]]
    px, py = pts[0]
    for x, y in pts[1:-1]:
        dx = x - px
        dy = y - py
        if dx * dx + dy * dy > tol2:
            out.append((x, y))
            px, py = x, y
    out.append(pts[-1])
    return out


def _dp(pts, tol2):
    """Iterative Douglas-Peucker (no recursion limit issues)."""
    n = len(pts)
    if n <= 3:
        return pts
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        dd = dx * dx + dy * dy
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if dd == 0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = ((px - ax) * dx + (py - ay) * dy) / dd
                if t < 0:
                    t = 0
                elif t > 1:
                    t = 1
                qx = ax + t * dx
                qy = ay + t * dy
                d = (px - qx) ** 2 + (py - qy) ** 2
            if d > best:
                best, idx = d, i
        if best > tol2 and idx > 0:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, k in zip(pts, keep) if k]


def ring_area(pts):
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return a / 2.0


def simplify_ring(pts, tol):
    tol2 = tol * tol
    pts = _radial(pts, tol2 * 0.25)
    if len(pts) > 4:
        # DP needs a split point for closed rings: use the farthest point from the first.
        x0, y0 = pts[0]
        far = max(range(len(pts)), key=lambda i: (pts[i][0] - x0) ** 2 + (pts[i][1] - y0) ** 2)
        if 0 < far < len(pts) - 1:
            a = _dp(pts[:far + 1], tol2)
            b = _dp(pts[far:], tol2)
            pts = a[:-1] + b
        else:
            pts = _dp(pts, tol2)
    return pts


def process_rings(rings_lonlat, tol, min_area=0.0):
    """rings: list of flat lon/lat tuples -> (simplified mercator rings, bbox merc, centroid lonlat).
    Small rings (islands/slivers) below min_area are dropped unless they are the largest."""
    proj = []
    for flat in rings_lonlat:
        lons = flat[0::2]
        # U.S. features live in the western hemisphere; Aleutian islands past the 180th meridian
        # (positive longitudes) are shifted west so Alaska stays one compact shape.
        shift = -360.0 if lons and sum(lons) / len(lons) > 90 else 0.0
        pts = [merc(flat[i] + shift, flat[i + 1]) for i in range(0, len(flat) - 1, 2)]
        if len(pts) >= 3:
            proj.append(pts)
    if not proj:
        return [], None, None
    areas = [abs(ring_area(p)) for p in proj]
    largest = max(range(len(proj)), key=lambda i: areas[i])
    out = []
    for i, pts in enumerate(proj):
        if i != largest and areas[i] < min_area:
            continue
        s = simplify_ring(pts, tol)
        if len(s) < 4:
            if i != largest:
                continue
            s = pts if len(pts) < 8 else simplify_ring(pts, tol / 4)
        out.append(s)
    minx = min(x for r in out for x, _ in r)
    maxx = max(x for r in out for x, _ in r)
    miny = min(y for r in out for _, y in r)
    maxy = max(y for r in out for _, y in r)
    # Area-weighted centroid of the largest ring (good enough for labels / search zoom).
    cx, cy = _centroid(proj[largest])
    lon, lat = unmerc(cx, cy)
    return out, (minx, miny, maxx, maxy), (lon, lat)


def _centroid(pts):
    a = 0.0
    cx = cy = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        cr = x1 * y2 - x2 * y1
        a += cr
        cx += (x1 + x2) * cr
        cy += (y1 + y2) * cr
    if abs(a) < 1e-18:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return sum(xs) / n, sum(ys) / n
    return cx / (3 * a), cy / (3 * a)


def encode_rings(rings):
    """Quantize to the integer grid and delta-encode each ring: [x0,y0,dx1,dy1,...]."""
    out = []
    for r in rings:
        enc = []
        px = py = None
        for x, y in r:
            qx = int(round(x * QSCALE))
            qy = int(round(y * QSCALE))
            if px is None:
                enc.extend((qx, qy))
            else:
                dx, dy = qx - px, qy - py
                if dx == 0 and dy == 0:
                    continue
                enc.extend((dx, dy))
            px, py = qx, qy
        if len(enc) >= 6:
            out.append(enc)
    return out


def qbbox(b):
    return [int(math.floor(b[0] * QSCALE)), int(math.floor(b[1] * QSCALE)),
            int(math.ceil(b[2] * QSCALE)), int(math.ceil(b[3] * QSCALE))]


def point_in_rings(x, y, rings):
    """Even-odd point-in-polygon test on mercator rings (list of (x,y) lists)."""
    inside = False
    for r in rings:
        n = len(r)
        j = n - 1
        for i in range(n):
            xi, yi = r[i]
            xj, yj = r[j]
            if (yi > y) != (yj > y):
                xint = (xj - xi) * (y - yi) / ((yj - yi) or 1e-30) + xi
                if x < xint:
                    inside = not inside
            j = i
    return inside
