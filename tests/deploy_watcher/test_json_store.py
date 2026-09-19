import json
import os

import pytest

from services.deploy_watcher import json_store
from services.deploy_watcher.json_store import read_json, write_json_atomic


def test_write_json_atomic_writes_and_reads_back(tmp_path):
    path = str(tmp_path / "data.json")

    write_json_atomic(path, {"a": 1})

    assert read_json(path) == {"a": 1}


def test_write_json_atomic_overwrites_existing_file(tmp_path):
    path = str(tmp_path / "data.json")
    write_json_atomic(path, {"a": 1})

    write_json_atomic(path, {"a": 2})

    assert read_json(path) == {"a": 2}


def test_failed_write_leaves_original_file_intact_and_no_stray_temp_file(tmp_path, monkeypatch):
    path = str(tmp_path / "data.json")
    write_json_atomic(path, {"a": 1})

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated crash mid-write")

    monkeypatch.setattr(json_store.json, "dump", _boom)

    with pytest.raises(RuntimeError):
        write_json_atomic(path, {"a": 2})

    # Original file must still be intact -- never truncated or corrupted.
    assert read_json(path) == {"a": 1}

    # No stray temp file should be left behind in the directory.
    remaining = os.listdir(tmp_path)
    assert remaining == ["data.json"]
