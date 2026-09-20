from __future__ import annotations

import os
from dataclasses import dataclass

from flotilla_mcp.self_dev_mcp.tools import DEFAULT_TEST_TIMEOUT_SECONDS


@dataclass
class Settings:
    repo_remote: str
    github_token: str
    github_repo_full_name: str
    max_attempts: int
    test_timeout_seconds: float = DEFAULT_TEST_TIMEOUT_SECONDS


def load_settings() -> Settings:
    # SELF_DEV_GITHUB_TOKEN authenticates both the GitHub API client and git
    # (via the credential helper in git_ops, which reads it from the
    # environment at call time). It is deliberately separate from the
    # watcher's WATCHER_GITHUB_TOKEN.
    return Settings(
        repo_remote=os.environ["SELF_DEV_REPO_REMOTE"],
        github_token=os.environ["SELF_DEV_GITHUB_TOKEN"],
        github_repo_full_name=os.environ["GITHUB_REPO_FULL_NAME"],
        max_attempts=int(os.environ.get("SELF_DEV_MAX_ATTEMPTS", "5")),
        test_timeout_seconds=float(
            os.environ.get("SELF_DEV_TEST_TIMEOUT_SECONDS", str(DEFAULT_TEST_TIMEOUT_SECONDS))
        ),
    )
