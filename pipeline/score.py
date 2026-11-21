"""C4: score a zone set against the real 311 floods of that day.

Only approved zones count (the ops manager's decision). Also reports the
"if every proposed zone were approved" numbers so sets can be compared fairly.
"""
import json
import os
import statistics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
SF_CELLS = 4340  # ~121 km2 / ~0.0279 km2 per cell


def _load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _mins(t):
    return int(t[11:13]) * 60 + int(t[14:16])


def _measure(zones, events):
    cell_z = {}
    for z in zones:
        for c in z["cells"]:
            cell_z.setdefault(c, []).append(z)
    leads, inside = [], 0
    for e in events:
        m = _mins(e["t"])
        hit = [z for z in cell_z.get(e["cell"], []) if _mins(z["start"]) <= m <= _mins(z["end"])]
        if hit:
            inside += 1
            leads.append(m - min(_mins(z["start"]) for z in hit))
    cells = {c for z in zones for c in z["cells"]}
    n = len(events)
    return {
        "n_events": n,
        "n_in_zone": inside,
        "pct_in_zone": round(inside / n, 3) if n else None,
        "median_lead_min": int(statistics.median(leads)) if leads else None,
        "zone_area_pct": round(len(cells) / SF_CELLS, 3),
        "n_zones": len(zones),
    }


def score(date, zset="carbon"):
    name = f"zones_{date}.json" if zset == "carbon" else f"zones_{date}_baseline.json"
    zf = _load(os.path.join(DATA, name))
    if zf is None and zset == "carbon":
        zset, zf = "baseline", _load(os.path.join(DATA, f"zones_{date}_baseline.json"))
    events = _load(os.path.join(DATA, f"events_{date}.json"), [])
    if zf is None:
        return {"error": "no zones", "date": date}
    ap = _load(os.path.join(DATA, f"approvals_{date}_{zset}.json"), {})
    zones = zf["zones"] + _load(os.path.join(DATA, f"camera_zones_{date}.json"), [])
    for z in zones:
        z["status"] = ap.get(z["id"], z.get("status", "proposed"))
    approved = [z for z in zones if z["status"] == "approved"]
    proposed = [z for z in zones if z["status"] != "rejected"]
    return {"date": date, "set": zset, "generated_by": zf.get("generated_by"),
            "forecast_source": zf.get("forecast_source"),
            **_measure(approved, events),
            "if_all_approved": _measure(proposed, events)}


if __name__ == "__main__":
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else "2026-11-18"
    for s in ("carbon", "baseline"):
        print(json.dumps(score(d, s)))
