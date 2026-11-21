# Devpost Submission Draft

## Inspiration

During San Francisco's November 18, 2026 storm, residents filed 778 flood reports on 311—384 by 10:00 AM. Public CPUC Q3 filings show 48% of those floods (374 of 778) fell inside the 65 tracts where autonomous vehicles operate, representing just 27% of the city. Public NHTSA reports also log 16 rain-related autonomous crashes in San Francisco between June 2025 and October 2026. Static maps do not show standing water forming mid-ride, and cameras only see a flood once the car arrives. We wanted to test whether world simulation and sub-second vision can help a vehicle pull back before reaching flooded streets.

## What it does

We built **Flood Pull-Back**, a live replay and operations console for weather-aware autonomous routing. On a real November 18 ride from Stanyan & Fell to Chase Center (12.2 min, 8.12 km), a mid-ride forecast spikes to 8.6 mm/h at 09:00 (24.9 mm over 6 hours). Flood memory flags 4th & King (17 past storms). **Genie 4** generates a **simulated** street preview from a real resident photo 39 m away. **Decision 1** grades three simulated frames (`avoid`, 0.82 flooded, ankle-deep, 91.3% agreement) in 834 ms. **Gemini 4 Carbon** explains the choice, **Valhalla** reroutes (+0 min), and a **Managed Agent** logs the audit trail—cutting real Nov 18 floods on the route from 34 to 16.

## How we built it

We built a strict zero-leakage pipeline using 72 prior storm days of SF 311 data (excluding November 18) and Open-Meteo forecasts. Leave-one-storm-out backtesting across 15 past storms confirmed our corridor memory catches 44.8% of flooded blocks at 8% of the city (baseline 42.9%, random 7.9%). We pre-warmed **Genie 4** on the forecast alert (2.4 s wait, 0.44 s cache fallback), ran **Decision 1** across 3 frames in parallel threads (834 ms), added **Gemini 4 Carbon** structured explanations (5.36 s, 145 ms template fallback) with strict date/rainfall validation, verified clips offline with **Gemini 4 Hydrogen** (8.86 s), and ran **Managed Agents** (`antigravity-preview-09-2026`) beside the live path.

## Challenges

Latency and stage reliability were our biggest hurdles. Cold-starting Genie 4 took 4.5–4.9 seconds, too slow for a live mid-ride check. Pre-warming Genie 4 when the forecast alert fires cut perceived wait to 2.4 seconds, backed by a 0.44-second local cache fallback. Preventing false alarms on wet roads was equally critical. We tested Decision 1 on real rain footage from the **Waymo Open Dataset** (not redistributed; Waymo does not use this system). On wet freeway frames, Decision 1 returned `proceed` (0.23, 94.8% agreement) and offline Hydrogen scored 0.05—proving our rubric separates standing water from wet pavement.

## What we learned

Different Gemini 4 models excel at distinct slices of a real-time safety loop. **Decision 1** is fast enough (500–834 ms) to sit directly inside a vehicle decision loop and evaluate multi-question rubrics cleanly. **Genie 4** unlocks proactive look-ahead by turning static street photos into **simulated** weather previews, while **Gemini 4 Hydrogen** excels at deeper offline video verification (`first_water_s: 0.0` in 8.86 s). Grounding **Gemini 4 Carbon** with post-call validators—rejecting unverified storm dates or rainfall numbers—eliminated hallucinations. Finally, running **Managed Agents** alongside the fast path gives operators a verifiable `interaction_id` audit trail without blocking routing.

## What's next

First, we want to wire live municipal camera feeds (such as Caltrans District 4) and National Weather Service alerts alongside our Live Mode (already tested on November 25 with Carbon corridors covering 2.9% of SF). Second, we plan to pair spatial flood memory with elevation and storm-drain telemetry so blocks without 311 history are still protected. Third, we want to expand our leave-one-storm-out backtest to include historical forecast errors, not just spatial memory. Finally, we aim to stream **Managed Agent** audit traces directly into fleet dispatch consoles with human-in-the-loop override controls.
