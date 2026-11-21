# Lane G: tasks for the Gemini coding agent

Paste one task at a time into Antigravity or Gemini CLI. Read `contracts.md` first. You own only `gem/` and `media/`. Do not edit any other folder.

**Shared TODO:** keep [TODO.md](TODO.md) current. Mark your task `doing` when you start and `done` with a check when you finish, and edit only the Lane G rows. Talk to Claude under **Messages**. Read the Messages section before every task.

Setup facts:
- Python venv: `.venv` (Python 3.15, `google-genai` 3.6.1, `python-dotenv`). Key in `.env` as `GEMINI_API_KEY`.
- Load the key with `load_dotenv("/Users/adarsha/new proj/.env")` (an explicit path; bare `load_dotenv()` fails on this Python).
- Working Decision 1 pattern: `experiments/frame_test.py` and `experiments/bike_lane_scan.py`.
  `genai.Client(http_options={"api_version":"v1beta"}).decisions.create(model="models/gemini-decision-1", input=[{"type":"image","data":b64,"mime_type":"image/jpeg"}], questions={...})`, then read `res.answers[q].noul`.
- The key can see these models: `gemini-4-carbon`, `gemini-4-neon`, `gemini-4-hydrogen`, `gemini-decision-1`, `genie-4` (supports `bidiGenerateContent`, so it is a live stream), `gemini-omni-1.2-flash`, `gemini-nano-banana-2.1`, `gemini-3.8-live`.
- Genie 4 costs about $0.10 per second. Keep every test under 10 seconds.

---

## G1 (3:20–3:45): Access probe

Write `gem/probe.py`. It makes one minimal call each to:
- `genie-4` (a live session, about 5 seconds, from a text prompt of a flooded San Francisco street)
- the Managed Agents API
- `gemini-omni-1.2-flash` (one short clip)
- `gemini-nano-banana-2.1` (one image edit)

It prints a PASS/FAIL table with the error text.

**Done when:** the table prints. Tell the human which `world.render_flood` path to use and whether Managed Agents works.

## G2 (to 4:30): `gem/vision.py` → `judge_frame`

Use Decision 1 with two questions:
- `flooded`, type `noul`: "Is standing water covering the roadway?"
- `depth`, type `score`, criteria `["none","wet","ankle","impassable"]`

Return the contract dict, with `depth_label` as the top score level and `latency_ms` measured.

Collect 8 real flood images from the 2026-11-18 San Francisco storm (news and social posts) and 4 dry-street images into `media/frames/`. Add a `SOURCES.md` there with the URL for each.

**Done when:** `python -m gem.vision media/frames/*` prints contract JSON per image, flooded images score ≥0.8, and dry ones ≤0.2.

## G3 (to 5:45): `gem/plan.py` → `propose_zones`

Depends on Lane C's `data/cells.json` and `data/forecast_2026-11-18.json`. Until they exist, use a 5-cell stub.

1. Pre-rank the top 60 cells by `n_storm_days`.
2. Send them plus the forecast to `gemini-4-carbon`. Ask for at most 12 zones, each with a time window and a plain-language reason that cites real storm dates.
   - Prompt rule: reason from the day total and 6-hour sums, not single hours. The night-before forecast for Nov 18 got the day right (59 mm) but the hour wrong.
   - Use structured JSON output.
3. Get `p_flood` per zone from Decision 1 `score`.
4. Build each zone polygon as the convex hull of its cell centers, padded by half a cell.

**Done when:** `python -m gem.plan 2026-11-18` writes a valid `data/zones_2026-11-18.json` in under 60 s, and every reason names at least one real date from `storm_days`.

## G4 (to 6:45): `gem/agent.py` → `run_incident`

This targets the $5k Managed Agents prize. Build an agent with these tools:
- `get_cell_history(cell)`
- `get_forecast(date)`
- `judge_frame(path)`
- `propose_zone(cells, start, end, reason)`

Given a camera verdict, it decides the zone's extent and duration and drafts a one-line fleet notice. Return the list of steps; the last result is the zone (`source: "camera"`).

If G1 showed Managed Agents is unavailable, build a Carbon function-calling loop with the same return shape.

**Done when:** `python -m gem.agent media/frames/<flood>.jpg 37.76 -122.41` prints at least 3 tool steps and a zone.

## G5 (to 7:30): `gem/world.py` → `render_flood`

Try Genie 4 first, starting from the street image if one is given. Fall back to Omni 1.2 Flash, then to a Nano Banana edit of a street image. Return `{"kind","path"}`.

Pre-render one demo intersection and save it in `media/renders/`. Label every output as an illustration, not a measurement.

**Done when:** it returns a playable file for the demo intersection.

## G6 (stretch): `vision.judge_video`

Use `gemini-4-hydrogen` on one 2026-11-18 flood clip. Return the contract fields plus `summary` and `first_water_s`.
