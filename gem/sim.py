"""G7 + G8 + G13: Stage-proof Genie 4 street simulation, Decision 1 rubric, and Hydrogen clip review.

Wraps gem.world.GenieSession and gem.vision without importing from pipeline/.
Every public function enforces timeouts and fallbacks and never raises to its caller.
"""
from __future__ import annotations

import base64
import json
import os
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any

from gem.client import get_beta_client
from gem.vision import (
    DECISION_MODEL,
    DEPTH_CRITERIA,
    _clamp01,
    _shrink_jpeg,
    judge_video,
)
from gem.world import GenieSession

ROOT = Path(__file__).resolve().parent.parent
RENDERS_DIR = ROOT / "media" / "renders"
CACHE_DIR = ROOT / "media" / "sim_cache"

CAR_DEPTH_CRITERIA = [
    "dry or damp road",
    "wet road, thin film of water",
    "puddles in the lane, below the tire tread",
    "water over the tire sidewall, below the wheel hub",
    "water at or above the wheel hub, stall risk for a car",
]

CAR_QUESTIONS: dict[str, dict[str, Any]] = {
    "lane_covered": {
        "type": "noul",
        "instructions": (
            "Is standing or running water covering the vehicle TRAVEL LANE of the road "
            "(not just the sidewalk, gutter or curb)?"
        ),
    },
    "car_depth": {
        "type": "score",
        "instructions": "How deep is the water a car driving in this lane would have to go through?",
        "criteria": CAR_DEPTH_CRITERIA,
    },
    "edges_hidden": {
        "type": "noul",
        "instructions": (
            "Does the water hide the lane markings or the curb line, "
            "so a self-driving car could not tell where the road edge is?"
        ),
    },
}

SIM_QUESTIONS = CAR_QUESTIONS

DEFAULT_DECISION_TIMEOUT_S = 8.0
DEFAULT_VIDEO_TIMEOUT_S = 90.0


