from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    repo_remote: str
    github_token: str
    github_repo_full_name: str
    max_attempts: int


def load_settings() -> Settings:
    return Settings(
        repo_remote=os.environ["SELF_DEV_REPO_REMOTE"],
        github_token=os.environ["GITHUB_TOKEN"],
        github_repo_full_name=os.environ["GITHUB_REPO_FULL_NAME"],
        max_attempts=int(os.environ.get("SELF_DEV_MAX_ATTEMPTS", "5")),
    )
