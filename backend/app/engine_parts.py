"""Downloadable parts of ACE-Step and YuE2 for the Models page (Stable Audio 3 has its own, app/sa3_weights.py).

Each part is fetched by the engine's own tool, the way the installers do it: ACE-Step's `acestep-download`
(Hugging Face, ModelScope as its fallback) and audio.cpp's `tools/model_manager_v2.py install <package>`.
Neither reports byte counts, so progress is the growth of the folder the part lands in against its known size.
One download at a time; stopping kills the tool, and the next run picks up what it left.
"""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Optional

from . import engine_settings, features
from .config import ACE_STEP_DIR, LOG_DIR, MUSCRIPTOR_MODEL_PATH, SHEETSAGE_MODEL_PATH, UV_BIN, YUE2_DIR, YUE2_MODEL_PATH

IS_WINDOWS = sys.platform == "win32"

Status = Literal["running", "done", "failed", "cancelled"]


@dataclass(frozen=True)
class Part:
    id: str
    engine: str
    # what it is, for grouping on the page: the main bundle, a DiT, a language model, a YuE2 precision, shared weights
    kind: str
    bytes: int
    folder: Path
    installed: Callable[[], bool]
    commands: Callable[[], list[tuple[list[str], Path]]]
    required: bool = False


def _ace(model: Optional[str]) -> Callable[[], list[tuple[list[str], Path]]]:
    # --force only skips acestep-download's "the folder exists" check (a stopped download leaves the folder),
    # its Hugging Face download still keeps the files that are complete; --skip-main leaves the core bundle alone.
    args = [UV_BIN, "run", "acestep-download", *(["--model", model, "--force", "--skip-main"] if model else [])]
    return lambda: [(args, ACE_STEP_DIR)]


def _yue2(*packages: str) -> Callable[[], list[tuple[list[str], Path]]]:
    # The backend's own Python: the model manager needs only the standard library (the desktop app does the same).
    return lambda: [([sys.executable, str(Path("tools") / "model_manager_v2.py"), "install", p], YUE2_DIR) for p in packages]


def _ace_main_installed() -> bool:
    return all(engine_settings.ace_checkpoint_ready(n) for n in ("acestep-v15-turbo", "acestep-5Hz-lm-1.7B")) \
        and (ACE_STEP_DIR / "checkpoints" / "vae").is_dir()


def _yue2_common_installed() -> bool:
    return all(_is_file(p) for p in (YUE2_MODEL_PATH / "yue2-vae-f16.gguf", SHEETSAGE_MODEL_PATH, MUSCRIPTOR_MODEL_PATH))


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


_CKPT = ACE_STEP_DIR / "checkpoints"
_ACE_SIZES = {
    "acestep-v15-sft": 4_790_000_000, "acestep-v15-base": 4_790_000_000,
    "acestep-v15-xl-turbo": 19_950_000_000, "acestep-v15-xl-sft": 19_950_000_000, "acestep-v15-xl-base": 19_950_000_000,
    "acestep-5Hz-lm-0.6B": 1_370_000_000, "acestep-5Hz-lm-4B": 8_430_000_000,
}

PARTS: dict[str, Part] = {}


def _add(p: Part) -> None:
    PARTS[p.id] = p


# ACE-Step: the main bundle (turbo DiT, the 1.7B language model, the VAE and the text encoder) and the extras.
_add(Part("ace-main", "ace_step", "main", 9_400_000_000, _CKPT, _ace_main_installed, _ace(None), required=True))
for _name, _size in _ACE_SIZES.items():
    _add(Part(_name, "ace_step", "lm" if "-lm-" in _name else "dit", _size, _CKPT / _name,
              (lambda n=_name: engine_settings.ace_checkpoint_ready(n)), _ace(_name)))
# YuE2: the shared weights (VAE, SheetSage2, MuScriptor) and one main model per precision.
_add(Part("yue2-common", "yue2", "common", 3_390_000_000, YUE2_MODEL_PATH.parent, _yue2_common_installed,
          _yue2("yue2_vae_f16", "sheetsage2_orig", "muscriptor_small_f32"), required=True))
