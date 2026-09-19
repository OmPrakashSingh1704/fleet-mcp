import os
import sys

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


# --- Final fix wave: C-1 .git is never readable/writable through the tools ---

GIT_METADATA_PATHS = [
    ".git/config",
    ".git/hooks/pre-commit",
    ".GIT/config",
    "sub/../.git/config",
    "./.git/x",
    ".git",
    ".Git/HEAD",
    "services/.git/config",
    ".git./config",
    ".git /config",
    ".git::$INDEX_ALLOCATION/config",
    ".git\\config",
]


def _seed_git_dir(workspace):
    (workspace / ".git" / "hooks").mkdir(parents=True)
    (workspace / ".git" / "config").write_text("[core]\n")


@pytest.mark.parametrize("git_path", GIT_METADATA_PATHS)
def test_write_file_refuses_git_metadata(tmp_path, git_path):
    manifest = _manifest_with_protected_deploy_watcher(tmp_path)
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_git_dir(workspace)

    with pytest.raises(tools.ProtectedPathError):
        tools.write_file(str(workspace), git_path, "[remote \"origin\"]\n", manifest, "issue-1", tracker)

    assert (workspace / ".git" / "config").read_text() == "[core]\n"
    assert not (workspace / ".git" / "hooks" / "pre-commit").exists()
    assert not tracker.is_exhausted("issue-1")


@pytest.mark.parametrize("git_path", GIT_METADATA_PATHS)
def test_read_file_refuses_git_metadata(tmp_path, git_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_git_dir(workspace)

    with pytest.raises(tools.ProtectedPathError):
        tools.read_file(str(workspace), git_path)


@pytest.mark.parametrize("git_path", GIT_METADATA_PATHS)
def test_validate_test_path_refuses_git_metadata(tmp_path, git_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_git_dir(workspace)

    with pytest.raises(tools.ProtectedPathError):
        tools.validate_test_path(str(workspace), git_path)


@pytest.mark.parametrize("ok_path", [".gitignore_extra", "docs/.github-notes.md", "a.git/x", "git/config"])
def test_git_like_but_not_git_dir_paths_are_allowed(tmp_path, ok_path):
    manifest = _manifest_with_protected_deploy_watcher(tmp_path)
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tools.write_file(str(workspace), ok_path, "x", manifest, "issue-1", tracker)

    assert (workspace / ok_path).read_text() == "x"


def test_validate_test_path_refuses_leading_dash(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(tools.ProtectedPathError):
        tools.validate_test_path(str(workspace), "--basetemp=.")


# --- Final fix wave: I-1 symlink / junction bypass ---


def _make_dir_link(link_path, target_path) -> str:
    """Create a directory symlink, or a junction on Windows; skip if neither works."""
    try:
        os.symlink(target_path, link_path, target_is_directory=True)
        return "symlink"
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32":
        try:
            import _winapi

            _winapi.CreateJunction(str(target_path), str(link_path))
            return "junction"
        except OSError:
            pass
    pytest.skip("neither symlinks nor junctions can be created here")


def test_write_file_refuses_protected_path_reached_through_directory_link(tmp_path):
    manifest = _manifest_with_protected_deploy_watcher(tmp_path)
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    protected_dir = workspace / "services" / "deploy_watcher"
    protected_dir.mkdir(parents=True)
    (protected_dir / "main.py").write_text("original\n")
    _make_dir_link(workspace / "innocent", protected_dir)

    with pytest.raises(tools.ProtectedPathError):
        tools.write_file(str(workspace), "innocent/main.py", "pwned\n", manifest, "issue-1", tracker)

    assert (protected_dir / "main.py").read_text() == "original\n"
    assert not tracker.is_exhausted("issue-1")


def test_write_file_refuses_git_dir_reached_through_directory_link(tmp_path):
    manifest = _manifest_with_protected_deploy_watcher(tmp_path)
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _seed_git_dir(workspace)
    _make_dir_link(workspace / "notgit", workspace / ".git")

    with pytest.raises(tools.ProtectedPathError):
        tools.write_file(str(workspace), "notgit/config", "[remote]\n", manifest, "issue-1", tracker)
    with pytest.raises(tools.ProtectedPathError):
        tools.read_file(str(workspace), "notgit/config")

    assert (workspace / ".git" / "config").read_text() == "[core]\n"


def test_write_file_refuses_always_protected_file_via_file_symlink(tmp_path):
    manifest = _manifest_with_protected_deploy_watcher(tmp_path)
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "requirements.txt").write_text("flask\n")
    try:
        os.symlink(workspace / "requirements.txt", workspace / "reqs.txt")
    except (OSError, NotImplementedError):
        pytest.skip("file symlinks not permitted here")

    with pytest.raises(tools.ProtectedPathError):
        tools.write_file(str(workspace), "reqs.txt", "evil\n", manifest, "issue-1", tracker)

    assert (workspace / "requirements.txt").read_text() == "flask\n"


# --- Final fix wave: I-4 expanded protected core, through write_file ---


@pytest.mark.parametrize(
    "path",
    [
        "services/__init__.py",
        "requirements.txt",
        "docker-compose.yml",
        "pyproject.toml",
        ".gitattributes",
        ".gitignore",
        "services/common/new_module.py",
        "services/common/__init__.py",
        ".github/workflows/test.yml",
        ".github/CODEOWNERS",
        "Requirements.TXT",
        ".GitHub/workflows/x.yml",
        "services/Common/x.py",
    ],
)
def test_write_file_refuses_expanded_protected_core(tmp_path, path):
    manifest = _manifest_with_protected_deploy_watcher(tmp_path)
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(tools.ProtectedPathError):
        tools.write_file(str(workspace), path, "x", manifest, "issue-1", tracker)

    assert not (workspace / path).exists()
