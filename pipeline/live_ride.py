"""LIVE mode: plan a real robotaxi ride for later today and look at the route through
live Caltrans cameras.

plan_live()      route for a ride at t (default: the next rainy hour today); scan it against
                 the LIVE Open-Meteo forecast + street-flood memory through today; find live
                 Caltrans cameras within ~600 m of the route.
camera_now()     fetch a camera's current frame (refreshed ~every 5 min) and judge it NOW with
                 the Decision 1 car rubric.
simulate_cam()   seed Genie 4 with that live frame and the forecast for the ETA at that spot;
                 Decision 1 judges the simulated view ("what it will look like when you get there").
"""
import json
import os
import time
import urllib.request
from datetime import datetime

from pipeline import ride, route as R
from pipeline.build import get_json, SF, TZ

ROOT = ride.ROOT
DATA = ride.DATA
CAM_RADIUS_M = 600
from zoneinfo import ZoneInfo
SF_TZ = ZoneInfo("America/Los_Angeles")  # the trip happens in SF, whatever the laptop clock says


def live_forecast():
    h = get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": SF[0], "longitude": SF[1], "hourly": "precipitation", "timezone": TZ, "forecast_days": 2})["hourly"]
    return [{"t": t, "mm": round(mm or 0.0, 2)} for t, mm in zip(h["time"], h["precipitation"])]


def next_rainy_hour(hours, now):
    later = [h for h in hours if h["t"] >= now[:13] + ":00"][:30]
    wet = [h for h in later if h["mm"] >= 0.3]
    return (max(wet[:8], key=lambda h: h["mm"]) if wet else later[0])["t"]


def _six(hours, t):
    hs = [h for h in hours if h["t"] <= t[:13] + ":00"][-6:]
    return round(sum(h["mm"] for h in hs), 1)


