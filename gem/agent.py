"""Task G4: Flood incident response agent powered by Antigravity Managed Agents.

Exposes:
  - run_incident(verdict: dict) -> list[dict]
  - Tool functions: get_cell_history, get_forecast, judge_frame, propose_zone
  - CLI: python -m gem.agent media/frames/flood_01.jpg 37.76 -122.41
"""
from __future__ import annotations

import json
import math
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from google.genai import types

from gem.client import REPO_ROOT, get_beta_client, get_client
from gem.vision import judge_frame as _vision_judge_frame

DATA_DIR = REPO_ROOT / "data"
TRACES_DIR = REPO_ROOT / "media" / "traces"
SIM_CACHE_DIR = REPO_ROOT / "media" / "sim_cache"
DEFAULT_GRID: dict[str, float] = {
    "lat0": 37.70,
    "lon0": -122.52,
    "dlat": 0.0015,
    "dlon": 0.0019,
}
DEFAULT_DATE = "2026-11-18"
DEFAULT_TIME = "2026-11-18T10:00"

MANAGED_AGENT_NAME = "antigravity-preview-09-2026"
MANAGED_AGENT_MODEL = "gemini-4-hydrogen"
MANAGED_AGENT_MAX_TOKENS = 50000
FALLBACK_CARBON_MODEL = "gemini-4-carbon"

_CELL_ID_RE = re.compile(r"^r(-?\d+)_c(-?\d+)$")
_CELLS_CACHE: tuple[dict[str, float], dict[str, dict[str, Any]]] | None = None


def latlon_to_cell(lat: float, lon: float, grid: dict[str, float] | None = None) -> str:
    """Map (lat, lon) to contract grid cell id r{row}_c{col}."""
    g = grid or DEFAULT_GRID
    row = math.floor((float(lat) - g["lat0"]) / g["dlat"])
    col = math.floor((float(lon) - g["lon0"]) / g["dlon"])
    return f"r{row}_c{col}"


