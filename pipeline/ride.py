"""The ride: one robotaxi trip A -> B on 2026-11-18, told as a story.

plan()      normal route + per-point clock; mid-ride forecast warning (latest model run);
            flood history of the blocks ahead; the "watch point" to simulate.
simulate()  Genie 4 renders the watch-point street (seeded with a real 311 photo) under
            the forecast rain; Decision 1 judges a simulated frame.  (~6-8 s)
reroute()   route that avoids the risky blocks ahead.
proof()     the REAL 311 flood reports on the old vs new route after the decision.
"""
import json
import math
import os
import time
from datetime import datetime, timedelta

from pipeline import route as R

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
GRID = R.GRID


def _j(name, default=None):
    try:
        with open(os.path.join(DATA, name)) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _dist_m(a, b):
    return math.hypot((a[0] - b[0]) * 111000, (a[1] - b[1]) * 88000)


def _timeline(coords, minutes, t0):
    """Clock time at each route point, spread by distance."""
    d = [0.0]
    for a, b in zip(coords, coords[1:]):
        d.append(d[-1] + _dist_m(a, b))
    total = d[-1] or 1
    start = datetime.fromisoformat(t0)
    return [(start + timedelta(minutes=minutes * x / total)).strftime("%Y-%m-%dT%H:%M:%S") for x in d], d


def _cells_on(coords):
    seen, out = set(), []
    for i, (la, lo) in enumerate(R._densify(coords, 30)):
        c = R._cell(la, lo)
        if c not in seen:
            seen.add(c)
            out.append((c, la, lo))
    return out


def _rain_window(fc, t, hours=3):
    h0 = t[:13] + ":00"
    hrs = [h for h in fc["hours"] if h["t"] >= h0][:hours]
    return hrs, (max(hrs, key=lambda h: h["mm"]) if hrs else None)


def plan(frm, to, t="2026-11-18T08:40", date="2026-11-18"):
    cells = {c["id"]: c for c in _j("cells.json")["cells"]}          # history strictly before Nov 18
    fc_latest = _j(f"forecast_{date}_latest.json") or _j(f"forecast_{date}.json")
    base = R._valhalla(frm, to, set())
    times, dist = _timeline(base["coords"], base["min"], t)

    # 1) forecast warning: the in-ride model update for the next hours
    hrs, peak = _rain_window(fc_latest, t, 3)
    warning = {"source": fc_latest["source"], "next_hours": hrs, "peak": peak,
               "text": f"{peak['mm']} mm/h expected at {peak['t'][11:16]} over the route" if peak else "no rain"}

    # 2) history of the blocks ahead
    ahead = []
    for c, la, lo in _cells_on(base["coords"]):
        h = cells.get(c)
        if h and h["n_storm_days"] >= 3:
            ahead.append({"cell": c, "lat": la, "lon": lo, "n_storm_days": h["n_storm_days"],
                          "storm_days": h["storm_days"][:5], "thresh_mm_6h": h["thresh_mm_6h"],
                          "name": (h["top_addresses"] or [c])[0].replace("Intersection of ", "")})
    six_h = sum(x["mm"] for x in [h for h in fc_latest["hours"] if h["t"] <= (peak or {"t": t})["t"]][-6:])
    # where along the route each block sits (0..1)
    n = len(base["coords"])
    for a in ahead:
        k = min(range(n), key=lambda i: _dist_m(base["coords"][i], (a["lat"], a["lon"])))
        a["route_index"], a["frac"], a["eta"] = k, round(dist[k] / (dist[-1] or 1), 3), times[k]
    # risky = strong flood history + forecast rain above the block's threshold, in the 2nd half of the ride
    risky = [a for a in ahead if a["thresh_mm_6h"] is not None and six_h >= a["thresh_mm_6h"]
             and a["n_storm_days"] >= 8 and 0.3 <= a["frac"] <= 0.92]
    risky.sort(key=lambda a: -a["n_storm_days"])
    risky = risky[:10]
    watch = dict(risky[0]) if risky else None
    if watch:
        watch["photo"] = _nearest_photo(date, watch["lat"], watch["lon"])
    decide_index = max(1, int(min(a["route_index"] for a in risky) * 0.6)) if risky else 0
    return {"from": frm, "to": to, "t": t, "date": date,
            "route": {"coords": base["coords"], "times": times, "min": base["min"], "km": base["km"]},
            "warning": warning, "forecast_6h_mm": round(six_h, 1),
            "ahead": ahead, "risky": [r["cell"] for r in risky], "risky_detail": risky, "watch": watch,
            "decide_index": decide_index, "decide_t": times[decide_index]}


