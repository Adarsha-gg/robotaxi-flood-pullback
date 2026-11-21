"""C2: baseline flood zones (no AI), same contract as Carbon zones.

Rule: a cell is at risk when the forecast's peak 6-hour rain beats its historical
threshold AND it has flooded on enough past storm days. Rank by storm days, cap
the total area, merge touching cells into zones, and time-box each zone around
the forecast hours where 6-hour rain beats the zone's threshold.

Writes data/zones_<date>_baseline.json.  Run: .venv/bin/python -m pipeline.baseline [date]
"""
import json
import os
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

AREA_CAP = 0.08          # max share of SF covered by zones
SF_CELLS = 4340          # ~121 km2 land / ~0.0279 km2 per cell
MIN_STORM_DAYS = 3
LEAD_H, TAIL_H = 1, 2    # open a zone 1 h before rain crosses threshold, keep 2 h after


def load(name):
    with open(os.path.join(DATA, name)) as f:
        return json.load(f)


def six_hour(hours):
    """Trailing 6 h sums aligned to each forecast hour."""
    mm = [h["mm"] for h in hours]
    return [sum(mm[max(0, i - 5):i + 1]) for i in range(len(mm))]


def components(ids):
    """Group cell ids into 8-connected components."""
    left = set(ids)
    out = []
    while left:
        start = left.pop()
        comp, stack = [start], [start]
        while stack:
            r, c = (int(p[1:]) for p in stack.pop().split("_"))
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    n = f"r{r+dr}_c{c+dc}"
                    if n in left:
                        left.remove(n)
                        comp.append(n)
                        stack.append(n)
        out.append(comp)
    return out


def hull(points):
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def cell_polygon(cids, grid):
    """Convex hull of the cells' corners, as [lon, lat] points."""
    pts = []
    for cid in cids:
        r, c = (int(p[1:]) for p in cid.split("_"))
        la0, lo0 = grid["lat0"] + r * grid["dlat"], grid["lon0"] + c * grid["dlon"]
        for dla in (0, grid["dlat"]):
            for dlo in (0, grid["dlon"]):
                pts.append((round(lo0 + dlo, 6), round(la0 + dla, 6)))
    return [list(p) for p in hull(pts)]


def nice_name(addr):
    a = addr.replace("Intersection of ", "").replace("INTERSECTION ", "")
    if " and " in a:
        x, y = a.split(" and ", 1)
        a = f"{x.title()} & {y.title()}"
    else:
        a = a.split(",")[0].title()
    return a


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-11-18"
    cdata = load("cells.json")
    fc = load(f"forecast_{date}.json")
    grid = cdata["grid"]
    s6 = six_hour(fc["hours"])
    peak6 = max(s6)
    times = [h["t"] for h in fc["hours"]]

    at_risk = [c for c in cdata["cells"]
               if c["n_storm_days"] >= MIN_STORM_DAYS and c["thresh_mm_6h"] is not None
               and peak6 >= c["thresh_mm_6h"]]
    at_risk.sort(key=lambda c: (-c["n_storm_days"], -c["n_reports"]))
    chosen = at_risk[:int(AREA_CAP * SF_CELLS)]
    by_id = {c["id"]: c for c in chosen}

    zones = []
    for comp in components(list(by_id)):
        cs = [by_id[i] for i in comp]
        thresh = min(c["thresh_mm_6h"] for c in cs)
        idx = [i for i, v in enumerate(s6) if v >= thresh]
        if not idx:
            continue
        t0 = datetime.fromisoformat(times[idx[0]]) - timedelta(hours=LEAD_H)
        t1 = min(datetime.fromisoformat(times[idx[-1]]) + timedelta(hours=TAIL_H),
                 datetime.fromisoformat(f"{date}T23:59"))
        t0 = max(t0, datetime.fromisoformat(f"{date}T00:00"))
        top = max(cs, key=lambda c: (c["n_storm_days"], c["n_reports"]))
        sdays = sorted({d for c in cs for d in c["storm_days"]}, reverse=True)
        n_rep = sum(c["n_reports"] for c in cs)
        zones.append({
            "id": "", "name": nice_name(top["top_addresses"][0]) if top["top_addresses"] else top["id"],
            "cells": comp, "polygon": cell_polygon(comp, grid),
            "start": t0.strftime("%Y-%m-%dT%H:%M"), "end": t1.strftime("%Y-%m-%dT%H:%M"),
            "p_flood": round(min(0.95, top["n_storm_days"] / max(1, len(cdata["storm_days"])) * 3), 2),
            "reason": (f"Flooded on {top['n_storm_days']} past storm days (latest {top['storm_days'][0]}). "
                       f"Forecast 6-hour rain peaks at {peak6:.1f} mm, above this spot's {thresh:.1f} mm threshold."),
            "evidence": {"n_reports": n_rep, "storm_days": sdays[:10]},
            "status": "proposed", "source": "forecast",
            "_rank": max(c["n_storm_days"] for c in cs) * 1000 + n_rep,
        })
    zones.sort(key=lambda z: -z["_rank"])
    for i, z in enumerate(zones, 1):
        z["id"] = f"b{i}"
        del z["_rank"]

    out = {"date": date, "forecast_source": fc["source"], "generated_by": "baseline", "zones": zones}
    path = os.path.join(DATA, f"zones_{date}_baseline.json")
    with open(path, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    n_cells = sum(len(z["cells"]) for z in zones)
    print(f"wrote {path}: {len(zones)} zones, {n_cells} cells (~{n_cells / SF_CELLS:.1%} of SF), peak 6h={peak6:.1f} mm")

    ev_path = os.path.join(DATA, f"events_{date}.json")
    if os.path.exists(ev_path):
        ev = load(f"events_{date}.json")
        cell_zone = {cid: z for z in zones for cid in z["cells"]}
        inside = [e for e in ev if e["cell"] in cell_zone
                  and cell_zone[e["cell"]]["start"] <= e["t"][:16] <= cell_zone[e["cell"]]["end"]]
        print(f"  events inside an active zone: {len(inside)}/{len(ev)} = {len(inside) / len(ev):.0%}")
        for z in zones[:5]:
            print(f"  {z['id']:4} {z['name'][:40]:40} {z['start'][11:]}-{z['end'][11:]} cells={len(z['cells'])}")


if __name__ == "__main__":
    main()
