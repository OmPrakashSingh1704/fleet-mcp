"""End-to-end proof of Cycle A's git/protection mechanics against a real
local git remote (a bare repo on disk, cloned/pushed to over the filesystem
transport -- no mocks, no network).

This is the "does the safety story survive contact with real git" test: it
proves that a protected-path write and a workspace-escaping write never
reach disk or a commit, while a legitimate write really does commit, push,
and round-trip through a second clone -- including the follow-up flow of
discovering and checking out an existing remote branch for a second commit.
"""

from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock

import pytest

from services.common.manifest import FleetManifest
from services.self_dev_mcp import git_ops
from services.self_dev_mcp.attempt_tracker import AttemptTracker
from services.self_dev_mcp.server import (
    ServerDependencies,
    handle_read_file,
    handle_start_issue,
    handle_submit_pr,
    handle_write_file,
)
from services.self_dev_mcp.tools import ProtectedPathError, write_file

MANIFEST_YAML = (
    "services:\n"
    "  deploy-watcher:\n"
    "    path: services/deploy_watcher\n"
    "    protected: true\n"
)

PROTECTED_RELATIVE_PATH = "services/deploy_watcher/deploy_manager.py"
PROTECTED_ORIGINAL_CONTENT = "# real deploy watcher code\n"
LEGITIMATE_RELATIVE_PATH = "services/fixture_hello_mcp/server.py"


def _run_git(args: list[str], cwd) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result


def _init_bare_remote_with_manifest(tmp_path) -> str:
    """Seed a real bare repo (the "GitHub remote") with a manifest that
    marks services/deploy_watcher protected, plus a file under it.
    """
    remote_dir = tmp_path / "remote.git"
    # Force the bare repo's default branch to "main" regardless of the
    # local git install's init.defaultBranch -- otherwise HEAD may point at
    # a "master" ref that's never created (we only ever push "main"),
    # leaving a plain `clone` with nothing checked out.
    _run_git(["init", "--bare", "-b", "main", str(remote_dir)], cwd=tmp_path)

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    _run_git(["init"], cwd=seed_dir)
    _run_git(["config", "user.email", "seed@example.com"], cwd=seed_dir)
    _run_git(["config", "user.name", "Seed"], cwd=seed_dir)
    (seed_dir / "fleet_manifest.yaml").write_text(MANIFEST_YAML)
    (seed_dir / "services" / "deploy_watcher").mkdir(parents=True)
    (seed_dir / "services" / "deploy_watcher" / "deploy_manager.py").write_text(PROTECTED_ORIGINAL_CONTENT)
    _run_git(["add", "-A"], cwd=seed_dir)
    _run_git(["commit", "-m", "seed"], cwd=seed_dir)
    _run_git(["branch", "-M", "main"], cwd=seed_dir)
    _run_git(["remote", "add", "origin", str(remote_dir)], cwd=seed_dir)
    _run_git(["push", "origin", "main"], cwd=seed_dir)
    return str(remote_dir)


def _checkout(repo_dir, branch_name: str) -> None:
    _run_git(["checkout", branch_name], cwd=repo_dir)


def _setup_remote_and_first_commit(tmp_path):
    """Clone, attempt (and refuse) malicious writes, make a legitimate write,
    commit, and push -- returning everything a follow-up flow needs.
    """
    remote_url = _init_bare_remote_with_manifest(tmp_path)

    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text(MANIFEST_YAML)
    manifest = FleetManifest.load(str(manifest_path))
    tracker = AttemptTracker(max_attempts=5)

    workspace = tmp_path / "workspace"
    git_ops.clone(remote_url, str(workspace))
    git_ops.create_branch(str(workspace), "selfdev/issue-1")

    protected_file = workspace / PROTECTED_RELATIVE_PATH

    # --- refusal 1: writing a protected path never lands on disk ---
    with pytest.raises(ProtectedPathError):
        write_file(
            str(workspace),
            PROTECTED_RELATIVE_PATH,
            "malicious change",
            manifest,
            "issue-1",
            tracker,
        )
    assert protected_file.read_text() == PROTECTED_ORIGINAL_CONTENT

    # --- refusal 2: a relative path that escapes the workspace never lands ---
    escape_target = tmp_path / "escape.txt"
    with pytest.raises(ProtectedPathError):
        write_file(
            str(workspace),
            "../escape.txt",
            "malicious escape",
            manifest,
            "issue-1",
            tracker,
        )
    assert not escape_target.exists()

    # --- refusal 3: an absolute path is refused outright, never lands ---
    absolute_target = tmp_path / "absolute_escape.txt"
    with pytest.raises(ProtectedPathError):
        write_file(
            str(workspace),
            str(absolute_target),
            "malicious absolute write",
            manifest,
            "issue-1",
            tracker,
        )
    assert not absolute_target.exists()

    # --- the legitimate write really does commit and push ---
    write_file(
        str(workspace),
        LEGITIMATE_RELATIVE_PATH,
        "# a real fix\n",
        manifest,
        "issue-1",
        tracker,
    )
    first_sha = git_ops.commit_all(str(workspace), "fix: patch fixture service")
    git_ops.push(str(workspace), "selfdev/issue-1")

    return remote_url, manifest, tracker, first_sha


