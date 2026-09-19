from __future__ import annotations

import json
import os
import tempfile


def read_json(path: str) -> dict:
    """Read a JSON object from ``path``."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path: str, data: dict) -> None:
    """Write ``data`` as JSON to ``path`` atomically.

    Writes to a temporary file in the same directory as ``path``, flushes it
    to disk, and then swaps it into place with ``os.replace``. This ensures
    a crash or interruption mid-write can never leave a truncated or
    partially-written file at ``path`` -- readers always see either the old
    complete content or the new complete content, never a mix of the two.
    """
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
