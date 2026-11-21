"""G9: Grounded ride-decision explainer using Gemini 4 Carbon with deterministic fallback.

Exposes:
    explain_decision(plan: dict, sim: dict, reroute: dict | None = None, timeout_s: float = 8.0) -> dict

CLI:
    .venv/bin/python -m gem.explain media/sim_cache/plan_sample.json [media/sim_cache/<cell>/result.json]
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import sys
import time
from typing import Any

from google.genai import types
from pydantic import BaseModel, Field

from gem.client import REPO_ROOT, get_client

MODEL_NAME = "gemini-4-carbon"

DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
MM_RE = re.compile(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)\s*mm(?:/h|/hr|h)?\b", re.IGNORECASE)
HHMM_RE = re.compile(r"(?:^|T|\s)(\d{2}:\d{2})(?::\d{2})?(?!\d)")
OBSERVED_RE = re.compile(r"\bobserved\b", re.IGNORECASE)
SIMULATED_RE = re.compile(r"\bsimulated\b", re.IGNORECASE)
ORDINAL_RE = re.compile(r"^(\d+)(ST|ND|RD|TH)$", re.IGNORECASE)

HEADLINE_MAX = 90
RIDER_MAX = 140
FLEET_MAX = 200


class ExplanationDraft(BaseModel):
    headline: str = Field(
        description="Short decision headline, strictly <= 90 characters."
    )
    reasons: list[str] = Field(
        description=(
            "Exactly 3 concise reasons: "
            "[0] forecast rain rate/total and timing (citing peak mm/h and/or 6h total), "
            "[1] historical flood memory at the block (citing n_storm_days and at least one exact YYYY-MM-DD date from storm_days), "
            "[2] Genie 4 simulated street-view assessment (must use the word 'simulated', never 'observed')."
        )
    )
    rider_message: str = Field(
        description=(
            "Calm, plain-language rider message, strictly <= 140 characters. "
            "No jargon (no cell IDs, mm/h, or probabilities). "
            "If reroute.added_min is given and action is reroute, state the added minutes."
        )
    )
    fleet_notice: str = Field(
        description=(
            "Operational fleet notice, strictly <= 200 characters. "
            "Must name the watch intersection/block and the forecast time window (HH:MM-HH:MM)."
        )
    )


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val: Any, default: int = 0) -> int:
    try:
        if val is None:
            return default
        return int(val)
    except (TypeError, ValueError):
        return default


def _extract_hhmm(ts: Any, default: str = "09:00") -> str:
    if not isinstance(ts, str):
        return default
    m = HHMM_RE.search(ts)
    return m.group(1) if m else default


def _pretty_block(name: str) -> str:
    """Turn '4TH ST and KING ST' into '4th St & King St' while keeping short/clean labels."""
    raw = (name or "").strip()
    if not raw:
        return "the corridor ahead"
    tokens = raw.split()
    non_conj = [t for t in tokens if t.lower() not in ("and", "at", "of")]
    if not non_conj or not all(t == t.upper() for t in non_conj):
        return raw
    out: list[str] = []
    for tok in tokens:
        low = tok.lower()
        if low == "and":
            out.append("&")
            continue
        m = ORDINAL_RE.match(tok)
        if m:
            out.append(f"{m.group(1)}{m.group(2).lower()}")
        else:
            out.append(tok.capitalize())
    return " ".join(out)


def _truncate(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: max(1, limit - 1)].rstrip(" ,;:-")
    if " " in cut and len(cut) > limit // 2:
        cut = cut.rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut + "."


def _extract_context(
    plan: dict[str, Any] | None,
    sim: dict[str, Any] | None,
    reroute: dict[str, Any] | None,
) -> dict[str, Any]:
    """Extract only allowed fields from plan/sim/reroute (never Nov 18 events or photo metadata)."""
    plan = plan if isinstance(plan, dict) else {}
    sim = sim if isinstance(sim, dict) else {}
    reroute_clean: dict[str, Any] | None = None
    if isinstance(reroute, dict):
        reroute_clean = {
            k: reroute[k]
            for k in ("added_min", "min", "km")
            if k in reroute and reroute[k] is not None
        }
        if not reroute_clean:
            reroute_clean = None

    # Support BOTH v1 plan (warning.peak, forecast_6h_mm, risky_detail) AND v2 check/merged plan (peak, six_h_mm, risky_b)
    warning = plan.get("warning") if isinstance(plan.get("warning"), dict) else {}
    peak = (
        warning.get("peak")
        if isinstance(warning.get("peak"), dict)
        else (plan.get("peak") if isinstance(plan.get("peak"), dict) else {})
    )
    peak_mm = round(_safe_float(peak.get("mm"), 0.0), 1)
    forecast_t = _extract_hhmm(peak.get("t"), _extract_hhmm(plan.get("t"), "09:00"))
    raw_6h = plan.get("forecast_6h_mm") if plan.get("forecast_6h_mm") is not None else plan.get("six_h_mm")
    forecast_6h_mm = round(_safe_float(raw_6h, peak_mm), 1)

    next_hours = (
        warning.get("next_hours")
        if isinstance(warning.get("next_hours"), list)
        else (plan.get("next_hours") if isinstance(plan.get("next_hours"), list) else [])
    )
    hour_labels = [_extract_hhmm(h.get("t"), "") for h in next_hours if isinstance(h, dict)]
    hour_labels = [h for h in hour_labels if h]
    if len(hour_labels) >= 2:
        window = f"{hour_labels[0]}-{hour_labels[-1]}"
    elif len(hour_labels) == 1:
        window = hour_labels[0]
    else:
        window = forecast_t

    watch = plan.get("watch") if isinstance(plan.get("watch"), dict) else {}
    watch_name_raw = str(watch.get("name") or watch.get("cell") or "watch block")
    watch_block = _pretty_block(watch_name_raw)
    watch_n_storms = _safe_int(watch.get("n_storm_days"), 0)
    watch_storm_days = [
        str(d) for d in (watch.get("storm_days") or []) if isinstance(d, str) and DATE_RE.fullmatch(d)
    ]
    watch_eta = _extract_hhmm(watch.get("eta"), forecast_t)

    risky_raw = (
        plan.get("risky_detail")
        if isinstance(plan.get("risky_detail"), list)
        else (plan.get("risky_b") if isinstance(plan.get("risky_b"), list) else [])
    )
    top3_risky: list[dict[str, Any]] = []
    allowed_dates: set[str] = set(watch_storm_days)
    for item in risky_raw[:3]:
        if not isinstance(item, dict):
            continue
        sdays = [
            str(d) for d in (item.get("storm_days") or []) if isinstance(d, str) and DATE_RE.fullmatch(d)
        ]
        allowed_dates.update(sdays)
        top3_risky.append(
            {
                "name": _pretty_block(str(item.get("name") or item.get("cell") or "")),
                "n_storm_days": _safe_int(item.get("n_storm_days"), 0),
                "storm_days": sdays,
                "eta": _extract_hhmm(item.get("eta"), ""),
            }
        )

    verdict = sim.get("verdict") if isinstance(sim.get("verdict"), dict) else {}
    raw_action = verdict.get("action")
    raw_fp = verdict.get("flooded_p") if verdict.get("flooded_p") is not None else verdict.get("lane_covered")
    flooded_p = round(_safe_float(raw_fp, 0.0), 3)
    if isinstance(raw_action, str) and raw_action.strip():
        action = "reroute" if raw_action.strip().lower() == "avoid" else "proceed"
    else:
        action = "reroute" if flooded_p >= 0.6 else "proceed"

    verdict_for_model: dict[str, Any] = {
        "action": verdict.get("action"),
        "flooded_p": flooded_p,
        "depth_label": verdict.get("depth_label") or "unknown",
        "depth_score": verdict.get("depth_score"),
    }
    for extra in ("lane_covered", "edges_hidden", "p_tire_or_worse", "depth_level", "rubric", "trend", "agreement"):
        if extra in verdict and verdict[extra] is not None:
            verdict_for_model[extra] = verdict[extra]

    # Strict payload: ONLY warning (time-only, no Nov 18 date/other hourly mm),
    # forecast_6h_mm, watch (no photo), top 3 risky_detail, sim["verdict"], reroute.
    model_payload = {
        "decision_action": action,
        "warning": {
            "source": warning.get("source", "latest"),
            "peak_mm_per_h": peak_mm,
            "peak_time": forecast_t,
            "time_window": window,
            "text": str(warning.get("text") or ""),
        },
        "forecast_6h_mm": forecast_6h_mm,
        "watch": {
            "name": watch_block,
            "n_storm_days": watch_n_storms,
            "storm_days": watch_storm_days,
            "eta": watch_eta,
        },
        "top_risky_blocks": top3_risky,
        "simulated_verdict": verdict_for_model,
        "reroute": reroute_clean,
    }

    allowed_mm: list[float] = []
    if peak.get("mm") is not None:
        allowed_mm.append(peak_mm)
    if plan.get("forecast_6h_mm") is not None:
        allowed_mm.append(forecast_6h_mm)
    if not allowed_mm:
        allowed_mm.append(peak_mm)

    return {
        "action": action,
        "peak_mm": peak_mm,
        "forecast_t": forecast_t,
        "forecast_6h_mm": forecast_6h_mm,
        "window": window,
        "watch_block": watch_block,
        "watch_name_raw": watch_name_raw,
        "watch_n_storms": watch_n_storms,
        "watch_storm_days": watch_storm_days,
        "allowed_dates": allowed_dates,
        "allowed_mm": allowed_mm,
        "flooded_p": flooded_p,
        "depth_label": str(verdict.get("depth_label") or "standing water"),
        "reroute": reroute_clean,
        "model_payload": model_payload,
    }


def _build_cited(ctx: dict[str, Any], texts: list[str] | None = None) -> dict[str, Any]:
    storm_days = list(ctx["watch_storm_days"])
    if texts:
        combined = " ".join(texts)
        for d in DATE_RE.findall(combined):
            if d in ctx["allowed_dates"] and d not in storm_days:
                storm_days.append(d)
    return {
        "storm_days": storm_days,
        "forecast_mm": ctx["peak_mm"],
        "forecast_t": ctx["forecast_t"],
        "n_storm_days": ctx["watch_n_storms"],
        "flooded_p": ctx["flooded_p"],
    }


def _format_added_min(reroute: dict[str, Any] | None) -> str | None:
    if not reroute or reroute.get("added_min") is None:
        return None
    val = _safe_float(reroute.get("added_min"), 0.0)
    rounded = max(1, int(round(val))) if val >= 0.5 else round(val, 1)
    unit = "minute" if rounded == 1 else "minutes"
    return f"{rounded} {unit}"


def _build_template(ctx: dict[str, Any], latency_ms: int) -> dict[str, Any]:
    action = ctx["action"]
    block = ctx["watch_block"]
    peak_mm = ctx["peak_mm"]
    f6 = ctx["forecast_6h_mm"]
    ft = ctx["forecast_t"]
    window = ctx["window"]
    n_storms = ctx["watch_n_storms"]
    sdays = ctx["watch_storm_days"]
    flooded_p = ctx["flooded_p"]
    pct = int(round(flooded_p * 100))
    depth = ctx["depth_label"]
    added_str = _format_added_min(ctx["reroute"])

    date_phrase = f"including {sdays[0]}" + (f" and {sdays[1]}" if len(sdays) >= 2 else "") if sdays else "in prior storms"

    if action == "reroute":
        headline = _truncate(f"Rerouting around {block}: simulated flooding ahead", HEADLINE_MAX)
        reasons = [
            f"Forecast expects {peak_mm:.1f} mm/h peak rain at {ft} ({f6:.1f} mm over 6h).",
            f"Flood memory shows {block} flooded on {n_storms} past storm days, {date_phrase}.",
            f"Simulated street view predicts {depth} roadway water ({pct}% flood likelihood); rerouting clear.",
        ]
        if added_str:
            rider_message = _truncate(
                f"Taking an alternate route around heavy rain ahead. This adds about {added_str} for a safer ride.",
                RIDER_MAX,
            )
        else:
            rider_message = _truncate(
                "Taking an alternate route to stay clear of heavy rain and street pooling ahead for a smoother ride.",
                RIDER_MAX,
            )
        fleet_notice = _truncate(
            f"Reroute around {block} ({window}): {peak_mm:.1f} mm/h forecast, {n_storms} prior flood days, simulated roadway flooding.",
            FLEET_MAX,
        )
    else:
        headline = _truncate(f"Proceeding via {block}: simulated street looks passable", HEADLINE_MAX)
        reasons = [
            f"Forecast expects {peak_mm:.1f} mm/h peak rain at {ft} ({f6:.1f} mm over 6h).",
            f"Flood memory notes {block} flooded on {n_storms} past storm days, {date_phrase}.",
            f"Simulated street view indicates passable conditions ({depth}, {pct}% flood likelihood); safe to proceed.",
        ]
        rider_message = _truncate(
            "Rain is expected ahead, but your route looks clear and your trip is continuing on schedule.",
            RIDER_MAX,
        )
        fleet_notice = _truncate(
            f"Proceed via {block} ({window}): {peak_mm:.1f} mm/h forecast, {n_storms} prior flood days, simulated view passable.",
            FLEET_MAX,
        )

    return {
        "action": action,
        "headline": headline,
        "reasons": reasons,
        "rider_message": rider_message,
        "fleet_notice": fleet_notice,
        "cited": _build_cited(ctx, [headline, *reasons, rider_message, fleet_notice]),
        "model": "template",
        "latency_ms": max(0, int(latency_ms)),
    }


def _build_prompt(ctx: dict[str, Any], retry_feedback: str | None = None) -> str:
    payload_json = json.dumps(ctx["model_payload"], separators=(",", ":"))
    allowed_dates = sorted(ctx["allowed_dates"], reverse=True)
    allowed_mm_str = ", ".join(f"{v:.1f}" for v in sorted(set(ctx["allowed_mm"])))

    prompt = f"""You explain an autonomous vehicle's rain-routing decision to a rider and a fleet operator.
