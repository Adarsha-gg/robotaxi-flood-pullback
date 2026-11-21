"""C7: live mode for the next real storm.

1. Pick the date (argv or the next day with >= 5 mm in the live forecast).
2. Write data/forecast_<date>.json from the live Open-Meteo forecast (source "live").
3. Rebuild flood memory with ALL history up to today (Nov 18 included) -> data/cells_live.json.
4. Ask Gemini 4 Carbon for zones (gem.plan.propose_zones) -> data/zones_<date>.json.
5. Write data/live.json so the UI knows which date is live.
Run: .venv/bin/python -m pipeline.live [date]
"""
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date as Date

from pipeline import build

DATA = build.DATA


def pick_date():
    d = build.get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": build.SF[0], "longitude": build.SF[1], "daily": "precipitation_sum",
        "timezone": build.TZ, "forecast_days": 10})["daily"]
    today = Date.today().isoformat()
    for t, mm in zip(d["time"], d["precipitation_sum"]):
        if t > today and (mm or 0) >= 5:
            return t
    return max(zip(d["precipitation_sum"], d["time"]))[1]


def live_forecast(date):
    h = build.get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": build.SF[0], "longitude": build.SF[1], "hourly": "precipitation",
        "timezone": build.TZ, "start_date": date, "end_date": date})["hourly"]
    hours = [{"t": t, "mm": round(mm or 0.0, 2)} for t, mm in zip(h["time"], h["precipitation"])]
    return {"date": date, "source": "live", "total_mm": round(sum(x["mm"] for x in hours), 1), "hours": hours}


def live_cells(cutoff):
    with open(os.path.join(build.RAW, "311_flooding.json")) as f:
        reports = [r for r in build.clean_reports(json.load(f)) if r["t"][:10] < cutoff]
    with open(os.path.join(build.RAW, "rain_hourly.json")) as f:
        rain = json.load(f)
    per_day = Counter(r["t"][:10] for r in reports)
    storm_days = sorted(d for d, n in per_day.items() if n >= build.STORM_DAY_MIN)
    storm_set = set(storm_days)
    by_cell = defaultdict(list)
    for r in reports:
        by_cell[r["cell"]].append(r)
    cells = []
    for cid, rs in by_cell.items():
        r_, c_ = (int(p[1:]) for p in cid.split("_"))
        lat, lon = build.cell_center(r_, c_)
        sdays = sorted({x["t"][:10] for x in rs if x["t"][:10] in storm_set}, reverse=True)
        r6 = [v for v in (build.rain_6h(rain, x["t"]) for x in rs) if v > 0]
        th = build.percentile(r6, 0.25)
        cells.append({"id": cid, "lat": lat, "lon": lon, "n_reports": len(rs), "n_storm_days": len(sdays),
                      "storm_days": sdays, "thresh_mm_6h": round(th, 1) if th is not None else None,
                      "top_addresses": [a for a, _ in Counter(x["address"] for x in rs).most_common(3)]})
    cells.sort(key=lambda c: (-c["n_storm_days"], -c["n_reports"]))
    return {"grid": build.GRID, "history_before": cutoff, "storm_days": storm_days, "cells": cells}


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else pick_date()
    fc = live_forecast(date)
    build.write(f"forecast_{date}.json", fc)
    print(f"live forecast {date}: {fc['total_mm']} mm")
    cells = live_cells(Date.today().isoformat())
    build.write("cells_live.json", cells)
    print(f"cells_live: {len(cells['cells'])} cells, {len(cells['storm_days'])} storm days (Nov 18 included: {'2026-11-18' in cells['storm_days']})")
    from gem.plan import propose_zones
    zones = propose_zones(cells, fc, date)
    build.write(f"zones_{date}.json", zones)
    print(f"Carbon zones for {date}: {len(zones['zones'])}")
    for z in zones["zones"][:5]:
        print(f"  {z['name'][:40]:40} {z['start'][11:16]}-{z['end'][11:16]} p={z.get('p_flood')}")
    build.write("live.json", {"date": date, "total_mm": fc["total_mm"], "generated_by": zones.get("generated_by")})


if __name__ == "__main__":
    main()
