"""Stable Audio 3 weights from the app: what is downloaded, start or stop a download, save a Hugging Face token.
See app/sa3_weights.py."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import sa3_weights
from ..orchestrator.manager import manager
from ..orchestrator.state import ModelStatus
from ..sfx_cpu import sampler

router = APIRouter(prefix="/api/sa3-weights", tags=["stable-audio"])


class TokenRequest(BaseModel):
    token: str = Field(min_length=1, max_length=400)


@router.get("")
async def weights() -> dict:
    return await asyncio.to_thread(sa3_weights.snapshot)


@router.post("/{model}/download")
async def start_download(model: str) -> dict:
    try:
        await sa3_weights.start(model)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await asyncio.to_thread(sa3_weights.snapshot)


@router.post("/{model}/cancel")
async def cancel_download(model: str) -> dict:
    await sa3_weights.cancel(model)
    return await asyncio.to_thread(sa3_weights.snapshot)


@router.delete("/{model}")
async def delete_model(model: str) -> dict:
    running = manager.state.models["stable_audio"].status != ModelStatus.STOPPED or sampler.status in ("running", "starting")
    try:
        await sa3_weights.delete(model, running)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return await asyncio.to_thread(sa3_weights.snapshot)


@router.post("/token")
async def save_token(req: TokenRequest) -> dict:
    try:
        return await sa3_weights.save_token(req.token)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
