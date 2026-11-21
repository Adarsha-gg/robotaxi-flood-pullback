"""Flood Pull-Back server (standard library only).

  GET  /                      -> web/index.html
  GET  /web/*, /data/*        -> static files
  GET  /api/zones?date=&set=  -> zones (set = carbon | baseline), with approvals applied
  POST /api/zones/approve     -> {date, set, zone_id, status}
  GET  /api/score?date=&set=  -> score card (approved zones only)       [C4]
  POST /api/route             -> default vs safe route                  [C5]
  POST /api/camera            -> frame verdict + camera zone            [C6]

Run: .venv/bin/python server.py  (http://localhost:8000)
"""
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
PORT = int(os.environ.get("PORT", 8000))
LOCK = threading.Lock()
GENIE = {"session": None, "photo": None}
RIDE = {}  # one live Genie 4 world at a time (cost cap)


def pick_photo(date, zone):
    """Real 311 resident photo from inside the zone, else the nearest one to it."""
    photos = read_json(os.path.join(DATA, f"photos_{date}.json")) or read_json(os.path.join(DATA, "photos_2026-11-18.json"), [])
    photos = [p for p in photos if os.path.exists(os.path.join(ROOT, p["path"]))]
    if not photos:
        return None
    # skip photos that make bad Genie seeds (window decal, balcony, screen, gate, indoor garage)
    bad = ("235 GOUGH", "880 5TH", "500 PIERCE", "1931 EVANS", "340 6TH")
    photos = [p for p in photos if not p["address"].upper().startswith(bad)] or photos
    inside = [p for p in photos if zone and p["cell"] in set(zone["cells"])]
    if inside:
        return inside[0]
    if not zone:
        return photos[0]
    g = read_json(os.path.join(DATA, "cells.json"))["grid"]
    rc = [tuple(int(x[1:]) for x in c.split("_")) for c in zone["cells"]]
    lat = g["lat0"] + (sum(r for r, _ in rc) / len(rc) + 0.5) * g["dlat"]
    lon = g["lon0"] + (sum(c for _, c in rc) / len(rc) + 0.5) * g["dlon"]
    return min(photos, key=lambda p: (p["lat"] - lat) ** 2 + ((p["lon"] - lon) * 0.79) ** 2)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def zones_path(date, zset):
    return os.path.join(DATA, f"zones_{date}.json" if zset == "carbon" else f"zones_{date}_baseline.json")


def approvals_path(date, zset):
    return os.path.join(DATA, f"approvals_{date}_{zset}.json")


