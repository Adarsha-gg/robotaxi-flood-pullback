# Contracts (frozen)

Both agents read this file. Only the human changes it. All times are naive local `America/Los_Angeles` ISO strings.

## Ownership

| Lane | Agent | Owns |
|---|---|---|
| G | Gemini (Antigravity / Gemini CLI) | `gem/`, `media/` |
| C | Claude Code | `pipeline/`, `data/`, `server.py`, `web/` |

Commit only inside your own directories. Shared files (`contracts.md`, `README.md`, `PLAN.md`) are the human's.

## Grid

Plain lat/lon grid, about 165 m cells. Cell id `r{row}_c{col}`.
`row = floor((lat - 37.70) / 0.0015)`, `col = floor((lon - -122.52) / 0.0019)`.

## Data files (Lane C writes, Lane G reads)

```jsonc
// data/cells.json   (history strictly BEFORE history_before, so the Nov 18 replay can't peek)
{"grid":{"lat0":37.70,"lon0":-122.52,"dlat":0.0015,"dlon":0.0019},
 "history_before":"2026-11-18","storm_days":["2025-12-26","..."],
 "cells":[{"id":"r41_c57","lat":37.7615,"lon":-122.4108,"n_reports":212,"n_storm_days":9,
   "storm_days":["2022-12-31","2019-12-07"],"thresh_mm_6h":14.0,"top_addresses":["..."]}]}

// data/forecast_<date>.json          (source: previous_day1 = night-before run; the default for zones)
// data/forecast_<date>_latest.json   (source: latest; caught the real 9-10 AM peak on Nov 18)
// live mode: data/forecast_<date>.json with source: live
{"date":"2026-11-18","source":"previous_day1","total_mm":59.3,
 "hours":[{"t":"2026-11-18T06:00","mm":5.4}]}

// data/events_<date>.json   (real 311 street-flooding reports)
[{"t":"2026-11-18T10:14:00","lat":37.76,"lon":-122.41,"address":"...","cell":"r41_c57"}]

// data/zones_<date>.json   (Lane G writes via gem.plan)
// data/zones_<date>_baseline.json   (Lane C, pipeline/baseline.py, generated_by: baseline)
{"date":"2026-11-18","forecast_source":"previous_day1","generated_by":"gemini-4-carbon|baseline",
 "zones":[{"id":"z3","name":"Folsom & 17th","cells":["r41_c57"],
   "polygon":[[-122.41,37.76]],
   "start":"2026-11-18T06:00","end":"2026-11-18T14:00","p_flood":0.82,
   "reason":"Flooded on 5 of the last 6 storms over 40 mm/day ...",
   "evidence":{"n_reports":212,"storm_days":["2022-12-31"]},
   "status":"proposed|approved|rejected","source":"forecast|camera"}]}
```

Polygon points are `[lon, lat]`.

## HTTP API (Lane C serves)

```jsonc
// POST /api/camera {image_b64, lat, lon, car_id}  ->
{"car_id":"W-112","t":"...","cell":"r41_c57","flooded_p":0.93,"depth_score":0.7,
 "depth_label":"none|wet|ankle|impassable","latency_ms":210,"zone":{/* zone, source:"camera" */}}

// POST /api/route {from:[lat,lon], to:[lat,lon], t}  ->
{"default":{"coords":[[lat,lon]],"min":14,"km":6.1,"hits_zones":["z3"]},
 "safe":{"coords":[[lat,lon]],"min":17,"km":7.0,"hits_zones":[]},"added_min":3}

// GET /api/score?date=2026-11-18  ->
{"n_events":778,"pct_in_zone":0.71,"median_lead_min":190,"zone_area_pct":0.06}

// POST /api/zones/approve {date, zone_id, status}  -> updated zone
```

Only `approved` zones count toward routing and the score.

## Python surface (Lane G exposes, Lane C calls)

```python
from gem import plan, vision, world, agent

plan.propose_zones(cells: list, forecast: dict, date: str) -> dict      # zones contract
vision.judge_frame(jpeg: bytes) -> dict    # flooded_p, depth_score, depth_label, latency_ms
vision.judge_video(path: str) -> dict      # same + "summary", "first_water_s"
world.render_flood(lat: float, lon: float, jpeg: bytes | None) -> dict  # {"kind":"genie|video|image","path":"media/..."}
agent.run_incident(verdict: dict) -> list[dict]   # steps [{"tool","args","result"}], last result is a zone
```

These five functions are the only cross-lane code surface.