def test_full_cycle_a_git_mechanics_including_protected_path_refusal(tmp_path):
    remote_url, _manifest, _tracker, first_sha = _setup_remote_and_first_commit(tmp_path)

    verify_dir = tmp_path / "verify"
    git_ops.clone(remote_url, str(verify_dir))
    _checkout(verify_dir, "selfdev/issue-1")

    assert (verify_dir / LEGITIMATE_RELATIVE_PATH).read_text() == "# a real fix\n"
    assert (verify_dir / PROTECTED_RELATIVE_PATH).read_text() == PROTECTED_ORIGINAL_CONTENT
    assert git_ops.current_commit_sha(str(verify_dir)) == first_sha


def test_followup_checkout_remote_branch_and_second_commit(tmp_path):
    remote_url, manifest, tracker, first_sha = _setup_remote_and_first_commit(tmp_path)

    # A fresh clone -- simulating a Self-Dev MCP restart / a second
    # invocation of start_issue for the same issue -- discovers the branch
    # already exists on the remote and resumes it instead of re-branching.
    fresh_workspace = tmp_path / "workspace2"
    git_ops.clone(remote_url, str(fresh_workspace))

    assert git_ops.remote_branch_exists(str(fresh_workspace), "selfdev/issue-1") is True

    git_ops.checkout_remote_branch(str(fresh_workspace), "selfdev/issue-1")

    write_file(
        str(fresh_workspace),
        "services/fixture_hello_mcp/second_file.py",
        "# a second real fix\n",
        manifest,
        "issue-1",
        tracker,
    )
    second_sha = git_ops.commit_all(str(fresh_workspace), "fix: second patch")
    git_ops.push(str(fresh_workspace), "selfdev/issue-1")

    verify_dir = tmp_path / "verify2"
    git_ops.clone(remote_url, str(verify_dir))
    _checkout(verify_dir, "selfdev/issue-1")

    assert (verify_dir / LEGITIMATE_RELATIVE_PATH).read_text() == "# a real fix\n"
    assert (verify_dir / "services" / "fixture_hello_mcp" / "second_file.py").read_text() == "# a second real fix\n"
    assert (verify_dir / PROTECTED_RELATIVE_PATH).read_text() == PROTECTED_ORIGINAL_CONTENT
    assert git_ops.current_commit_sha(str(verify_dir)) == second_sha

    parent_sha = _run_git(["rev-parse", f"{second_sha}^"], cwd=verify_dir).stdout.strip()
    assert parent_sha == first_sha


# --- Final fix wave: C-1 exploit reproduction against real git ---------------

MALICIOUS_PUSH_CONFIG = (
    '\n[remote "origin"]\n'
    "\tpush = +refs/heads/selfdev/issue-1:refs/heads/main\n"
)


def _main_sha(remote_url: str, tmp_path) -> str:
    out = _run_git(["ls-remote", remote_url, "refs/heads/main"], cwd=tmp_path).stdout
    return out.split()[0]


def _plant_hook(workspace, hook_name: str, marker) -> None:
    hook = workspace / ".git" / "hooks" / hook_name
    marker_posix = str(marker).replace("\\", "/")
    hook.write_text(f"#!/bin/sh\necho pwned > '{marker_posix}'\nexit 0\n", newline="\n")
    os.chmod(hook, 0o755)


