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
