"""C1: build flood memory from SF 311 + hourly rain.

Writes (see contracts.md):
  data/cells.json
  data/events_2026-11-18.json
  data/forecast_2026-11-18.json         (source: previous_day1, the night-before run)
  data/forecast_2026-11-18_latest.json  (source: latest)
Caches raw downloads in data/raw/.

Standard library only. Run: .venv/bin/python -m pipeline.build [--refresh]
"""
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")

SOCRATA = "https://data.sf.gov/resource/vw6y-z8j6.json"
SF = (37.7749, -122.4194)  # rain point: downtown SF
TZ = "America/Los_Angeles"
GRID = {"lat0": 37.70, "lon0": -122.52, "dlat": 0.0015, "dlon": 0.0019}
BBOX = (37.70, 37.84, -122.53, -122.35)  # lat min/max, lon min/max
STORM_DAY_MIN = 50
DEMO_DATE = "2026-11-18"


# ---------- helpers ----------
def get_json(url, params=None, tries=3):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "flood-pullback-hackathon"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"  retry {i+1}: {e}", file=sys.stderr)
            time.sleep(2 * (i + 1))


def cached(name, fetch, refresh):
    path = os.path.join(RAW, name)
    if os.path.exists(path) and not refresh:
        with open(path) as f:
            return json.load(f)
    data = fetch()
    with open(path, "w") as f:
        json.dump(data, f)
    return data


def cell_of(lat, lon):
    r = math.floor((lat - GRID["lat0"]) / GRID["dlat"])
    c = math.floor((lon - GRID["lon0"]) / GRID["dlon"])
    return r, c


def cell_center(r, c):
    return (round(GRID["lat0"] + (r + 0.5) * GRID["dlat"], 6),
            round(GRID["lon0"] + (c + 0.5) * GRID["dlon"], 6))


def percentile(xs, p):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


# ---------- 1. 311 flooding reports ----------
def fetch_311():
    rows, offset, page = [], 0, 50000
    while True:
        batch = get_json(SOCRATA, {
            "$select": "requested_datetime,address,lat,long,service_details",
            "$where": "lower(service_subtype)='flooding'",
            "$order": "requested_datetime",
            "$limit": page, "$offset": offset,
        })
        rows += batch
        print(f"  311: {len(rows)} rows")
        if len(batch) < page:
            return rows
        offset += page


