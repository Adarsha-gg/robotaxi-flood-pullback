# Business Case, Multi-City Expansion & ROI Dossier: Robotaxi Flood Pull-Back

> **Bottom Line Up Front:** On **November 18–19, 2026**, a record-breaking San Francisco atmospheric river (2.64" rain, breaking a 1918 record) stalled ≥5 Waymo robotaxis and forced a **23-hour Bay Area citywide shutdown** (~11:00 AM PST Nov 18 → ~10:00 AM PST Nov 19). That single blunt kill-switch cost an estimated **$607K–$629K in lost gross fares** (conservative floor: **$518K**, before rain-surge demand) plus **$50K–$190K+ in stalled-vehicle recovery and EV write-off exposure**. By replacing a 100% citywide kill-switch with a **surgical ~8% Dynamic ODD Flood Pull-Back + Fleet-as-Sensor + Genie 4 SOTIF Flywheel**, an operator preserves **$566K–$715K per storm** in the Bay Area alone—achieving **<1-storm payback** and **$6M–$15M+/year** across Waymo's 10+ flood-prone U.S. markets (**$20M–$50M+/year** industry-wide).

---

## 1. Waymo & Robotaxi Unit Economics (2025–2026 Verified Data)

### A. Demand & Revenue Scale (CPUC Filings & Market Trackers)
- **California Paid Trips (CPUC 2025–2026):** Scaled from ~122K weekly CA trips in late 2024 to >300K/week in late 2025, reaching **315,000–360,000 weekly paid trips in California** by mid-2026 (*CPUC filings / Road to Autonomy / EE Times*).
- **SF Bay Area Share:** Historically **70%–75%** of CA rides (*The Driverless Digest*); using a conservative **65%–70%** share yields **210,000–250,000 weekly paid trips** in the SF Bay Area (base anchor: **225,000 trips/week**, or **~1,339 trips/hour**).
- **National Fleet Scale (2026):** **450,000–500,000+ weekly paid rides** across **~3,000 active commercial robotaxis** nationally; dense SF utilization averages **20–24 trips/vehicle/day** (*SQ Magazine*).
- **Average SF Waymo Fare:**
  - **Obi Rideshare Aggregator Study** (*Bloomberg / TechCrunch / The Rideshare Guy*): **$20.43/ride** average in SF (vs. $15.58 UberX, $14.44 Lyft Standard).
  - **SQ Magazine Bay Area Analysis:** **$19.69/ride** Bay Area average (*Sacra* estimates $15–$17 globally).

### B. Cost of the Nov 18–19, 2026 Bay Area 23-Hour Shutdown (`23 / 168 = 13.69%` of a week)
- **Conservative Floor ($18 fare, 210K/wk):** `28,750 trips × $18.00` = **$517,500**
- **Base Case ($19.69 SQ Bay Area, 225K/wk):** `30,804 trips × $19.69` = **$606,531**
- **Obi SF Benchmark ($20.43, 225K/wk):** `30,804 trips × $20.43` = **$629,326**
- **Rain-Demand Adjusted (+25% storm lift):** **$786,657**
- **Annual Bay Area Exposure:** NOAA / CW3E Scripps data show NorCal averages **4–6 atmospheric river storms/winter** driving **>90% of California flood damages** → 3–5 shutdown-grade storms/yr puts **$1.8M–$3.1M/yr** in Bay Area fares at risk.

### C. Cost of a Single Flooded / Stalled Robotaxi
| Cost Component | Gen-5 Jaguar I-PACE (SF Backbone) | Gen-6 Zeekr ("Ojai") / Ioniq 5 (2026+) | Notes |
| :--- | :--- | :--- | :--- |
| **Total Equipped Vehicle Cost** | **$120,000–$200,000** (Mid: **$150,000**) | **$50,000–$75,000** (Mid: **$65,000**) | Base EV + LiDAR/camera/radar/compute suite |
| **EV High-Voltage Battery Risk** | 90 kWh pack: **$15K–$25K** part / **$30K–$40K+** installed | Comparable HV pack economics | Water ingress → delayed thermal runaway → **automatic total loss** |
| **Non-Totaled Stall Recovery** | **$5,000–$15,000 / stall** (Mid: **$10,000**) | **$5,000–$12,000 / stall** | Flatbed EV tow + 50-ft quarantine yard + HV diagnostics + sensor recalibration + 3–5 days downtime (~$400–$480/day) |

- **Nov 18 SF Fleet Exposure (≥5 Stalled Vehicles):** **$50K** best case (5 recoverable stalls) to **$190K+** realistic case (1 water-ingressed I-PACE total loss + 4 stalls).

---

## 2. Multi-City Expansion: Every Major 2026 AV Market Floods & Has Open 311 Data

| Metro Market | 2026 AV Operators | Primary Urban Flood Hazard | Open 311 / Real-Time Flood Data Feed |
| :--- | :--- | :--- | :--- |
| **San Francisco** | Waymo, Zoox | Atmospheric rivers (4–6/winter) + king tides | **DataSF** `311 Cases` (`vw6y-z8j6`) |
| **Los Angeles** | Waymo, Zoox (testing) | Atmospheric rivers, underpass flash floods | **Data LA** `MyLA311` (LASAN Storm Drain / Flooding) |
| **Phoenix** | Waymo | Monsoon flash floods across desert washes | **myPHX311** + **Maricopa FCDMC** flood gauges/GIS |
| **Austin** | Waymo, Tesla, Zoox | "Flash Flood Alley" (30–70+ low-water closures/storm) | **Austin 311** (`i26j-ai4z`) + **ATXfloods** (>100 gauges) |
| **Miami** | Waymo, Tesla, Zoox | Tropical storms + NOAA King Tides ("sunny-day" flooding) | **Miami-Dade 311** (DERM drainage/flooding) |
| **Houston** | Waymo, Tesla, Zoox | Flat coastal terrain, bayou surges, Gulf cloudbursts | **Houston 311** + Houston Water Flood Hazards GIS |
| **Dallas** | Waymo, Tesla, Zoox | North Texas convective flash floods | **Dallas ArcGIS Hub** — *"Flood Plain Map with Flood Calls"* |
| **San Antonio** | Waymo (May 2026 recall site!) | Flash Flood Alley low-water crossings | **San Antonio 311** + SARA ponding GIS |
| **Atlanta** | Waymo (Uber), Zoox | Rapid convective cloudbursts (flooded before NWS warned!) | **ATL311** + Watershed Management catch-basin GIS |
| **Las Vegas** | Zoox | Desert flash floods into washes & Strip underpasses | **Clark County CCRFCD** OpenWeb GIS |
| **New York City** | Waymo (testing) | Extreme cloudbursts, combined-sewer backups | **NYC 311** + **NYC FloodNet** (400+ ultrasonic sensors) |

---

## 3. Insurance, Regulatory & SOTIF Data-Flywheel Value

- **Regulatory Permit Protection:** Auditable, timestamped Dynamic ODD pull-back logs (311 + forecast + Decision 1 + Managed Agent trace) give CPUC, CA DMV, SFMTA, and NHTSA SGO verifiable weather-governance proof.
- **Fleet Insurance Economics (Waymo + Swiss Re, 25.3M miles):** Routine liability claims dropped **88% property / 92% bodily injury** vs human drivers — making **correlated weather catastrophe ("cat") events** (flooding dozens of $65K–$150K EVs in one storm) the #1 insurable physical-damage tail risk.
- **ISO 21448 (SOTIF) & Genie 4 Flywheel:** RAND (*Driving to Safety*, 2016) proved physical testing needs **11 billion miles (518 years for a 100-car fleet)**; the real simulation bottleneck is authoring long-tail 3D scenarios. **Genie 4** collapses scenario creation from weeks of 3D prep to **5 seconds from a single real incident photo**.

---

## 4. Concrete ROI Summary Table (Judge-Verifiable Napkin Math)

*Assumptions: 225K Bay Area trips/wk, 23h Nov 18 pause (30,804 trips), $19.69 SQ Bay Area fare (no rain surge), 8% Dynamic ODD footprint → 92% SF open → conservative 85% net trips completed, 4 storms/winter.*

| Metric | Status Quo: Static Maps + 23h Kill-Switch | Robotaxi Flood Pull-Back: 8% Dynamic ODD + Fleet-as-Sensor | Net Advantage |
| :--- | :--- | :--- | :--- |
| **City Available During Storm** | **0%** (23h citywide blackout) | **~92%** (8% flooded corridors excluded) | **+92% uptime footprint** |
| **Trips Completed (23h Storm)** | `0` | `~26,183 trips` (`85% × 30,804`) | **+26,183 rides served** |
| **Gross Fare Revenue (1 SF Storm)** | `$0` (−$607K to −$629K lost) | **`+$516K–$535K`** | **+$516K–$535K / storm** |
| **Stalled / Flooded Vehicle Exposure** | **$50K–$190K** (5 stalls / 1 total loss) | **~$0–$10K** (pre-emptive reroute) | **+$50K–$180K / storm** |
| **Total Direct Value / SF Storm** | **−$657K to −$819K** | ~$91K foregone in 8% flood zones | **+$566K–$715K saved / storm** |
| **Annual SF Bay Area (4 storms/yr)** | −$2.63M to −$3.28M / yr | ~$364K foregone | **+$2.26M–$2.86M / yr (1 city)** |
| **National Waymo Fleet (10+ Cities)** | −$8M to −$16M+ / yr | Surgical ODD across all metros | **+$6M–$15M+ / yr** (**$20M–$50M+/yr** industry) |
| **Payback Period** | N/A | **< 1 single storm event** (~10h of 1 Bay Area AR) | **Immediate ROI** |
