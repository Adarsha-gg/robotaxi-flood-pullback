# Robotaxi Flood Pull-Back

Robotaxis keep driving into flooded streets. On 2026-11-18, Waymo paused all San Francisco service around 11 AM after cars stopped in flooded crosswalks. That day, San Francisco logged 778 street-flooding reports to 311, the most on record.

This project gives a robotaxi fleet operations manager a flood plan for the day:

1. **Flood memory.** About 33,000 historical SF 311 street-flooding reports show which streets flood, and at what rain rate.
2. **Morning plan.** Gemini 4 Carbon reads the hourly rain forecast and draws time-boxed no-go zones, each with a reason. Gemini Decision 1 gives a calibrated flood probability per street per hour. The ops manager approves the zones.
3. **Reroute.** Trips are planned around the active zones.
4. **Fleet eyes.** Decision 1 judges car camera frames ("is this road flooded?") so the first car to see water warns the fleet. Genie 4 renders a flagged street flooded, so the team sees what the car will face.

Built at the Gemini 4 NYC Hackathon, 2026-11-21.

## Status

Work in progress. See [PLAN.md](PLAN.md), [contracts.md](contracts.md), [GEMINI_TASKS.md](GEMINI_TASKS.md) and [CLAUDE_TASKS.md](CLAUDE_TASKS.md).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install google-genai python-dotenv
echo "GEMINI_API_KEY=your-key" > .env
```

`experiments/` holds earlier API tests (Decision 1 and Hydrogen on images and video).
