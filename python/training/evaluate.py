from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch

from voice_engine.features import log_mel
from voice_engine.kws_model import WakeWordNet
from .audio_data import fixed_window, load_manifest, read_wav


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--split", choices=["train", "validation", "test"], default="test")
    parser.add_argument("--threshold", type=float, default=0.85)
    args = parser.parse_args()
    data = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    model = WakeWordNet()
    model.load_state_dict(data["model_state"])
    model.eval()
    tp = fp = tn = fn = 0
    negative_seconds = 0.0
    with torch.inference_mode():
        for row in load_manifest(args.manifest, args.split):
            samples = fixed_window(read_wav(Path(row["path"])))
            if int(row["label"]) == 0:
                negative_seconds += len(samples) / 16000
            features = log_mel(samples)
            logits = model(torch.from_numpy(features[None, None, :, :]))
            score = float(torch.softmax(logits, dim=-1)[0, 1])
            predicted = score >= args.threshold
            actual = int(row["label"]) == 1
            if predicted and actual: tp += 1
            elif predicted and not actual: fp += 1
            elif not predicted and not actual: tn += 1
            else: fn += 1
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    far = fp / max(1, fp + tn)
    frr = fn / max(1, fn + tp)
    false_accepts_per_hour = fp / max(negative_seconds / 3600.0, 1e-9)
    print(f"split={args.split} threshold={args.threshold:.3f}")
    print(f"TP={tp} FP={fp} TN={tn} FN={fn}")
    print(f"precision={precision:.4f} recall={recall:.4f} FAR={far:.4f} FRR={frr:.4f}")
    print(f"clip-duration-estimated false accepts/hour={false_accepts_per_hour:.4f}")
    print("Note: continuous background recording is required for a real false-activations/hour measurement.")


if __name__ == "__main__":
    main()