def load_zones(date, zset):
    z = read_json(zones_path(date, zset))
    if z is None:
        return None
    z["zones"] += read_json(os.path.join(DATA, f"camera_zones_{date}.json"), [])
    ap = read_json(approvals_path(date, zset), {})  # apply AFTER camera zones so they can be rejected too
    for zone in z["zones"]:
        if zone["id"] in ap:
            zone["status"] = ap[zone["id"]]
    return z


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):
        if "/api/" in self.path:
            super().log_message(fmt, *args)

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body_json(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            self.path = "/web/index.html"
            return super().do_GET()
        if u.path == "/api/zones":
            date, zset = q.get("date", "2026-11-18"), q.get("set", "carbon")
            z = load_zones(date, zset)
            if z is None and zset == "carbon":
                z, zset = load_zones(date, "baseline"), "baseline"
            if z is None:
                return self.send_json({"error": "no zones"}, 404)
            z["set"] = zset
            return self.send_json(z)
        if u.path == "/api/camera/incidents":
            from pipeline.camera import incidents
            return self.send_json(incidents(q.get("date", "2026-11-18")))
        if u.path in ("/ride", "/ride.html"):
            self.path = "/web/ride.html"
            return super().do_GET()
        if u.path in ("/cam", "/cam.html"):
            self.path = "/web/cam.html"
            return super().do_GET()
        if u.path == "/api/genie/status":
            s = GENIE["session"]
            return self.send_json({"photo": GENIE["photo"], **(s.info() if s else {"status": "idle"})})
        if u.path == "/api/genie/stream":
            s = GENIE["session"]
            if not s:
                return self.send_error(404)
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = -1
            try:
                while GENIE["session"] is s and s.status not in ("stopped", "error"):
                    frame, last = s.wait_frame(last)
                    if frame is None:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        if u.path == "/api/score":
            from pipeline.score import score
            return self.send_json(score(q.get("date", "2026-11-18"), q.get("set", "carbon")))
        if u.path.startswith(("/web/", "/data/", "/media/")) and ".." not in u.path:
            return super().do_GET()
        self.send_error(404)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            b = self.body_json()
        except Exception:
            return self.send_json({"error": "bad json"}, 400)
        if u.path == "/api/zones/approve":
            date, zset = b.get("date", "2026-11-18"), b.get("set", "carbon")
            if b.get("status") not in ("proposed", "approved", "rejected"):
                return self.send_json({"error": "bad status"}, 400)
            with LOCK:
                path = approvals_path(date, zset)
                ap = read_json(path, {})
                ids = b["zone_ids"] if "zone_ids" in b else [b["zone_id"]]
                for zid in ids:
                    ap[zid] = b["status"]
                with open(path, "w") as f:
                    json.dump(ap, f)
            return self.send_json({"ok": True, "updated": len(ids)})
        if u.path == "/api/ride/plan":
            from pipeline import ride
            p = ride.plan(b.get("from", [37.7800, -122.4650]), b.get("to", [37.7765, -122.3946]),
                          b.get("t", "2026-11-18T08:58"), b.get("date", "2026-11-18"))
            RIDE.clear()
            RIDE["plan"] = p
            return self.send_json({k: v for k, v in p.items() if not k.startswith("_")})
        if u.path == "/api/ride/check":
            from pipeline import ride
            RIDE["check"] = ride.check_auto(RIDE["plan"])
            return self.send_json(RIDE["check"])
        if u.path == "/api/ride/simulate":
            from pipeline import ride
            c = RIDE.get("check")
            if not c or not c.get("watch"):
                return self.send_json({"error": "no block to simulate"}, 400)
            if GENIE["session"]:
                GENIE["session"].stop()
            try:
                return self.send_json(ride.simulate(c["watch"], c, GENIE))
            except Exception as e:
                return self.send_json({"error": f"{type(e).__name__}: {str(e)[:300]}"}, 500)
        if u.path == "/api/ride/reroute":
            from pipeline import ride
            p, c = RIDE["plan"], RIDE.get("check") or {"risky_b": []}
            if GENIE["session"]:
                GENIE["session"].stop()
            excl = [r["cell"] for r in p["risky_a"]] + [r["cell"] for r in c["risky_b"]]
            here, idx = b["here"], int(b.get("index", c.get("at_index", 0)))
            route_b = ride.reroute(p, here, b["t"], excl)
            driven = p["route_a"]["coords"][:idx + 1] + route_b["coords"]
            return self.send_json({"route_b": route_b, "proof": ride.proof(p, driven, p["t"])})
        if u.path == "/api/genie/start":
            from gem.world import GenieSession, DEFAULT_PROMPT
            date, zset = b.get("date", "2026-11-18"), b.get("set", "carbon")
            zone = None
            if b.get("zone_id"):
                zf = load_zones(date, zset) or load_zones(date, "baseline") or {"zones": []}
                zone = next((z for z in zf["zones"] if z["id"] == b["zone_id"]), None)
            photo = pick_photo(date, zone)
            if not photo:
                return self.send_json({"error": "no 311 photos; run python -m pipeline.fetch_photos"}, 404)
            if GENIE["session"]:
                GENIE["session"].stop()
            place = zone["name"] if zone else photo["address"]
            prompt = (f"Street-level view from a driverless robotaxi at {photo['address']}, San Francisco, during the "
                      f"2026-11-18 storm (photo taken {photo['t'][11:16]}). Heavy rain, runoff flooding the roadway and "
                      f"rising toward the curb. Keep the real street from the reference photo. The car drives slowly.")
            with open(os.path.join(ROOT, photo["path"]), "rb") as f:
                GENIE["session"] = GenieSession(f.read(), prompt, max_seconds=float(b.get("max_seconds", 60))).start()
            GENIE["photo"] = {**photo, "zone": place}
            return self.send_json({"ok": True, "photo": GENIE["photo"]})
        if u.path == "/api/genie/key":
            s = GENIE["session"]
            if not s:
                return self.send_json({"error": "no session"}, 404)
            try:
                s.send_key(b.get("action"), b.get("key"))
            except ValueError as e:
                return self.send_json({"error": str(e)}, 400)
            return self.send_json({"ok": True})
        if u.path == "/api/genie/stop":
            s = GENIE["session"]
            if not s:
                return self.send_json({"ok": True})
            s.stop()
            out = {"ok": True, **s.info()}
            if b.get("save") and s.frames:
                import time as _t
                path = os.path.join(ROOT, "media", "renders", f"genie_live_{int(_t.time())}.mp4")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                s.save_mp4(path)
                out["path"] = os.path.relpath(path, ROOT)
            return self.send_json(out)
        if u.path == "/api/route":
            from pipeline.route import route
            return self.send_json(route(b, load_zones))
        if u.path == "/api/camera":
            from pipeline.camera import handle
            try:
                return self.send_json(handle(b))
            except Exception as e:
                return self.send_json({"error": f"{type(e).__name__}: {str(e)[:300]}"}, 500)
        if u.path == "/api/camera/reset":
            from pipeline.camera import reset
            reset(b.get("date", "2026-11-18"))
            return self.send_json({"ok": True})
        self.send_error(404)


if __name__ == "__main__":
    print(f"Flood Pull-Back on http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
