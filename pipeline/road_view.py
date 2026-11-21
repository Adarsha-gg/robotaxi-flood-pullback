"""Score every 311 photo: does it show the ROADWAY the way a car sees it?

Adds road_view (0-1) and cars_in_water (0-1) to data/photos_<date>.json using Decision 1.
The ride only seeds Genie 4 with photos where road_view >= 0.6 (no courtyards, windows,
basements or sidewalk-only shots).
Run: .venv/bin/python -m pipeline.road_view [date]
"""
import base64
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

Q = {
    "road_view": {"type": "noul", "instructions":
        "Is this photo taken at street level and does it clearly show the vehicle roadway (a driving lane of a street), "
        "the way a car's front camera would see it? Answer false for courtyards, rooftops, building interiors, "
        "basements, close-ups of a drain, or photos that only show a sidewalk."},
    "cars_in_water": {"type": "noul", "instructions": "Is at least one car or truck visible driving or parked in water on the road?"},
}


_CLIENT = None


def score(p):
    from gem.client import shared_beta_client
    _CLIENT = shared_beta_client()
    with open(os.path.join(ROOT, p["path"]), "rb") as f:
        img = f.read()
    try:
        a = _CLIENT.decisions.create(
            model="models/gemini-decision-1",
            input=[{"type": "image", "data": base64.b64encode(img).decode(), "mime_type": "image/jpeg"}],
            questions=Q).answers
        p = {k: v for k, v in p.items() if k != "error"}
        return {**p, "road_view": round(a["road_view"].noul, 3), "cars_in_water": round(a["cars_in_water"].noul, 3)}
    except Exception as e:
        return {**p, "road_view": None, "error": str(e)[:120]}


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-11-18"
    path = os.path.join(ROOT, "data", f"photos_{date}.json")
    with open(path) as f:
        photos = json.load(f)
    with ThreadPoolExecutor(8) as ex:
        out = list(ex.map(score, photos))
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    good = [p for p in out if (p.get("road_view") or 0) >= 0.6]
    print(f"{len(good)}/{len(out)} photos show the roadway like a car camera")
    for p in sorted(good, key=lambda p: -(p.get("cars_in_water") or 0))[:8]:
        print(f"  road={p['road_view']} cars_in_water={p['cars_in_water']} {p['t'][11:16]} {p['address'][:34]}")


if __name__ == "__main__":
    main()
