import subprocess

from services.self_dev_mcp import git_ops


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
