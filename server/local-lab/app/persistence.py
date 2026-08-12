from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


def _encode(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__floodman_bytes_b64__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"__floodman_bytes_b64__"}:
            return base64.b64decode(value["__floodman_bytes_b64__"])
        return {str(key): _decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decode(item) for item in value]
    return value


class JsonStateFile:
    """Small atomic JSON state store used only by the Windows evaluation lab."""

    def __init__(self, directory: str | None = None, filename: str = "state.json") -> None:
        self.directory = Path(directory or os.getenv("LAB_STATE_DIR", "/data/lab-state"))
        self.path = self.directory / filename
        self.lock = threading.RLock()
        self.directory.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any] | None:
        with self.lock:
            if not self.path.exists():
                return None
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            decoded = _decode(raw)
            return decoded if isinstance(decoded, dict) else None

    def save(self, value: dict[str, Any]) -> None:
        encoded = _encode(value)
        data = json.dumps(encoded, indent=2, sort_keys=True, ensure_ascii=False)
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd, temporary_name = tempfile.mkstemp(prefix="state-", suffix=".json.tmp", dir=self.directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary_name, self.path)
            finally:
                try:
                    os.unlink(temporary_name)
                except FileNotFoundError:
                    pass
