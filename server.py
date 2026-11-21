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
    ap = read_json(approvals_path(date, zset), {})
    for zone in z["zones"]:
        if zone["id"] in ap:
            zone["status"] = ap[zone["id"]]
    extra = read_json(os.path.join(DATA, f"camera_zones_{date}.json"), [])
    z["zones"] += extra
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
        if u.path == "/api/route":
            from pipeline.route import route
            return self.send_json(route(b, load_zones))
        if u.path == "/api/camera":
            from pipeline.camera import handle
            return self.send_json(handle(b))
        self.send_error(404)


if __name__ == "__main__":
    print(f"Flood Pull-Back on http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
