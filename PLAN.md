# Plan: Robotaxi Flood Pull-Back

**Pitch:** "Flood Pull-Back tells a robotaxi fleet manager, the night before, which streets to close and when. Then the first car that sees water closes the street for every other car."

**Role:** robotaxi fleet operations manager.

**Why now:**
- On 2026-11-18, Waymo paused all San Francisco service around 11 AM after cars stopped in flooded streets.
- That day San Francisco logged 778 street-flooding reports to 311, the most on record.
- Waymo's earlier flood patch, after the San Antonio recall of 3,791 vehicles, was reported as "not effective enough."
- Genie 4 opened to developers on 2026-11-19.

## Two lanes

| Lane | Agent | Owns | Tasks |
|---|---|---|---|
| G | Gemini (Antigravity / Gemini CLI) | `gem/`, `media/` | [GEMINI_TASKS.md](GEMINI_TASKS.md) |
| C | Claude Code | `pipeline/`, `data/`, `server.py`, `web/` | [CLAUDE_TASKS.md](CLAUDE_TASKS.md) |

The interface between the lanes is [contracts.md](contracts.md). It is frozen, and only the human changes it.

## Facts that shape the design (verified 2026-11-21)

- **No osmnx.** Use a plain lat/lon grid of about 165 m cells and a hosted router (Valhalla, falling back to OSRM).
- **The night-before forecast for Nov 18 got the day right but the hour wrong.** It predicted 59.3 mm for the day and 5.4 mm at 6 AM, but only 0.7 mm at 9 AM and 0.0 mm at 10 AM. The real peak (9–10 AM) shows up only in the latest model run.
- **So forecast zones key on storm-day and 6-hour totals,** and the fleet camera layer fixes the timing. That is the honest story: Atlanta's roads "flooded before NWS warned."
- **The key can see `genie-4`** (a live stream, `bidiGenerateContent`) and every Gemini 4 model. The Managed Agents API is not yet probed.

## Merge points

| Time | Merge | What must work |
|---|---|---|
| 4:30 | M1 | Replay with baseline zones; `judge_frame` CLI |
| 6:00 | M2 | Carbon zones in the UI with approval; score card |
| 7:30 | M3 | Camera to agent to zone to reroute; flood render |

## Timeline

| Time | Checkpoint |
|---|---|
| 3:00–3:20 | Contracts frozen, repo initialized |
| 3:45 | Genie 4 and Managed Agents go/no-go (G1) |
| 4:30 | M1 |
| 6:00 | M2; eat |
| 7:30 | M3 |
| 8:15 | Live mode |
| **8:30** | **Feature freeze** |
| 8:30–9:15 | Three timed rehearsals; record a backup screen capture |
| 9:15–9:45 | Bug fixes only; README and submission |
| 9:45 | Submit |

## Cut list (drop first to last)

1. G6 video judging
2. Phone camera (keep the laptop webcam)
3. Genie interactivity (use a still or clip)
4. Editing zone windows
5. Per-zone Decision 1 `p_flood` (use empirical frequency)
6. Live mode's flood render

Never cut: replay, approval, the camera-to-zone path, the score card.

## Fallbacks

- **Genie 4 fails:** Omni clip, then a Nano Banana edit, labeled honestly.
- **Managed Agents unavailable:** a Carbon tool loop, and drop that prize claim.
- **Previous-runs data missing for a date:** use the Historical Forecast API and label the source.
- **Valhalla down:** OSRM with `alternatives=true`.
- **Socrata slow:** cache the raw JSON on the first run.

## Demo script (2:50)

| Time | Beat |
|---|---|
| 0:00 | "Wednesday, Waymo paused all of San Francisco. I'm the fleet ops manager, and it's Tuesday night." |
| 0:15 | The night-before forecast. Carbon's zones with reasons ("flooded on 5 of the last 6 big storms"). Approve 10, reject 1. |
| 0:45 | Press play. Real 311 reports land in the red zones. The trip reroutes around the underpass. The 11 AM pause marker appears. |
| 1:20 | Score card: percent of floods inside zones, median lead time, zone area. Say it plainly: "the forecast knew the day, not the hour." |
| 1:35 | Hold a flood photo to the webcam. Decision 1 verdict in about 200 ms. The agent's tool steps. A new zone appears, and every route updates. |
| 2:10 | "View flooded": the Genie 4 scene of that street. |
| 2:30 | Live mode: the real forecast for Nov 25 (about 9 mm), with zones awaiting approval. |
| 2:45 | Pitch line. |

## Top risks

1. **The night-before forecast missed the hour, so zones can look wrong.** Use storm-day windows, show the zone area, and let the camera layer carry the timing.
2. **Genie 4 or Managed Agents access.** Probe by 3:45, with fallbacks decided in advance.
3. **Zones too broad, so the score looks gamed.** Cap at 12 zones and about 8% of the city's area, and show the baseline row.
4. **Stage network or latency.** Cache `data/`, pre-render the flood scene, and record a backup. The camera and Carbon calls stay live.
5. **The two agents collide.** Enforce folder ownership and the frozen `contracts.md`.
