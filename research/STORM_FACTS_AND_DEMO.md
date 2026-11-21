# Verified Nov 18, 2026 SF Storm Facts, 2:50 Demo Script & Judge Q&A

*(Compiled Nov 21, 2026 for Robotaxi Flood Pull-Back — Gemini 4 NYC Hackathon)*

---

## 1. Verified Real-World Facts & Timeline

- **Nov 17, 2026 (24 hours before storm):** California DMV restricted Waymo from operating on state freeways following construction-zone incidents — forcing **100% of Waymo SF routing onto surface arterials**.
- **Morning of Wed, Nov 18, 2026:** Powerful atmospheric river hit San Francisco:
  - **2.11 inches before noon** in Downtown SF — wettest pre-noon period in **76 years** (breaking 1950 record).
  - **2.28 inches by mid-afternoon** — breaking the **108-year** Nov 18 daily rainfall record (since 1918); >2.60" storm total.
  - **778 street-flooding reports** logged to SF 311 (`data.sf.gov/resource/vw6y-z8j6.json`), with **384 in the 10 AM hour alone** (559 between 10 AM–12 PM).
- **~11:00 AM PST, Nov 18 → ~10:00 AM PST, Nov 19 (~23-hour blackout):** After 5+ Waymo robotaxis stalled in standing water, Waymo paused commercial service across SF, Peninsula, and South Bay (*"We've paused for now due to weather"*). Waymo runs ~3,000 vehicles nationwide and ~315,000 paid CA trips/week.
- **Verified Waymo Stall & Flood Sites (Nov 18, 2026):**
  - **Oak St & Cole St** (Panhandle) — Waymo stalled in flooded crosswalk blocking shallowest lane.
  - **Fell St & Masonic Ave** (Panhandle / Haight) — Waymo stranded in deep water.
  - **Bayshore Blvd & Industrial St** (Bayview) — Waymo disabled in deep floodwaters.
  - **17th St & Folsom St** (Inner Mission), **13th St & Harrison St** (SoMa), **Lombard St & Gough St** (storm sinkhole).
- **Real CPUC & NHTSA Ground-Truth Data (`data/waymo_stats.json`, `data/waymo_sf.geojson`):**
  - CPUC Waymo 2026 Q3 filing (ended Sep 30, 2026 — strictly pre-Nov-18): 65 of 244 SF census tracts (27%) had Waymo collisions; **374 / 778 (48.1%) of Nov 18 floods** fell inside those 65 active Waymo tracts.
  - NHTSA SGO (Jun 2025–Oct 2026): **402 Waymo SF crash reports, 16 in rain**.
- **San Antonio Recall Context (Apr/May 2026 — 3,791 vehicles):**
  - On Apr 20, 2026, an unoccupied Waymo detected floodwater on the I-35 frontage road near Salado Creek, slowed down, then erroneously proceeded into the water and was swept away. Waymo filed a voluntary recall of 3,791 vehicles and pushed static flood-zone map patches — yet 6 months later still suffered a 23-hour SF citywide shutdown.
- **AV Fleet Ops Terminology (ISO 34503 / ISO 21448):**
  - **Dynamic ODD Envelope (ISO 34503)** vs binary citywide pause
  - **SOTIF (ISO 21448)** functional insufficiency (LiDAR specular multipath/absorption on standing water)
  - **Dynamic Exclusion Geofence Polygons** + **Crowdsourced HD-Map Hazard Delta** + **Clear-to-Reopen Hysteresis**

---

## 2. Hero Media & Demo Coordinates (Visually Verified)

### Real Nov 18 311 Photos (`media/frames/311/`)
- **Best Beat 1:35 Camera Site (VERIFIED real Waymo roof dome in floodwater + outside all forecast zones):**
  - **`691 2ND ST`** (`37.78082, -122.39070`, `r53_c68`, `09:49`, `media/frames/311/0949_cegfgqd2cp0yehms3cu4.jpg`) — pinned to the top of `/cam` with `★ Waymo`.
