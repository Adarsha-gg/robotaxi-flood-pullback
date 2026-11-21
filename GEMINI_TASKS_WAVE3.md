# Lane G, Wave 3: make the ride demo stronger

Written 2026-11-21, 3:05 PM EST. The hackathon ends at 10 PM. Feature freeze is 7:00 PM. After that we only rehearse.

## Story the demo tells

1. A robotaxi rides from Stanyan & Fell to Chase Center on 2026-11-18. A new forecast lands mid-ride: 8.6 mm/h at 09:00.
2. The car checks flood memory. 4th & King flooded on 17 past storms (real SF 311 reports).
3. The car does what no map can do: Genie 4 builds that street from a real resident photo and plays the forecast forward.
4. Decision 1 judges the simulated frames in under a second. Carbon explains the choice. A Managed Agent leaves an audit trail.
5. The car reroutes (Valhalla). Real 311 reports prove it: about 34 floods on the old route, about 16 on the new one.

Every task below makes one of these five lines faster, safer on stage, or more believable to DeepMind judges.

## Rules for this wave

- You own `gem/` and `media/` only. Do not edit `pipeline/`, `server.py`, `web/`, `data/`, `README.md`, `contracts.md`.
- Do not import from `pipeline/`. If a task needs routing, Claude passes a callable in.
- Do not change these frozen signatures: `vision.judge_frame`, `vision.judge_video`, `world.render_flood`, `agent.run_incident`, `plan.propose_zones`.
- Do not edit `gem/world.py`. Claude wrote it and `/ride` depends on it. Wrap `GenieSession` from a new file.
- The new functions in this wave extend the Python surface in `contracts.md`. The human approves that. Build them anyway; Claude calls them behind `try/except`.
- Genie 4 costs about $0.10 per second. Keep each test under 10 s. Always stop the session in `finally`.
- Every network call needs a timeout and a fallback. A function in this wave must never raise to its caller.
- Read TODO.md Messages before each task. Mark your row `doing`, then `done` with the check command.
- Do the tasks in order. If you run late, cut from the bottom.

Facts you need:

