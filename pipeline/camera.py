"""C6: car camera -> Decision 1 flood judge -> Managed Agent -> camera zone.

POST /api/camera {image_b64, lat, lon, car_id, t?, date?}
  -> verdict now (~0.6 s); if flooded, the Managed Agent runs in the background
     (~20 s) and appends a zone (source "camera") to data/camera_zones_<date>.json.
     Camera zones are auto-applied (status "approved") so every car avoids the street
     at once; the ops manager can reject them on the map.
GET /api/camera/incidents?date= -> incidents with the agent's tool steps.
"""
import base64
import json
import math
import os
import threading
import time
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
GRID = {"lat0": 37.70, "lon0": -122.52, "dlat": 0.0015, "dlon": 0.0019}
FLOOD_P = 0.8
LOCK = threading.Lock()
INCIDENTS = {}  # id -> incident dict


def _cell(lat, lon):
    return f"r{math.floor((lat - GRID['lat0']) / GRID['dlat'])}_c{math.floor((lon - GRID['lon0']) / GRID['dlon'])}"


def _zones_path(date):
    return os.path.join(DATA, f"camera_zones_{date}.json")


def _load(date):
    try:
        with open(_zones_path(date)) as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def _jsonable(x):
    try:
        json.dumps(x)
        return x
    except TypeError:
        return str(x)


def _run_agent(inc):
    from gem import agent
    try:
        steps = agent.run_incident(inc["verdict"])
        inc["steps"] = [{"tool": s.get("tool"), "args": _jsonable(s.get("args")), "result": _jsonable(s.get("result"))}
                        for s in steps]
        zone = dict(steps[-1]["result"])
        zone.update({"id": f"cam_{inc['id']}", "source": "camera", "status": "approved",
                     "car_id": inc["verdict"]["car_id"], "seen_at": inc["verdict"]["t"],
                     "flooded_p": inc["verdict"]["flooded_p"], "depth_label": inc["verdict"]["depth_label"]})
        zone.setdefault("name", f"Camera report near {inc['verdict']['cell']}")
        with LOCK:
            zs = _load(inc["date"])
            zs.append(zone)
            with open(_zones_path(inc["date"]), "w") as f:
                json.dump(zs, f)
        inc.update(status="zone_added", zone=zone, agent_s=round(time.time() - inc["started"], 1))
    except Exception as e:
        inc.update(status="error", error=f"{type(e).__name__}: {str(e)[:300]}")


def handle(b):
    from gem import vision
    date = b.get("date", "2026-11-18")
    lat, lon = float(b["lat"]), float(b["lon"])
    jpeg = base64.b64decode(b["image_b64"].split(",")[-1])
    v = vision.judge_frame(jpeg)
    cell = _cell(lat, lon)
    verdict = {**v, "car_id": b.get("car_id", "W-112"), "lat": lat, "lon": lon, "cell": cell,
               "t": b.get("t") or f"{date}T10:00", "date": date}
    out = {"verdict": verdict, "incident": None}
    if v["flooded_p"] < FLOOD_P:
        return out
    with LOCK:
        busy = next((i for i in INCIDENTS.values() if i["verdict"]["cell"] == cell and i["status"] == "running"), None)
        known = any(cell in z.get("cells", []) for z in _load(date))
        if busy or known:
            out["incident"] = {"id": busy["id"] if busy else None, "status": "already_reported"}
            return out
        inc = {"id": uuid.uuid4().hex[:6], "date": date, "verdict": verdict, "status": "running",
               "started": time.time(), "steps": []}
        INCIDENTS[inc["id"]] = inc
    threading.Thread(target=_run_agent, args=(inc,), daemon=True).start()
    out["incident"] = {"id": inc["id"], "status": "running"}
    return out


def incidents(date):
    return sorted(({k: v for k, v in i.items()} for i in INCIDENTS.values() if i["date"] == date),
                  key=lambda i: -i["started"])


def reset(date):
    with LOCK:
        try:
            os.remove(_zones_path(date))
        except FileNotFoundError:
            pass
        for k in [k for k, i in INCIDENTS.items() if i["date"] == date]:
            INCIDENTS.pop(k)