- **Best Genie 4 Street-Level WASD Driving Seeds:**
  - **`Broderick St & Haight St`** (`37.77103, -122.43869`, `r47_c42`, `09:18`, `0918_msmqrburzhh2pgyhjyok.jpg`) — clean eye-level Victorian street vanishing point (Panhandle).
  - **`199 Jones St`** (`37.78296, -122.41250`, `r55_c56`, `09:10`, `0910_nciaiilrrhxwuq9j77am.jpg`, `1152×867` landscape) — pouring rain, flooded yellow crosswalk, splashing van.
  - **`402 Ellis St`** (`37.78492, -122.41288`, `r56_c56`, `09:47`, `0947_ibtxkue2vtbinenlio7m.jpg`) — crisp wake across flooded downtown intersection.
  - **`1701 Divisadero St`** (`37.78543, -122.44023`, `r56_c41`, `10:00`, `1000_anpovtp9fkkeq77i1b40.jpg`) — clean wide SF arterial.
- **Filtered Out in `server.py:pick_photo()` (Non-street landmines):** `235 Gough` (shop window orange bike decal), `880 5th` (4th-floor balcony), `500 Pierce` (window bug screen), `1931 Evans` (construction gate), `340 6th` (indoor garage).

### Hero Demo Trip (Preset in `web/index.html`)
- **Stanyan & Fell (`[37.7715, -122.4545]`) → Moscone (`[37.7840, -122.4010]`):** Sweeps straight east down Fell/Oak/Market/SoMa through Panhandle + Civic Center + SoMa flood corridors (15–22 flood blocks), bends cleanly on Beat 0:45, then bends again when `691 2nd St` closes on Beat 1:35.

---

## 3. Word-for-Word 2:50 Demo Script

### Pre-Stage Setup (30s before timer)
- **Window A:** `http://localhost:8000` (Nov 18 Replay, clock `06:00`, Carbon zones `proposed`, `Waymo CPUC Q3 Activity` toggled ON).
- **Window B:** `http://localhost:8000/cam` (`W-112`, Location `691 2ND ST ★ Waymo`, `Live Webcam` with flood photo ready OR `Real 311 Photo` one-click fallback; click `Reset Camera Zones` beforehand).
- **Backup:** Pre-recorded Genie 4 MP4s in `media/renders/`.

### Beats
- **0:00 – 0:18 | Hook:** *"Three days ago, San Francisco broke a 108-year rainfall record—2.28 inches, 778 street-flooding 311 calls. Twenty-four hours earlier, the California DMV banned Waymo from freeways, forcing 100% surface-street routing. By 11 AM, after cars stalled at Oak & Cole, Fell & Masonic, and Bayshore, Waymo shut down the entire city for 23 hours. Even their San Antonio flood recall of 3,791 vehicles didn't fix it—because static flood maps can't keep up with a live storm. I'm the fleet ops manager, and right now it's Tuesday night."*
- **0:18 – 0:48 | Surface 1 (`gemini-4-carbon`):** Click the **Panhandle / Fell & Masonic** zone card, approve it, reject 1 edge zone, then click **Approve All**. *"Instead of shutting down a city of 315,000 weekly rides, Gemini 4 Carbon digests 33,000 strictly pre-storm 311 reports and Tuesday night's forecast to draft a Dynamic ODD—just 12 compact drainage corridors covering 8% of San Francisco. Look right here: Fell & Masonic—literally where a Waymo stalled Wednesday morning. Carbon cites exact historical storm days and a calibrated Decision 1 probability. As ops manager, I keep human-in-the-loop sign-off and publish live HD-Map Hazard Deltas."*
- **0:48 – 1:18 | Replay + Valhalla Reroute + Score Card:** Press **▶ Play** (or jump `09:00` → `10:00`), click **Stanyan & Fell → Moscone**, let clock cross **11:00 AM** so the Waymo pause toast fires. Point to the Carbon-vs-Baseline KPI bars and the amber vs cyan rain deck. *"Real 311 floods land—green dots are caught inside our approved zones. Valhalla reroutes our Stanyan & Fell to Moscone trip around flooded blocks for barely a minute of detour—no citywide pause. Look at the score card: Carbon matches a naive 100-blob baseline with nearly 10× fewer zones. And look at the rain chart: Tuesday's amber forecast knew the day, not the hour—it missed the 9-to-10 AM cloudburst in cyan. Pre-storm planning alone isn't enough."*
- **1:18 – 2:00 | Surfaces 2 & 3 (`gemini-decision-1` + `antigravity-preview-09-2026`):** Switch to **Window B** (`/cam`, `691 2ND ST ★ Waymo`), click **Send One Frame**. Decision 1 flashes `FLOODED` sub-second; Managed Agent executes `get_cell_history`, `get_forecast`, `propose_zone`. Switch back to **Window A**: cyan toast + pulsing cyan corridor + trip auto-reroutes. *"Every robotaxi becomes a flood sensor. Car W-112 hits an unzoned flooded intersection at 691 2nd St. Gemini Decision 1 flags standing water in under a second—0.85 to 0.92 on real Nov 18 floods vs 0.12 on dry asphalt—waking our Antigravity Managed Agent on `antigravity-preview-09-2026`. It inspects the 3×3 neighborhood flood history and updated rain curve, sizes a multi-block drainage closure, and broadcasts a Fleet Dispatch Notice. Back on the map, the corridor closes in pulsing cyan and active trips reroute automatically."*
- **2:00 – 2:28 | Surface 4 (`genie-4`):** Click **▶ Drive in Genie 4** on Panhandle (`Broderick & Haight`). Drive `W`/`A`/`D` for ~10 s using the live WASD HUD, then press `ESC`. *"When remote ops needs visual context before locking an ODD pullback, Genie 4—opened to developers two days ago—turns a single real Nov 18 resident photo into a live, 720p, 24fps WASD-steerable world with native stereo rain audio, transparently labeled as a visual simulation, not a depth measurement."*
- **2:28 – 2:50 | Surface 5 (Live Mode — Nov 25) + Close:** Click **Live · 11-25** in the top ops bar. *"This isn't just a post-mortem. Here is Live Mode for next Wednesday, November 25th—Thanksgiving Eve—with live forecast data and Carbon's proposed zones awaiting approval right now. Robotaxi Flood Pull-Back tells a fleet manager the night before which streets to close and when—and the first car that sees water closes the street for every other car."*

