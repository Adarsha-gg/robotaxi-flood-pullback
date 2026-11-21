"""G3: Forecast-based flood zone planner using Gemini 4 Carbon + Decision 1.

Exposes:
    propose_zones(cells: list, forecast: dict, date: str) -> dict

CLI:
    .venv/bin/python -m gem.plan 2026-11-18
"""
from __future__ import annotations

import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any

from google.genai import types
from pydantic import BaseModel, Field

from gem.client import REPO_ROOT, get_beta_client, get_client

DEFAULT_GRID = {
    "lat0": 37.70,
    "lon0": -122.52,
    "dlat": 0.0015,
    "dlon": 0.0019,
}
SF_CELLS = 4340  # ~121 km^2 SF land area / ~0.0279 km^2 per cell
AREA_CAP_CELLS = int(0.08 * SF_CELLS)  # 347 cells = 8.0% of SF
MAX_ZONES = 12
MIN_ANCHOR_STORM_DAYS = 10
CORRIDOR_RADII = (1.5, 2.5, 3.5, 4.5)
TOP_CANDIDATE_BASINS = 16

DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


class ProposedZoneDraft(BaseModel):
    name: str = Field(description="Short human-readable neighborhood or intersection corridor name")
    cluster_id: str = Field(
        description="Exact single candidate cluster_id from the provided list (e.g. 'k1')"
    )
    start: str = Field(description="Zone start time in naive local ISO format YYYY-MM-DDTHH:MM")
    end: str = Field(description="Zone end time in naive local ISO format YYYY-MM-DDTHH:MM")
    reason: str = Field(
        description="Plain-language explanation referencing 24h total / 6h rain sums and citing at least one exact YYYY-MM-DD date from that cluster's storm_days"
    )


class ProposedPlanDraft(BaseModel):
    zones: list[ProposedZoneDraft] = Field(
        description="List of 10 to 12 distinct flood zone objects, one per selected cluster_id"
    )


def _parse_cell_id(cid: str) -> tuple[int, int]:
    r_part, c_part = cid.split("_")
    return int(r_part[1:]), int(c_part[1:])


def _cell_center(cid: str, grid: dict[str, float]) -> tuple[float, float]:
    """Return (lon, lat) center of cell."""
    r, c = _parse_cell_id(cid)
    lat = grid["lat0"] + (r + 0.5) * grid["dlat"]
    lon = grid["lon0"] + (c + 0.5) * grid["dlon"]
    return lon, lat


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Andrew's monotone chain convex hull on (lon, lat) points."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def build_padded_hull(cell_ids: list[str], grid: dict[str, float]) -> list[list[float]]:
    """Convex hull of cell centers padded by half a cell (dlat/2, dlon/2), closed [lon, lat] ring."""
    half_lat = grid["dlat"] / 2.0
    half_lon = grid["dlon"] / 2.0
    corners: list[tuple[float, float]] = []
    for cid in cell_ids:
        lon, lat = _cell_center(cid, grid)
        for dl in (-half_lon, half_lon):
            for da in (-half_lat, half_lat):
                corners.append((round(lon + dl, 6), round(lat + da, 6)))
    hull = _convex_hull(corners)
    if not hull:
        return []
    ring = [list(p) for p in hull]
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return ring


