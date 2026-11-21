"""Task G1: Access probe for Genie 4, Managed Agents, Omni 1.2 Flash, and Nano Banana 2.1."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from pathlib import Path
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
    """Open a minimal Genie 4 live session, wait for first video/image frame (strictly <= 5s)."""
    t0 = time.perf_counter()
    client = get_beta_client()
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.VIDEO],
    )
    frame_count = 0
    total_bytes = 0
    mime_types: set[str] = set()
    text_snippets: list[str] = []

    try:
        async with asyncio.timeout(max_seconds):
            async with client.aio.live.connect(model="genie-4", config=config) as session:
                await session.send_client_content(
                    turns=types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                text=(
                                    "A flooded San Francisco street in heavy rain, "
                                    "ankle-deep standing water on asphalt reflecting streetlights."
                                )
                            )
                        ],
                    ),
                    turn_complete=True,
                )
                async for msg in session.receive():
                    sc = getattr(msg, "server_content", None)
                    mt = getattr(sc, "model_turn", None) if sc else None
                    if mt and getattr(mt, "parts", None):
                        for part in mt.parts:
                            inline = getattr(part, "inline_data", None)
                            if inline and getattr(inline, "data", None):
                                frame_count += 1
                                total_bytes += len(inline.data)
                                if inline.mime_type:
                                    mime_types.add(inline.mime_type)
                            elif getattr(part, "text", None):
                                text_snippets.append(part.text)
                    # Stop immediately once we receive at least one media frame to keep cost minimal.
                    if frame_count >= 1:
                        break
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
            detail=f"Timeout after {max_seconds:.1f}s with 0 frames (text={_truncate(' '.join(text_snippets), 80)})",
        )
    except Exception as exc:
        return ProbeResult(
            surface="genie-4",
            passed=False,
            latency_s=time.perf_counter() - t0,
            detail=f"{type(exc).__name__}: {_truncate(str(exc))}",
        )

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
        detail=f"Session closed with 0 media frames (text={_truncate(' '.join(text_snippets), 80)})",
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
        outputs = getattr(interaction, "outputs", None) or []
        out_text = ""
        for item in outputs:
            txt = getattr(item, "text", None)
            if txt:
                out_text += txt + " "
        if not out_text:
            out_text = str(interaction)[:120]
        return ProbeResult(
            surface="managed-agents",
            passed=True,
            latency_s=elapsed,
            detail=f"status={status}, out={_truncate(out_text, 100)}",
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
    """Minimal call to gemini-omni-1.2-flash for a short video clip."""
    t0 = time.perf_counter()
    client = get_beta_client()
    try:
        resp = client.models.generate_content(
            model="gemini-omni-1.2-flash",
            contents="A 2-second clip of a flooded San Francisco street in heavy rain.",
            config=types.GenerateContentConfig(
                response_modalities=["VIDEO"],
            ),
        )
        elapsed = time.perf_counter() - t0
        media_count, mimes, total_bytes, text = _summarize_response_parts(resp)
        if media_count >= 1:
            return ProbeResult(
                surface="gemini-omni-1.2-flash",
                passed=True,
                latency_s=elapsed,
                detail=f"parts={media_count}, bytes={total_bytes}, mimes={mimes}",
            )
        return ProbeResult(
            surface="gemini-omni-1.2-flash",
            passed=False,
            latency_s=elapsed,
            detail=f"No media parts returned (text={_truncate(text, 100)})",
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