---

## 4. Managed Agents ($5k Prize) Positioning

- **Why not a static `if flooded: block_cell()` script?** Blocking 1 GPS cell leaves adjacent flooded cross-streets open; blocking a wide fixed radius kills dry hillsides. Our remote `antigravity-preview-09-2026` Managed Agent uses `previous_interaction_id` multi-turn tool calls (`get_cell_history`, `get_forecast`, `propose_zone`) to reason jointly over 3×3 neighborhood storm-day history, the updated rain taper, and Decision 1 depth severity—emitting an auditable tool trace, storm-day citations, and a one-line Fleet Dispatch Notice.

---

## 5. Top 8 Judge Questions — Concise Answers

1. **Data leakage?** Zero—all 33k 311 reports are strictly filtered to `date < 2026-11-18` before building `cells.json`, and Carbon only sees the night-before (`previous_day1`) forecast.
2. **Why not static SFPUC 100-year flood maps?** Waymo pushed static flood-map patches after the 3,791-vehicle San Antonio recall and still paused SF for 23 hours on Nov 18; static maps lack storm-specific rainfall thresholds, hourly windows, and live camera closure of clogged-drain flash floods.
3. **False positives from wet asphalt/puddles?** Decision 1 gives calibrated probabilities plus a separate `depth_score`, cleanly separating Nov 18 floods (`0.85–0.92`) from dry SF streets (`0.12–0.13`), gated at `≥ 0.80` (and 2-frame temporal confirmation in production).
4. **Genie 4 cost (`~$0.10/s`) in production?** Triggered only on-demand for remote ops ODD review or generating rare SOTIF edge-case simulations from a single incident photo, capped at 60 s (~$6 max) and transparently labeled as an illustration.
5. **Why Managed Agents vs a 20-line script?** Dynamic basin sizing (expanding only into historically flood-prone 3×3 neighbors), rain-decay duration scaling, and auditable fleet dispatch notices with full tool traces.
6. **Night-before forecast missed the 9–10 AM peak?** That's the core product insight: numerical weather models nail storm-day totals (`59.3 mm`) while missing the convective hour, so Carbon keys pre-storm ODD windows on 6h/daily totals while fleet cameras handle minute-level timing.
7. **Why cap zones at 8% of SF (~40% catch)?** Closing 40% of SF is a soft shutdown that ruins fleet ETA/availability; pre-closing the chronic 8% before dawn (12 corridors vs 100 baseline blobs) and catching the unpredictable tail via fleet cameras preserves citywide service.
8. **Does ~500 ms vision + ~19 s agent scale to 1,000 cars?** Onboard perception handles millisecond braking for car #1; Decision 1 triages rain-mode frames in ~250–500 ms; the Managed Agent runs once per newly flooded corridor (~19 s)—orders of magnitude faster than human ops taking 10–30 minutes before pausing SF at 11 AM.
