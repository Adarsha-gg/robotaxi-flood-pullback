"""Wildcard #6: Gemini 3.8 Flash TTS Audio Dispatch Alerts.

Synthesizes calm in-cabin rider reroute notifications and crisp fleet dispatch
alerts into playable WAV files using Gemini 3.8 Flash TTS (`v1beta`).
Does not import from `pipeline/`. Never raises to callers.
"""
from __future__ import annotations

import base64
import io
import json
import re
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from gem.client import REPO_ROOT, ensure_env

PRIMARY_MODEL = "gemini-3.8-flash-lite-tts"
FALLBACK_MODEL = "gemini-3.8-flash-tts"
DEFAULT_VOICE = "Kore"
RIDER_VOICE = "Kore"
FLEET_VOICE = "Charon"
DEFAULT_SAMPLE_RATE = 24000
DEFAULT_CHANNELS = 1
DEFAULT_SAMPLE_WIDTH = 2  # 16-bit signed PCM

TRACE_PATH = REPO_ROOT / "media" / "traces" / "ride_2026-11-18.json"
DEFAULT_RIDER_OUT = "media/audio/rider_reroute.wav"
DEFAULT_FLEET_OUT = "media/audio/fleet_alert.wav"

FALLBACK_RIDER_TEXT = (
    "Heavy rain is expected ahead, so we're taking a slightly different route "
    "around 4th and King Street to keep your ride smooth and safe."
)
FALLBACK_FLEET_TEXT = (
    "Avoid 4th Street and King Street and nearby SOMA and Laguna flood cells "
    "from 9:00 to 11:00; simulated ankle-deep flooding with 8.6 millimeters per hour peak rain."
)

_RATE_RE = re.compile(r"rate=(\d+)", re.IGNORECASE)
_AUTH_ERROR_MARKERS = (
    "api_key_invalid",
    "api key not valid",
    "invalid api key",
    "unauthenticated",
    "permission_denied",
    "401",
    "403",
)


def _resolve_out_path(out_path: str | Path) -> Path:
    p = Path(out_path)
    if p.is_absolute():
        return p
    return REPO_ROOT / p


def _extract_audio_bytes(response: Any) -> tuple[bytes, str]:
    """Pull raw audio bytes and MIME type from a GenerateContentResponse."""
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline is None:
                continue
            data = getattr(inline, "data", None)
            mime = str(getattr(inline, "mime_type", "") or "")
            if isinstance(data, str):
                data = base64.b64decode(data)
            if isinstance(data, (bytes, bytearray)) and len(data) > 0:
                return bytes(data), mime
    raise ValueError("TTS response contained no audio inline_data")


def _ensure_wav_bytes(audio_bytes: bytes, mime_type: str = "") -> bytes:
    """Return valid RIFF/WAVE bytes; wrap raw 16-bit mono PCM if needed."""
    if len(audio_bytes) >= 12 and audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
        wav_bytes = audio_bytes
    else:
        rate = DEFAULT_SAMPLE_RATE
        m = _RATE_RE.search(mime_type or "")
        if m:
            try:
                parsed = int(m.group(1))
                if 8000 <= parsed <= 96000:
                    rate = parsed
            except ValueError:
                pass
        # Pad odd byte length for 16-bit PCM safety.
        pcm = audio_bytes if len(audio_bytes) % 2 == 0 else audio_bytes + b"\x00"
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(DEFAULT_CHANNELS)
            wf.setsampwidth(DEFAULT_SAMPLE_WIDTH)
            wf.setframerate(rate)
            wf.writeframes(pcm)
        wav_bytes = buf.getvalue()

    # Validate playable WAV header + non-empty frames.
    if len(wav_bytes) < 44 or wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        raise ValueError("Invalid RIFF/WAVE header")
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        if wf.getnframes() <= 0 or wf.getframerate() <= 0:
            raise ValueError("WAV audio contains zero frames")
    return wav_bytes


def inspect_wav(path: str | Path) -> dict[str, Any]:
    """Inspect a WAV file on disk and return header + duration metadata."""
    p = _resolve_out_path(path)
    raw = p.read_bytes()
    riff_ok = len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"
    with wave.open(io.BytesIO(raw), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
    duration_s = round(n_frames / float(sample_rate), 2) if sample_rate > 0 else 0.0
    return {
        "path": str(p),
        "bytes": len(raw),
        "riff_wave": riff_ok,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "sample_rate_hz": sample_rate,
        "n_frames": n_frames,
        "duration_s": duration_s,
    }


def _call_tts(model: str, prompt: str, voice: str, timeout_ms: int) -> bytes:
    """Single TTS call on v1beta returning validated RIFF/WAVE bytes."""
    ensure_env()
    # Gemini API rejects server-side deadlines below 10s; enforce shorter wall budgets locally.
    server_timeout_ms = max(10_000, int(timeout_ms))
    client = genai.Client(
        http_options=types.HttpOptions(api_version="v1beta", timeout=server_timeout_ms)
    )
    res = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        ),
    )
    raw_audio, mime = _extract_audio_bytes(res)
    return _ensure_wav_bytes(raw_audio, mime)


def _is_auth_error(exc: Exception) -> bool:
    msg = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in msg for marker in _AUTH_ERROR_MARKERS)


