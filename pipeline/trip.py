"""Plan a real robotaxi trip between ANY two San Francisco places, live.

plan()      geocode both places (OpenStreetMap Nominatim), fastest surface-street route,
            then flag every hazard on it:
              - flood NOTICES: real 311 street-flooding reports from the last 72 hours
              - flood MEMORY: streets that flooded in past storms, if the live forecast for the
                next 6 hours beats that street's flood threshold
              - lane CLOSURES: SFMTA-permitted closures active at departure
            Gemini 4 Carbon decides whether to take a route around the flagged blocks.
eyes()      live Caltrans camera frames near the route, judged by Decision 1 (now).
simulate()  Genie 4 renders the most dangerous flagged spot at the time the car would get
            there (seeded with a live camera frame if one is close, else a real street photo);
            Decision 1 judges it; Carbon makes the final call and the route is updated.
"""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from pipeline import ride, live_ride as LR, route as R

ROOT, DATA = ride.ROOT, ride.DATA
SF_BOX = "-122.52,37.83,-122.35,37.70"


def geocode(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q if "san francisco" in q.lower() else q + ", San Francisco", "format": "json", "limit": 1,
         "viewbox": SF_BOX, "bounded": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "flood-pullback-hackathon"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)
    if not d:
        raise ValueError(f"could not find '{q}' in San Francisco")
    return {"q": q, "lat": float(d[0]["lat"]), "lon": float(d[0]["lon"]),
            "label": ", ".join(d[0]["display_name"].split(", ")[:2])}


def notices(hours=72):
    """Real 311 street-flooding reports in the last `hours` (the city refreshes this feed daily)."""
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    q = urllib.parse.urlencode({"$select": "requested_datetime,address,lat,long,service_details,media_url",
                                "$where": f"lower(service_subtype)='flooding' AND requested_datetime > '{since}'",
                                "$limit": 2000})
    with urllib.request.urlopen(f"https://data.sf.gov/resource/vw6y-z8j6.json?{q}", timeout=60) as r:
        rows = json.load(r)
    out = []
    for x in rows:
        try:
            lat, lon = float(x["lat"]), float(x["long"])
        except (KeyError, TypeError, ValueError):
            continue
        if "property" in (x.get("service_details") or "").lower():
            continue  # basements/property: not a car problem
        m = x.get("media_url")
        out.append({"t": x["requested_datetime"][:16], "lat": lat, "lon": lon, "cell": R._cell(lat, lon),
                    "address": (x.get("address") or "").split(", SAN FRANCISCO")[0],
                    "photo": m if isinstance(m, str) else (m or {}).get("url")})
    return out


def _near_route(points, coords, m):
    pts = coords[::2]
    return [p for p in points if min(ride._dist_m(a, (p["lat"], p["lon"])) for a in pts) < m]


