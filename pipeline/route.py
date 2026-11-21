"""C5: route a robotaxi trip around approved, active flood zones.

1. Ask Valhalla for the normal route.
2. Find approved zones active at time t that the route passes through.
3. Ask again with those zones' cells excluded. Repeat (max 4 rounds) until clean.
Only zones the route actually touches are sent, to stay under the public
server's exclusion-perimeter limit. Falls back to OSRM alternatives.
"""
import json
import math
import urllib.request

VALHALLA = "https://valhalla1.openstreetmap.de/route"
OSRM = "https://router.project-osrm.org/route/v1/driving"
GRID = {"lat0": 37.70, "lon0": -122.52, "dlat": 0.0015, "dlon": 0.0019}


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "flood-pullback-hackathon"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "flood-pullback-hackathon"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _decode(s, precision=6):
    coords, idx, lat, lon, f = [], 0, 0, 0, 10 ** precision
    while idx < len(s):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(s[idx]) - 63
                idx += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            d = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += d
            else:
                lon += d
        coords.append([lat / f, lon / f])
    return coords


def _densify(coords, step_m=40):
    out = []
    for (a, b), (c, d) in zip(coords, coords[1:]):
        dist = math.hypot((c - a) * 111000, (d - b) * 88000)
        n = max(1, int(dist / step_m))
        out += [[a + (c - a) * k / n, b + (d - b) * k / n] for k in range(n)]
    return out + coords[-1:]


def _cell(lat, lon):
    return f"r{math.floor((lat - GRID['lat0']) / GRID['dlat'])}_c{math.floor((lon - GRID['lon0']) / GRID['dlon'])}"


def _square(cid, pad=0.00015):
    r, c = (int(p[1:]) for p in cid.split("_"))
    la, lo = GRID["lat0"] + r * GRID["dlat"], GRID["lon0"] + c * GRID["dlon"]
    la0, la1, lo0, lo1 = la - pad, la + GRID["dlat"] + pad, lo - pad, lo + GRID["dlon"] + pad
    return [[lo0, la0], [lo1, la0], [lo1, la1], [lo0, la1], [lo0, la0]]


MAX_CIRCUM_M = 9500  # public Valhalla rejects > 10,000 m of total exclusion outline


def _rects(cells, pad=0.00015):
    """Merge 8-connected cells into one bounding rectangle each; keep within the outline budget."""
    left, comps = set(cells), []
    while left:
        s = left.pop()
        comp, stack = [s], [s]
        while stack:
            r, c = (int(p[1:]) for p in stack.pop().split("_"))
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    n = f"r{r+dr}_c{c+dc}"
                    if n in left:
                        left.remove(n); comp.append(n); stack.append(n)
        comps.append(comp)
    polys, used = [], 0.0
    for comp in sorted(comps, key=len, reverse=True):
        rc = [tuple(int(p[1:]) for p in c.split("_")) for c in comp]
        r0, r1 = min(r for r, _ in rc), max(r for r, _ in rc) + 1
        c0, c1 = min(c for _, c in rc), max(c for _, c in rc) + 1
        la0, la1 = GRID["lat0"] + r0 * GRID["dlat"] - pad, GRID["lat0"] + r1 * GRID["dlat"] + pad
        lo0, lo1 = GRID["lon0"] + c0 * GRID["dlon"] - pad, GRID["lon0"] + c1 * GRID["dlon"] + pad
        circ = 2 * ((la1 - la0) * 111000 + (lo1 - lo0) * 88000)
        if used + circ > MAX_CIRCUM_M:
            continue
        used += circ
        polys.append([[lo0, la0], [lo1, la0], [lo1, la1], [lo0, la1], [lo0, la0]])
    return polys


def _valhalla(frm, to, exclude_cells):
    body = {"locations": [{"lat": frm[0], "lon": frm[1]}, {"lat": to[0], "lon": to[1]}],
            "costing": "auto", "units": "kilometers"}
    if exclude_cells:
        body["exclude_polygons"] = _rects(exclude_cells)
    t = _post(VALHALLA, body)["trip"]
    coords = []
    for leg in t["legs"]:
        coords += _decode(leg["shape"])
    return {"coords": coords, "min": round(t["summary"]["time"] / 60, 1), "km": round(t["summary"]["length"], 2)}


def _osrm(frm, to):
    d = _get(f"{OSRM}/{frm[1]},{frm[0]};{to[1]},{to[0]}?alternatives=3&overview=full&geometries=geojson")
    return [{"coords": [[y, x] for x, y in r["geometry"]["coordinates"]],
             "min": round(r["duration"] / 60, 1), "km": round(r["distance"] / 1000, 2)} for r in d["routes"]]


def _hits(route, cell_zone):
    cells = {_cell(la, lo) for la, lo in _densify(route["coords"])}
    hit_cells = {c for c in cells if c in cell_zone}
    return hit_cells, sorted({cell_zone[c] for c in hit_cells})


def route(body, load_zones):
    date = body.get("date") or str(body.get("t", "2026-11-18"))[:10]
    zset = body.get("set", "carbon")
    frm, to, t = body["from"], body["to"], body.get("t", f"{date}T10:00")
    m = int(t[11:13]) * 60 + int(t[14:16])
    zf = load_zones(date, zset) or load_zones(date, "baseline") or {"zones": []}
    active = [z for z in zf["zones"] if z.get("status") == "approved"
              and int(z["start"][11:13]) * 60 + int(z["start"][14:16]) <= m <= int(z["end"][11:13]) * 60 + int(z["end"][14:16])]
    cell_zone = {c: z["id"] for z in active for c in z["cells"]}
    try:
        default = _valhalla(frm, to, set())
        _, default["hits_zones"] = _hits(default, cell_zone)
        # never block the pickup or drop-off block itself
        ends = set()
        for la, lo in (frm, to):
            r, c = (int(p[1:]) for p in _cell(la, lo).split("_"))
            ends |= {f"r{r+dr}_c{c+dc}" for dr in (-1, 0, 1) for dc in (-1, 0, 1)}
        excl, safe, note = set(), default, None
        for _ in range(5):
            cells, _z = _hits(safe, cell_zone)
            cells -= ends
            if not cells or cells <= excl:
                break
            try:
                cand = _valhalla(frm, to, excl | cells)  # exclude only the flooded cells this route crosses
            except Exception as e:
                note = f"stopped early: {type(e).__name__}"
                break
            excl |= cells
            safe = cand
        c_safe, safe["hits_zones"] = _hits(safe, cell_zone)
        c_def, _ = _hits(default, cell_zone)
        default["flood_cells"], safe["flood_cells"] = len(c_def - ends), len(c_safe - ends)
        router = "valhalla" + (f" ({note})" if note else "")
    except Exception as e:  # fallback: pick the OSRM alternative with the fewest zone hits
        alts = _osrm(frm, to)
        for a in alts:
            _, a["hits_zones"] = _hits(a, cell_zone)
        default = alts[0]
        safe = min(alts, key=lambda a: (len(a["hits_zones"]), a["min"]))
        router, excl = f"osrm ({type(e).__name__})", set()
    return {"default": default, "safe": safe, "added_min": round(safe["min"] - default["min"], 1),
            "router": router, "active_zones": len(active), "excluded_cells": len(excl)}
