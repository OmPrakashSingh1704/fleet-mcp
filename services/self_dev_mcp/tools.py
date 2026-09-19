from __future__ import annotations

import os
import subprocess

from services.common.manifest import FleetManifest, canonicalize_path
from services.self_dev_mcp.attempt_tracker import AttemptTracker, AttemptsExhaustedError

DEFAULT_TEST_TIMEOUT_SECONDS = 600.0

# Environment variables stripped from the run_tests subprocess. This is
# hygiene, NOT a security boundary: the test code runs as the same OS user as
# the server and can still recover the token (e.g. from /proc/<pid>/environ).
# See SECURITY.md#known-limitations.
_TEST_ENV_DENYLIST = ("SELF_DEV_GITHUB_TOKEN", "WATCHER_GITHUB_TOKEN", "GITHUB_TOKEN")


class ProtectedPathError(Exception):
    pass


def _has_git_component(path: str) -> bool:
    """True if any canonicalized component of ``path`` is ``.git``.

    Git's own metadata directory (config, hooks, refs, ...) must never be
    readable or writable through the tools: a written ``.git/config`` can
    redirect a push onto main or run code via ``core.fsmonitor``, a written
    ``.git/hooks/*`` runs code on commit/push, and a read ``.git/config``
    exposes the remote.
    """
    return any(part == ".git" for part in canonicalize_path(path).split("/"))


def _validate_workspace_path(
    workspace_dir: str,
    relative_path: str,
    manifest: FleetManifest | None = None,
) -> str:
    """Validate ``relative_path`` against the workspace and return the resolved target.

    Raises ProtectedPathError if:
    - the path is absolute, starts with a separator, or has a drive letter;
    - any component is ``.git`` (case-insensitive, Windows-canonicalized) --
      checked on the raw path AND on the resolved target's path relative to
      the resolved workspace root;
    - the resolved target escapes the workspace root;
    - ``manifest`` is given and either the raw path or the resolved
      (symlink/junction-followed) relative path is protected.
    """
    if os.path.isabs(relative_path):
        raise ProtectedPathError(f"refused absolute path: {relative_path!r}")

    if relative_path.startswith("/") or relative_path.startswith("\\"):
        raise ProtectedPathError(f"refused path starting with separator: {relative_path!r}")

    # splitdrive handles both "C:\x" and "C:/x" (and "C:x") formats
    drive, _ = os.path.splitdrive(relative_path)
    if drive:
        raise ProtectedPathError(f"refused path with drive letter: {relative_path!r}")

    if _has_git_component(relative_path):
        raise ProtectedPathError(f"refused git metadata path: {relative_path!r}")

    if manifest is not None and manifest.is_path_protected(relative_path):
        raise ProtectedPathError(f"refused protected path: {relative_path!r}")

    target_path = os.path.realpath(os.path.join(workspace_dir, relative_path))
    workspace_root = os.path.realpath(workspace_dir)

    target_normalized = os.path.normcase(target_path)
    workspace_normalized = os.path.normcase(workspace_root)

    try:
        common = os.path.commonpath([workspace_normalized, target_normalized])
    except ValueError:
        # Different drives on Windows
        raise ProtectedPathError(f"refused path on different drive: {relative_path!r}")

    if common != workspace_normalized:
        raise ProtectedPathError(f"refused path escaping workspace: {relative_path!r}")

    # The lexical checks above see only the path as typed. A symlink or
    # junction inside the workspace (e.g. innocent -> services/deploy_watcher)
    # makes the real target differ, so re-check what will actually be touched.
    resolved_relative = os.path.relpath(target_path, workspace_root).replace("\\", "/")
    if _has_git_component(resolved_relative):
        raise ProtectedPathError(f"refused git metadata path: {relative_path!r}")
    if manifest is not None and manifest.is_path_protected(resolved_relative):
        raise ProtectedPathError(f"refused protected path (resolved): {relative_path!r}")

    return target_path


# Backwards-compatible name: containment + .git checks, no manifest check.
def _resolve_inside_workspace(workspace_dir: str, relative_path: str) -> str:
    return _validate_workspace_path(workspace_dir, relative_path)


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

    # Protection + containment checks (a refusal does not consume an attempt)
    target_path = _validate_workspace_path(workspace_dir, relative_path, manifest)

    # Atomically record attempt and check cap (authoritative gate)
    if not tracker.try_record_attempt(issue_key):
        raise AttemptsExhaustedError(f"attempt cap reached for {issue_key}")

    # Write to disk (only reached after all checks pass)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)


def read_file(workspace_dir: str, relative_path: str) -> str:
    target_path = _validate_workspace_path(workspace_dir, relative_path)
    with open(target_path, "r", encoding="utf-8") as f:
        return f.read()


def validate_test_path(workspace_dir: str, service_relative_path: str) -> None:
    """Refuse a run_tests path that pytest could read as an option, that
    touches .git, or that escapes the workspace."""
    if service_relative_path.startswith("-"):
        raise ProtectedPathError(f"refused option-like test path: {service_relative_path!r}")
    _validate_workspace_path(workspace_dir, service_relative_path)


def run_local_tests(
    workspace_dir: str,
    service_relative_path: str,
    timeout_seconds: float = DEFAULT_TEST_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess:
    """Run pytest on ``service_relative_path`` inside the workspace.

    ``--`` ends option parsing so the path can never be read as a pytest
    flag. Raises subprocess.TimeoutExpired after ``timeout_seconds``.
    """
    env = {k: v for k, v in os.environ.items() if k not in _TEST_ENV_DENYLIST}
    return subprocess.run(
        ["python", "-m", "pytest", "--", service_relative_path],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
    )
