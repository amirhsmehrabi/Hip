"""The Stable Audio 3 checkpoints we know and how to tell that one is downloaded. Kept free of torch so the
downloader (sa3_server.download) starts in a second."""
from __future__ import annotations

from typing import Any

from huggingface_hub import try_to_load_from_cache

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
# The pre-training checkpoints: the start of LoRA training, and the only ones where CFG and a negative
# prompt do anything (about 50 steps, CFG around 7). Same limits as their post-trained twins.
for _name, _spec in list(MODEL_SPECS.items()):
    MODEL_SPECS[f"{_name}-base"] = {**_spec, "label": f"{_spec['label']} Base", "repo": f"{_spec['repo']}-base", "base": True}
for _spec in MODEL_SPECS.values():
    _spec.setdefault("base", False)

# Every checkpoint repo carries its own copy of the text encoder (T5Gemma) next to the DiT weights;
# the model config points the conditioner at that subfolder. Both have to be there to generate.
REQUIRED_FILES = ("model.safetensors", "t5gemma-b-b-ul2/model.safetensors")
# Not needed to generate: the model card picture, and the base repos' SVD bases (only LoRA training reads them).
IGNORE_PATTERNS = ["*.png", "svd_bases.pt"]


def installed_models() -> dict[str, str | None]:
    """model id -> path of the cached checkpoint, or None when it is not (completely) downloaded."""
    found: dict[str, str | None] = {}
    for name, spec in MODEL_SPECS.items():
        paths = [try_to_load_from_cache(spec["repo"], f) for f in REQUIRED_FILES]
        found[name] = paths[0] if all(isinstance(p, str) for p in paths) else None
    return found
