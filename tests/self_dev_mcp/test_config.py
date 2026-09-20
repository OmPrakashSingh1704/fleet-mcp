import subprocess

import pytest

from flotilla_mcp.self_dev_mcp.config import RepoRemoteNotFoundError, load_settings


def test_load_settings_reads_env(monkeypatch):
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "git@example.com:org/repo.git")
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "token-123")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")
    monkeypatch.delenv("SELF_DEV_MAX_ATTEMPTS", raising=False)

    settings = load_settings()

    assert settings.repo_remote == "git@example.com:org/repo.git"
    assert settings.github_token == "token-123"
    assert settings.github_repo_full_name == "org/repo"
    assert settings.max_attempts == 5


def test_load_settings_respects_max_attempts_override(monkeypatch):
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "git@example.com:org/repo.git")
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "token-123")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")
    monkeypatch.setenv("SELF_DEV_MAX_ATTEMPTS", "3")

    settings = load_settings()

    assert settings.max_attempts == 3


def test_load_settings_test_timeout_default_and_override(monkeypatch):
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "git@example.com:org/repo.git")
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "token-123")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")
    monkeypatch.delenv("SELF_DEV_TEST_TIMEOUT_SECONDS", raising=False)
    assert load_settings().test_timeout_seconds == 600.0

    monkeypatch.setenv("SELF_DEV_TEST_TIMEOUT_SECONDS", "42")
    assert load_settings().test_timeout_seconds == 42.0


def test_load_settings_does_not_fall_back_to_shared_github_token(monkeypatch):
    # Token split: self-dev must never silently pick up the old shared
    # GITHUB_TOKEN (or the watcher's token).
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "git@example.com:org/repo.git")
    monkeypatch.delenv("SELF_DEV_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "shared")
    monkeypatch.setenv("WATCHER_GITHUB_TOKEN", "watcher")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")

    with pytest.raises(KeyError):
        load_settings()


# --- Zero-config startup: SELF_DEV_REPO_REMOTE / GITHUB_REPO_FULL_NAME detection ---


def _init_repo_with_origin(tmp_path, url):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", url], cwd=repo_dir, check=True, capture_output=True)
    return repo_dir


def test_load_settings_detects_repo_remote_and_full_name_when_unset(tmp_path, monkeypatch):
    repo_dir = _init_repo_with_origin(tmp_path, "https://github.com/octocat/hello-world.git")
    monkeypatch.chdir(repo_dir)
    monkeypatch.delenv("SELF_DEV_REPO_REMOTE", raising=False)
    monkeypatch.delenv("GITHUB_REPO_FULL_NAME", raising=False)
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "token-123")

    settings = load_settings()

    assert settings.repo_remote == "https://github.com/octocat/hello-world.git"
    assert settings.github_repo_full_name == "octocat/hello-world"


def test_load_settings_explicit_env_overrides_detection(tmp_path, monkeypatch):
    repo_dir = _init_repo_with_origin(tmp_path, "https://github.com/octocat/hello-world.git")
    monkeypatch.chdir(repo_dir)
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "https://github.com/someone-else/other-repo.git")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "someone-else/other-repo")
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "token-123")

    settings = load_settings()

    assert settings.repo_remote == "https://github.com/someone-else/other-repo.git"
    assert settings.github_repo_full_name == "someone-else/other-repo"


def test_load_settings_non_github_remote_yields_none_full_name(tmp_path, monkeypatch):
    repo_dir = _init_repo_with_origin(tmp_path, "https://gitlab.com/octocat/hello-world.git")
    monkeypatch.chdir(repo_dir)
    monkeypatch.delenv("SELF_DEV_REPO_REMOTE", raising=False)
    monkeypatch.delenv("GITHUB_REPO_FULL_NAME", raising=False)
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "token-123")

    settings = load_settings()

    assert settings.repo_remote == "https://gitlab.com/octocat/hello-world.git"
    assert settings.github_repo_full_name is None


def test_load_settings_raises_repo_remote_not_found_outside_a_git_repo(tmp_path, monkeypatch):
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()
    monkeypatch.chdir(not_a_repo)
    monkeypatch.delenv("SELF_DEV_REPO_REMOTE", raising=False)
    monkeypatch.delenv("GITHUB_REPO_FULL_NAME", raising=False)
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "token-123")

    with pytest.raises(RepoRemoteNotFoundError):
        load_settings()


def test_load_settings_still_requires_github_token_even_with_detection_available(tmp_path, monkeypatch):
    repo_dir = _init_repo_with_origin(tmp_path, "https://github.com/octocat/hello-world.git")
    monkeypatch.chdir(repo_dir)
    monkeypatch.delenv("SELF_DEV_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("SELF_DEV_REPO_REMOTE", raising=False)
    monkeypatch.delenv("GITHUB_REPO_FULL_NAME", raising=False)

    with pytest.raises(KeyError):
        load_settings()
