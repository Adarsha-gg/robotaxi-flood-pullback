# Demo: 3 minutes, 2 pages

Start the server first: `.venv/bin/python server.py`. Open http://localhost:8000 (the Replay) in one tab and http://localhost:8000/trip in a second tab. Press Start once before going on stage to warm the cache, then reload. Space pauses the ride if a judge asks a question; click any finished step to replay it.

The numbers below are what the app shows every run (checked twice on 2026-11-21).

---

## 0:00 – 0:20 · The problem (Replay tab, before pressing Start)

**Say:** "Three days ago, on November 18, San Francisco had its worst street-flooding day on record: 778 reports to 311. At 11 AM Waymo paused the whole city because robotaxis drove into flooded streets. They only react after a car is stuck. We built the part that looks ahead."

## 0:20 – 0:45 · Before pickup: it is already flooding (press ▶ Start ride)

**Screen:** 10:00. Red dots fill the map: 122 real 311 street-flood reports so far, with real resident photos (a Waymo on 2nd St at 09:49). The fastest route draws as a red dotted line.

**Say:** "10 AM. 122 streets have already been reported flooded to 311 this morning. The car checks the fastest route before pickup."

## 0:45 – 1:15 · Simulate the fastest route's worst spot

**Screen:** 1777 Oak St, a resident's photo from 09:57: water running across Oak St, a barricade knocked over. Genie 4 plays the forecast forward to 10:03, when the car would get there: AVOID, water over the tire sidewall.

**Say:** "Right on the fastest route, Oak Street. A resident sent this photo three minutes ago. Genie 4 builds the street from it and plays the forecast forward to the minute the car would arrive: 7 millimeters that hour. Decision 1 checks it the way a car would: water over the tire sidewall. Oak Street is where a Waymo blocked traffic that morning."

## 1:15 – 1:35 · Carbon picks the route, no human

**Screen:** REROUTE card, green route draws around Oak St. A second robotaxi (dark, red ring) takes the fastest route.

**Say:** "Gemini 4 Carbon decides on its own: take the route around it. It's even 0.4 minutes faster. Watch the other robotaxi, the one that only follows the fastest route."

## 1:35 – 2:05 · Mid-ride: check again, don't overreact

**Screen:** New forecast, Franklin & Geary ahead. Genie again from the clearest nearby photo: puddles below the tire tread. Carbon keeps the route. The fastest-route robotaxi shows STUCK at 1777 Oak St. The fleet agent (Antigravity Managed Agent) calls its tools and draws a purple avoid zone.

**Say:** "Three minutes in, a new forecast. The car simulates the next street too: puddles. So it keeps going. It doesn't cry wolf. Meanwhile the other robotaxi is stuck on Oak Street. And our fleet agent, an Antigravity Managed Agent, takes what this car saw and pulls the whole fleet off Franklin for the next four hours."

## 2:05 – 2:30 · Did it work?

**Screen:** counter 30 vs 9 (real 311 reports in the next 2 hours), "11:00 Waymo paused all San Francisco service".

**Say:** "In the next two hours: 30 floods on the fastest route, 9 on ours. At 11, Waymo paused the city."

## 2:30 – 3:00 · It works today (switch to the Plan a trip tab)

**Screen:** press Go on Noe Valley → Chase Center (or ask a judge for two places). Genie starts from the live Caltrans camera US-101 at 23rd St.

**Say:** "And it runs live. Any two places in San Francisco. It pulls flood reports from the last three days, tonight's forecast, live lane closures and live Caltrans cameras, simulates the worst spot with Genie 4, and Carbon decides. Same loop works for any hazard a robotaxi struggles with: floods today, construction zones next, which is exactly why Waymo got pulled off California freeways."

---

## If something breaks

- **Genie slow or down:** the simulations fall back to real cached Genie runs of 1777 Oak St and Franklin & Geary. Nothing to say.
- **Carbon slow:** after 8 seconds a rule-based fallback decides, with the same card. Nothing to say.
- **Wi-Fi dies:** play the backup screen recording. Record one full Replay run before the demo.
- **A Plan-a-trip address isn't found:** use "Noe Valley" → "Chase Center".

## Likely judge questions

- **"Doesn't Waymo already do this with its World Model?"** No, it does a different job. Waymo's World Model (Feb 6, 2026, built on DeepMind's Genie 3) runs offline in their simulator: it makes rare scenes, floods included, to train and test the driver before cars ship. We run at trip time: for a real street on today's route, with today's forecast, 311 reports, closures and cameras, Genie 4 shows what the car will meet when it arrives, Carbon decides, and a fleet agent warns the other cars. Waymo had that model since February and still paused San Francisco on Nov 18. "Waymo uses Genie to train the driver. We use Genie to plan the trip."
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