def test_c1_exploit_through_tool_handlers_is_refused_and_main_is_unchanged(tmp_path):
    """The reviewer's C-1 reproduction, driven through the real MCP handlers:
    start_issue against a local bare remote, write_file('.git/config', <push
    refmap onto main>), then submit_pr. The write must be REFUSED and main
    must not move."""
    remote_url = _init_bare_remote_with_manifest(tmp_path)
    main_before = _main_sha(remote_url, tmp_path)
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text(MANIFEST_YAML)
    github_client = MagicMock()
    github_client.open_pr.return_value = MagicMock(number=1)
    deps = ServerDependencies(
        repo_remote=remote_url,
        manifest=FleetManifest.load(str(manifest_path)),
        tracker=AttemptTracker(max_attempts=5),
        github_client=github_client,
    )

    assert handle_start_issue(1, deps) == "selfdev/issue-1"
    workspace_dir = deps.workspaces["1"]
    config_before = open(os.path.join(workspace_dir, ".git", "config"), encoding="utf-8").read()

    for path in (".git/config", ".GIT/config", "sub/../.git/config", "./.git/config"):
        result = handle_write_file(1, path, config_before + MALICIOUS_PUSH_CONFIG, deps)
        assert result.startswith("REFUSED"), (path, result)
    assert handle_write_file(1, ".git/hooks/pre-push", "#!/bin/sh\ntouch /tmp/x\n", deps).startswith("REFUSED")
    assert handle_read_file(1, ".git/config", deps).startswith("REFUSED")
    assert open(os.path.join(workspace_dir, ".git", "config"), encoding="utf-8").read() == config_before

    assert handle_write_file(1, LEGITIMATE_RELATIVE_PATH, "# fix\n", deps) == "OK"
    assert handle_submit_pr(1, "fix", "body", deps) == "opened PR #1"

    assert _main_sha(remote_url, tmp_path) == main_before
    branch = _run_git(["ls-remote", remote_url, "refs/heads/selfdev/issue-1"], cwd=tmp_path).stdout
    assert branch.strip(), "selfdev/issue-1 was not pushed"


def test_c1_raw_malicious_config_and_hooks_cannot_move_main_or_run_code(tmp_path):
    """Defense in depth for any route that bypasses write_file (e.g. code run
    by run_tests): pre-seed .git/config with a push refmap onto main and an
    fsmonitor command, and plant executable hooks. commit_all + push must
    push only refs/heads/selfdev/issue-1, leave main unchanged, and run no
    hook or fsmonitor."""
    remote_url = _init_bare_remote_with_manifest(tmp_path)
    main_before = _main_sha(remote_url, tmp_path)

    workspace = tmp_path / "workspace"
    git_ops.clone(remote_url, str(workspace))
    git_ops.create_branch(str(workspace), "selfdev/issue-1")

    hook_markers = {name: tmp_path / f"{name}.marker" for name in ("pre-commit", "pre-push", "post-commit")}
    for name, marker in hook_markers.items():
        _plant_hook(workspace, name, marker)
    fsmonitor_marker = tmp_path / "fsmonitor.marker"
    fsmonitor_script = tmp_path / "fsmonitor.sh"
    fsmonitor_script.write_text(
        f"#!/bin/sh\necho pwned > '{str(fsmonitor_marker).replace(chr(92), '/')}'\n", newline="\n"
    )
    os.chmod(fsmonitor_script, 0o755)

    with open(workspace / ".git" / "config", "a", encoding="utf-8") as f:
        f.write(MALICIOUS_PUSH_CONFIG)
        f.write(f"[core]\n\tfsmonitor = {str(fsmonitor_script).replace(chr(92), '/')}\n")

    # Control: the planted hook really is runnable by plain git, so the
    # "marker not created" assertions below are meaningful.
    control = subprocess.run(
        ["git", "hook", "run", "pre-commit"], cwd=str(workspace), capture_output=True, text=True
    )
    assert control.returncode == 0, control.stderr
    assert hook_markers["pre-commit"].exists()
    hook_markers["pre-commit"].unlink()

    (workspace / "services" / "fixture_hello_mcp").mkdir(parents=True, exist_ok=True)
    (workspace / LEGITIMATE_RELATIVE_PATH).write_text("# fix\n")
    sha = git_ops.commit_all(str(workspace), "fix")
    git_ops.push(str(workspace), "selfdev/issue-1")

    assert _main_sha(remote_url, tmp_path) == main_before, "main moved: malicious push refmap was honored"
    branch_line = _run_git(["ls-remote", remote_url, "refs/heads/selfdev/issue-1"], cwd=tmp_path).stdout
    assert branch_line.split()[0] == sha
    for name, marker in hook_markers.items():
        assert not marker.exists(), f"{name} hook ran"
    assert not fsmonitor_marker.exists(), "fsmonitor command ran"