def _parse_cell_id(cell_id: str) -> tuple[int, int] | None:
    m = _CELL_ID_RE.match(cell_id.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _cell_center(cell_id: str, grid: dict[str, float]) -> tuple[float, float]:
    """Return (lon, lat) center of a grid cell."""
    parsed = _parse_cell_id(cell_id)
    if parsed is None:
        raise ValueError(f"Invalid cell id: {cell_id!r}")
    row, col = parsed
    lat = grid["lat0"] + (row + 0.5) * grid["dlat"]
    lon = grid["lon0"] + (col + 0.5) * grid["dlon"]
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


def _build_padded_hull(cell_ids: list[str], grid: dict[str, float]) -> list[list[float]]:
    """Convex hull of cell centers padded by half a cell, as a closed [lon, lat] ring."""
    half_lat = grid["dlat"] / 2.0
    half_lon = grid["dlon"] / 2.0
    corners: list[tuple[float, float]] = []
    for cid in cell_ids:
        if _parse_cell_id(cid) is None:
            continue
        lon, lat = _cell_center(cid, grid)
        for dlon in (-half_lon, half_lon):
            for dlat in (-half_lat, half_lat):
                corners.append((round(lon + dlon, 6), round(lat + dlat, 6)))
    hull = _convex_hull(corners)
    if not hull:
        return []
    ring = [[p[0], p[1]] for p in hull]
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return ring


def _load_cells_index() -> tuple[dict[str, float], dict[str, dict[str, Any]]]:
    global _CELLS_CACHE
    if _CELLS_CACHE is not None:
        return _CELLS_CACHE
    cells_path = DATA_DIR / "cells.json"
    if not cells_path.exists():
        _CELLS_CACHE = (dict(DEFAULT_GRID), {})
        return _CELLS_CACHE
    raw = json.loads(cells_path.read_text(encoding="utf-8"))
    grid = raw.get("grid") or dict(DEFAULT_GRID)
    index = {c["id"]: c for c in raw.get("cells", []) if "id" in c}
    _CELLS_CACHE = (grid, index)
    return _CELLS_CACHE


def _clean_intersection_name(addresses: list[str], fallback_cell: str) -> str:
    if not addresses:
        return f"Camera Alert @ {fallback_cell}"
    addr = addresses[0].strip()
    if addr.lower().startswith("intersection of "):
        addr = addr[len("intersection of "):]
    addr = re.sub(r"\s+and\s+", " & ", addr, flags=re.IGNORECASE)
    addr = re.sub(r",\s*Virtual\s*\d+.*$", "", addr, flags=re.IGNORECASE)
    addr = re.sub(r",\s*\d{5}.*$", "", addr)
    return addr.title().replace(" St", " St").replace(" Ave", " Ave").strip() or f"Camera Alert @ {fallback_cell}"


def _normalize_iso_minute(ts: str, fallback: str) -> str:
    raw = (ts or "").strip()
    if not raw:
        return fallback
    # Trim timezone or seconds if present so we emit naive local YYYY-MM-DDTHH:MM
    raw = re.sub(r"(Z|[+-]\d{2}:\d{2})$", "", raw)
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", raw)
    if m:
        return f"{m.group(1)}T{m.group(2)}"
    return fallback


def _add_hours_iso(ts: str, hours: int) -> str:
    norm = _normalize_iso_minute(ts, DEFAULT_TIME)
    day_prefix = norm[:10]
    dt = datetime.strptime(norm, "%Y-%m-%dT%H:%M") + timedelta(hours=hours)
    if dt.strftime("%Y-%m-%d") != day_prefix:
        return f"{day_prefix}T23:59"
    return dt.strftime("%Y-%m-%dT%H:%M")


# ---------------------------------------------------------------------------
# Module-level tools (exposed publicly & registered with the Managed Agent)
# ---------------------------------------------------------------------------


def get_cell_history(cell: str) -> dict[str, Any]:
    """Look up historical 311 flooding data for a cell and its 3x3 immediate neighbors."""
    grid, index = _load_cells_index()
    cid = cell.strip()
    rec = index.get(cid)
    parsed = _parse_cell_id(cid)

    if rec is not None:
        target = {
            "id": rec["id"],
            "lat": rec["lat"],
            "lon": rec["lon"],
            "n_reports": rec.get("n_reports", 0),
            "n_storm_days": rec.get("n_storm_days", 0),
            "storm_days": rec.get("storm_days", [])[:10],
            "thresh_mm_6h": rec.get("thresh_mm_6h"),
            "top_addresses": rec.get("top_addresses", [])[:3],
        }
    else:
        lon, lat = _cell_center(cid, grid) if parsed else (DEFAULT_GRID["lon0"], DEFAULT_GRID["lat0"])
        target = {
            "id": cid,
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "n_reports": 0,
            "n_storm_days": 0,
            "storm_days": [],
            "thresh_mm_6h": None,
            "top_addresses": [],
        }

    neighbors: list[dict[str, Any]] = []
    if parsed is not None:
        r0, c0 = parsed
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nid = f"r{r0 + dr}_c{c0 + dc}"
                nrec = index.get(nid)
                if nrec is not None:
                    neighbors.append(
                        {
                            "id": nid,
                            "lat": nrec["lat"],
                            "lon": nrec["lon"],
                            "n_reports": nrec.get("n_reports", 0),
                            "n_storm_days": nrec.get("n_storm_days", 0),
                            "storm_days": nrec.get("storm_days", [])[:5],
                            "thresh_mm_6h": nrec.get("thresh_mm_6h"),
                            "top_addresses": nrec.get("top_addresses", [])[:2],
                        }
                    )
        neighbors.sort(key=lambda x: (x["n_storm_days"], x["n_reports"]), reverse=True)

    return {
        "cell": target,
        "neighbors": neighbors,
        "neighbor_count": len(neighbors),
    }


def get_forecast(date: str) -> dict[str, Any]:
    """Load the rain forecast for YYYY-MM-DD (plus latest run if available)."""
    day = (date or DEFAULT_DATE).strip()[:10]
    primary_path = DATA_DIR / f"forecast_{day}.json"
    latest_path = DATA_DIR / f"forecast_{day}_latest.json"

    if not primary_path.exists():
        return {
            "date": day,
            "source": "missing",
            "total_mm": 0.0,
            "max_6h_mm": 0.0,
            "hours": [],
        }

    data = json.loads(primary_path.read_text(encoding="utf-8"))
    hours = data.get("hours", [])
    mms = [float(h.get("mm", 0.0)) for h in hours]
    max_6h = 0.0
    for i in range(len(mms)):
        window_sum = sum(mms[i : i + 6])
        if window_sum > max_6h:
            max_6h = window_sum

    rain_hours = [h for h in hours if float(h.get("mm", 0.0)) > 0.0]
    result: dict[str, Any] = {
        "date": data.get("date", day),
        "source": data.get("source", "previous_day1"),
        "total_mm": round(float(data.get("total_mm", sum(mms))), 2),
        "max_6h_mm": round(max_6h, 2),
        "rain_hours": rain_hours,
        "hours": hours,
    }

    if latest_path.exists():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        latest_hours = latest.get("hours", [])
        latest_rain = [h for h in latest_hours if float(h.get("mm", 0.0)) > 0.0]
        result["latest_update"] = {
            "source": latest.get("source", "latest"),
            "total_mm": round(float(latest.get("total_mm", 0.0)), 2),
            "rain_hours": latest_rain,
        }

    return result


def judge_frame(path: str) -> dict[str, Any]:
    """Run Decision 1 roadway flood judgment on a local JPEG image path."""
    p = Path(path)
    if not p.is_absolute():
        candidate = REPO_ROOT / p
        if candidate.exists():
            p = candidate
    if not p.is_file():
        return {
            "path": str(path),
            "error": f"Image file not found: {p}",
            "flooded_p": 0.0,
            "depth_score": 0.0,
            "depth_label": "none",
            "latency_ms": 0,
        }
    verdict = _vision_judge_frame(p.read_bytes())
    return {"path": str(path), **verdict}


def propose_zone(
    cells: list[str],
    start: str,
    end: str,
    reason: str,
    *,
    fleet_notice: str = "",
    p_flood: float | None = None,
    name: str | None = None,
    target_cell: str | None = None,
    verdict_flooded_p: float | None = None,
) -> dict[str, Any]:
    """Construct a contract-compliant camera-triggered flood zone dict."""
    grid, index = _load_cells_index()

    clean_cells: list[str] = []
    seen: set[str] = set()
    raw_list = list(cells or [])
    if target_cell and target_cell not in raw_list:
        raw_list.insert(0, target_cell)
    target_rc = _parse_cell_id(target_cell) if target_cell else None
    for cid in raw_list:
        c = str(cid).strip()
        parsed_rc = _parse_cell_id(c)
        if parsed_rc is None or c in seen:
            continue
        if target_rc is not None and max(abs(parsed_rc[0] - target_rc[0]), abs(parsed_rc[1] - target_rc[1])) > 2:
            continue
        seen.add(c)
        clean_cells.append(c)
    if not clean_cells:
        fallback = target_cell or "r40_c57"
        clean_cells = [fallback]

    primary_cell = target_cell if (target_cell and target_cell in clean_cells) else clean_cells[0]
    primary_rec = index.get(primary_cell, {})

    norm_start = _normalize_iso_minute(start, DEFAULT_TIME)
    day_prefix = norm_start[:10]
    norm_end = _normalize_iso_minute(end, _add_hours_iso(norm_start, 4))
    if norm_end[:10] != day_prefix:
        norm_end = f"{day_prefix}T23:59"
    if norm_end <= norm_start:
        norm_end = _add_hours_iso(norm_start, 4)

    total_reports = 0
    storm_days_set: set[str] = set()
    for cid in clean_cells:
        rec = index.get(cid)
        if rec:
            total_reports += int(rec.get("n_reports", 0))
            for sd in rec.get("storm_days", []):
                storm_days_set.add(str(sd))
    storm_days_sorted = sorted(storm_days_set, reverse=True)

    computed_p = p_flood if p_flood is not None else 0.85
    if verdict_flooded_p is not None:
        computed_p = max(float(computed_p), float(verdict_flooded_p))
    computed_p = round(max(0.0, min(1.0, float(computed_p))), 3)

    zone_name = (name or "").strip() or _clean_intersection_name(
        primary_rec.get("top_addresses", []),
        primary_cell,
    )
    hhmm = norm_start[11:16].replace(":", "")
    zone_id = f"cam_{primary_cell}_{hhmm}"

    clean_notice = (fleet_notice or "").strip()
    clean_reason = (reason or "").strip()
    if not clean_notice:
        clean_notice = (
            f"AVOID {zone_name} ({len(clean_cells)} cells) {norm_start[11:16]}-{norm_end[11:16]}: "
            f"camera-confirmed roadway flooding; reroute around low-lying blocks."
        )
    if not clean_reason:
        clean_reason = f"Camera-confirmed roadway flooding at {zone_name} ({primary_cell})."

    polygon = _build_padded_hull(clean_cells, grid)

    return {
        "id": zone_id,
        "name": zone_name,
        "cells": clean_cells,
        "polygon": polygon,
        "start": norm_start,
        "end": norm_end,
        "p_flood": computed_p,
        "reason": clean_reason,
        "fleet_notice": clean_notice,
        "evidence": {
            "n_reports": total_reports,
            "storm_days": storm_days_sorted[:10],
        },
        "status": "proposed",
        "source": "camera",
    }


# ---------------------------------------------------------------------------
# Tool declarations for Antigravity Managed Agents (Interactions API)
# ---------------------------------------------------------------------------

MANAGED_AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_cell_history",
        "description": (
            "Look up historical 311 flood reports, storm_days, 6h rain threshold, top addresses, "
            "and 3x3 adjacent neighbor cells for a San Francisco grid cell ID (e.g. 'r40_c57')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cell": {
                    "type": "string",
                    "description": "Grid cell ID formatted as r{row}_c{col}, e.g. 'r40_c57'.",
                }
            },
            "required": ["cell"],
        },
    },
    {
        "type": "function",
        "name": "get_forecast",
        "description": (
            "Get hourly precipitation forecast, 24h total_mm, max_6h_mm, and any latest forecast update "
            "for a date (YYYY-MM-DD)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format, e.g. '2026-11-18'.",
                }
            },
            "required": ["date"],
        },
    },
    {
        "type": "function",
        "name": "judge_frame",
        "description": (
            "Run Decision 1 computer vision model on a street camera JPEG file path to confirm "
            "standing water probability (flooded_p), depth_score, and depth_label."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the JPEG camera frame (e.g. 'media/frames/flood_01.jpg').",
                }
            },
            "required": ["path"],
        },
    },
    {
        "type": "function",
        "name": "propose_zone",
        "description": (
            "Finalize and propose a camera-triggered flood avoidance zone for autonomous fleet routing. "
            "Call this once after inspecting cell history and forecast."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cells": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of grid cell IDs to include in the zone: always include the camera's cell, "
                        "plus 1-4 adjacent high-risk neighbor cells that share flood history or drainage."
                    ),
                },
                "start": {
                    "type": "string",
                    "description": "Zone start time in naive local ISO format YYYY-MM-DDTHH:MM.",
                },
                "end": {
                    "type": "string",
                    "description": "Zone end time in naive local ISO format YYYY-MM-DDTHH:MM.",
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Concise plain-English explanation citing camera depth/confidence, specific "
                        "historical storm_days dates from cell history, and forecast rain totals."
                    ),
                },
                "fleet_notice": {
                    "type": "string",
                    "description": "One-line actionable notice for autonomous vehicle fleet operations.",
                },
                "p_flood": {
                    "type": "number",
                    "description": "Estimated flood probability in [0, 1].",
                },
                "name": {
                    "type": "string",
                    "description": "Short human-readable intersection/area name for the zone.",
                },
            },
            "required": ["cells", "start", "end", "reason", "fleet_notice"],
        },
    },
]


