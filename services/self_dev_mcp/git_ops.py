from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading

TOKEN_ENV_VAR = "SELF_DEV_GITHUB_TOKEN"

# A git credential helper that reads the token from the environment at call
# time. The token value itself never appears in argv, in a URL, in
# .git/config or in logs -- only the *name* of the variable does. The empty
# credential.helper that precedes it clears every inherited helper (system,
# global, and anything planted in the repo's .git/config).
CREDENTIAL_HELPER = (
    '!f() { echo username=x-access-token; echo "password=$' + TOKEN_ENV_VAR + '"; }; f'
)

_URL_USERINFO_RE = re.compile(r"(?P<scheme>\b[a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s@]+@")

_hooks_dir_lock = threading.Lock()
_hooks_dir: str | None = None


class GitOpsError(Exception):
    pass


def _empty_hooks_dir() -> str:
    """An empty directory, created once per process, used as core.hooksPath.

    Pointing core.hooksPath at an empty directory disables every hook,
    including any planted in .git/hooks. (/dev/null is not portable to Git
    for Windows; an empty temp dir works on both Windows and Linux.)
    """
    global _hooks_dir
    with _hooks_dir_lock:
        if _hooks_dir is None or not os.path.isdir(_hooks_dir):
            _hooks_dir = tempfile.mkdtemp(prefix="selfdev-nohooks-")
        return _hooks_dir


def _safety_config() -> list[str]:
    return [
        "-c", f"core.hooksPath={_empty_hooks_dir()}",
        "-c", "core.fsmonitor=false",
        "-c", "credential.helper=",
        "-c", f"credential.helper={CREDENTIAL_HELPER}",
    ]


def _redact(message: str, extra_secrets: tuple[str, ...] = ()) -> str:
    """Remove the remote URL, the token and any URL userinfo from ``message``."""
    for secret in (*extra_secrets, os.environ.get("SELF_DEV_REPO_REMOTE", "")):
        if secret:
            message = message.replace(secret, "<remote>")
    token = os.environ.get(TOKEN_ENV_VAR, "")
    if token:
        message = message.replace(token, "<redacted>")
    return _URL_USERINFO_RE.sub(r"\g<scheme>", message)


def _run_git(args: list[str], cwd: str | None = None, redact: tuple[str, ...] = ()) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(
        ["git", *_safety_config(), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise GitOpsError(_redact(f"git {' '.join(args)} failed: {result.stderr}", redact))
    return result.stdout.strip()


def clone(remote_url: str, dest_dir: str) -> None:
    _run_git(["clone", "--", remote_url, dest_dir], redact=(remote_url,))
    _run_git(["config", "user.email", "self-dev-mcp@fleet.local"], cwd=dest_dir)
    _run_git(["config", "user.name", "self-dev-mcp"], cwd=dest_dir)


def create_branch(repo_dir: str, branch_name: str) -> None:
    _run_git(["checkout", "-b", branch_name], cwd=repo_dir)


def commit_all(repo_dir: str, message: str) -> str:
    _run_git(["add", "-A"], cwd=repo_dir)
    _run_git(["commit", "-m", message], cwd=repo_dir)
    return _run_git(["rev-parse", "HEAD"], cwd=repo_dir)


def push(repo_dir: str, branch_name: str) -> None:
    # Fully explicit refspec with no "+": a remote.origin.push (or
    # push.default) setting can't redirect this onto another ref, and it can
    # never force-push.
    refspec = f"refs/heads/{branch_name}:refs/heads/{branch_name}"
    _run_git(["push", "-u", "origin", refspec], cwd=repo_dir)


def current_commit_sha(repo_dir: str) -> str:
    return _run_git(["rev-parse", "HEAD"], cwd=repo_dir)


def remote_branch_exists(repo_dir: str, branch_name: str) -> bool:
    output = _run_git(["ls-remote", "--heads", "origin", f"refs/heads/{branch_name}"], cwd=repo_dir)
    return bool(output.strip())


def checkout_remote_branch(repo_dir: str, branch_name: str) -> None:
    _run_git(["checkout", "-b", branch_name, "--track", f"origin/{branch_name}"], cwd=repo_dir)
