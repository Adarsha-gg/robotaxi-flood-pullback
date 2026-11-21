"""Wildcard #8: Live Multi-City Portability Adapter for 7 Active 2026 US AV Markets.

Demonstrates drop-in portability of the Robotaxi Flood Pull-Back stack across 7
flood-prone US autonomous vehicle markets by fetching live Open-Meteo hourly
precipitation forecasts and live NWS active alerts in parallel.

Pure Python stdlib only. Zero imports from `pipeline/`. Every public function
enforces strict timeouts (<= 4s per HTTP call) and never raises.

Exposes:
    list_cities() -> list[dict]
    live_city_status(city_id: str, timeout_s: float = 4.0) -> dict
    sweep_all_cities(timeout_s: float = 6.0) -> dict
    load_cached_snapshot() -> dict | None

CLI:
    .venv/bin/python -m gem.cities
"""
from __future__ import annotations

import copy
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = ROOT / "media" / "cities_snapshot.json"

NWS_USER_AGENT = "FloodPullBackSF/1.0 (ops@example.com)"
MAX_HTTP_TIMEOUT_S = 4.0

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}&hourly=precipitation&forecast_days=2&timezone=auto"
)
NWS_ALERTS_URL = "https://api.weather.gov/alerts/active?point={lat},{lon}"

_CITIES: tuple[dict[str, Any], ...] = (
    {
        "id": "sf",
        "name": "San Francisco",
        "lat": 37.7749,
        "lon": -122.4194,
        "timezone": "America/Los_Angeles",
        "av_operators": ["Waymo", "Zoox"],
        "flood_hazard": "Atmospheric rivers (4-6/winter) + king tides",
        "open_311_source": "DataSF 311 Cases (vw6y-z8j6)",
        "grid_origin": {"lat0": 37.7, "lon0": -122.52, "dlat": 0.0015, "dlon": 0.0019},
    },
    {
        "id": "austin",
        "name": "Austin",
        "lat": 30.2672,
        "lon": -97.7431,
        "timezone": "America/Chicago",
        "av_operators": ["Waymo", "Tesla", "Zoox"],
        "flood_hazard": "Flash Flood Alley (30-70+ low-water closures/storm)",
        "open_311_source": "Austin 311 (i26j-ai4z) + ATXfloods (>100 gauges)",
        "grid_origin": {"lat0": 30.15, "lon0": -97.88, "dlat": 0.0015, "dlon": 0.0017},
    },
    {
        "id": "miami",
        "name": "Miami",
        "lat": 25.7617,
        "lon": -80.1918,
        "timezone": "America/New_York",
        "av_operators": ["Waymo", "Tesla", "Zoox"],
        "flood_hazard": "Tropical storms + NOAA King Tides (sunny-day flooding)",
        "open_311_source": "Miami-Dade 311 (DERM drainage/flooding) + NOAA King Tides",
        "grid_origin": {"lat0": 25.68, "lon0": -80.32, "dlat": 0.0015, "dlon": 0.0017},
    },
    {
        "id": "atlanta",
        "name": "Atlanta",
        "lat": 33.7490,
        "lon": -84.3880,
        "timezone": "America/New_York",
        "av_operators": ["Waymo", "Zoox"],
        "flood_hazard": "Rapid convective cloudbursts (May 20 2026 pre-NWS flood site)",
        "open_311_source": "ATL311 + Watershed Management catch-basin GIS",
        "grid_origin": {"lat0": 33.65, "lon0": -84.50, "dlat": 0.0015, "dlon": 0.0018},
    },
    {
        "id": "san_antonio",
        "name": "San Antonio",
        "lat": 29.4241,
        "lon": -98.4936,
        "timezone": "America/Chicago",
        "av_operators": ["Waymo"],
        "flood_hazard": "Flash Flood Alley low-water crossings (May 1 2026 NHTSA 26E-026 recall site)",
        "open_311_source": "San Antonio 311 + SARA ponding GIS",
        "grid_origin": {"lat0": 29.32, "lon0": -98.65, "dlat": 0.0015, "dlon": 0.0017},
    },
    {
        "id": "phoenix",
        "name": "Phoenix",
        "lat": 33.4484,
        "lon": -112.0740,
        "timezone": "America/Phoenix",
        "av_operators": ["Waymo"],
        "flood_hazard": "Monsoon flash floods across desert washes",
        "open_311_source": "myPHX311 + Maricopa FCDMC flood gauges/GIS",
        "grid_origin": {"lat0": 33.32, "lon0": -112.22, "dlat": 0.0015, "dlon": 0.0018},
    },
    {
        "id": "nyc",
        "name": "New York City",
        "lat": 40.7128,
        "lon": -74.0060,
        "timezone": "America/New_York",
        "av_operators": ["Waymo (testing)"],
        "flood_hazard": "Extreme cloudbursts, combined-sewer backups",
        "open_311_source": "NYC 311 + NYC FloodNet (400+ ultrasonic sensors)",
        "grid_origin": {"lat0": 40.58, "lon0": -74.06, "dlat": 0.0015, "dlon": 0.0020},
    },
)

