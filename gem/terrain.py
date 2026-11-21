"""Wildcard #7: Live SF Hydrology Grounding Pack (`gem.terrain`).

Grounds any San Francisco block coordinate in 4 live public hydrology & terrain feeds:
1. Topographic sink depth via USGS 3DEP (`epqs.nationalmap.gov`) with automatic fallback
   to USGS NED 10m DEM (`api.opentopodata.org/v1/ned10m`) and Open-Meteo DEM.
2. Stormwater drainage density via DataSF SFPUC Stormwater Inlets & Catch Basins (`jtgq-b7c5`).
3. SF Bay tidal backpressure via NOAA CO-OPS Station 9414290 (San Francisco / Fort Point).
4. Active flood weather alerts via NWS (`api.weather.gov/alerts/active`).

Pure Python stdlib. Zero imports from `pipeline/`. Every network call enforces a strict
timeout (<= 4.0s) and graceful fallback (including `media/hydrology_cache.json`) and
NEVER raises to its caller.
"""
from __future__ import annotations

import json
import math
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "media" / "hydrology_cache.json"

USER_AGENT = "FloodPullBackSF/1.0 (ops@example.com)"
MAX_NETWORK_TIMEOUT_S = 4.0
M_TO_FT = 3.280839895

# ~150m N/S/E/W offsets at SF latitude (~37.77 N)
DELTA_LAT_150M = 0.0014
DELTA_LON_150M = 0.0017
SINK_THRESHOLD_FT = 1.0
HIGH_TIDE_THRESHOLD_FT = 5.5

USGS_EPQS_URL = "https://epqs.nationalmap.gov/v1/json"
OPENTOPO_NED10M_URL = "https://api.opentopodata.org/v1/ned10m"
OPEN_METEO_ELEV_URL = "https://api.open-meteo.com/v1/elevation"
DATASF_INLETS_URL = "https://data.sfgov.org/resource/jtgq-b7c5.json"
NOAA_DATAGETTER_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"

NOAA_STATION_SF = "9414290"
NOAA_STATION_NAME = "San Francisco (Fort Point)"

DEMO_BLOCKS: tuple[tuple[str, str, float, float], ...] = (
    ("r50_c66", "4th St & King St", 37.7764, -122.3939),
    ("r52_c52", "Grove St & Van Ness Ave", 37.7785, -122.4193),
    ("r53_c68", "691 2nd St", 37.7805, -122.3910),
    ("r39_c57", "20th St & Alabama/Florida", 37.7593, -122.4108),
)

_OPENTOPO_LOCK = threading.Lock()
_OPENTOPO_LAST_CALL = 0.0
_OPENTOPO_MIN_INTERVAL_S = 1.05


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clamp_timeout(timeout_s: float, ceiling: float = MAX_NETWORK_TIMEOUT_S) -> float:
    try:
        val = float(timeout_s)
    except Exception:
        val = ceiling
    if not math.isfinite(val) or val <= 0:
        return min(1.0, ceiling)
    return max(0.2, min(val, ceiling))


def _normalize_date(date: str) -> tuple[str, str]:
    """Return (YYYY-MM-DD, YYYYMMDD) from an input date string; never raises."""
    raw = str(date or "2026-11-18").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 8:
        ymd = digits[:8]
        return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}", ymd
    return "2026-11-18", "20261118"


def _make_ssl_context() -> ssl.SSLContext | None:
    try:
        return ssl.create_default_context()
    except Exception:
        return None


