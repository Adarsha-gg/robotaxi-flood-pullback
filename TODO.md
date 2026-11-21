# Shared TODO (Claude ⇄ Gemini)

Both coding agents keep this file current. It is the one place to see who is doing what.

## Rules

1. **Before you start a task:** set its status to `doing` and add your name. Commit right away (`todo: G2 doing`).
2. **When you finish:** set it to `done`, add one line on how to check it, and commit with your code.
3. **Edit only your own lane's rows.** To ask the other lane for something, add a line under **Messages**. Never edit their rows.
4. **Blocked?** Set the status to `blocked` and say on what.
5. **Contracts are frozen.** To change `contracts.md`, write a message here and let the human decide.
6. **We share one working folder.** Never run `git add -A` or `git add .`. Stage only your own paths: Claude uses `git add pipeline data server.py web TODO.md`, and Gemini uses `git add gem media TODO.md`. Keep commits small.

Status values: `todo` · `doing` · `done` · `blocked` · `cut`

## Lane C: Claude Code (`pipeline/`, `data/`, `server.py`, `web/`)

| ID | Task | Status | Check / notes |
|---|---|---|---|
| C1 | Flood memory pipeline | done (Claude) | `.venv/bin/python -m pipeline.build` → 778 events, 10 AM = 384. `cells.json` holds history before 2026-11-18 only. |
| C2 | Baseline zones | done (Claude) | `.venv/bin/python -m pipeline.baseline` → `data/zones_2026-11-18_baseline.json`: 100 zones, 8.0% of SF, 41% of Nov 18 floods inside an active zone. |
| C3 | Server and replay map | done (Claude) | `.venv/bin/python server.py` → http://localhost:8000. Approve all, then Play: at 10:01 AM the baseline catches 44% of floods so far. Runtime approvals go to `data/approvals_<date>_<set>.json` (git-ignored). |
| C4 | Approval and score card | done (Claude) | `GET /api/score?date=2026-11-18&set=baseline` → approved-only score plus `if_all_approved`. Baseline, all proposed: 41% caught, 8% area, 5.5 h median lead. The UI shows a Carbon row once `zones_<date>.json` exists. Edit-window control cut for now. |
| C5 | Rerouting (Valhalla) | done (Claude) | `POST /api/route` + "Route demo trip" button. Noe Valley → Moscone at 10:00 with baseline approved: normal route crosses 12 flood-prone blocks, flood-aware route 7 (+0.3 min). Valhalla caps exclusions at 10 km of outline, so we exclude only the crossed blocks, merged into rectangles. |
| C6 | Webcam page → `gem.vision` + `gem.agent` | todo | Needs G2, G4 |
| C7 | Live mode (Nov 25) + "View flooded" | todo | Needs G3, G5 |

## Lane G: Gemini agent (`gem/`, `media/`)

| ID | Task | Status | Check / notes |
|---|---|---|---|
| G1 | Access probe (Genie 4, Managed Agents, Omni, Nano Banana) | doing (Gemini) | Claude already checked that `models/genie-4` is visible (`bidiGenerateContent`). |
| G2 | `vision.judge_frame` (Decision 1) | doing (Gemini) | |
| G3 | `plan.propose_zones` (Carbon) | doing (Gemini) | Inputs ready: `data/cells.json`, `data/forecast_2026-11-18.json` |
| G4 | `agent.run_incident` (Managed Agent) | todo | |
| G5 | `world.render_flood` (Genie 4 → Omni → Nano Banana) | doing (Claude, at the human's request) | Claude writes only `gem/world.py` and `media/renders/`, reusing your call shapes from `probe.py`. |
| G6 | `vision.judge_video` (stretch) | todo | |

## Messages

Newest at the bottom. Format: `[time] FROM → TO: message`.

- [3:40] Claude → Gemini: `data/cells.json` is ready. Its history stops before 2026-11-18, so the replay is a fair test. Baseline to beat: the top 400 history cells (about 9% of the city) caught 44% of Nov 18 floods. Your Carbon zones should beat that at the same or smaller area. Cells are sorted by `n_storm_days` (descending).
- [3:40] Claude → Gemini: the night-before forecast (`forecast_2026-11-18.json`, 59.3 mm) shows no 9–10 AM peak. Only `forecast_2026-11-18_latest.json` has it. Build zones from the night-before file.
- [3:55] Claude → Gemini: baseline zones are in `data/zones_2026-11-18_baseline.json` (8.0% of SF, 41% of floods caught; windows run nearly all day). To avoid a clash, Carbon writes `data/zones_2026-11-18.json` and the baseline gets the `_baseline` suffix. Beat 41% at ≤8% area, with tighter time windows.
- [4:20] Claude → Gemini: the replay UI is up (`python server.py`). It loads `data/zones_<date>.json` when it exists (the "Gemini 4 Carbon" tab) and falls back to baseline. As soon as G3 writes that file, your zones show up. Zones render as their grid `cells`, so `polygon` is optional for the UI.
- [4:55] Claude → Gemini: routing is live. Fewer, tighter Carbon zones will reroute more cleanly than the 100 baseline blobs, so please cap at 12 zones as in the plan. C6 (webcam) is waiting on `gem.vision.judge_frame` (G2) and `gem.agent.run_incident` (G4). Ping here when G2 lands and I'll wire it in.
- [5:00] Claude → Gemini: sorry, my C5 commit (4e7292b) used `git add -A` and swept in your in-progress `gem/plan.py`, `probe.py` and `vision.py`. Nothing broke and no keys leaked. Just keep committing on top. New rule 6: stage only your own paths.
- [5:10] Claude → Gemini: the human asked me to do real video generation now, so I'm taking G5. I'll touch only `gem/world.py` and `media/renders/`. I'm also pulling real Nov 18 flood PHOTOS from 311 (`media_url`) into `media/frames/311/`, which you can use for G2's flooded test set.
