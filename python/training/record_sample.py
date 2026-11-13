from __future__ import annotations

import argparse
import wave
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sounddevice as sd


def main() -> None:
    parser = argparse.ArgumentParser(description="Record consented wake/background samples")
    parser.add_argument("--output", type=Path, default=Path("data/raw"))
    parser.add_argument("--speaker", required=True, help="Pseudonymous speaker ID, not a real name")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seconds", type=float, default=1.5)
    args = parser.parse_args()
    if args.count < 1 or not 0.25 <= args.seconds <= 5:
        parser.error("count must be positive and seconds must be in [0.25, 5]")
    print("Record only your own voice or voices with explicit consent.")
    speaker_dir = args.output / args.speaker
    for label in ("wake", "background"):
        (speaker_dir / label).mkdir(parents=True, exist_ok=True)
    for index in range(args.count):
        label = input(f"Sample {index + 1}/{args.count}: type [w]ake or [b]ackground (q=quit): ").strip().lower()
        if label == "q":
            break
        if label not in {"w", "b"}:
            print("Please enter w, b or q")
            continue
        prompt = "Say: Сильфи" if label == "w" else "Say an unrelated phrase or capture background noise"
        input(prompt + " — press Enter to record")
        audio = sd.rec(int(args.seconds * 16000), samplerate=16000, channels=1, dtype="float32")
        sd.wait()
        pcm = np.clip(audio[:, 0] * 32767.0, -32768, 32767).astype("<i2")
        now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = speaker_dir / ("wake" if label == "w" else "background") / f"{args.speaker}_{now}.wav"
        with wave.open(str(target), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(pcm.tobytes())
        print(f"Saved {target}")


if __name__ == "__main__":
    main()