def _http_get_json(
    url: str,
    timeout_s: float = MAX_NETWORK_TIMEOUT_S,
    headers: dict[str, str] | None = None,
) -> tuple[Any | None, str | None]:
    """Perform a bounded HTTP GET and parse JSON. Returns (data, error_str). Never raises."""
    t_eff = _clamp_timeout(timeout_s, MAX_NETWORK_TIMEOUT_S)
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    try:
        req = urllib.request.Request(url, headers=req_headers, method="GET")
        ctx = _make_ssl_context()
        with urllib.request.urlopen(req, timeout=t_eff, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _load_cache(cache_path: Path = CACHE_PATH) -> dict[str, Any]:
    """Load `media/hydrology_cache.json` safely. Returns empty dict on error."""
    try:
        if not cache_path.exists():
            return {}
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = (lat2 - lat1) * 111_320.0
    dlon = (lon2 - lon1) * 111_320.0 * math.cos(math.radians(0.5 * (lat1 + lat2)))
    return math.hypot(dlat, dlon)


def _find_cached_block(
    cache: dict[str, Any],
    lat: float,
    lon: float,
    max_dist_m: float = 350.0,
) -> dict[str, Any] | None:
    blocks = cache.get("blocks")
    if not isinstance(blocks, dict):
        return None
    best: dict[str, Any] | None = None
    best_d = max_dist_m
    for entry in blocks.values():
        if not isinstance(entry, dict):
            continue
        try:
            d = _dist_m(lat, lon, float(entry["lat"]), float(entry["lon"]))
        except Exception:
            continue
        if d <= best_d:
            best_d = d
            best = entry
    return best


def _valid_elev_ft(val: Any) -> float | None:
    try:
        v = float(val)
    except Exception:
        return None
    if not math.isfinite(v) or v < -500.0 or v > 20_000.0:
        return None
    return v


def _query_usgs_epqs_5pts(
    pts: list[tuple[str, float, float]],
    timeout_s: float,
) -> tuple[dict[str, float] | None, str | None]:
    """Query USGS 3DEP EPQS in parallel for 5 (label, lat, lon) points."""
    t_eff = _clamp_timeout(timeout_s, MAX_NETWORK_TIMEOUT_S)

    def _one(item: tuple[str, float, float]) -> tuple[str, float | None, str | None]:
        label, la, lo = item
        q = urllib.parse.urlencode(
            {"x": f"{lo:.6f}", "y": f"{la:.6f}", "wkid": 4326, "units": "Feet"}
        )
        data, err = _http_get_json(f"{USGS_EPQS_URL}?{q}", timeout_s=t_eff)
        if err or not isinstance(data, dict):
            return label, None, err or "invalid JSON"
        v = _valid_elev_ft(data.get("value"))
        if v is None:
            return label, None, f"nodata value={data.get('value')!r}"
        return label, v, None

    out: dict[str, float] = {}
    last_err: str | None = None
    try:
        with ThreadPoolExecutor(max_workers=len(pts)) as pool:
            futs = [pool.submit(_one, p) for p in pts]
            done, _ = wait(futs, timeout=t_eff + 0.35)
            for fut in done:
                try:
                    label, val, err = fut.result(timeout=0.05)
                except Exception as exc:
                    last_err = f"{type(exc).__name__}: {exc}"
                    continue
                if val is not None:
                    out[label] = val
                elif err:
                    last_err = err
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"

    if len(out) == len(pts):
        return out, None
    return None, last_err or f"usgs_epqs incomplete ({len(out)}/{len(pts)})"


def _query_opentopo_ned10m_5pts(
    pts: list[tuple[str, float, float]],
    timeout_s: float,
) -> tuple[dict[str, float] | None, str | None]:
    """Fallback: USGS NED 10m DEM via OpenTopoData batch endpoint (meters -> feet)."""
    global _OPENTOPO_LAST_CALL
    t_eff = _clamp_timeout(timeout_s, MAX_NETWORK_TIMEOUT_S)
    try:
        with _OPENTOPO_LOCK:
            now = time.monotonic()
            wait_s = _OPENTOPO_MIN_INTERVAL_S - (now - _OPENTOPO_LAST_CALL)
            if wait_s > 0:
                if wait_s > max(0.0, t_eff - 0.6):
                    return None, "rate-limit wait exceeds timeout budget"
                time.sleep(wait_s)
            _OPENTOPO_LAST_CALL = time.monotonic()
            rem = _clamp_timeout(t_eff - max(0.0, wait_s), MAX_NETWORK_TIMEOUT_S)
            locs = "|".join(f"{la:.6f},{lo:.6f}" for _, la, lo in pts)
            url = f"{OPENTOPO_NED10M_URL}?locations={urllib.parse.quote(locs, safe=',|')}"
            data, err = _http_get_json(url, timeout_s=rem)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"

    if err or not isinstance(data, dict):
        return None, err or "invalid JSON"
    results = data.get("results")
    if not isinstance(results, list) or len(results) != len(pts):
        return None, f"unexpected results length ({type(results).__name__})"

    out: dict[str, float] = {}
    for (label, _, _), row in zip(pts, results):
        if not isinstance(row, dict):
            return None, "malformed row"
        raw_m = row.get("elevation")
        if raw_m is None:
            return None, "null elevation"
        v = _valid_elev_ft(float(raw_m) * M_TO_FT)
        if v is None:
            return None, f"invalid elevation={raw_m!r}"
        out[label] = v
    return out, None


def _query_open_meteo_5pts(
    pts: list[tuple[str, float, float]],
    timeout_s: float,
) -> tuple[dict[str, float] | None, str | None]:
    """Secondary fallback: Open-Meteo Copernicus DEM batch endpoint (meters -> feet)."""
    t_eff = _clamp_timeout(timeout_s, MAX_NETWORK_TIMEOUT_S)
    lats = ",".join(f"{la:.6f}" for _, la, _ in pts)
    lons = ",".join(f"{lo:.6f}" for _, _, lo in pts)
    url = f"{OPEN_METEO_ELEV_URL}?latitude={lats}&longitude={lons}"
    data, err = _http_get_json(url, timeout_s=t_eff)
    if err or not isinstance(data, dict):
        return None, err or "invalid JSON"
    vals = data.get("elevation")
    if not isinstance(vals, list) or len(vals) != len(pts):
        return None, "unexpected elevation array"
    out: dict[str, float] = {}
    for (label, _, _), raw_m in zip(pts, vals):
        if raw_m is None:
            return None, "null elevation"
        v = _valid_elev_ft(float(raw_m) * M_TO_FT)
        if v is None:
            return None, f"invalid elevation={raw_m!r}"
        out[label] = v
    return out, None


def elevation_sink(lat: float, lon: float, timeout_s: float = 4.0) -> dict[str, Any]:
    """Compute topographic sink depth at (lat, lon) vs 4 neighbors ~150m N/S/E/W.

    Tries USGS 3DEP EPQS first in parallel; if unavailable/timed out within budget,
    falls back cleanly to USGS NED 10m (`ned10m`) and then Open-Meteo DEM, and finally
    to `media/hydrology_cache.json`. Never raises.
    """
    t0 = time.monotonic()
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception as exc:
        return {
            "elevation_ft": None,
            "neighbor_mean_ft": None,
            "sink_depth_ft": 0.0,
            "is_sink": False,
            "source": "unavailable",
            "ok": False,
            "error": f"invalid coordinates: {exc}",
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        }

    total_budget = _clamp_timeout(timeout_s, MAX_NETWORK_TIMEOUT_S)
    pts: list[tuple[str, float, float]] = [
        ("center", lat_f, lon_f),
        ("N", lat_f + DELTA_LAT_150M, lon_f),
        ("S", lat_f - DELTA_LAT_150M, lon_f),
        ("E", lat_f, lon_f + DELTA_LON_150M),
        ("W", lat_f, lon_f - DELTA_LON_150M),
    ]

    errors: list[str] = []
    elev_map: dict[str, float] | None = None
    source = "unavailable"

    # 1. Primary: USGS 3DEP EPQS in parallel (bounded share of timeout budget)
    epqs_budget = min(1.8, max(0.6, total_budget * 0.45))
    elev_map, err = _query_usgs_epqs_5pts(pts, timeout_s=epqs_budget)
    if elev_map is not None:
        source = "usgs_3dep_epqs"
    else:
        if err:
            errors.append(f"usgs_3dep_epqs: {err}")

        # 2. Fallback 1: USGS NED 10m DEM via OpenTopoData
        rem = total_budget - (time.monotonic() - t0)
        if rem >= 0.4:
            elev_map, err2 = _query_opentopo_ned10m_5pts(pts, timeout_s=min(rem, 2.5))
            if elev_map is not None:
                source = "usgs_ned10m"
            elif err2:
                errors.append(f"usgs_ned10m: {err2}")

        # 3. Fallback 2: Open-Meteo Copernicus DEM
        if elev_map is None:
            rem = total_budget - (time.monotonic() - t0)
            if rem >= 0.35:
                elev_map, err3 = _query_open_meteo_5pts(pts, timeout_s=min(rem, 2.0))
                if elev_map is not None:
                    source = "open_meteo_dem"
                elif err3:
                    errors.append(f"open_meteo_dem: {err3}")

    if elev_map is not None:
        elev_ft = round(elev_map["center"], 2)
        neighbor_mean_ft = round(
            (elev_map["N"] + elev_map["S"] + elev_map["E"] + elev_map["W"]) / 4.0,
            2,
        )
        sink_depth_ft = round(neighbor_mean_ft - elev_ft, 2)
        return {
            "lat": round(lat_f, 6),
            "lon": round(lon_f, 6),
            "elevation_ft": elev_ft,
            "neighbor_mean_ft": neighbor_mean_ft,
            "sink_depth_ft": sink_depth_ft,
            "is_sink": bool(sink_depth_ft > SINK_THRESHOLD_FT),
            "neighbors_ft": {
                k: round(elev_map[k], 2) for k in ("N", "S", "E", "W")
            },
            "source": source,
            "ok": True,
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        }

    # 4. Offline cache fallback
    cached = _find_cached_block(_load_cache(), lat_f, lon_f)
    if cached and isinstance(cached.get("elevation"), dict) and cached["elevation"].get("ok"):
        res = dict(cached["elevation"])
        res["from_cache"] = True
        res["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
        return res

    return {
        "lat": round(lat_f, 6),
        "lon": round(lon_f, 6),
        "elevation_ft": None,
        "neighbor_mean_ft": None,
        "sink_depth_ft": 0.0,
        "is_sink": False,
        "source": "unavailable",
        "ok": False,
        "error": "; ".join(errors) or "elevation lookup failed",
        "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
    }


def _detect_datasf_geom_col(timeout_s: float) -> str:
    """Inspect 1 row of jtgq-b7c5 to identify its GeoJSON geometry column name."""
    data, err = _http_get_json(f"{DATASF_INLETS_URL}?$limit=1", timeout_s=timeout_s)
    if not err and isinstance(data, list) and data and isinstance(data[0], dict):
        row = data[0]
        for key in ("location", "the_geom", "geom", "shape", "point"):
            val = row.get(key)
            if isinstance(val, dict) and "coordinates" in val:
                return key
        for key, val in row.items():
            if isinstance(val, dict) and val.get("type") == "Point":
                return key
    return "location"


def nearby_inlets(
    lat: float,
    lon: float,
    radius_m: int = 200,
    timeout_s: float = 4.0,
) -> dict[str, Any]:
    """Count SFPUC stormwater inlets & catch basins within `radius_m` via DataSF `jtgq-b7c5`.

    Never raises.
    """
    t0 = time.monotonic()
    try:
        lat_f = float(lat)
        lon_f = float(lon)
        rad_i = max(1, int(radius_m))
    except Exception as exc:
        return {
            "count": 0,
            "radius_m": 200,
            "source": "sfpuc_jtgq-b7c5",
            "ok": False,
            "error": f"invalid args: {exc}",
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        }

    t_eff = _clamp_timeout(timeout_s, MAX_NETWORK_TIMEOUT_S)

    def _query_col(geom_col: str, budget: float) -> tuple[list[Any] | None, str | None]:
        q = urllib.parse.urlencode(
            {
                "$limit": 200,
                "$where": f"within_circle({geom_col},{lat_f:.6f},{lon_f:.6f},{rad_i})",
            }
        )
        data, err = _http_get_json(f"{DATASF_INLETS_URL}?{q}", timeout_s=budget)
        if err:
            return None, err
        if isinstance(data, list):
            return data, None
        return None, f"unexpected response type {type(data).__name__}"

    # Verified schema column for jtgq-b7c5 is `location` (GeoJSON Point).
    rows, err = _query_col("location", t_eff)
    if rows is None:
        rem = t_eff - (time.monotonic() - t0)
        if rem >= 0.8:
            geom_col = _detect_datasf_geom_col(min(rem * 0.5, 1.5))
            if geom_col != "location":
                rem2 = t_eff - (time.monotonic() - t0)
                if rem2 >= 0.4:
                    rows, err = _query_col(geom_col, rem2)

    if rows is not None:
        return {
            "count": len(rows),
            "radius_m": rad_i,
            "source": "sfpuc_jtgq-b7c5",
            "ok": True,
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        }

    # Offline cache fallback
    cached = _find_cached_block(_load_cache(), lat_f, lon_f)
    if cached and isinstance(cached.get("inlets"), dict) and cached["inlets"].get("ok"):
        res = dict(cached["inlets"])
        res["from_cache"] = True
        res["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
        return res

    return {
        "count": 0,
        "radius_m": rad_i,
        "source": "sfpuc_jtgq-b7c5",
        "ok": False,
        "error": err or "datasf query failed",
        "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
    }


def _parse_noaa_rows(rows: Any) -> list[tuple[str, float]]:
    parsed: list[tuple[str, float]] = []
    if not isinstance(rows, list):
        return parsed
    for item in rows:
        if not isinstance(item, dict):
            continue
        t_raw = str(item.get("t") or "").strip()
        v_raw = item.get("v")
        try:
            v_f = float(v_raw)
        except Exception:
            continue
        if t_raw and math.isfinite(v_f):
            parsed.append((t_raw, v_f))
    return parsed


def sf_bay_tide(date: str = "2026-11-18", timeout_s: float = 4.0) -> dict[str, Any]:
    """Query NOAA CO-OPS Station 9414290 (SF Fort Point) for daily peak tide (MLLW, ft).

    Tries `hourly_height` first and falls back to `predictions` (e.g. for future or
    unverified dates), then `media/hydrology_cache.json`. Never raises.
    """
    t0 = time.monotonic()
    date_str, ymd = _normalize_date(date)
    t_eff = _clamp_timeout(timeout_s, MAX_NETWORK_TIMEOUT_S)
    errors: list[str] = []

    rows: list[tuple[str, float]] = []
    used_product = ""

    # 1. Try verified hourly_height
    q_obs = urllib.parse.urlencode(
        {
            "begin_date": ymd,
            "end_date": ymd,
            "station": NOAA_STATION_SF,
            "product": "hourly_height",
            "datum": "MLLW",
            "time_zone": "lst_ldt",
            "units": "english",
            "format": "json",
        }
    )
    obs_data, obs_err = _http_get_json(
        f"{NOAA_DATAGETTER_URL}?{q_obs}",
        timeout_s=min(1.5, max(0.5, t_eff * 0.45)),
    )
    if obs_data and isinstance(obs_data, dict) and not obs_data.get("error"):
        rows = _parse_noaa_rows(obs_data.get("data"))
        if rows:
            used_product = "hourly_height"
    elif obs_err:
        errors.append(f"hourly_height: {obs_err}")

    # 2. Fallback to harmonic predictions
    if not rows:
        rem = max(0.5, t_eff - (time.monotonic() - t0))
        q_pred = urllib.parse.urlencode(
            {
                "begin_date": ymd,
                "end_date": ymd,
                "station": NOAA_STATION_SF,
                "product": "predictions",
                "datum": "MLLW",
                "time_zone": "lst_ldt",
                "units": "english",
                "interval": "h",
                "format": "json",
            }
        )
        pred_data, pred_err = _http_get_json(
            f"{NOAA_DATAGETTER_URL}?{q_pred}",
            timeout_s=min(rem, MAX_NETWORK_TIMEOUT_S),
        )
        if pred_data and isinstance(pred_data, dict) and not pred_data.get("error"):
            rows = _parse_noaa_rows(pred_data.get("predictions"))
            if rows:
                used_product = "predictions"
        elif pred_err:
            errors.append(f"predictions: {pred_err}")
        elif isinstance(pred_data, dict) and pred_data.get("error"):
            errors.append(f"predictions: {pred_data['error']}")

    if rows:
        peak_t_raw, peak_val = max(rows, key=lambda pair: pair[1])
        min_val = min(pair[1] for pair in rows)
        peak_tide_ft = round(peak_val, 2)
        parts = peak_t_raw.split()
        peak_hhmm = parts[-1][:5] if parts else peak_t_raw[:5]
        return {
            "station": NOAA_STATION_SF,
            "station_name": NOAA_STATION_NAME,
            "date": date_str,
            "peak_tide_ft": peak_tide_ft,
            "min_tide_ft": round(min_val, 2),
            "peak_t": peak_hhmm,
            "high_tide_backpressure": bool(peak_tide_ft >= HIGH_TIDE_THRESHOLD_FT),
            "product": used_product,
            "datum": "MLLW",
            "ok": True,
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        }

    # 3. Offline cache fallback
    cache = _load_cache()
    cached_tide = cache.get("tide")
    if (
        isinstance(cached_tide, dict)
        and cached_tide.get("ok")
        and cached_tide.get("date") == date_str
    ):
        res = dict(cached_tide)
        res["from_cache"] = True
        res["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
        return res

    return {
        "station": NOAA_STATION_SF,
        "station_name": NOAA_STATION_NAME,
        "date": date_str,
        "peak_tide_ft": None,
        "peak_t": None,
        "high_tide_backpressure": False,
        "product": "unavailable",
        "datum": "MLLW",
        "ok": False,
        "error": "; ".join(errors) or "noaa query failed",
        "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
    }


def nws_alerts(
    lat: float = 37.7749,
    lon: float = -122.4194,
    timeout_s: float = 4.0,
) -> dict[str, Any]:
    """Query active NWS weather alerts for (lat, lon). Never raises."""
    t0 = time.monotonic()
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception as exc:
        return {
            "n_active": 0,
            "has_flood_alert": False,
            "alerts": [],
            "ok": False,
            "error": f"invalid coordinates: {exc}",
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        }

    t_eff = _clamp_timeout(timeout_s, MAX_NETWORK_TIMEOUT_S)
    url = f"{NWS_ALERTS_URL}?point={lat_f:.4f},{lon_f:.4f}"
    data, err = _http_get_json(
        url,
        timeout_s=t_eff,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/geo+json",
        },
    )

    if not err and isinstance(data, dict):
        features = data.get("features")
        alerts: list[dict[str, str]] = []
        if isinstance(features, list):
            for feat in features:
                if not isinstance(feat, dict):
                    continue
                props = feat.get("properties")
                if not isinstance(props, dict):
                    continue
                alerts.append(
                    {
                        "event": str(props.get("event") or ""),
                        "severity": str(props.get("severity") or ""),
                        "headline": str(props.get("headline") or ""),
                    }
                )
        has_flood = any(
            "flood" in f"{a['event']} {a['headline']}".lower()
            for a in alerts
        )
        return {
            "n_active": len(alerts),
            "has_flood_alert": has_flood,
            "alerts": alerts,
            "ok": True,
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        }

    # Offline cache fallback
    cache = _load_cache()
    cached_nws = cache.get("nws")
    if isinstance(cached_nws, dict) and cached_nws.get("ok"):
        res = dict(cached_nws)
        res["from_cache"] = True
        res["elapsed_ms"] = round((time.monotonic() - t0) * 1000, 1)
        return res

    return {
        "n_active": 0,
        "has_flood_alert": False,
        "alerts": [],
        "ok": False,
        "error": err or "nws query failed",
        "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
    }


def _build_summary(
    elev: dict[str, Any],
    inlets: dict[str, Any],
    tide: dict[str, Any],
    nws: dict[str, Any],
) -> str:
    """Format a crisp 1-line hydrology grounding summary."""
    parts: list[str] = []

    if elev.get("elevation_ft") is not None:
        sink = float(elev.get("sink_depth_ft") or 0.0)
        tag = f"SINK {sink:+.1f}ft" if elev.get("is_sink") else f"relief {sink:+.1f}ft"
        parts.append(f"Elev {float(elev['elevation_ft']):.1f}ft ({tag})")
    else:
        parts.append("Elev n/a")

    if inlets.get("ok"):
        parts.append(f"{int(inlets.get('count', 0))} inlets/{int(inlets.get('radius_m', 200))}m")
    else:
        parts.append("inlets n/a")

    if tide.get("peak_tide_ft") is not None:
        bp = "HIGH-TIDE BACKPRESSURE" if tide.get("high_tide_backpressure") else "normal tide"
        parts.append(f"Bay peak {float(tide['peak_tide_ft']):.2f}ft@{tide.get('peak_t', '--:--')} ({bp})")
    else:
        parts.append("Bay tide n/a")

    if nws.get("ok"):
        n_act = int(nws.get("n_active", 0))
        if n_act > 0:
            ev_names = [a.get("event", "") for a in (nws.get("alerts") or []) if a.get("event")]
            top_ev = ev_names[0] if ev_names else "Alert"
            suffix = f" +{n_act - 1}" if n_act > 1 else ""
            parts.append(f"NWS: {top_ev}{suffix}")
        else:
            parts.append("NWS: 0 alerts")
    else:
        parts.append("NWS n/a")

    return " | ".join(parts)


def hydrology_profile(
    lat: float,
    lon: float,
    date: str = "2026-11-18",
    timeout_s: float = 6.0,
) -> dict[str, Any]:
    """Run all 4 SF hydrology grounding checks in parallel with cache fallback.

    NEVER raises.
    """
    t0 = time.monotonic()
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except Exception as exc:
        return {
            "lat": lat,
            "lon": lon,
            "date": str(date),
            "elevation": {"ok": False},
            "inlets": {"ok": False},
            "tide": {"ok": False},
            "nws": {"ok": False},
            "summary": f"Hydrology unavailable: invalid coordinates ({exc})",
            "from_cache": False,
            "ok": False,
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        }

    try:
        date_str, _ = _normalize_date(date)
        total_budget = max(0.5, float(timeout_s)) if math.isfinite(float(timeout_s)) else 6.0
        per_call = min(MAX_NETWORK_TIMEOUT_S, max(0.5, total_budget * 0.85))

        results: dict[str, dict[str, Any]] = {}
        tasks = {
            "elevation": lambda: elevation_sink(lat_f, lon_f, timeout_s=per_call),
            "inlets": lambda: nearby_inlets(lat_f, lon_f, radius_m=200, timeout_s=per_call),
            "tide": lambda: sf_bay_tide(date=date_str, timeout_s=per_call),
            "nws": lambda: nws_alerts(lat_f, lon_f, timeout_s=per_call),
        }

        with ThreadPoolExecutor(max_workers=4) as pool:
            fut_map = {pool.submit(fn): name for name, fn in tasks.items()}
            done, not_done = wait(fut_map.keys(), timeout=total_budget)
            for fut in done:
                name = fut_map[fut]
                try:
                    results[name] = fut.result(timeout=0.05)
                except Exception as exc:
                    results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            for fut in not_done:
                name = fut_map[fut]
                fut.cancel()
                results[name] = {"ok": False, "error": f"timed out after {total_budget:.1f}s"}

        # Fill any missing/failed components from local cache if available
        cache = _load_cache()
        cached_block = _find_cached_block(cache, lat_f, lon_f)

        elev = results.get("elevation", {"ok": False})
        if not elev.get("ok") and cached_block and isinstance(cached_block.get("elevation"), dict):
            if cached_block["elevation"].get("ok"):
                elev = dict(cached_block["elevation"])
                elev["from_cache"] = True

        inlets = results.get("inlets", {"ok": False})
        if not inlets.get("ok") and cached_block and isinstance(cached_block.get("inlets"), dict):
            if cached_block["inlets"].get("ok"):
                inlets = dict(cached_block["inlets"])
                inlets["from_cache"] = True

        tide = results.get("tide", {"ok": False})
        if not tide.get("ok"):
            ct = cache.get("tide")
            if isinstance(ct, dict) and ct.get("ok") and ct.get("date") == date_str:
                tide = dict(ct)
                tide["from_cache"] = True

        nws = results.get("nws", {"ok": False})
        if not nws.get("ok"):
            cn = cache.get("nws")
            if isinstance(cn, dict) and cn.get("ok"):
                nws = dict(cn)
                nws["from_cache"] = True

        any_cached = any(
            bool(part.get("from_cache"))
            for part in (elev, inlets, tide, nws)
        )
        all_ok = all(bool(part.get("ok")) for part in (elev, inlets, tide, nws))
        summary = _build_summary(elev, inlets, tide, nws)

        return {
            "lat": round(lat_f, 6),
            "lon": round(lon_f, 6),
            "date": date_str,
            "elevation": elev,
            "inlets": inlets,
            "tide": tide,
            "nws": nws,
            "summary": summary,
            "from_cache": any_cached,
            "ok": all_ok,
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        }
    except Exception as exc:
        return {
            "lat": round(lat_f, 6),
            "lon": round(lon_f, 6),
            "date": str(date),
            "elevation": {"ok": False},
            "inlets": {"ok": False},
            "tide": {"ok": False},
            "nws": {"ok": False},
            "summary": f"Hydrology error: {exc}",
            "from_cache": False,
            "ok": False,
            "elapsed_ms": round((time.monotonic() - t0) * 1000, 1),
        }


def _run_cli(date: str = "2026-11-18") -> int:
    t_start = time.monotonic()
    date_str, _ = _normalize_date(date)

    blocks_out: dict[str, dict[str, Any]] = {}
    first_tide: dict[str, Any] | None = None
    first_nws: dict[str, Any] | None = None

    for block_id, name, lat, lon in DEMO_BLOCKS:
        prof = hydrology_profile(lat, lon, date=date_str, timeout_s=6.0)
        entry = {"block_id": block_id, "name": name, **prof}
        blocks_out[block_id] = entry
        if first_tide is None and isinstance(prof.get("tide"), dict) and prof["tide"].get("ok"):
            first_tide = prof["tide"]
        if first_nws is None and isinstance(prof.get("nws"), dict) and prof["nws"].get("ok"):
            first_nws = prof["nws"]

    payload = {
        "generated_at": _iso_utc_now(),
        "date": date_str,
        "tide": first_tide or sf_bay_tide(date=date_str),
        "nws": first_nws or nws_alerts(),
        "blocks": blocks_out,
    }

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    total_ms = round((time.monotonic() - t_start) * 1000, 1)

    print(f"\nSF Live Hydrology Grounding Pack — {date_str} (total {total_ms:.0f} ms)")
    print("=" * 116)
    header = (
        f"{'Block':<8} {'Location':<26} {'Elev(ft)':>8} {'Sink(ft)':>9} "
        f"{'Sink?':<5} {'Inlets':>6} {'PeakTide':>12} {'NWS':>4} {'Time':>7}  {'ElevSrc'}"
    )
    print(header)
    print("-" * 116)
    for block_id, name, _, _ in DEMO_BLOCKS:
        b = blocks_out[block_id]
        e = b.get("elevation", {})
        inl = b.get("inlets", {})
        td = b.get("tide", {})
        nw = b.get("nws", {})

        elev_s = f"{e['elevation_ft']:.2f}" if e.get("elevation_ft") is not None else "n/a"
        sink_s = f"{e['sink_depth_ft']:+.2f}" if e.get("elevation_ft") is not None else "n/a"
        is_sink_s = "YES" if e.get("is_sink") else "no"
        inl_s = str(inl.get("count", "n/a")) if inl.get("ok") else "n/a"
        tide_s = (
            f"{td['peak_tide_ft']:.2f}@{td.get('peak_t', '--')}"
            if td.get("peak_tide_ft") is not None
            else "n/a"
        )
        nws_s = str(nw.get("n_active", "n/a")) if nw.get("ok") else "n/a"
        ms_s = f"{b.get('elapsed_ms', 0):.0f}ms"
        src_s = str(e.get("source", "n/a"))
        print(
            f"{block_id:<8} {name:<26} {elev_s:>8} {sink_s:>9} "
            f"{is_sink_s:<5} {inl_s:>6} {tide_s:>12} {nws_s:>4} {ms_s:>7}  {src_s}"
        )
    print("-" * 116)
    for block_id, name, _, _ in DEMO_BLOCKS:
        print(f"  {block_id} ({name}): {blocks_out[block_id]['summary']}")

    nws_top = payload.get("nws") or {}
    if nws_top.get("alerts"):
        print("\nActive NWS Alerts:")
        for a in nws_top["alerts"]:
            print(f"  - [{a.get('severity', '')}] {a.get('event', '')}: {a.get('headline', '')}")

    print(f"\nSaved cache -> {CACHE_PATH}")
    return 0


if __name__ == "__main__":
    cli_date = sys.argv[1] if len(sys.argv) > 1 else "2026-11-18"
    raise SystemExit(_run_cli(date=cli_date))
