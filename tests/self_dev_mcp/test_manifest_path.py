import logging
import subprocess

from flotilla_mcp.self_dev_mcp import server


def test_manifest_path_defaults_to_cwd_file(monkeypatch):
    monkeypatch.delenv("FLEET_MANIFEST_PATH", raising=False)
    assert server.manifest_path() == "fleet_manifest.yaml"


def test_manifest_path_honors_env(monkeypatch, tmp_path):
    p = tmp_path / "m.yaml"
    monkeypatch.setenv("FLEET_MANIFEST_PATH", str(p))
    assert server.manifest_path() == str(p)


def test_manifest_path_honors_env_even_when_missing(monkeypatch, tmp_path):
    # An explicit FLEET_MANIFEST_PATH is returned as-is, whether or not the
    # file exists -- an explicit path that's missing is a hard error, not a
    # fallback to another location.
    p = tmp_path / "does-not-exist.yaml"
    monkeypatch.setenv("FLEET_MANIFEST_PATH", str(p))
    assert server.manifest_path() == str(p)


def _init_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    return repo_dir


def test_manifest_path_falls_back_to_repo_root_when_not_in_cwd(monkeypatch, tmp_path):
    repo_dir = _init_repo(tmp_path)
    (repo_dir / "fleet_manifest.yaml").write_text("services: {}\n")
    subdir = repo_dir / "sub"
    subdir.mkdir()
    monkeypatch.chdir(subdir)
    monkeypatch.delenv("FLEET_MANIFEST_PATH", raising=False)

    resolved = server.manifest_path()

    import os

    assert os.path.abspath(resolved) == os.path.abspath(repo_dir / "fleet_manifest.yaml")


def test_manifest_path_returns_none_when_nothing_found(monkeypatch, tmp_path):
    repo_dir = _init_repo(tmp_path)
    monkeypatch.chdir(repo_dir)
    monkeypatch.delenv("FLEET_MANIFEST_PATH", raising=False)

    assert server.manifest_path() is None


def test_manifest_path_returns_none_outside_a_git_repo_with_no_cwd_file(monkeypatch, tmp_path):
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()
    monkeypatch.chdir(not_a_repo)
    monkeypatch.delenv("FLEET_MANIFEST_PATH", raising=False)

    assert server.manifest_path() is None


# --- _load_manifest(): empty-manifest fallback + warning ---


def test_load_manifest_returns_empty_manifest_and_warns_when_nothing_found(monkeypatch, tmp_path, caplog):
    repo_dir = _init_repo(tmp_path)
    monkeypatch.chdir(repo_dir)
    monkeypatch.delenv("FLEET_MANIFEST_PATH", raising=False)

    with caplog.at_level(logging.WARNING, logger="flotilla_mcp.self_dev_mcp.server"):
        manifest = server._load_manifest()

    assert manifest.all_services() == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "fleet_manifest.yaml" in message
    assert "no services are declared" in message or "nothing in the target repo is service-protected" in message


def test_load_manifest_loads_existing_file_without_warning(monkeypatch, tmp_path, caplog):
    manifest_file = tmp_path / "fleet_manifest.yaml"
    manifest_file.write_text(
        "services:\n  demo:\n    path: demo\n", encoding="utf-8"
    )
    monkeypatch.setenv("FLEET_MANIFEST_PATH", str(manifest_file))

    with caplog.at_level(logging.WARNING, logger="flotilla_mcp.self_dev_mcp.server"):
        manifest = server._load_manifest()

    assert [s.name for s in manifest.all_services()] == ["demo"]
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_load_manifest_explicit_but_missing_path_is_a_hard_error(monkeypatch, tmp_path):
    import pytest

    missing = tmp_path / "does-not-exist.yaml"
    monkeypatch.setenv("FLEET_MANIFEST_PATH", str(missing))

    with pytest.raises(FileNotFoundError):
        server._load_manifest()


# --- Built-in protections still hold under an empty manifest ---


def test_empty_manifest_still_protects_builtin_paths():
    from flotilla_mcp.common.manifest import ALWAYS_PROTECTED_PATHS, ALWAYS_PROTECTED_PREFIXES, FleetManifest

    manifest = FleetManifest({})

    for path in ALWAYS_PROTECTED_PATHS:
        assert manifest.is_path_protected(path), path
    for prefix in ALWAYS_PROTECTED_PREFIXES:
        assert manifest.is_path_protected(prefix + "some_file.py"), prefix

    # .. escapes are refused independent of manifest content.
    assert manifest.is_path_protected("../escape.py")
    assert manifest.is_path_protected("sub/../../escape.py")


def test_empty_manifest_write_file_still_refuses_git_and_absolute_and_escape(tmp_path):
    # .git metadata, absolute paths, and workspace escapes are refused by
    # tools._validate_workspace_path independent of manifest content -- an
    # empty manifest (no services declared) must not weaken any of these.
    from flotilla_mcp.common.manifest import FleetManifest
    from flotilla_mcp.self_dev_mcp.attempt_tracker import AttemptTracker
    from flotilla_mcp.self_dev_mcp.tools import ProtectedPathError, write_file

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = FleetManifest({})
    tracker = AttemptTracker(max_attempts=5)

    import pytest

    with pytest.raises(ProtectedPathError):
        write_file(str(workspace), ".git/config", "x", manifest, "1", tracker)
    with pytest.raises(ProtectedPathError):
        write_file(str(workspace), str(tmp_path / "outside.py"), "x", manifest, "1", tracker)
    with pytest.raises(ProtectedPathError):
        write_file(str(workspace), "../escape.py", "x", manifest, "1", tracker)
    with pytest.raises(ProtectedPathError):
        write_file(str(workspace), "fleet_manifest.yaml", "x", manifest, "1", tracker)


def test_empty_manifest_does_not_protect_arbitrary_paths():
    from flotilla_mcp.common.manifest import FleetManifest

    manifest = FleetManifest({})

    assert not manifest.is_path_protected("some_service/app.py")