def _nearest_photo(date, lat, lon):
    photos = _j(f"photos_{date}.json") or _j("photos_2026-11-18.json", [])
    bad = ("235 GOUGH", "880 5TH", "500 PIERCE", "1931 EVANS", "340 6TH")
    photos = [p for p in photos if not p["address"].upper().startswith(bad)
              and os.path.exists(os.path.join(ROOT, p["path"]))]
    if not photos:
        return None
    p = min(photos, key=lambda p: _dist_m((p["lat"], p["lon"]), (lat, lon)))
    return {**p, "dist_m": round(_dist_m((p["lat"], p["lon"]), (lat, lon)))}


def simulate(watch, warning, session_holder, settle_s=1.2, max_wait=25):
    """Genie 4 world of the watch point under the forecast rain; Decision 1 on a simulated frame."""
    from gem.world import GenieSession
    from gem.vision import judge_frame
    photo = watch["photo"]
    with open(os.path.join(ROOT, photo["path"]), "rb") as f:
        img = f.read()
    peak = warning.get("peak") or {"mm": 0, "t": ""}
    prompt = (f"Street-level view from a driverless robotaxi approaching {watch['name']}, San Francisco, at "
              f"{peak['t'][11:16]} on 2026-11-18. Forecast: {peak['mm']} mm of rain in one hour on already "
              f"saturated streets; this spot flooded on {watch['n_storm_days']} past storms. Show how deep the "
              f"runoff gets on the roadway as the car drives forward slowly. Keep the real street from the photo.")
    t0 = time.time()
    s = GenieSession(img, prompt, max_seconds=30).start()
    session_holder["session"], session_holder["photo"] = s, {**photo, "zone": watch["name"]}
    while s.status in ("starting", "warming") and time.time() - t0 < max_wait:
        time.sleep(0.1)
    s.send_key("key_down", "key_w")
    t1 = time.time()
    while time.time() - t1 < settle_s and s.status == "live":
        time.sleep(0.1)
    frame = s.frame
    t_frame = time.time() - t0
    verdict = judge_frame(frame) if frame else {"flooded_p": None, "depth_label": "unknown"}
    path = os.path.join(ROOT, "media", "renders", f"sim_{watch['cell']}_{int(time.time())}.jpg")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if frame:
        with open(path, "wb") as f:
            f.write(frame)
    return {"verdict": verdict, "frame": os.path.relpath(path, ROOT) if frame else None,
            "genie_first_frame_s": round(s.first_frame_at - s.started_at, 1) if s.first_frame_at else None,
            "total_s": round(time.time() - t0, 1), "frames_seen": s.frame_no}


def reroute(p, from_index=0):
    """Safe route from the car's current position, avoiding the risky blocks."""
    coords = p["route"]["coords"]
    here = coords[min(from_index, len(coords) - 1)]
    excl = set(p["risky"])
    safe = None
    for keep in (len(excl), 6, 3, 1):  # fewer exclusions if the router refuses
        try:
            ex = set(sorted(excl, key=lambda c: -next(r["n_storm_days"] for r in p["risky_detail"] if r["cell"] == c))[:keep])
            safe = R._valhalla(here, p["to"], ex)
            break
        except Exception:
            continue
    if safe is None:
        raise RuntimeError("router refused every exclusion set")
    rest = coords[from_index:]
    # time for the remaining normal route vs the new route
    rest_min = p["route"]["min"] * (len(rest) / max(1, len(coords)))
    t_here = p["route"]["times"][min(from_index, len(coords) - 1)]
    times, _ = _timeline(safe["coords"], safe["min"], t_here)
    crossed = {R._cell(la, lo) for la, lo in R._densify(safe["coords"], 30)} & excl
    return {"coords": safe["coords"], "times": times, "min": safe["min"], "km": safe["km"],
            "added_min": round(safe["min"] - rest_min, 1), "risky_crossed": len(crossed)}


def proof(p, safe, after_t, hours=3):
    """Real 311 flood reports on the old route vs the new route, after the decision."""
    ev = _j(f"events_{p['date']}.json", [])
    end = (datetime.fromisoformat(after_t) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    old_cells = {c for c, _, _ in _cells_on(p["route"]["coords"][p.get("decide_index", 0):])}
    new_cells = {c for c, _, _ in _cells_on(safe["coords"])}

    def pick(cs):
        return [e for e in ev if e["cell"] in cs and after_t <= e["t"] <= end]
    old, new = pick(old_cells), pick(new_cells)
    return {"window": [after_t, end], "old_route": old, "new_route": new,
            "old_n": len(old), "new_n": len(new)}