def plan(from_q, to_q, depart=None):
    a, b = geocode(from_q), geocode(to_q)
    depart = depart or datetime.now().strftime("%Y-%m-%dT%H:%M")
    hours = LR.live_forecast()
    cells = {c["id"]: c for c in ride._j("cells_street_live.json")["cells"]}
    fast = ride._route([a["lat"], a["lon"]], [b["lat"], b["lon"]], [], depart, no_freeways=True)
    six = LR._six(hours, (datetime.fromisoformat(depart) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"))

    # 1) flood notices from the last 72 h, on the route
    nts = _near_route(notices(), fast["coords"], 45)
    # 2) flood memory under tonight's forecast
    mem = ride._scan(fast, cells, max(six, 0.1), 6, 0.0, 1.0)
    # 3) lane closures active around departure
    cl = ride.closures_near(fast["coords"], ride.closures(depart[:10], depart, fast["times"][-1]))

    flags = {}
    for n in nts:
        f = flags.setdefault(n["cell"], {"cell": n["cell"], "lat": n["lat"], "lon": n["lon"], "name": n["address"],
                                         "notices": [], "n_storm_days": cells.get(n["cell"], {}).get("n_storm_days", 0)})
        f["notices"].append(n)
    for m in mem:
        f = flags.setdefault(m["cell"], {"cell": m["cell"], "lat": m["lat"], "lon": m["lon"], "name": m["name"], "notices": []})
        f["n_storm_days"] = m["n_storm_days"]
        f["storm_days"] = m["storm_days"][:3]
    for f in flags.values():
        f["score"] = 3 * len(f["notices"]) + f.get("n_storm_days", 0)
    flagged = sorted(flags.values(), key=lambda f: -f["score"])[:8]

    # blocks to avoid: flagged flood spots + streets with ALL lanes closed (never the pickup/drop-off blocks)
    ends = set()
    for la, lo in ((a["lat"], a["lon"]), (b["lat"], b["lon"])):
        r_, c_ = (int(x[1:]) for x in R._cell(la, lo).split("_"))
        ends |= {f"r{r_+dr}_c{c_+dc}" for dr in (-2, -1, 0, 1, 2) for dc in (-2, -1, 0, 1, 2)}
    closed_cells = {R._cell(la, lo) for c in cl if c["impact"] == "all-lanes-closed" for la, lo in R._densify(c["line"], 30)}
    avoid = [f["cell"] for f in flagged] + sorted(closed_cells - ends)
    route_a = fast
    if flagged or closed_cells:
        for keep in (len(avoid), 10, 5):
            try:
                route_a = ride._route([a["lat"], a["lon"]], [b["lat"], b["lon"]], [x for x in avoid if x not in ends][:keep], depart, no_freeways=True)
                break
            except Exception:
                continue
    pre = None
    if flagged or closed_cells:
        pre = ride.decide({
            "moment": "before pickup: choose the route for a real trip",
            "trip": {"from": a["label"], "to": b["label"], "depart": depart},
            "fastest_route": {"minutes": fast["min"], "flagged_spots": [
                {"street": f["name"], "flood_reports_last_72h": len(f["notices"]), "past_storms_with_street_flooding": f.get("n_storm_days", 0)}
                for f in flagged]},
            "lane_closures_on_fastest_route": [{k: c[k] for k in ("street", "from", "to", "impact")} for c in cl][:6],
            "alternative_route": {"minutes": route_a["min"], "extra_minutes": round(route_a["min"] - fast["min"], 1)},
            "live_forecast": {"next_6h_mm": six},
            "options": {"reroute": "take the alternative route", "keep_route": "take the fastest route"}})
        if pre["action"] == "keep_route":
            route_a = fast
    cams = LR.cams_near(route_a, fast)
    try:
        allnt = [{k: n[k] for k in ("t", "lat", "lon", "address")} for n in notices()]
    except Exception:
        allnt = []
    try:
        n_closed_today = len(ride.closures(depart[:10], depart, depart[:10] + "T23:59"))
    except Exception:
        n_closed_today = 0
    return {"from": a, "to": b, "depart": depart, "notices_all": allnt, "closures_today": n_closed_today,
            "rain_today_mm": round(sum(h["mm"] for h in hours if h["t"][:10] == depart[:10]), 1), "forecast": [h for h in hours if h["t"] >= depart[:13] + ":00"][:8],
            "six_h_mm": six, "fast": ride._strip(fast), "route": ride._strip(route_a), "pre_decision": pre,
            "notices": nts, "memory": mem, "closures": cl, "flagged": flagged, "cams": cams, "avoid_cells": avoid,
            "_route_dist": route_a.get("dist")}


def simulate(p, cams_now, session_holder):
    """Genie 4 at the most dangerous flagged spot, at the car's ETA; Carbon makes the final call."""
    target = p["flagged"][0] if p["flagged"] else None
    route = p["route"]
    if not target:
        return {"skipped": True, "reason": "nothing flagged on this route"}
    k = min(range(len(p["fast"]["coords"])), key=lambda i: ride._dist_m(p["fast"]["coords"][i], (target["lat"], target["lon"])))
    eta = p["fast"]["times"][k]
    online = [c for c in cams_now if c.get("available")]
    cam = min(online, key=lambda c: ride._dist_m((c["lat"], c["lon"]), (target["lat"], target["lon"])), default=None)
    if cam and ride._dist_m((cam["lat"], cam["lon"]), (target["lat"], target["lon"])) < 700:
        seed_path, seed = cam["frame"], {"kind": "live camera", "label": cam["name"].split(" -- ")[-1], "t": cam["fetched_at"]}
    else:
        ph = ride._car_photo("2026-11-18", target["lat"], target["lon"])
        seed_path, seed = ph["path"], {"kind": "real 311 photo", "label": ph["address"], "t": ph["t"], "dist_m": ph["dist_m"]}
    mm = next((h["mm"] for h in p["forecast"] if h["t"][:13] == eta[:13]), 0)
    from gem.world import GenieSession
    with open(os.path.join(ROOT, seed_path), "rb") as f:
        img = f.read()
    prompt = (f"Forward-facing roof camera of a driverless robotaxi in the travel lane, approaching {target['name'].title()}, "
              f"San Francisco, at {eta[11:16]}. {p['six_h_mm']} mm of rain over six hours, {mm} mm in that hour. "
              f"{len(target['notices'])} street-flooding reports here in the last 3 days; it flooded in "
              f"{target.get('n_storm_days', 0)} past storms. Show the water on the driving lane and how high it reaches "
              f"on car wheels. Keep the real street layout from the reference image. The car drives forward slowly.")
    t0 = time.time()
    s, frame, first_s = None, None, None
    try:
        s = GenieSession(img, prompt, max_seconds=30).start()
        session_holder["session"], session_holder["photo"] = s, {"zone": target["name"], "path": seed_path}
        while s.status in ("starting", "warming") and time.time() - t0 < 25:
            time.sleep(0.1)
        if s.status == "live":
            s.send_key("key_down", "key_w")
            time.sleep(1.2)
            frame = s.frame
        first_s = round(s.first_frame_at - s.started_at, 1) if s.first_frame_at else None
    except Exception:
        frame = None
    finally:
        if s:
            try:
                s.stop()
            except Exception:
                pass
    try:
        v = ride.judge_car(frame or img)
    except Exception:
        v = {"action": "slow", "depth_label": "simulated check unavailable (seed fallback)", "lane_covered": 0.5, "p_tire_or_worse": 0.25, "edges_hidden": 0.2}
    out_path = None
    if frame:
        os.makedirs(os.path.join(ROOT, "media", "renders"), exist_ok=True)
        out_path = os.path.join("media", "renders", f"trip_{target['cell']}_{int(time.time())}.jpg")
        with open(os.path.join(ROOT, out_path), "wb") as f:
            f.write(frame)
    dec = ride.decide({
        "moment": "final check before the car reaches the most dangerous spot",
        "spot": target["name"], "reached_at": eta[11:16],
        "flood_reports_last_72h": [{"t": n["t"], "address": n["address"]} for n in target["notices"]][:5],
        "past_storms_with_street_flooding": target.get("n_storm_days", 0),
        "forecast_mm_that_hour": mm, "six_hour_mm": p["six_h_mm"],
        "live_cameras_now": [{"camera": c["name"], **(c.get("verdict") or {})} for c in online][:4],
        "genie4_simulation_judged_by_decision1": v, "simulation_seed": seed,
        "current_plan": "route avoids the flagged spots" if p["route"]["coords"] != p["fast"]["coords"] else "fastest route",
        "options": {"reroute": "avoid this spot (take or keep the flood-aware route)", "keep_route": "the current plan is fine"}})
    return {"target": target, "eta": eta, "mm_eta": mm, "seed": seed, "seed_path": seed_path, "verdict": v, "frame": out_path,
            "genie_first_frame_s": first_s, "total_s": round(time.time() - t0, 1), "decision": dec}
