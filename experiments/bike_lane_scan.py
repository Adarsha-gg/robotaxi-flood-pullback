"""Scan every online Manhattan NYC DOT camera with Decision 1.

Asks: is a bike lane visible, and is a vehicle stopped in it?
Saves frames for likely hits to hits/ and a summary to scan_results.json.
"""
import base64
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from google import genai

load_dotenv()
beta = genai.Client(http_options={"api_version": "v1beta"})
AREA = sys.argv[1] if len(sys.argv) > 1 else "Manhattan"

QUESTIONS = {
    "bike_lane_visible": {
        "type": "noul",
        "instructions": "This is a live NYC traffic camera frame. Is a marked bike lane visible (green paint, bike symbols, or a lane separated by posts or parked cars)?",
    },
    "bike_lane_blocked": {
        "type": "noul",
        "instructions": "Is a car, truck, or van stopped or parked inside a marked bike lane, blocking it? Answer false if no bike lane is visible.",
    },
}


def get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read()


def check(cam):
    try:
        jpg = get(cam["imageUrl"])
        res = beta.decisions.create(
            model="models/gemini-decision-1",
            input=[{"type": "image", "data": base64.b64encode(jpg).decode(), "mime_type": "image/jpeg"}],
            questions=QUESTIONS,
        )
        a = res.answers
        out = {
            "id": cam["id"], "name": cam["name"], "lat": cam["latitude"], "lon": cam["longitude"],
            "lane": round(a["bike_lane_visible"].noul, 3),
            "blocked": round(a["bike_lane_blocked"].noul, 3),
        }
        if out["blocked"] >= 0.5:
            open(f"hits/{cam['id'][:8]}.jpg", "wb").write(jpg)
        return out
    except Exception as e:
        return {"id": cam["id"], "name": cam["name"], "error": f"{type(e).__name__}: {e}"[:200]}


if __name__ == "__main__":
    os.makedirs("hits", exist_ok=True)
    cams = [c for c in json.loads(get("https://webcams.nyctmc.org/api/cameras"))
            if c["isOnline"] == "true" and c["area"] == AREA]
    t = time.time()
    with ThreadPoolExecutor(16) as ex:
        results = list(ex.map(check, cams))
    ok = [r for r in results if "error" not in r]
    errs = [r for r in results if "error" in r]
    json.dump(results, open("scan_results.json", "w"), indent=1)
    print(f"{AREA}: {len(cams)} cameras in {time.time()-t:.0f}s, {len(errs)} errors")
    print(f"bike lane visible (p>=0.5): {sum(r['lane'] >= 0.5 for r in ok)}")
    hits = sorted([r for r in ok if r["blocked"] >= 0.5], key=lambda r: -r["blocked"])
    print(f"bike lane blocked (p>=0.5): {len(hits)}")
    for r in hits[:15]:
        print(f"  {r['blocked']:.2f}  lane={r['lane']:.2f}  {r['name']}  hits/{r['id'][:8]}.jpg")
    for r in errs[:3]:
        print("  ERR", r["error"])
