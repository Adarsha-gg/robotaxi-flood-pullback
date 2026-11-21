"""Roadway flood vision judgment using Gemini Decision 1 and Hydrogen."""
from __future__ import annotations

import base64
import json
import mimetypes
import sys
import time
from pathlib import Path
from typing import Any

from google.genai import types

from gem.client import get_beta_client, get_client

DECISION_MODEL = "models/gemini-decision-1"
VIDEO_MODEL = "gemini-4-hydrogen"
DEPTH_CRITERIA = ["none", "wet", "ankle", "impassable"]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def judge_frame(jpeg: bytes) -> dict[str, Any]:
    """Judge a single roadway JPEG frame for standing water and flood depth.

    Returns exact contract keys:
      {"flooded_p": float, "depth_score": float, "depth_label": str, "latency_ms": int}
    """
    beta = get_beta_client()
    image_b64 = base64.b64encode(jpeg).decode("ascii")

    t0 = time.perf_counter()
    res = beta.decisions.create(
        model=DECISION_MODEL,
        input=[{"type": "image", "data": image_b64, "mime_type": "image/jpeg"}],
        questions={
            "flooded": {
                "type": "noul",
                "instructions": "Is standing water covering the roadway?",
            },
            "depth": {
                "type": "score",
                "instructions": "How deep is the standing water on the roadway?",
                "criteria": DEPTH_CRITERIA,
            },
        },
    )
    latency_ms = int(round((time.perf_counter() - t0) * 1000))

    flooded_ans = res.answers["flooded"]
    depth_ans = res.answers["depth"]

    flooded_p = round(_clamp01(flooded_ans.noul), 4)

    max_score = float(len(DEPTH_CRITERIA) - 1)
    raw_score = getattr(depth_ans, "score", 0.0) or 0.0
    depth_score = round(_clamp01(raw_score / max_score), 4)

    probs = getattr(depth_ans, "probabilities", None) or {}
    legend = getattr(depth_ans, "legend", None) or {
        str(i): label for i, label in enumerate(DEPTH_CRITERIA)
    }
    if probs:
        top_key = max(probs, key=lambda k: probs[k])
        depth_label = str(legend.get(str(top_key), DEPTH_CRITERIA[0]))
    else:
        idx = int(round(_clamp01(raw_score / max_score) * (len(DEPTH_CRITERIA) - 1)))
        depth_label = DEPTH_CRITERIA[idx]

    return {
        "flooded_p": flooded_p,
        "depth_score": depth_score,
        "depth_label": depth_label,
        "latency_ms": latency_ms,
    }


def judge_video(path: str) -> dict[str, Any]:
    """Judge a dashcam/street video clip for roadway flooding using agentic video processing.

    Returns contract keys:
      {"flooded_p": float, "depth_score": float, "depth_label": str, "latency_ms": int,
       "summary": str, "first_water_s": float | None}
    """
    client = get_client()
    video_path = Path(path)
    video_bytes = video_path.read_bytes()
    mime_type = mimetypes.guess_type(video_path.name)[0] or "video/mp4"

    video_part = types.Part(
        inline_data=types.Blob(data=video_bytes, mime_type=mime_type),
        media_processing=types.MediaProcessing.AGENTIC,
    )
    prompt = (
        "Analyze this street/dashcam video for standing water covering the roadway. "
        "Return strict JSON with keys: "
        "flooded_p (float 0..1, probability standing water covers the roadway), "
        "depth_score (float 0..1, 0=none, 0.33=wet, 0.67=ankle, 1.0=impassable), "
        'depth_label (one of "none", "wet", "ankle", "impassable"), '
        "summary (short 1-2 sentence description of roadway water conditions), "
        "first_water_s (float seconds when standing roadway water first appears, or null if none)."
    )

    t0 = time.perf_counter()
    res = client.models.generate_content(
        model=VIDEO_MODEL,
        contents=[video_part, prompt],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    latency_ms = int(round((time.perf_counter() - t0) * 1000))

    parsed = json.loads(res.text)
    depth_label = str(parsed.get("depth_label", "none"))
    if depth_label not in DEPTH_CRITERIA:
        depth_label = "none"

    first_water_s = parsed.get("first_water_s")
    if first_water_s is not None:
        first_water_s = float(first_water_s)

    return {
        "flooded_p": round(_clamp01(parsed.get("flooded_p", 0.0)), 4),
        "depth_score": round(_clamp01(parsed.get("depth_score", 0.0)), 4),
        "depth_label": depth_label,
        "latency_ms": latency_ms,
        "summary": str(parsed.get("summary", "")),
        "first_water_s": first_water_s,
    }


def main(argv: list[str]) -> int:
    if not argv:
        print("Usage: python -m gem.vision <image_path> [...]", file=sys.stderr)
        return 2

    exit_code = 0
    for arg in argv:
        p = Path(arg)
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            continue
        try:
            verdict = judge_frame(p.read_bytes())
            print(json.dumps({"file": str(p), **verdict}))
        except Exception as exc:
            exit_code = 1
            print(json.dumps({"file": str(p), "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