Return ONLY valid JSON matching the schema.

INPUT DATA (the ONLY facts you may use):
{payload_json}

STRICT RULES:
1. Fixed action: The decision is ALREADY made (`decision_action` = "{ctx['action']}"). Explain this exact action; never contradict it.
2. Length limits (strict):
   - `headline`: <= {HEADLINE_MAX} characters.
   - `reasons`: EXACTLY 3 concise sentences:
     * reasons[0]: Forecast rain — must include `{ctx['peak_mm']:.1f} mm/h` at `{ctx['forecast_t']}` (and optionally `{ctx['forecast_6h_mm']:.1f} mm` 6h total).
     * reasons[1]: Flood memory — must include `{ctx['watch_n_storms']}` past storm days and at least one exact `YYYY-MM-DD` date verbatim from `watch.storm_days` ({allowed_dates[:5]}).
     * reasons[2]: Street-view simulation — must explicitly use the word "simulated" (NEVER "observed") to describe the Genie 4 preview and verdict.
   - `rider_message`: <= {RIDER_MAX} characters. Calm, reassuring, zero technical jargon (no cell IDs, no mm/h, no probabilities, no model names). If `reroute.added_min` is present and action is "reroute", mention the added minutes naturally.
   - `fleet_notice`: <= {FLEET_MAX} characters. Must name the block (`{ctx['watch_block']}`) and the time window (`{ctx['window']}`).
