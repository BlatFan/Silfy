from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd

log = logging.getLogger("silfy.speech")


class SherpaStreamingAsr:
    def __init__(self, config: dict[str, Any]) -> None:
        import sherpa_onnx
        required = ("tokens", "encoder", "decoder", "joiner")
        paths = {name: Path(str(config.get(name, ""))).expanduser() for name in required}
        missing = [name for name, path in paths.items() if not path.is_file()]
        if missing:
            raise FileNotFoundError("ASR model files missing: " + ", ".join(missing))
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(paths["tokens"]), encoder=str(paths["encoder"]),
            decoder=str(paths["decoder"]), joiner=str(paths["joiner"]),
            num_threads=max(1, int(config.get("numThreads", 2))),
            sample_rate=int(config.get("sampleRate", 16000)),
            feature_dim=int(config.get("featureDim", 80)),
            enable_endpoint_detection=True,
        )
        self.stream = self.recognizer.create_stream()

    def accept(self, samples: np.ndarray) -> str | None:
        self.stream.accept_waveform(16000, samples.astype(np.float32, copy=False))
        while self.recognizer.is_ready(self.stream):
            self.recognizer.decode_stream(self.stream)
        if self.recognizer.is_endpoint(self.stream):
            result = self.recognizer.get_result_all(self.stream)
            text = str(result.text).strip()
            self.recognizer.reset(self.stream)
            return text or None
        return None


class SherpaOfflineTts:
    def __init__(self, config: dict[str, Any]) -> None:
        import sherpa_onnx
        model = Path(str(config.get("model", ""))).expanduser()
        tokens = Path(str(config.get("tokens", ""))).expanduser()
        if not model.is_file() or not tokens.is_file():
            raise FileNotFoundError("TTS VITS model or tokens.txt is missing")
        lexicon_value = str(config.get("lexicon", "")).strip()
        lexicon = Path(lexicon_value).expanduser() if lexicon_value else None
        model_config = sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(model), tokens=str(tokens),
                lexicon=str(lexicon) if lexicon and lexicon.is_file() else "",
            ),
            num_threads=max(1, int(config.get("numThreads", 2))),
        )
        tts_config = sherpa_onnx.OfflineTtsConfig(model=model_config, max_num_sentences=1)
        if not tts_config.validate():
            raise ValueError("Sherpa-ONNX TTS config validation failed")
        self.tts = sherpa_onnx.OfflineTts(tts_config)
        self.sid = max(0, int(config.get("speakerId", 0)))
        self.speed = min(max(float(config.get("speed", 1.0)), 0.6), 1.5)
        self.volume = min(max(float(config.get("volume", 0.85)), 0.0), 1.0)

    def speak(self, text: str) -> None:
        import sherpa_onnx
        normalized = text.replace("Сильфи", "Си́льфи").replace("сильфи", "си́льфи")
        generation = sherpa_onnx.GenerationConfig()
        generation.sid = self.sid
        generation.speed = self.speed
        audio = self.tts.generate(normalized, generation)
        if len(audio.samples) == 0:
            raise RuntimeError("TTS returned empty audio")
        samples = np.asarray(audio.samples, dtype=np.float32) * self.volume
        sd.play(samples, samplerate=int(audio.sample_rate), blocking=True)
