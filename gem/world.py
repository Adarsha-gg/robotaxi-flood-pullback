"""G5: Genie 4 flood worlds from real street photos.

GenieSession streams a live, steerable Genie 4 world (720p JPEG frames + 48 kHz
stereo PCM audio) that starts from a real photo. render_flood() records a short
clip to MP4 (contract function; also the pre-rendered backup for the demo).

Every output is an illustration generated from a real photo, not a measurement.
"""
import asyncio
import base64
import os
import subprocess
import threading
import time

from gem.client import get_beta_client

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RENDERS = os.path.join(ROOT, "media", "renders")
KEYS = {"key_w", "key_a", "key_s", "key_d", "arrow_up", "arrow_down", "arrow_left", "arrow_right", "space", "key_e"}

DEFAULT_PROMPT = ("Street-level view from a driverless robotaxi in San Francisco during the 2026-11-18 storm. "
                  "Heavy rain, runoff flooding the roadway and rising toward the curb. Keep the real street from the "
                  "reference photo. The car drives slowly and carefully.")


class GenieSession:
    """One live Genie 4 world. Thread-safe: call start(), send_key(), stop() from any thread."""

    def __init__(self, image: bytes, prompt: str = DEFAULT_PROMPT, max_seconds: float = 90.0, mime="image/jpeg"):
        self.image, self.prompt, self.mime, self.max_seconds = image, prompt, mime, max_seconds
        self.frame, self.frame_no, self.status, self.error = None, 0, "starting", None
        self.started_at = self.first_frame_at = None
        self.frames, self.audio = [], bytearray()   # kept for the MP4 save
        self._loop = None
        self._queue = None
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self.interaction_id = None

    # ---- public ----
    def start(self):
        threading.Thread(target=lambda: asyncio.run(self._run()), daemon=True).start()
        return self

    def send_key(self, action: str, key: str):
        if action not in ("key_down", "key_up", "key_click") or key not in KEYS:
            raise ValueError("bad action/key")
        if self._loop and self._queue:
            self._loop.call_soon_threadsafe(self._queue.put_nowait,
                                            {"event_type": "user_action", "action": action, "input": key})

    def stop(self):
        self._stop.set()

    def wait_frame(self, last_no: int, timeout: float = 2.0):
        with self._cond:
            self._cond.wait_for(lambda: self.frame_no != last_no or self.status in ("stopped", "error"), timeout)
            return self.frame, self.frame_no

    def info(self):
        return {"status": self.status, "frames": self.frame_no, "error": self.error,
                "seconds": round(time.time() - self.started_at, 1) if self.started_at else 0,
                "first_frame_s": round(self.first_frame_at - self.started_at, 1) if self.first_frame_at else None,
                "max_seconds": self.max_seconds}

    def save_mp4(self, path: str) -> str:
        """Write the frames and audio streamed so far to an H.264/AAC MP4."""
        if not self.frames:
            raise RuntimeError("no frames")
        tmp = path + ".parts"
        os.makedirs(tmp, exist_ok=True)
        for i, f in enumerate(self.frames):
            with open(os.path.join(tmp, f"f{i:05d}.jpg"), "wb") as fh:
                fh.write(f)
        with open(os.path.join(tmp, "audio.raw"), "wb") as fh:
            fh.write(bytes(self.audio))
        cmd = ["ffmpeg", "-loglevel", "error", "-y", "-framerate", "24", "-i", os.path.join(tmp, "f%05d.jpg")]
        if self.audio:
            cmd += ["-f", "s16le", "-ar", "48000", "-ac", "2", "-i", os.path.join(tmp, "audio.raw"), "-c:a", "aac", "-shortest"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", path]
        subprocess.run(cmd, check=True)
        subprocess.run(["rm", "-rf", tmp])
        return path

    # ---- internals ----
    async def _run(self):
        self._loop, self._queue = asyncio.get_running_loop(), asyncio.Queue()
        client = get_beta_client()
        self.started_at = time.time()
        try:
            it = client.interactions.create(model="genie-4", background=True)
            self.interaction_id = it.id
            async with client.aio.interactions.connect(it.id) as conn:
                await conn.send({"event_type": "world_setup", "world_prompt": self.prompt,
                                 "reference_image": {"data": base64.b64encode(self.image).decode(), "mime_type": self.mime}})
                self.status = "warming"
                sender = asyncio.create_task(self._send_loop(conn))
                try:
                    async for ev in conn.receive():
                        if self._stop.is_set() or time.time() - self.started_at > self.max_seconds:
                            break
                        et = str(getattr(ev, "event_type", ""))
                        if et == "error" or "completed" in et or "cancel" in et:
                            self.error = None if "completed" in et else str(ev)[:300]
                            break
                        d = getattr(ev, "delta", None)
                        data = getattr(d, "data", None) if d is not None else None
                        if not data:
                            continue
                        raw = base64.b64decode(data) if isinstance(data, str) else data
                        if raw[:2] == b"\xff\xd8":  # JPEG frame
                            self.frames.append(raw)
                            with self._cond:
                                self.frame, self.frame_no = raw, self.frame_no + 1
                                self.first_frame_at = self.first_frame_at or time.time()
                                self.status = "live"
                                self._cond.notify_all()
                        else:                        # 48 kHz s16le stereo PCM
                            self.audio += raw
                finally:
                    sender.cancel()
                    try:
                        await conn.cancel()
                    except Exception:
                        pass
        except Exception as e:
            self.error, self.status = f"{type(e).__name__}: {str(e)[:300]}", "error"
        finally:
            if self.interaction_id:
                try:
                    client.interactions.cancel(self.interaction_id)
                except Exception:
                    pass
            if self.status != "error":
                self.status = "stopped"
            with self._cond:
                self._cond.notify_all()

    async def _send_loop(self, conn):
        while True:
            msg = await self._queue.get()
            await conn.send(msg)


def render_flood(lat: float, lon: float, jpeg: bytes | None, seconds: float = 8.0,
                 prompt: str = DEFAULT_PROMPT, drive: bool = True) -> dict:
    """Contract: record a short Genie 4 clip from a real street photo. Returns {"kind","path"}."""
    if jpeg is None:
        raise ValueError("render_flood needs a real street photo (jpeg bytes)")
    s = GenieSession(jpeg, prompt, max_seconds=seconds + 15).start()
    t0 = time.time()
    while s.status in ("starting", "warming") and time.time() - t0 < 20:
        time.sleep(0.2)
    if drive:
        s.send_key("key_down", "key_w")
    while s.status == "live" and s.first_frame_at and time.time() - s.first_frame_at < seconds:
        time.sleep(0.2)
    s.stop()
    time.sleep(0.5)
    if s.error and not s.frames:
        raise RuntimeError(s.error)
    os.makedirs(RENDERS, exist_ok=True)
    path = os.path.join(RENDERS, f"genie_{lat:.4f}_{lon:.4f}_{int(time.time())}.mp4")
    s.save_mp4(path)
    return {"kind": "genie", "path": os.path.relpath(path, ROOT), "frames": len(s.frames)}


if __name__ == "__main__":
    import sys
    img = open(sys.argv[1], "rb").read()
    print(render_flood(float(sys.argv[2]), float(sys.argv[3]), img, seconds=float(sys.argv[4]) if len(sys.argv) > 4 else 8))
