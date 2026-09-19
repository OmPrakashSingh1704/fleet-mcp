from __future__ import annotations

import os
import subprocess

from services.common.manifest import FleetManifest
from services.self_dev_mcp.attempt_tracker import AttemptTracker, AttemptsExhaustedError


class ProtectedPathError(Exception):
    pass


def _resolve_inside_workspace(workspace_dir: str, relative_path: str) -> str:
    """Resolve and validate that relative_path stays within workspace_dir.

    Raises ProtectedPathError if:
    - The path is absolute
    - The path starts with / or \
    - The path has a drive letter (Windows)
    - The resolved path escapes the workspace root
    """
    # Reject absolute paths
    if os.path.isabs(relative_path):
        raise ProtectedPathError(f"refused to write absolute path: {relative_path}")

    # Reject paths starting with / or \
    if relative_path.startswith("/") or relative_path.startswith("\\"):
        raise ProtectedPathError(f"refused to write path starting with separator: {relative_path}")

    # Reject paths with drive letters (Windows: "C:" or "C:/")
    # splitdrive handles both "C:\x" and "C:/x" formats
    drive, _ = os.path.splitdrive(relative_path)
    if drive:
        raise ProtectedPathError(f"refused to write path with drive letter: {relative_path}")

    # Resolve both paths to their real forms
    target_path = os.path.realpath(os.path.join(workspace_dir, relative_path))
    workspace_root = os.path.realpath(workspace_dir)

    # Normalize for case-insensitive comparison on Windows
    target_normalized = os.path.normcase(target_path)
    workspace_normalized = os.path.normcase(workspace_root)

    # Check that target is within the workspace root
    try:
        common = os.path.commonpath([workspace_normalized, target_normalized])
    except ValueError:
        # Different drives on Windows
        raise ProtectedPathError(f"refused to write path on different drive: {relative_path}")

    if common != workspace_normalized:
        raise ProtectedPathError(f"refused to write path escaping workspace: {relative_path}")

    return target_path


def write_file(
    workspace_dir: str,
    relative_path: str,
    content: str,
    manifest: FleetManifest,
    issue_key: str,
    tracker: AttemptTracker,
) -> None:
    # Early exhaustion check for fast-fail on exhausted issues
    if tracker.is_exhausted(issue_key):
        raise AttemptsExhaustedError(f"attempt cap reached for {issue_key}")

    # Check manifest protection (does not consume an attempt if refused)
    if manifest.is_path_protected(relative_path):
        raise ProtectedPathError(f"refused to write protected path: {relative_path}")

    # Check workspace containment (does not consume an attempt if refused)
    target_path = _resolve_inside_workspace(workspace_dir, relative_path)

    # Atomically record attempt and check cap (authoritative gate)
    if not tracker.try_record_attempt(issue_key):
        raise AttemptsExhaustedError(f"attempt cap reached for {issue_key}")

    # Write to disk (only reached after all checks pass)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)


def read_file(workspace_dir: str, relative_path: str) -> str:
    # Validate that read stays within workspace
    target_path = _resolve_inside_workspace(workspace_dir, relative_path)
    with open(target_path, "r", encoding="utf-8") as f:
        return f.read()


def run_local_tests(workspace_dir: str, service_relative_path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python", "-m", "pytest", service_relative_path, "-v"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
    )
