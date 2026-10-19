"""Model registry and generation: which Stable Audio 3 checkpoints exist in the Hugging Face
cache, which are resident, and one `run()` that turns a job into WAV files."""
from __future__ import annotations

import logging
import random
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

import torch
from huggingface_hub import try_to_load_from_cache

from .audio import trim_to_seconds, write_wav
from .jobs import Job, JobCancelled

log = logging.getLogger("sa3.engine")

MODEL_SPECS: dict[str, dict[str, Any]] = {
    "medium": {
        "label": "Medium",
        "repo": "stabilityai/stable-audio-3-medium",
        "params": "1.4B",
        "max_seconds": 380,
        "gpu_only": True,
        "kinds": ["music", "sfx"],
    },
    "small-music": {
        "label": "Small Music",
        "repo": "stabilityai/stable-audio-3-small-music",
        "params": "433M",
        "max_seconds": 120,
        "gpu_only": False,
        "kinds": ["music"],
    },
    "small-sfx": {
        "label": "Small SFX",
        "repo": "stabilityai/stable-audio-3-small-sfx",
        "params": "433M",
        "max_seconds": 120,
        "gpu_only": False,
        "kinds": ["sfx"],
    },
}
TASKS = ("text", "a2a", "inpaint")


def installed_models() -> dict[str, str | None]:
    """model id -> path of the cached checkpoint, or None when it was never downloaded."""
    found: dict[str, str | None] = {}
    for name, spec in MODEL_SPECS.items():
        path = try_to_load_from_cache(spec["repo"], "model.safetensors")
        found[name] = path if isinstance(path, str) else None
    return found


class Engine:
    def __init__(self, out_dir: Path, device: str | None = None, max_resident: int = 1) -> None:
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.device = device
        self.max_resident = max(1, max_resident)
        self._models: "OrderedDict[str, Any]" = OrderedDict()
        self._lock = threading.RLock()
        self._loading: str | None = None

    # ---- residency ----
    def loaded(self) -> list[str]:
        with self._lock:
            return list(self._models.keys())

    def loading(self) -> str | None:
        return self._loading

    def load(self, name: str) -> Any:
        if name not in MODEL_SPECS:
            raise ValueError(f"unknown model '{name}'")
        with self._lock:
            if name in self._models:
                self._models.move_to_end(name)
                return self._models[name]
            if installed_models().get(name) is None:
                raise FileNotFoundError(
                    f"model '{name}' is not downloaded: accept the licence on "
                    f"https://huggingface.co/{MODEL_SPECS[name]['repo']} and run "
                    f"`hf download {MODEL_SPECS[name]['repo']}`"
                )
            while len(self._models) >= self.max_resident:
                evicted, model = self._models.popitem(last=False)
                log.info("unloading %s", evicted)
                del model
                self._free()
            from stable_audio_3 import StableAudioModel

            self._loading = name
            t0 = time.time()
            try:
                model = StableAudioModel.from_pretrained(name, device=self.device)
            finally:
                self._loading = None
            self._models[name] = model
            log.info("loaded %s in %.1fs", name, time.time() - t0)
            return model

    def unload_all(self) -> None:
        with self._lock:
            self._models.clear()
            self._free()

    @staticmethod
    def _free() -> None:
        import gc

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def device_name(self) -> str:
        if self.device:
            return self.device
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    # ---- generation ----
    def run(self, job: Job) -> None:
        req = job.request
        name = req["model"]
        job.stage = "loading_model"
        model = self.load(name)
        sr = int(model.model_config["sample_rate"])
        steps = int(req["steps"])
        seed = int(req["seed"])
        if seed < 0:
            seed = random.randint(0, 2**31 - 1)
        job.seed = seed

        def on_step(info: dict[str, Any]) -> None:
            if job.cancel_event.is_set():
                raise JobCancelled()
            job.stage = "sampling"
            job.progress = min(99, int(round((info.get("i", 0) + 1) / steps * 95)))

        kwargs: dict[str, Any] = {
            "prompt": req["prompt"],
            "negative_prompt": req.get("negative_prompt") or None,
            "duration": float(req["duration"]),
            # generate() clamps the audio length to sample_size, whose default is 120 s; the checkpoint's
            # own limit (380 s for medium) lives in its config, the same value the upstream CLI passes.
            "sample_size": int(model.model_config["sample_size"]),
            "steps": steps,
            "cfg_scale": float(req["cfg_scale"]),
            "seed": seed,
            "batch_size": int(req["batch_size"]),
            "callback": on_step,
            "disable_tqdm": True,
        }
        if req.get("chunked_decode") is not None:
            kwargs["chunked_decode"] = bool(req["chunked_decode"])

        task = req["task"]
        if task == "a2a":
            kwargs["init_audio"] = job.audio
            kwargs["init_noise_level"] = float(req["init_noise_level"])
        elif task == "inpaint":
            kwargs["inpaint_audio"] = job.audio
            kwargs["inpaint_mask_start_seconds"] = [float(x) for x in req["mask_start"]]
            kwargs["inpaint_mask_end_seconds"] = [float(x) for x in req["mask_end"]]

        job.stage = "encoding"
        if job.cancel_event.is_set():
            raise JobCancelled()
        with torch.inference_mode():
            audio = model.generate(**kwargs)  # [B, C, N] float32 in [-1, 1]
        job.stage = "decoding"
        job.progress = 97
        if job.cancel_event.is_set():
            raise JobCancelled()

        if task == "a2a":
            audio = trim_to_seconds(audio, float(req["duration"]), sr)

        files: list[str] = []
        durations: list[float] = []
        for i in range(audio.shape[0]):
            fname = f"{job.id}_{i}.wav"
            durations.append(write_wav(self.out_dir / fname, audio[i], sr))
            files.append(f"/v1/files/{fname}")
        job.files = files
        job.durations = durations
        del audio
        self._free()
