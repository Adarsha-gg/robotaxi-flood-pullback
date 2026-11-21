# High-Jaw-Drop Optimistic Upgrades (Ranked by Judge Wow × Feasibility)

> Audited directly against `gem/world.py`, `gem/agent.py`, `gem/vision.py`, `server.py`, `pipeline/ride.py`, `pipeline/camera.py`, `data/sf_cameras.json`, `web/index.html`, and `web/ride.html`. None of these duplicate Wave 3 (`G7–G13`) — they stack cleanly on top.

## Two Hidden Goldmines Already in the Repo & SDK
1. **`google.genai` already supports Genie 4 mid-stream text steering in 5 lines:** `_serialize_client_payload(str)` natively converts a plain `str` in `conn.send(msg)` to `{"event_type": "input", "content": [{"type": "text", "text": msg}]}` — zero changes to `_send_loop` in `gem/world.py`!
2. **`data/sf_cameras.json` is ALREADY on disk with 33 live in-service SF Caltrans CCTV cameras** (I-80 6th St, I-280 6th St Offramp, US-101, Presidio Tunnel, Fremont St) — ready for a ~1.2 s parallel Decision 1 sweep!

---

## Ranking Matrix

| Rank | Upgrade | Wow | Feas | Score | Time | Risk | Files |
|---:|---|---:|---:|---:|---|---|---|
| **1** | **Genie 4 Mid-Stream Weather Steering + Live Decision 1 Telemetry HUD** | 10 | 9.5 | **95.0** | 20–25m | Low | `gem/world.py`, `server.py`, `web/index.html` |
| **2** | **Managed Agent Fleet-Detour Optimizer (`estimate_fleet_detour`) + Live Step Streaming** | 10 | 9.0 | **90.0** | 30–35m | Low-Med | `gem/agent.py`, `pipeline/camera.py`, `web/cam.html` |
| **3** | **Live 12-Cam SF Caltrans CCTV Parallel Decision 1 Sweep** | 9.5 | 9.0 | **85.5** | 25–30m | Low | `pipeline/cctv.py`, `server.py`, `web/index.html` |
| **4** | **Dual-Car "Ghost Static-Map Waymo vs W-112" Race + Live Fleet Continuity Counter** | 9.0 | 9.5 | **85.5** | 20–25m | Ultra-Low | `web/ride.html`, `web/index.html` |
| **5** | **Closed-Loop "Clear-to-Reopen" Hysteresis via Managed Agent** | 9.0 | 8.5 | **76.5** | 30–35m | Low | `gem/agent.py`, `pipeline/camera.py`, `web/cam.html`, `web/index.html` |
| **6** | **Mission-Control Audio & Voice Fleet Dispatch Alerts** | 8.0 | 9.5 | **76.0** | 15m | Ultra-Low | `web/index.html`, `web/ride.html`, `web/cam.html` |
| **7** | **Hydrology Grounding Pack (SFPUC 100-Yr Basin + USGS 1m Sink + NWS Alerts)** | 8.5 | 7.5 | **63.8** | 35–40m | Medium | `pipeline/terrain.py`, `gem/agent.py`, `web/index.html` |
| **8** | **Multi-City Portability Adapter (SF → Austin / Miami / San Antonio)** | 7.5 | 7.0 | **52.5** | 35–45m | Medium | `pipeline/cities.py`, `server.py`, `web/index.html` |

---

## Top 4 Concrete Blueprints (Highest ROI Before 7 PM Freeze)

### #1. Genie 4 Mid-Stream Weather Steering + Live Decision 1 Telemetry HUD (20–25 min)
- **Stage beat:** While driving a real SF street in 720p 24fps Genie 4 with WASD, click **`🌊 Escalate: Ankle-Deep Storm Surge`** → water rises live via mid-stream text injection while a floating **Decision 1 HUD** scores live frames every 2.5 s and spikes from `38% WET · PROCEED` → `91% IMPASSABLE · AVOID` in real time.
- **How:**
  1. `gem/world.py`: add 5-line `GenieSession.send_text(self, text: str)` pushing `clean` onto `self._queue` (wrap `conn.send` in `try/except` so the video stream never drops).
  2. `server.py`: add `POST /api/genie/prompt` (`s.send_text`) and `POST /api/genie/judge` (judges `s.frame` via `ride.judge_car` / `vision.judge_frame`).
  3. `web/index.html`: add 4 weather injector pills inside `#genie` (`🌧 Heavy Downpour`, `🌊 Ankle-Deep Rising Water`, `🌙 Night + Headlight Glare`, `☀️ Draining`) + floating live Decision 1 HUD badge with `⚡ Auto-Judge` toggle.

### #2. Managed Agent `estimate_fleet_detour` + Live Step Streaming (30–35 min — $5k Prize Killer)
- **Stage beat:** Remote `antigravity-preview-09-2026` Managed Agent proposes a 5-cell closure, calls `estimate_fleet_detour(cells)` against Valhalla mid-reasoning, sees `+4.8 min` arterial impact, **self-corrects to a tight 3-cell drainage basin (`+1.1 min`)**, and only then commits `propose_zone` — with every tool call streaming live into `/cam` via `on_step` (already supported in `gem/agent.py`!).
- **How:** Wire `on_step` in `pipeline/camera.py` (3 lines!) + add `estimate_fleet_detour` tool (4s timeout + arterial fallback) in `gem/agent.py` + render streamed steps & `thought_summary` + `interaction_id` in `web/cam.html`.

### #3. Live 12-Cam SF Caltrans CCTV Parallel Decision 1 Sweep (25–30 min)
- **Stage beat:** Click **`📡 Sweep 12 Live SF Cams`** in Live Mode → `ThreadPoolExecutor(12)` fetches 12 live Caltrans SF road JPEGs from `data/sf_cameras.json` (already on disk!) and runs Decision 1 across all 12 in **~1.2 s** → 12 glowing pins appear on SF with click-to-inspect live camera feeds (`"12/12 SF corridors scanned in 1.1s · 0 false alarms"`).

### #4. Dual-Car "Ghost Static-Map Waymo vs W-112" Race + Continuity Counter (20–25 min — Zero API Risk)
- **Stage beat:** On `/ride`, launch a red **Ghost Car ("Static-Map Robotaxi")** along `P.fast` at the same `08:58` departure as cyan W-112. Watch the Ghost Car hit the first real Nov 18 311 flood point and freeze with **`⚠ STRANDED IN FLOODWATER`** while W-112 pulls into Caltrain dry. On `/`, show a live **"92.0% SF Open vs 0% Waymo Pause"** continuity meter + CPUC-modeled rides preserved counter.
