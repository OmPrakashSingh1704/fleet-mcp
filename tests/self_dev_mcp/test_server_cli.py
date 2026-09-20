"""main()'s friendly first-run failure handling -- see RELEASING.md's
"friendly first-run failures" note and CHANGELOG's [Unreleased] entry.

A fresh `pip install flotilla-mcp` / `uvx flotilla-mcp` user with no manifest and no
env configured should get an actionable one/two-line stderr message and
exit 1, never a raw traceback out of site-packages.
"""
from __future__ import annotations

import pytest

from flotilla_mcp.self_dev_mcp import server

_REQUIRED_ENV = ("SELF_DEV_REPO_REMOTE", "SELF_DEV_GITHUB_TOKEN", "GITHUB_REPO_FULL_NAME")


def _set_required_env(monkeypatch):
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "https://example.com/repo.git")
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "token-123")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")


def _clear_required_env(monkeypatch):
    for var in _REQUIRED_ENV:
        monkeypatch.delenv(var, raising=False)


def test_main_missing_manifest_exits_1_with_friendly_message(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FLEET_MANIFEST_PATH", raising=False)
    _set_required_env(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        server.main([])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "fleet_manifest.yaml" in err
    assert "FLEET_MANIFEST_PATH" in err
    assert "Traceback" not in err
    assert "File \"" not in err


def test_main_missing_env_var_exits_1_with_friendly_message(monkeypatch, tmp_path, capsys):
    manifest = tmp_path / "fleet_manifest.yaml"
    manifest.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setenv("FLEET_MANIFEST_PATH", str(manifest))
    _clear_required_env(monkeypatch)
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "https://example.com/repo.git")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")
    # SELF_DEV_GITHUB_TOKEN intentionally left unset.

    with pytest.raises(SystemExit) as exc:
        server.main([])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "SELF_DEV_GITHUB_TOKEN" in err
    assert "Traceback" not in err
    assert "File \"" not in err


def test_main_version_exits_0_with_no_env_and_no_manifest(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FLEET_MANIFEST_PATH", raising=False)
    _clear_required_env(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        server.main(["--version"])

    assert exc.value.code == 0


def test_main_help_exits_0_with_no_env_and_no_manifest(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FLEET_MANIFEST_PATH", raising=False)
    _clear_required_env(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        server.main(["--help"])

    assert exc.value.code == 0
    assert "Self-Dev MCP" in capsys.readouterr().out
