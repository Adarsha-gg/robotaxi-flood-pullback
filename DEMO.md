# Demo: 3 minutes, 2 pages

Start the server first: `.venv/bin/python server.py`. Open http://localhost:8000 (the Replay) in one tab and http://localhost:8000/trip in a second tab. Press Start once before going on stage to warm the cache, then reload.

The numbers below are what the app shows every run (checked twice on 2026-11-21).

---

## 0:00 – 0:20 · The problem (Replay tab, before pressing Start)

**Say:** "Three days ago, on November 18, San Francisco had its worst street-flooding day on record: 778 reports to 311. At 11 AM Waymo paused the whole city because robotaxis drove into flooded streets. They only react after a car is stuck. We built the part that looks ahead."

## 0:20 – 0:45 · Before pickup (press ▶ Start ride)

**Screen:** the fastest route draws, three blue dots appear, the route turns into a green flood-aware route.

**Say:** "8:58 AM. Before pickup, the car checks the fastest route against the night-before forecast and every street that has flooded in past storms. Laguna and Oak, Fell and Masonic, Ashbury and Fell have flooded 14 to 16 times each. Gemini 4 Carbon picks a route around them. It costs half a minute."

## 0:45 – 1:05 · Mid-ride, the forecast changes

**Screen:** caption "New forecast: 8.6 mm of rain in the next hour". The car slows. Blue dot and orange dashed line appear at Grove and Van Ness.

**Say:** "Three minutes in, a newer forecast lands: 8.6 millimeters in an hour. Ahead is Grove and Van Ness. The street has flooded in 8 past storms, and right next to it, 5 permitted lane closures are active on Van Ness and Fell. That is exactly the kind of spot where cars get stuck."

## 1:05 – 1:40 · Simulate the street (Genie 4 + Decision 1)

**Screen:** real resident photo on the left, Genie 4 on the right, then the meters fill: SLOW, water across most of the lane.

**Say:** "The car can't see four blocks ahead. So Genie 4 builds that street, starting from a real photo a resident sent to 311 that morning, and plays the forecast forward to the minute the car would get there. Decision 1 then asks car questions, not human questions: is water across the travel lane, does it reach the tire sidewall, are the lane edges hidden. Answer: slow, water across most of the lane."

## 1:40 – 2:05 · The decision, with no human

**Screen:** green route redraws from where the car is; the card shows REROUTE, three reasons, and the rider message. The car never stops.

**Say:** "No human approves anything. Gemini 4 Carbon reads the forecast, the flood history, the closures and the simulation, and decides in a few seconds: reroute. It even tells the rider why. The new route is also faster. The car never stopped."

## 2:05 – 2:30 · What really happened

**Screen:** clock fast-forwards to noon, red dots land on the fastest route, counter shows 37 vs 13, caption "11:00 Waymo paused all San Francisco service".

**Say:** "Now the real 311 reports from that morning. 37 street floods on the fastest route, 13 on ours. The first one hit at 9:35 on Webster Street. At 11, Waymo paused the city. This car finished its trip. And this isn't one lucky storm: across 15 past storms, the same flood memory caught 45% of flooded blocks while covering 8% of the city."

## 2:30 – 3:00 · It works today (switch to the Plan a trip tab)

**Screen:** type two places (or ask a judge for two), press Go.

**Say:** "And it runs live. Any two places in San Francisco. It pulls flood reports from the last three days, tonight's forecast, live lane closures and live Caltrans cameras, simulates the worst spot with Genie 4, and Carbon decides. Same loop works for any hazard a robotaxi struggles with: floods today, construction zones next, which is exactly why Waymo got pulled off California freeways."

---

## If something breaks

- **Genie slow or down:** the simulation falls back to a real cached Genie run of Grove and Van Ness. Nothing to say.
- **Carbon slow:** after 8 seconds a rule-based fallback decides, with the same card. Nothing to say.
- **Wi-Fi dies:** play the backup screen recording. Record one full Replay run before the demo.
- **A Plan-a-trip address isn't found:** use "Noe Valley" → "Moscone Center".

## Likely judge questions

- **"Is the Genie scene real?"** It is a simulation, seeded with a real resident photo or a live camera frame. The decision uses it as one input next to real data. We label it "simulated" everywhere.
- **"Did you cheat with hindsight?"** No. Flood history stops the day before Nov 18, and the route decisions use the night-before forecast run and the same-day model run (Open-Meteo previous-runs archive). The 311 reports are only used afterwards, to score.
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