def _point_in_polygon(lon: float, lat: float, poly: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon check (inclusive of boundary via small tolerance)."""
    if len(poly) < 3:
        return False
    eps = 1e-9
    inside = False
    n = len(poly)
    for i in range(n - 1):
        x1, y1 = poly[i]
        x2, y2 = poly[i + 1]
        if min(x1, x2) - eps <= lon <= max(x1, x2) + eps and min(y1, y2) - eps <= lat <= max(y1, y2) + eps:
            cross = abs((lon - x1) * (y2 - y1) - (lat - y1) * (x2 - x1))
            if cross <= eps * max(1.0, abs(x2 - x1) + abs(y2 - y1)):
                return True
        if (y1 > lat) != (y2 > lat):
            x_int = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < x_int:
                inside = not inside
    return inside


def cells_inside_polygon(poly: list[list[float]], grid: dict[str, float]) -> list[str]:
    """Return all grid cell IDs whose centers fall inside the polygon."""
    if len(poly) < 4:
        return []
    lons = [p[0] for p in poly]
    lats = [p[1] for p in poly]
    r_min = max(0, int(math.floor((min(lats) - grid["lat0"]) / grid["dlat"])))
    r_max = int(math.ceil((max(lats) - grid["lat0"]) / grid["dlat"]))
    c_min = max(0, int(math.floor((min(lons) - grid["lon0"]) / grid["dlon"])))
    c_max = int(math.ceil((max(lons) - grid["lon0"]) / grid["dlon"]))

    inside: list[str] = []
    for r in range(r_min, r_max + 1):
        lat = grid["lat0"] + (r + 0.5) * grid["dlat"]
        for c in range(c_min, c_max + 1):
            lon = grid["lon0"] + (c + 0.5) * grid["dlon"]
            if _point_in_polygon(lon, lat, poly):
                inside.append(f"r{r}_c{c}")
    return inside


def _polygon_area_km2(poly: list[list[float]]) -> float:
    """Approximate planar area of a [lon, lat] polygon in km^2 at SF latitude."""
    if len(poly) < 4:
        return 0.0
    lat_km = 111.0
    lon_km = 111.0 * math.cos(math.radians(37.77))
    area2 = 0.0
    for i in range(len(poly) - 1):
        x1, y1 = poly[i][0] * lon_km, poly[i][1] * lat_km
        x2, y2 = poly[i + 1][0] * lon_km, poly[i + 1][1] * lat_km
        area2 += x1 * y2 - x2 * y1
    return abs(area2) / 2.0


def _six_hour_sums(hours: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mm = [float(h.get("mm", 0.0)) for h in hours]
    out = []
    for i, h in enumerate(hours):
        s6 = round(sum(mm[max(0, i - 5) : i + 1]), 1)
        out.append({"t": h["t"], "mm": round(mm[i], 1), "sum_6h_mm": s6})
    return out


def _clean_time(ts: str, date: str, fallback: str) -> str:
    """Normalize a timestamp string to YYYY-MM-DDTHH:MM on `date`."""
    if not isinstance(ts, str):
        return fallback
    ts = ts.strip()
    m = re.search(r"(\d{2}:\d{2})", ts)
    if not m:
        return fallback
    hhmm = m.group(1)
    hh, mm = int(hhmm[:2]), int(hhmm[3:])
    if hh == 24 and mm == 0:
        return f"{date}T23:59"
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return fallback
    return f"{date}T{hh:02d}:{mm:02d}"


MIN_STORM_DAYS = 2
WAYMO_ALPHA = 0.50  # CPUC 2026 Q3 Waymo tract weight (strictly pre-Nov-18, zero leakage)


def _load_waymo_tracts() -> list[tuple[tuple[float, float, float, float], list[list[list[float]]], int]]:
    """Load CPUC Q3 2026 Waymo active tract polygons (strictly pre-Nov-18)."""
    path = REPO_ROOT / "data" / "waymo_sf.geojson"
    if not path.exists():
        return []
    try:
        geo = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    tracts: list[tuple[tuple[float, float, float, float], list[list[list[float]]], int]] = []
    for feat in geo.get("features", []):
        coll = int((feat.get("properties") or {}).get("waymo_collisions_q3", 0) or 0)
        if coll <= 0:
            continue
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates") or []
        rings = [coords[0]] if gtype == "Polygon" and coords else [p[0] for p in coords if p] if gtype == "MultiPolygon" else []
        if not rings:
            continue
        xs = [pt[0] for r in rings for pt in r]
        ys = [pt[1] for r in rings for pt in r]
        tracts.append(((min(xs), min(ys), max(xs), max(ys)), rings, coll))
    return tracts


def _cell_waymo_collisions(
    lon: float,
    lat: float,
    tracts: list[tuple[tuple[float, float, float, float], list[list[list[float]]], int]],
) -> int:
    for bbox, rings, coll in tracts:
        if bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]:
            for ring in rings:
                if _point_in_polygon(lon, lat, ring):
                    return coll
    return 0


def _ward_cluster_cells(
    cell_ids: list[str],
    target_k: int,
) -> list[list[str]]:
    """Pure-Python Ward hierarchical clustering on grid (row, col) into compact corridors."""
    if len(cell_ids) <= target_k:
        return [[cid] for cid in cell_ids]
    clusters: list[dict[str, Any]] = []
    for cid in cell_ids:
        r, c = _parse_cell_id(cid)
        clusters.append({"ids": [cid], "sr": float(r), "sc": float(c)})
    while len(clusters) > target_k:
        best_d = 1e18
        bi, bj = 0, 1
        n_cl = len(clusters)
        for i in range(n_cl):
            ni = len(clusters[i]["ids"])
            ri = clusters[i]["sr"] / ni
            ci = clusters[i]["sc"] / ni
            for j in range(i + 1, n_cl):
                nj = len(clusters[j]["ids"])
                rj = clusters[j]["sr"] / nj
                cj = clusters[j]["sc"] / nj
                d = (ni * nj / (ni + nj)) * ((ri - rj) ** 2 + (ci - cj) ** 2)
                if d < best_d:
                    best_d, bi, bj = d, i, j
        a, b = clusters[bi], clusters[bj]
        a["ids"].extend(b["ids"])
        a["sr"] += b["sr"]
        a["sc"] += b["sc"]
        clusters.pop(bj)
    return [cl["ids"] for cl in clusters]


def _build_candidate_basins(
    cell_list: list[dict[str, Any]],
    grid: dict[str, float],
    forecast_peak6: float = 0.0,
    total_mm: float = 0.0,
) -> list[dict[str, Any]]:
    peak6 = float(forecast_peak6 or 0.0)
    if total_mm > 0 and total_mm < 20.0:
        # Scale down area budget proportionally on light-rain days (e.g., ~9 mm)
        cell_cap = min(AREA_CAP_CELLS, max(45, int(AREA_CAP_CELLS * (total_mm / 25.0))))
        target_k = max(3, min(6, int(round(cell_cap / 25.0))))
    else:
        cell_cap = AREA_CAP_CELLS
        target_k = MAX_ZONES

    all_by_id = {c["id"]: c for c in cell_list}
    rc_map = {_parse_cell_id(c["id"]): c for c in cell_list}
    waymo_tracts = _load_waymo_tracts()

    # Watershed-smoothed basin score * CPUC Q3 Waymo tract weight (strictly pre-Nov-18)
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for c in cell_list:
        if (
            int(c.get("n_storm_days", 0)) < MIN_STORM_DAYS
            or c.get("thresh_mm_6h") is None
            or peak6 < float(c["thresh_mm_6h"])
        ):
            continue
        r, col = _parse_cell_id(c["id"])
        nbr_sd = sum(
            int(rc_map[(r + dr, col + dc)].get("n_storm_days", 0))
            for dr in (-1, 0, 1)
            for dc in (-1, 0, 1)
            if (dr or dc) and (r + dr, col + dc) in rc_map
        )
        watershed = float(c["n_storm_days"]) + 0.05 * nbr_sd
        coll = _cell_waymo_collisions(float(c["lon"]), float(c["lat"]), waymo_tracts) if waymo_tracts else 0
        weight = 1.0 + WAYMO_ALPHA * math.log1p(coll)
        scored.append((watershed * weight, coll, c))

    if not scored and cell_list:
        for c in cell_list[:60]:
            scored.append((float(c.get("n_storm_days", 1)), 0, c))

    scored.sort(key=lambda x: (-x[0], -int(x[2].get("n_reports", 0))))
    top_scored = scored[:cell_cap]
    coll_by_id = {c["id"]: coll for _, coll, c in top_scored}
    top_ids = [c["id"] for _, _, c in top_scored]

    clusters = _ward_cluster_cells(top_ids, target_k=min(target_k, max(1, len(top_ids))))
    clusters.sort(
        key=lambda cl: sum(int(all_by_id[cid].get("n_storm_days", 0)) for cid in cl),
        reverse=True,
    )

    basins = []
    for cl in clusters:
        comp_objs = [all_by_id[c] for c in cl]
        reps = sum(int(c.get("n_reports", 0)) for c in comp_objs)
        max_sd = max((int(c.get("n_storm_days", 0)) for c in comp_objs), default=1)
        thresholds = [float(c["thresh_mm_6h"]) for c in comp_objs if c.get("thresh_mm_6h") is not None]
        min_thresh = min(thresholds) if thresholds else 3.0
        waymo_active_cells = sum(1 for cid in cl if coll_by_id.get(cid, 0) > 0)

        sdays = sorted({d for c in comp_objs for d in (c.get("storm_days") or [])}, reverse=True)
        top_addrs = []
        for m in sorted(comp_objs, key=lambda x: (-int(x.get("n_storm_days", 0)), -int(x.get("n_reports", 0))))[:3]:
            if m.get("top_addresses"):
                top_addrs.append(m["top_addresses"][0])

        poly = build_padded_hull(cl, grid)
        hull_cells = cells_inside_polygon(poly, grid)
        sr, sc = _parse_cell_id(cl[0])

        basins.append({
            "cluster_id": f"k{len(basins) + 1}",
            "seed": cl[0],
            "r": sr,
            "c": sc,
            "members": sorted(set(cl)),
            "hull_cells": sorted(set(hull_cells)),
            "n_hull_cells": len(set(hull_cells)),
            "n_flood_cells": len(cl),
            "n_reports": reps,
            "hist_storm_cell_days": sum(int(c.get("n_storm_days", 0)) for c in comp_objs),
            "max_storm_days": max_sd,
            "min_thresh_mm_6h": round(min_thresh, 1),
            "waymo_active_cells": waymo_active_cells,
            "top_addresses": top_addrs or [cl[0]],
            "storm_days": sdays[:8],
        })

    return basins


def _score_zones_with_decision1(
    zones: list[dict[str, Any]],
    forecast_summary: str,
) -> dict[str, float]:
    """Score flood probability p_flood per zone in one fast Decision 1 call."""
    if not zones:
        return {}
    beta = get_beta_client()
    criteria = ["very low", "low", "moderate", "high", "very high"]

    lines = [
        "San Francisco storm flood risk assessment.",
        forecast_summary,
        "Candidate flood zones (historical 311 flood memory strictly before forecast date):",
    ]
    questions: dict[str, dict[str, Any]] = {}
    for z in zones:
        zid = z["id"]
        ev = z["evidence"]
        recent = ", ".join(ev["storm_days"][:5])
        lines.append(
            f"- {zid} ({z['name']}): {len(z['cells'])} cells, "
            f"{ev['n_reports']} historical reports, "
            f"max_cell_storm_days={z['_max_storm_days']}, "
            f"min_6h_thresh={z['_min_thresh']:.1f} mm, "
            f"window={z['start'][11:]}-{z['end'][11:]}, "
            f"recent storm dates=[{recent}]"
        )
        questions[zid] = {
            "type": "score",
            "instructions": (
                f"Given the forecast rainfall totals and 6-hour sums, how likely is "
                f"street flooding in zone {zid} ({z['name']}) during {z['start'][11:]}-{z['end'][11:]}?"
            ),
            "criteria": criteria,
        }

    res = beta.decisions.create(
        model="models/gemini-decision-1",
        input=[{"type": "text", "text": "\n".join(lines)}],
        questions=questions,
    )
    scores: dict[str, float] = {}
    max_idx = float(len(criteria) - 1)
    for zid, ans in res.answers.items():
        raw_score = getattr(ans, "score", None)
        if raw_score is None:
            scores[zid] = 0.75
        else:
            p = max(0.05, min(0.99, float(raw_score) / max_idx))
            scores[zid] = round(p, 2)
    return scores


def propose_zones(
    cells: list[dict[str, Any]] | dict[str, Any],
    forecast: dict[str, Any],
    date: str,
) -> dict[str, Any]:
    """Generate up to 12 forecast-based flood zones for San Francisco.

    Args:
        cells: List of historical cell dicts (from data/cells.json["cells"]) or the full cells.json dict.
        forecast: Forecast dict with keys `date`, `source`, `total_mm`, `hours`.
        date: Forecast date string YYYY-MM-DD.

    Returns:
        Zones contract dict matching contracts.md.
    """
    grid = dict(DEFAULT_GRID)
    if isinstance(cells, dict):
        grid = dict(cells.get("grid", DEFAULT_GRID))
        cell_list: list[dict[str, Any]] = list(cells.get("cells", []))
    else:
        cell_list = list(cells)

    all_by_id = {c["id"]: c for c in cell_list}

    # 1. Compute 6-hour rolling sums and forecast summary
    hourly = _six_hour_sums(forecast.get("hours", []))
    total_mm = float(forecast.get("total_mm", sum(h["mm"] for h in hourly)))
    peak_6h = max((h["sum_6h_mm"] for h in hourly), default=0.0)
    peak_6h_t = max(hourly, key=lambda h: h["sum_6h_mm"])["t"] if hourly else f"{date}T12:00"
    daytime_6h = max((h["sum_6h_mm"] for h in hourly if h["t"][11:13] <= "15"), default=0.0)

    # 2. Pre-cluster top historically flood-prone cells into compact candidate basins
    basins = _build_candidate_basins(cell_list, grid, forecast_peak6=peak_6h, total_mm=total_mm)
    basin_by_id = {b["cluster_id"]: b for b in basins}

    compact_basins = [
        {
            "cluster_id": b["cluster_id"],
            "r": b["r"],
            "c": b["c"],
            "cells": len(b["members"]),
            "n_reports": b["n_reports"],
            "max_storm_days": b["max_storm_days"],
            "min_thresh_mm_6h": b["min_thresh_mm_6h"],
            "landmarks": b["top_addresses"],
            "storm_days": b["storm_days"][:5],
        }
        for b in basins
    ]

    prompt = f"""You are a San Francisco street-flooding operations planner for an autonomous vehicle fleet.
Date: {date}
Forecast source: {forecast.get("source", "previous_day1")}
Forecast 24-hour total rainfall: {total_mm:.1f} mm
Forecast peak 6-hour rolling sum: {peak_6h:.1f} mm (at {peak_6h_t})
Daytime (00:00-15:00) peak 6-hour rolling sum: {daytime_6h:.1f} mm

Hourly forecast with trailing 6-hour rolling sums (local America/Los_Angeles):
{json.dumps(hourly, separators=(",", ":"))}

Top {len(compact_basins)} pre-clustered compact historical flood basins in San Francisco (strictly pre-{date} history; ranked by historical flood reports; total SF area = {SF_CELLS} cells):
{json.dumps(compact_basins, separators=(",", ":"))}

INSTRUCTIONS:
1. Select AT MOST {MAX_ZONES} flood pull-back zones from the candidate clusters above (each zone should use 1 `cluster_id`, and do NOT repeat a `cluster_id` across zones).
2. Selection & Area budget (STRICT):
   - On severe storm days, select up to {MAX_ZONES} zones to aggressively protect the fleet.
   - On lighter rain days, select FEWER zones (proposing fewer/smaller zones rather than unnecessarily closing 8% of SF).
   - Total `cells` across all selected zones MUST stay <= {AREA_CAP_CELLS} cells (<= 8.0% of SF).
   - Aim to use ~300 to 340 `cells` (7.0%–7.8% of SF) across 11–12 highest-risk basins so the fleet avoids the highest-volume historical flood corridors without exceeding 8% of SF.
3. Timing rule (CRITICAL):
   - Reason from the 24-hour DAY TOTAL ({total_mm:.1f} mm) and 6-HOUR ROLLING SUMS, NOT single hourly spikes. Night-before forecasts get the storm day total and multi-hour rain waves right even if exact single-hour peaks shift by 1–3 hours.
   - Set **tight, operationally useful time windows** (`YYYY-MM-DDTHH:MM`, naive local time) centered on the primary daytime 6-hour rain wave (when 6h rolling sums exceed each basin's `min_thresh_mm_6h`, typically starting ~1h before threshold crossing around `05:00`–`06:00` and ending ~2h after the daytime wave subsides around `14:00`–`16:00`).
   - Do NOT use lazy all-day `01:00-23:59` or `05:00-23:59` windows! Keep windows moderately tight (roughly 12 to 14 hours, e.g. `03:00`–`17:00` or `04:00`–`18:00`) so the fleet stays operational during the dry afternoon lull.
4. Reason requirement:
   - Write a crisp 1-2 sentence plain-language `reason` for each zone mentioning the 24h total or 6-hour forecast rainfall sum AND explicitly citing at least one exact historical storm date (`YYYY-MM-DD`) taken verbatim from that cluster's `storm_days`.
"""

    client = get_client()
    response = client.models.generate_content(
        model="gemini-4-carbon",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ProposedPlanDraft,
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
        ),
    )

    draft = ProposedPlanDraft.model_validate_json(response.text)

    # 3. Post-process zones: build padded convex hulls, expand cells inside hull, enforce <= 8% area
    used_clusters: set[str] = set()
    zones: list[dict[str, Any]] = []

    for z_draft in draft.zones[:MAX_ZONES]:
        cid = z_draft.cluster_id.strip()
        if cid not in basin_by_id or cid in used_clusters:
            continue
        used_clusters.add(cid)

        member_cells = sorted(set(basin_by_id[cid]["members"]))

        poly = build_padded_hull(member_cells, grid)
        hull_cells = cells_inside_polygon(poly, grid)
        # Put ONLY the historically flood-prone cells in zone["cells"]!
        zone_cells = sorted(set(member_cells))

        known_cells = [all_by_id[c] for c in zone_cells if c in all_by_id]
        member_objs = [all_by_id[c] for c in member_cells if c in all_by_id]
        n_reports = sum(int(c.get("n_reports", 0)) for c in known_cells)
        all_sdays = sorted(
            {d for c in known_cells for d in (c.get("storm_days") or [])},
            reverse=True,
        )
        max_storm_days = max((int(c.get("n_storm_days", 0)) for c in member_objs), default=1)
        thresholds = [float(c["thresh_mm_6h"]) for c in member_objs if c.get("thresh_mm_6h") is not None]
        min_thresh = min(thresholds) if thresholds else 3.0

        # Ensure every zone's reason cites at least one real date in evidence.storm_days
        reason = z_draft.reason.strip()
        cited_dates = [d for d in DATE_RE.findall(reason) if d in all_sdays]
        top_sdays = all_sdays[:10]
        for cd in cited_dates:
            if cd not in top_sdays:
                top_sdays = [cd] + top_sdays[:9]
        if not cited_dates and top_sdays:
            reason = f"{reason.rstrip('.')} (e.g., flooded on {top_sdays[0]})."

        start_t = _clean_time(z_draft.start, date, f"{date}T05:00")
        end_t = _clean_time(z_draft.end, date, f"{date}T15:00")
        if end_t <= start_t:
            end_t = f"{date}T16:00"

        zones.append({
            "id": "",
            "name": z_draft.name.strip()[:80],
            "cells": zone_cells,
            "polygon": poly,
            "start": start_t,
            "end": end_t,
            "p_flood": 0.0,
            "reason": reason,
            "evidence": {
                "n_reports": n_reports,
                "storm_days": top_sdays,
            },
            "status": "proposed",
            "source": "forecast",
            "_max_storm_days": max_storm_days,
            "_min_thresh": min_thresh,
            "_rank": n_reports * 100 + max_storm_days,
        })

    # Sort highest-risk zones first
    zones.sort(key=lambda z: -z["_rank"])

    # Hard-enforce <= 8.0% SF area cap (AREA_CAP_CELLS = 347 unique cells)
    while len(zones) > 1 and len({cid for z in zones for cid in z["cells"]}) > AREA_CAP_CELLS:
        zones.pop()

    # Assign final z1..zN IDs
    for idx, z in enumerate(zones, 1):
        z["id"] = f"z{idx}"

    # 4. Score p_flood per zone using Decision 1 in one fast call
    forecast_summary = (
        f"Date: {date}. Source: {forecast.get('source', 'previous_day1')}. "
        f"24h total rainfall: {total_mm:.1f} mm. "
        f"Peak 6h rolling rainfall: {peak_6h:.1f} mm (daytime peak 6h: {daytime_6h:.1f} mm)."
    )
    p_scores = _score_zones_with_decision1(zones, forecast_summary)
    for z in zones:
        z["p_flood"] = p_scores.get(z["id"], 0.75)
        del z["_max_storm_days"]
        del z["_min_thresh"]
        del z["_rank"]

    return {
        "date": date,
        "forecast_source": forecast.get("source", "previous_day1"),
        "generated_by": "gemini-4-carbon",
        "zones": zones,
    }


def _evaluate_against_events(plan_dict: dict[str, Any], events_path: Path) -> dict[str, Any]:
    """Compute pct_in_zone and area stats against real 311 events (for verification only)."""
    events = json.loads(events_path.read_text())
    zones = plan_dict["zones"]

    cell_to_zones: dict[str, list[dict[str, Any]]] = {}
    for z in zones:
        for cid in z["cells"]:
            cell_to_zones.setdefault(cid, []).append(z)

    in_cell_active = 0
    in_cell_anytime = 0
    in_poly_active = 0
    for ev in events:
        t_min = ev["t"][:16]
        zs = cell_to_zones.get(ev["cell"], [])
        if zs:
            in_cell_anytime += 1
            if any(z["start"] <= t_min <= z["end"] for z in zs):
                in_cell_active += 1
        lon, lat = ev["lon"], ev["lat"]
        if any(
            z["start"] <= t_min <= z["end"] and _point_in_polygon(lon, lat, z["polygon"])
            for z in zones
        ):
            in_poly_active += 1

    unique_cells = len({cid for z in zones for cid in z["cells"]})
    poly_area_km2 = sum(_polygon_area_km2(z["polygon"]) for z in zones)
    return {
        "n_events": len(events),
        "in_cell_active": in_cell_active,
        "pct_in_zone_cell": in_cell_active / max(1, len(events)),
        "pct_in_zone_poly": in_poly_active / max(1, len(events)),
        "pct_in_zone_anytime": in_cell_anytime / max(1, len(events)),
        "unique_cells": unique_cells,
        "zone_area_pct_cells": unique_cells / SF_CELLS,
        "zone_area_pct_poly": poly_area_km2 / 121.0,
    }


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else "2026-11-18"
    data_dir = REPO_ROOT / "data"
    cells_path = data_dir / "cells.json"
    forecast_path = data_dir / f"forecast_{date}.json"
    out_path = data_dir / f"zones_{date}.json"

    cells_data = json.loads(cells_path.read_text())
    forecast = json.loads(forecast_path.read_text())

    t0 = time.time()
    result = propose_zones(cells_data["cells"], forecast, date)
    elapsed = time.time() - t0

    out_path.write_text(json.dumps(result, indent=2) + "\n")

    zones = result["zones"]
    unique_cells = len({cid for z in zones for cid in z["cells"]})
    poly_area_km2 = sum(_polygon_area_km2(z["polygon"]) for z in zones)
    print(
        f"wrote {out_path} in {elapsed:.1f}s: {len(zones)} zones, "
        f"{unique_cells} cells ({unique_cells / SF_CELLS:.1%} of SF, "
        f"poly area ~{poly_area_km2 / 121.0:.1%} of SF)"
    )

    all_cited = True
    for z in zones:
        sdays = set(z["evidence"]["storm_days"])
        cited = [d for d in DATE_RE.findall(z["reason"]) if d in sdays]
        ok = "OK" if cited else "MISSING_DATE"
        if not cited:
            all_cited = False
        print(
            f"  {z['id']:3} {z['name'][:34]:34} {z['start'][11:]}-{z['end'][11:]} "
            f"p={z['p_flood']:.2f} cells={len(z['cells']):3d} cited={cited[:2]} [{ok}]"
        )
    print(f"All reasons cite real storm_days: {all_cited}")

    events_path = data_dir / f"events_{date}.json"
    if events_path.exists():
        stats = _evaluate_against_events(result, events_path)
        print(
            f"Score vs {events_path.name}: "
            f"pct_in_zone(cell)={stats['pct_in_zone_cell']:.1%} ({stats['in_cell_active']}/{stats['n_events']}), "
            f"pct_in_zone(poly)={stats['pct_in_zone_poly']:.1%}, "
            f"anytime={stats['pct_in_zone_anytime']:.1%}, "
            f"area(cells)={stats['zone_area_pct_cells']:.1%}, "
            f"area(poly)={stats['zone_area_pct_poly']:.1%}"
        )


if __name__ == "__main__":
    main()
