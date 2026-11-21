"""Task G1: Access probe for Genie 4, Managed Agents, Omni 1.2 Flash, and Nano Banana 2.1."""
from __future__ import annotations

import asyncio
import time
import warnings
from dataclasses import dataclass
from typing import Any

from google.genai import types

from gem.client import REPO_ROOT, ensure_env, get_beta_client, get_client


@dataclass
class ProbeResult:
    surface: str
    passed: bool
    latency_s: float
    detail: str


def _truncate(text: str, limit: int = 160) -> str:
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3] + "..."


async def _probe_genie4_async(max_seconds: float = 4.5) -> ProbeResult:
    """Open a minimal Genie 4 live session via Interactions API (strictly <= 5s)."""
    t0 = time.perf_counter()
    beta_client = get_beta_client()
    interaction_id: str | None = None
    frame_count = 0
    total_bytes = 0
    mime_types: set[str] = set()
    event_types: list[str] = []

    try:
        interaction = beta_client.interactions.create(
            model="genie-4",
            background=True,
        )
        interaction_id = getattr(interaction, "id", None)
        if not interaction_id:
            return ProbeResult(
                surface="genie-4",
                passed=False,
                latency_s=time.perf_counter() - t0,
                detail=f"No interaction id returned: {_truncate(str(interaction), 120)}",
            )

        async with asyncio.timeout(max_seconds):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                conn_ctx = beta_client.aio.interactions.connect(interaction_id)
            async with conn_ctx as conn:
                try:
                    await conn.send(
                        {
                            "event_type": "world_setup",
                            "world_prompt": (
                                "A flooded San Francisco street in heavy rain, "
                                "ankle-deep standing water on asphalt reflecting streetlights."
                            ),
                        }
                    )
                    async for event in conn.receive():
                        etype = getattr(event, "event_type", type(event).__name__)
                        event_types.append(str(etype))
                        delta = getattr(event, "delta", None)
                        if delta is not None:
                            data = getattr(delta, "data", None)
                            if data:
                                frame_count += 1
                                total_bytes += len(data)
                                mt = getattr(delta, "mime_type", None) or getattr(delta, "type", None)
                                if mt:
                                    mime_types.add(str(mt))
                        if frame_count >= 1:
                            break
                        if str(etype) in ("error", "interaction.completed", "interaction.cancelled"):
                            break
                finally:
                    try:
                        await conn.cancel()
                    except Exception:
                        pass
    except TimeoutError:
        elapsed = time.perf_counter() - t0
        if frame_count >= 1:
            return ProbeResult(
                surface="genie-4",
                passed=True,
                latency_s=elapsed,
                detail=f"frames={frame_count}, bytes={total_bytes}, mimes={sorted(mime_types)}",
            )
        return ProbeResult(
            surface="genie-4",
            passed=False,
            latency_s=elapsed,
            detail=f"Timeout after {max_seconds:.1f}s with 0 frames (events={event_types[:6]})",
        )
    except Exception as exc:
        return ProbeResult(
            surface="genie-4",
            passed=False,
            latency_s=time.perf_counter() - t0,
            detail=f"{type(exc).__name__}: {_truncate(str(exc))}",
        )
    finally:
        if interaction_id:
            try:
                beta_client.interactions.cancel(interaction_id)
            except Exception:
                pass

    elapsed = time.perf_counter() - t0
    if frame_count >= 1:
        return ProbeResult(
            surface="genie-4",
            passed=True,
            latency_s=elapsed,
            detail=f"frames={frame_count}, bytes={total_bytes}, mimes={sorted(mime_types)}",
        )
    return ProbeResult(
        surface="genie-4",
        passed=False,
        latency_s=elapsed,
        detail=f"Closed with 0 frames (events={event_types[:8]})",
    )


def probe_genie4() -> ProbeResult:
    return asyncio.run(_probe_genie4_async(max_seconds=4.5))


def probe_managed_agents() -> ProbeResult:
    """Minimal call to Managed Agents API via beta_client.interactions.create."""
    t0 = time.perf_counter()
    beta_client = get_beta_client()
    try:
        interaction = beta_client.interactions.create(
            agent="antigravity-preview-09-2026",
            environment="remote",
            agent_config={
                "type": "antigravity",
                "model": "gemini-4-hydrogen",
                "max_total_tokens": 5000,
            },
            input="Print 2+2 using python and return the number.",
            timeout=60.0,
        )
        elapsed = time.perf_counter() - t0
        status = getattr(interaction, "status", None)
        steps = getattr(interaction, "steps", None) or []
        out_text = getattr(interaction, "output_text", None) or ""
        step_types = [getattr(s, "type", type(s).__name__) for s in steps]
        passed = status in ("completed", "incomplete") and (bool(out_text) or len(steps) > 0)
        return ProbeResult(
            surface="managed-agents",
            passed=passed,
            latency_s=elapsed,
            detail=f"status={status}, steps={len(steps)} {step_types[:4]}, text={_truncate(out_text or '(none)', 70)}",
        )
    except Exception as exc:
        return ProbeResult(
            surface="managed-agents",
            passed=False,
            latency_s=time.perf_counter() - t0,
            detail=f"{type(exc).__name__}: {_truncate(str(exc))}",
        )