3. Grounding rules (CRITICAL — checked by automated validator):
   - Every `YYYY-MM-DD` date anywhere in your text MUST be one of: {allowed_dates}. Do NOT write today's date or any other `YYYY-MM-DD` date!
   - Every `mm` or `mm/h` figure anywhere in your text MUST equal one of: [{allowed_mm_str}]. Do NOT write any other mm figure!
   - NEVER use the word "observed" anywhere in any field. Always say "simulated" for the street preview.
"""
    if retry_feedback:
        prompt += f"\nPREVIOUS OUTPUT FAILED VALIDATION: {retry_feedback}\nFix every issue above and return valid JSON.\n"
    return prompt


def _validate_draft(draft: ExplanationDraft, ctx: dict[str, Any]) -> tuple[bool, str]:
    headline = " ".join(draft.headline.split())
    reasons = [" ".join(r.split()) for r in draft.reasons]
    rider_message = " ".join(draft.rider_message.split())
    fleet_notice = " ".join(draft.fleet_notice.split())

    if not headline or len(headline) > HEADLINE_MAX:
        return False, f"headline length {len(headline)} exceeds {HEADLINE_MAX}"
    if len(reasons) != 3 or any(not r for r in reasons):
        return False, f"reasons must have exactly 3 non-empty strings (got {len(reasons)})"
    if not rider_message or len(rider_message) > RIDER_MAX:
        return False, f"rider_message length {len(rider_message)} exceeds {RIDER_MAX}"
    if not fleet_notice or len(fleet_notice) > FLEET_MAX:
        return False, f"fleet_notice length {len(fleet_notice)} exceeds {FLEET_MAX}"

    all_text = " ".join([headline, *reasons, rider_message, fleet_notice])
    reasons_text = " ".join(reasons)

    # Rule: Never say "observed"; must say "simulated" in reasons
    if OBSERVED_RE.search(all_text):
        return False, "text contains forbidden word 'observed'; use 'simulated'"
    if not SIMULATED_RE.search(reasons_text):
        return False, "reasons must explicitly contain the word 'simulated'"

    # Rule: Every YYYY-MM-DD in text must be in watch["storm_days"] or top3 risky_detail storm_days
    found_dates = DATE_RE.findall(all_text)
    bad_dates = [d for d in found_dates if d not in ctx["allowed_dates"]]
    if bad_dates:
        return False, f"ungrounded YYYY-MM-DD dates found: {bad_dates}"
    if ctx["allowed_dates"]:
        reason_dates = [d for d in DATE_RE.findall(reasons_text) if d in ctx["allowed_dates"]]
        if not reason_dates:
            return False, "reasons must cite at least one exact YYYY-MM-DD date from storm_days"

    # Rule: Every mm figure must match warning["peak"]["mm"] or forecast_6h_mm
    for m in MM_RE.finditer(all_text):
        val = float(m.group(1))
        if not any(abs(val - allowed) < 0.051 for allowed in ctx["allowed_mm"]):
            return False, f"ungrounded mm figure '{m.group(0)}'; allowed: {ctx['allowed_mm']}"

    # Rule: reasons must include peak mm and n_storm_days when present
    if ctx["peak_mm"] > 0:
        peak_str = f"{ctx['peak_mm']:.1f}"
        peak_int = str(int(ctx["peak_mm"])) if ctx["peak_mm"].is_integer() else peak_str
        if peak_str not in reasons_text and peak_int not in reasons_text:
            return False, f"reasons must mention forecast peak {peak_str}"
    if ctx["watch_n_storms"] > 0 and str(ctx["watch_n_storms"]) not in reasons_text:
        return False, f"reasons must mention n_storm_days ({ctx['watch_n_storms']})"

    # Rule: if reroute with added_min is provided on a reroute action, rider_message mentions minutes
    if ctx["action"] == "reroute" and ctx["reroute"] and ctx["reroute"].get("added_min") is not None:
        if "min" not in rider_message.lower():
            return False, "rider_message must mention added minutes when reroute is provided"

    return True, ""


def _call_carbon(prompt: str) -> ExplanationDraft:
    client = get_client()
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExplanationDraft,
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
        ),
    )
    if not response.text:
        raise ValueError("Empty response text from Gemini 4 Carbon")
    return ExplanationDraft.model_validate_json(response.text)


def _call_carbon_with_timeout(prompt: str, timeout_s: float) -> ExplanationDraft:
    if timeout_s <= 0.1:
        raise TimeoutError("No remaining timeout budget")
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(_call_carbon, prompt)
    try:
        return fut.result(timeout=timeout_s)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


def explain_decision(
    plan: dict,
    sim: dict,
    reroute: dict | None = None,
    timeout_s: float = 8.0,
) -> dict:
    """Explain a ride flood-routing decision with Gemini 4 Carbon, strictly grounded.

    Never raises: falls back to a deterministic template on timeout, API error, or validation failure.
    """
    t0 = time.perf_counter()
    try:
        ctx = _extract_context(plan, sim, reroute)
    except Exception:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {
            "action": "proceed",
            "headline": "Continuing on route: flood assessment unavailable",
            "reasons": [
                "Forecast rainfall summary unavailable.",
                "Historical flood memory unavailable.",
                "Simulated street preview unavailable; using conservative fallback.",
            ],
            "rider_message": "Your trip is continuing smoothly.",
            "fleet_notice": "Fallback notice: unable to parse ride plan context.",
            "cited": {
                "storm_days": [],
                "forecast_mm": 0.0,
                "forecast_t": "09:00",
                "n_storm_days": 0,
                "flooded_p": 0.0,
            },
            "model": "template",
            "latency_ms": elapsed_ms,
        }

    deadline = t0 + max(0.2, _safe_float(timeout_s, 8.0))
    feedback: str | None = None

    for attempt in range(2):
        remaining = deadline - time.perf_counter()
        if remaining <= 0.25 or (attempt == 1 and remaining < 1.2):
            break
        try:
            prompt = _build_prompt(ctx, retry_feedback=feedback)
            draft = _call_carbon_with_timeout(prompt, timeout_s=remaining)
            ok, reason = _validate_draft(draft, ctx)
            if ok:
                headline = " ".join(draft.headline.split())
                reasons = [" ".join(r.split()) for r in draft.reasons]
                rider_message = " ".join(draft.rider_message.split())
                fleet_notice = " ".join(draft.fleet_notice.split())
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                return {
                    "action": ctx["action"],
                    "headline": headline,
                    "reasons": reasons,
                    "rider_message": rider_message,
                    "fleet_notice": fleet_notice,
                    "cited": _build_cited(ctx, [headline, *reasons, rider_message, fleet_notice]),
                    "model": MODEL_NAME,
                    "latency_ms": elapsed_ms,
                }
            feedback = reason
        except Exception:
            break

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return _build_template(ctx, latency_ms=elapsed_ms)


class AutonomousDecisionDraft(BaseModel):
    action: str = Field(description='Autonomous driving decision: strictly "reroute" or "keep_route".')
    confidence: float = Field(description="Calibrated confidence between 0.0 and 1.0.")
    headline: str = Field(description="Short decision headline, strictly <= 90 characters.")
    reasons: list[str] = Field(description="2 to 3 crisp, grounded reasons citing exact numbers from the context.")
    rider_message: str = Field(description="Calm, plain-language rider message, strictly <= 140 characters, no jargon.")


def _fallback_decide(ctx: dict[str, Any], latency_ms: int) -> dict[str, Any]:
    """Deterministic safety-first autonomous fallback if Carbon times out or fails."""
    verdict = ctx.get("verdict") if isinstance(ctx.get("verdict"), dict) else {}
    v_act = str(verdict.get("action") or "").lower()
    lane_p = _safe_float(verdict.get("lane_covered", verdict.get("flooded_p")), 0.0)
    p_tire = _safe_float(verdict.get("p_tire_or_worse"), 0.0)
    has_risky = bool(ctx.get("fastest_route", {}).get("street_flood_blocks_on_it"))
    should_reroute = (
        v_act in ("avoid", "slow")
        or lane_p >= 0.55
        or p_tire >= 0.45
        or (not verdict and has_risky)
    )
    action = "reroute" if should_reroute else "keep_route"
    return {
        "action": action,
        "confidence": round(max(0.75, lane_p) if should_reroute else max(0.75, 1.0 - lane_p), 2),
        "headline": "Autonomously rerouting around flooded blocks ahead" if should_reroute else "Continuing on current route: road clear for travel",
        "reasons": [
            "Autonomous safety policy prioritizes avoiding standing roadway water over minor travel-time savings.",
            f"Simulated/assessed roadway flood signal: action={v_act or 'pre_trip'}, lane_covered={lane_p:.2f}.",
        ],
        "rider_message": (
            "Taking a slightly different route to stay clear of heavy rain and street water ahead."
            if should_reroute
            else "Continuing along your current route; road conditions ahead look clear."
        ),
        "model": "template",
        "latency_ms": latency_ms,
    }


def decide(ctx: dict[str, Any], timeout_s: float = 8.0) -> dict[str, Any]:
    """Hardened autonomous Gemini 4 Carbon decision (drop-in upgrade for pipeline.ride.decide).

    Returns {"action": "reroute"|"keep_route", "confidence": float, "headline": str,
             "reasons": list[str], "rider_message": str, "model": str, "latency_ms": int}.
    Enforces timeout_s and never raises.
    """
    t0 = time.perf_counter()
    safe_ctx = ctx if isinstance(ctx, dict) else {}
    prompt = (
        "You are the autonomous driving policy of a robotaxi in San Francisco. Decide NOW, with no human in the loop, "
        "whether to reroute around the street ahead ('reroute') or keep the current route ('keep_route'). "
        "Rider safety and not getting stranded in water outrank a few minutes of travel time. "
        "Use ONLY the numbers and dates in the JSON below; never invent dates or rainfall figures. "
        "Refer to Genie 4 frames as 'simulated', never 'observed'.\n\n"
        + json.dumps(safe_ctx, indent=1)
    )

    def _call() -> AutonomousDecisionDraft:
        client = get_client()
        resp = client.models.generate_content(
            model=MODEL_NAME,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AutonomousDecisionDraft,
                thinking_config=types.ThinkingConfig(thinking_level="LOW"),
            ),
        )
        return AutonomousDecisionDraft.model_validate_json(resp.text)

    try:
        pool = ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(_call)
        try:
            draft = fut.result(timeout=max(0.5, float(timeout_s)))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        act = draft.action.strip().lower()
        if act not in ("reroute", "keep_route"):
            act = "reroute" if "reroute" in act or "avoid" in act else "keep_route"
        conf = max(0.0, min(1.0, float(draft.confidence)))
        reasons = [" ".join(str(r).split()) for r in (draft.reasons or []) if str(r).strip()][:3]
        if not reasons:
            reasons = ["Autonomous Carbon policy evaluated forecast, street flood history, and simulated conditions."]
        return {
            "action": act,
            "confidence": round(conf, 3),
            "headline": _truncate(draft.headline, HEADLINE_MAX),
            "reasons": reasons,
            "rider_message": _truncate(draft.rider_message, RIDER_MAX),
            "model": MODEL_NAME,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }
    except Exception:
        return _fallback_decide(safe_ctx, latency_ms=int((time.perf_counter() - t0) * 1000))


def _sample_sim_for_cli(plan: dict[str, Any]) -> dict[str, Any]:
    """Load cached Genie sim result if present, else synthesize a realistic verdict for CLI tests."""
    cell = ((plan.get("watch") or {}).get("cell")) or "r50_c66"
    cached = REPO_ROOT / "media" / "sim_cache" / str(cell) / "result.json"
    if cached.exists():
        try:
            return json.loads(cached.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "source": "synthetic",
        "verdict": {
            "flooded_p": 0.9,
            "depth_score": 0.78,
            "depth_label": "ankle",
            "action": "avoid",
            "rubric": {
                "reaches_curb": 0.88,
                "sedan_stall": 0.65,
                "lane_visible": 0.22,
            },
            "trend": "rising",
            "agreement": 0.94,
            "latency_ms": 420,
        },
    }


def main() -> None:
    args = sys.argv[1:]
    plan_path = Path(args[0]) if len(args) >= 1 else REPO_ROOT / "media" / "sim_cache" / "plan_sample.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    sim: dict[str, Any] | None = None
    if len(args) >= 2 and Path(args[1]).exists():
        sim = json.loads(Path(args[1]).read_text(encoding="utf-8"))
    if sim is None:
        sim = _sample_sim_for_cli(plan)

    reroute: dict[str, Any] | None = None
    if len(args) >= 3:
        p3 = Path(args[2])
        if p3.exists():
            reroute = json.loads(p3.read_text(encoding="utf-8"))
        else:
            try:
                reroute = json.loads(args[2])
            except Exception:
                reroute = None

    result = explain_decision(plan, sim, reroute=reroute)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
