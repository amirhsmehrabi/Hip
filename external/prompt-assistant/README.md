# prompt-assistant

Remiqora's prompt assistant: a small FastAPI server around a local language model
(Qwen3.5, Apache-2.0) that turns an idea into the prompt each engine takes. The backend starts it on
the first request and stops it after a while without use; it is not one of the GPU engines.

```
uv sync
uv run python -m prompt_assistant --port 8004 --device auto
uv run python -m prompt_assistant.download Qwen/Qwen3.5-2B
```

`POST /v1/write {task, idea, language?, kind?, seed?}` with `task` one of `sa3` (Stable Audio 3 tags,
with Stable Audio's own instructions from `prompt_assistant/sa3_prompts.py`, MIT), `yue2-song`,
`ace-song`, `ace-instrumental`. `--device auto` takes the GPU when about 6 GB are free there, else the
CPU (bfloat16).
