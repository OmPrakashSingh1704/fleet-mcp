"""main()'s friendly first-run failure handling.

A fresh `pip install flotilla-mcp` / `uvx flotilla-mcp` user with no repo
remote detectable and no env configured should get an actionable one/two-line
stderr message and exit 1, never a raw traceback out of site-packages.
"""
from __future__ import annotations

import subprocess

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


def _init_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    return repo_dir


def test_main_explicit_manifest_path_missing_exits_1_with_friendly_message(monkeypatch, tmp_path, capsys):
    # An explicit FLEET_MANIFEST_PATH that doesn't exist stays a hard error
    # -- unlike the zero-config default, where no manifest anywhere just
    # means an empty one plus a warning.
    missing = tmp_path / "does-not-exist.yaml"
    monkeypatch.setenv("FLEET_MANIFEST_PATH", str(missing))
    _set_required_env(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        server.main([])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "fleet_manifest.yaml" in err or str(missing) in err
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


def test_main_undetectable_repo_remote_exits_1_with_friendly_message(monkeypatch, tmp_path, capsys):
    # Zero-config startup: SELF_DEV_REPO_REMOTE unset, and not inside a git
    # repo with an origin remote to detect one from.
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()
    monkeypatch.chdir(not_a_repo)
    _clear_required_env(monkeypatch)
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "token-123")

    with pytest.raises(SystemExit) as exc:
        server.main([])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "SELF_DEV_REPO_REMOTE" in err
    assert "origin" in err
    assert "Traceback" not in err
    assert "File \"" not in err


def test_main_detects_repo_remote_and_only_fails_on_manifest(monkeypatch, tmp_path, capsys):
    # With only SELF_DEV_GITHUB_TOKEN set, inside a git repo with an origin
    # remote, config validation succeeds -- the run only fails later, on an
    # explicit-but-missing manifest, proving detection kicked in.
    repo_dir = _init_repo(tmp_path)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/octocat/hello-world.git"],
        cwd=repo_dir, check=True, capture_output=True,
    )
    monkeypatch.chdir(repo_dir)
    _clear_required_env(monkeypatch)
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "token-123")
    monkeypatch.setenv("FLEET_MANIFEST_PATH", str(tmp_path / "does-not-exist.yaml"))

    with pytest.raises(SystemExit) as exc:
        server.main([])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    # Got past config validation (no "missing environment variable" /
    # "could not detect a git repository remote" message) straight to the
    # manifest error.
    assert "SELF_DEV_REPO_REMOTE" not in err
    assert "fleet_manifest.yaml" in err or "does-not-exist.yaml" in err


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


# --- Program name derivation (section 5): messages match the invoked command ---


def test_prog_name_falls_back_to_flotilla_mcp_when_argv0_empty(monkeypatch):
    monkeypatch.setattr(server.sys, "argv", [""])
    assert server._prog_name() == "flotilla-mcp"


def test_prog_name_derived_from_self_dev_alias(monkeypatch):
    monkeypatch.setattr(server.sys, "argv", ["/usr/local/bin/flotilla-self-dev"])
    assert server._prog_name() == "flotilla-self-dev"


def test_prog_name_derived_from_mcp_alias(monkeypatch):
    monkeypatch.setattr(server.sys, "argv", ["/usr/local/bin/flotilla-mcp"])
    assert server._prog_name() == "flotilla-mcp"


def test_prog_name_strips_windows_exe_suffix(monkeypatch):
    monkeypatch.setattr(server.sys, "argv", ["C:\\Users\\me\\AppData\\flotilla-mcp.EXE"])
    assert server._prog_name() == "flotilla-mcp"


@pytest.mark.parametrize(
    "argv0, expected",
    [
        ("/usr/local/bin/flotilla-self-dev", "flotilla-self-dev"),
        ("C:\\venv\\Scripts\\flotilla-mcp.exe", "flotilla-mcp"),
        ("flotilla-mcp", "flotilla-mcp"),
        ("", "flotilla-mcp"),
    ],
)
def test_prog_name_handles_both_separators_on_any_platform(monkeypatch, argv0, expected):
    # A Windows-style argv[0] has to resolve on POSIX too: os.path.basename is
    # platform-dependent and returned the whole string on Linux, which CI caught.
    monkeypatch.setattr(server.sys, "argv", [argv0])
    assert server._prog_name() == expected


def test_main_missing_env_var_message_uses_invoked_prog_name(monkeypatch, tmp_path, capsys):
    manifest = tmp_path / "fleet_manifest.yaml"
    manifest.write_text("services: {}\n", encoding="utf-8")
    monkeypatch.setenv("FLEET_MANIFEST_PATH", str(manifest))
    _clear_required_env(monkeypatch)
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "https://example.com/repo.git")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")
    monkeypatch.setattr(server.sys, "argv", ["/usr/local/bin/flotilla-mcp"])

    with pytest.raises(SystemExit):
        server.main([])

    err = capsys.readouterr().err
    assert err.startswith("flotilla-mcp:")


def test_main_undetectable_repo_remote_message_uses_invoked_prog_name(monkeypatch, tmp_path, capsys):
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()
    monkeypatch.chdir(not_a_repo)
    _clear_required_env(monkeypatch)
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "token-123")
    monkeypatch.setattr(server.sys, "argv", ["/usr/local/bin/flotilla-self-dev"])

    with pytest.raises(SystemExit):
        server.main([])

    err = capsys.readouterr().err
    assert err.startswith("flotilla-self-dev:")


def test_parse_args_prog_matches_invoked_command(monkeypatch, capsys):
    monkeypatch.setattr(server.sys, "argv", ["/usr/local/bin/flotilla-mcp"])

    with pytest.raises(SystemExit):
        server._parse_args(["--version"])

    out = capsys.readouterr().out
    assert out.startswith("flotilla-mcp ")
