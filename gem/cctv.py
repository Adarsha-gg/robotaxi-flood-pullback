"""Wildcard Upgrade #3: Live 12-Cam SF Caltrans CCTV Parallel Decision 1 Sweep.

Fetches live District 4 Caltrans highway/arterial CCTV frames across San Francisco
in parallel and judges each frame with Decision 1 (`gem.sim.judge_sim_frame`).
Does not import from `pipeline/`. Every public function enforces timeouts and
catches all exceptions gracefully, never raising to its caller.
"""
from __future__ import annotations

import json
import math
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gem.client import shared_beta_client
from gem.sim import judge_sim_frame

ROOT = Path(__file__).resolve().parent.parent
CAMERAS_PATH = ROOT / "data" / "sf_cameras.json"
SWEEP_CACHE_PATH = ROOT / "media" / "cctv_sweep.json"

USER_AGENT = "FloodWatchSF/1.0 (Caltrans-D4-CCTV-Sweep; +https://cwwp2.dot.ca.gov)"
HTTP_TIMEOUT_S = 4.0
PRIORITY_ROUTES = {"I-80", "US-101", "I-280"}
ANCHOR_CAMERA_IDS = ("TV388", "TVD01", "TV316", "TV301", "TV327")
ACTION_ORDER = {"avoid": 0, "slow": 1, "proceed": 2}


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _geo_dist_km(a: dict[str, Any], b: dict[str, Any]) -> float:
    lat1 = float(a.get("lat", 0.0))
    lon1 = float(a.get("lon", 0.0))
    lat2 = float(b.get("lat", 0.0))
    lon2 = float(b.get("lon", 0.0))
    dlat = (lat2 - lat1) * 111.0
    dlon = (lon2 - lon1) * 111.0 * math.cos(math.radians(0.5 * (lat1 + lat2)))
    return math.hypot(dlat, dlon)


def _select_cameras(cameras: list[dict[str, Any]], n: int) -> list[dict[str, Any]]:
    """Select `n` geographically spread in-service SF cameras across major corridors."""
    target = max(0, int(n))
    if target == 0:
        return []

    eligible = [
        c for c in cameras
        if isinstance(c, dict)
        and c.get("in_service") is True
        and isinstance(c.get("image"), str)
        and c["image"].strip()
    ]
    if not eligible:
        return []

    # Prefer San Francisco city proper (lat >= 37.68) before distant peninsula cameras.
    sf_proper = [c for c in eligible if float(c.get("lat", 0.0)) >= 37.68]
    pool = sf_proper if len(sf_proper) >= target else eligible

    by_id = {str(c.get("id", "")): c for c in pool}
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()

    # Seed with iconic priority corridors (Presidio, Fremont, 6th St, Octavia/101, John Daly/280).
    for cid in ANCHOR_CAMERA_IDS:
        if len(selected) >= target:
            break
        cam = by_id.get(cid)
        if cam is not None and cid not in selected_ids:
            selected.append(cam)
            selected_ids.add(cid)

    remaining = [c for c in pool if str(c.get("id", "")) not in selected_ids]

    # Greedy farthest-point sampling with route balance bonus for I-80 / US-101 / I-280.
    while len(selected) < target and remaining:
        route_counts: dict[str, int] = {}
        for s in selected:
            r = str(s.get("route", ""))
            route_counts[r] = route_counts.get(r, 0) + 1

        def _score(cand: dict[str, Any]) -> tuple[float, str]:
            if not selected:
                min_d = 1.0
            else:
                min_d = min(_geo_dist_km(cand, s) for s in selected)
            route = str(cand.get("route", ""))
            route_bonus = 1.25 if route in PRIORITY_ROUTES else 0.9
            balance_factor = 1.0 / (1.0 + 0.15 * route_counts.get(route, 0))
            return (min_d * route_bonus * balance_factor, str(cand.get("id", "")))

        best = max(remaining, key=_score)
        selected.append(best)
        selected_ids.add(str(best.get("id", "")))
        remaining.remove(best)

    return selected


