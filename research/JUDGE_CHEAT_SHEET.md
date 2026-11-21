# Robotaxi Flood Pull-Back — 1-Page Judge Cheat Sheet & Winning Positioning Guide

> **Core Thesis:** Replace binary citywide robotaxi shutdowns with an **autonomous Dynamic ODD (ISO 34503)** loop powered by all 5 Gemini 4 surfaces: **pre-storm flood memory + mid-ride Genie 4 counterfactual preview + sub-second calibrated Decision 1 gating + fleet-camera Managed Agent closure.**

---

## 1. The 15-Second Hook

> *"Three days ago, a record **2.64-inch** San Francisco atmospheric river stalled 5+ robotaxis and triggered a **23-hour Bay Area shutdown** costing **$607K–$629K in lost fares** (plus **$50K–$190K+** in vehicle risk)—just months after a Midtown Atlanta robotaxi stalled **before the NWS issued any warning**, shutting the city down for 7 days. Our system watches a live ride as a mid-ride cloudburst hits: it pairs 72 past storms of SF 311 flood memory with a **Genie 4** simulated street preview, scores passability with **Decision 1** in under a second, reroutes autonomously via **Carbon + Valhalla** before the car hits standing water, and closes unzoned streets fleet-wide via **Antigravity Managed Agents**—preserving **92% of the city** and **$566K–$715K per storm** (<1-storm payback)."*

---

## 2. Why Each of the 5 Gemini 4 Surfaces Is Irreplaceable Here

| Gemini 4 Surface | Role & Verified Latency | Why a Generic LLM / VLM Cannot Substitute |
|---|---|---|
| **1. `genie-4`** *(World Model)* | Pre-warmed 720p 24fps **simulated** street preview from 1 real 311 photo (**2.4 s** wait; **0.44 s** cache fallback) + mid-stream weather steering | A static VLM cannot synthesize an action-conditioned, perspective-consistent 3D street rollout under an unseen `8.6 mm/h` rain state in seconds from a single flat photo so downstream vision can preview hazards *before* a car arrives. |
| **2. `gemini-decision-1`** *(Calibrated Decision)* | Parallel 3-frame CAR-flooded rubric (`lane_covered`, `car_depth` vs tire/hub, `edges_hidden`) in **539–977 ms**; 12 live Caltrans cams in **2.03 s** | Generic VLMs emit uncalibrated prose/JSON scores that cry wolf on shiny wet asphalt and lag 3–6 s; Decision 1 outputs native calibrated `noul`/`score` probabilities separating real floods (`0.80–0.92`) from real Waymo SF rain (`0.22–0.30`, `p_tire=0.04`) in <1 s. |
| **3. `gemini-4-carbon`** *(Frontier Reasoning)* | Autonomous structured `decide()` (**5.36–5.88 s**; **145 ms** template fallback) + pre-storm 12-corridor Dynamic ODD planning (**15.6–26.9 s**) | Synthesizes 72 storms of drainage clusters + forecast trajectories + rubric outputs into grounded, citation-validated autonomous dispatch decisions and calm rider messages. |
| **4. `gemini-4-hydrogen`** *(Agentic Video + Agent Backbone)* | Offline temporal video audit (`MediaProcessing.AGENTIC`, **8.86 s**) locating exact `first_water_s` + backbone model for Antigravity loops | Frame-by-frame polling misses temporal onset and splash dynamics; Hydrogen scans full clips agentically—scoring real Waymo SF rain at **`0.05` (`first_water_s: null`)** and flooded Genie video at **`0.98` (`0.0 s`)** as an independent second-opinion critic. |
| **5. `antigravity-preview-09-2026`** *(Managed Agents — $5k Track)* | Remote stateful multi-turn incident & ride loops (**19–25.9 s**, `previous_interaction_id`, **0.47 s** trace replay) with Valhalla detour + reopen hysteresis | A brittle `if flooded: block_cell()` script either under-blocks one 165 m cell or nukes dry arterials; Managed Agents orchestrate remote multi-tool state (`3×3` basin memory + forecast + live Valhalla detour cost `+1.19 min`) and leave a regulator-auditable `interaction_id` trace. |

---

## 3. DeepMind Judge Trap-Avoidance Checklist

