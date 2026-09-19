import pytest

from services.common.manifest import FleetManifest
from services.self_dev_mcp.attempt_tracker import AttemptTracker, AttemptsExhaustedError
from services.self_dev_mcp import tools


def _manifest_with_protected_deploy_watcher(tmp_path):
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text(
        "services:\n"
        "  deploy-watcher:\n"
        "    path: services/deploy_watcher\n"
        "    protected: true\n"
    )
    return FleetManifest.load(str(manifest_path))


def test_write_file_refuses_protected_path(tmp_path):
    manifest = _manifest_with_protected_deploy_watcher(tmp_path)
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(tools.ProtectedPathError):
        tools.write_file(
            str(workspace),
            "services/deploy_watcher/deploy_manager.py",
            "malicious content",
            manifest,
            "issue-1",
            tracker,
        )

    assert not (workspace / "services" / "deploy_watcher" / "deploy_manager.py").exists()


def test_write_file_refuses_hardcoded_protected_path_even_with_permissive_manifest(tmp_path):
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text("services: {}")
    manifest = FleetManifest.load(str(manifest_path))
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(tools.ProtectedPathError):
        tools.write_file(str(workspace), "fleet_manifest.yaml", "services: {}", manifest, "issue-1", tracker)


def test_write_file_succeeds_for_unprotected_path(tmp_path):
    manifest = _manifest_with_protected_deploy_watcher(tmp_path)
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tools.write_file(str(workspace), "services/fixture_hello_mcp/server.py", "print('hi')", manifest, "issue-1", tracker)

    written = workspace / "services" / "fixture_hello_mcp" / "server.py"
    assert written.read_text() == "print('hi')"


def test_write_file_raises_once_attempts_exhausted(tmp_path):
    manifest = _manifest_with_protected_deploy_watcher(tmp_path)
    tracker = AttemptTracker(max_attempts=1)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tools.write_file(str(workspace), "a.py", "1", manifest, "issue-1", tracker)

    with pytest.raises(AttemptsExhaustedError):
        tools.write_file(str(workspace), "b.py", "2", manifest, "issue-1", tracker)


def test_read_file_returns_contents(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.py").write_text("hello")

    assert tools.read_file(str(workspace), "a.py") == "hello"


def test_run_local_tests_reports_failure_without_raising(tmp_path):
    workspace = tmp_path / "workspace"
    service_dir = workspace / "service"
    service_dir.mkdir(parents=True)
    (service_dir / "test_fail.py").write_text("def test_fail():\n    assert False\n")

    result = tools.run_local_tests(str(workspace), "service")

    assert result.returncode != 0
    assert "test_fail" in result.stdout