def _build_incident_prompt(verdict: dict[str, Any], target_cell: str, incident_t: str, date_str: str) -> str:
    has_path = bool(verdict.get("path"))
    judge_instruction = (
        f"- Optionally call judge_frame(path='{verdict['path']}') if you need to re-verify the image.\n"
        if has_path
        else ""
    )
    return (
        "You are an autonomous vehicle fleet flood-incident response agent for San Francisco.\n"
        "A vehicle camera just reported possible roadway flooding. Your job is to investigate using "
        "your tools and propose a precise flood-avoidance zone.\n\n"
        f"INCIDENT INPUT:\n{json.dumps(verdict, indent=2)}\n\n"
        f"Resolved target cell: {target_cell}\n"
        f"Incident local time: {incident_t} (date: {date_str})\n\n"
        "REQUIRED WORKFLOW (be concise and fast — batch parallel tool calls when possible):\n"
        f"1. Call get_cell_history(cell='{target_cell}') AND get_forecast(date='{date_str}') in parallel.\n"
        f"{judge_instruction}"
        "2. Decide:\n"
        "   - Extent (`cells`): always include the target cell, and add adjacent neighbor cells from "
        "get_cell_history that have meaningful flood history (n_storm_days >= 2 or n_reports >= 5) "
        "to cover the local drainage basin without over-blocking dry blocks (typically 2-5 cells total).\n"
        "   - Duration (`start`, `end`): start at the incident time (naive local YYYY-MM-DDTHH:MM) and "
        "set `end` based on the depth severity and remaining forecast rain (typically 3-6 hours; extend "
        "longer if heavy rain continues).\n"
        "   - Plain-English `reason` citing the camera depth/flooded_p, specific historical storm_days "
        "dates from the cells, and the forecast rainfall total / 6h trajectory.\n"
        "   - One-line `fleet_notice` for dispatch/routing ops.\n"
        "3. Call propose_zone(...) with your final decision.\n"
        "Do NOT ask the user questions. Complete the workflow and finish with a 1-sentence confirmation."
    )


def _execute_tool(
    name: str,
    args: dict[str, Any],
    *,
    target_cell: str,
    incident_t: str,
    date_str: str,
    verdict_flooded_p: float | None,
) -> dict[str, Any]:
    if name == "get_cell_history":
        return get_cell_history(str(args.get("cell") or target_cell))
    if name == "get_forecast":
        return get_forecast(str(args.get("date") or date_str))
    if name == "judge_frame":
        return judge_frame(str(args.get("path") or ""))
    if name == "propose_zone":
        return propose_zone(
            cells=list(args.get("cells") or [target_cell]),
            start=str(args.get("start") or incident_t),
            end=str(args.get("end") or _add_hours_iso(incident_t, 4)),
            reason=str(args.get("reason") or ""),
            fleet_notice=str(args.get("fleet_notice") or ""),
            p_flood=args.get("p_flood"),
            name=args.get("name"),
            target_cell=target_cell,
            verdict_flooded_p=verdict_flooded_p,
        )
    return {"error": f"Unknown tool: {name}"}


def _run_managed_agent_loop(
    prompt: str,
    *,
    target_cell: str,
    incident_t: str,
    date_str: str,
    verdict_flooded_p: float | None,
    has_image_path: bool = False,
    on_step: Any = None,
    max_turns: int = 4,
) -> tuple[list[dict[str, Any]], str | None]:
    """Run multi-turn tool loop using Antigravity Managed Agents (antigravity-preview-09-2026)."""
    beta = get_beta_client()
    trace: list[dict[str, Any]] = []
    thoughts: list[str] = []
    prev_id: str | None = None
    first_interaction_id: str | None = None
    next_input: Any = prompt
    active_tools = (
        MANAGED_AGENT_TOOLS
        if has_image_path
        else [t for t in MANAGED_AGENT_TOOLS if t.get("name") != "judge_frame"]
    )

    for _turn in range(max_turns):
        kwargs: dict[str, Any] = {
            "agent": MANAGED_AGENT_NAME,
            "environment": "remote",
            "agent_config": {
                "type": "antigravity",
                "model": MANAGED_AGENT_MODEL,
                "max_total_tokens": MANAGED_AGENT_MAX_TOKENS,
            },
            "tools": active_tools,
            "input": next_input,
            "timeout": 35.0,
        }
        if prev_id is not None:
            kwargs["previous_interaction_id"] = prev_id

        interaction = beta.interactions.create(**kwargs)
        prev_id = getattr(interaction, "id", None)
        if first_interaction_id is None and prev_id:
            first_interaction_id = str(prev_id)
        status = getattr(interaction, "status", None)
        steps = getattr(interaction, "steps", None) or []

        for s in steps:
            if getattr(s, "type", None) == "thought":
                summ = getattr(s, "summary", None)
                if summ:
                    thoughts.append(str(summ))

        if status == "failed":
            raise RuntimeError(f"Managed Agent interaction failed (id={prev_id})")

        fc_steps = [s for s in steps if getattr(s, "type", None) == "function_call"]
        if not fc_steps:
            break

        tool_responses: list[dict[str, Any]] = []
        called_propose = False
        for fc in fc_steps:
            call_id = getattr(fc, "id", None) or getattr(fc, "call_id", None)
            fname = str(getattr(fc, "name", ""))
            raw_args = getattr(fc, "arguments", None) or {}
            fargs = dict(raw_args) if isinstance(raw_args, dict) else {}

            result = _execute_tool(
                fname,
                fargs,
                target_cell=target_cell,
                incident_t=incident_t,
                date_str=date_str,
                verdict_flooded_p=verdict_flooded_p,
            )
            step_entry = {"tool": fname, "args": fargs, "result": result}
            trace.append(step_entry)
            if callable(on_step):
                try:
                    on_step(step_entry)
                except Exception:
                    pass
            if fname == "propose_zone":
                called_propose = True

            tool_responses.append(
                {
                    "type": "function_result",
                    "call_id": call_id,
                    "name": fname,
                    "result": result,
                }
            )

        # Once propose_zone has been called, we already have the final zone dict and
        # do not need another remote round-trip just to echo a confirmation sentence.
        if called_propose:
            break
        if status != "requires_action":
            break
        next_input = tool_responses

    if not trace:
        raise RuntimeError(f"Managed Agent returned no tool calls (id={first_interaction_id})")
    return trace, first_interaction_id, thoughts


def _run_carbon_fallback_loop(
    prompt: str,
    *,
    target_cell: str,
    incident_t: str,
    date_str: str,
    verdict_flooded_p: float | None,
    max_turns: int = 6,
) -> list[dict[str, Any]]:
    """Fallback function-calling loop on gemini-4-carbon if Managed Agents is unreachable."""
    client = get_client()
    fn_decls = [
        types.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters_json_schema=t["parameters"],
        )
        for t in MANAGED_AGENT_TOOLS
    ]
    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=fn_decls)],
    )
    contents: list[Any] = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
    trace: list[dict[str, Any]] = []

    for _turn in range(max_turns):
        resp = client.models.generate_content(
            model=FALLBACK_CARBON_MODEL,
            contents=contents,
            config=config,
        )
        cand = (resp.candidates or [None])[0]
        if cand is None or cand.content is None:
            break
        contents.append(cand.content)

        fcalls = [p.function_call for p in (cand.content.parts or []) if p.function_call]
        if not fcalls:
            break

        resp_parts: list[types.Part] = []
        called_propose = False
        for fc in fcalls:
            fname = str(fc.name or "")
            fargs = dict(fc.args or {})
            result = _execute_tool(
                fname,
                fargs,
                target_cell=target_cell,
                incident_t=incident_t,
                date_str=date_str,
                verdict_flooded_p=verdict_flooded_p,
            )
            trace.append({"tool": fname, "args": fargs, "result": result})
            if fname == "propose_zone":
                called_propose = True
            resp_parts.append(types.Part.from_function_response(name=fname, response=result))

        contents.append(types.Content(role="user", parts=resp_parts))
        if called_propose:
            break

    return trace


