from services.self_dev_mcp.config import load_settings


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
    import pytest

    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "git@example.com:org/repo.git")
    monkeypatch.delenv("SELF_DEV_GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "shared")
    monkeypatch.setenv("WATCHER_GITHUB_TOKEN", "watcher")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")

    with pytest.raises(KeyError):
        load_settings()