def synthesize(
    text: str,
    out_path: str,
    voice: str = DEFAULT_VOICE,
    timeout_s: float = 12.0,
) -> dict[str, Any]:
    """Synthesize speech to a playable WAV file using Gemini 3.8 Flash TTS.

    Primary model: `gemini-3.8-flash-lite-tts`; fallback: `gemini-3.8-flash-tts`.
    Returns:
      {"ok": bool, "path": str, "bytes": int, "model": str, "latency_ms": int, "error": str | None}
    Never raises.
    """
    t0 = time.perf_counter()
    dest = _resolve_out_path(out_path) if out_path else _resolve_out_path(DEFAULT_RIDER_OUT)
    last_model = PRIMARY_MODEL

    try:
        clean_text = str(text or "").strip()
        if not clean_text:
            return {
                "ok": False,
                "path": str(dest),
                "bytes": 0,
                "model": PRIMARY_MODEL,
                "latency_ms": int(round((time.perf_counter() - t0) * 1000)),
                "error": "ValueError: text must be non-empty",
            }

        voice_name = str(voice or DEFAULT_VOICE).strip() or DEFAULT_VOICE
        budget_s = max(1.0, float(timeout_s)) if isinstance(timeout_s, (int, float)) else 12.0
        deadline = t0 + budget_s

        errors: list[str] = []
        models = (PRIMARY_MODEL, FALLBACK_MODEL)

        for idx, model in enumerate(models):
            remaining_s = deadline - time.perf_counter()
            if remaining_s <= 0.25:
                errors.append(f"{model}: TimeoutError: synthesis timeout budget exceeded")
                break

            last_model = model
            # Allocate most of the budget to primary, leaving headroom for fallback if needed.
            if idx == 0 and len(models) > 1:
                call_budget_s = min(remaining_s, max(2.0, budget_s * 0.65))
            else:
                call_budget_s = remaining_s

            pool = ThreadPoolExecutor(max_workers=1)
            fut = pool.submit(_call_tts, model, clean_text, voice_name, int(call_budget_s * 1000))
            try:
                wav_bytes = fut.result(timeout=call_budget_s)
            except FuturesTimeoutError:
                fut.cancel()
                pool.shutdown(wait=False, cancel_futures=True)
                errors.append(f"{model}: TimeoutError: timed out after {call_budget_s:.1f}s")
                continue
            except Exception as exc:
                pool.shutdown(wait=False, cancel_futures=True)
                errors.append(f"{model}: {type(exc).__name__}: {exc}")
                if _is_auth_error(exc):
                    break
                continue
            else:
                pool.shutdown(wait=False)

            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = dest.with_suffix(dest.suffix + ".tmp")
            tmp_path.write_bytes(wav_bytes)
            tmp_path.replace(dest)

            latency_ms = int(round((time.perf_counter() - t0) * 1000))
            return {
                "ok": True,
                "path": str(dest),
                "bytes": len(wav_bytes),
                "model": model,
                "latency_ms": latency_ms,
                "error": None,
            }

        latency_ms = int(round((time.perf_counter() - t0) * 1000))
        return {
            "ok": False,
            "path": str(dest),
            "bytes": 0,
            "model": last_model,
            "latency_ms": latency_ms,
            "error": " | ".join(errors) if errors else "TTS synthesis failed",
        }
    except Exception as exc:
        latency_ms = int(round((time.perf_counter() - t0) * 1000))
        return {
            "ok": False,
            "path": str(dest),
            "bytes": 0,
            "model": last_model,
            "latency_ms": latency_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }


def speak_rider_alert(
    text: str,
    out_path: str = DEFAULT_RIDER_OUT,
) -> dict[str, Any]:
    """Synthesize a calm, reassuring in-cabin rider reroute announcement. Never raises."""
    clean = str(text or "").strip()
    return synthesize(clean, out_path=out_path, voice=RIDER_VOICE)


def speak_fleet_dispatch(
    text: str,
    out_path: str = DEFAULT_FLEET_OUT,
) -> dict[str, Any]:
    """Synthesize a crisp, clear fleet operations dispatch notice. Never raises."""
    clean = str(text or "").strip()
    return synthesize(clean, out_path=out_path, voice=FLEET_VOICE)


def _load_trace_messages() -> tuple[str, str]:
    """Read real Carbon rider_message and fleet_notice from the Nov 18 ride trace."""
    try:
        if TRACE_PATH.is_file():
            data = json.loads(TRACE_PATH.read_text(encoding="utf-8"))
            decision = data.get("decision") or {}
            rider = str(decision.get("rider_message") or "").strip()
            fleet = str(decision.get("fleet_notice") or "").strip()
            if rider and fleet:
                return rider, fleet
    except Exception:
        pass
    return FALLBACK_RIDER_TEXT, FALLBACK_FLEET_TEXT


def main(argv: list[str]) -> int:
    rider_text, fleet_text = _load_trace_messages()
    rider_res = speak_rider_alert(rider_text, out_path=DEFAULT_RIDER_OUT)
    fleet_res = speak_fleet_dispatch(fleet_text, out_path=DEFAULT_FLEET_OUT)

    report: dict[str, Any] = {
        "source_trace": str(TRACE_PATH),
        "rider_text": rider_text,
        "fleet_text": fleet_text,
        "rider": rider_res,
        "fleet": fleet_res,
    }

    if rider_res.get("ok"):
        report["rider_wav"] = inspect_wav(rider_res["path"])
    if fleet_res.get("ok"):
        report["fleet_wav"] = inspect_wav(fleet_res["path"])

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
