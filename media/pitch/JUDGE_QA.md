# Judge Q&A Cheat Sheet & ROI Dossier

*(Every figure below is traced to `research/BUSINESS_CASE_AND_EXPANSION.md`, `research/COMPETITIVE_AND_INCIDENTS.md`, `media/backtest.json`, and our live done-checks in `TODO.md`.)*

---

## 1. The 15-Second ROI Proof (Napkin Math Judges Can Check)

- **Nov 18–19, 2026 SF Shutdown:** Record 2.64" atmospheric river stalled ≥5 Waymo robotaxis (Oak & Cole, Bayshore & Industrial) and forced a **23-hour Bay Area citywide shutdown** (~11 AM Nov 18 → ~10 AM Nov 19).
- **Lost Fares (1 Storm):** At **225,000 Bay Area trips/week** (`~1,339/hr`, CPUC/industry estimates) and **\$19.69–\$20.43 avg fare** (SQ / Obi), 23 hours offline = **30,804 missed trips = \$607K–\$629K** in lost gross fares (conservative floor: **\$518K**).
- **Vehicle Exposure:** 1 flooded Gen-5 Jaguar I-PACE (\$120K–\$200K equipped, 90 kWh HV battery water ingress = total loss) + 4 tow/recalibration stalls (\$5K–\$15K each) = **\$50K–\$190K+** per storm.
- **With Surgical 8% Dynamic ODD Pull-Back:** Keep **92% of SF open** (~85% net rides completed = **~26,183 rides preserved**), saving **\$566K–\$715K per Bay Area storm** → **< 1-storm payback**, **\$2.3M–\$2.9M/yr** in SF alone (4 atmospheric rivers/winter), and **\$6M–\$15M+/yr** across 10+ flood-prone US AV cities (**\$20M–\$50M+/yr** industry-wide).

---

## 2. Four Bulletproof Judge Q&A Answers

### Q1: "Why can't Waymo just plug into NWS flood alerts or Tomorrow.io?"
> *"They already tried. After Waymo's May 1, 2026 voluntary NHTSA recall of **3,791 vehicles (Campaign 26E-026)** following a San Antonio flood incident, Waymo tightened NWS weather integration. Nineteen days later—on May 20, 2026—a Waymo stalled at North & Argonne in Midtown Atlanta, and Waymo publicly stated the road flooded **before** the NWS issued any watch, warning, or advisory, triggering a **7-day Atlanta shutdown**. County-scale weather feeds lag hyperlocal urban drainage by 20–60 minutes."*

### Q2: "Why not install physical street flood sensors (FloodNet / Hohonu)?"
> *"FloodNet NYC is the world's largest municipal sensor network at ~400 ultrasonic posts, and commercial Hohonu gauges cost \$2,000–\$10,000 per site plus O&M. You cannot bolt hardware onto 100,000 intersections across SF, Austin, Phoenix, Atlanta, and Miami—when robotaxis are already rolling camera arrays driving those exact streets, and Decision 1 scores every frame in under a second with zero new hardware."*

### Q3: "How is this different from NVIDIA Cosmos or Applied Intuition?"
> *"Cosmos and Applied Intuition excel at offline R&D log replay after an incident is harvested and processed by a 3D team. They do not run live mid-ride ODD dispatch or turn a single real street photo into a steerable 720p flooded road in **4.8 seconds** via **Genie 4** so **Decision 1** can judge a simulated street before a car drives into it."*

### Q4: "Does this actually generalize beyond San Francisco?"
> *"Yes—every major 2026 AV market floods and publishes open 311/flood data: **SF** (DataSF `vw6y-z8j6`), **Austin** (Austin 311 + ATXfloods), **Miami** (Miami-Dade 311 + King Tides), **Phoenix** (myPHX311 + Maricopa FCDMC), **Atlanta** (ATL311), **San Antonio** (311 + SARA), **Houston**, **Dallas**, **LA**, **Las Vegas**, and **NYC** (NYC 311 + FloodNet). Zero hardware capex, day-one deployment in minutes."*

---

## 3. Verified Gemini 4 & Data Numbers (Never Improvise on Stage)

- **15-Storm Leave-One-Out Backtest (`media/backtest.json`):** `corridor` caught **44.8%** of flooded blocks at 8% of SF vs `baseline` **42.9%** (wins 13/15 storms, ties 2, loses 0; random floor **7.9%**).
- **Nov 18 Waymo Footprint (`data/waymo_sf.geojson`, CPUC Q3 2026):** 12 compact Carbon corridors caught **50.9%** of Nov 18 floods inside Waymo's 65 active tracts vs baseline **46.7%** (+4.2 pts) with **6.9h median lead time** (vs 5.5h) and 8.3x fewer zones.
- **Zero-False-Alarm Proof (Waymo Open Dataset, not redistributed):** Real SF rain freeway frames score **`proceed`** (`lane_covered=0.30`, `p_tire_or_worse=0.041`, **823 ms**); `gemini-4-hydrogen` agentic video review scores `0.05` (`first_water_s: null`).
- **Managed Agents (\$5k Prize):** `antigravity-preview-09-2026` runs both `run_incident` (3+ steps, **18.9 s**) and `run_ride` (5 steps ending in `decide`, **25.9 s**, real `interaction_id`, **0.47 s** trace replay fallback).
- **Genie 4 Pre-Warm & Cache:** Pre-warmed simulation waits **2.4 s** (`waited_s`); bad-key / offline fallback returns cached real Genie run in **0.44 s**.
