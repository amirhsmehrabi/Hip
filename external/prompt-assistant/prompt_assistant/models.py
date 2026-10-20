"""The models the Models page offers (all Apache-2.0, no licence to accept); sizes are the bfloat16 weights.
Kept free of torch so the downloader starts at once."""
from __future__ import annotations

from typing import Any

MODELS: dict[str, dict[str, Any]] = {
    "Qwen/Qwen3.5-0.8B": {"bytes": 1_750_000_000},
    "Qwen/Qwen3.5-2B": {"bytes": 4_550_000_000},
    "Qwen/Qwen3.5-4B": {"bytes": 9_320_000_000},
}
DEFAULT_MODEL = "Qwen/Qwen3.5-2B"
