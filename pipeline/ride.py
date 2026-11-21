"""The ride: one robotaxi trip A -> B on 2026-11-18, with two flood decisions and no stops.

plan()      PRE-TRIP: fastest route; scan it against the forecast available at departure
            (night-before run) + street-only flood memory; pick the flood-aware route A.
check()     MID-RIDE: a newer forecast run arrives; scan the rest of route A; return the
            block to simulate ("watch") if any.
simulate()  Genie 4 renders that street from a robotaxi's roof camera, seeded with a real
            311 photo; Decision 1 answers CAR questions (lane covered? depth vs wheel? lane
            edges hidden?) on simulated frames.
reroute()   new route from the car's current position, avoiding every risky block.
proof()     REAL street-flooding 311 reports on the fastest route vs the route driven.
Car-relevant only: 311 reports filed as flooding "on the street" (not basements/property).
"""
import base64
import json
import math
import os
import time
from datetime import datetime, timedelta

from pipeline import route as R

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
BAD_PHOTOS = ("235 GOUGH", "880 5TH", "500 PIERCE", "1931 EVANS", "340 6TH")
A_MIN_STORMS, B_MIN_STORMS = 14, 6


def _j(name, default=None):
    try:
        with open(os.path.join(DATA, name)) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _dist_m(a, b):
    return math.hypot((a[0] - b[0]) * 111000, (a[1] - b[1]) * 88000)


def _timeline(coords, minutes, t0):
    d = [0.0]
    for a, b in zip(coords, coords[1:]):
        d.append(d[-1] + _dist_m(a, b))
    start = datetime.fromisoformat(t0)
    return [(start + timedelta(minutes=minutes * x / (d[-1] or 1))).strftime("%Y-%m-%dT%H:%M:%S") for x in d], d


def _cells_on(coords):
    seen, out = set(), []
    for la, lo in R._densify(coords, 30):
        c = R._cell(la, lo)
        if c not in seen:
            seen.add(c)
            out.append((c, la, lo))
    return out


def _six(fc, t):
    hrs = [h for h in fc["hours"] if h["t"] <= t[:13] + ":00"][-6:]
    return round(sum(h["mm"] for h in hrs), 1)


def _route(coords_from, to, excl, t0, no_freeways=False):
    r = R._valhalla(coords_from, to, set(excl), no_freeways=no_freeways)
    times, dist = _timeline(r["coords"], r["min"], t0)
    return {"coords": r["coords"], "times": times, "min": r["min"], "km": r["km"], "dist": dist}


def _scan(route, cells, six_mm, min_storms, lo=0.0, hi=1.0, skip=()):
    """Blocks on the route with street-flood history whose threshold the forecast beats."""
    n, total, out = len(route["coords"]), route["dist"][-1] or 1, []
    for c, la, lo_ in _cells_on(route["coords"]):
        h = cells.get(c)
        if not h or c in skip or h["n_storm_days"] < min_storms or h["thresh_mm_6h"] is None or six_mm < h["thresh_mm_6h"]:
            continue
        k = min(range(n), key=lambda i: _dist_m(route["coords"][i], (la, lo_)))
        frac = route["dist"][k] / total
        if lo <= frac <= hi:
            out.append({"cell": c, "lat": la, "lon": lo_, "n_storm_days": h["n_storm_days"],
                        "storm_days": h["storm_days"][:6], "thresh_mm_6h": h["thresh_mm_6h"],
                        "name": (h["top_addresses"] or [c])[0].replace("Intersection of ", ""),
                        "route_index": k, "frac": round(frac, 3), "eta": route["times"][k]})
    out.sort(key=lambda a: -a["n_storm_days"])
    return out


def _strip(r):
    return {k: v for k, v in r.items() if k != "dist"}


def plan(frm, to, t="2026-11-18T08:58", date="2026-11-18"):
    cells = {c["id"]: c for c in (_j("cells_street.json") or _j("cells.json"))["cells"]}
    fc_night = _j(f"forecast_{date}.json")
    fast = _route(frm, to, [], t)
    six_a = _six(fc_night, "2026-11-18T08:00")
    risky_a = _scan(fast, cells, six_a, A_MIN_STORMS, 0.12, 0.9)[:4]
    route_a = _route(frm, to, [r["cell"] for r in risky_a], t) if risky_a else fast
    pre = decide_pre_trip(fast, route_a, risky_a, six_a, fc_night) if risky_a else None
    if pre and pre["action"] == "keep_route":
        route_a = fast
    return {"from": frm, "to": to, "t": t, "date": date, "pre_decision": pre,
            "fast": _strip(fast), "route_a": _strip(route_a), "risky_a": risky_a,
            "pre_trip": {"forecast_source": fc_night["source"], "six_h_mm": six_a,
                         "day_total_mm": fc_night["total_mm"],
                         "hours": [h for h in fc_night["hours"] if "06:00" <= h["t"][11:16] <= "12:00"]},
            "_route_a_dist": route_a["dist"]}


