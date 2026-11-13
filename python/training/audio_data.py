from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Iterable

import numpy as np

SAMPLE_RATE = 16000
CLIP_SAMPLES = 16000


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if width != 2:
        raise ValueError(f"{path}: expected 16-bit PCM WAV")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        old_times = np.arange(len(samples), dtype=np.float64) / rate
        new_length = max(1, round(len(samples) * SAMPLE_RATE / rate))
        new_times = np.arange(new_length, dtype=np.float64) / SAMPLE_RATE
        samples = np.interp(new_times, old_times, samples).astype(np.float32)
    return samples


def fixed_window(samples: np.ndarray, rng: np.random.Generator | None = None) -> np.ndarray:
    samples = np.asarray(samples, dtype=np.float32)
    if len(samples) > CLIP_SAMPLES:
        # Center crop keeps a prompted wake word near the middle of the recording.
        start = (len(samples) - CLIP_SAMPLES) // 2
        return samples[start:start + CLIP_SAMPLES]
    if len(samples) < CLIP_SAMPLES:
        left = int(rng.integers(0, CLIP_SAMPLES - len(samples) + 1)) if rng else (CLIP_SAMPLES - len(samples)) // 2
        return np.pad(samples, (left, CLIP_SAMPLES - len(samples) - left))
    return samples


def load_manifest(path: Path, split: str | None = None) -> list[dict[str, str]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if split:
        rows = [row for row in rows if row["split"] == split]
    return rows
