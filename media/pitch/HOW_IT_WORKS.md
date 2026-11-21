# How It Works

When a heavy rain forecast lands mid-ride, static maps cannot tell whether a flood-prone intersection ahead is passable. Our pipeline combines 72 prior storm days of real San Francisco 311 flood memory with five Gemini 4 capabilities.

First, flood memory flags high-risk blocks ahead—catching **44.8%** of flooded blocks at **8%** of the city across 15 held-out storms (random: **7.9%**). The moment a forecast spike arrives (**8.6 mm/h** at 09:00), **Genie 4** pre-warms a **simulated** street preview seeded from a real 311 resident photo 39 m away. **Decision 1** judges three simulated frames with a five-question safety rubric in under a second (`avoid`, 0.82 flooded, 91.3% agreement), while scoring real **Waymo Open Dataset** rain footage (not redistributed; Waymo does not use this) as `proceed` (0.23). **Gemini 4 Carbon** writes validated rider and fleet messages, **Valhalla** reroutes, and a **Managed Agent** logs an auditable tool trace.

| Model | Job | Measured Latency |
|---|---|---|
| **Genie 4** | Pre-warmed interactive **simulated** street preview from a real 311 photo (cached fallback in `media/sim_cache/`) | **2.4 s** pre-warmed wait (4.5 s first frame; **0.44 s** cache fallback) |
| **Decision 1** | 5-question safety rubric across 3 frames in parallel (`flooded`, `reaches_curb`, `sedan_stall`, `lane_visible`, `depth`) | **834 ms** (3-frame rubric; **500–700 ms** single frame) |
| **Gemini 4 Carbon** | Structured, fact-validated rider & fleet explanation (`explain_decision`) and pre-storm corridor planning (`propose_zones`) | **5.36 s** explanation (**145 ms** template fallback); **15.6–26.9 s** corridors |
| **Gemini 4 Hydrogen** | Offline video review (`MediaProcessing.AGENTIC`) locating first curb water on cached Genie clip (`0.98`, `0.0 s`) and Waymo rain clip (`0.05`) | **8.86 s** (offline clip review) |
| **Managed Agents** | End-to-end autonomous tool loop (`antigravity-preview-09-2026`) leaving a signed `interaction_id` audit trail | **19–23.6 s** (live 3-tool incident loop; **6.1 s** probe) |
