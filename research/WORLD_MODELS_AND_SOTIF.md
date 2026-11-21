# World Models in AV Safety: Why Genie 4 + Decision 1 Is NOT Circular

> **Purpose:** DeepMind-researcher-grade framing for `genie-4` + `gemini-decision-1` — answering the #1 toughest technical objection (*"Isn't Decision 1 grading Genie 4's own generated pixels circular?"*) with real 2025–2026 peer-reviewed and industry citations.

---

## 1. The 3-Sentence "DeepMind-Proof" Answer (For Live Q&A)

> *"It would be circular if we treated Genie 4 as a hydrological depth sensor—we don't; routing authority stays anchored in real 311 street-flood memory, real SFMTA lane closures, real precipitation forecasts, and live Caltrans/fleet cameras. What static pins and mm/h numbers cannot show is how a car's vision stack behaves under rare compositional hazards—like standing-water glare erasing lane lines or murky water around construction cones at a street the fleet has only seen dry. Following DeepMind's own Veo world-simulator evaluation paradigm (`arXiv:2512.10675`) and Waymo's Genie-3-based World Model (Feb 2026), we calibrate Decision 1 exclusively on real-world ground truth (Waymo Open Dataset rain + real Nov 18 photos + live cameras) and use Genie 4 strictly for counterfactual preview and ISO 21448 (SOTIF) Area 3 predictive red-teaming."*

---

## 2. Real Industry & Academic Anchors (2023–2026)

| Source / System | Date | Core Principle & Relevance to Robotaxi Flood Pull-Back |
|---|---|---|
| **Waymo World Model** *(built on Google DeepMind's **Genie 3**)* | Feb 6, 2026 | Waymo post-trained DeepMind's Genie 3 on fleet data to generate camera + 4D LiDAR counterfactuals—explicitly highlighting **flooded streets with floating debris & flash floods** because fleets cannot safely accumulate enough real-world exposure to rare flood edge cases. |
| **Google DeepMind — *Evaluating Gemini Robotics Policies in a Veo World Simulator*** (`arXiv:2512.10675`) | Dec 2025 | Validated across **1,600+ real-world trials**: defines 3 scientifically valid roles for generative world simulators—(1) correlating policy performance, (2) predicting **OOD degradation** under environmental shifts, and (3) **predictive red-teaming** before deployment—while explicitly noting physical artifacts require real-world calibration. |
| **Oefinger et al., TUM — *Validate the Dream Before You Trust Its Verdict*** (`arXiv:2607.07196`) | Jul 2026 | Formalizes the exact **"trust inversion" / circularity risk** in world-model safety evaluation: high visual quality (`L0`) ≠ valid safety verdict. Proposes a 5-rung Admissibility Ladder (`L0 Quality → L1 Action-Robust → L2 OOD-Bounded → L3 Failure-Attributable → L4 Verdict-Transfer-Validated`). We satisfy this separation by calibrating Decision 1 strictly on *real* data and labeling Genie outputs **`SIMULATED`** everywhere. |
| **Wayve GAIA-1 & GAIA-2** (`arXiv:2503.20523`) | Mar 2025 | Controllable multi-view latent diffusion world model used for **semantic weather/lighting counterfactuals** (converting dry daytime logs into downpours, wet-road specular glare, and fog) and offline validation suites mutating historical edge cases. |
| **NVIDIA Cosmos** (`arXiv:2501.03575`) | Jan 2025 | Decouples world-model functions into **Cosmos Transfer** (dry-to-storm domain translation), **Cosmos Predict** (counterfactual rollouts), and **Cosmos Reason** (VLM evaluation), wrapped in explicit guardrails because generative rollouts can hallucinate physics. |
| **Waabi World / UniSim** (CVPR) | 2023 | Turns real sensor logs into closed-loop reactive simulations anchored in **paired sim-to-real calibration** (real-vs-sim agreement up to 99.7%) rather than ungrounded synthetic runs. |
| **ISO 21448 (SOTIF)** | Standard | Targets perception/functional insufficiencies (not hardware faults). Mandate: surface **Area 3 (Unknown-Unsafe)** triggering conditions (e.g., specular wet glare + submerged lane lines + construction cones) and move them into known, mitigated regimes (**Area 2 / Area 1**). |

---

## 3. Clear Scientific Boundary (Never Overclaim)

- **What Genie 4 CAN do scientifically:**
  1. Generate **compositional long-tail visual scenarios** (*flooded arterial + SFMTA orange cones + dusk headlight glare*) that rarely co-occur in real fleet logs.
  2. Stress-test **zero-shot wet-road perception** (sky reflections mimicking dry road, obscured lane edges, tire spray) to surface ISO 21448 Area 3 blind spots.
  3. Provide **human-interpretable counterfactual previews** of what a dry live camera view looks like under a forecast cloudburst (`+8–15 mm/h`) at arrival ETA.
- **What Genie 4 CANNOT do scientifically:**
  1. Act as a **Navier–Stokes hydrological depth sensor** (it samples learned visual/spatiotemporal priors, not physical culvert drainage equations).
  2. Act as a **standalone uncalibrated ground-truth oracle** (must always sit beside real 311 history, real rainfall, real lane closures, and real-world-calibrated Decision 1 thresholds).

---

## 4. Two Concrete Flywheels Static Maps / 311 Rules Cannot Build

1. **Pre-Storm Counterfactual Rehearsal (Dry Cam → Forecast Cloudburst):** When heavy rain is forecast over a flood-prone corridor, Genie 4 translates recent *dry* fleet/Caltrans views of that exact road geometry into storm arrival counterfactuals. Decision 1 probes where visual ambiguity spikes (lane edges disappearing, glare causing false positives) *before* the storm arrives; when the storm hits, real fleet frames close the loop via paired sim-to-real recalibration.
2. **Continuous Offline SOTIF Area 3 Regression Suite:** Every real 311 flood photo, stalled-car near-miss, or closure incident becomes a seed that Genie 4 perturbs across unseen axes (*flood + cones + night glare + stalled car wake*). Every new Decision 1 / perception model release is gated against **both** held-out real-world calibration benchmarks (Waymo Open Dataset rain + Nov 18 311) **and** this expanding counterfactual regression suite—turning reactive storm post-mortems into a repeatable pre-deployment engineering loop.