def check(p, at_index, min_frac=0.0):
    """Mid-ride: newer forecast run; scan the rest of route A."""
    cells = {c["id"]: c for c in (_j("cells_street.json") or _j("cells.json"))["cells"]}
    fc_latest = _j(f"forecast_{p['date']}_latest.json") or _j(f"forecast_{p['date']}.json")
    t_now = p["route_a"]["times"][at_index]
    hrs = [h for h in fc_latest["hours"] if h["t"] >= t_now[:13] + ":00"][:3]
    peak = max(hrs, key=lambda h: h["mm"]) if hrs else None
    six_b = _six(fc_latest, (peak or {"t": t_now})["t"])
    ra = {**p["route_a"], "dist": p["_route_a_dist"]}
    frac_now = ra["dist"][at_index] / (ra["dist"][-1] or 1)
    risky_b = _scan(ra, cells, six_b, B_MIN_STORMS, max(min_frac, frac_now + 0.15), 0.92,
                    skip={r["cell"] for r in p["risky_a"]})[:4]
    # simulate the strongest block that has a real street-level photo close by
    for r in risky_b:
        r["photo"] = _car_photo(p["date"], r["lat"], r["lon"])
    near = [r for r in risky_b if r["photo"] and r["photo"]["dist_m"] <= 900]
    watch = dict((near or risky_b)[0]) if risky_b else None
    return {"t": t_now, "at_index": at_index, "forecast_source": fc_latest["source"], "next_hours": hrs,
            "peak": peak, "six_h_mm": six_b, "risky_b": risky_b, "watch": watch}


def _car_photo(date, lat, lon):
    """Nearest real 311 photo that shows the ROADWAY (prefer ones with cars in the water)."""
    photos = _j(f"photos_{date}.json") or _j("photos_2026-11-18.json", [])
    photos = [p for p in photos if not p["address"].upper().startswith(BAD_PHOTOS)
              and os.path.exists(os.path.join(ROOT, p["path"]))]
    road = [p for p in photos if (p.get("road_view") or 0) >= 0.6] or photos  # car's-eye photos only
    if not road:
        return None
    # nearest road-view photo; a car in the water nearby is a strong tiebreaker
    p = min(road, key=lambda p: _dist_m((p["lat"], p["lon"]), (lat, lon)) - 300 * (p.get("cars_in_water") or 0))
    return {**p, "dist_m": round(_dist_m((p["lat"], p["lon"]), (lat, lon)))}


CAR_QUESTIONS = {
    "lane_covered": {"type": "noul", "instructions":
        "Is standing or running water covering the vehicle TRAVEL LANE of the road (not just the sidewalk, gutter or curb)?"},
    "car_depth": {"type": "score", "instructions": "How deep is the water a car driving in this lane would have to go through?",
                  "criteria": ["dry or damp road", "wet road, thin film of water", "puddles in the lane, below the tire tread",
                               "water over the tire sidewall, below the wheel hub",
                               "water at or above the wheel hub, stall risk for a car"]},
    "edges_hidden": {"type": "noul", "instructions":
        "Does the water hide the lane markings or the curb line, so a self-driving car could not tell where the road edge is?"},
}


_CLIENT = None


def judge_car(jpeg):
    """Decision 1 with CAR questions (not 'is it wet for a person')."""
    from gem.client import shared_beta_client
    _CLIENT = shared_beta_client()
    t0 = time.time()
    res = _CLIENT.decisions.create(
        model="models/gemini-decision-1",
        input=[{"type": "image", "data": base64.b64encode(jpeg).decode(), "mime_type": "image/jpeg"}],
        questions=CAR_QUESTIONS)
    a = res.answers
    lane, hidden = a["lane_covered"].noul, a["edges_hidden"].noul
    probs = {int(k): v for k, v in a["car_depth"].probabilities.items()}
    level = max(probs, key=probs.get)
    p_tire_or_worse = sum(v for k, v in probs.items() if k >= 3)
    action = "avoid" if (lane >= 0.6 and p_tire_or_worse >= 0.5) or (hidden >= 0.6 and lane >= 0.6) else (
        "slow" if lane >= 0.5 else "proceed")
    return {"lane_covered": round(lane, 3), "edges_hidden": round(hidden, 3),
            "depth_level": level, "depth_label": CAR_QUESTIONS["car_depth"]["criteria"][level],
            "p_tire_or_worse": round(p_tire_or_worse, 3), "action": action, "latency_ms": int((time.time() - t0) * 1000)}


