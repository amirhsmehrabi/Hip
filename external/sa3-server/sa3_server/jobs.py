"""An in-memory job registry with one worker thread: the GPU runs one job at a time."""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("sa3.jobs")

STATUSES = ("queued", "running", "done", "failed", "cancelled")


class JobCancelled(Exception):
    """Raised inside the sampler callback to abandon a job the client cancelled."""


@dataclass
class Job:
    id: str
    request: dict[str, Any]
    audio: tuple[int, Any] | None = None  # (sample_rate, waveform) for a2a / inpaint
    status: str = "queued"
    stage: str = "queued"
    progress: int = 0
    files: list[str] = field(default_factory=list)
    durations: list[float] = field(default_factory=list)
    error: str | None = None
    seed: int | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "files": list(self.files),
            "durations": list(self.durations),
            "error": self.error,
            "seed": self.seed,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class JobRegistry:
    def __init__(self, runner: Callable[[Job], None], keep_seconds: float = 6 * 3600) -> None:
        self._runner = runner
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._keep_seconds = keep_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="sa3-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            for job in self._jobs.values():
                if job.status in ("queued", "running"):
                    job.cancel_event.set()
        self._queue.put("")  # wake the worker so it notices the stop flag

    def submit(self, request: dict[str, Any], audio: tuple[int, Any] | None) -> tuple[Job, int]:
        job = Job(id=uuid.uuid4().hex[:12], request=request, audio=audio)
        with self._lock:
            self._jobs[job.id] = job
            position = sum(1 for j in self._jobs.values() if j.status == "queued")
        self._queue.put(job.id)
        self._prune()
        return job, position

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def query(self, ids: list[str]) -> list[dict[str, Any]]:
        with self._lock:
            return [self._jobs[i].to_dict() for i in ids if i in self._jobs]

    def cancel(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status == "queued":
                job.status = "cancelled"
                job.stage = "cancelled"
                job.finished_at = time.time()
            job.cancel_event.set()
            return job

    def _prune(self) -> None:
        cutoff = time.time() - self._keep_seconds
        with self._lock:
            old = [i for i, j in self._jobs.items() if j.finished_at and j.finished_at < cutoff]
            for i in old:
                del self._jobs[i]

    def _loop(self) -> None:
        while not self._stop.is_set():
            job_id = self._queue.get()
            if not job_id or self._stop.is_set():
                continue
            job = self.get(job_id)
            if job is None or job.status != "queued":
                continue
            job.status = "running"
            job.stage = "starting"
            try:
                self._runner(job)
                if job.cancel_event.is_set():
                    raise JobCancelled()
                job.status = "done"
                job.stage = "done"
                job.progress = 100
            except JobCancelled:
                job.status = "cancelled"
                job.stage = "cancelled"
            except Exception as exc:  # noqa: BLE001 - the job carries the message to the client
                log.exception("job %s failed", job.id)
                job.status = "failed"
                job.stage = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
            finally:
                job.audio = None  # drop the decoded context, it can be tens of MB
                job.finished_at = time.time()