_CITY_BY_ID: dict[str, dict[str, Any]] = {c["id"]: c for c in _CITIES}


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clamp_http_timeout(timeout_s: float) -> float:
    try:
        val = float(timeout_s)
    except Exception:
        val = MAX_HTTP_TIMEOUT_S
    if val <= 0.0:
        return 0.5
    return min(val, MAX_HTTP_TIMEOUT_S)


def _ssl_context() -> ssl.SSLContext | None:
    try:
        return ssl.create_default_context()
    except Exception:
        return None


def _fetch_json(url: str, timeout_s: float, accept: str = "application/json") -> tuple[dict[str, Any] | None, str | None]:
    """Fetch JSON over HTTP(S) with strict timeout. Returns (data, error_str)."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": NWS_USER_AGENT,
            "Accept": accept,
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s, context=_ssl_context()) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", errors="replace"))
        if isinstance(data, dict):
            return data, None
        return None, "unexpected_json_type"
    except urllib.error.HTTPError as exc:
        return None, f"http_{exc.code}"
    except urllib.error.URLError as exc:
        return None, f"url_error:{exc.reason}"
    except TimeoutError:
        return None, "timeout"
    except Exception as exc:
        return None, f"error:{type(exc).__name__}"


def _local_now_hour_key(tz_name: str, utc_offset_seconds: Any) -> str:
    """Compute current local hour string 'YYYY-MM-DDTHH:00' for matching Open-Meteo hourly.time."""
    now_utc = datetime.now(timezone.utc)
    if isinstance(utc_offset_seconds, (int, float)):
        local_dt = now_utc + timedelta(seconds=int(utc_offset_seconds))
        return local_dt.strftime("%Y-%m-%dT%H:00")
    if ZoneInfo is not None and tz_name:
        try:
            local_dt = now_utc.astimezone(ZoneInfo(tz_name))
            return local_dt.strftime("%Y-%m-%dT%H:00")
        except Exception:
            pass
    return now_utc.strftime("%Y-%m-%dT%H:00")


def _parse_open_meteo(
    payload: dict[str, Any],
    tz_name: str,
) -> tuple[float, float, float, str | None]:
    """Extract (next_6h_mm, next_24h_mm, peak_mm_h, peak_t) from Open-Meteo response."""
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    precip = hourly.get("precipitation") or []
    n = min(len(times), len(precip))
    if n == 0:
        return 0.0, 0.0, 0.0, None

    now_key = _local_now_hour_key(tz_name, payload.get("utc_offset_seconds"))

    start_idx = 0
    for i in range(n):
        t_str = str(times[i])
        if t_str >= now_key:
            start_idx = i
            break
    else:
        start_idx = max(0, n - 24)

    window_24_pairs: list[tuple[str, float]] = []
    for i in range(start_idx, min(n, start_idx + 24)):
        val_raw = precip[i]
        try:
            val = float(val_raw) if val_raw is not None else 0.0
        except Exception:
            val = 0.0
        if val < 0.0:
            val = 0.0
        window_24_pairs.append((str(times[i]), val))

    window_6 = [v for _, v in window_24_pairs[:6]]
    window_24 = [v for _, v in window_24_pairs]

    next_6h_mm = round(sum(window_6), 2)
    next_24h_mm = round(sum(window_24), 2)

    peak_mm_h = 0.0
    peak_t: str | None = None
    for t_str, val in window_24_pairs:
        if val > peak_mm_h:
            peak_mm_h = val
            peak_t = t_str
    peak_mm_h = round(peak_mm_h, 2)

    return next_6h_mm, next_24h_mm, peak_mm_h, peak_t


def _parse_nws_alerts(payload: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    """Extract (nws_flood_alert, alerts_summary) from NWS active alerts GeoJSON."""
    features = payload.get("features")
    if not isinstance(features, list):
        return False, []

    alerts: list[dict[str, Any]] = []
    has_flood = False
    for feat in features:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties")
        if not isinstance(props, dict):
            continue
        event = str(props.get("event") or "").strip()
        severity = str(props.get("severity") or "").strip()
        headline = str(props.get("headline") or "").strip()
        expires = props.get("expires")
        is_flood = "flood" in event.lower()
        if is_flood:
            has_flood = True
        alerts.append(
            {
                "event": event,
                "severity": severity,
                "headline": headline,
                "expires": str(expires) if expires else None,
                "is_flood": is_flood,
            }
        )
    return has_flood, alerts


def _compute_risk_level(
    next_6h_mm: float,
    next_24h_mm: float,
    peak_mm_h: float,
    nws_flood_alert: bool,
) -> str:
    if next_6h_mm >= 12.0 or peak_mm_h >= 6.0 or nws_flood_alert:
        return "pullback_active"
    if next_24h_mm >= 5.0:
        return "watch"
    return "clear"


def _fallback_status(city_meta: dict[str, Any], error: str, wall_ms: int = 0) -> dict[str, Any]:
    out = copy.deepcopy(city_meta)
    out.update(
        {
            "ts": _iso_utc_now(),
            "next_6h_mm": 0.0,
            "next_24h_mm": 0.0,
            "peak_mm_h": 0.0,
            "peak_t": None,
            "nws_flood_alert": False,
            "nws_alerts": [],
            "risk_level": "clear",
            "sources": {"open_meteo": "error", "nws": "error"},
            "errors": [error],
            "ok": False,
            "wall_ms": wall_ms,
        }
    )
    return out


def list_cities() -> list[dict[str, Any]]:
    """Return metadata for all 7 active 2026 US AV markets. Never raises."""
    try:
        return [copy.deepcopy(c) for c in _CITIES]
    except Exception:
        return []


def live_city_status(city_id: str, timeout_s: float = 4.0) -> dict[str, Any]:
    """Fetch live Open-Meteo forecast and NWS active alerts for one city in parallel.

    Strict timeout <= 4s per HTTP request. Never raises; degrades gracefully on error.
    """
    t0 = time.perf_counter()
    try:
        key = str(city_id or "").strip().lower()
        city = _CITY_BY_ID.get(key)
        if city is None:
            wall_ms = int(round((time.perf_counter() - t0) * 1000))
            return {
                "id": key,
                "name": key or "unknown",
                "lat": None,
                "lon": None,
                "timezone": None,
                "av_operators": [],
                "flood_hazard": "",
                "open_311_source": "",
                "grid_origin": None,
                "ts": _iso_utc_now(),
                "next_6h_mm": 0.0,
                "next_24h_mm": 0.0,
                "peak_mm_h": 0.0,
                "peak_t": None,
                "nws_flood_alert": False,
                "nws_alerts": [],
                "risk_level": "clear",
                "sources": {"open_meteo": "error", "nws": "error"},
                "errors": [f"unknown_city:{key}"],
                "ok": False,
                "wall_ms": wall_ms,
            }

        http_timeout = _clamp_http_timeout(timeout_s)
        om_url = OPEN_METEO_URL.format(lat=city["lat"], lon=city["lon"])
        nws_url = NWS_ALERTS_URL.format(lat=city["lat"], lon=city["lon"])

        om_data: dict[str, Any] | None = None
        om_err: str | None = "timeout"
        nws_data: dict[str, Any] | None = None
        nws_err: str | None = "timeout"

        pool = ThreadPoolExecutor(max_workers=2)
        try:
            fut_om = pool.submit(_fetch_json, om_url, http_timeout, "application/json")
            fut_nws = pool.submit(
                _fetch_json,
                nws_url,
                http_timeout,
                "application/geo+json, application/json",
            )
            done, _ = wait([fut_om, fut_nws], timeout=http_timeout + 0.15)
            if fut_om in done:
                try:
                    om_data, om_err = fut_om.result(timeout=0)
                except Exception as exc:
                    om_data, om_err = None, f"error:{type(exc).__name__}"
            if fut_nws in done:
                try:
                    nws_data, nws_err = fut_nws.result(timeout=0)
                except Exception as exc:
                    nws_data, nws_err = None, f"error:{type(exc).__name__}"
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        errors: list[str] = []
        if om_data is not None:
            next_6h_mm, next_24h_mm, peak_mm_h, peak_t = _parse_open_meteo(
                om_data, str(city["timezone"])
            )
            om_status = "live"
        else:
            next_6h_mm, next_24h_mm, peak_mm_h, peak_t = 0.0, 0.0, 0.0, None
            om_status = "error"
            errors.append(f"open_meteo:{om_err or 'failed'}")

        if nws_data is not None:
            nws_flood_alert, nws_alerts = _parse_nws_alerts(nws_data)
            nws_status = "live"
        else:
            nws_flood_alert, nws_alerts = False, []
            nws_status = "error"
            errors.append(f"nws:{nws_err or 'failed'}")

        risk_level = _compute_risk_level(
            next_6h_mm=next_6h_mm,
            next_24h_mm=next_24h_mm,
            peak_mm_h=peak_mm_h,
            nws_flood_alert=nws_flood_alert,
        )

        wall_ms = int(round((time.perf_counter() - t0) * 1000))
        result = copy.deepcopy(city)
        result.update(
            {
                "ts": _iso_utc_now(),
                "next_6h_mm": next_6h_mm,
                "next_24h_mm": next_24h_mm,
                "peak_mm_h": peak_mm_h,
                "peak_t": peak_t,
                "nws_flood_alert": nws_flood_alert,
                "nws_alerts": nws_alerts,
                "risk_level": risk_level,
                "sources": {"open_meteo": om_status, "nws": nws_status},
                "errors": errors,
                "ok": om_status == "live" or nws_status == "live",
                "wall_ms": wall_ms,
            }
        )
        return result
    except Exception as exc:
        wall_ms = int(round((time.perf_counter() - t0) * 1000))
        city_meta = _CITY_BY_ID.get(str(city_id or "").strip().lower())
        if city_meta is not None:
            return _fallback_status(city_meta, f"error:{type(exc).__name__}", wall_ms=wall_ms)
        return {
            "id": str(city_id or ""),
            "name": str(city_id or "unknown"),
            "ts": _iso_utc_now(),
            "next_6h_mm": 0.0,
            "next_24h_mm": 0.0,
            "peak_mm_h": 0.0,
            "peak_t": None,
            "nws_flood_alert": False,
            "nws_alerts": [],
            "risk_level": "clear",
            "sources": {"open_meteo": "error", "nws": "error"},
            "errors": [f"error:{type(exc).__name__}"],
            "ok": False,
            "wall_ms": wall_ms,
        }


def sweep_all_cities(timeout_s: float = 6.0) -> dict[str, Any]:
    """Run `live_city_status` across all 7 US AV markets in parallel. Never raises."""
    t0 = time.perf_counter()
    try:
        try:
            outer_timeout = max(0.5, float(timeout_s))
        except Exception:
            outer_timeout = 6.0
        per_city_timeout = min(MAX_HTTP_TIMEOUT_S, max(0.5, outer_timeout - 0.5))

        results_by_id: dict[str, dict[str, Any]] = {}
        pool = ThreadPoolExecutor(max_workers=len(_CITIES))
        try:
            fut_to_city = {
                pool.submit(live_city_status, city["id"], per_city_timeout): city
                for city in _CITIES
            }
            done, not_done = wait(fut_to_city.keys(), timeout=outer_timeout)
            for fut in done:
                city = fut_to_city[fut]
                try:
                    results_by_id[city["id"]] = fut.result(timeout=0)
                except Exception as exc:
                    results_by_id[city["id"]] = _fallback_status(
                        city,
                        f"error:{type(exc).__name__}",
                        wall_ms=int(round((time.perf_counter() - t0) * 1000)),
                    )
            for fut in not_done:
                city = fut_to_city[fut]
                results_by_id[city["id"]] = _fallback_status(
                    city,
                    "sweep_timeout",
                    wall_ms=int(round((time.perf_counter() - t0) * 1000)),
                )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        cities_out = [results_by_id[c["id"]] for c in _CITIES]
        n_total = len(cities_out)
        n_live = sum(1 for c in cities_out if c.get("ok"))
        n_open_meteo_live = sum(
            1 for c in cities_out if (c.get("sources") or {}).get("open_meteo") == "live"
        )
        n_nws_live = sum(
            1 for c in cities_out if (c.get("sources") or {}).get("nws") == "live"
        )
        n_pullback = sum(1 for c in cities_out if c.get("risk_level") == "pullback_active")
        n_watch = sum(1 for c in cities_out if c.get("risk_level") == "watch")
        n_clear = sum(1 for c in cities_out if c.get("risk_level") == "clear")
        n_flood_alerts = sum(1 for c in cities_out if c.get("nws_flood_alert"))
        wall_ms = int(round((time.perf_counter() - t0) * 1000))

        summary = (
            f"{n_live}/{n_total} US AV markets live in {wall_ms / 1000:.2f}s "
            f"· {n_pullback} pullback_active, {n_watch} watch, {n_clear} clear "
            f"· {n_flood_alerts} active NWS flood alert(s)"
        )

        return {
            "ts": _iso_utc_now(),
            "n_cities": n_total,
            "n_live": n_live,
            "n_open_meteo_live": n_open_meteo_live,
            "n_nws_live": n_nws_live,
            "n_pullback": n_pullback,
            "n_watch": n_watch,
            "n_clear": n_clear,
            "n_nws_flood_alerts": n_flood_alerts,
            "wall_ms": wall_ms,
            "summary": summary,
            "cities": cities_out,
        }
    except Exception as exc:
        wall_ms = int(round((time.perf_counter() - t0) * 1000))
        fallback_cities = [_fallback_status(c, f"error:{type(exc).__name__}", wall_ms=wall_ms) for c in _CITIES]
        return {
            "ts": _iso_utc_now(),
            "n_cities": len(fallback_cities),
            "n_live": 0,
            "n_open_meteo_live": 0,
            "n_nws_live": 0,
            "n_pullback": 0,
            "n_watch": 0,
            "n_clear": len(fallback_cities),
            "n_nws_flood_alerts": 0,
            "wall_ms": wall_ms,
            "summary": f"0/{len(fallback_cities)} US AV markets live (sweep error)",
            "cities": fallback_cities,
        }


def load_cached_snapshot() -> dict[str, Any] | None:
    """Load `media/cities_snapshot.json` if present and valid JSON. Never raises."""
    try:
        if not SNAPSHOT_PATH.is_file():
            return None
        data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _format_table(sweep: dict[str, Any]) -> str:
    cities = sweep.get("cities") or []
    header = (
        f"{'ID':<12} {'CITY':<15} {'RISK':<16} {'6H_MM':>6} {'24H_MM':>7} "
        f"{'PEAK':>6} {'PEAK_TIME':<17} {'NWS_FLD':<8} {'MS':>5}  OPERATORS"
    )
    sep = "-" * len(header)
    lines = [header, sep]
    for c in cities:
        peak_t = str(c.get("peak_t") or "-")
        nws_fld = "YES" if c.get("nws_flood_alert") else "no"
        ops = ", ".join(c.get("av_operators") or [])
        lines.append(
            f"{str(c.get('id', '')):<12} "
            f"{str(c.get('name', '')):<15} "
            f"{str(c.get('risk_level', 'clear')).upper():<16} "
            f"{float(c.get('next_6h_mm', 0.0)):>6.2f} "
            f"{float(c.get('next_24h_mm', 0.0)):>7.2f} "
            f"{float(c.get('peak_mm_h', 0.0)):>6.2f} "
            f"{peak_t:<17} "
            f"{nws_fld:<8} "
            f"{int(c.get('wall_ms', 0)):>5}  "
            f"{ops}"
        )
    lines.append(sep)
    lines.append(str(sweep.get("summary") or ""))
    return "\n".join(lines)


def main() -> int:
    try:
        sweep = sweep_all_cities()
        try:
            SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
            SNAPSHOT_PATH.write_text(json.dumps(sweep, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass
        print(_format_table(sweep))
        return 0
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