def simulate(watch, chk, session_holder, settle_s=1.2, max_wait=25):
    """Genie 4 from the robotaxi roof camera at the watch block; Decision 1 car rubric on a simulated frame."""
    from gem.world import GenieSession
    photo = watch["photo"]
    with open(os.path.join(ROOT, photo["path"]), "rb") as f:
        img = f.read()
    peak = chk.get("peak") or {"mm": 0, "t": ""}
    prompt = (f"Forward-facing roof camera of a driverless robotaxi in the travel lane, approaching {watch['name']}, "
              f"San Francisco, at {peak['t'][11:16]} on 2026-11-18. {peak['mm']} mm of rain in one hour on saturated "
              f"streets; this intersection's roadway flooded in {watch['n_storm_days']} past storms. Show the water "
              f"across the driving lane and how high it reaches on the wheels of cars ahead. The robotaxi drives "
              f"forward slowly in its lane. Keep the real street layout from the reference photo.")
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
    verdict = judge_car(frame) if frame else {"action": "unknown"}
    path = os.path.join(ROOT, "media", "renders", f"sim_{watch['cell']}_{int(time.time())}.jpg")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if frame:
        with open(path, "wb") as f:
            f.write(frame)
    return {"verdict": verdict, "frame": os.path.relpath(path, ROOT) if frame else None,
            "genie_first_frame_s": round(s.first_frame_at - s.started_at, 1) if s.first_frame_at else None,
            "total_s": round(time.time() - t0, 1), "frames_seen": s.frame_no}


def reroute(p, here, t_now, excl):
    for keep in (len(excl), 4, 2):
        try:
            r = _route(here, p["to"], list(excl)[:keep], t_now)
            return _strip(r)
        except Exception:
            continue
    raise RuntimeError("router refused every exclusion set")


def proof(p, driven_coords, after_t, hours=3):
    """REAL street-flooding reports on the fastest route vs the route actually driven."""
    ev = [e for e in _j(f"events_{p['date']}.json", []) if e.get("where", "street") == "street"]
    end = (datetime.fromisoformat(after_t) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    fast_cells = {c for c, _, _ in _cells_on(p["fast"]["coords"])}
    drove_cells = {c for c, _, _ in _cells_on(driven_coords)}

    def pick(cs):
        return [e for e in ev if e["cell"] in cs and after_t <= e["t"] <= end]
    old, new = pick(fast_cells), pick(drove_cells)
    return {"window": [after_t, end], "old_route": old, "new_route": new, "old_n": len(old), "new_n": len(new)}


def check_auto(p, lead_min=3.5):
    """Pick the mid-ride moment: the newer forecast lands ~lead_min ride-minutes before the block to simulate."""
    first = check(p, 1, min_frac=0.5)
    w = first["watch"]
    if not w:
        return first
    times = p["route_a"]["times"]
    target = datetime.fromisoformat(w["eta"]) - timedelta(minutes=lead_min)
    idx = max(1, max((i for i, t in enumerate(times) if datetime.fromisoformat(t) <= target), default=1))
    out = check(p, idx, min_frac=0.5)
    if not out["watch"] or out["watch"]["cell"] != w["cell"]:
        out = {**first, "at_index": idx, "t": times[idx]}
    return out


DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["reroute", "keep_route"]},
        "confidence": {"type": "number"},
        "headline": {"type": "string"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "rider_message": {"type": "string"},
    },
    "required": ["action", "confidence", "headline", "reasons", "rider_message"],
}


def decide(ctx):
    """Gemini 4 Carbon makes the call autonomously (no human approval)."""
    from google.genai import types
    from gem.client import shared_client
    t0 = time.time()
    prompt = (
        "You are the autonomous driving policy of a robotaxi in San Francisco. Decide NOW, with no human, whether to "
        "reroute around the street ahead or keep the current route. Rider safety and not getting stranded in water "
        "outrank a few minutes of travel time. Use only the facts below; cite the numbers you rely on.\n\n"
        + json.dumps(ctx, indent=1))
    res = shared_client().models.generate_content(
        model="gemini-4-carbon", contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=DECISION_SCHEMA,
                                           thinking_config=types.ThinkingConfig(thinking_level="low")))
    out = json.loads(res.text)
    out["latency_ms"] = int((time.time() - t0) * 1000)
    out["model"] = "gemini-4-carbon"
    return out


def decide_pre_trip(fast, alt, risky, six_mm, fc):
    return decide({
        "moment": "before pickup: choose the route",
        "fastest_route": {"minutes": fast["min"], "street_flood_blocks_on_it": [
            {"street": r["name"], "past_storms_with_street_flooding": r["n_storm_days"], "latest": r["storm_days"][:3],
             "flood_threshold_6h_mm": r["thresh_mm_6h"], "reached_at": r["eta"][11:16]} for r in risky]},
        "flood_aware_route": {"minutes": alt["min"], "extra_minutes": round(alt["min"] - fast["min"], 1),
                              "flagged_blocks_crossed": 0},
        "forecast": {"source": fc.get("source"), "day_total_mm": fc.get("total_mm"), "six_hour_mm_by_8am": six_mm},
        "options": {"reroute": "take the flood-aware route", "keep_route": "take the fastest route"}})