for _p, _size in (("q8_0", 4_260_000_000), ("q4_0", 2_670_000_000)):
    _add(Part(f"yue2-{_p}", "yue2", "precision", _size, YUE2_MODEL_PATH,
              (lambda p=_p: p in features.yue2_precisions()), _yue2(f"yue2_main_{_p}")))


def engine_ready(engine: str) -> bool:
    """The engine's own environment is there, so its tool can run."""
    if engine == "ace_step":
        return features.has_ace_step()
    if engine == "yue2":
        return (YUE2_DIR / "tools" / "model_manager_v2.py").is_file()
    return False


@dataclass
class Download:
    part: str
    status: Status = "running"
    done: int = 0
    total: int = 0
    error: Optional[str] = None
    proc: Optional[asyncio.subprocess.Process] = field(default=None, repr=False)
    cancel_requested: bool = False


_downloads: dict[str, Download] = {}


def active() -> Optional[str]:
    return next((d.part for d in _downloads.values() if d.status == "running"), None)


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def snapshot(engine: str) -> list[dict]:
    out = []
    for p in PARTS.values():
        if p.engine != engine:
            continue
        d = _downloads.get(p.id)
        running = d is not None and d.status == "running"
        out.append({
            "id": p.id, "kind": p.kind, "bytes": p.bytes, "required": p.required,
            "installed": not running and p.installed(),
            "download": None if d is None else {"status": d.status, "done": d.done, "total": d.total, "error": d.error},
        })
    return out


async def start(part_id: str) -> None:
    part = PARTS.get(part_id)
    if part is None:
        raise KeyError(part_id)
    current = active()
    if current == part_id:
        return
    if current is not None:
        raise RuntimeError(f"'{current}' is downloading; one at a time")
    if not engine_ready(part.engine):
        raise FileNotFoundError(f"{part.engine} is not installed")
    d = Download(part=part_id, total=part.bytes)
    _downloads[part_id] = d
    asyncio.create_task(_run(part, d))


async def cancel(part_id: str) -> None:
    d = _downloads.get(part_id)
    if d is None or d.status != "running":
        return
    d.cancel_requested = True
    if d.proc is not None:
        await _kill_tree(d.proc)


async def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    if IS_WINDOWS:
        killer = await asyncio.create_subprocess_exec("taskkill", "/PID", str(proc.pid), "/T", "/F",
                                                      stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await killer.wait()
    else:
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def _run(part: Part, d: Download) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "engine_downloads.log"
    # Not created here: acestep-download takes an existing folder for a finished download and skips it.
    baseline = await asyncio.to_thread(_dir_size, part.folder)
    stop = asyncio.Event()

    async def watch() -> None:
        while not stop.is_set():
            grown = max(0, await asyncio.to_thread(_dir_size, part.folder) - baseline)
            d.done = min(grown, int(d.total * 0.99))
            try:
                await asyncio.wait_for(stop.wait(), timeout=1.5)
            except asyncio.TimeoutError:
                pass

    watcher = asyncio.create_task(watch())
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_SYMLINKS_WARNING": "1"}
    code = 0
    try:
        with open(log_path, "a", encoding="utf-8") as log:
            for cmd, cwd in part.commands():
                if d.cancel_requested:
                    break
                log.write(f"\n--- {part.id}: {' '.join(cmd)}\n")
                log.flush()
                try:
                    proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(cwd), env=env, stdin=asyncio.subprocess.DEVNULL,
                                                                stdout=log, stderr=asyncio.subprocess.STDOUT)
                except OSError as exc:
                    d.error, code = str(exc), -1
                    break
                d.proc = proc
                code = await proc.wait()
                d.proc = None
                if code != 0:
                    break
    finally:
        stop.set()
        await watcher
    if d.cancel_requested:
        d.status = "cancelled"
    elif code == 0 and part.installed():
        d.status, d.done = "done", d.total
    else:
        d.status = "failed"
        d.error = d.error or f"the download exited with code {code}; see {log_path}"