| Trap Judges Penalize | How Our Architecture Nails It Cleanly |
|---|---|
| **1. Confusing Simulation with Physical Reality** | Every UI badge, prompt, and `gem/explain.py` validator enforces **`"simulated"`** (never `"observed"`). Genie 4 is strictly a forecast-conditioned counterfactual preview & SOTIF stress-test; real Caltrans/fleet cameras provide physical ground truth. |
| **2. Test-Set / Hindsight Data Leakage** | Strict temporal firewall: `cells.json` cuts off at **`date < 2026-11-18`** (72 prior storms); pre-storm plan uses **`previous_day1`** forecast (which *missed* 9–10 AM); Waymo weighting uses **CPUC 2026 Q3** (ended Sep 30); backtest is **strict leave-one-storm-out** across 15 storms. |
| **3. Uncalibrated "Crying Wolf" Probabilities** | Calibrated CAR-flooded rubric + real-rain negative control: dry SF (`0.095`), real Waymo SF rain (`0.22–0.30`, `p_tire=0.04` → `proceed`), and 12 live Caltrans cams (`0` false alarms in `2.03 s`) vs real Nov 18 floods (`0.85–0.92`, `p_tire=0.97` → `avoid`). |
| **4. "Wrapper Agent" Theater** | Native stateful `antigravity-preview-09-2026` chaining 4–5 real tools (`get_cell_history`, `get_forecast`, `estimate_fleet_detour`, `simulate_street`, `propose_zone`/`decide`) with hard Python bounds (Chebyshev ≤ 2, `23:59` clamp, `avoid_cells ⊆ risky`, 2-frame reopen hysteresis) and signed `interaction_id`. |
| **5. Unverified LLM Hallucinations** | Programmatic post-call validator (`gem/explain.py`) checks every `YYYY-MM-DD`, every `mm` number, and `"simulated"` against real inputs; retries once, then falls back cleanly in `145 ms`. |
| **6. Fragile Stage Demo / Silent Faking** | Explicitly labeled fallbacks on every surface: `cached Genie run` (`0.44 s`), `template` (`145 ms`), `replayed` agent trace (`0.47 s`). Never fakes live execution; never raises on stage. |
| **7. Licensing / Attribution Sloppiness** | Clearly states rain footage is from the **Waymo Open Dataset** (git-ignored, not redistributed), tract data from public CPUC Q3 / NHTSA SGO filings, and **does not claim Waymo uses this system**. |

---

## 4. Best 1-Liners for Live Q&A

- **Flood memory predictive?** *"Across a strict leave-one-storm-out backtest of **15 past SF storms**, pre-storm corridor memory caught **44.8%** of flooded blocks at **8%** of the city—beating baseline (**42.9%**, winning 13/15, losing 0) and crushing random (**7.9%**) by **5.7×**; inside Waymo's 65 CPUC Q3 tracts on Nov 18, Carbon caught **50.9%** with **6.9 h** median lead."*
- **False alarms on shiny wet asphalt?** *"We tested real SF rain footage from the **Waymo Open Dataset**: **Decision 1** scored **`0.22–0.30` (`p_tire=0.04`, `proceed`)** in `<1 s`, **Hydrogen** scored the full clip **`0.05` (`first_water_s: null`)**, and a live sweep of **12 SF Caltrans cameras** returned **0 false alarms in 2.03 s**."*
- **What about unmapped clogged drains?** *"Look at **`691 2nd St`**—a real Nov 18 311 photo showing a Waymo roof dome in standing water outside every pre-storm zone. Car #1's camera hits **Decision 1** in ~600 ms, triggers **Antigravity Managed Agents**, which checks 3×3 history + Valhalla detour cost (`+1.19 min`) and closes that corridor fleet-wide before car #2 arrives."*
- **Why trust Genie 4 in safety ops?** *"We never treat Genie 4 as a physical depth sensor—it's labeled **simulated** and used strictly as a counterfactual preview to decide whether to take a `+0.5 min` preventive detour, and offline as a 5-second SOTIF scenario generator vs weeks of 3D prep."*
- **Business ROI & scale?** *"Keeping **92%** of SF open during one Nov 18-scale 23h storm preserves **~26,183 rides** and **$566K–$715K/storm** (<1-storm payback; **$6M–$15M+/yr** across 10+ US AV cities), and every major AV metro already publishes free open 311 flood data."*
