from services.self_dev_mcp.config import load_settings


def test_load_settings_reads_env(monkeypatch):
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "git@example.com:org/repo.git")
    monkeypatch.setenv("GITHUB_TOKEN", "token-123")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")
    monkeypatch.delenv("SELF_DEV_MAX_ATTEMPTS", raising=False)

    settings = load_settings()

    assert settings.repo_remote == "git@example.com:org/repo.git"
    assert settings.github_token == "token-123"
    assert settings.github_repo_full_name == "org/repo"
    assert settings.max_attempts == 5


def test_load_settings_respects_max_attempts_override(monkeypatch):
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "git@example.com:org/repo.git")
    monkeypatch.setenv("GITHUB_TOKEN", "token-123")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")
    monkeypatch.setenv("SELF_DEV_MAX_ATTEMPTS", "3")

    settings = load_settings()

    assert settings.max_attempts == 3
