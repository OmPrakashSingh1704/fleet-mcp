from __future__ import annotations

import os
import threading

from flotilla_mcp.deploy_watcher.json_store import read_json, write_json_atomic


class KnownGoodStore:
    """Tracks the last successfully-deployed image tag per service.

    Never overwritten except by a subsequent successful deploy, which is
    what guarantees the "known-good floor" from the design spec.
    """

    def __init__(self, store_path: str):
        self._path = store_path
        self._lock = threading.Lock()
        if not os.path.exists(self._path):
            self._write({})

    def record(self, service_name: str, image_tag: str) -> None:
        with self._lock:
            data = self._read()
            data[service_name] = image_tag
            self._write(data)

    def get(self, service_name: str) -> str | None:
        with self._lock:
            return self._read().get(service_name)

    def _read(self) -> dict:
        return read_json(self._path)

    def _write(self, data: dict) -> None:
        write_json_atomic(self._path, data)
