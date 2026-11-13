from __future__ import annotations

import logging
import queue
from typing import Any

import numpy as np
import sounddevice as sd

log = logging.getLogger("silfy.audio")


class MicrophoneCapture:
    def __init__(self, sample_rate: int = 16000, block_size: int = 1600,
                 device: int | None = None, capacity: int = 32) -> None:
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.device = device
        self.queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=max(4, capacity))
        self._stream: Any = None
        self.dropped_blocks = 0

    def _callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            log.warning("Audio callback status: %s", status)
        block = np.asarray(indata[:, 0], dtype=np.float32).copy()
        try:
            self.queue.put_nowait(block)
        except queue.Full:
            self.dropped_blocks += 1
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self.queue.put_nowait(block)
            except queue.Full:
                self.dropped_blocks += 1

    def start(self) -> None:
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.block_size,
            channels=1,
            dtype="float32",
            device=self.device,
            callback=self._callback,
        )
        self._stream.start()

    def read(self, timeout: float = 1.0) -> np.ndarray:
        return self.queue.get(timeout=timeout)

    def close(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()

    @staticmethod
    def devices() -> list[dict[str, Any]]:
        rows = []
        for index, item in enumerate(sd.query_devices()):
            if int(item.get("max_input_channels", 0)) > 0:
                rows.append({"index": index, "name": item["name"],
                             "channels": item["max_input_channels"],
                             "defaultSampleRate": item["default_samplerate"]})
        return rows
