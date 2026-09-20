import subprocess

from flotilla_mcp.self_dev_mcp import git_ops


def _init_bare_remote(tmp_path) -> str:
    remote_dir = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote_dir)], check=True, capture_output=True)

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    subprocess.run(["git", "init"], cwd=seed_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "seed@example.com"], cwd=seed_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Seed"], cwd=seed_dir, check=True)
    (seed_dir / "README.md").write_text("seed")
    subprocess.run(["git", "add", "-A"], cwd=seed_dir, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=seed_dir, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=seed_dir, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote_dir)], cwd=seed_dir, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=seed_dir, check=True, capture_output=True)
    return str(remote_dir)


def test_clone_branch_commit_push_round_trip(tmp_path):
    remote_url = _init_bare_remote(tmp_path)
    workspace = tmp_path / "workspace"

    git_ops.clone(remote_url, str(workspace))
    git_ops.create_branch(str(workspace), "selfdev/issue-1")
    (workspace / "new_file.txt").write_text("hello")
    sha = git_ops.commit_all(str(workspace), "add new_file")
    git_ops.push(str(workspace), "selfdev/issue-1")

    check_dir = tmp_path / "check"
    git_ops.clone(remote_url, str(check_dir))
    subprocess.run(["git", "checkout", "selfdev/issue-1"], cwd=check_dir, check=True, capture_output=True)
    assert (check_dir / "new_file.txt").read_text() == "hello"
    assert git_ops.current_commit_sha(str(check_dir)) == sha


def test_commit_all_raises_on_empty_commit(tmp_path):
    remote_url = _init_bare_remote(tmp_path)
    workspace = tmp_path / "workspace"
    git_ops.clone(remote_url, str(workspace))

    import pytest
    with pytest.raises(git_ops.GitOpsError):
        git_ops.commit_all(str(workspace), "nothing changed")


def test_clone_raises_git_ops_error_on_invalid_url(tmp_path):
    import pytest
    workspace = tmp_path / "workspace"
    with pytest.raises(git_ops.GitOpsError):
        git_ops.clone("git://invalid-url-that-does-not-exist.git", str(workspace))


def test_remote_branch_exists_false_before_push_true_after(tmp_path):
    remote_url = _init_bare_remote(tmp_path)
    workspace = tmp_path / "workspace"
    git_ops.clone(remote_url, str(workspace))

    assert git_ops.remote_branch_exists(str(workspace), "selfdev/issue-1") is False

    git_ops.create_branch(str(workspace), "selfdev/issue-1")
    (workspace / "new_file.txt").write_text("hello")
    git_ops.commit_all(str(workspace), "add new_file")
    git_ops.push(str(workspace), "selfdev/issue-1")

    assert git_ops.remote_branch_exists(str(workspace), "selfdev/issue-1") is True


