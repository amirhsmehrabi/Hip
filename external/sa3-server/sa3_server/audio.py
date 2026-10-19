"""Audio in and out: decode an uploaded context file into the (sample_rate, waveform) tuple
Stable Audio 3 expects, and write generated tensors as 16-bit stereo WAV files."""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio.functional as AF

TARGET_SR = 44100
# Generated audio is clamped to [-1, 1] by the model; keep half a dB of headroom so a hot
# peak does not clip after the int16 conversion, without touching the overall level
# (a repaint must sit at the level of the context around it).
PEAK_LIMIT = 10 ** (-0.5 / 20)


def decode_upload(data: bytes, target_sr: int = TARGET_SR) -> tuple[int, torch.Tensor]:
    """Bytes of a wav/flac/ogg/mp3 file -> (sample_rate, float32 waveform [2, N]) at target_sr."""
    audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)  # [N, C]
    wav = torch.from_numpy(np.ascontiguousarray(audio.T))  # [C, N]
    if wav.shape[0] == 1:
        wav = wav.repeat(2, 1)
    elif wav.shape[0] > 2:
        wav = wav[:2]
    if sr != target_sr:
        wav = AF.resample(wav, sr, target_sr)
        sr = target_sr
    return sr, wav


def write_wav(path: Path, audio: torch.Tensor, sample_rate: int) -> float:
    """Write one [C, N] float tensor as PCM16 WAV. Returns the duration in seconds."""
    data = audio.detach().to(torch.float32).cpu()
    if data.dim() == 1:
        data = data.unsqueeze(0)
    if data.shape[0] == 1:
        data = data.repeat(2, 1)
    peak = float(data.abs().max()) if data.numel() else 0.0
    if peak > PEAK_LIMIT:
        data = data * (PEAK_LIMIT / peak)
    sf.write(str(path), data.T.numpy(), sample_rate, subtype="PCM_16")
    return data.shape[1] / sample_rate


def trim_to_seconds(audio: torch.Tensor, seconds: float, sample_rate: int) -> torch.Tensor:
    n = int(round(seconds * sample_rate))
    return audio[..., :n] if n > 0 else audio


def trim_leading_silence(audio: torch.Tensor, sample_rate: int, threshold_db: float = -60.0, keep_ms: float = 5.0) -> torch.Tensor:
    """Drops the quiet run before a one-shot's attack, keeping a few ms of lead-in so the attack is not clipped."""
    if audio.numel() == 0:
        return audio
    level = audio.abs().amax(dim=0) if audio.dim() == 2 else audio.abs()  # [N]
    threshold = 10 ** (threshold_db / 20)
    loud = torch.nonzero(level > threshold)
    if loud.numel() == 0:
        return audio
    start = max(0, int(loud[0]) - int(sample_rate * keep_ms / 1000))
    return audio[..., start:]