def _ensure_contract_steps(
    trace: list[dict[str, Any]],
    *,
    verdict: dict[str, Any],
    target_cell: str,
    incident_t: str,
    date_str: str,
    verdict_flooded_p: float | None,
) -> list[dict[str, Any]]:
    """Guarantee >= 3 tool steps and that steps[-1]['result'] is a valid camera zone."""
    tools_called = {s["tool"] for s in trace}

    hist_result: dict[str, Any] | None = None
    for s in trace:
        if s["tool"] == "get_cell_history" and isinstance(s.get("result"), dict):
            hist_result = s["result"]
    if hist_result is None:
        hist_result = get_cell_history(target_cell)
        trace.insert(0, {"tool": "get_cell_history", "args": {"cell": target_cell}, "result": hist_result})
        tools_called.add("get_cell_history")

    fc_result: dict[str, Any] | None = None
    for s in trace:
        if s["tool"] == "get_forecast" and isinstance(s.get("result"), dict):
            fc_result = s["result"]
    if fc_result is None:
        fc_result = get_forecast(date_str)
        trace.append({"tool": "get_forecast", "args": {"date": date_str}, "result": fc_result})
        tools_called.add("get_forecast")

    # Find if propose_zone was already called; if so, move the latest one to the end.
    propose_indices = [i for i, s in enumerate(trace) if s["tool"] == "propose_zone"]
    if propose_indices:
        last_idx = propose_indices[-1]
        if last_idx != len(trace) - 1:
            zone_step = trace.pop(last_idx)
            trace.append(zone_step)
        return trace

    # Safety net: synthesize propose_zone from gathered evidence.
    selected_cells = [target_cell]
    for nb in hist_result.get("neighbors", [])[:3]:
        if nb.get("n_storm_days", 0) >= 2 or nb.get("n_reports", 0) >= 5:
            selected_cells.append(nb["id"])
    storm_days = hist_result.get("cell", {}).get("storm_days", [])
    if not storm_days:
        for nb in hist_result.get("neighbors", []):
            if nb.get("storm_days"):
                storm_days = nb["storm_days"]
                break
    storm_cite = ", ".join(storm_days[:3]) if storm_days else "prior storm events"
    depth_label = verdict.get("depth_label", "standing water")
    total_mm = fc_result.get("total_mm", 0.0)
    end_t = _add_hours_iso(incident_t, 4)
    reason = (
        f"Camera detected {depth_label} roadway flooding (p={verdict_flooded_p or 0.85:.2f}) at {target_cell}. "
        f"Local basin has flood history on {storm_cite}, with {total_mm:.1f} mm forecasted for {date_str}."
    )
    zone = propose_zone(
        cells=selected_cells,
        start=incident_t,
        end=end_t,
        reason=reason,
        target_cell=target_cell,
        verdict_flooded_p=verdict_flooded_p,
    )
    trace.append(
        {
            "tool": "propose_zone",
            "args": {
                "cells": selected_cells,
                "start": incident_t,
                "end": end_t,
                "reason": reason,
                "fleet_notice": zone["fleet_notice"],
            },
            "result": zone,
        }
    )
    return trace


def run_incident(verdict: dict[str, Any], on_step: Any = None) -> list[dict[str, Any]]:
    """Run the Managed Agent flood-incident response workflow for a camera verdict.

    Returns a list of tool step dicts: [{"tool": str, "args": dict, "result": Any}, ...]
    with at least 3 steps, where steps[-1]["result"] is the contract zone dict (source="camera").
    """
    grid, _ = _load_cells_index()
    v = dict(verdict or {})

    target_cell = v.get("cell")
    if not target_cell:
        if "lat" in v and "lon" in v:
            target_cell = latlon_to_cell(float(v["lat"]), float(v["lon"]), grid)
        else:
            target_cell = "r40_c57"
    target_cell = str(target_cell).strip()
    v["cell"] = target_cell

    raw_t = str(v.get("t") or "").strip()
    raw_date = str(v.get("date") or "").strip()
    date_str = (raw_date[:10] if len(raw_date) >= 10 else (raw_t[:10] if len(raw_t) >= 10 else DEFAULT_DATE))
    incident_t = _normalize_iso_minute(raw_t, f"{date_str}T10:00")
    date_str = incident_t[:10]
    v["t"] = incident_t
    v["date"] = date_str

    verdict_flooded_p = float(v["flooded_p"]) if v.get("flooded_p") is not None else None
    has_image_path = bool(v.get("path"))
    prompt = _build_incident_prompt(v, target_cell, incident_t, date_str)

    agent_engine = MANAGED_AGENT_NAME
    interaction_id: str | None = None
    thoughts: list[str] = []
    try:
        trace, interaction_id, thoughts = _run_managed_agent_loop(
            prompt,
            target_cell=target_cell,
            incident_t=incident_t,
            date_str=date_str,
            verdict_flooded_p=verdict_flooded_p,
            has_image_path=has_image_path,
            on_step=on_step,
        )
    except Exception:
        agent_engine = FALLBACK_CARBON_MODEL
        trace = _run_carbon_fallback_loop(
            prompt,
            target_cell=target_cell,
            incident_t=incident_t,
            date_str=date_str,
            verdict_flooded_p=verdict_flooded_p,
        )

    final_steps = _ensure_contract_steps(
        trace,
        verdict=v,
        target_cell=target_cell,
        incident_t=incident_t,
        date_str=date_str,
        verdict_flooded_p=verdict_flooded_p,
    )
    if final_steps and isinstance(final_steps[-1].get("result"), dict):
        final_steps[-1]["result"]["agent_engine"] = agent_engine
        if interaction_id:
            final_steps[-1]["result"]["interaction_id"] = interaction_id
        if thoughts:
            final_steps[-1]["result"]["thought_summary"] = " | ".join(thoughts[:3])
    return final_steps


# ---------------------------------------------------------------------------
# Wave 3 Task G10: Managed Agent ride decision (run_ride + load_ride_trace)
# ---------------------------------------------------------------------------

RIDE_AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_forecast",
        "description": (
            "Get hourly precipitation forecast, 24h total_mm, max_6h_mm, and latest forecast update "
            "for a date (YYYY-MM-DD)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format, e.g. '2026-11-18'.",
                }
            },
            "required": ["date"],
        },
    },
    {
        "type": "function",
        "name": "get_cell_history",
        "description": (
            "Look up historical 311 flood reports, storm_days, 6h rain threshold, top addresses, "
            "and adjacent neighbor cells for a San Francisco grid cell ID (e.g. 'r50_c66')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cell": {
                    "type": "string",
                    "description": "Grid cell ID formatted as r{row}_c{col}, e.g. 'r50_c66'.",
                }
            },
            "required": ["cell"],
        },
    },
    {
        "type": "function",
        "name": "simulate_street",
        "description": (
            "Inspect the Genie 4 + Decision 1 simulated roadway flood verdict for a watch cell ahead "
            "on the route. Returns verdict (flooded_p, depth_label, rubric, agreement, action) and source."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "cell": {
                    "type": "string",
                    "description": "Grid cell ID of the street to simulate/inspect, e.g. 'r50_c66'.",
                }
            },
            "required": ["cell"],
        },
    },
    {
        "type": "function",
        "name": "route_options",
        "description": (
            "Compare the default route travel time against a flood-avoiding reroute avoiding the "
            "specified risky grid cell IDs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "avoid_cells": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of risky grid cell IDs from the ride plan to avoid.",
                }
            },
            "required": ["avoid_cells"],
        },
    },
    {
        "type": "function",
        "name": "decide",
        "description": (
            "Record the final ride routing decision after reviewing forecast, cell history, "
            "simulated street verdict, and route options."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["reroute", "proceed"],
                    "description": "Whether the robotaxi should 'reroute' around flood-prone blocks or 'proceed'.",
                },
                "avoid_cells": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Subset of risky cell IDs from the plan to avoid (empty list if action is 'proceed')."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Concise audit explanation citing forecast rain, historical storm dates from cell "
                        "history, and the simulated street verdict (explicitly refer to it as simulated)."
                    ),
                },
                "rider_message": {
                    "type": "string",
                    "description": "Calm, jargon-free message for the passenger (<= 140 chars).",
                },
                "fleet_notice": {
                    "type": "string",
                    "description": "One-line fleet operations notice naming the block and time window (<= 200 chars).",
                },
            },
            "required": ["action", "avoid_cells", "reason", "rider_message", "fleet_notice"],
        },
    },
]


