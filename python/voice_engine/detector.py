from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .features import log_mel
from .kws_model import WakeWordNet

log = logging.getLogger("silfy.kws")


class WakeWordDetector:
    def __init__(self, checkpoint: Path, threshold: float) -> None:
        if not checkpoint.is_file():
            raise FileNotFoundError(f"KWS checkpoint not found: {checkpoint}")
        import torch
        self._torch = torch
        self._model = WakeWordNet()
        data = torch.load(checkpoint, map_location="cpu", weights_only=True)
        state = data.get("model_state", data)
        self._model.load_state_dict(state)
        self._model.eval()
        self.threshold = min(max(float(threshold), 0.01), 0.999)

    def score(self, samples: np.ndarray) -> float:
        features = log_mel(samples)
        tensor = self._torch.from_numpy(features[None, None, :, :])
        with self._torch.inference_mode():
            logits = self._model(tensor)
            probability = self._torch.softmax(logits, dim=-1)[0, 1]
        return float(probability.item())

    def detect(self, samples: np.ndarray) -> bool:
        return self.score(samples) >= self.threshold
