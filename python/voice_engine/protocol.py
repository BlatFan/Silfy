from __future__ import annotations

import json
import logging
import sys
import threading
import uuid
from typing import Any, Callable

log = logging.getLogger("silfy.protocol")


class JsonLinesProtocol:
    """One JSON object per stdin line; stdout is reserved for protocol messages."""

    def __init__(self, handler: Callable[[str, dict[str, Any]], dict[str, Any]],
                 event_source: Any | None = None) -> None:
        self._handler = handler
        self._write_lock = threading.Lock()
        self._event_source = event_source

    def write(self, message: dict[str, Any]) -> None:
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            sys.stdout.write(encoded + "\n")
            sys.stdout.flush()

    def emit(self, event: str, data: dict[str, Any]) -> None:
        self.write({"type": "event", "event": event, "data": data})

    def run(self) -> int:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            request_id = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("Request must be a JSON object")
                request_id = request.get("id") or str(uuid.uuid4())
                command = request.get("command")
                payload = request.get("payload", {})
                if not isinstance(command, str) or not isinstance(payload, dict):
                    raise ValueError("Fields 'command' and 'payload' have invalid types")
                data = self._handler(command, payload)
                self.write({"type": "response", "id": request_id, "ok": True, "data": data})
                if command == "shutdown":
                    return 0
            except Exception as exc:  # protocol boundary: return an error, keep process alive
                log.exception("IPC request failed")
                self.write({"type": "response", "id": request_id, "ok": False,
                            "error": {"code": type(exc).__name__, "message": str(exc)}})
        return 0