def plan_live(frm, to, t=None):
    now = datetime.now(SF_TZ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M")
    hours = live_forecast()
    t = t or next_rainy_hour(hours, now)
    cells = {c["id"]: c for c in ride._j("cells_street_live.json")["cells"]}
    fast = ride._route(frm, to, [], t, no_freeways=True)
    six = _six(hours, t)
    risky = ride._scan(fast, cells, six, 8, 0.1, 0.92)[:4]
    route_a = ride._route(frm, to, [r["cell"] for r in risky], t, no_freeways=True) if risky else fast
    pre = None
    if risky:
        day = [h for h in hours if h["t"][:10] == t[:10]]
        pre = ride.decide_pre_trip(fast, route_a, risky, six, {"source": "live Open-Meteo", "total_mm": round(sum(h["mm"] for h in day), 1)})
        if pre["action"] == "keep_route":
            route_a = fast
    cams = cams_near(route_a, fast)
    return {"now": now, "t": t, "from": frm, "to": to, "forecast": [h for h in hours if h["t"][:10] == t[:10]],
            "six_h_mm": six, "pre_decision": pre, "fast": ride._strip(fast), "route_a": ride._strip(route_a), "risky": risky, "cams": cams}


def cams_near(*routes):
    cams = ride._j("sf_cameras.json", [])
    out = {}
    for r in routes:
        for c in cams:
            if not c["in_service"]:
                continue
            k = min(range(len(r["coords"])), key=lambda i: ride._dist_m(r["coords"][i], (c["lat"], c["lon"])))
            d = ride._dist_m(r["coords"][k], (c["lat"], c["lon"]))
            if d <= CAM_RADIUS_M and (c["id"] not in out or d < out[c["id"]]["dist_m"]):
                out[c["id"]] = {**c, "dist_m": round(d), "eta": r["times"][k], "route_index": k}
    return sorted(out.values(), key=lambda c: c["eta"])


def _fetch(url):
    req = urllib.request.Request(url + f"?t={int(time.time())}", headers={"User-Agent": "flood-pullback-hackathon"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


_CLIENT = None


def is_real_view(img):
    """Reject 'Temporarily Unavailable' placeholders and broken frames before judging."""
    import base64
    from gem.client import shared_beta_client
    _CLIENT = shared_beta_client()
    a = _CLIENT.decisions.create(
        model="models/gemini-decision-1",
        input=[{"type": "image", "data": base64.b64encode(img).decode(), "mime_type": "image/jpeg"}],
        questions={"real": {"type": "noul", "instructions":
                   "Is this a real live camera view of a road (not a 'temporarily unavailable' or error placeholder, "
                   "not a blank or solid-color image)?"}}).answers
    return a["real"].noul


FREEWAY_QUESTIONS = {
    "lane_closed": {"type": "noul", "instructions":
        "Is any travel lane closed or blocked by cones, barriers, a construction zone, road workers, a flagger, "
        "or a police car directing traffic?"},
    "stopped_vehicle": {"type": "noul", "instructions":
        "Is a vehicle stopped or stalled in a travel lane (not just slow traffic)?"},
}


def freeway_check(img):
    """Hazards an automated car must know about BEFORE it enters a freeway segment."""
    import base64
    from gem.client import shared_beta_client
    a = shared_beta_client().decisions.create(
        model="models/gemini-decision-1",
        input=[{"type": "image", "data": base64.b64encode(img).decode(), "mime_type": "image/jpeg"}],
        questions=FREEWAY_QUESTIONS).answers
    return {"lane_closed": round(a["lane_closed"].noul, 3), "stopped_vehicle": round(a["stopped_vehicle"].noul, 3)}


def camera_now(cam):
    img = _fetch(cam["image"])
    os.makedirs(os.path.join(ROOT, "media", "frames", "caltrans"), exist_ok=True)
    path = os.path.join(ROOT, "media", "frames", "caltrans", f"{cam['id'].lower()}_{int(time.time())}.jpg")
    with open(path, "wb") as f:
        f.write(img)
    real = is_real_view(img)
    v = ride.judge_car(img) if real >= 0.5 else None
    fw = freeway_check(img) if real >= 0.5 else None
    if v and fw:
        v = {**v, **fw, "freeway_clear": fw["lane_closed"] < 0.5 and fw["stopped_vehicle"] < 0.5 and v["action"] == "proceed"}
    return {"cam": cam["id"], "name": cam["name"], "frame": os.path.relpath(path, ROOT), "available": real >= 0.5,
            "real_view_p": round(real, 3), "lat": cam["lat"], "lon": cam["lon"], "eta": cam.get("eta"), "dist_m": cam.get("dist_m"),
            "fetched_at": datetime.now(SF_TZ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%S"), "verdict": v}


def simulate_cam(cam, frame_path, eta, mm_eta, six_mm, session_holder, settle_s=1.2, max_wait=25):
    from gem.world import GenieSession
    with open(os.path.join(ROOT, frame_path), "rb") as f:
        img = f.read()
    prompt = (f"Live Caltrans traffic camera view of {cam['name'].split(' -- ')[-1]}, San Francisco. Show this same "
              f"camera view at {eta[11:16]} tonight, after {six_mm} mm of rain in the previous six hours and "
              f"{mm_eta} mm falling in that hour: wet asphalt, spray from tires, any standing water on the travel "
              f"lanes and shoulders, headlights in the rain. Keep the real road, lanes and buildings from the "
              f"reference frame. Traffic keeps moving.")
    t0 = time.time()
    s = GenieSession(img, prompt, max_seconds=30).start()
    session_holder["session"], session_holder["photo"] = s, {"zone": cam["name"], "path": frame_path}
    while s.status in ("starting", "warming") and time.time() - t0 < max_wait:
        time.sleep(0.1)
    t1 = time.time()
    while time.time() - t1 < settle_s and s.status == "live":
        time.sleep(0.1)
    frame = s.frame
    v = ride.judge_car(frame) if frame else {"action": "unknown"}
    path = os.path.join(ROOT, "media", "renders", f"live_{cam['id'].lower()}_{int(time.time())}.jpg")
    if frame:
        with open(path, "wb") as f:
            f.write(frame)
    return {"verdict": v, "frame": os.path.relpath(path, ROOT) if frame else None,
            "genie_first_frame_s": round(s.first_frame_at - s.started_at, 1) if s.first_frame_at else None,
            "total_s": round(time.time() - t0, 1)}
