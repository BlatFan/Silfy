from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .audio_data import read_wav


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    rows = []
    speakers = set()
    for speaker_dir in sorted(p for p in args.input.iterdir() if p.is_dir()):
        speaker = speaker_dir.name
        speakers.add(speaker)
        for label_name, label in (("background", 0), ("wake", 1)):
            folder = speaker_dir / label_name
            if not folder.exists():
                continue
            for path in sorted(folder.glob("*.wav")):
                read_wav(path)  # validate file decodes before adding it
                rows.append({"path": str(path.resolve()), "label": label,
                             "speaker_id": speaker})
    if len(speakers) < 3:
        raise SystemExit("Need at least 3 different speaker IDs for speaker-disjoint train/validation/test split")
    ordered = sorted(speakers, key=lambda name: hashlib.sha256(f"{args.seed}:{name}".encode()).hexdigest())
    n = len(ordered)
    train_n = max(1, int(n * 0.70))
    val_n = max(1, int(n * 0.15))
    if train_n + val_n >= n:
        train_n = n - 2
        val_n = 1
    split_by_speaker = {}
    for index, speaker in enumerate(ordered):
        split = "train" if index < train_n else "validation" if index < train_n + val_n else "test"
        split_by_speaker[speaker] = split
    for split in ("train", "validation", "test"):
        labels = {row["label"] for row in rows if split_by_speaker[row["speaker_id"]] == split}
        if labels != {0, 1}:
            raise SystemExit(f"Split '{split}' must contain both wake and background clips; found labels={sorted(labels)}")
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = args.output / "manifest.jsonl"
    with manifest.open("w", encoding="utf-8") as file:
        for row in rows:
            row["split"] = split_by_speaker[row["speaker_id"]]
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    summary = {split: sum(1 for row in rows if split_by_speaker[row["speaker_id"]] == split)
               for split in ("train", "validation", "test")}
    (args.output / "split.json").write_text(json.dumps({"seed": args.seed,
        "speakerSplit": split_by_speaker, "counts": summary}, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} records to {manifest}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
