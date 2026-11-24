"""Minimal streaming ESRI Shapefile (.shp + .dbf) reader - polygons only.

Census cartographic boundary files are distributed as zipped shapefiles. This
reader avoids any third-party dependency (no GDAL / pyshp) and streams records
one at a time so even the 64 MB ZCTA file can be processed with little memory.
"""

import struct
import zipfile


def _read_exact(f, n):
    buf = f.read(n)
    if len(buf) < n:
        raise EOFError
    return buf


def iter_shp(f):
    """Yield list-of-rings per record; each ring is a flat tuple (x0,y0,x1,y1,...).
    Null shapes yield []."""
    header = _read_exact(f, 100)
    file_code = struct.unpack(">i", header[0:4])[0]
    if file_code != 9994:
        raise ValueError("not a shapefile (file code %s)" % file_code)
    while True:
        try:
            rec_header = _read_exact(f, 8)
        except EOFError:
            return
        _, content_words = struct.unpack(">ii", rec_header)
        content = _read_exact(f, content_words * 2)
        shape_type = struct.unpack_from("<i", content, 0)[0]
        if shape_type == 0:
            yield []
            continue
        if shape_type not in (5, 15, 25, 3, 13, 23):  # polygon / polyline (+Z/M)
            yield []
            continue
        num_parts, num_points = struct.unpack_from("<ii", content, 36)
        parts = struct.unpack_from("<%di" % num_parts, content, 44)
        pts_off = 44 + 4 * num_parts
        coords = struct.unpack_from("<%dd" % (2 * num_points), content, pts_off)
        rings = []
        for i, start in enumerate(parts):
            end = parts[i + 1] if i + 1 < num_parts else num_points
            rings.append(coords[2 * start:2 * end])
        yield rings


def iter_dbf(f, encoding="utf-8"):
    header = _read_exact(f, 32)
    num_records = struct.unpack("<I", header[4:8])[0]
    header_len, record_len = struct.unpack("<HH", header[8:12])
    fields = []
    read = 32
    while True:
        b = _read_exact(f, 1)
        read += 1
        if b == b"\r":
            break
        desc = b + _read_exact(f, 31)
        read += 31
        name = desc[:11].split(b"\x00")[0].decode("ascii", "replace").strip()
        ftype = chr(desc[11])
        flen = desc[16]
        fields.append((name, ftype, flen))
    # Skip to the start of the records.
    if header_len > read:
        _read_exact(f, header_len - read)
    for _ in range(num_records):
        try:
            rec = _read_exact(f, record_len)
        except EOFError:
            return
        pos = 1  # first byte is the deletion flag
        out = {}
        for name, ftype, flen in fields:
            raw = rec[pos:pos + flen]
            pos += flen
            try:
                txt = raw.decode(encoding)
            except UnicodeDecodeError:
                txt = raw.decode("latin-1")
            txt = txt.strip().strip("\x00")
            if ftype in ("N", "F"):
                try:
                    out[name] = float(txt) if txt else None
                    if out[name] is not None and out[name].is_integer() and "." not in txt:
                        out[name] = int(out[name])
                except ValueError:
                    out[name] = None
            else:
                out[name] = txt
        yield out


def iter_zipped_shapefile(zip_path):
    """Yield (attributes, rings) for each record in a zipped shapefile."""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        shp = next((n for n in names if n.lower().endswith(".shp")), None)
        dbf = next((n for n in names if n.lower().endswith(".dbf")), None)
        cpg = next((n for n in names if n.lower().endswith(".cpg")), None)
        if not shp or not dbf:
            raise ValueError("zip does not contain a .shp/.dbf pair: %s" % zip_path)
        encoding = "utf-8"
        if cpg:
            enc = z.read(cpg).decode("ascii", "ignore").strip().lower()
            if enc in ("utf-8", "utf8"):
                encoding = "utf-8"
            elif enc:
                encoding = "latin-1" if "1252" in enc or "8859" in enc else "utf-8"
        with z.open(shp) as fs, z.open(dbf) as fd:
            for rings, attrs in zip(iter_shp(fs), iter_dbf(fd, encoding)):
                yield attrs, rings
