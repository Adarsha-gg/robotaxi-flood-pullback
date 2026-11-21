# Nov 18 SF Storm Verified Press Quotes & $5k Managed Agents Track Playbook

> **Purpose:** Exact, verifiable Nov 18–19, 2026 press quotes and facts for our stage hook + concrete rubric & 20-second demo pattern for the **Cerebral Valley / Google DeepMind $5,000 Managed Agents (`antigravity-preview-09-2026`) track**.

---

## 1. Verified Nov 18–19, 2026 San Francisco Storm Facts & Press Quotes

- **Rainfall Record:** **2.64 inches** total daily rainfall in Downtown SF (**2.28"** by 3:00 PM PT), breaking the **108-year-old** Nov 18 daily record of **2.24"** set in **1918**.
- **Worst-Hit Areas:** Mission District, Marina District, Sunset District, Ocean Beach (floating manhole covers / sewage geysers), and Panhandle. **SFMTA / Muni** suffered systemwide delays, route bypasses, and closed **Van Ness Station** (right beside our Grove & Van Ness corridor!).
- **Waymo Stalls:** **At least 5 Waymo vehicles** stalled in standing water across SF, including confirmed intersections:
  - **Oak Street & Cole Street** (Panhandle): Waymo stalled directly in the flooded intersection, blocking a passable lane.
  - **Bayshore Boulevard & Industrial Street** (east of US-101): Waymo disabled/stuck in deep floodwater.
- **Exact Pause & Resumption Window:**
  - **~11:00 AM PT, Wed Nov 18, 2026:** Paused across San Francisco, the Peninsula, and the South Bay (after initially thinning the fleet earlier that morning).
  - **~10:00 AM PT, Thu Nov 19, 2026:** Resumed after **~23 hours offline**.

### Exact Verbatim Quotes (Safe to Cite on Stage / Devpost)
- **NWS Bay Area (`@NWSBayArea`, Nov 18, via CBS News Bay Area):**
  > *"Record daily rainfall for Downtown San Francisco. As of 3 pm 2.28 inches of rain has fallen so far today (since midnight). The old record for this date was 2.24 inches back in 1918."*
- **Waymo In-App Rider Message (~11:00 AM PT, via Engadget):**
  > *"We've paused for now due to weather"* — adding service would resume *"when road conditions improve and the forecast looks clear."*
- **SF Supervisor Bilal Mahmood (via KQED):**
  > *"We have been informed that Waymo service has accordingly been paused today due to stalling in flood zones."*
- **Waymo Spokesperson (via CBS News):**
  > *"Safety is Waymo's top priority, both for our riders and everyone we share the road with."*

---

## 2. Google DeepMind / Cerebral Valley Judging Rubric & $5k Managed Agents Track

### Standard Overall Judging Weights
1. **Technical Execution & Deep Stack Integration (30–40%):** Does it actually work cleanly, and does it use capabilities *unique* to Gemini 4?
2. **Innovation & "Wow" Factor (30–40%):** Solves a hard problem not viable before frontier multimodal + world-model + managed-agent loops.
3. **Real-World Impact & Utility (20%):** Concrete, urgent real-world pain point (live AV fleet ops & municipal incident response).
4. **Presentation & Demo Clarity (10%):** Crisp hook, unmistakable live proof, zero wasted time.

### What Specifically Wins the $5,000 Managed Agents (`antigravity-preview-09-2026`) Track
1. **Anti-"Thin Wrapper" Rule:** Judges reject single-prompt wrappers or brittle `if/else` scripts. You must visibly demonstrate multi-step planning, multi-tool orchestration, and autonomous decision-making inside `environment="remote"`.
2. **Visible Interactions API Primitives:** Show `agent: antigravity-preview-09-2026`, `previous_interaction_id` stateful multi-turn continuity, real tool execution (`get_cell_history`, `get_forecast`, `estimate_fleet_detour`, `propose_zone` / `decide`), and concrete artifacts pushed straight back into the live app.
3. **Autonomous Guardrails & Error Recovery:** Highlight programmatic safety constraints (Chebyshev ≤ 2 basin bound, `23:59` clamp, Valhalla detour budgeting `+1.19 min`, 2-frame reopen hysteresis, citation validator) so the agent cannot hallucinate or over-block dry arterials.
4. **Honest Evals Over Cherry-Picking:** Cite real numbers with caveats: **15-storm leave-one-storm-out backtest (`44.8%` vs `7.9%` random)**, **Waymo Open Dataset rain control (`0.22–0.30` Decision 1 / `0.05` Hydrogen → `PROCEED`)**, and **12 live Caltrans cameras (`0` false alarms in `2.03 s`)**.

---

## 3. The 20-Second Managed Agent Proof Pattern (For Demo or Q&A)

If a judge asks *"How do you use Managed Agents?"* (or as a crisp 20-second beat on `/cam`):
1. **0–5 s (Trigger inside UI):** Open `/cam` on **`691 2nd St ★ Waymo`** (a real Nov 18 311 photo showing a Waymo roof dome in standing water *outside* every pre-storm zone) and show the `antigravity-preview-09-2026` + `interaction_id` header.
2. **5–13 s (Multi-Tool Reasoning):** Point to the live/replayed 4-step tool cards: `Decision 1 (0.91 flooded)` → `get_cell_history (3×3 basin)` → `get_forecast` → `estimate_fleet_detour (+1.19 min, +0.39 km via Valhalla)` → `propose_zone`.
3. **13–20 s (Artifact Lands in Fleet Ops):** Show the new cyan closure zone + Fleet Dispatch Notice instantly rerouting every car behind car #1 on `/ops` — zero human in the loop.
