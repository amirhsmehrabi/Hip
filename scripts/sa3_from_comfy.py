# /// script
# requires-python = ">=3.10"
# dependencies = ["huggingface_hub>=0.30"]
# ///
"""Puts a post-trained Stable Audio 3 checkpoint into Remiqora's Hugging Face cache without a Hugging Face account.

The post-trained checkpoints (stabilityai/stable-audio-3-medium, -small-music, -small-sfx) are gated. Their DiT
weights are also published openly by Comfy-Org (Comfy-Org/stable-audio-3) and are byte-identical: the script checks
the SHA-256 against the official file. Everything else a checkpoint needs (the T5Gemma text encoder, its tokenizer,
the model config and the licence files) is in the open -base repos of the same model. The base config differs from
the post-trained one in the fields used at inference time only by the diffusion objective, the default sample size,
the autoencoder scale (small-sfx) and the repo the text encoder is read from; the script sets those. Its "training"
section stays the base one, which nothing in Remiqora reads.

The result is laid out exactly as a download from the official repo would be (models--stabilityai--stable-audio-3-*
in the Hugging Face cache, at the official commit), so Remiqora sees the checkpoint as installed.

Windows, with the Python of Remiqora's Stable Audio 3 engine (nothing else to install):
    "%LOCALAPPDATA%\\Remiqora\\engines\\StableAudio\\.venv\\Scripts\\python.exe" sa3_from_comfy.py small-music
macOS:
    ~/Library/Application\\ Support/Remiqora/engines/StableAudio/.venv/bin/python sa3_from_comfy.py small-music
or with uv:
    uv run sa3_from_comfy.py small-music

Options: --hf-home DIR (default: Remiqora's cache), --yes (accept the licences without asking).
The weights stay under the Stability AI Community License and the text encoder under the Gemma Terms of Use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

COMFY_REPO = "Comfy-Org/stable-audio-3"

# model -> official commit, SHA-256 of its model.safetensors, the commit of its -base repo the files are taken from,
# and the default sample size of the post-trained config.
MODELS = {
    "medium": {
        "commit": "d4d3579395a8ac0df4ab13b5b1d7138ce7290f81",
        "sha256": "48d9c65e290e7bcd5194e0633bfc2424a59ee9683f5c2d58762d997b7d8ce0b5",
        "base_commit": "c397d9a6912dc8b1f71a80e7b9673f4d307e7f8c",
        "sample_size": 16777216,
    },
    "small-music": {
        "commit": "8bdfb53c6b0fbc62113cd571fd37373efe15fa14",
        "sha256": "da85866b11b01d0694d990785f6abbd79c8064df1b0e6f8aea52935e0ef84b64",
        "base_commit": "4249e9179cd64a03fc016919c88d0e6f2c5617f3",
        "sample_size": 5292032,
    },
    "small-sfx": {
        "commit": "05ca3857881c94a2b84026b1111c537d78f5f9f0",
        "sha256": "ed9cf1b6172f1a8c2921a9560c21109ff3239524563ced9dce6dcdef41e2f515",
        "base_commit": "b332479a012f83c24c4381f331ce594284ec8a81",
        "sample_size": 5292032,
    },
}

ENCODER_DIR = "t5gemma-b-b-ul2"
ENCODER_FILES = [
    "config.json",
    "generation_config.json",
    "model.safetensors",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer.model",
    "tokenizer_config.json",
]
LICENCE_FILES = ["LICENSE.md", "LICENSE_GEMMA.md", "NOTICE"]


def remiqora_hf_home() -> Path:
    """The cache the desktop app uses: <data root>/cache/huggingface (see desktop/src/paths.js)."""
    if os.getenv("REMIQORA_HOME"):
        root = Path(os.environ["REMIQORA_HOME"])
    elif sys.platform == "win32":
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Remiqora"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "Remiqora"
    else:
        root = Path(os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "Remiqora"
    return root / "cache" / "huggingface"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(16 << 20):
            h.update(chunk)
    return h.hexdigest()


def post_trained_config(base: dict, model: str) -> dict:
    """The base model config with the fields the post-trained checkpoint is run with."""
    config = json.loads(json.dumps(base))
    config["sample_size"] = MODELS[model]["sample_size"]
    config["model"]["diffusion"]["diffusion_objective"] = "rf_denoiser"
    config["model"]["pretransform"].pop("scale", None)
    for cond in config["model"]["conditioning"]["configs"]:
        if cond.get("type") == "t5gemma":
            cond["config"]["repo_id"] = f"stabilityai/stable-audio-3-{model}"
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("model", choices=sorted(MODELS))
    parser.add_argument("--hf-home", type=Path, help="Hugging Face cache root (default: Remiqora's)")
    parser.add_argument("--yes", action="store_true", help="accept the licences without asking")
    args = parser.parse_args()

    hf_home = (args.hf_home or remiqora_hf_home()).resolve()
    # Before huggingface_hub is imported: it reads these once.
    os.environ["HF_HOME"] = str(hf_home)
    os.environ.pop("HF_HUB_CACHE", None)
    os.environ.pop("HF_HUB_OFFLINE", None)
    from huggingface_hub import hf_hub_download

    spec = MODELS[args.model]
    repo_dir = hf_home / "hub" / f"models--stabilityai--stable-audio-3-{args.model}"
    snapshot = repo_dir / "snapshots" / spec["commit"]
    if (snapshot / "model.safetensors").is_file() and (snapshot / ENCODER_DIR / "model.safetensors").is_file():
        print(f"{args.model} is already in {repo_dir}")
        return 0

    print(
        f"Stable Audio 3 {args.model}: the weights are under the Stability AI Community License\n"
        "(https://stability.ai/community-license-agreement, free for individuals and organisations under\n"
        "USD 1M annual revenue) and the T5Gemma text encoder under the Gemma Terms of Use\n"
        "(https://ai.google.dev/gemma/terms). Both licence texts are saved next to the weights."
    )
    if not args.yes and input("Accept them and continue? [y/N] ").strip().lower() not in ("y", "yes"):
        return 1

    staging = hf_home / "sa3-from-comfy" / args.model
    base_repo = f"stabilityai/stable-audio-3-{args.model}-base"

    def fetch(repo: str, filename: str, revision: str = "main") -> Path:
        # token=False: the files are public, and a stale saved token must not make them fail.
        return Path(hf_hub_download(repo, filename, revision=revision, local_dir=staging, token=False))

    print(f"\nText encoder, tokenizer and config from {base_repo}")
    encoder = [fetch(base_repo, f"{ENCODER_DIR}/{f}", spec["base_commit"]) for f in ENCODER_FILES]
    licences = [fetch(base_repo, f, spec["base_commit"]) for f in LICENCE_FILES]
    base_config = json.loads(fetch(base_repo, "model_config.json", spec["base_commit"]).read_text(encoding="utf-8"))

    comfy_name = f"checkpoints/stable_audio_3_{args.model.replace('-', '_')}.safetensors"
    print(f"\nWeights from {COMFY_REPO} ({comfy_name})")
    weights = fetch(COMFY_REPO, comfy_name)
    print("Checking the SHA-256 against the official file...")
    digest = sha256_of(weights)
    if digest != spec["sha256"]:
        print(f"Error: {comfy_name} has SHA-256 {digest}, the official {args.model} file has {spec['sha256']}.\n"
              f"Nothing was installed; the download stays in {staging}.", file=sys.stderr)
        return 2

    (snapshot / ENCODER_DIR).mkdir(parents=True, exist_ok=True)
    for f, path in zip(ENCODER_FILES, encoder):
        shutil.move(str(path), snapshot / ENCODER_DIR / f)
    for f, path in zip(LICENCE_FILES, licences):
        shutil.move(str(path), snapshot / f)
    (snapshot / "model_config.json").write_text(
        json.dumps(post_trained_config(base_config, args.model), indent=4), encoding="utf-8")
    # Last: Remiqora counts a checkpoint as installed once model.safetensors is in place.
    shutil.move(str(weights), snapshot / "model.safetensors")
    (repo_dir / "refs").mkdir(exist_ok=True)
    (repo_dir / "refs" / "main").write_text(spec["commit"], encoding="utf-8")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        staging.parent.rmdir()
    except OSError:
        pass

    print(f"\nDone: {args.model} is in {repo_dir}.\n"
          "Restart Remiqora (or stop and start Stable Audio 3) to use it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
