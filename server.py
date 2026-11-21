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
from datetime import datetime, timedelta
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
PORT = int(os.environ.get("PORT", 8000))
LOCK = threading.Lock()
GENIE = {"session": None, "photo": None}
FLEET = {"run": 0, "steps": [], "done": True, "zone": None, "error": None}
RIDE = {}
LIVE = {}
TRIP = {}  # one live Genie 4 world at a time (cost cap)


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
    for zone in z["zones"]:  # autonomous: every zone the models produce is active immediately (no human approval)
        zone["status"] = "approved"
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
        if u.path in ("/", "/ride", "/ride.html") and False:
            pass
        if u.path == "/":
            self.path = "/web/ride.html"
            return super().do_GET()
        if u.path in ("/ops", "/index.html"):
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
        if u.path in ("/trip", "/trip.html"):
            self.path = "/web/trip.html"
            return super().do_GET()
        if u.path in ("/ride", "/ride.html"):
            self.path = "/web/ride.html"
            return super().do_GET()
        if u.path in ("/cam", "/cam.html"):
            self.path = "/web/cam.html"
            return super().do_GET()
        if u.path == "/api/fleet/status":
            z = FLEET["zone"] or {}
            return self.send_json({"run": FLEET["run"], "done": FLEET["done"], "error": FLEET["error"],
                                   "steps": [{"tool": x.get("tool"), "args": x.get("args")} for x in FLEET["steps"]],
                                   "zone": {k: z.get(k) for k in ("name", "polygon", "start", "end", "p_flood", "fleet_notice", "reason", "agent_engine", "cells")} if z else None})
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
                          b.get("t", "2026-11-18T09:50"), b.get("date", "2026-11-18"))
            RIDE.clear()
            RIDE["plan"] = p
            return self.send_json({k: v for k, v in p.items() if not k.startswith("_")})
        if u.path == "/api/ride/presim":
            from pipeline import ride
            pw = RIDE["plan"].get("pre_watch")
            if not pw:
                return self.send_json({"error": "no spot to simulate"}, 400)
            if GENIE["session"]:
                GENIE["session"].stop()
            try:
                RIDE["presim"] = ride.simulate(pw, {"t": RIDE["plan"]["t"], "peak": {"t": pw["eta"], "mm": pw["forecast_at_eta"]["mm"]},
                                                    "six_h_mm": pw["forecast_at_eta"]["six_h_mm"]}, GENIE)
                return self.send_json(RIDE["presim"])
            except Exception as e:
                return self.send_json({"error": f"{type(e).__name__}: {str(e)[:300]}"}, 500)
        if u.path == "/api/ride/predecide":
            from pipeline import ride
            if GENIE["session"]:
                GENIE["session"].stop()
            out = ride.pre_decide(RIDE["plan"], RIDE.get("presim"))
            RIDE.pop("check", None); RIDE.pop("proof", None)
            return self.send_json({"decision": out["decision"], "route_a": {k: v for k, v in out["route_a"].items() if k != "dist"}})
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
                RIDE["sim"] = ride.simulate(c["watch"], c, GENIE)
                return self.send_json(RIDE["sim"])
            except Exception as e:
                return self.send_json({"error": f"{type(e).__name__}: {str(e)[:300]}"}, 500)
        if u.path == "/api/ride/reroute":
            from pipeline import ride
            p, c = RIDE["plan"], RIDE.get("check") or {"risky_b": []}
            if GENIE["session"]:
                GENIE["session"].stop()
            excl = [r["cell"] for r in p["risky_a"]] + [x["cell"] for x in p.get("live_a", [])] + ([p["pre_watch"]["cell"]] if p.get("pre_watch") else []) + [r["cell"] for r in c["risky_b"]]
            here, idx = b["here"], int(b.get("index", c.get("at_index", 0)))
            route_b = ride.reroute(p, here, b["t"], excl)
            rest_a_min = round((datetime.fromisoformat(p["route_a"]["times"][-1]) - datetime.fromisoformat(b["t"])).total_seconds() / 60, 1)
            w, sim = c.get("watch") or {}, (RIDE.get("sim") or {}).get("verdict")
            dec = ride.decide({
                "moment": "mid-ride: newer forecast arrived; car is slowing while it decides",
                "street_ahead": w.get("name"), "reached_at": (w.get("eta") or "")[11:16], "now": b["t"][11:16],
                "street_flood_history": {"past_storms_with_street_flooding": w.get("n_storm_days"), "latest": (w.get("storm_days") or [])[:3]},
                "live_311_street_flood_reports_within_500m_so_far_today": [{"time": e["t"][11:16], "address": e["address"]} for e in (w.get("live_near") or [])][-6:],
                "permitted_lane_closures_here": [{k: x[k] for k in ("street", "from", "to", "impact", "type", "start", "end")} for x in (w.get("closures") or [])],
                "forecast": {"source": c.get("forecast_source"), "next_hour_mm": (c.get("peak") or {}).get("mm"), "six_hour_mm": c.get("six_h_mm")},
                "genie4_simulation_judged_by_decision1": sim,
                "current_route_remaining_minutes": rest_a_min,
                "alternative_route": {"minutes": route_b["min"], "eta_change_min": round(route_b["min"] - rest_a_min, 1), "flagged_blocks_crossed": 0},
                "options": {"reroute": "switch to the alternative route now", "keep_route": "stay on the current route"}})
            final = route_b if dec["action"] == "reroute" else {**p["route_a"], "coords": p["route_a"]["coords"][idx:], "times": p["route_a"]["times"][idx:]}
            # deterministic proof: the reroute as planned from a fixed point (check time + 2 min), so the
            # number on screen is the same every run regardless of animation timing
            proof = RIDE.get("proof")
            if not proof:
                times = p["route_a"]["times"]
                fx = next((i for i, t in enumerate(times) if t >= (datetime.fromisoformat(c["t"]) + timedelta(minutes=2)).isoformat()), idx)
                planned = ride.reroute(p, p["route_a"]["coords"][fx], times[fx], excl) if dec["action"] == "reroute" else {"coords": p["route_a"]["coords"][fx:]}
                proof = ride.proof(p, p["route_a"]["coords"][:fx + 1] + planned["coords"], p["t"])
                bt = read_json(os.path.join(ROOT, "media", "backtest.json"), {}) or {}
                proof["backtest"] = bt.get("one_liner")
                RIDE["proof"] = proof
            return self.send_json({"route_b": final, "decision": dec, "proof": proof})
        if u.path == "/api/trip/plan":
            from pipeline import trip
            try:
                p = trip.plan(b.get("from", "Noe Valley"), b.get("to", "Moscone Center"), b.get("depart"))
            except Exception as e:
                return self.send_json({"error": f"{type(e).__name__}: {str(e)[:200]}"}, 400)
            TRIP.clear()
            TRIP["plan"] = p
            return self.send_json({k: v for k, v in p.items() if not k.startswith("_")})
        if u.path == "/api/trip/eyes":
            from concurrent.futures import ThreadPoolExecutor
            from pipeline import live_ride as LR, trip
            cams = TRIP["plan"]["cams"][:8]
            def safe(c):
                try:
                    return LR.camera_now(c)
                except Exception as e:
                    return {"cam": c["id"], "name": c["name"], "available": False, "frame": "", "error": str(e)[:120]}
            with ThreadPoolExecutor(6) as ex:
                TRIP["cams"] = list(ex.map(safe, cams))
            tgt, cam, ph = trip.pick_sim(TRIP["plan"], TRIP["cams"])
            return self.send_json({"cams": TRIP["cams"], "sim_target": tgt and tgt["cell"], "sim_target_obj": tgt,
                                   "sim_cam": cam and cam["cam"], "sim_cam_dist": cam and cam["dist_m"],
                                   "sim_photo": ph and {"path": ph["path"], "address": ph["address"], "t": ph["t"], "dist_m": ph["dist_m"]}})
        if u.path == "/api/trip/simulate":
            from pipeline import trip
            if GENIE["session"]:
                GENIE["session"].stop()
            try:
                out = trip.simulate(TRIP["plan"], TRIP.get("cams", []), GENIE)
                if GENIE["session"]:
                    GENIE["session"].stop()
                TRIP["sim"] = out
                return self.send_json({k: v for k, v in out.items() if k != "online_cams"})
            except Exception as e:
                return self.send_json({"error": f"{type(e).__name__}: {str(e)[:300]}"}, 500)
        if u.path == "/api/trip/decide":
            from pipeline import trip
            try:
                return self.send_json(trip.decide_mid(TRIP["plan"], TRIP["sim"], b["here"], b["t"], int(b["index"])))
            except Exception as e:
                return self.send_json({"error": f"{type(e).__name__}: {str(e)[:300]}"}, 500)
        if u.path == "/api/live/plan":
            from pipeline import live_ride as LR
            p = LR.plan_live(b.get("from", [37.7502, -122.4337]), b.get("to", [37.7840, -122.4010]), b.get("t"))
            LIVE.clear()
            LIVE["plan"] = p
            return self.send_json(p)
        if u.path == "/api/live/cams":
            from concurrent.futures import ThreadPoolExecutor
            from pipeline import live_ride as LR
            cams = LIVE["plan"]["cams"][:6]
            def safe(c):
                try:
                    return LR.camera_now(c)
                except Exception as e:
                    return {"cam": c["id"], "name": c["name"], "available": False, "frame": "", "error": str(e)[:120]}
            with ThreadPoolExecutor(6) as ex:
                res = list(ex.map(safe, cams))
            LIVE["cams"] = res
            return self.send_json(res)
        if u.path == "/api/live/simulate":
            from pipeline import live_ride as LR
            p = LIVE["plan"]
            cam = next(c for c in LIVE["cams"] if c["cam"] == b["cam"])
            meta = next(c for c in p["cams"] if c["id"] == b["cam"])
            mm = next((h["mm"] for h in p["forecast"] if h["t"][:13] == cam["eta"][:13]), 0)
            if GENIE["session"]:
                GENIE["session"].stop()
            try:
                sim = LR.simulate_cam(meta, cam["frame"], cam["eta"], mm, p["six_h_mm"], GENIE)
                from pipeline import ride
                sim["decision"] = ride.decide({
                    "moment": "planning tonight's ride; decide whether the route past this camera is safe",
                    "camera": cam["name"], "camera_now": {"fetched_at": cam["fetched_at"], **(cam["verdict"] or {})},
                    "car_passes_camera_at": cam["eta"][11:16], "forecast_mm_that_hour": mm, "six_hour_mm": p["six_h_mm"],
                    "genie4_simulation_at_eta_judged_by_decision1": sim["verdict"],
                    "route_already_avoids": [r["name"] for r in p["risky"]],
                    "options": {"reroute": "avoid the streets near this camera tonight", "keep_route": "keep the planned route"}})
                if GENIE["session"]:
                    GENIE["session"].stop()
                return self.send_json(sim)
            except Exception as e:
                return self.send_json({"error": f"{type(e).__name__}: {str(e)[:300]}"}, 500)
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
        if u.path == "/api/fleet/start":
            # Antigravity Managed Agent: takes this car's simulated street and decides what the whole fleet avoids
            import threading
            FLEET.update(run=FLEET["run"] + 1, steps=[], done=False, zone=None, error=None)
            run_id = FLEET["run"]

            def work():
                from gem.agent import run_incident
                try:
                    steps = run_incident(b, on_step=lambda st: FLEET["run"] == run_id and FLEET["steps"].append(st))
                    if FLEET["run"] == run_id:
                        FLEET["steps"] = steps
                        FLEET["zone"] = steps[-1]["result"] if steps and isinstance(steps[-1].get("result"), dict) else None
                except Exception as e:
                    FLEET["error"] = f"{type(e).__name__}: {str(e)[:200]}"
                finally:
                    if FLEET["run"] == run_id:
                        FLEET["done"] = True
            threading.Thread(target=work, daemon=True).start()
            return self.send_json({"ok": True, "run": run_id})
        if u.path == "/api/voice":
            from gem.voice import synthesize
            out = synthesize(str(b.get("text", ""))[:400], os.path.join(ROOT, "media", "audio", "rider_live.wav"))
            if not out.get("ok"):
                return self.send_json({"error": out.get("error") or "tts failed"}, 502)
            return self.send_json({"path": "media/audio/rider_live.wav", "latency_ms": out.get("latency_ms")})
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
