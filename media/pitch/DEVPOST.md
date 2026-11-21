# Devpost Submission Draft

## Inspiration

During San Francisco's November 18, 2026 storm, residents filed 778 flood reports on 311—384 by 10:00 AM. Public CPUC Q3 filings show 48% of those floods (374 of 778) fell inside the 65 tracts where autonomous fleets operate, just 27% of the city, forcing a 23-hour citywide shutdown worth \$607K–\$629K in lost fares plus \$50K–\$190K+ in stalled-vehicle exposure. Surgical 8% dynamic ODD pull-back keeps 92% of SF open, saving **\$566K–\$715K per storm**. Static maps miss mid-ride standing water, and cameras see floods too late—so we built an autonomous look-ahead loop.

## What it does

**Flood Pull-Back** is an autonomous weather-aware routing system with zero human-in-the-loop gates; every model-created flood zone activates immediately. On a real November 18 ride from Stanyan & Fell to Chase Center (12.2 min, 8.12 km), a mid-ride forecast spikes to 8.6 mm/h at 09:00 (24.9 mm over 6 hours). Flood memory flags 4th & King (17 past storms). **Genie 4** generates a **simulated** street preview from a real photo 39 m away. **Decision 1** grades car clearance (`CAR_QUESTIONS`: `avoid`, `0.80`, `p_tire=0.53`). **Gemini 4 Carbon** `decide()` autonomously selects `reroute`, **Valhalla** detours (+0 min), and a **Managed Agent** audits fleet impact—cutting real Nov 18 route floods from 34 to 16.

## How we built it

We built a zero-leakage pipeline from 72 prior storm days of SF 311 data (excluding November 18) and Open-Meteo forecasts. Leave-one-storm-out backtesting across 15 storms proved corridor memory catches 44.8% of flooded blocks at 8% of SF (baseline 42.9%, random 7.9%). We pre-warmed **Genie 4** on forecast alerts (2.4 s wait, 0.44 s cache fallback), ran **Decision 1** `CAR_QUESTIONS` in parallel (823–977 ms) plus a **12-cam live SF Caltrans CCTV sweep in 2.03 s** (0 false alarms), added autonomous **Gemini 4 Carbon** `decide()` (5.88 s, 146 ms fallback), verified clips offline with **Gemini 4 Hydrogen** (8.86 s), and ran **Managed Agents** (`antigravity-preview-09-2026`) executing `run_ride` and `estimate_fleet_detour`.

## Challenges

Cold-starting Genie 4 took 4.5–4.9 seconds—too slow mid-ride. Pre-warming Genie 4 when the forecast alert fires cut wait time to 2.4 seconds, backed by a 0.44-second local cache fallback. Preventing false alarms on wet roads was equally vital. We upgraded Decision 1 to a car-clearance rubric (`CAR_QUESTIONS`: travel lane, tire/hub depth, hidden edges) and tested real rain footage from the **Waymo Open Dataset** (not redistributed; Waymo does not use this system). Dry streets scored `0.095` (`proceed`), Waymo rain scored `0.30` (`p_tire=0.04`, `proceed`, 823 ms), Hydrogen scored `0.05`, and 12 live Caltrans cams swept in 2.03 s with zero false alarms.

## What we learned

Each Gemini 4 model owns a distinct slice of an autonomous safety loop. **Decision 1** is sub-second (539–977 ms) for live vehicle rubrics and parallel CCTV sweeps (2.03 s across 12 cams). **Genie 4** turns static street photos into **simulated** flood look-aheads, while **Gemini 4 Hydrogen** excels at deep offline clip verification (`first_water_s: 0.0` in 8.86 s). Grounding **Gemini 4 Carbon** `decide()` with deterministic post-call validators—blocking unverified dates or rainfall—enables reliable autonomous `reroute` decisions without human bottlenecks. Running **Managed Agents** (`run_ride`, `estimate_fleet_detour`) in parallel yields a verifiable `interaction_id` audit trail without delaying routing.

## What's next

First, we will expand our autonomous 311 flood memory and live Caltrans-style CCTV sweeps to every major US AV market with open civic flood feeds—Austin, Miami, Phoenix, Atlanta, San Antonio, and NYC—where saving \$566K–\$715K per storm scales to \$6M–\$15M+/yr per fleet. Second, we plan to pair street memory with elevation and storm-drain telemetry so blocks without 311 history stay protected. Third, we will extend our leave-one-storm-out backtest to model historical forecast error alongside spatial recall. Finally, we will connect our **Gemini 3.8 Flash TTS** in-cabin rider and dispatch voice alerts directly to autonomous fleet telemetry streams and **Managed Agent** reopen hysteresis.