def load_ride_trace(date: str = DEFAULT_DATE) -> dict[str, Any] | None:
    """Load a saved ride audit trace from media/traces/ride_<date>.json.

    Falls back to any media/traces/ride_*.json if the exact date file is missing.
    Keeps the original agent_engine and sets replayed=True. Never raises.
    """
    try:
        day = str(date or DEFAULT_DATE).strip()[:10]
        candidates: list[Path] = []
        if day:
            candidates.append(TRACES_DIR / f"ride_{day}.json")
        if TRACES_DIR.is_dir():
            for p in sorted(TRACES_DIR.glob("ride_*.json"), reverse=True):
                if p not in candidates:
                    candidates.append(p)
        for path in candidates:
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if (
                isinstance(data, dict)
                and isinstance(data.get("steps"), list)
                and isinstance(data.get("decision"), dict)
            ):
                out = dict(data)
                if not out.get("agent_engine"):
                    out["agent_engine"] = "replay"
                out["replayed"] = True
                return out
    except Exception:
        return None
    return None


def _ride_simulate_street(
    cell: str,
    watch_cell: str,
    tools: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return ONLY {verdict, source} for a street cell; never starts a Genie session."""
    clean_cell = str(cell or watch_cell or "").strip()
    if isinstance(tools, dict) and callable(tools.get("simulate_street")):
        try:
            raw = tools["simulate_street"](clean_cell)
            if isinstance(raw, dict) and raw.get("verdict") is not None:
                return {
                    "verdict": raw.get("verdict"),
                    "source": str(raw.get("source") or "cache"),
                }
        except Exception:
            pass

    cache_candidates: list[Path] = []
    if clean_cell:
        cache_candidates.append(SIM_CACHE_DIR / clean_cell / "result.json")
    if watch_cell and watch_cell != clean_cell:
        cache_candidates.append(SIM_CACHE_DIR / watch_cell / "result.json")
    if SIM_CACHE_DIR.is_dir():
        for p in sorted(SIM_CACHE_DIR.glob("*/result.json")):
            if p not in cache_candidates:
                cache_candidates.append(p)

    for path in cache_candidates:
        if not path.is_file():
            continue
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(cached, dict) and cached.get("verdict") is not None:
                return {
                    "verdict": cached.get("verdict"),
                    "source": "cache",
                }
        except Exception:
            continue

    return {
        "verdict": {
            "flooded_p": None,
            "depth_score": None,
            "depth_label": None,
            "action": "slow",
        },
        "source": "missing",
    }


def _ride_route_options(
    avoid_cells: Any,
    plan: dict[str, Any],
    tools: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare default route vs. flood-avoiding route via injected callable or safe default."""
    risky_cells = [str(c).strip() for c in (plan.get("risky") or []) if str(c).strip()]
    risky_set = set(risky_cells)
    raw_list = avoid_cells if isinstance(avoid_cells, list) else ([avoid_cells] if isinstance(avoid_cells, str) else [])
    clean_avoid: list[str] = []
    seen: set[str] = set()
    for c in raw_list:
        cs = str(c).strip()
        if not cs or cs in seen:
            continue
        if risky_set and cs not in risky_set:
            continue
        seen.add(cs)
        clean_avoid.append(cs)
    if not clean_avoid and risky_cells:
        clean_avoid = risky_cells[:6]

    if isinstance(tools, dict) and callable(tools.get("route_options")):
        try:
            res = tools["route_options"](clean_avoid)
            if isinstance(res, dict):
                return res
        except Exception:
            pass

    route_info = plan.get("route") if isinstance(plan.get("route"), dict) else {}
    return {
        "default": {"min": route_info.get("min")},
        "safe": None,
    }


def _normalize_ride_decision(
    args: dict[str, Any],
    plan: dict[str, Any],
    *,
    sim_res: dict[str, Any] | None = None,
    route_res: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and normalize the final ride decision with strict avoid_cells guard."""
    risky_cells = [str(c).strip() for c in (plan.get("risky") or []) if str(c).strip()]
    risky_set = set(risky_cells)

    raw_action = str(args.get("action") or "").strip().lower()
    if raw_action in ("reroute", "avoid", "detour"):
        action = "reroute"
    elif raw_action in ("proceed", "continue", "stay", "keep"):
        action = "proceed"
    else:
        v = (sim_res or {}).get("verdict") if isinstance(sim_res, dict) else {}
        v = v if isinstance(v, dict) else {}
        v_act = str(v.get("action") or "").strip().lower()
        fp = v.get("flooded_p")
        rubric = v.get("rubric") if isinstance(v.get("rubric"), dict) else {}
        stall = rubric.get("sedan_stall")
        should_reroute = (
            v_act == "avoid"
            or (isinstance(fp, (int, float)) and fp >= 0.6)
            or (isinstance(stall, (int, float)) and stall >= 0.5)
        )
        action = "reroute" if should_reroute else "proceed"

    raw_avoid = args.get("avoid_cells")
    if isinstance(raw_avoid, str):
        raw_avoid = [raw_avoid]
    elif not isinstance(raw_avoid, list):
        raw_avoid = []

    filtered_avoid: list[str] = []
    seen: set[str] = set()
    for c in raw_avoid:
        cs = str(c).strip()
        if cs in risky_set and cs not in seen:
            seen.add(cs)
            filtered_avoid.append(cs)

    if action == "reroute" and not filtered_avoid:
        filtered_avoid = risky_cells[:6]
    elif action == "proceed":
        filtered_avoid = []

    watch = plan.get("watch") if isinstance(plan.get("watch"), dict) else {}
    warning = plan.get("warning") if isinstance(plan.get("warning"), dict) else {}
    peak = warning.get("peak") if isinstance(warning.get("peak"), dict) else {}
    watch_name = str(watch.get("name") or watch.get("cell") or "flood-prone corridor")
    peak_mm = peak.get("mm")
    peak_t = str(peak.get("t") or plan.get("t") or "")
    hhmm = peak_t[11:16] if len(peak_t) >= 16 else "09:00"
    n_days = watch.get("n_storm_days")
    storm_days = watch.get("storm_days") if isinstance(watch.get("storm_days"), list) else []
    verdict = (sim_res or {}).get("verdict") if isinstance(sim_res, dict) else {}
    verdict = verdict if isinstance(verdict, dict) else {}
    fp = verdict.get("flooded_p")
    depth_label = verdict.get("depth_label") or "standing water"

    reason = str(args.get("reason") or "").strip()
    if not reason:
        parts = []
        if peak_mm is not None:
            parts.append(f"Forecast peaks at {peak_mm} mm/h around {hhmm}")
        if n_days:
            cite = f" ({', '.join(str(d) for d in storm_days[:2])})" if storm_days else ""
            parts.append(f"{watch_name} flooded on {n_days} past storm days{cite}")
        if isinstance(fp, (int, float)):
            parts.append(f"simulated street check shows {depth_label} roadway flooding (p={fp:.2f})")
        reason = "; ".join(parts) + "." if parts else f"Flood risk assessment complete for {watch_name}."

    rider_message = str(args.get("rider_message") or "").strip()
    if not rider_message:
        safe_info = (route_res or {}).get("safe") if isinstance(route_res, dict) else None
        added_txt = ""
        if isinstance(safe_info, dict) and safe_info.get("added_min") is not None:
            added_txt = f" (+{safe_info['added_min']} min)"
        if action == "reroute":
            rider_message = f"Taking a drier route around heavy rain near {watch_name}{added_txt}."
        else:
            rider_message = "Continuing on the planned route; roadway conditions ahead remain passable."

    fleet_notice = str(args.get("fleet_notice") or "").strip()
    if not fleet_notice:
        if action == "reroute":
            fleet_notice = (
                f"AVOID {watch_name} ({len(filtered_avoid)} cells) around {hhmm}: "
                f"forecast rain + simulated roadway flooding."
            )
        else:
            fleet_notice = f"MONITOR {watch_name} around {hhmm}: proceeding with caution."

    return {
        "action": action,
        "avoid_cells": filtered_avoid,
        "reason": reason,
        "rider_message": rider_message,
        "fleet_notice": fleet_notice,
    }


def _compact_ride_plan_for_prompt(plan: dict[str, Any]) -> dict[str, Any]:
    """Strip large route coordinate/timestamp arrays so the agent prompt stays lean and fast."""
    route = plan.get("route") if isinstance(plan.get("route"), dict) else {}
    watch = plan.get("watch") if isinstance(plan.get("watch"), dict) else {}
    watch_clean = {k: v for k, v in watch.items() if k != "photo"}
    if isinstance(watch.get("photo"), dict):
        watch_clean["photo_address"] = watch["photo"].get("address")
    return {
        "date": plan.get("date") or DEFAULT_DATE,
        "t": plan.get("t") or DEFAULT_TIME,
        "decide_t": plan.get("decide_t"),
        "route": {"min": route.get("min"), "km": route.get("km")},
        "warning": plan.get("warning"),
        "forecast_6h_mm": plan.get("forecast_6h_mm"),
        "watch": watch_clean,
        "risky": plan.get("risky") or [],
        "risky_detail": (plan.get("risky_detail") or [])[:6],
    }


def _build_ride_prompt(plan: dict[str, Any], date_str: str, watch_cell: str, risky_cells: list[str]) -> str:
    compact = _compact_ride_plan_for_prompt(plan)
    risky_json = json.dumps(risky_cells)
    return (
        "You are an autonomous robotaxi flood-safety decision agent operating in San Francisco.\n"
        "A mid-ride heavy-rain warning just arrived. Investigate the forecast, historical 311 flood "
        "memory, the simulated street condition ahead, and routing alternatives, then issue a final "
        "routing decision.\n\n"
        f"RIDE PLAN SUMMARY:\n{json.dumps(compact, indent=2)}\n\n"
        "REQUIRED WORKFLOW (be concise and fast — batch parallel tool calls):\n"
        "1. In your FIRST turn, call ALL FOUR evidence tools in parallel:\n"
        f"   - get_forecast(date='{date_str}')\n"
        f"   - get_cell_history(cell='{watch_cell}')\n"
        f"   - simulate_street(cell='{watch_cell}')\n"
        f"   - route_options(avoid_cells={risky_json})\n"
        "2. In your SECOND turn, call decide(action, avoid_cells, reason, rider_message, fleet_notice):\n"
        "   - action: 'reroute' if the simulated street verdict shows flooding/avoid (action=='avoid', "
        "flooded_p >= 0.6, or sedan_stall >= 0.5), else 'proceed'.\n"
        f"   - avoid_cells: MUST be a subset of {risky_json} (never invent cell IDs; use [] if proceeding).\n"
        "   - reason: cite real numbers from the forecast, past storm_days dates from cell history, and "
        "explicitly call the street check 'simulated' (never 'observed').\n"
        "   - rider_message: calm, jargon-free passenger message (<= 140 chars).\n"
        "   - fleet_notice: actionable one-line fleet ops notice naming the block and time window (<= 200 chars).\n"
        "Do NOT ask questions. Finish as soon as decide(...) is called."
    )


def _execute_ride_tool(
    name: str,
    args: dict[str, Any],
    *,
    plan: dict[str, Any],
    date_str: str,
    watch_cell: str,
    tools: dict[str, Any] | None,
    state: dict[str, Any],
) -> dict[str, Any]:
    if name == "get_forecast":
        res = get_forecast(str(args.get("date") or date_str))
        state["forecast"] = res
        return res
    if name == "get_cell_history":
        res = get_cell_history(str(args.get("cell") or watch_cell))
        state["history"] = res
        return res
    if name == "simulate_street":
        res = _ride_simulate_street(str(args.get("cell") or watch_cell), watch_cell, tools)
        state["sim"] = res
        return res
    if name == "route_options":
        res = _ride_route_options(args.get("avoid_cells"), plan, tools)
        state["route"] = res
        return res
    if name == "decide":
        res = _normalize_ride_decision(
            args,
            plan,
            sim_res=state.get("sim"),
            route_res=state.get("route"),
        )
        state["decision"] = res
        return res
    return {"error": f"Unknown tool: {name}"}


def _emit_step(on_step: Any, step: dict[str, Any], cancel_event: threading.Event | None = None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        return
    if callable(on_step):
        try:
            on_step(step)
        except Exception:
            pass


def _run_with_timeout(fn: Any, timeout_s: float, cancel_event: threading.Event) -> Any:
    """Run fn() in a daemon thread with a hard wall-clock timeout without blocking on abandon."""
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    th = threading.Thread(target=_target, daemon=True)
    th.start()
    th.join(timeout=max(0.1, float(timeout_s)))
    if th.is_alive():
        cancel_event.set()
        raise TimeoutError(f"Operation timed out after {timeout_s:.1f}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _run_ride_managed_agent_loop(
    prompt: str,
    *,
    plan: dict[str, Any],
    date_str: str,
    watch_cell: str,
    tools: dict[str, Any] | None,
    on_step: Any,
    deadline: float,
    cancel_event: threading.Event,
    max_turns: int = 5,
) -> tuple[list[dict[str, Any]], str | None, dict[str, Any]]:
    """Run multi-turn ride decision loop on Antigravity Managed Agents (antigravity-preview-09-2026)."""
    beta = get_beta_client()
    trace: list[dict[str, Any]] = []
    state: dict[str, Any] = {}
    prev_id: str | None = None
    first_interaction_id: str | None = None
    next_input: Any = prompt

    for _turn in range(max_turns):
        if cancel_event.is_set():
            raise TimeoutError("Managed Agent cancelled")
        remaining = deadline - time.perf_counter()
        if remaining <= 0.5:
            raise TimeoutError("Managed Agent deadline exceeded")

        kwargs: dict[str, Any] = {
            "agent": MANAGED_AGENT_NAME,
            "environment": "remote",
            "agent_config": {
                "type": "antigravity",
                "model": MANAGED_AGENT_MODEL,
                "max_total_tokens": MANAGED_AGENT_MAX_TOKENS,
            },
            "tools": RIDE_AGENT_TOOLS,
            "input": next_input,
            "timeout": max(3.0, min(30.0, remaining)),
        }
        if prev_id is not None:
            kwargs["previous_interaction_id"] = prev_id

        interaction = beta.interactions.create(**kwargs)
        if cancel_event.is_set():
            raise TimeoutError("Managed Agent cancelled")

        prev_id = getattr(interaction, "id", None)
        if first_interaction_id is None and prev_id:
            first_interaction_id = str(prev_id)
        status = getattr(interaction, "status", None)
        steps = getattr(interaction, "steps", None) or []

        if status == "failed":
            raise RuntimeError(f"Managed Agent interaction failed (id={prev_id})")

        fc_steps = [s for s in steps if getattr(s, "type", None) == "function_call"]
        if not fc_steps:
            break

        tool_responses: list[dict[str, Any]] = []
        called_decide = False
        for fc in fc_steps:
            if cancel_event.is_set():
                raise TimeoutError("Managed Agent cancelled")
            call_id = getattr(fc, "id", None) or getattr(fc, "call_id", None)
            fname = str(getattr(fc, "name", ""))
            raw_args = getattr(fc, "arguments", None) or {}
            fargs = dict(raw_args) if isinstance(raw_args, dict) else {}

            t_tool = time.perf_counter()
            result = _execute_ride_tool(
                fname,
                fargs,
                plan=plan,
                date_str=date_str,
                watch_cell=watch_cell,
                tools=tools,
                state=state,
            )
            ms = max(0, int(round((time.perf_counter() - t_tool) * 1000)))
            step_entry = {"tool": fname, "args": fargs, "result": result, "ms": ms}
            trace.append(step_entry)
            _emit_step(on_step, step_entry, cancel_event)

            if fname == "decide":
                called_decide = True

            tool_responses.append(
                {
                    "type": "function_result",
                    "call_id": call_id,
                    "name": fname,
                    "result": result,
                }
            )

        if called_decide:
            break
        if status != "requires_action":
            break
        next_input = tool_responses

    if not trace:
        raise RuntimeError(f"Managed Agent returned no tool calls (id={first_interaction_id})")
    return trace, first_interaction_id, state


def _run_ride_carbon_loop(
    prompt: str,
    *,
    plan: dict[str, Any],
    date_str: str,
    watch_cell: str,
    tools: dict[str, Any] | None,
    on_step: Any,
    deadline: float,
    cancel_event: threading.Event,
    max_turns: int = 5,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fallback function-calling loop on gemini-4-carbon (same 5 tools, default sampling)."""
    client = get_client()
    fn_decls = [
        types.FunctionDeclaration(
            name=t["name"],
            description=t["description"],
            parameters_json_schema=t["parameters"],
        )
        for t in RIDE_AGENT_TOOLS
    ]
    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=fn_decls)],
    )
    contents: list[Any] = [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])]
    trace: list[dict[str, Any]] = []
    state: dict[str, Any] = {}

    for _turn in range(max_turns):
        if cancel_event.is_set() or time.perf_counter() >= deadline:
            raise TimeoutError("Carbon fallback deadline exceeded")

        resp = client.models.generate_content(
            model=FALLBACK_CARBON_MODEL,
            contents=contents,
            config=config,
        )
        if cancel_event.is_set():
            raise TimeoutError("Carbon fallback cancelled")

        cand = (resp.candidates or [None])[0]
        if cand is None or cand.content is None:
            break
        contents.append(cand.content)

        fcalls = [p.function_call for p in (cand.content.parts or []) if p.function_call]
        if not fcalls:
            break

        resp_parts: list[types.Part] = []
        called_decide = False
        for fc in fcalls:
            fname = str(fc.name or "")
            fargs = dict(fc.args or {})
            t_tool = time.perf_counter()
            result = _execute_ride_tool(
                fname,
                fargs,
                plan=plan,
                date_str=date_str,
                watch_cell=watch_cell,
                tools=tools,
                state=state,
            )
            ms = max(0, int(round((time.perf_counter() - t_tool) * 1000)))
            step_entry = {"tool": fname, "args": fargs, "result": result, "ms": ms}
            trace.append(step_entry)
            _emit_step(on_step, step_entry, cancel_event)
            if fname == "decide":
                called_decide = True
            resp_parts.append(types.Part.from_function_response(name=fname, response=result))

        contents.append(types.Content(role="user", parts=resp_parts))
        if called_decide:
            break

    if not trace:
        raise RuntimeError("Carbon fallback returned no tool calls")
    return trace, state


