"""Samples on the CPU: a second sa3-server for the editor's Samples panel that runs next to whatever engine holds
the GPU (ACE-Step, YuE2 or Stable Audio itself), so making a kick does not unload the model in use.

It is not part of the orchestrator's exclusive switching: it starts on the panel's first request, stops after a
while without use (its 3 GB of RAM come back) and with the backend. The GPU is hidden from it
(CUDA_VISIBLE_DEVICES=""), and sa3-server turns Flash Attention off there. Measured on a 16-core Ryzen 9 9950X with
small-sfx and 8 steps: a 2 s one-shot in about 13 s, 10 s in 43 s, 30 s in 81 s (all threads); with 8 threads
18 s and 56 s.

Settings (saved in the database, key "sfx_cpu"): enabled; route "auto" (the GPU when Stable Audio runs there,
otherwise the CPU) or "cpu" (always the CPU); threads (0 = PyTorch's default, one per physical core); the model
it warms up; minutes without use before it stops (0 = never).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from typing import Literal, Optional

from . import db, features
from .config import FFMPEG_BIN_DIR, IS_WINDOWS, STABLE_AUDIO_CPU_PORT, STABLE_AUDIO_DIR, ProcessSpec
from .orchestrator.process import ManagedProcess, StartCancelled

log = logging.getLogger("sfx_cpu")

SETTINGS_KEY = "sfx_cpu"
CPU_MODELS = ("small-sfx", "small-music", "small-sfx-base", "small-music-base")
BASE_URL = f"http://127.0.0.1:{STABLE_AUDIO_CPU_PORT}"
IDLE_CHECK_SECONDS = 30.0

Status = Literal["stopped", "starting", "running", "error"]


@dataclass
class Settings:
    enabled: bool = False
    route: Literal["auto", "cpu"] = "auto"
    threads: int = 0
    model: str = "small-sfx"
    idle_minutes: int = 15


def load_settings() -> Settings:
    try:
        raw = json.loads(db.get_setting(SETTINGS_KEY, "") or "{}")
    except ValueError:
        raw = {}
    s = Settings()
    if isinstance(raw, dict):
        s.enabled = bool(raw.get("enabled", s.enabled))
        s.route = "cpu" if raw.get("route") == "cpu" else "auto"
        s.threads = max(0, min(int(raw.get("threads") or 0), os.cpu_count() or 64))
        s.model = raw.get("model") if raw.get("model") in CPU_MODELS else s.model
        s.idle_minutes = max(0, min(int(raw.get("idle_minutes", s.idle_minutes) or 0), 24 * 60))
    return s


def save_settings(s: Settings) -> Settings:
    db.set_setting(SETTINGS_KEY, json.dumps(asdict(s)))
    return load_settings()


class CpuSampler:
    def __init__(self) -> None:
        self.status: Status = "stopped"
        self.error: Optional[str] = None
        self._proc: Optional[ManagedProcess] = None
        self._lock = asyncio.Lock()
        self._cancel: Optional[asyncio.Event] = None
        self._last_used = time.monotonic()
        self._watcher: Optional[asyncio.Task] = None
        # what the running process was started with: a change of threads or model restarts it
        self._started_with: Optional[tuple[int, str]] = None

    # ---- state ----
    def touch(self) -> None:
        self._last_used = time.monotonic()

    def pids(self) -> list[int]:
        return [self._proc.pid] if self._proc and self._proc.pid else []

    def snapshot(self) -> dict:
        s = load_settings()
        installed = set(features.stable_audio_models())
        if self.status == "running" and self._proc is not None and not self._proc.is_running:
            self.status, self.error = "error", self._proc.exit_summary()
        return {
            "settings": asdict(s),
            "status": self.status,
            "error": self.error,
            "available": features.has_stable_audio_env() and any(m in installed for m in CPU_MODELS),
            "models": [m for m in CPU_MODELS if m in installed],
            "cpu_count": os.cpu_count() or 0,
            # applied on the next start, so the panel can say a restart is pending
            "restart_pending": self.status == "running" and self._started_with != (s.threads, s.model),
        }

    # ---- lifecycle ----
    def _spec(self, s: Settings) -> ProcessSpec:
        python = STABLE_AUDIO_DIR / ".venv" / ("Scripts" if IS_WINDOWS else "bin") / ("python.exe" if IS_WINDOWS else "python")
        return ProcessSpec(
            name="stable_audio_cpu",
            cwd=STABLE_AUDIO_DIR,
            cmd=[
                str(python), "-m", "sa3_server",
                "--host", "127.0.0.1", "--port", str(STABLE_AUDIO_CPU_PORT),
                "--device", "cpu", "--threads", str(s.threads),
                "--preload", s.model, "--max-resident", "1",
                "--out-dir", "output-cpu",
            ],
            extra_path_dirs=[FFMPEG_BIN_DIR],
            env={"PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "CUDA_VISIBLE_DEVICES": ""},
            health_url=f"{BASE_URL}/health",
            startup_timeout=180.0,
        )

    async def ensure_running(self) -> None:
        """Starts the server if it is not up (or restarts it when its threads or model changed)."""
        s = load_settings()
        if not s.enabled:
            raise PermissionError("samples on the CPU are switched off")
        if not features.has_stable_audio_env():
            raise FileNotFoundError("Stable Audio 3 is not installed")
        if s.model not in features.stable_audio_models():
            raise FileNotFoundError(f"the '{s.model}' checkpoint is not downloaded")
        self.touch()
        async with self._lock:
            if self._proc is not None and self._proc.is_running and self._started_with == (s.threads, s.model):
                self.status = "running"
                return
            await self._stop_locked()
            self.status, self.error = "starting", None
            self._cancel = asyncio.Event()
            proc = ManagedProcess(self._spec(s))
            try:
                proc.start()
                self._proc = proc
                await proc.wait_healthy(self._cancel)
            except StartCancelled:
                await proc.stop()
                self._proc, self.status = None, "stopped"
                raise
            except Exception as exc:  # noqa: BLE001 - surface any start failure to the panel
                log.exception("the CPU sample server did not start")
                await proc.stop()
                self._proc, self.status, self.error = None, "error", str(exc)
                raise
            finally:
                self._cancel = None
            self._started_with = (s.threads, s.model)
            self.status = "running"
            self.touch()
        self._ensure_watcher()

    async def stop(self) -> None:
        if self._cancel is not None:
            self._cancel.set()
        async with self._lock:
            await self._stop_locked()

    async def _stop_locked(self) -> None:
        proc, self._proc = self._proc, None
        self._started_with = None
        if proc is not None:
            await proc.stop()
        if self.status != "error":
            self.status = "stopped"

    async def shutdown(self) -> None:
        if self._watcher is not None:
            self._watcher.cancel()
            self._watcher = None
        await self.stop()

    def _ensure_watcher(self) -> None:
        if self._watcher is None or self._watcher.done():
            self._watcher = asyncio.create_task(self._watch_idle())

    async def _watch_idle(self) -> None:
        while self._proc is not None:
            await asyncio.sleep(IDLE_CHECK_SECONDS)
            minutes = load_settings().idle_minutes
            if minutes and self.status == "running" and time.monotonic() - self._last_used > minutes * 60:
                log.info("the CPU sample server was idle for %d min: stopping it", minutes)
                await self.stop()


sampler = CpuSampler()
