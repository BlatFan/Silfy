from __future__ import annotations

import argparse
import queue
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

from voice_engine.detector import WakeWordDetector


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.88)
    parser.add_argument("--device", type=int, default=None)
    args = parser.parse_args()
    detector = WakeWordDetector(args.checkpoint, args.threshold)
    blocks: queue.Queue[np.ndarray] = queue.Queue(maxsize=32)

    def callback(indata, frames, time_info, status):
        if status:
            print(f"audio status: {status}")
        item = np.asarray(indata[:, 0], dtype=np.float32).copy()
        try:
            blocks.put_nowait(item)
        except queue.Full:
            try:
                blocks.get_nowait()
            except queue.Empty:
                pass
            try:
                blocks.put_nowait(item)
            except queue.Full:
                pass

    history = np.zeros(16000, dtype=np.float32)
    last_scan = 0.0
    cooldown_until = 0.0
    detections = 0
    durations: list[float] = []
    started = time.monotonic()
    print("Listening for 'Сильфи'. Ctrl+C to stop.")
    try:
        with sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=1600,
                            device=args.device, callback=callback):
            while True:
                try:
                    block = blocks.get(timeout=0.5)
                except queue.Empty:
                    continue
                history = np.concatenate((history[len(block):], block))
                now = time.monotonic()
                if now - last_scan < 0.2 or now < cooldown_until:
                    continue
                last_scan = now
                begin = time.perf_counter()
                score = detector.score(history)
                durations.append((time.perf_counter() - begin) * 1000)
                if score >= detector.threshold:
                    detections += 1
                    cooldown_until = now + 1.5
                    print(f"DETECTED score={score:.3f}")
    except KeyboardInterrupt:
        elapsed = max(0.001, time.monotonic() - started)
        rate = detections * 3600.0 / elapsed
        avg = float(np.mean(durations)) if durations else 0.0
        p95 = float(np.percentile(durations, 95)) if durations else 0.0
        print(f"duration={elapsed / 60:.2f} min; detections={detections}; false-activations/hour={rate:.3f}")
        print(f"KWS inference latency: mean={avg:.2f} ms; p95={p95:.2f} ms")


if __name__ == "__main__":
    main()
