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

    assert not (workspace / "fleet_manifest.yaml").exists()


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


def test_write_file_refuses_absolute_path(tmp_path):
    """Test that absolute paths are rejected."""
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text("services: {}")
    manifest = FleetManifest.load(str(manifest_path))
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    outside_path = str(tmp_path / "outside" / "x.txt")

    with pytest.raises(tools.ProtectedPathError):
        tools.write_file(workspace, outside_path, "malicious", manifest, "issue-1", tracker)

    assert not (tmp_path / "outside" / "x.txt").exists()


def test_write_file_refuses_leading_slash_path(tmp_path):
    """Test that paths starting with / are rejected."""
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text("services: {}")
    manifest = FleetManifest.load(str(manifest_path))
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(tools.ProtectedPathError):
        tools.write_file(workspace, "/x.txt", "malicious", manifest, "issue-1", tracker)


def test_write_file_refuses_dotdot_escape(tmp_path):
    """Test that .. escapes are rejected."""
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text("services: {}")
    manifest = FleetManifest.load(str(manifest_path))
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(tools.ProtectedPathError):
        tools.write_file(workspace, "../outside.txt", "malicious", manifest, "issue-1", tracker)

    assert not (tmp_path / "outside.txt").exists()


def test_read_file_refuses_absolute_path(tmp_path):
    """Test that read_file rejects absolute paths."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret")

    with pytest.raises(tools.ProtectedPathError):
        tools.read_file(str(workspace), str(outside_file))


def test_refused_path_does_not_consume_attempt(tmp_path):
    """Test that refused paths (protected or escaping) don't consume attempts."""
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text("services: {}")
    manifest = FleetManifest.load(str(manifest_path))
    tracker = AttemptTracker(max_attempts=1)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # First write: try to escape but fail (attempt not consumed)
    with pytest.raises(tools.ProtectedPathError):
        tools.write_file(workspace, "../outside.txt", "malicious", manifest, "issue-1", tracker)

    # Second write: should succeed because the failed attempt wasn't consumed
    tools.write_file(workspace, "legit.txt", "content", manifest, "issue-1", tracker)

    assert (workspace / "legit.txt").read_text() == "content"
