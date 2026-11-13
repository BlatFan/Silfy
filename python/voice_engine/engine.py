from __future__ import annotations

import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .audio import MicrophoneCapture
from .config import VoiceConfig
from .detector import WakeWordDetector
from .speech import SherpaStreamingAsr, SherpaOfflineTts

log = logging.getLogger("silfy.engine")


class VoiceEngine:
    def __init__(self, config: VoiceConfig, emit: Callable[[str, dict[str, Any]], None]) -> None:
        self.config = config
        self.emit = emit
        self.state = "idle"
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._speaking = threading.Event()
        self._worker: threading.Thread | None = None
        self._capture: MicrophoneCapture | None = None
        self._last_error: str | None = None
        self._detector: WakeWordDetector | None = None
        self._asr: SherpaStreamingAsr | None = None
        self._tts: SherpaOfflineTts | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"state": self.state, "lastError": self._last_error,
                    "microphone": self._capture is not None,
                    "models": {"kws": self._detector is not None,
                               "asr": self._asr is not None,
                               "tts": self._tts is not None}}

    def _set_state(self, state: str, **extra: Any) -> None:
        with self._lock:
            self.state = state
        self.emit("state", {"state": state, **extra})

    def start_listening(self) -> dict[str, Any]:
        with self._lock:
            if self._worker and self._worker.is_alive():
                return self.status()
        kws_path = self.config.resolve(self.config.kws.get("checkpoint"))
        if kws_path is None:
            raise ValueError("kws.checkpoint is not configured")
        asr_cfg = dict(self.config.asr)
        for key in ("tokens", "encoder", "decoder", "joiner"):
            path = self.config.resolve(asr_cfg.get(key))
            asr_cfg[key] = str(path) if path else ""
        detector = WakeWordDetector(kws_path, float(self.config.kws.get("threshold", 0.88)))
        asr = SherpaStreamingAsr(asr_cfg)
        audio_cfg = self.config.audio
        capture = MicrophoneCapture(
            sample_rate=int(audio_cfg.get("sampleRate", 16000)),
            block_size=int(audio_cfg.get("blockSize", 1600)),
            device=audio_cfg.get("device"),
            capacity=int(audio_cfg.get("queueCapacity", 32)),
        )
        capture.start()
        with self._lock:
            self._detector = detector
            self._asr = asr
            self._capture = capture
            self._stop.clear()
            self._last_error = None
            self._worker = threading.Thread(target=self._listen_loop, name="SilfyAudioWorker", daemon=True)
            self._worker.start()
        self._set_state("listening")
        return self.status()

    def _listen_loop(self) -> None:
        assert self._capture and self._detector and self._asr
        sample_rate = int(self.config.audio.get("sampleRate", 16000))
        if sample_rate != 16000:
            self._fail("This KWS/ASR model configuration requires a 16 kHz capture stream")
            return
        window_len = int(float(self.config.kws.get("windowSeconds", 1.0)) * sample_rate)
        scan_interval = max(0.05, float(self.config.kws.get("scanIntervalSeconds", 0.2)))
        cooldown = max(0.5, float(self.config.kws.get("cooldownSeconds", 1.5)))
        ring: deque[np.ndarray] = deque(maxlen=max(1, int(np.ceil(window_len / self._capture.block_size))))
        active = False
        last_scan = 0.0
        last_wake = 0.0
        try:
            while not self._stop.is_set():
                try:
                    block = self._capture.read(timeout=0.5)
                except Exception:
                    continue
                if self._speaking.is_set():
                    # Do not feed the assistant's own TTS output back into KWS/ASR.
                    ring.clear()
                    active = False
                    continue
                ring.append(block)
                if active:
                    result = self._asr.accept(block)
                    if result:
                        self.emit("recognized", {"text": result})
                        self._set_state("listening")
                        active = False
                    continue
                now = time.monotonic()
                if now - last_scan < scan_interval or now - last_wake < cooldown:
                    continue
                if sum(len(x) for x in ring) < window_len:
                    continue
                audio = np.concatenate(list(ring))[-window_len:]
                last_scan = now
                score = self._detector.score(audio)
                if score >= self._detector.threshold:
                    last_wake = now
                    active = True
                    self._set_state("thinking", wakeScore=round(score, 4))
                    self.emit("wake_detected", {"score": round(score, 4)})
                    self._asr.stream = self._asr.recognizer.create_stream()
                    # A short tail of the wake phrase may be present; ASR endpointing will decide when speech ends.
        except Exception as exc:
            log.exception("Audio worker failed")
            self._fail(str(exc))
        finally:
            self._close_capture()

    def _fail(self, message: str) -> None:
        with self._lock:
            self._last_error = message
        self.emit("error", {"message": message})
        self._set_state("error")

    def _close_capture(self) -> None:
        capture, self._capture = self._capture, None
        if capture is not None:
            capture.close()

    def stop_listening(self) -> dict[str, Any]:
        self._stop.set()
        worker = self._worker
        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=3.0)
        self._close_capture()
        self._worker = None
        self._set_state("idle")
        return self.status()

    def speak(self, text: str) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Text must not be empty")
        tts_cfg = dict(self.config.tts)
        model = self.config.resolve(tts_cfg.get("model"))
        tokens = self.config.resolve(tts_cfg.get("tokens"))
        lexicon = self.config.resolve(tts_cfg.get("lexicon")) if tts_cfg.get("lexicon") else None
        tts_cfg["model"] = str(model) if model else ""
        tts_cfg["tokens"] = str(tokens) if tokens else ""
        tts_cfg["lexicon"] = str(lexicon) if lexicon else ""
        if self._tts is None:
            self._tts = SherpaOfflineTts(tts_cfg)
        self._speaking.set()
        self._set_state("speaking")
        try:
            self._tts.speak(text[:2000])
        finally:
            self._speaking.clear()
            self._set_state("listening" if self._worker and self._worker.is_alive() else "idle")
        return {"spoken": True}

    def shutdown(self) -> None:
        self.stop_listening()
