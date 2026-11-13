from __future__ import annotations

import numpy as np

SAMPLE_RATE = 16000
FRAME_LENGTH = 400
FRAME_SHIFT = 160
FFT_SIZE = 512
MEL_BINS = 40


def _hz_to_mel(value: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + value / 700.0)


def _mel_to_hz(value: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (value / 2595.0) - 1.0)


def mel_filterbank(sample_rate: int = SAMPLE_RATE, bins: int = MEL_BINS) -> np.ndarray:
    low_mel = _hz_to_mel(np.array([0.0]))[0]
    high_mel = _hz_to_mel(np.array([sample_rate / 2]))[0]
    points = _mel_to_hz(np.linspace(low_mel, high_mel, bins + 2))
    fft_freqs = np.linspace(0.0, sample_rate / 2, FFT_SIZE // 2 + 1)
    filters = np.zeros((bins, len(fft_freqs)), dtype=np.float32)
    for index in range(bins):
        left, center, right = points[index:index + 3]
        filters[index] = np.maximum(0.0, np.minimum(
            (fft_freqs - left) / max(center - left, 1e-8),
            (right - fft_freqs) / max(right - center, 1e-8)))
    return filters


_FILTERS = mel_filterbank()
_WINDOW = np.hanning(FRAME_LENGTH).astype(np.float32)


def log_mel(samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Return [mel, frames], matching the training and inference pipeline."""
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    if sample_rate != SAMPLE_RATE:
        raise ValueError(f"Expected {SAMPLE_RATE} Hz, received {sample_rate}")
    target_length = SAMPLE_RATE
    if len(audio) < target_length:
        audio = np.pad(audio, (target_length - len(audio), 0))
    elif len(audio) > target_length:
        audio = audio[-target_length:]
    frames = np.stack([audio[i:i + FRAME_LENGTH]
                       for i in range(0, target_length - FRAME_LENGTH + 1, FRAME_SHIFT)])
    spectrum = np.abs(np.fft.rfft(frames * _WINDOW, n=FFT_SIZE, axis=1)) ** 2
    mel = spectrum @ _FILTERS.T
    logmel = np.log(np.maximum(mel, 1e-8)).astype(np.float32)
    mean = float(logmel.mean())
    std = float(logmel.std())
    return np.clip((logmel - mean) / max(std, 1e-4), -5.0, 5.0).T
