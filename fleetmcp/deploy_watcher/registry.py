from __future__ import annotations

import os
import threading

from fleetmcp.deploy_watcher.json_store import read_json, write_json_atomic


class ServiceRegistry:
    """File-backed stand-in for the MCP gateway's routing table.

    A real gateway would expose an API for this; until it exists, the
    Deploy Watcher writes the active container name per service here, and
    a future gateway integration reads from this same file.
    """

    def __init__(self, registry_path: str):
        self._path = registry_path
        self._lock = threading.Lock()
        if not os.path.exists(self._path):
            self._write({})

    def set_active_container(self, service_name: str, container_name: str) -> None:
        with self._lock:
            data = self._read()
            data[service_name] = container_name
            self._write(data)

    def get_active_container(self, service_name: str) -> str | None:
        with self._lock:
            return self._read().get(service_name)

    def _read(self) -> dict:
        return read_json(self._path)

    def _write(self, data: dict) -> None:
        write_json_atomic(self._path, data)
