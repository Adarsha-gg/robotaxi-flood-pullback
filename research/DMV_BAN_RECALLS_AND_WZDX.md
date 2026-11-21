# Waymo 2026 Flood & Work-Zone Recalls, CA DMV Freeway Suspension & USDOT WZDx

> **Purpose:** Verified federal NHTSA recall IDs, exact Nov 2026 CA DMV freeway suspension facts, and USDOT WZDx / Caltrans LCS / SFMTA `8x25-yybr` schema mapping so every word on stage is 100% bulletproof.

---

## 1. Exact Verified 2026 Regulatory & Recall Timeline

| Date | Event / Official ID | Scope & Verified Trigger | Root Cause / Outcome |
|---|---|---|---|
| **May 6, 2026** | **NHTSA Recall `26E-026`** *(cross-ref `26V278000`)* | **3,791 vehicles** (5th- & 6th-gen Waymo ADS). Triggered Apr 20, 2026 in San Antonio, TX when an unoccupied Waymo entered an untraversable flooded 40 mph lane and stalled. | ADS detected standing water and slowed down, but failed to treat an untraversable flooded lane as a complete closure barrier. |
| **June 17, 2026** | **NHTSA Recall `26E-035`** | **3,871 vehicles** (5th-gen freeway ADS). Triggered by Phoenix ramp-closure entries (Apr 11 & 19) + **7 Waymo vehicles driving between cones into closed US-101 construction lanes in the Bay Area (May 18, 2026)**. | Verbatim Part 573 filing: *"inappropriately prioritizing the avoidance of other freeway hazards and/or failing to recognize the construction zone."* |
| **Nov 5–6, 2026** | **Post-Remedy Bay Area Freeway Incidents** | **Nov 5 (US-101 near Burlingame):** **3 driverless Waymos** entered an active construction closure occupied by workers & equipment. **Nov 6 (I-280 in SF):** Driverless Waymo attempted to maneuver past **CHP cruisers** conducting an active rolling traffic break. | Occurred *after* the June `26E-035` OTA software remedy. |
| **Nov 11 / 17, 2026** | **California DMV Driverless Freeway Suspension** *(effective Nov 11, announced Nov 17)* | Banned driverless testing and commercial service on **all California freeways** (DMV called it an *"imminent hazard to public safety"*). Waymo voluntarily paused commercial freeway rides **nationwide** (AZ, TX, FL, CA). | Forced **100% of SF commercial robotaxi trips onto surface streets** — 1–7 days before SF's worst street-flooding day on record (Nov 18). |

*(Accuracy note: NHTSA's Nov 6/9, 2026 action **`RQ26006`** covering 2,895 vehicles is an ODI Recall Query on the Dec 2025 school-bus recall `25E-084`, not the freeway incidents. Citing `26E-026` [floods], `26E-035` [work zones], and the Nov 11/17 CA DMV suspension [US-101 Burlingame + I-280 CHP] keeps every fact 100% airtight.)*

---

## 2. National Work-Zone Standards: USDOT WZDx + Caltrans LCS + SFMTA `8x25-yybr`

Our second-hazard layer (`pipeline/ride.py:closures()` reading DataSF `8x25-yybr`) is **not** a San Francisco one-off—it maps directly onto the federal **USDOT Work Zone Data Exchange (WZDx v4.2 → Connected Work Zones / CWZ)** standard already published by **20+ US state DOTs**:

- **USDOT WZDx Registry (`datahub.transportation.gov`):** Standardized GeoJSON `FeatureCollection` of `WorkZoneRoadEvent` objects (`road_names`, `start_date`, `end_date`, `beginning_cross_street`, `ending_cross_street`, `vehicle_impact` enum: `all-lanes-closed` / `some-lanes-closed` / `alternating-one-way`).
- **Caltrans LCS + CWWP2 (`cwwp2.dot.ca.gov`):** Live District 4 (Bay Area) highway lane closures refreshed every ~5 min; normalized into live WZDx GeoJSON via **MTC 511 (`api.511.org/traffic/wzdx`)**.
- **SFMTA Permitted Street Closures (`data.sfgov.org/resource/8x25-yybr.json`):** Maps 1-to-1 to WZDx (`shape` → GeoJSON geometry, `street`/`from_st`/`to_st` → `road_names`/cross streets, `start_dt`/`end_dt` → temporal bounds, `veh_imp` → `vehicle_impact`, `cnn` → deterministic street centerline edge ID).

---

## 3. Why "Floods + Permitted Lane Closures" Is a Compounding Trap for AVs

1. **Zero Escape Geometry:** A lane closure collapses a multi-lane arterial into a bottleneck; when an adjacent low-lying block floods simultaneously, lateral escape margins vanish.
2. **Competing-Hazard Prioritization Failure:** Waymo's own `26E-035` NHTSA filing documented that AVs cross into closed lanes when *avoiding another hazard simultaneously*—and `26E-026` proved standing water isn't reliably treated as a hard barrier. When rain glare + standing water + cones coincide, steering around one pushes the car into the other.
3. **Upstream Routing Prevents Bottleneck Stalls:** Blocking compounded flood + closure corridors *before dispatch* keeps robotaxis out of single-lane traps where a single stall blocks emergency vehicles and triggers fleet-swarming deadlocks.

---

## 4. Stage-Ready Soundbites (Zero Overclaiming)

- *"Waymo already filed two NHTSA recalls this year for our exact two hazards—`26E-026` for driving into a flooded road and `26E-035` for driving into closed freeway construction zones—and on November 11, after three more cars entered a US-101 work zone near Burlingame and one tried to pass a CHP traffic break on I-280, the California DMV suspended driverless freeways statewide."*
- *"Our SFMTA lane-closure layer uses the exact same GeoJSON impact schema standardized across 20+ US states by USDOT's WZDx spec and Caltrans LCS—turning free public municipal data into an upstream safety layer before the car's sensors ever see the cones."*
