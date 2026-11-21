# How It Works

When heavy rain spikes mid-ride, static maps miss standing water ahead. Our fully autonomous pipeline—zero human gates—pairs 72 prior storm days of SF 311 flood memory with five Gemini 4 capabilities, keeping 92% of the city open and saving \$566K–\$715K per storm.

Flood memory flags high-risk blocks—catching **44.8%** of flooded blocks at **8%** of SF across 15 held-out storms (random: **7.9%**); model-created corridors activate immediately. On a forecast spike (**8.6 mm/h**), **Genie 4** pre-warms a **simulated** street preview from a real 311 photo 39 m away. **Decision 1** scores car clearance (`CAR_QUESTIONS`: `avoid`, `0.80`, `p_tire=0.53`; dry `0.095`; **Waymo Open Dataset** rain `0.30` / `p_tire=0.04` `proceed`—not redistributed, Waymo does not use this) and sweeps 12 live Caltrans cams in **2.03 s** (0 false alarms). **Gemini 4 Carbon** `decide()` autonomously reroutes while a **Managed Agent** audits fleet detour impact.

| Model | Job | Measured Latency |
|---|---|---|
| **Genie 4** | Pre-warmed interactive **simulated** street preview from a real 311 photo (cached fallback in `media/sim_cache/`) | **2.4 s** pre-warmed wait (4.5 s first frame; **0.44 s** cache fallback) |
| **Decision 1** | Car-focused `CAR_QUESTIONS` rubric (lane covered, tire/hub depth, hidden edges) + parallel 12-cam SF Caltrans CCTV sweep | **823–977 ms** rubric (**2.03 s** for 12 live SF Caltrans cams, 0 false alarms) |
| **Gemini 4 Carbon** | Autonomous `decide()` (`reroute` vs `keep_route`, `0.91` confidence, fact-validated rider message) + active-immediately pre-storm corridors | **5.88 s** decision (**146 ms** template fallback); **15.6–26.9 s** corridors |
| **Gemini 4 Hydrogen** | Offline video review (`MediaProcessing.AGENTIC`) locating first curb water on cached Genie clip (`0.98`, `0.0 s`) and Waymo rain clip (`0.05`) | **8.86 s** (offline clip review) |
| **Managed Agents** | End-to-end autonomous tool loop (`antigravity-preview-09-2026`) running `run_ride` and `estimate_fleet_detour` with signed `interaction_id` audit trail | **18.9–25.9 s** live multi-tool loop (**0.47 s** trace replay fallback) |