def _summarize_response_parts(resp: Any) -> tuple[int, list[str], int, str]:
    media_count = 0
    mimes: list[str] = []
    total_bytes = 0
    texts: list[str] = []
    candidates = getattr(resp, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            file_data = getattr(part, "file_data", None)
            if inline and getattr(inline, "data", None):
                media_count += 1
                total_bytes += len(inline.data)
                if inline.mime_type:
                    mimes.append(inline.mime_type)
            elif file_data and getattr(file_data, "file_uri", None):
                media_count += 1
                mimes.append(getattr(file_data, "mime_type", "file_uri") or "file_uri")
            elif getattr(part, "text", None):
                texts.append(part.text)
    return media_count, sorted(set(mimes)), total_bytes, " ".join(texts).strip()


def probe_omni() -> ProbeResult:
    """Minimal call to gemini-omni-1.2-flash via Interactions API for a short video clip."""
    t0 = time.perf_counter()
    beta_client = get_beta_client()
    try:
        interaction = beta_client.interactions.create(
            model="gemini-omni-1.2-flash",
            input="A 2-second clip of a flooded San Francisco street in heavy rain.",
            response_modalities=["video"],
            generation_config={"video_config": {"task": "text_to_video"}},
            timeout=90.0,
        )
        elapsed = time.perf_counter() - t0
        status = getattr(interaction, "status", None)
        videos = getattr(interaction, "output_video", None) or []
        if not isinstance(videos, list):
            videos = [videos]
        media_count = 0
        mimes: list[str] = []
        total_bytes = 0
        uris: list[str] = []
        for item in videos:
            data = getattr(item, "data", None)
            uri = getattr(item, "uri", None)
            mime = getattr(item, "mime_type", None) or getattr(item, "type", None)
            if data or uri:
                media_count += 1
                if data:
                    total_bytes += len(data)
                if uri:
                    uris.append(str(uri))
                if mime:
                    mimes.append(str(mime))
        if media_count == 0:
            for step in getattr(interaction, "steps", None) or []:
                content = getattr(step, "content", None) or []
                if not isinstance(content, list):
                    content = [content]
                for part in content:
                    data = getattr(part, "data", None)
                    uri = getattr(part, "uri", None)
                    mime = getattr(part, "mime_type", None) or getattr(part, "type", None)
                    if data or uri:
                        media_count += 1
                        if data:
                            total_bytes += len(data)
                        if uri:
                            uris.append(str(uri))
                        if mime:
                            mimes.append(str(mime))
        if media_count >= 1:
            extra = f"uri={_truncate(uris[0], 50)}" if uris and not total_bytes else f"bytes={total_bytes}"
            return ProbeResult(
                surface="gemini-omni-1.2-flash",
                passed=True,
                latency_s=elapsed,
                detail=f"status={status}, videos={media_count}, {extra}, mimes={sorted(set(mimes))}",
            )
        return ProbeResult(
            surface="gemini-omni-1.2-flash",
            passed=False,
            latency_s=elapsed,
            detail=f"status={status}, no video outputs (steps={len(getattr(interaction, 'steps', None) or [])})",
        )
    except Exception as exc:
        return ProbeResult(
            surface="gemini-omni-1.2-flash",
            passed=False,
            latency_s=time.perf_counter() - t0,
            detail=f"{type(exc).__name__}: {_truncate(str(exc))}",
        )


def probe_nano_banana() -> ProbeResult:
    """Minimal image edit call to gemini-nano-banana-2.1."""
    t0 = time.perf_counter()
    client = get_client()
    sample_img = REPO_ROOT / "frame_cd229284.jpg"
    try:
        if sample_img.exists():
            img_part = types.Part.from_bytes(
                data=sample_img.read_bytes(),
                mime_type="image/jpeg",
            )
            contents: Any = [
                img_part,
                "Edit this street photo to show ankle-deep rainwater flooding the roadway during a storm.",
            ]
        else:
            contents = "A photorealistic photo of a flooded San Francisco street in heavy rain."

        resp = client.models.generate_content(
            model="gemini-nano-banana-2.1",
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )
        elapsed = time.perf_counter() - t0
        media_count, mimes, total_bytes, text = _summarize_response_parts(resp)
        if media_count >= 1:
            return ProbeResult(
                surface="gemini-nano-banana-2.1",
                passed=True,
                latency_s=elapsed,
                detail=f"images={media_count}, bytes={total_bytes}, mimes={mimes}",
            )
        return ProbeResult(
            surface="gemini-nano-banana-2.1",
            passed=False,
            latency_s=elapsed,
            detail=f"No image returned (text={_truncate(text, 100)})",
        )
    except Exception as exc:
        return ProbeResult(
            surface="gemini-nano-banana-2.1",
            passed=False,
            latency_s=time.perf_counter() - t0,
            detail=f"{type(exc).__name__}: {_truncate(str(exc))}",
        )


def print_table(results: list[ProbeResult]) -> None:
    w_surf = max(len("Surface"), *(len(r.surface) for r in results))
    w_stat = 6
    w_lat = 9
    header = f"{'Surface':<{w_surf}} | {'Status':<{w_stat}} | {'Latency':>{w_lat}} | Details"
    sep = f"{'-' * w_surf}-+-{'-' * w_stat}-+-{'-' * w_lat}-+-{'-' * 40}"
    print(header)
    print(sep)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"{r.surface:<{w_surf}} | {status:<{w_stat}} | {r.latency_s:>{w_lat - 1}.2f}s | {r.detail}")


def main() -> None:
    ensure_env()
    probes = [
        probe_genie4,
        probe_managed_agents,
        probe_omni,
        probe_nano_banana,
    ]
    results = [fn() for fn in probes]
    print_table(results)


if __name__ == "__main__":
    main()
