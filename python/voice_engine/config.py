from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VoiceConfig:
    root: Path
    raw: dict[str, Any]

    @property
    def audio(self) -> dict[str, Any]:
        return self.raw.get("audio", {})

    @property
    def kws(self) -> dict[str, Any]:
        return self.raw.get("kws", {})

    @property
    def asr(self) -> dict[str, Any]:
        return self.raw.get("asr", {})

    @property
    def tts(self) -> dict[str, Any]:
        return self.raw.get("tts", {})

    def resolve(self, value: str | None) -> Path | None:
        if not value:
            return None
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return candidate.resolve()


def load_config() -> VoiceConfig:
    default_root = Path(__file__).resolve().parents[2]
    root = Path(os.environ.get("SILFY_ROOT", default_root)).resolve()
    config_path = Path(os.environ.get("SILFY_CONFIG", root / "config" / "voice.json"))
    if not config_path.is_absolute():
        config_path = root / config_path
    if not config_path.exists():
        example = root / "config" / "voice.example.json"
        if example.exists():
            raw = json.loads(example.read_text(encoding="utf-8"))
        else:
            raw = {}
    else:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    return VoiceConfig(root=root, raw=raw)