def _resolve_path(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else (ROOT / p)


def _stop_session_safely(session: Any) -> None:
    if session is None:
        return
    try:
        session.stop()
    except Exception:
        pass


def _empty_frame_verdict(latency_ms: int = 0) -> dict[str, Any]:
    return {
        "lane_covered": None,
        "edges_hidden": None,
        "depth_level": 0,
        "p_tire_or_worse": None,
        "flooded_p": None,
        "depth_score": None,
        "depth_label": "unknown",
        "action": "slow",
        "latency_ms": latency_ms,
        "rubric": {
            "lane_covered": None,
            "edges_hidden": None,
            "p_tire_or_worse": None,
            "reaches_curb": None,
            "sedan_stall": None,
            "lane_visible": None,
        },
    }


def _empty_sim_verdict(latency_ms: int = 0) -> dict[str, Any]:
    return {
        "lane_covered": None,
        "edges_hidden": None,
        "depth_level": 0,
        "p_tire_or_worse": None,
        "flooded_p": None,
        "depth_score": None,
        "depth_label": "unknown",
        "latency_ms": latency_ms,
        "rubric": {
            "lane_covered": None,
            "edges_hidden": None,
            "p_tire_or_worse": None,
            "reaches_curb": None,
            "sedan_stall": None,
            "lane_visible": None,
        },
        "per_frame": [],
        "trend": "steady",
        "agreement": 0.0,
        "action": "slow",
    }


def build_prompt(watch: dict, warning: dict) -> str:
    """Build the Genie 4 robotaxi roof-camera street-flood prompt (matches pipeline/ride.py v2)."""
    try:
        peak = (warning or {}).get("peak") or {"mm": 0, "t": ""}
        t_hhmm = str(peak.get("t", ""))[11:16] or "09:00"
        date_str = str(peak.get("t", ""))[:10] or "2026-11-18"
        name = (watch or {}).get("name", "San Francisco")
        n_storm_days = (watch or {}).get("n_storm_days", 0)
        return (
            f"Forward-facing roof camera of a driverless robotaxi in the travel lane, approaching {name}, "
            f"San Francisco, at {t_hhmm} on {date_str}. {peak.get('mm', 0)} mm of rain in one hour on saturated "
            f"streets; this intersection's roadway flooded in {n_storm_days} past storms. Show the water "
            f"across the driving lane and how high it reaches on the wheels of cars ahead. The robotaxi drives "
            f"forward slowly in its lane. Keep the real street layout from the reference photo."
        )
    except Exception:
        return (
            "Forward-facing roof camera of a driverless robotaxi in the travel lane in San Francisco. "
            "Show the water across the driving lane and how high it reaches on the wheels of cars ahead. "
            "Keep the real street layout from the reference photo."
        )


def prewarm(watch: dict, warning: dict, session_holder: dict) -> dict:
    """Start a Genie 4 session in the background (<50ms) and store it in session_holder."""
    started_at = time.time()
    cell = str((watch or {}).get("cell") or "unknown")
    try:
        if isinstance(session_holder, dict):
            _stop_session_safely(session_holder.get("session"))
        photo = (watch or {}).get("photo") or {}
        photo_path = photo.get("path")
        if not photo_path:
            return {
                "ok": False,
                "started_at": started_at,
                "cell": cell,
                "error": "watch.photo.path missing",
            }
        img = _resolve_path(photo_path).read_bytes()
        prompt = build_prompt(watch, warning)
        session = GenieSession(img, prompt, max_seconds=35).start()
        if isinstance(session_holder, dict):
            session_holder["session"] = session
            session_holder["photo"] = {**photo, "zone": watch.get("name", cell)}
            session_holder["cell"] = cell
        return {
            "ok": True,
            "started_at": started_at,
            "cell": cell,
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "started_at": started_at,
            "cell": cell,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _judge_sim_frame_strict(jpeg: bytes) -> dict[str, Any]:
    """Single Decision 1 call returning CAR-FLOODED rubric answers (raises on failure)."""
    beta = get_beta_client()
    small_jpeg = _shrink_jpeg(jpeg)
    image_b64 = base64.b64encode(small_jpeg).decode("ascii")

    t0 = time.perf_counter()
    res = beta.decisions.create(
        model=DECISION_MODEL,
        input=[{"type": "image", "data": image_b64, "mime_type": "image/jpeg"}],
        questions=CAR_QUESTIONS,
    )
    latency_ms = int(round((time.perf_counter() - t0) * 1000))

    lane_covered = round(_clamp01(res.answers["lane_covered"].noul), 4)
    edges_hidden = round(_clamp01(res.answers["edges_hidden"].noul), 4)

    depth_ans = res.answers["car_depth"]
    max_score = float(len(CAR_DEPTH_CRITERIA) - 1)
    raw_score = getattr(depth_ans, "score", 0.0) or 0.0
    depth_score = round(_clamp01(raw_score / max_score), 4)

    probs_raw = getattr(depth_ans, "probabilities", None) or {}
    probs = {int(k): float(v) for k, v in probs_raw.items()}
    if probs:
        depth_level = max(probs, key=probs.get)
        p_tire_or_worse = round(_clamp01(sum(v for k, v in probs.items() if k >= 3)), 4)
    else:
        depth_level = int(round(_clamp01(raw_score / max_score) * (len(CAR_DEPTH_CRITERIA) - 1)))
        p_tire_or_worse = round(_clamp01(1.0 if depth_level >= 3 else 0.0), 4)

    depth_label = CAR_DEPTH_CRITERIA[min(max(depth_level, 0), len(CAR_DEPTH_CRITERIA) - 1)]
    action = (
        "avoid"
        if (lane_covered >= 0.6 and p_tire_or_worse >= 0.5) or (edges_hidden >= 0.6 and lane_covered >= 0.6)
        else ("slow" if lane_covered >= 0.5 else "proceed")
    )

    return {
        "lane_covered": lane_covered,
        "edges_hidden": edges_hidden,
        "depth_level": depth_level,
        "p_tire_or_worse": p_tire_or_worse,
        "flooded_p": lane_covered,
        "depth_score": depth_score,
        "depth_label": depth_label,
        "action": action,
        "latency_ms": latency_ms,
        "rubric": {
            "lane_covered": lane_covered,
            "edges_hidden": edges_hidden,
            "p_tire_or_worse": p_tire_or_worse,
            # Back-compat aliases for v1 UI bars
            "reaches_curb": edges_hidden,
            "sedan_stall": p_tire_or_worse,
            "lane_visible": round(_clamp01(1.0 - edges_hidden), 4),
        },
    }


def judge_sim_frame(jpeg: bytes) -> dict[str, Any]:
    """Judge a single simulated frame with the 5-question Decision 1 rubric. Never raises."""
    t0 = time.perf_counter()
    try:
        pool = ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(_judge_sim_frame_strict, jpeg)
        try:
            return fut.result(timeout=DEFAULT_DECISION_TIMEOUT_S)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    except Exception:
        latency_ms = int(round((time.perf_counter() - t0) * 1000))
        return _empty_frame_verdict(latency_ms=latency_ms)


def judge_sim(frames: list[bytes]) -> dict[str, Any]:
    """Judge multiple frames in parallel threads and aggregate into a rubric verdict. Never raises."""
    t0 = time.perf_counter()
    try:
        valid_frames = [f for f in (frames or []) if isinstance(f, (bytes, bytearray)) and len(f) > 0]
        if not valid_frames:
            return _empty_sim_verdict(latency_ms=int(round((time.perf_counter() - t0) * 1000)))

        max_workers = max(1, min(len(valid_frames), 6))
        pool = ThreadPoolExecutor(max_workers=max_workers)
        futures = [pool.submit(_judge_sim_frame_strict, bytes(f)) for f in valid_frames]
        deadline = time.perf_counter() + DEFAULT_DECISION_TIMEOUT_S

        per_frame: list[dict[str, Any]] = []
        try:
            for fut in futures:
                remaining = max(0.05, deadline - time.perf_counter())
                try:
                    item = fut.result(timeout=remaining)
                    if item and item.get("flooded_p") is not None:
                        per_frame.append(item)
                except Exception:
                    continue
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        wall_ms = int(round((time.perf_counter() - t0) * 1000))
        if not per_frame:
            return _empty_sim_verdict(latency_ms=wall_ms)

        flooded_ps = [r["lane_covered"] for r in per_frame]
        edges_hiddens = [r["edges_hidden"] for r in per_frame]
        p_tires = [r["p_tire_or_worse"] for r in per_frame]
        depth_levels = [r["depth_level"] for r in per_frame]
        depth_scores = [r["depth_score"] for r in per_frame]
        depth_labels = [r["depth_label"] for r in per_frame]

        lane_covered = round(float(statistics.median(flooded_ps)), 4)
        edges_hidden = round(float(statistics.median(edges_hiddens)), 4)
        p_tire_or_worse = round(float(statistics.median(p_tires)), 4)
        depth_level = int(round(float(statistics.median(depth_levels))))
        depth_score = round(float(statistics.median(depth_scores)), 4)
        depth_label = Counter(depth_labels).most_common(1)[0][0]

        rubric = {
            "lane_covered": lane_covered,
            "edges_hidden": edges_hidden,
            "p_tire_or_worse": p_tire_or_worse,
            "reaches_curb": edges_hidden,
            "sedan_stall": p_tire_or_worse,
            "lane_visible": round(_clamp01(1.0 - edges_hidden), 4),
        }

        if len(flooded_ps) >= 2:
            delta = flooded_ps[-1] - flooded_ps[0]
            if delta > 0.1:
                trend = "rising"
            elif delta < -0.1:
                trend = "falling"
            else:
                trend = "steady"
        else:
            trend = "steady"

        agreement = round(_clamp01(1.0 - (max(flooded_ps) - min(flooded_ps))), 4)

        if (lane_covered >= 0.6 and p_tire_or_worse >= 0.5) or (edges_hidden >= 0.6 and lane_covered >= 0.6):
            action = "avoid"
        elif lane_covered >= 0.5:
            action = "slow"
        else:
            action = "proceed"

        return {
            "lane_covered": lane_covered,
            "edges_hidden": edges_hidden,
            "depth_level": depth_level,
            "p_tire_or_worse": p_tire_or_worse,
            "flooded_p": lane_covered,
            "depth_score": depth_score,
            "depth_label": depth_label,
            "latency_ms": wall_ms,
            "rubric": rubric,
            "per_frame": per_frame,
            "trend": trend,
            "agreement": agreement,
            "action": action,
        }
    except Exception:
        wall_ms = int(round((time.perf_counter() - t0) * 1000))
        return _empty_sim_verdict(latency_ms=wall_ms)


def _load_cache_fallback(cell: str, waited_s: float, error: str) -> dict[str, Any]:
    """Load cached Genie simulation result for cell (or any cached cell). Never raises."""
    candidates: list[Path] = []
    if cell:
        candidates.append(CACHE_DIR / cell / "result.json")
    if CACHE_DIR.exists():
        for p in sorted(CACHE_DIR.glob("*/result.json")):
            if p not in candidates:
                candidates.append(p)

    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict) and "verdict" in data:
                data["source"] = "cache"
                data["waited_s"] = round(float(waited_s), 2)
                data["total_s"] = round(float(waited_s), 1)
                data["error"] = error
                return data
        except Exception:
            continue

    return {
        "verdict": _empty_sim_verdict(latency_ms=0),
        "frame": None,
        "frames": [],
        "genie_first_frame_s": None,
        "total_s": round(float(waited_s), 1),
        "frames_seen": 0,
        "source": "cache",
        "waited_s": round(float(waited_s), 2),
        "error": error,
    }


def simulate_street(
    watch: dict,
    warning: dict,
    session_holder: dict,
    settle_s: float = 1.2,
    max_wait_s: float = 12.0,
    n_frames: int = 3,
) -> dict[str, Any]:
    """Run or attach to a pre-warmed Genie 4 street simulation, judge frames, or fall back to cache.

    Never raises to its caller. Output is a strict superset of pipeline.ride.simulate().
    """
    t0 = time.time()
    cell = str((watch or {}).get("cell") or "unknown")
    session: GenieSession | None = None
    try:
        existing = session_holder.get("session") if isinstance(session_holder, dict) else None
        existing_cell = session_holder.get("cell") if isinstance(session_holder, dict) else None

        if (
            existing is not None
            and existing_cell == cell
            and getattr(existing, "status", None) in ("starting", "warming", "live")
        ):
            session = existing
            source = "genie_prewarmed"
        else:
            _stop_session_safely(existing)
            photo = (watch or {}).get("photo") or {}
            photo_path = photo.get("path")
            if not photo_path:
                return _load_cache_fallback(
                    cell,
                    waited_s=time.time() - t0,
                    error="watch.photo.path missing",
                )
            img = _resolve_path(photo_path).read_bytes()
            prompt = build_prompt(watch, warning)
            session = GenieSession(img, prompt, max_seconds=35).start()
            if isinstance(session_holder, dict):
                session_holder["session"] = session
                session_holder["photo"] = {**photo, "zone": watch.get("name", cell)}
                session_holder["cell"] = cell
            source = "genie"

        deadline = t0 + max(0.5, float(max_wait_s))
        while (
            session.frame is None
            and session.status in ("starting", "warming", "live")
            and time.time() < deadline
        ):
            time.sleep(0.05)

        if session.frame is None:
            err = session.error or f"no frame after {round(time.time() - t0, 1)}s (status={session.status})"
            _stop_session_safely(session)
            return _load_cache_fallback(cell, waited_s=time.time() - t0, error=err)

        try:
            session.send_key("key_down", "key_w")
        except Exception:
            pass

        captured: list[bytes] = []
        last_no = -1
        target_n = max(1, int(n_frames))
        gap = 0.4
        total_drive = max(0.0, float(settle_s), gap * max(0, target_n - 1))
        sample_offsets = [
            max(0.0, total_drive - (target_n - 1 - i) * gap)
            for i in range(target_n)
        ]
        t_drive = time.time()
        for offset in sample_offsets:
            while (time.time() - t_drive) < offset and session.status == "live":
                time.sleep(0.05)
            cur_frame = session.frame
            cur_no = session.frame_no
            if cur_frame and cur_no != last_no:
                captured.append(cur_frame)
                last_no = cur_no

        if not captured and session.frame:
            captured = [session.frame]

        if not captured:
            err = session.error or "no frames captured"
            _stop_session_safely(session)
            return _load_cache_fallback(cell, waited_s=time.time() - t0, error=err)

        ts = int(time.time())
        RENDERS_DIR.mkdir(parents=True, exist_ok=True)
        frame_paths: list[str] = []
        for idx, fb in enumerate(captured):
            fpath = RENDERS_DIR / f"sim_{cell}_{ts}_{idx}.jpg"
            fpath.write_bytes(fb)
            frame_paths.append(os.path.relpath(fpath, ROOT))

        verdict = judge_sim(captured)
        elapsed = time.time() - t0
        first_frame_s = (
            round(session.first_frame_at - session.started_at, 1)
            if (session.first_frame_at and session.started_at)
            else None
        )
        return {
            "verdict": verdict,
            "frame": frame_paths[-1] if frame_paths else None,
            "frames": frame_paths,
            "genie_first_frame_s": first_frame_s,
            "total_s": round(elapsed, 1),
            "frames_seen": session.frame_no,
            "source": source,
            "waited_s": round(elapsed, 2),
            "error": None,
        }
    except Exception as exc:
        _stop_session_safely(session)
        return _load_cache_fallback(
            cell,
            waited_s=time.time() - t0,
            error=f"{type(exc).__name__}: {exc}",
        )


def record_cache(watch: dict, warning: dict, seconds: float = 6.0) -> dict[str, Any]:
    """Record a short live Genie 4 session (default 6s) into media/sim_cache/<cell>/."""
    t0 = time.time()
    cell = str((watch or {}).get("cell") or "unknown")
    session: GenieSession | None = None
    try:
        out_dir = CACHE_DIR / cell
        out_dir.mkdir(parents=True, exist_ok=True)

        photo = (watch or {}).get("photo") or {}
        photo_path = photo.get("path")
        if not photo_path:
            return _load_cache_fallback(cell, waited_s=time.time() - t0, error="watch.photo.path missing")

        img = _resolve_path(photo_path).read_bytes()
        prompt = build_prompt(watch, warning)
        dur = max(1.0, min(float(seconds), 9.0))
        session = GenieSession(img, prompt, max_seconds=dur + 10.0).start()

        try:
            wait_deadline = time.time() + 15.0
            while (
                session.frame is None
                and session.status in ("starting", "warming")
                and time.time() < wait_deadline
            ):
                time.sleep(0.1)

            if session.frame is None:
                raise RuntimeError(session.error or f"no frame from Genie (status={session.status})")

            try:
                session.send_key("key_down", "key_w")
            except Exception:
                pass

            drive_start = session.first_frame_at or time.time()
            while session.status == "live" and (time.time() - drive_start) < dur:
                time.sleep(0.1)
        finally:
            _stop_session_safely(session)
            time.sleep(0.4)

        all_frames = list(session.frames)
        if not all_frames and session.frame:
            all_frames = [session.frame]
        if not all_frames:
            raise RuntimeError(session.error or "no frames recorded")

        n = len(all_frames)
        if n >= 3:
            idxs = [
                min(n - 1, max(0, int(round(n * 0.35)))),
                min(n - 1, max(0, int(round(n * 0.68)))),
                n - 1,
            ]
            # Ensure distinct indices when n >= 3
            if idxs[0] == idxs[1]:
                idxs = [0, n // 2, n - 1]
            selected = [all_frames[i] for i in idxs]
        else:
            selected = [all_frames[min(i, n - 1)] for i in range(3)]

        rel_frames: list[str] = []
        for i, fb in enumerate(selected):
            fpath = out_dir / f"frame_{i}.jpg"
            fpath.write_bytes(fb)
            rel_frames.append(os.path.relpath(fpath, ROOT))

        clip_path = out_dir / "clip.mp4"
        session.save_mp4(str(clip_path))

        verdict = judge_sim(selected)
        elapsed = time.time() - t0
        first_frame_s = (
            round(session.first_frame_at - session.started_at, 1)
            if (session.first_frame_at and session.started_at)
            else None
        )
        result: dict[str, Any] = {
            "verdict": verdict,
            "frame": rel_frames[-1],
            "frames": rel_frames,
            "genie_first_frame_s": first_frame_s,
            "total_s": round(elapsed, 1),
            "frames_seen": len(all_frames),
            "source": "genie",
            "waited_s": round(elapsed, 2),
            "error": None,
            "clip": os.path.relpath(clip_path, ROOT),
        }
        (out_dir / "result.json").write_text(json.dumps(result, indent=2))
        return result
    except Exception as exc:
        _stop_session_safely(session)
        return _load_cache_fallback(
            cell,
            waited_s=time.time() - t0,
            error=f"{type(exc).__name__}: {exc}",
        )


def review_clip(path: str) -> dict[str, Any]:
    """Offline Hydrogen review of a simulated clip (G13 stretch). Never raises."""
    t0 = time.perf_counter()
    try:
        abs_path = _resolve_path(path)
        pool = ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(judge_video, str(abs_path))
        try:
            verdict = fut.result(timeout=DEFAULT_VIDEO_TIMEOUT_S)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        result: dict[str, Any] = {**verdict, "path": str(path)}
        try:
            abs_path.resolve().relative_to(CACHE_DIR.resolve())
            in_cache = True
        except ValueError:
            in_cache = False
        if in_cache:
            (abs_path.parent / "video.json").write_text(json.dumps(result, indent=2))
        return result
    except FuturesTimeoutError:
        latency_ms = int(round((time.perf_counter() - t0) * 1000))
        return {
            "path": str(path),
            "flooded_p": None,
            "depth_score": None,
            "depth_label": "unknown",
            "latency_ms": latency_ms,
            "summary": "",
            "first_water_s": None,
            "error": f"TimeoutError: review_clip exceeded {DEFAULT_VIDEO_TIMEOUT_S}s",
        }
    except Exception as exc:
        latency_ms = int(round((time.perf_counter() - t0) * 1000))
        return {
            "path": str(path),
            "flooded_p": None,
            "depth_score": None,
            "depth_label": "unknown",
            "latency_ms": latency_ms,
            "summary": "",
            "first_water_s": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _load_plan(plan_path: str) -> tuple[dict, dict]:
    plan = json.loads(_resolve_path(plan_path).read_text())
    return plan["watch"], plan["warning"]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "Usage:\n"
            "  python -m gem.sim record <plan.json>\n"
            "  python -m gem.sim prewarm-test <plan.json>\n"
            "  python -m gem.sim run <plan.json>\n"
            "  python -m gem.sim judge <frame1> [frame2 ...]\n"
            "  python -m gem.sim review <clip.mp4>",
            file=sys.stderr,
        )
        return 2

    cmd = argv[0]
    if cmd == "record":
        watch, warning = _load_plan(argv[1])
        seconds = float(argv[2]) if len(argv) > 2 else 6.0
        res = record_cache(watch, warning, seconds=seconds)
        print(json.dumps(res, indent=2))
        return 0

    if cmd == "prewarm-test":
        watch, warning = _load_plan(argv[1])
        holder: dict[str, Any] = {}
        try:
            pw = prewarm(watch, warning, holder)
            time.sleep(5.0)
            res = simulate_street(watch, warning, holder)
            print(json.dumps({"prewarm": pw, "result": res}, indent=2))
        finally:
            _stop_session_safely(holder.get("session"))
            time.sleep(0.3)
        return 0

    if cmd == "run":
        watch, warning = _load_plan(argv[1])
        holder = {}
        try:
            res = simulate_street(watch, warning, holder)
            print(json.dumps(res, indent=2))
        finally:
            _stop_session_safely(holder.get("session"))
            time.sleep(0.3)
        return 0

    if cmd == "judge":
        frame_bytes = [_resolve_path(p).read_bytes() for p in argv[1:]]
        res = judge_sim(frame_bytes)
        print(json.dumps(res, indent=2))
        return 0

    if cmd == "review":
        res = review_clip(argv[1])
        print(json.dumps(res, indent=2))
        return 0

    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