def clean_reports(rows):
    out = []
    for x in rows:
        try:
            lat, lon = float(x["lat"]), float(x["long"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lon <= BBOX[3]):
            continue
        t = x["requested_datetime"][:19]  # naive local time
        r, c = cell_of(lat, lon)
        out.append({"t": t, "lat": lat, "lon": lon,
                    "address": (x.get("address") or "").replace(", SAN FRANCISCO, CA", "").split(", US")[0],
                    "details": x.get("service_details"), "cell": f"r{r}_c{c}"})
    return out


# ---------- 2. hourly rain ----------
def fetch_rain_history(first_day):
    """Hourly precip (mm), local time, first_day..today. ERA5 archive + recent model runs."""
    today = datetime.now().date()
    arch_end = today - timedelta(days=7)
    rain = {}
    # archive in yearly chunks (smaller responses)
    y0 = int(first_day[:4])
    for y in range(y0, arch_end.year + 1):
        s = max(first_day, f"{y}-01-01")
        e = min(arch_end.isoformat(), f"{y}-12-31")
        d = get_json("https://archive-api.open-meteo.com/v1/archive", {
            "latitude": SF[0], "longitude": SF[1], "start_date": s, "end_date": e,
            "hourly": "precipitation", "timezone": TZ})
        for t, mm in zip(d["hourly"]["time"], d["hourly"]["precipitation"]):
            rain[t] = mm or 0.0
        print(f"  rain archive {y}: {len(rain)} hours")
    # last ~week from the historical-forecast API
    d = get_json("https://historical-forecast-api.open-meteo.com/v1/forecast", {
        "latitude": SF[0], "longitude": SF[1],
        "start_date": (arch_end + timedelta(days=1)).isoformat(), "end_date": today.isoformat(),
        "hourly": "precipitation", "timezone": TZ})
    for t, mm in zip(d["hourly"]["time"], d["hourly"]["precipitation"]):
        if mm is not None:
            rain[t] = mm
    return rain


def rain_6h(rain, t):
    """Trailing 6-hour rain (mm) ending at the hour of local time t."""
    h = datetime.fromisoformat(t[:13] + ":00")
    return sum(rain.get((h - timedelta(hours=k)).strftime("%Y-%m-%dT%H:00"), 0.0) for k in range(6))


# ---------- 3. forecasts for the demo day ----------
def fetch_forecasts(date):
    d = get_json("https://previous-runs-api.open-meteo.com/v1/forecast", {
        "latitude": SF[0], "longitude": SF[1], "start_date": date, "end_date": date,
        "hourly": "precipitation_previous_day1,precipitation", "timezone": TZ})
    h = d["hourly"]
    out = {}
    for key, src in (("precipitation_previous_day1", "previous_day1"), ("precipitation", "latest")):
        hours = [{"t": t, "mm": round(mm or 0.0, 2)} for t, mm in zip(h["time"], h[key])]
        out[src] = {"date": date, "source": src,
                    "total_mm": round(sum(x["mm"] for x in hours), 1), "hours": hours}
    return out


def write(name, obj):
    path = os.path.join(DATA, name)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    print(f"wrote {path} ({os.path.getsize(path)//1024} KB)")


# ---------- main ----------
def main():
    refresh = "--refresh" in sys.argv
    os.makedirs(RAW, exist_ok=True)

    print("1. 311 reports")
    reports = clean_reports(cached("311_flooding.json", fetch_311, refresh))
    print(f"  {len(reports)} reports with valid SF coordinates")

    per_day = Counter(r["t"][:10] for r in reports)
    storm_days = sorted(d for d, n in per_day.items() if n >= STORM_DAY_MIN)
    print(f"  {len(storm_days)} storm days (>= {STORM_DAY_MIN} reports)")

    print("2. hourly rain")
    first = min(r["t"][:10] for r in reports)
    rain = cached("rain_hourly.json", lambda: fetch_rain_history(first), refresh)

    print(f"3. cells (history strictly before {DEMO_DATE}, so the replay score can't peek)")
    by_cell = defaultdict(list)
    for r in reports:
        if r["t"][:10] < DEMO_DATE:
            by_cell[r["cell"]].append(r)
    storm_days = [d for d in storm_days if d < DEMO_DATE]
    storm_set = set(storm_days)
    cells = []
    for cid, rs in by_cell.items():
        r_, c_ = (int(p[1:]) for p in cid.split("_"))
        lat, lon = cell_center(r_, c_)
        sdays = sorted({x["t"][:10] for x in rs if x["t"][:10] in storm_set}, reverse=True)
        r6 = [rain_6h(rain, x["t"]) for x in rs]
        r6 = [v for v in r6 if v > 0]
        th = percentile(r6, 0.25)
        cells.append({
            "id": cid, "lat": lat, "lon": lon,
            "n_reports": len(rs), "n_storm_days": len(sdays), "storm_days": sdays,
            "thresh_mm_6h": round(th, 1) if th is not None else None,
            "top_addresses": [a for a, _ in Counter(x["address"] for x in rs).most_common(3)],
        })
    cells.sort(key=lambda c: (-c["n_storm_days"], -c["n_reports"]))
    write("cells.json", {"grid": GRID, "history_before": DEMO_DATE, "storm_days": storm_days, "cells": cells})

    print(f"4. events {DEMO_DATE}")
    ev = sorted(({"t": r["t"], "lat": r["lat"], "lon": r["lon"], "address": r["address"], "cell": r["cell"]}
                 for r in reports if r["t"].startswith(DEMO_DATE)), key=lambda e: e["t"])
    write(f"events_{DEMO_DATE}.json", ev)
    by_hour = Counter(int(e["t"][11:13]) for e in ev)
    print(f"  {len(ev)} events; 9h={by_hour[9]} 10h={by_hour[10]} 11h={by_hour[11]}")

    print(f"5. forecasts {DEMO_DATE}")
    fc = fetch_forecasts(DEMO_DATE)
    write(f"forecast_{DEMO_DATE}.json", fc["previous_day1"])
    write(f"forecast_{DEMO_DATE}_latest.json", fc["latest"])
    print(f"  previous_day1 total={fc['previous_day1']['total_mm']} mm, latest total={fc['latest']['total_mm']} mm")


if __name__ == "__main__":
    main()
