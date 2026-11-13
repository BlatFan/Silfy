from __future__ import annotations

import argparse
from pathlib import Path

import torch

from voice_engine.kws_model import WakeWordNet


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    model = WakeWordNet()
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sample = torch.zeros((1, 1, 40, 98), dtype=torch.float32)
    torch.onnx.export(model, sample, args.output, input_names=["log_mel"],
                      output_names=["logits"], dynamic_axes={"log_mel": {0: "batch"},
                      "logits": {0: "batch"}}, opset_version=17)
    print(f"Exported {args.output}")


if __name__ == "__main__":
    main()
