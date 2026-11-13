from __future__ import annotations

import numpy as np


def augment(samples: np.ndarray, rng: np.random.Generator,
            noise_bank: list[np.ndarray] | None = None) -> np.ndarray:
    result = np.asarray(samples, dtype=np.float32).copy()
    if rng.random() < 0.7:
        result *= float(rng.uniform(0.55, 1.25))
    if rng.random() < 0.6:
        shift = int(rng.integers(-1600, 1601))
        result = np.roll(result, shift)
        if shift > 0:
            result[:shift] = 0
        elif shift < 0:
            result[shift:] = 0
    if noise_bank and rng.random() < 0.7:
        noise = noise_bank[int(rng.integers(0, len(noise_bank)))]
        if len(noise) < len(result):
            noise = np.tile(noise, int(np.ceil(len(result) / len(noise))))
        start = int(rng.integers(0, len(noise) - len(result) + 1))
        noise = noise[start:start + len(result)]
        snr_db = float(rng.uniform(5, 25))
        signal_rms = np.sqrt(np.mean(result ** 2) + 1e-8)
        noise_rms = np.sqrt(np.mean(noise ** 2) + 1e-8)
        result += noise * (signal_rms / (noise_rms * (10 ** (snr_db / 20))))
    if rng.random() < 0.25:
        speed = float(rng.uniform(0.92, 1.08))
        positions = np.arange(0, len(result), speed)
        source = np.arange(len(result))
        result = np.interp(positions, source, result).astype(np.float32)
        if len(result) < 16000:
            result = np.pad(result, (0, 16000 - len(result)))
        result = result[:16000]
    if rng.random() < 0.25:
        delay = int(rng.integers(160, 640))
        result[delay:] += result[:-delay] * float(rng.uniform(0.05, 0.22))
    return np.clip(result, -1.0, 1.0)
