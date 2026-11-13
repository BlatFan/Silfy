from __future__ import annotations

import logging
import os
import sys
from typing import Any

from .config import load_config
from .engine import VoiceEngine
from .protocol import JsonLinesProtocol


def configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("SILFY_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def main() -> int:
    configure_logging()
    config = load_config()
    protocol: JsonLinesProtocol
    engine = VoiceEngine(config, lambda event, data: protocol.emit(event, data))

    def handle(command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command == "status":
            return engine.status()
        if command == "list_microphones":
            from .audio import MicrophoneCapture
            return {"devices": MicrophoneCapture.devices()}
        if command == "start_listening":
            return engine.start_listening()
        if command == "stop_listening":
            return engine.stop_listening()
        if command == "speak":
            return engine.speak(str(payload.get("text", "")))
        if command == "shutdown":
            engine.shutdown()
            return {"shuttingDown": True}
        raise ValueError(f"Unsupported command: {command}")

    protocol = JsonLinesProtocol(handle)
    protocol.emit("state", {"state": "idle", "version": "0.1.0"})
    try:
        return protocol.run()
    finally:
        engine.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