def _ensure_ride_steps(
    trace: list[dict[str, Any]],
    *,
    plan: dict[str, Any],
    date_str: str,
    watch_cell: str,
    risky_cells: list[str],
    tools: dict[str, Any] | None,
    state: dict[str, Any],
    on_step: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Guarantee >= 4 steps covering evidence tools and ending in a validated 'decide' step."""
    steps = list(trace)
    present = {s.get("tool") for s in steps}

    # Keep any existing decide step aside so backfilled evidence appears before decide.
    decide_step: dict[str, Any] | None = None
    non_decide: list[dict[str, Any]] = []
    for s in steps:
        if s.get("tool") == "decide":
            decide_step = s
        else:
            non_decide.append(s)
    steps = non_decide

    def _run_missing(tool_name: str, tool_args: dict[str, Any]) -> None:
        t_tool = time.perf_counter()
        res = _execute_ride_tool(
            tool_name,
            tool_args,
            plan=plan,
            date_str=date_str,
            watch_cell=watch_cell,
            tools=tools,
            state=state,
        )
        ms = max(0, int(round((time.perf_counter() - t_tool) * 1000)))
        entry = {"tool": tool_name, "args": tool_args, "result": res, "ms": ms}
        steps.append(entry)
        _emit_step(on_step, entry)

    if "get_forecast" not in present:
        _run_missing("get_forecast", {"date": date_str})
    if "get_cell_history" not in present:
        _run_missing("get_cell_history", {"cell": watch_cell})
    if "simulate_street" not in present:
        _run_missing("simulate_street", {"cell": watch_cell})
    if "route_options" not in present:
        _run_missing("route_options", {"avoid_cells": risky_cells[:6]})

    if decide_step is not None:
        raw_dec = decide_step.get("result") if isinstance(decide_step.get("result"), dict) else {}
        normalized = _normalize_ride_decision(
            raw_dec,
            plan,
            sim_res=state.get("sim"),
            route_res=state.get("route"),
        )
        decide_step = {
            "tool": "decide",
            "args": decide_step.get("args") if isinstance(decide_step.get("args"), dict) else {},
            "result": normalized,
            "ms": int(decide_step.get("ms", 0)),
        }
        steps.append(decide_step)
        return steps, normalized

    t_tool = time.perf_counter()
    normalized = _normalize_ride_decision(
        {},
        plan,
        sim_res=state.get("sim"),
        route_res=state.get("route"),
    )
    ms = max(0, int(round((time.perf_counter() - t_tool) * 1000)))
    synth_step = {"tool": "decide", "args": dict(normalized), "result": normalized, "ms": ms}
    steps.append(synth_step)
    _emit_step(on_step, synth_step)
    return steps, normalized


def run_ride(
    plan: dict[str, Any],
    tools: dict[str, Any] | None = None,
    on_step: Any = None,
    timeout_s: float = 45.0,
) -> dict[str, Any]:
    """Run the end-to-end ride flood decision via Antigravity Managed Agents.

    Fallback chain (strict timeout_s, never raises):
      1. Antigravity Managed Agent (antigravity-preview-09-2026)
      2. gemini-4-carbon function-calling loop
      3. Saved trace via load_ride_trace(date) with replayed=True
      4. Deterministic synthesis fallback
    """
    t0 = time.perf_counter()
    safe_plan = plan if isinstance(plan, dict) else {}
    raw_date = str(safe_plan.get("date") or str(safe_plan.get("t") or "")[:10] or DEFAULT_DATE).strip()
    date_str = raw_date[:10] if len(raw_date) >= 10 else DEFAULT_DATE
    watch = safe_plan.get("watch") if isinstance(safe_plan.get("watch"), dict) else {}
    risky_cells = [str(c).strip() for c in (safe_plan.get("risky") or []) if str(c).strip()]
    watch_cell = str(watch.get("cell") or (risky_cells[0] if risky_cells else "r50_c66")).strip()

    total_budget = max(1.0, float(timeout_s))
    hard_deadline = t0 + total_budget
    prompt = _build_ride_prompt(safe_plan, date_str, watch_cell, risky_cells)

    emitted_any = False

    def _tracking_on_step(step: dict[str, Any]) -> None:
        nonlocal emitted_any
        emitted_any = True
        if callable(on_step):
            try:
                on_step(step)
            except Exception:
                pass

    # 1. Antigravity Managed Agents (antigravity-preview-09-2026)
    try:
        ma_budget = min(total_budget * 0.78, max(2.0, total_budget - 8.0)) if total_budget > 10.0 else total_budget * 0.7
        ma_deadline = min(hard_deadline, time.perf_counter() + ma_budget)
        ma_cancel = threading.Event()
        trace, interaction_id, state = _run_with_timeout(
            lambda: _run_ride_managed_agent_loop(
                prompt,
                plan=safe_plan,
                date_str=date_str,
                watch_cell=watch_cell,
                tools=tools,
                on_step=_tracking_on_step,
                deadline=ma_deadline,
                cancel_event=ma_cancel,
            ),
            timeout_s=max(0.5, ma_deadline - time.perf_counter()),
            cancel_event=ma_cancel,
        )
        steps, decision = _ensure_ride_steps(
            trace,
            plan=safe_plan,
            date_str=date_str,
            watch_cell=watch_cell,
            risky_cells=risky_cells,
            tools=tools,
            state=state,
            on_step=_tracking_on_step,
        )
        return {
            "steps": steps,
            "decision": decision,
            "agent_engine": MANAGED_AGENT_NAME,
            "interaction_id": interaction_id,
            "elapsed_s": round(time.perf_counter() - t0, 2),
        }
    except Exception:
        pass

    # 2. gemini-4-carbon function-calling loop
    rem_for_carbon = hard_deadline - time.perf_counter()
    if rem_for_carbon > 1.0:
        try:
            c_cancel = threading.Event()
            trace, state = _run_with_timeout(
                lambda: _run_ride_carbon_loop(
                    prompt,
                    plan=safe_plan,
                    date_str=date_str,
                    watch_cell=watch_cell,
                    tools=tools,
                    on_step=_tracking_on_step,
                    deadline=hard_deadline,
                    cancel_event=c_cancel,
                ),
                timeout_s=max(0.5, rem_for_carbon),
                cancel_event=c_cancel,
            )
            steps, decision = _ensure_ride_steps(
                trace,
                plan=safe_plan,
                date_str=date_str,
                watch_cell=watch_cell,
                risky_cells=risky_cells,
                tools=tools,
                state=state,
                on_step=_tracking_on_step,
            )
            return {
                "steps": steps,
                "decision": decision,
                "agent_engine": FALLBACK_CARBON_MODEL,
                "interaction_id": None,
                "elapsed_s": round(time.perf_counter() - t0, 2),
            }
        except Exception:
            pass

    # 3. Saved trace replay via load_ride_trace(date)
    try:
        replayed = load_ride_trace(date_str)
        if replayed is not None:
            if risky_cells and isinstance(replayed.get("decision"), dict):
                replayed["decision"] = _normalize_ride_decision(replayed["decision"], safe_plan)
            replayed["replayed"] = True
            replayed["elapsed_s"] = round(time.perf_counter() - t0, 2)
            if not emitted_any and callable(on_step):
                for s in replayed.get("steps", []):
                    _emit_step(on_step, s)
            return replayed
    except Exception:
        pass

    # 4. Deterministic synthesis fallback (only if no saved trace exists)
    try:
        state = {}
        steps, decision = _ensure_ride_steps(
            [],
            plan=safe_plan,
            date_str=date_str,
            watch_cell=watch_cell,
            risky_cells=risky_cells,
            tools=tools,
            state=state,
            on_step=_tracking_on_step if not emitted_any else None,
        )
        return {
            "steps": steps,
            "decision": decision,
            "agent_engine": "replay",
            "interaction_id": None,
            "replayed": True,
            "elapsed_s": round(time.perf_counter() - t0, 2),
        }
    except Exception:
        fallback_decision = {
            "action": "reroute" if risky_cells else "proceed",
            "avoid_cells": risky_cells[:6],
            "reason": f"Fallback flood safety decision for {watch_cell} on {date_str}.",
            "rider_message": "Taking a safer route around potential street flooding.",
            "fleet_notice": f"AVOID {watch_cell}: fallback flood safety routing active.",
        }
        return {
            "steps": [{"tool": "decide", "args": dict(fallback_decision), "result": fallback_decision, "ms": 0}],
            "decision": fallback_decision,
            "agent_engine": "replay",
            "interaction_id": None,
            "replayed": True,
            "elapsed_s": round(time.perf_counter() - t0, 2),
        }


def _save_ride_trace(result: dict[str, Any], date_str: str) -> Path | None:
    try:
        TRACES_DIR.mkdir(parents=True, exist_ok=True)
        day = str(date_str or DEFAULT_DATE).strip()[:10] or DEFAULT_DATE
        out_path = TRACES_DIR / f"ride_{day}.json"
        payload = dict(result)
        payload.pop("replayed", None)
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return out_path
    except Exception:
        return None


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "ride":
        plan_path = Path(argv[1])
        if not plan_path.is_absolute():
            candidate = REPO_ROOT / plan_path
            if candidate.exists():
                plan_path = candidate
        if not plan_path.is_file():
            print(f"Plan file not found: {plan_path}", file=sys.stderr)
            return 2
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        res = run_ride(plan)
        if not res.get("replayed") and res.get("agent_engine") == MANAGED_AGENT_NAME:
            date_str = str(plan.get("date") or str(plan.get("t") or "")[:10] or DEFAULT_DATE)[:10]
            _save_ride_trace(res, date_str)
        print(json.dumps(res, indent=2))
        return 0

    if len(argv) < 3:
        print(
            "Usage: python -m gem.agent <image_path> <lat> <lon> [YYYY-MM-DDTHH:MM]\n"
            "   or: python -m gem.agent ride <plan.json>",
            file=sys.stderr,
        )
        return 2

    image_path = argv[0]
    lat = float(argv[1])
    lon = float(argv[2])
    incident_t = argv[3] if len(argv) >= 4 else DEFAULT_TIME

    t0 = time.perf_counter()
    vision_res = judge_frame(image_path)
    cell = latlon_to_cell(lat, lon)
    verdict = {
        "lat": lat,
        "lon": lon,
        "cell": cell,
        "t": incident_t,
        "date": incident_t[:10],
        "path": image_path,
        "flooded_p": vision_res.get("flooded_p", 0.0),
        "depth_score": vision_res.get("depth_score", 0.0),
        "depth_label": vision_res.get("depth_label", "none"),
        "latency_ms": vision_res.get("latency_ms", 0),
    }

    steps = run_incident(verdict)
    elapsed = time.perf_counter() - t0

    print(f"=== Incident Verdict (cell={cell}, elapsed={elapsed:.2f}s) ===")
    print(json.dumps(verdict, indent=2))
    print(f"\n=== Agent Tool Steps ({len(steps)} steps) ===")
    for idx, step in enumerate(steps, 1):
        print(f"\n--- Step {idx}: {step['tool']} ---")
        print("args:", json.dumps(step["args"]))
        res_preview = json.dumps(step["result"])
        if len(res_preview) > 400 and step["tool"] != "propose_zone":
            res_preview = res_preview[:397] + "..."
        print("result:", res_preview)

    print("\n=== Final Proposed Zone ===")
    print(json.dumps(steps[-1]["result"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