def _make_ssl_context() -> ssl.SSLContext | None:
    try:
        return ssl.create_default_context()
    except Exception:
        return None


def _fetch_jpeg(url: str, timeout_s: float) -> bytes | None:
    """Fetch a live camera JPEG with cache-buster timestamp. Returns None on any error."""
    sep = "&" if "?" in url else "?"
    busted_url = f"{url}{sep}t={int(time.time())}"
    req = urllib.request.Request(
        busted_url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "image/jpeg,image/*,*/*;q=0.8",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    try:
        ctx = _make_ssl_context()
        with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as resp:
            status = getattr(resp, "status", 200)
            if status and int(status) >= 400:
                return None
            data = resp.read(5 * 1024 * 1024)
            if not data or len(data) < 256:
                return None
            # Basic JPEG SOI check (0xFF 0xD8) to drop HTML error pages.
            if data[:2] != b"\xff\xd8":
                return None
            return data
    except Exception:
        return None


def _scan_one_camera(cam: dict[str, Any], http_timeout_s: float) -> dict[str, Any] | None:
    """Fetch live JPEG for a single camera and judge it with Decision 1. Never raises."""
    try:
        image_url = str(cam.get("image", "")).strip()
        if not image_url:
            return None
        jpeg = _fetch_jpeg(image_url, timeout_s=http_timeout_s)
        if not jpeg:
            return None
        verdict = judge_sim_frame(jpeg)
        return {
            "id": str(cam.get("id", "")),
            "name": str(cam.get("name", "")).strip(),
            "route": str(cam.get("route", "")).strip(),
            "lat": float(cam.get("lat", 0.0)),
            "lon": float(cam.get("lon", 0.0)),
            "image": image_url,
            "verdict": verdict,
        }
    except Exception:
        return None


def _empty_sweep(n_requested: int, wall_ms: int, n_failed: int = 0) -> dict[str, Any]:
    summary = (
        f"0/{n_requested} live SF Caltrans highway cameras scanned in {wall_ms / 1000:.2f}s "
        f"· 0 avoid, 0 slow, 0 proceed"
    )
    return {
        "ts": _iso_utc_now(),
        "n_requested": n_requested,
        "n_scanned": 0,
        "n_failed": n_failed,
        "n_avoid": 0,
        "n_slow": 0,
        "n_proceed": 0,
        "wall_ms": wall_ms,
        "summary": summary,
        "cameras": [],
    }


def sweep_sf_cameras(n: int = 12, timeout_s: float = 8.0) -> dict[str, Any]:
    """Fetch and judge `n` live SF Caltrans CCTV cameras in parallel. Never raises."""
    t0 = time.perf_counter()
    n_requested = max(1, int(n)) if isinstance(n, (int, float)) else 12
    total_timeout = max(1.0, float(timeout_s)) if isinstance(timeout_s, (int, float)) else 8.0

    try:
        if not CAMERAS_PATH.is_file():
            wall_ms = int(round((time.perf_counter() - t0) * 1000))
            return _empty_sweep(n_requested=n_requested, wall_ms=wall_ms, n_failed=n_requested)

        raw = json.loads(CAMERAS_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            wall_ms = int(round((time.perf_counter() - t0) * 1000))
            return _empty_sweep(n_requested=n_requested, wall_ms=wall_ms, n_failed=n_requested)

        selected = _select_cameras(raw, n_requested)
        if not selected:
            wall_ms = int(round((time.perf_counter() - t0) * 1000))
            return _empty_sweep(n_requested=n_requested, wall_ms=wall_ms, n_failed=n_requested)

        # Warm the shared v1beta client once before fanning out threads.
        try:
            shared_beta_client()
        except Exception:
            pass

        http_timeout = min(HTTP_TIMEOUT_S, max(1.0, total_timeout * 0.5))
        max_workers = max(1, min(len(selected), 12))
        deadline = t0 + total_timeout

        scanned: list[dict[str, Any]] = []
        n_failed = 0

        pool = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = [pool.submit(_scan_one_camera, cam, http_timeout) for cam in selected]
            remaining_s = max(0.1, deadline - time.perf_counter())
            done, not_done = wait(futures, timeout=remaining_s)

            for fut in done:
                try:
                    item = fut.result(timeout=0)
                except Exception:
                    item = None
                if item is not None:
                    scanned.append(item)
                else:
                    n_failed += 1

            n_failed += len(not_done)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        scanned.sort(
            key=lambda c: (
                ACTION_ORDER.get(str((c.get("verdict") or {}).get("action", "slow")), 1),
                -(
                    float((c.get("verdict") or {}).get("flooded_p"))
                    if (c.get("verdict") or {}).get("flooded_p") is not None
                    else -1.0
                ),
                str(c.get("id", "")),
            )
        )

        n_scanned = len(scanned)
        n_avoid = sum(1 for c in scanned if (c.get("verdict") or {}).get("action") == "avoid")
        n_slow = sum(1 for c in scanned if (c.get("verdict") or {}).get("action") == "slow")
        n_proceed = sum(1 for c in scanned if (c.get("verdict") or {}).get("action") == "proceed")
        wall_ms = int(round((time.perf_counter() - t0) * 1000))

        summary = (
            f"{n_scanned}/{len(selected)} live SF Caltrans highway cameras scanned "
            f"in {wall_ms / 1000:.2f}s · {n_avoid} avoid, {n_slow} slow, {n_proceed} proceed"
        )

        return {
            "ts": _iso_utc_now(),
            "n_requested": len(selected),
            "n_scanned": n_scanned,
            "n_failed": n_failed,
            "n_avoid": n_avoid,
            "n_slow": n_slow,
            "n_proceed": n_proceed,
            "wall_ms": wall_ms,
            "summary": summary,
            "cameras": scanned,
        }
    except Exception:
        wall_ms = int(round((time.perf_counter() - t0) * 1000))
        return _empty_sweep(n_requested=n_requested, wall_ms=wall_ms, n_failed=n_requested)


def load_cached_sweep() -> dict[str, Any] | None:
    """Read `media/cctv_sweep.json` if it exists and is valid JSON. Never raises."""
    try:
        if not SWEEP_CACHE_PATH.is_file():
            return None
        data = json.loads(SWEEP_CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _format_table(result: dict[str, Any]) -> str:
    cameras = result.get("cameras") or []
    lines = [
        f"{'ID':<6} {'ROUTE':<7} {'ACTION':<8} {'LANE_P':>6} {'EDGE_P':>6} {'DEPTH':<38} {'MS':>5}  NAME",
        "-" * 112,
    ]
    for cam in cameras:
        v = cam.get("verdict") or {}
        action = str(v.get("action") or "slow").upper()
        lane_p = f"{v['lane_covered']:.2f}" if v.get("lane_covered") is not None else "  n/a"
        edge_p = f"{v['edges_hidden']:.2f}" if v.get("edges_hidden") is not None else "  n/a"
        depth = str(v.get("depth_label") or "unknown")[:38]
        ms = int(v.get("latency_ms") or 0)
        name = str(cam.get("name") or "")
        lines.append(
            f"{cam.get('id', ''):<6} {cam.get('route', ''):<7} {action:<8} "
            f"{lane_p:>6} {edge_p:>6} {depth:<38} {ms:>5}  {name}"
        )
    lines.append("-" * 112)
    lines.append(str(result.get("summary") or ""))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    try:
        n = 12
        if argv:
            try:
                n = max(1, int(argv[0]))
            except ValueError:
                n = 12

        result = sweep_sf_cameras(n=n)

        has_real_verdict = any(
            (c.get("verdict") or {}).get("flooded_p") is not None
            for c in (result.get("cameras") or [])
        )
        if has_real_verdict or not SWEEP_CACHE_PATH.is_file():
            try:
                SWEEP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                SWEEP_CACHE_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass

        print(_format_table(result))
        summary_json = {k: v for k, v in result.items() if k != "cameras"}
        summary_json["cached_path"] = str(SWEEP_CACHE_PATH)
        print()
        print(json.dumps(summary_json, indent=2))
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
