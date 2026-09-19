from __future__ import annotations

import subprocess


class GitOpsError(Exception):
    pass


def _run_git(args: list[str], cwd: str | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GitOpsError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def clone(remote_url: str, dest_dir: str) -> None:
    _run_git(["clone", remote_url, dest_dir])
    _run_git(["config", "user.email", "self-dev-mcp@fleet.local"], cwd=dest_dir)
    _run_git(["config", "user.name", "self-dev-mcp"], cwd=dest_dir)


def create_branch(repo_dir: str, branch_name: str) -> None:
    _run_git(["checkout", "-b", branch_name], cwd=repo_dir)


def commit_all(repo_dir: str, message: str) -> str:
    _run_git(["add", "-A"], cwd=repo_dir)
    _run_git(["commit", "-m", message], cwd=repo_dir)
    return _run_git(["rev-parse", "HEAD"], cwd=repo_dir)


def push(repo_dir: str, branch_name: str) -> None:
    _run_git(["push", "-u", "origin", branch_name], cwd=repo_dir)


def current_commit_sha(repo_dir: str) -> str:
    return _run_git(["rev-parse", "HEAD"], cwd=repo_dir)


def remote_branch_exists(repo_dir: str, branch_name: str) -> bool:
    output = _run_git(["ls-remote", "--heads", "origin", branch_name], cwd=repo_dir)
    return bool(output.strip())


def checkout_remote_branch(repo_dir: str, branch_name: str) -> None:
    _run_git(["checkout", "-b", branch_name, "--track", f"origin/{branch_name}"], cwd=repo_dir)
