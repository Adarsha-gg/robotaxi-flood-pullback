# Demo: 3 minutes, 2 pages

Start the server first: `.venv/bin/python server.py`. Open http://localhost:8000 (the Replay) in one tab and http://localhost:8000/trip in a second tab. Press Start once before going on stage to warm the cache, then reload.

The numbers below are what the app shows every run (checked twice on 2026-11-21).

---

## 0:00 – 0:20 · The problem (Replay tab, before pressing Start)

**Say:** "Three days ago, on November 18, San Francisco had its worst street-flooding day on record: 778 reports to 311. At 11 AM Waymo paused the whole city because robotaxis drove into flooded streets. They only react after a car is stuck. We built the part that looks ahead."

## 0:20 – 0:50 · Before pickup: it is already flooding (press ▶ Start ride)

**Screen:** 09:50. Red dots fill the map: 77 real 311 street-flood reports so far. Three real resident photos appear in the panel (199 Jones St, 204 Park Presidio, 3411 20th St). The fastest route draws, then the green flood-aware route.

**Say:** "9:50 AM. 77 streets have already been reported flooded to 311 this morning. These are the real photos residents sent. Three of those reports sit right on the fastest route, and three more streets on it, Laguna and Oak, Fell and Masonic, Ashbury and Fell, have flooded in 14 to 16 past storms. Gemini 4 Carbon routes around all six. It's even 0.4 minutes faster."

## 0:50 – 1:10 · Mid-ride, the forecast changes

**Screen:** caption "New forecast: 8.6 mm of rain in the next hour", new red dots pop in. Pulse at Franklin & Geary.

**Say:** "Three minutes in, a newer forecast lands, and 14 new reports come in. Ahead is Franklin and Geary. It has flooded in 20 past storms, and two reports came in within 500 meters this morning."

## 1:10 – 1:40 · Simulate the street (Genie 4 + Decision 1)

**Screen:** Genie 4 fills the screen, built from the 199 Jones St photo (inset, 09:10). Then the meters.

**Say:** "The car can't see that street yet. So Genie 4 builds it from the clearest real photo nearby, sent to 311 at 9:10, and plays it forward to the minute the car arrives. Decision 1 asks car questions: is water across the travel lane, does it reach the tire sidewall, are the lane edges hidden."

## 1:40 – 2:05 · The decision, with no human

**Screen:** REROUTE card with two reasons and the rider message. The car never stops.

**Say:** "No human approves anything. Carbon starts deciding the moment the simulation is judged, reads the live reports, history, forecast and simulation, and reroutes. It tells the rider why. The car never stopped."

## 2:05 – 2:30 · Did it work?

**Screen:** clock runs to 11:50; counter 35 vs 16 (real 311 reports in the next 2 hours); caption "11:00 Waymo paused all San Francisco service".

**Say:** "And the check: in the next two hours, 35 floods were reported on the fastest route, 16 on ours. At 11, Waymo paused the city. Across 15 past storms, the same flood memory caught 45% of flooded blocks while covering 8% of the city."

## 2:30 – 3:00 · It works today (switch to the Plan a trip tab)

**Screen:** press Go on Noe Valley → Chase Center (or ask a judge for two places). Genie starts from the live Caltrans camera US-101 at 23rd St.

**Say:** "And it runs live. Any two places in San Francisco. It pulls flood reports from the last three days, tonight's forecast, live lane closures and live Caltrans cameras, simulates the worst spot with Genie 4, and Carbon decides. Same loop works for any hazard a robotaxi struggles with: floods today, construction zones next, which is exactly why Waymo got pulled off California freeways."

---

## If something breaks

- **Genie slow or down:** the simulation falls back to a real cached Genie run of Franklin and Geary. Nothing to say.
- **Carbon slow:** after 8 seconds a rule-based fallback decides, with the same card. Nothing to say.
- **Wi-Fi dies:** play the backup screen recording. Record one full Replay run before the demo.
- **A Plan-a-trip address isn't found:** use "Noe Valley" → "Chase Center".

## Likely judge questions

- **"Is the Genie scene real?"** It is a simulation, seeded with a real resident photo or a live camera frame. The decision uses it as one input next to real data. We label it "simulated" everywhere.
- **"Did you cheat with hindsight?"** No. Flood history stops the day before Nov 18. The car only sees 311 reports and photos filed before each decision. Forecasts are the night-before and same-day model runs (Open-Meteo previous-runs archive). Reports after the decision are only used for the final check.
- **"Human flooding vs car flooding?"** 311 separates street flooding from basement/property flooding. On Nov 18: 691 street, 87 property. The car only uses street reports, and the simulation questions are about the travel lane and the tires.
- **"Why not just use Waymo's own sensors?"** Sensors see what is in front of the car now. This sees four blocks and twenty minutes ahead.
- **"Does it cry wolf?"** On real Waymo camera footage of a rainy SF freeway (Waymo Open Dataset), the judge says "wet road, proceed" at 22–27%.
- **"Where does Waymo actually drive?"** Waymo's own CPUC filing: 48% of the Nov 18 floods landed in the 27% of SF tracts where Waymo reported collisions in Q3 2026.
- **"Why freeways?"** The DMV pulled driverless cars off California freeways on Nov 11 for driving into construction zones and past a CHP traffic break, and Waymo filed two recalls on Nov 19–20. Our lane-closure layer reads the same kind of data.

## Sources to have open

- Engadget, Waymo pauses SF service after robotaxis get stuck on flooded streets (Nov 18)
- SFist, Waymo blocks traffic on flooded Oak Street (Nov 18)
- ABC7, California DMV bans Waymos from freeways (Nov 17)
- Engadget, Waymo recalls after driving into closed freeway lanes (Nov 21)
