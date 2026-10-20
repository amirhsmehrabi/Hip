"""Downloads one of the assistant's language models into the Hugging Face cache (adapted from sa3_server.download).

    python -m prompt_assistant.download Qwen/Qwen3.5-2B          # progress for a person
    python -m prompt_assistant.download Qwen/Qwen3.5-2B --json   # one JSON object per line, for Remiqora's backend

The models are open (Apache-2.0); no token is needed, but a saved one is used and raises the rate limits.
JSON events: start {total}, progress {done, total}, done, login {user}, error {code, message}; error codes:
login (no or bad token), access (licence not accepted), network, unknown. Exit code 0 on success, 2 on error.
Stopping the process is safe: the files that finished stay in the cache and the next run fetches only the rest.
A file cut off half way starts over (huggingface_hub downloads each file to a temporary name unique to the
process, so a later run cannot continue it); the next run deletes such leftovers first.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import threading
import time
from fnmatch import fnmatch
from pathlib import Path

from huggingface_hub import HfApi, constants, get_token, login, snapshot_download
from huggingface_hub.utils import disable_progress_bars
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, LocalEntryNotFoundError, RepositoryNotFoundError

from .models import MODELS

# Only the weights, config, tokenizer and chat template are needed to generate text.
IGNORE_PATTERNS = ["*.png", "*.jpg", "*.gif", "*.md"]


class Reporter:
    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json
        self._lock = threading.Lock()

    def emit(self, event: str, **fields: object) -> None:
        with self._lock:
            if self.as_json:
                print(json.dumps({"event": event, **fields}), flush=True)
            elif event == "progress":
                done, total = fields["done"], fields["total"]
                print(f"\r  {done / 1e9:6.2f} / {total / 1e9:.2f} GB", end="", flush=True)  # type: ignore[operator]
            elif event == "start":
                print(f"Downloading {fields['repo']} ({fields['total'] / 1e9:.2f} GB) into {fields['cache']}", flush=True)  # type: ignore[operator]
            elif event == "done":
                print("\nDone.", flush=True)
            elif event == "login":
                print(f"Saved the token of {fields['user']}.", flush=True)
            elif event == "error":
                print(f"\nError ({fields['code']}): {fields['message']}", file=sys.stderr, flush=True)


def _bytes_on_disk(repo_dir: Path) -> int:
    """What the cache holds for the repo, finished files and partial ones (blobs/*.incomplete). Symlinked
    snapshot entries (Linux, macOS) point at blobs and are skipped; on Windows the snapshot holds the files."""
    total = 0
    for root, _dirs, files in os.walk(repo_dir):
        for name in files:
            path = os.path.join(root, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if not os.path.islink(path):
                total += st.st_size
    return total


def remove_partials(repo_dir: Path) -> int:
    """Deletes the temporary files a stopped download left behind (blobs/*.incomplete): no later run can
    continue them. Only safe while nothing else downloads this repo. Returns the bytes freed."""
    freed = 0
    for path in (repo_dir / "blobs").glob("*.incomplete"):
        try:
            size = path.stat().st_size
            path.unlink()
            freed += size
        except OSError:
            pass  # still open: another download of the same repo is running
    return freed


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, GatedRepoError):
        return "login" if get_token() is None else "access"
    if isinstance(exc, RepositoryNotFoundError):
        # Hugging Face answers 401 "not found" for a gated repo asked without a valid token.
        return "login"
    if isinstance(exc, HfHubHTTPError):
        status = getattr(exc.response, "status_code", None)
        if status == 401:
            return "login"
        if status == 403:
            return "access"
        return "network"
    if isinstance(exc, (LocalEntryNotFoundError, ConnectionError, TimeoutError, OSError)):
        return "network"
    return "unknown"


def download(model: str, out: Reporter) -> int:
    if model not in MODELS:
        out.emit("error", code="unknown", message=f"unknown model '{model}', one of {list(MODELS)}")
        return 2
    repo = model
    try:
        info = HfApi().model_info(repo, files_metadata=True)
        files = [s for s in info.siblings or [] if not any(fnmatch(s.rfilename, p) for p in IGNORE_PATTERNS)]
        total = sum(s.size or 0 for s in files)
    except Exception as exc:  # noqa: BLE001
        out.emit("error", code=_error_code(exc), message=str(exc).splitlines()[0] if str(exc) else type(exc).__name__)
        return 2

    repo_dir = Path(constants.HF_HUB_CACHE) / f"models--{repo.replace('/', '--')}"
    remove_partials(repo_dir)
    out.emit("start", model=model, repo=repo, total=total, cache=str(Path(constants.HF_HUB_CACHE)))
    stop = threading.Event()

    def watch() -> None:
        while not stop.wait(1.0):
            out.emit("progress", done=min(_bytes_on_disk(repo_dir), total), total=total)

    watcher = threading.Thread(target=watch, name="assistant-download-progress", daemon=True)
    watcher.start()
    try:
        snapshot_download(repo, ignore_patterns=IGNORE_PATTERNS)
    except Exception as exc:  # noqa: BLE001
        stop.set()
        out.emit("error", code=_error_code(exc), message=str(exc).splitlines()[0] if str(exc) else type(exc).__name__)
        return 2
    stop.set()
    watcher.join(timeout=2)
    out.emit("progress", done=total, total=total)
    out.emit("done", model=model)
    return 0


def save_token(token: str, out: Reporter) -> int:
    token = token.strip()
    if not token:
        out.emit("error", code="login", message="empty token")
        return 2
    try:
        user = HfApi().whoami(token=token)
    except Exception as exc:  # noqa: BLE001
        code = _error_code(exc)
        out.emit("error", code="login" if code in ("login", "access", "unknown") else code, message=str(exc).splitlines()[0] if str(exc) else type(exc).__name__)
        return 2
    # login() talks on stdout; keep it off the JSON stream.
    with contextlib.redirect_stdout(sys.stderr):
        login(token=token, add_to_git_credential=False, skip_if_logged_in=False)
    out.emit("login", user=user.get("name") or "")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m prompt_assistant.download", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("model", nargs="?", help=f"one of {', '.join(MODELS)}")
    parser.add_argument("--json", action="store_true", help="JSON lines instead of a progress line")
    parser.add_argument("--login", action="store_true", help="read a Hugging Face token from stdin, check it and save it")
    args = parser.parse_args(argv)
    out = Reporter(args.json)
    if args.json:
        disable_progress_bars()  # our own events carry the progress
    if args.login:
        sys.exit(save_token(sys.stdin.readline(), out))
    if not args.model:
        parser.error("name a model, or pass --login")
    started = time.time()
    code = download(args.model, out)
    if code == 0 and not args.json:
        print(f"Took {time.time() - started:.0f} s.")
    sys.exit(code)


if __name__ == "__main__":
    main()
