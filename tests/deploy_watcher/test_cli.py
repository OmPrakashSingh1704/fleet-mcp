import builtins
import sys

import pytest

from fleetmcp.deploy_watcher import cli


def test_cli_without_docker_exits_with_extra_hint(monkeypatch, capsys):
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "docker" or name.startswith("docker."):
            raise ModuleNotFoundError("No module named 'docker'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    for m in [m for m in sys.modules if m == "docker" or m.startswith("docker.")]:
        monkeypatch.delitem(sys.modules, m)
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
    assert 'pip install "fleetmcp[watcher]"' in capsys.readouterr().err


def test_cli_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "Deploy Watcher" in capsys.readouterr().out


def test_cli_version_exits_0_with_no_env(monkeypatch, capsys):
    for var in ("WATCHER_GITHUB_TOKEN", "GITHUB_REPO_FULL_NAME", "REPO_REMOTE"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])

    assert exc.value.code == 0


def test_cli_missing_env_var_exits_1_with_friendly_message(monkeypatch, capsys):
    # docker is importable in this dev/test environment (it's a direct
    # requirements.txt dependency for the deploy_watcher test suite), so
    # main() proceeds past the missing-Docker-SDK branch into run(), whose
    # very first statements read the three required env vars.
    for var in ("WATCHER_GITHUB_TOKEN", "GITHUB_REPO_FULL_NAME", "REPO_REMOTE"):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(SystemExit) as exc:
        cli.main([])

    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "WATCHER_GITHUB_TOKEN" in err
    assert "Traceback" not in err
    assert "File \"" not in err
