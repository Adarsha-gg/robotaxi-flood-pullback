# 60-Second Backup Capture Shot List

Record full-screen in dark mode with the server running locally (`http://localhost:8000`). Keep the cursor steady so captions stay readable. Every decision and zone runs **autonomously** with zero human-in-the-loop clicks.

| Shot | URL | What to Click | Seconds |
|---|---|---|---|
| **1. Departure & Pre-Trip** | `http://localhost:8000/ride` | Click **▶ Start ride**. Show route drawing from Stanyan & Fell to Chase Center (12.2 min, 8.12 km) and autonomous vehicle leaving at 09:00. | **8 s** |
| **2. Forecast & Flood Memory** | `http://localhost:8000/ride` | No click (auto-advances). Hold on Step 2 (**8.6 mm/h** at 09:00, 24.9 mm 6h) and Step 3 (**4th & King**, **17 past storms**, **44.8%** backtest footnote). | **10 s** |
| **3. Genie 4 Sim & Car Rubric** | `http://localhost:8000/ride` | No click. Hold on Step 4 side-by-side: real 311 photo (39 m away) vs **simulated** Genie 4 street, plus Decision 1 `CAR_QUESTIONS` bars (`avoid`, **0.80** lane flooded, **`p_tire=0.53`**, `ankle`). | **12 s** |
| **4. Autonomous Carbon & Agent Trail** | `http://localhost:8000/ride` | Let Step 5 green Valhalla reroute and autonomous **Gemini 4 Carbon** `decide()` (`reroute`, `0.91` confidence, 3 reasons, rider message) land, then click **Agent audit trail** drawer to reveal **Managed Agent** tool steps (`run_ride`, `estimate_fleet_detour`) and `interaction_id`. | **12 s** |
| **5. Real 311 Proof & ROI** | `http://localhost:8000/ride` | Close drawer (or scroll to Step 6). Hold on the final proof counter showing **34** real Nov 18 floods on the fastest route vs **16** on the autonomous reroute (\$566K–\$715K/storm saved). | **8 s** |
| **6. No-False-Alarm & Live CCTV Check** | `http://localhost:8000/cam` | Click **Real Waymo Camera** (Waymo Open Dataset rain frame; not redistributed; Waymo does not use this system), click **Judge frame** (`proceed`, **0.30**, **`p_tire=0.04`**, **823 ms**), and flash the 12-cam live SF Caltrans sweep (**2.03 s**, 0 false alarms). | **10 s** |

**Total duration:** 8 + 10 + 12 + 12 + 8 + 10 = **60 seconds**.
