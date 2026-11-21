"""Real Waymo data for San Francisco (public filings; most fields are redacted by Waymo).

Sources:
  - CPUC AV Program quarterly deployment data, Waymo 2026 Q3 (Jul-Sep):
    AV_Incidents_Location: collisions per census tract. Tracts with collisions = where
    Waymo cars actually drive (trip locations themselves are redacted).
  - NHTSA Standing General Order ADS crash reports (Waymo, San Francisco, weather flags).
  - Census TIGERweb SF tract polygons.
Writes data/waymo_sf.geojson and data/waymo_stats.json.
Run: .venv/bin/python -m pipeline.waymo  (needs the raw files in data/raw/, see README)
"""
import csv
import glob
import json
import os
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw")


def in_ring(x, y, ring):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1:
            inside = not inside
    return inside


def in_feature(lon, lat, geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    return any(in_ring(lon, lat, p[0]) and not any(in_ring(lon, lat, h) for h in p[1:]) for p in polys)


def main():
    tracts = json.load(open(os.path.join(RAW, "sf_tracts.geojson")))["features"]
    loc = glob.glob(os.path.join(RAW, "waymo_2026q3", "**", "*Incidents_Location*.csv"), recursive=True)[0]
    coll = {}
    with open(loc, newline="") as f:
        for r in csv.DictReader(f):
            if r["Tract"].startswith("6075"):
                try:
                    coll["0" + r["Tract"]] = int(r["CollisionsAll"])
                except ValueError:
                    pass
    for t in tracts:
        g = t["properties"]["GEOID"]
        t["properties"] = {"geoid": g, "name": t["properties"]["NAME"], "waymo_collisions_q3": coll.get(g, 0)}
    active = [t for t in tracts if t["properties"]["waymo_collisions_q3"] > 0]

    # Nov 18 floods inside tracts where Waymo was active
    ev = json.load(open(os.path.join(ROOT, "data", "events_2026-11-18.json")))
    def tract_of(e):
        for t in active:
            if in_feature(e["lon"], e["lat"], t["geometry"]):
                return t["properties"]["geoid"]
    in_active = Counter(tract_of(e) for e in ev)
    n_in = sum(v for k, v in in_active.items() if k)

    # NHTSA SGO: Waymo crashes in San Francisco, and in rain
    sgo_path = os.path.join(RAW, "sgo_ads.csv")
    sgo = {}
    if os.path.exists(sgo_path):
        rows = list(csv.DictReader(open(sgo_path, encoding="utf-8", errors="replace")))
        w = [r for r in rows if "waymo" in (r.get("Reporting Entity", "") + r.get("Make", "")).lower()
             and r.get("City", "").upper().startswith("SAN FRANCISCO")]
        from datetime import datetime
        ms = sorted(datetime.strptime(r["Incident Date"], "%b-%Y") for r in w if r.get("Incident Date"))
        sgo = {"waymo_sf_crash_reports": len(w), "in_rain": sum(r.get("Weather - Rain") == "Y" for r in w),
               "months": f"{ms[0]:%b %Y} .. {ms[-1]:%b %Y}"}

    stats = {"cpuc_quarter": "2026Q3", "sf_tracts": len(tracts), "tracts_with_waymo_collisions": len(active),
             "waymo_collisions_sf_q3": sum(coll.values()),
             "nov18_floods": len(ev), "nov18_floods_in_waymo_active_tracts": n_in,
             "top_flooded_waymo_tracts": [{"geoid": k, "floods": v, "collisions": coll.get(k, 0)}
                                          for k, v in in_active.most_common(8) if k],
             "nhtsa_sgo": sgo,
             "note": "Waymo redacts trip locations, times and stoppage locations in its CPUC filings; "
                     "tracts with reported collisions are used as the public proxy for where Waymo drives."}
    for t in tracts:
        t["properties"]["nov18_floods"] = in_active.get(t["properties"]["geoid"], 0)
    json.dump({"type": "FeatureCollection", "features": tracts},
              open(os.path.join(ROOT, "data", "waymo_sf.geojson"), "w"), separators=(",", ":"))
    json.dump(stats, open(os.path.join(ROOT, "data", "waymo_stats.json"), "w"), indent=1)
    print(json.dumps(stats, indent=1))


if __name__ == "__main__":
    main()