def test_followup_commit_round_trip_via_checkout_remote_branch(tmp_path):
    remote_url = _init_bare_remote(tmp_path)

    # First invocation: clone, branch, commit, push.
    first_workspace = tmp_path / "workspace-1"
    git_ops.clone(remote_url, str(first_workspace))
    git_ops.create_branch(str(first_workspace), "selfdev/issue-1")
    (first_workspace / "new_file.txt").write_text("hello")
    first_sha = git_ops.commit_all(str(first_workspace), "add new_file")
    git_ops.push(str(first_workspace), "selfdev/issue-1")

    # Second invocation (follow-up after review comments): fresh clone,
    # resume on the existing remote branch instead of branching off main.
    second_workspace = tmp_path / "workspace-2"
    git_ops.clone(remote_url, str(second_workspace))
    assert git_ops.remote_branch_exists(str(second_workspace), "selfdev/issue-1") is True
    git_ops.checkout_remote_branch(str(second_workspace), "selfdev/issue-1")

    # The first commit's file must already be present after resuming.
    assert (second_workspace / "new_file.txt").read_text() == "hello"

    (second_workspace / "another_file.txt").write_text("world")
    second_sha = git_ops.commit_all(str(second_workspace), "add another_file")
    git_ops.push(str(second_workspace), "selfdev/issue-1")

    # Verify-clone of the branch has both commits, in order, no force-push.
    check_dir = tmp_path / "check"
    git_ops.clone(remote_url, str(check_dir))
    subprocess.run(["git", "checkout", "selfdev/issue-1"], cwd=check_dir, check=True, capture_output=True)
    assert (check_dir / "new_file.txt").read_text() == "hello"
    assert (check_dir / "another_file.txt").read_text() == "world"
    assert git_ops.current_commit_sha(str(check_dir)) == second_sha

    parent_sha = subprocess.run(
        ["git", "rev-parse", "HEAD^"], cwd=check_dir, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert parent_sha == first_sha


# --- Final fix wave: C-1 (hooks/fsmonitor disabled, explicit refspec) and
# --- I-2 (credential helper, no token in argv, redaction) ---

import os  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402

SECRET = "ghp_SUPERSECRETTOKENVALUE123"


def _ok(*args, **kwargs):
    return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")


def _capture_git_calls(monkeypatch, fn):
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", SECRET)
    with patch("flotilla_mcp.self_dev_mcp.git_ops.subprocess.run", side_effect=_ok) as mock_run:
        fn()
    return mock_run.call_args_list


@pytest.mark.parametrize(
    "operation",
    [
        lambda: git_ops.clone("https://github.com/org/private.git", "/tmp/ws"),
        lambda: git_ops.push("/tmp/ws", "selfdev/issue-1"),
        lambda: git_ops.remote_branch_exists("/tmp/ws", "selfdev/issue-1"),
        lambda: git_ops.commit_all("/tmp/ws", "msg"),
    ],
    ids=["clone", "push", "ls-remote", "commit"],
)
def test_every_git_call_carries_safety_config_and_never_the_token(monkeypatch, operation):
    calls = _capture_git_calls(monkeypatch, operation)

    assert calls
    for call in calls:
        argv = call.args[0]
        joined = " ".join(argv)
        assert argv[0] == "git"
        # Hooks and fsmonitor disabled on every invocation.
        hooks_arg = next(a for a in argv if a.startswith("core.hooksPath="))
        assert os.path.isdir(hooks_arg.split("=", 1)[1])
        assert os.listdir(hooks_arg.split("=", 1)[1]) == []
        assert "core.fsmonitor=false" in argv
        # Inherited helpers cleared, then our env-reading helper installed.
        empty_idx = argv.index("credential.helper=")
        helper_idx = argv.index(f"credential.helper={git_ops.CREDENTIAL_HELPER}")
        assert empty_idx < helper_idx
        assert "$SELF_DEV_GITHUB_TOKEN" in git_ops.CREDENTIAL_HELPER
        # The token VALUE is never in argv; prompts are disabled.
        assert SECRET not in joined
        assert call.kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_push_uses_fully_explicit_non_forcing_refspec(monkeypatch):
    calls = _capture_git_calls(monkeypatch, lambda: git_ops.push("/tmp/ws", "selfdev/issue-7"))

    argv = calls[0].args[0]
    assert argv[-4:] == ["push", "-u", "origin", "refs/heads/selfdev/issue-7:refs/heads/selfdev/issue-7"]
    assert not any(a.startswith("+") for a in argv)


def test_git_ops_error_redacts_credentials_remote_and_token(monkeypatch):
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", SECRET)
    remote = f"https://user:{SECRET}@github.com/org/private.git"
    stderr = (
        f"fatal: unable to access '{remote}/': could not resolve host\n"
        f"also saw https://someone:hunter2@example.com/x and token {SECRET}"
    )

    def fail(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=128, stdout="", stderr=stderr)

    with patch("flotilla_mcp.self_dev_mcp.git_ops.subprocess.run", side_effect=fail):
        with pytest.raises(git_ops.GitOpsError) as exc_info:
            git_ops.clone(remote, "/tmp/ws")

    message = str(exc_info.value)
    assert SECRET not in message
    assert "hunter2" not in message
    assert "someone:" not in message
    assert "<remote>" in message
    assert "https://example.com/x" in message
    # The helper plumbing is not echoed into errors either.
    assert "credential.helper" not in message


def test_git_ops_error_redacts_configured_remote_on_non_clone_ops(monkeypatch):
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "https://github.com/org/private.git")

    def fail(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0], returncode=1, stdout="", stderr="fatal: 'https://github.com/org/private.git' denied"
        )

    with patch("flotilla_mcp.self_dev_mcp.git_ops.subprocess.run", side_effect=fail):
        with pytest.raises(git_ops.GitOpsError) as exc_info:
            git_ops.push("/tmp/ws", "selfdev/issue-1")

    assert "org/private" not in str(exc_info.value)


def test_real_clone_error_with_embedded_credentials_is_redacted(tmp_path):
    remote = "https://x-access-token:ghp_REALLOOKINGTOKEN@example.invalid/org/repo.git"

    with pytest.raises(git_ops.GitOpsError) as exc_info:
        git_ops.clone(remote, str(tmp_path / "ws"))

    assert "ghp_REALLOOKINGTOKEN" not in str(exc_info.value)


def test_clone_does_not_persist_token_or_helper_into_git_config(tmp_path, monkeypatch):
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", SECRET)
    remote_url = _init_bare_remote(tmp_path)
    workspace = tmp_path / "workspace"

    git_ops.clone(remote_url, str(workspace))

    config = (workspace / ".git" / "config").read_text()
    assert SECRET not in config
    assert "credential" not in config
    assert "hooksPath" not in config
