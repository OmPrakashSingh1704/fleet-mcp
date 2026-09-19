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
