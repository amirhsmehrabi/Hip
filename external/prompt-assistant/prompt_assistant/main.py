"""HTTP server: POST /v1/write turns an idea into an engine's prompt."""
from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import __version__, tasks
from .engine import Model
from .models import DEFAULT_MODEL

log = logging.getLogger("assistant")

class WriteRequest(BaseModel):
    task: str
    idea: str = Field(min_length=1, max_length=4000)
    language: str | None = None
    kind: str | None = None
    seed: int | None = None


def build_app(model: Model) -> FastAPI:
    app = FastAPI(title="prompt-assistant", version=__version__)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "model": model.model_id, "loaded": model.loaded, "loading": model.loading,
                "device": model.device, "version": __version__}

    @app.post("/v1/load")
    def load() -> dict[str, Any]:
        model.load()
        return health()

    @app.post("/v1/write")
    def write(req: WriteRequest) -> dict[str, Any]:
        t0 = time.time()
        tokens = 0

        def generate(system: str, user: str, max_new: int, temperature: float, seed: int | None) -> tuple[str, int]:
            nonlocal tokens
            reply, n = model.generate(system, user, max_new, temperature, seed)
            tokens += n
            return reply, n

        try:
            fields = tasks.run(req.task, generate, req.idea, language=req.language, kind=req.kind, seed=req.seed)
        except tasks.TaskError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"task": req.task, "fields": fields, "tokens": tokens, "took_ms": int((time.time() - t0) * 1000),
                "device": model.device, "model": model.model_id}

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="prompt-assistant")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8004)
    parser.add_argument("--model", default=os.getenv("ASSISTANT_MODEL") or DEFAULT_MODEL)
    parser.add_argument("--device", default=os.getenv("ASSISTANT_DEVICE") or "auto", help="auto / cpu / cuda / mps")
    parser.add_argument("--threads", type=int, default=0, help="CPU threads (0 = PyTorch's default, one per core)")
    parser.add_argument("--preload", action="store_true", help="load the model right away, not on the first request")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if args.threads > 0:
        import torch

        torch.set_num_threads(args.threads)
    model = Model(args.model, args.device)
    app = build_app(model)
    if args.preload:
        # warm up in the background: /health answers at once, the first /v1/write waits for the load
        threading.Thread(target=model.load, name="assistant-preload", daemon=True).start()

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level=args.log_level, access_log=False)
    server = uvicorn.Server(config)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, lambda *_: setattr(server, "should_exit", True))
    server.run()


if __name__ == "__main__":
    main()

