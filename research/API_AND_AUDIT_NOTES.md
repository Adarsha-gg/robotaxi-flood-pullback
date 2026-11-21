# Gemini 4 / SDK 3.6.1 API Notes & Remaining Hardening Checklist

*(Verified directly against `.venv/lib/python3.15/site-packages/google/genai/` v3.6.1 and codebase audit.)*

---

## 1. Verified `google-genai` 3.6.1 Patterns & Gotchas

### Genie 4 (`models/genie-4`)
- **Surface:** `v1beta` Live Interactions WebSocket (`beta.interactions.create(model="genie-4", background=True)` → `beta.aio.interactions.connect(inter.id)`). NOT `live.connect`.
- **Street photo seeding:** Send one `world_setup` event with `"world_prompt"` + top-level `"reference_image": {"data": b64, "mime_type": "image/jpeg"}`.
- **Output:** Fixed 720p (`1280×720`), 24 fps video (`step.delta`, base64-encoded `str`) + 48 kHz `s16le` stereo PCM audio; ~5–9 s to first frame; max 120 s session.
- **Billing safety (`~$0.10/s`):** Exiting `connect()` detaches only—always call BOTH `await conn.cancel()` AND `beta.interactions.cancel(inter_id)` in `finally`.

### Antigravity Managed Agents (`antigravity-preview-09-2026`)
- **Surface:** `beta.interactions.create(agent="antigravity-preview-09-2026", agent_config={"type": "antigravity", "model": "gemini-4-hydrogen", "max_total_tokens": 50000}, tools=[...], input=...)`.
- **Gotchas verified in SDK source:**
  - `Interaction` has **no `.outputs`** — read `inter.steps` (`step.type == "function_call"`, `.id`, `.name`, `.arguments: dict`, plus `ThoughtStep.summary`) and `inter.output_text`.
  - `CreateAgentInteraction` requires `agent="antigravity-preview-09-2026"` on **every** turn, including follow-ups with `previous_interaction_id=inter.id`.
  - Resume on `inter.status == "requires_action"` with `input=[{"type": "function_result", "call_id": call.id, "name": call.name, "result": out}, ...]`.
  - Also supports persistent registration (`beta.agents.create(...)`), `environment={"type": "remote"}` (dict), remote MCP servers (`type: "mcp_server"`), and Credentials API secret isolation.

### Gemini Decision 1 (`models/gemini-decision-1`)
- **Surface:** `v1beta` `beta.decisions.create(model="models/gemini-decision-1", input=..., questions={...})`. Prefill-only, 0 output tokens, up to 1,000 batched questions.
- **Calibration & latency:**
  - `noul` is strictly clamped to `[0.01, 0.99]`.
  - `score` uses `"criteria": list[str]` (verified); returns expected value `0..len-1` + `probabilities` + `legend`.
  - Downscaling images to ~640 px JPEG keeps compute inside the ~50–100 ms band (~200–400 ms end-to-end).

### Omni 1.2 Flash (`gemini-omni-1.2-flash`) & Nano Banana 2.1 (`gemini-nano-banana-2.1`)
- **Omni 1.2 Flash:** `beta.interactions.create` with `response_format={"type": "video", "resolution": "720p", "aspect_ratio": "16:9", "duration": "4s", "delivery": "inline"}` and `generation_config={"video_config": {"task": "image_to_video"}}`. `inter.output_video.data` is a **base64 `str`** (must `base64.b64decode`).
- **Nano Banana 2.1:** `client.models.generate_content(..., config=GenerateContentConfig(response_modalities=["IMAGE"]))` — `part.inline_data.data` is already raw bytes. In Interactions API, `image_size` strictly requires uppercase `"1K"` / `"2K"` / `"4K"`.

---

## 2. Remaining Backend & Agent Hardening Checklist

### Lane C (`server.py`, `pipeline/camera.py`, `pipeline/score.py`, `pipeline/route.py`)
- [x] `server.py`: approvals applied after `camera_zones` *(fixed in `4ae9a4a`)*
- [x] `pipeline/route.py`: derive `date` from `t[:10]` *(fixed in `4ae9a4a`)*
- [x] `server.py:pick_photo()`: skip 235 Gough, 880 5th, 500 Pierce, 1931 Evans, 340 6th *(fixed in `4ae9a4a`)*
- [ ] **P0 `server.py` Genie billing leak:** wrap `GENIE["session"]` start/stop in `LOCK` (prevent double-click orphan), stop session on stream disconnect / idle timeout, clamp `max_seconds <= 90`, and wait for worker exit before `save_mp4()`.
- [ ] **P1 `pipeline/camera.py` races:** add reset `generation` counter under `LOCK` so mid-run `Reset` can't be resurrected 15s later; use atomic `.tmp` + `os.replace()` for `camera_zones_<date>.json`; lock `INCIDENTS` reads.
- [ ] **P1 `pipeline/score.py`:** measure `zf["zones"]` unconditionally for `if_all_approved` (don't drop rejected zones) and exclude `camera_zones` from the `baseline` row.
- [ ] **P1 `pipeline/route.py`:** use `dict[str, set[str]]` for overlapping `cell_zone`, keep best candidate across Valhalla iterations, and populate `flood_cells` in OSRM fallback.

### Lane G (`gem/agent.py`, `gem/plan.py`, `gem/world.py`)
- [ ] **P0 `gem/agent.py`:** clamp `end` to `YYYY-MM-DDT23:59` (avoid midnight wrap), resolve `date_str` before `incident_t` (Nov 25 live mode safety), raise when `status == "failed"` or empty tool calls so Carbon fallback actually triggers, default `propose_zone` to `status: "approved"`, constrain cells within Chebyshev ≤ 2 of target, and tag `agent_engine` + `interaction_id` on output.
- [ ] **P1 `gem/world.py`:** check `d.mime_type` before assuming `else: self.audio += raw`, and allow `stop()` to wake/cancel `conn.receive()` during 5s warmup.
- [ ] **P1 `gem/plan.py`:** optionally add CPUC Q3 Waymo tract weighting (`1 + 1.0 * log1p(waymo_collisions_q3)`) for ~58.6% recall inside Waymo's operating footprint.
