from __future__ import annotations

import os
import subprocess

from services.common.manifest import FleetManifest
from services.self_dev_mcp.attempt_tracker import AttemptTracker, AttemptsExhaustedError


class ProtectedPathError(Exception):
    pass


def write_file(
    workspace_dir: str,
    relative_path: str,
    content: str,
    manifest: FleetManifest,
    issue_key: str,
    tracker: AttemptTracker,
) -> None:
    if tracker.is_exhausted(issue_key):
        raise AttemptsExhaustedError(f"attempt cap reached for {issue_key}")
    if manifest.is_path_protected(relative_path):
        raise ProtectedPathError(f"refused to write protected path: {relative_path}")

    tracker.record_attempt(issue_key)
    target_path = os.path.join(workspace_dir, relative_path)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)


def read_file(workspace_dir: str, relative_path: str) -> str:
    target_path = os.path.join(workspace_dir, relative_path)
    with open(target_path, "r", encoding="utf-8") as f:
        return f.read()


def run_local_tests(workspace_dir: str, service_relative_path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python", "-m", "pytest", service_relative_path, "-v"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
    )