- `pipeline.ride.plan()` returns the `plan` dict. Keys you may read: `t`, `date`, `warning` (`source`, `next_hours`, `peak{t,mm}`, `text`), `forecast_6h_mm`, `watch` (`cell`, `lat`, `lon`, `name`, `n_storm_days`, `storm_days` (5 dates), `thresh_mm_6h`, `eta`, `photo{path,address,dist_m}`), `risky_detail[]` (same shape as `watch`, no photo), `route{min,km}`, `decide_t`.
- `pipeline.ride.simulate()` returns today: `{"verdict": judge_frame dict, "frame": "media/renders/sim_<cell>_<ts>.jpg", "genie_first_frame_s", "total_s", "frames_seen"}`. Your G7 output must be a superset of this.
- `GenieSession(image, prompt, max_seconds).start()`; fields `status` (`starting|warming|live|stopped|error`), `frame` (latest JPEG bytes), `frames` (list), `frame_no`, `first_frame_at`, `started_at`, `error`; methods `send_key("key_down","key_w")`, `stop()`, `save_mp4(path)`.
- Get a test plan without the server: save one from `curl -s -X POST localhost:8000/api/ride/plan -d '{}' > media/sim_cache/plan_sample.json` (Claude's server must run), then load it in your `__main__` blocks.

---

## G7 (3:10–3:55, 45 min): Stage-proof simulation: pre-warm + cached fallback

**Goal.** Step 4 never fails and feels instant. Genie's first frame takes about 5 s. Start Genie when the forecast warning fires (step 2), not when step 4 opens. If Genie is slow or the Wi-Fi drops, return a cached real Genie result.

**Files owned.** `gem/sim.py` (new), `media/sim_cache/` (new).

**Signatures.**

```python
# gem/sim.py
def build_prompt(watch: dict, warning: dict) -> str
    # Same text pipeline.ride.simulate builds today. Copy it. Numbers come from watch and warning only.

def prewarm(watch: dict, warning: dict, session_holder: dict) -> dict
    # Starts GenieSession in the background. Returns at once (< 50 ms).
    # Sets session_holder["session"] and session_holder["photo"] = {**watch["photo"], "zone": watch["name"]}.
    # Stops any session already in the holder first.
    # Returns {"ok": bool, "started_at": float, "cell": str, "error": str | None}

def simulate_street(watch: dict, warning: dict, session_holder: dict,
                    settle_s: float = 1.2, max_wait_s: float = 12.0, n_frames: int = 3) -> dict
    # Reuses the pre-warmed session if session_holder holds a live or warming one for the same cell.
    # Else starts one. Presses W, waits settle_s, grabs n_frames frames about 0.4 s apart.
    # Judges them (G8 rubric when it exists; until then vision.judge_frame on the last frame).
    # If there is no frame after max_wait_s, or anything raises: load the cache. Never raise.
    # Returns the pipeline.ride.simulate dict plus:
    #   "source": "genie" | "genie_prewarmed" | "cache"
    #   "frames": ["media/renders/sim_<cell>_<ts>_0.jpg", ...]   # "frame" stays = the last one
    #   "waited_s": seconds the caller waited inside this call
    #   "error": str | None        # why we fell back

def record_cache(watch: dict, warning: dict, seconds: float = 6.0) -> dict
    # Run once now. Saves media/sim_cache/<cell>/frame_0..2.jpg, clip.mp4, result.json (a full simulate_street dict).
```

**Done-check.**

- `.venv/bin/python -m gem.sim record media/sim_cache/plan_sample.json` writes `media/sim_cache/<cell>/result.json`, 3 frames and `clip.mp4`. Cost: one 6 s session.
- `.venv/bin/python -m gem.sim prewarm-test media/sim_cache/plan_sample.json` calls `prewarm`, sleeps 5 s, calls `simulate_street`, prints `source: genie_prewarmed` and `waited_s` under 3.0.
- `GEMINI_API_KEY=bad .venv/bin/python -m gem.sim run media/sim_cache/plan_sample.json` prints `source: cache`, a verdict, and exits 0 in under 13 s.

**Claude wires.** `server.py`: call `sim.prewarm(p["watch"], p["warning"], GENIE)` at the end of `/api/ride/plan`. `/api/ride/simulate` calls `sim.simulate_street(...)` and falls back to `ride.simulate`. `web/ride.html`: show a small "cached Genie run" tag when `source == "cache"`, and show `waited_s`.

---

## G8 (3:55–4:30, 35 min): Decision 1 rubric for the simulated frames

**Goal.** One yes/no is thin. Ask Decision 1 the questions a safety driver asks, on several frames, and aggregate. This is the "only Decision 1 can do this in 300 ms" beat.

**Files owned.** `gem/sim.py`.

**Signatures.**

```python
def judge_sim_frame(jpeg: bytes) -> dict
    # ONE decisions.create call, 640 px downscale (reuse vision._shrink_jpeg), these questions:
    #   flooded      noul   "Is standing water covering the roadway?"
    #   reaches_curb noul   "Does the water reach or cover the curb?"
    #   sedan_stall  noul   "Could a sedan stall or lose traction driving through this water?"
    #   lane_visible noul   "Are the lane markings still visible through the water?"
    #   depth        score  ["none","wet","ankle","impassable"]
    # Returns the judge_frame keys (flooded_p, depth_score, depth_label, latency_ms) plus
    #   "rubric": {"reaches_curb": float, "sedan_stall": float, "lane_visible": float}

def judge_sim(frames: list[bytes]) -> dict
    # Judges the frames in parallel threads. Wall time under 1.5 s for 3 frames.
    # Returns the judge_frame keys (median flooded_p, median depth_score, modal depth_label, latency_ms = wall time) plus
    #   "rubric": medians, "per_frame": [judge_sim_frame dicts],
    #   "trend": "rising" | "steady" | "falling"   # flooded_p first frame vs last frame, +-0.1
    #   "agreement": float   # 1 - (max flooded_p - min flooded_p)
    #   "action": "avoid" | "slow" | "proceed"
    #       avoid   if flooded_p >= 0.6 or sedan_stall >= 0.5
    #       slow    if flooded_p >= 0.3
    #       proceed otherwise
    # If one frame fails, drop it. If all fail, return vision.judge_frame keys with None values and action "slow".
```

Then make `simulate_street` use `judge_sim` and return its dict as `"verdict"`. The old keys stay, so the current UI keeps working.

**Done-check.**

- `.venv/bin/python -m gem.sim judge media/sim_cache/<cell>/frame_*.jpg` prints `action: avoid`, `flooded_p` >= 0.6, wall time under 1500 ms.
- `.venv/bin/python -m gem.sim judge media/frames/waymo/front_000.jpg media/frames/waymo/front_100.jpg media/frames/waymo/front_190.jpg` prints `action: proceed` or `slow`, never `avoid`. This is the no-false-alarm check on real Waymo rain frames.
- `.venv/bin/python -m gem.sim judge media/frames/dry_0*.jpg` prints `action: proceed`.

Write the three results into your TODO row. If the thresholds give a wrong action on a set, tune them and say what you chose.

**Claude wires.** `web/ride.html` step 4: four small bars (flooded, reaches curb, sedan could stall, lane visible), the depth label, "3 frames agree 94%", and the action. Step 5 uses `verdict.action` in place of the `pct >= 60` test.

---

## G9 (4:30–5:05, 35 min): Carbon explains the decision

**Goal.** Step 5 says why, in words a rider and a fleet operator each understand. Every number is real.

**Files owned.** `gem/explain.py` (new).

**Signature.**

```python
def explain_decision(plan: dict, sim: dict, reroute: dict | None = None, timeout_s: float = 8.0) -> dict
    # plan = pipeline.ride.plan() dict. sim = simulate_street() dict. reroute = {"added_min","min","km"} or None.
    # gemini-4-carbon, structured JSON output (pydantic schema, like gem/plan.py).
    # Returns:
    # {"action": "reroute" | "proceed",          # copy from sim["verdict"]["action"]: avoid -> reroute; do not let the model choose
    #  "headline": str,                          # <= 90 chars
    #  "reasons": [str, str, str],               # exactly 3: forecast, flood memory, simulation
    #  "rider_message": str,                     # <= 140 chars, calm, no jargon, says the added minutes if reroute is given
    #  "fleet_notice": str,                      # <= 200 chars, names the block and the time window
    #  "cited": {"storm_days": [..], "forecast_mm": float, "forecast_t": "HH:MM", "n_storm_days": int, "flooded_p": float},
    #  "model": "gemini-4-carbon" | "template", "latency_ms": int}
```

**Hard rules.**

- Give Carbon only `warning`, `forecast_6h_mm`, `watch`, the top 3 of `risky_detail`, `sim["verdict"]`, `reroute`. Do not send events from Nov 18. The proof step must stay a fair test.
- Validate after the call. Every `YYYY-MM-DD` in the text must be in `watch["storm_days"]` or a `risky_detail` list. Every mm figure must equal `warning["peak"]["mm"]` or `forecast_6h_mm`. If validation fails, retry once, then use the template.
- Call the model in a thread with `timeout_s`. On timeout or error, return a deterministic template built from the same fields, with `"model": "template"`. Never raise.
- State that the frame is a simulation. Use "simulated", not "observed".

**Done-check.** `.venv/bin/python -m gem.explain media/sim_cache/plan_sample.json media/sim_cache/<cell>/result.json` prints the JSON in under 8 s with `"model": "gemini-4-carbon"`. The reasons contain at least one real storm date, `8.6`, and `17`. Then `GEMINI_API_KEY=bad .venv/bin/python -m gem.explain ...` prints the template version in under 1 s and exits 0.

**Claude wires.** New route `POST /api/ride/explain` that calls it after reroute. `web/ride.html` step 5 shows `headline`, the 3 reasons, and a phone-style bubble with `rider_message`. The UI shows the reroute first and fills the text when it lands.

---

## G10 (5:05–6:00, 55 min): Managed Agent runs the ride decision (the $5k prize)

**Goal.** The same decision, run end to end by a Managed Agent with a visible tool trace. The live path stays fast. The agent runs beside it and gives the audit trail.

**Files owned.** `gem/agent.py` (add only; do not change `run_incident`), `media/traces/` (new).

**Signature.**

```python
def run_ride(plan: dict, tools: dict | None = None, on_step=None, timeout_s: float = 45.0) -> dict
    # Managed Agent (antigravity-preview-09-2026), same loop helpers as run_incident.
    # Agent tools:
    #   get_forecast(date)                -> existing function
    #   get_cell_history(cell)            -> existing function
    #   simulate_street(cell)             -> tools["simulate_street"](cell) if given, else the cached result in media/sim_cache/<cell>/result.json.
    #                                        Return only verdict + source to the agent. Never start a second Genie session from here.
    #   route_options(avoid_cells: list)  -> tools["route_options"](avoid_cells) if given (Claude injects it), else
    #                                        {"default": {"min": plan["route"]["min"]}, "safe": None}
    #   decide(action, avoid_cells, reason, rider_message, fleet_notice)   -> final step
    # on_step(step) fires as each step finishes, so the UI can stream it.
    # Returns:
    # {"steps": [{"tool","args","result","ms"}],        # >= 4 steps, the last tool is "decide"
    #  "decision": {"action": "reroute"|"proceed", "avoid_cells": [...], "reason": str, "rider_message": str, "fleet_notice": str},
    #  "agent_engine": "antigravity-preview-09-2026" | "gemini-4-carbon" | "replay",
    #  "interaction_id": str | None, "elapsed_s": float}

def load_ride_trace(date: str = "2026-11-18") -> dict | None
    # Returns the saved trace from media/traces/ride_<date>.json with agent_engine kept and "replayed": True.
```

**Fallback chain.** Managed Agent, then the Carbon function-calling loop you already have, then `load_ride_trace`. On `timeout_s` or any error, move down the chain. Never raise. Guard: `avoid_cells` must be a subset of `plan["risky"]`; drop the rest.

**Done-check.**

- `.venv/bin/python -m gem.agent ride media/sim_cache/plan_sample.json` prints at least 4 steps ending in `decide`, `agent_engine: antigravity-preview-09-2026`, a real `interaction_id`, and saves `media/traces/ride_2026-11-18.json`. Target under 30 s.
- `GEMINI_API_KEY=bad .venv/bin/python -m gem.agent ride media/sim_cache/plan_sample.json` prints the saved trace with `agent_engine` shown and `replayed: True`, in under 2 s.
- `.venv/bin/python -m gem.agent media/frames/flood_01.jpg 37.76 -122.41` still works (no regression in `run_incident`).

**Claude wires.** `server.py`: start `agent.run_ride(plan, tools={"route_options": ..., "simulate_street": ...}, on_step=...)` in a background thread when `/api/ride/plan` returns. New `GET /api/ride/agent` returns the steps so far. `web/ride.html`: an "Agent audit trail" drawer that fills step by step and shows the `interaction_id`. The drawer labels a replayed trace as replayed.

---

## G11 (6:00–6:35, 35 min): Backtest: is the flood memory real?

**Goal.** One honest number for the pitch. "Across N past storms, history picked before the storm caught X% of that storm's flooded blocks at 8% of the city."

**Files owned.** `gem/backtest.py` (new), `media/backtest.json` (new).

**Method.** Leave one storm out. `data/cells.json` holds 72 storm days and the full `storm_days` list per cell.

1. Take the 15 storm days with the most flooded cells. Print them.
2. For each held-out day D: remove D from every cell's list and recount `n_storm_days`. Rank cells two ways with the remaining days only:
   - `baseline`: top 347 cells by `n_storm_days`.
   - `corridor`: top 347 cells by `n_storm_days + 0.05 * sum(n_storm_days of the 8 neighbours)`. This is the pre-rank `gem.plan` uses before Carbon.
3. Score: share of cells that flooded on D that are inside the 347 picked cells. Also score a random pick of 347 cells (mean of 200 draws) as the floor.
4. No model calls. Pure Python. Runs in under 20 s.

**Output contract.** `media/backtest.json`:

```jsonc
{"n_storms": 15, "area_cells": 347, "area_pct": 0.08,
 "mean_caught": {"corridor": 0.0, "baseline": 0.0, "random": 0.0},
 "per_storm": [{"date": "2022-12-31", "flooded_cells": 0, "corridor": 0.0, "baseline": 0.0, "random": 0.0}],
 "worst_storm": {"date": "", "corridor": 0.0}, "best_storm": {"date": "", "corridor": 0.0},
 "caveat": "Spatial memory only. Past forecasts are not replayed. Unit is flooded cells, not reports.",
 "one_liner": "Across 15 past storms, flood memory chosen before each storm caught X% of flooded blocks at 8% of the city (random: Y%)."}
```

Also expose `backtest.run(n_storms: int = 15) -> dict` (same dict).

**Done-check.** `.venv/bin/python -m gem.backtest` prints a 15-row table and the one-liner, writes the file, and finishes in under 20 s. Report the numbers as they come out. Do not tune the method to lift them. If `corridor` loses to `baseline`, say so in your TODO row.

**Claude wires.** `web/ride.html` step 3 footnote and the ops console score card read `/media/backtest.json` and show `one_liner`.

---

## G12 (6:35–7:00, 25 min): Pitch assets

**Goal.** Text the human can paste. No code.

**Files owned.** `media/pitch/` (new). These are drafts. The human copies what they approve into `README.md` and Devpost.

1. `media/pitch/DEMO_SCRIPT.md`: the live demo, under 3 minutes, as a table: time, what is on screen, the exact words to say, which Gemini 4 model is working. Follow the six steps of `/ride`. Leave 20 s at the end for `/cam` with the real Waymo frame (no false alarm) or the agent trail. Add a "if it breaks" line per step that names the fallback from G7, G9, G10.
2. `media/pitch/BACKUP_CAPTURE.md`: a 60-second screen-capture shot list for a backup video. Each shot: URL, what to click, seconds. The human records it.
3. `media/pitch/HOW_IT_WORKS.md`: a README section, at most 150 words plus one table: model, job, measured latency. Rows: Genie 4, Decision 1, Carbon, Hydrogen, Managed Agents. Use only latencies from TODO.md rows or your own done-checks.
4. `media/pitch/DEVPOST.md`: Inspiration, What it does, How we built it, Challenges, What we learned, What's next. At most 120 words each.

**Rules.** Every number must appear in TODO.md, `media/backtest.json`, or a done-check you ran. Say "simulated" for Genie frames. Say the Waymo frames are from the Waymo Open Dataset and are not redistributed. Do not claim Waymo uses this. Plain short sentences.

**Done-check.** `wc -w media/pitch/*.md` shows four files. `grep -c "simulated" media/pitch/DEMO_SCRIPT.md` is at least 1. The script's times add up to 180 s or less.

**Claude wires.** Nothing. The human reviews.

---

## G13 (stretch, only if G7–G12 are done before 7:00, 20 min): Hydrogen watches the Genie clip

**Goal.** A second model checks the first. Hydrogen watches the cached Genie clip and says when water first reaches the curb.

**Files owned.** `gem/sim.py`, `media/sim_cache/<cell>/video.json`.

**Signature.** `sim.review_clip(path: str) -> dict`: calls the existing `vision.judge_video(path)` and returns its dict plus `"path"`. Save the result for `media/sim_cache/<cell>/clip.mp4` to `video.json`. This is offline only. Do not call it in the live path; it is too slow.

**Done-check.** `.venv/bin/python -m gem.sim review media/sim_cache/<cell>/clip.mp4` prints `flooded_p`, `first_water_s` and `summary`, and writes `video.json`.

**Claude wires.** Optional caption under the step 4 image: "Hydrogen review of this clip: water at the curb from N s."

---

## Cut ideas (do not build)

- Genie on live Nov 25 data in the ride. One story is enough.
- More zone tuning in `gem/plan.py`. The ride does not use zones.
- Calling Carbon 15 times in the backtest. Too slow, and the number means the same without it.
