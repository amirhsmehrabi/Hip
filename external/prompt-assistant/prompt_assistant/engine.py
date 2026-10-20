"""The language model: which device it runs on, loading, and one generate() at a time."""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import torch

log = logging.getLogger("assistant.engine")

# The model takes about 5 GB in bfloat16; "auto" uses the GPU only when this much is free there.
GPU_HEADROOM_BYTES = 6 * 1024**3


def pick_device(wanted: str) -> str:
    """auto: the GPU when it has room (an engine may hold it), else Apple's GPU, else the CPU."""
    if wanted in ("cpu", "cuda", "mps"):
        return wanted
    if torch.cuda.is_available():
        try:
            free, _total = torch.cuda.mem_get_info()
            if free >= GPU_HEADROOM_BYTES:
                return "cuda"
            log.info("GPU has %.1f GB free, using the CPU", free / 1024**3)
        except Exception:  # noqa: BLE001
            pass
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class Model:
    def __init__(self, model_id: str, device: str = "auto") -> None:
        self.model_id = model_id
        self.wanted_device = device
        self.device: str | None = None
        self._tok: Any = None
        self._model: Any = None
        self._lock = threading.Lock()
        self.loading = False
        self.load_seconds: float | None = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        with self._lock:
            self._load_locked()

    def _load_locked(self) -> None:
        if self._model is not None:
            return
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.loading = True
        t0 = time.time()
        try:
            device = pick_device(self.wanted_device)
            # bfloat16 everywhere: on a CPU with AVX-512 BF16 it is twice as fast as float32 (RFC 0002, section 8).
            dtype = torch.float16 if device == "mps" else torch.bfloat16
            self._tok = AutoTokenizer.from_pretrained(self.model_id)
            self._model = AutoModelForCausalLM.from_pretrained(self.model_id, dtype=dtype).to(device).eval()
            self.device = device
        finally:
            self.loading = False
        self.load_seconds = time.time() - t0
        log.info("loaded %s on %s in %.1f s", self.model_id, self.device, self.load_seconds)

    def generate(self, system: str, user: str, max_new_tokens: int, temperature: float, seed: int | None = None,
                 on_token: Callable[[str, int], None] | None = None,
                 should_stop: Callable[[], bool] | None = None) -> tuple[str, int]:
        """The reply text (thinking off) and how many tokens it took. `on_token(text so far, tokens)` follows the
        writing; `should_stop()` returning True ends it early (the caller then treats the job as stopped)."""
        with self._lock:
            self._load_locked()
            text = self._tok.apply_chat_template(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                tokenize=False, add_generation_prompt=True, enable_thinking=False,
            )
            inputs = self._tok(text, return_tensors="pt").to(self.device)
            if seed is not None:
                torch.manual_seed(seed)
            extra: dict[str, Any] = {}
            if on_token is not None:
                extra["streamer"] = _Progress(self._tok, on_token)
            if should_stop is not None:
                from transformers import StoppingCriteriaList

                extra["stopping_criteria"] = StoppingCriteriaList([_Stop(should_stop)])
            with torch.no_grad():
                out = self._model.generate(
                    **inputs, max_new_tokens=int(max_new_tokens),
                    do_sample=temperature > 0, temperature=max(float(temperature), 1e-3), **extra,
                )
            new = out[0][inputs["input_ids"].shape[-1]:]
            reply = self._tok.decode(new, skip_special_tokens=True).strip()
            if "</think>" in reply:
                reply = reply.split("</think>", 1)[1].strip()
            return reply, int(new.shape[-1])

    def unload(self) -> None:
        with self._lock:
            self._model = None
            self._tok = None
            self.device = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()


class _Progress:
    """A transformers streamer: generate() hands it the prompt first, then each new token. Decodes what was written
    so far every few tokens (a reply is at most ~900 tokens, so decoding it whole stays cheap)."""

    EVERY = 4

    def __init__(self, tok: Any, on_token: Callable[[str, int], None]) -> None:
        self._tok = tok
        self._on_token = on_token
        self._ids: list[int] = []
        self._prompt_seen = False

    def put(self, value: Any) -> None:
        if not self._prompt_seen:
            self._prompt_seen = True  # the first call is the prompt
            return
        self._ids.extend(int(x) for x in value.reshape(-1).tolist())
        if len(self._ids) % self.EVERY == 0:
            self._emit()

    def end(self) -> None:
        self._emit()

    def _emit(self) -> None:
        self._on_token(self._tok.decode(self._ids, skip_special_tokens=True), len(self._ids))


class _Stop:
    """A stopping criterion that ends generation when the job is stopped."""

    def __init__(self, should_stop: Callable[[], bool]) -> None:
        self._should_stop = should_stop

    def __call__(self, input_ids: Any, scores: Any, **kwargs: Any) -> Any:
        return torch.full((input_ids.shape[0],), bool(self._should_stop()), dtype=torch.bool, device=input_ids.device)
