# Why Robotaxis Fail on Flooded Streets: Automotive Hydrodynamics, AV Sensor Physics & EV HV Safety

> **Purpose:** Grounds our Decision 1 visual flood-depth rubric (`tire tread` / `tire sidewall` / `wheel hub` / `edges_hidden`) and autonomous Dynamic ODD pitch in verified automotive engineering, ISO 21448 (SOTIF) sensor physics, and federal EV flood-safety standards.

---

## 1. Vehicle Wading Depth, Ground Clearance & Exact Tire Geometry

### 1.1 Robotaxi Platforms vs. Passenger Sedans
| Platform | Role | Standard Ground Clearance | Published Max Wading Depth | Factory Tire Sizes |
| :--- | :--- | :--- | :--- | :--- |
| **Jaguar I-PACE** | Waymo Gen-5 | **174 mm (6.85 in)** coil *(up to 230 mm / 9.1 in air)* | **500 mm (~19.7–20 in)** *(controlled, slow, clean water)* | `235/65R18`, `245/50R20` |
| **Hyundai Ioniq 5** | Waymo Gen-6 | **160 mm (6.3 in)** standard | **None published** *(on-road EV crossover)* | `235/55R19`, `255/45R20` |
| **Typical Sedan** *(Camry / Civic)* | Urban baseline | **135–160 mm (5.3–6.3 in)** | **None** | `215/55R17` |

### 1.2 NWS / FEMA / AAA Flood-Depth Danger Thresholds
- **6 inches (150 mm):** Reaches underbody/rocker panels (`5.3–6.3 in` clearance) → **loss of traction, loss of steering control, or stalling**.
- **12 inches (300 mm):** Buoyant force **floats most passenger vehicles**, eliminating tire friction.
- **18–24 inches (450–600 mm):** **Sweeps away most vehicles, including heavy SUVs/trucks** (exceeding even the I-PACE's controlled 500 mm test limit).

### 1.3 Exact Tire Geometry Mapping — Validating Decision 1 (`CAR_QUESTIONS`)
| Tire Size (Vehicle) | Sidewall Height (to Rim Edge) | Overall Diameter | Wheel-Hub / Axle Height *(loaded–unloaded)* |
| :--- | :--- | :--- | :--- |
| **`215/55R17`** *(Mid-size sedan)* | **4.66 in (118 mm)** | 26.31 in (668 mm) | **12.5–13.2 in (317–334 mm)** |
| **`245/50R20`** *(Jaguar I-PACE 20")* | **4.82 in (123 mm)** | 29.65 in (753 mm) | **14.1–14.8 in (358–377 mm)** |
| **`235/55R19`** *(Hyundai Ioniq 5 19")* | **5.09 in (129 mm)** | 29.18 in (741 mm) | **13.9–14.6 in (353–371 mm)** |

| Decision 1 Visual Cue | Physical Water Depth | Engineering / NWS Alignment | Autonomous Action |
| :--- | :--- | :--- | :--- |
| **1. Tire tread / wet** | **~1–2 in (25–50 mm)** | Wet film / shallow splash; well below chassis underbody | **`proceed`** |
| **2. Tire sidewall (to rim edge)** | **~4–6 in (100–150 mm)** | Matches sidewall (`4.5–5.1 in`) & **NWS 6-inch critical threshold**; touches sedan/Ioniq 5 underbody (`6.3 in`); hides curbs & popped manholes | **`slow` / reroute boundary** |
| **3. Wheel hub / axle center** | **~10–14+ in (250–360+ mm)** | Matches axle center & **NWS 12-inch flotation threshold**; dynamic wave hits HV seals & door sills | **Hard `avoid`** |

---

## 2. AV Sensor Physics on Standing Water (ISO 21448 — SOTIF)

Under **ISO 21448:2022 (SOTIF)**, standing water causes a **functional insufficiency with zero hardware failure**:
1. **LiDAR (905 nm vs 1550 nm) — Mirror Effect + 74× Absorption:**
   - Smooth standing water acts as a specular mirror: oblique beams bounce away (**zero-return "phantom holes"** in the road plane) or bounce off buildings (**phantom underground ghosts** below ground).
   - From Hale & Querry (*Applied Optics*, 1973): liquid water attenuation at **1550 nm** ($\alpha \approx 693\text{ m}^{-1}$) is **~74× stronger** than at **905 nm** ($\alpha \approx 9.3\text{ m}^{-1}$) — round-trip transmission through just 1 cm of water drops $>99.9999\%$, making submerged pavement unreadable.
2. **Automotive Radar (77 GHz, $\lambda \approx 3.9\text{ mm}$) — Multipath & Zero Depth Profiling:**
   - Water attenuation exceeds **~30 dB/mm** at 77 GHz; radar reflects off the air-water interface (creating multipath clutter) and **cannot measure standing-water depth**.
3. **RGB Cameras — Glare & Submerged Hazards:**
   - Specular glare erases lane markings and curbs (`edges_hidden`), while turbid runoff conceals potholes and **dislodged/floating cast-iron manhole covers** (documented across SF on Nov 18, 2026).

---

## 3. EV High-Voltage Safety & Why Fleets Must Stop Early

- **IP67/IP68 ≠ Dynamic Wading:** IEC 60529 IP67 tests *static* clean-water immersion (1 m / 30 min). Driving at 10–15 mph creates a **bow wave** closer to high-pressure **ISO 20653 IPX9K** jet pressure against floorpan gaskets and breathers—and passing buses/SUVs push 6–12" waves over creeping AVs.
- **UN ECE R100 Instant Stranding:** Water breaching an HV connector drops insulation resistance and triggers immediate **HV isolation disconnect**, immobilizing the driverless vehicle mid-flood.
- **Delayed Thermal Runaway (NHTSA / USFA / FEMA / NFPA):** Conductive stormwater/saltwater inside a Li-ion pack causes delayed thermal runaway hours to weeks later, mandating **50-foot open-air quarantine** and frequent total-loss write-offs ($65K–$150K+ vehicle).
