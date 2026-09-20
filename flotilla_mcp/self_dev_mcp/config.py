from __future__ import annotations

import os
from dataclasses import dataclass

from flotilla_mcp.self_dev_mcp.repo_detect import detect_remote_url, parse_github_full_name
from flotilla_mcp.self_dev_mcp.tools import DEFAULT_TEST_TIMEOUT_SECONDS


class RepoRemoteNotFoundError(Exception):
    """SELF_DEV_REPO_REMOTE is unset and no ``origin`` remote could be detected."""


@dataclass
class Settings:
    repo_remote: str
    github_token: str
    github_repo_full_name: str | None
    max_attempts: int
    test_timeout_seconds: float = DEFAULT_TEST_TIMEOUT_SECONDS


def load_settings() -> Settings:
    # SELF_DEV_GITHUB_TOKEN authenticates both the GitHub API client and git
    # (via the credential helper in git_ops, which reads it from the
    # environment at call time). It is deliberately separate from the
    # watcher's WATCHER_GITHUB_TOKEN. It stays required: there is nothing to
    # detect it from.
    github_token = os.environ["SELF_DEV_GITHUB_TOKEN"]

    # SELF_DEV_REPO_REMOTE, when unset, is detected from the `origin` remote
    # of the git repo the server is started in -- this is what makes
    # zero-config startup possible: only the token is truly required.
    repo_remote = os.environ.get("SELF_DEV_REPO_REMOTE") or detect_remote_url()
    if not repo_remote:
        raise RepoRemoteNotFoundError(
            "could not detect a git repository remote; run inside a git "
            "repository with an 'origin' remote, or set SELF_DEV_REPO_REMOTE"
        )

    # GITHUB_REPO_FULL_NAME, when unset, is parsed from the (possibly
    # detected) remote URL. A non-GitHub remote (or a local path) yields
    # None -- the server still starts, but GitHub-backed tools return an
    # explanatory error instead of guessing wrong.
    github_repo_full_name = os.environ.get("GITHUB_REPO_FULL_NAME") or parse_github_full_name(repo_remote)

    return Settings(
        repo_remote=repo_remote,
        github_token=github_token,
        github_repo_full_name=github_repo_full_name,
        max_attempts=int(os.environ.get("SELF_DEV_MAX_ATTEMPTS", "5")),
        test_timeout_seconds=float(
            os.environ.get("SELF_DEV_TEST_TIMEOUT_SECONDS", str(DEFAULT_TEST_TIMEOUT_SECONDS))
        ),
    )
