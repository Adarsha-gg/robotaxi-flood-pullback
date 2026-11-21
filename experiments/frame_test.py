"""Pull live NYC DOT frames near Union Square and run them through Gemini.

Step 1: Decision 1 gates each frame (fast, calibrated yes/no + score).
Step 2: Hydrogen describes what it sees, as JSON.
"""
import base64
import json
import math
import time
import urllib.request

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client()
beta = genai.Client(http_options={"api_version": "v1beta"})

CAMS_URL = "https://webcams.nyctmc.org/api/cameras"
UNION_SQ = (40.7359, -73.9911)


def get(url):
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read()


def nearest(n=4):
    cams = [c for c in json.loads(get(CAMS_URL)) if c["isOnline"] == "true"]
    d = lambda c: math.hypot((c["latitude"] - UNION_SQ[0]) * 111, (c["longitude"] - UNION_SQ[1]) * 84)
    return sorted(cams, key=d)[:n]


def gate(jpg):
    t = time.time()
    res = beta.decisions.create(
        model="models/gemini-decision-1",
        input=[{"type": "image", "data": base64.b64encode(jpg).decode(), "mime_type": "image/jpeg"}],
        questions={
            "unusual": {
                "type": "noul",
                "instructions": "This is a live NYC traffic camera frame. Is anything unusual happening: a crash, a blocked lane, emergency vehicles, flooding, a crowd spilling into the street, or a street closure?",
            },
            "lane_blocked": {
                "type": "noul",
                "instructions": "Is a vehicle stopped or parked in a bus lane or bike lane?",
            },
            "crowd": {
                "type": "score",
                "instructions": "How many pedestrians are visible?",
                "criteria": ["none", "a few", "moderate", "busy", "packed"],
            },
        },
    )
    return res, time.time() - t


def describe(jpg):
    t = time.time()
    res = client.models.generate_content(
        model="gemini-4-hydrogen",
        contents=[
            types.Part.from_bytes(data=jpg, mime_type="image/jpeg"),
            "Live NYC traffic camera frame (352x240). Return JSON with keys: "
            "vehicles (count estimate), pedestrians (count estimate), buses, cyclists, "
            "notable (list of short observations, e.g. blocked lanes, double parking, crowds), "
            "weather, confidence (low/medium/high). Only report what is visible.",
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return res.text, time.time() - t


if __name__ == "__main__":
    for cam in nearest():
        jpg = get(cam["imageUrl"])
        open(f"frame_{cam['id'][:8]}.jpg", "wb").write(jpg)
        print(f"\n=== {cam['name']} ({len(jpg)} bytes) -> frame_{cam['id'][:8]}.jpg")
        try:
            res, dt = gate(jpg)
            print(f"[Decision 1, {dt*1000:.0f} ms]")
            print(res.model_dump_json(indent=1, exclude_none=True) if hasattr(res, "model_dump_json") else res)
        except Exception as e:
            print(f"[Decision 1 failed] {type(e).__name__}: {e}")
        try:
            text, dt = describe(jpg)
            print(f"[Hydrogen, {dt:.1f} s]\n{text}")
        except Exception as e:
            print(f"[Hydrogen failed] {type(e).__name__}: {e}")
