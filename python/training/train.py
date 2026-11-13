from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from voice_engine.features import log_mel
from voice_engine.kws_model import WakeWordNet
from .audio_data import fixed_window, load_manifest, read_wav
from .augment import augment


class WakeDataset(Dataset):
    def __init__(self, rows: list[dict[str, str]], training: bool, noise_bank: list[np.ndarray]) -> None:
        self.rows = rows
        self.training = training
        self.noise_bank = noise_bank

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int):
        row = self.rows[index]
        rng = np.random.default_rng()
        samples = fixed_window(read_wav(Path(row["path"])), rng if self.training else None)
        if self.training:
            samples = augment(samples, rng, self.noise_bank)
        features = log_mel(samples)
        return torch.from_numpy(features[None, :, :]), torch.tensor(int(row["label"]), dtype=torch.long)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    train_rows = load_manifest(args.manifest, "train")
    val_rows = load_manifest(args.manifest, "validation")
    if not train_rows or not val_rows:
        raise SystemExit("Manifest must contain both train and validation samples")
    noise_bank = [fixed_window(read_wav(Path(row["path"]))) for row in train_rows if int(row["label"]) == 0]
    train_loader = DataLoader(WakeDataset(train_rows, True, noise_bank), batch_size=args.batch_size,
                              shuffle=True, num_workers=0)
    val_loader = DataLoader(WakeDataset(val_rows, False, []), batch_size=args.batch_size,
                            shuffle=False, num_workers=0)
    model = WakeWordNet()
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate)
    loss_fn = nn.CrossEntropyLoss()
    best_loss = float("inf")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss = 0.0
        train_count = 0
        for features, labels in train_loader:
            optimizer.zero_grad(set_to_none=True)
            logits = model(features)
            loss = loss_fn(logits, labels)
            loss.backward()
            optimizer.step()
            train_loss += float(loss.item()) * len(labels)
            train_count += len(labels)
        model.eval()
        val_loss = 0.0
        val_count = 0
        with torch.inference_mode():
            for features, labels in val_loader:
                loss = loss_fn(model(features), labels)
                val_loss += float(loss.item()) * len(labels)
                val_count += len(labels)
        train_loss /= max(1, train_count)
        val_loss /= max(1, val_count)
        print(f"epoch={epoch:03d} train_loss={train_loss:.4f} val_loss={val_loss:.4f}")
        if val_loss < best_loss:
            best_loss = val_loss
            torch.save({"model_state": model.state_dict(), "epoch": epoch,
                        "val_loss": val_loss, "classes": ["background", "wake"],
                        "feature": {"sample_rate": 16000, "mel_bins": 40, "window_samples": 16000}},
                       args.output)
    print(f"Best checkpoint: {args.output} (validation loss={best_loss:.4f})")


if __name__ == "__main__":
    main()
