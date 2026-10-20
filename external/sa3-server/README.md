# sa3-server

A small FastAPI server that Remiqora's orchestrator runs around
[Stable Audio 3](https://github.com/Stability-AI/stable-audio-3). It exposes
text-to-audio, audio-to-audio and inpainting/continuation as a job queue over HTTP.

Install (a uv project, like `external/Demucs`):

```
uv sync
uv run sa3-server --host 127.0.0.1 --port 8002
```

The server reads the weights from the Hugging Face cache (`HF_HOME`) and never downloads on
its own. `python -m sa3_server.download <model>` fetches one (`--json` prints progress events
for Remiqora's backend, which runs it from the app's Stable Audio 3 page; `--login` reads a
token from stdin and saves it). `medium`, `small-music` and `small-sfx` are gated: accept the
licence on `stabilityai/stable-audio-3-<model>` first; the `-base` checkpoints are open.

API (all under `/v1`): `GET /health`, `GET /v1/models`, `POST /v1/models/load`,
`POST /v1/jobs` (multipart), `POST /v1/jobs/query`, `POST /v1/jobs/{id}/cancel`,
`GET /v1/files/{name}`.
