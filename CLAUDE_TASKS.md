# Lane C: tasks for Claude Code

Paste one task at a time into Claude Code. Read `contracts.md` first. You own only `pipeline/`, `data/`, `server.py`, and `web/`. Call Gemini only through the `gem` functions in `contracts.md`. Do not edit `gem/` or `media/`.

**Shared TODO:** keep [TODO.md](TODO.md) current. Mark your task `doing` when you start and `done` with a check when you finish, and edit only the Lane C rows. Talk to Gemini under **Messages**. Read the Messages section before every task.

Setup facts:
- Python venv: `.venv` (Python 3.15 with `google-genai` and `requests`; no pandas, numpy, networkx, or osmnx). Use the standard library.
- Map pattern: `experiments/nyc-live-eyes.html` (Leaflet 1.9.4, Esri dark gray tiles). OpenStreetMap tiles are blocked from `file://`, so keep Esri.
- 311 data: `https://data.sf.gov/resource/vw6y-z8j6.json` (Socrata, no key). Filter on `lower(service_subtype)='flooding'`. Fields: `requested_datetime`, `address`, `lat`, `long`. There are 33,103 rows.
- Verified on 2026-11-18: 778 reports, with 119 at 9 AM, 384 at 10 AM, and 134 at 11 AM.
- Verified Nov 18 forecast (Open-Meteo previous-runs API, `precipitation_previous_day1`): 59.3 mm for the day. The latest run gave 46.4 mm and peaked at 9–10 AM; the night-before run did not catch that peak.
- Router: Valhalla at `https://valhalla1.openstreetmap.de/route` with `exclude_polygons` (status 200). Fallback: public OSRM.

---

## C1 (to 4:15): `pipeline/build.py`

1. Page through Socrata (`$limit=50000`) and cache the raw JSON to `data/raw/`.
2. Bin every report to grid cells (see `contracts.md`).
3. Find storm days, meaning days with 50 or more reports.
4. Pull Open-Meteo archive hourly rain for SF from 2014 to 2026.
5. For each cell, set `thresh_mm_6h` to the 25th percentile of the 6-hour rain at the times its reports came in.
6. Write `data/cells.json` and `data/events_2026-11-18.json`.
7. Write `data/forecast_2026-11-18.json` twice: from `previous_day1` (the default) and from `latest`.

**Done when:** the events file has 778 rows, and the 10 AM hour has 384.

## C2 (to 4:30): `pipeline/baseline.py`

Build threshold-based zones in the zones contract, with `generated_by: "baseline"`. A cell joins a zone when the forecast's 6-hour sum exceeds its `thresh_mm_6h`. Merge neighboring cells into zones.

This unblocks the UI before Carbon zones exist, and it is the comparison row for the score.

## C3 (to 5:30): `server.py` and `web/index.html` (replay)

`server.py` is a standard-library `ThreadingHTTPServer`. It serves `web/` and `data/`, plus the `/api/*` routes.

The replay page has:
- a clock scrubber starting at 6 AM
- real 311 events dropping onto the map at their real times
- zone polygons colored by status
- an 11 AM marker reading "Waymo paused the city"

**Done when:** pressing play runs 6 AM to 2 PM in 40 s.

## C4 (to 6:15): Approval and score

Add a side panel per zone showing the reason and evidence, with Approve, Reject, and Edit-window controls. It calls `POST /api/zones/approve`.

Build `GET /api/score`:
- Count only approved zones.
- `pct_in_zone` is the share of events inside an active zone.
- `median_lead_min` is the event time minus the zone start.
- `zone_area_pct` is the zones' share of the city area.

Show the baseline row next to the Carbon row.

## C5 (to 7:00): `POST /api/route`

Call Valhalla with `exclude_polygons`, sending only approved zones that are active and near the trip corridor (to stay under the server's perimeter limit). Fall back to OSRM with `alternatives=true`, picking the route with the fewest zone hits.

Draw the default route in red and the safe route in green, with `added_min`.

**Done when:** a SoMa trip shows both lines.

## C6 (to 7:30): `web/cam.html`

Use `getUserMedia` on `localhost` (camera access needs a secure origin). Post a frame every 2 s to `/api/camera`. The server calls `gem.vision.judge_frame`, then `gem.agent.run_incident` when `flooded_p` is at least 0.8.

The new zone appears on the main map by polling, and routes recompute.

## C7 (to 8:15): Live mode

Add a toggle that:
1. fetches the real forecast for 2026-11-25 into `data/forecast_2026-11-25.json` (source `live`)
2. calls `gem.plan.propose_zones`
3. shows the zones awaiting approval

Add a "View flooded" button on a zone that calls `gem.world.render_flood` and plays the result.
