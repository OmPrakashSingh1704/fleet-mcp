import textwrap

from services.common.manifest import FleetManifest


def _write_manifest(tmp_path, content: str) -> str:
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text(textwrap.dedent(content))
    return str(manifest_path)


def test_protected_service_blocks_all_paths_under_it(tmp_path):
    path = _write_manifest(tmp_path, """
        services:
          deploy-watcher:
            path: services/deploy_watcher
            protected: true
    """)
    manifest = FleetManifest.load(path)
    assert manifest.is_path_protected("services/deploy_watcher/deploy_manager.py")


def test_unprotected_service_path_is_allowed(tmp_path):
    path = _write_manifest(tmp_path, """
        services:
          fixture-hello-mcp:
            path: services/fixture_hello_mcp
            protected: false
    """)
    manifest = FleetManifest.load(path)
    assert not manifest.is_path_protected("services/fixture_hello_mcp/server.py")


def test_fleet_manifest_yaml_itself_is_always_protected(tmp_path):
    path = _write_manifest(tmp_path, "services: {}")
    manifest = FleetManifest.load(path)
    assert manifest.is_path_protected("fleet_manifest.yaml")


def test_manifest_loader_module_is_always_protected(tmp_path):
    path = _write_manifest(tmp_path, "services: {}")
    manifest = FleetManifest.load(path)
    assert manifest.is_path_protected("services/common/manifest.py")


def test_specific_protected_path_within_unprotected_service(tmp_path):
    path = _write_manifest(tmp_path, """
        services:
          self-dev-mcp:
            path: services/self_dev_mcp
            protected: false
            protected_paths:
              - services/self_dev_mcp/config.py
    """)
    manifest = FleetManifest.load(path)
    assert manifest.is_path_protected("services/self_dev_mcp/config.py")
    assert not manifest.is_path_protected("services/self_dev_mcp/tools.py")


def test_get_and_all_services(tmp_path):
    path = _write_manifest(tmp_path, """
        services:
          fixture-hello-mcp:
            path: services/fixture_hello_mcp
            container: fixture-hello-mcp
            health_check: http://fixture-hello-mcp:8080/health
    """)
    manifest = FleetManifest.load(path)
    service = manifest.get("fixture-hello-mcp")
    assert service.container == "fixture-hello-mcp"
    assert service.health_check == "http://fixture-hello-mcp:8080/health"
    assert manifest.all_services() == [service]


def test_backslash_path_normalization(tmp_path):
    path = _write_manifest(tmp_path, """
        services:
          deploy-watcher:
            path: services/deploy_watcher
            protected: true
    """)
    manifest = FleetManifest.load(path)
    # Windows-style path with backslashes should be normalized and recognized as protected
    assert manifest.is_path_protected("services\\deploy_watcher\\file.py")


def test_case_insensitive_always_protected_paths(tmp_path):
    path = _write_manifest(tmp_path, "services: {}")
    manifest = FleetManifest.load(path)
    # Case variations of always-protected paths should be protected
    assert manifest.is_path_protected("FLEET_MANIFEST.YAML")
    assert manifest.is_path_protected("Fleet_Manifest.Yaml")
    assert manifest.is_path_protected("SERVICES/COMMON/MANIFEST.PY")
    assert manifest.is_path_protected("Services/Common/Manifest.Py")


def test_dot_segment_collapsing(tmp_path):
    path = _write_manifest(tmp_path, "services: {}")
    manifest = FleetManifest.load(path)
    # Paths with . and .. segments should be canonicalized before comparison
    assert manifest.is_path_protected("./fleet_manifest.yaml")
    assert manifest.is_path_protected("./services/common/manifest.py")
    assert manifest.is_path_protected("services/../services/common/manifest.py")
    assert manifest.is_path_protected("services/./common/manifest.py")


def test_path_escape_refusal(tmp_path):
    path = _write_manifest(tmp_path, """
        services:
          fixture-hello-mcp:
            path: services/fixture_hello_mcp
            protected: false
    """)
    manifest = FleetManifest.load(path)
    # Paths that escape the repo root via .. should be treated as protected
    # regardless of manifest content — they're escape attempts
    assert manifest.is_path_protected("../../etc/passwd")
    assert manifest.is_path_protected("../../../secret")
    assert manifest.is_path_protected("services/fixture_hello_mcp/../../../../../../etc/passwd")


# --- Final fix wave: I-4 expanded protected core ---

import pytest  # noqa: E402

from services.common.manifest import (  # noqa: E402
    ALWAYS_PROTECTED_PATHS,
    ALWAYS_PROTECTED_PREFIXES,
    canonicalize_path,
)

NEW_EXACT_PATHS = [
    "services/__init__.py",
    "requirements.txt",
    "docker-compose.yml",
    "pyproject.toml",
    ".gitattributes",
    ".gitignore",
]


def test_always_protected_constants_contain_expanded_core():
    assert set(NEW_EXACT_PATHS) <= ALWAYS_PROTECTED_PATHS
    assert ALWAYS_PROTECTED_PREFIXES == frozenset({"services/common/", ".github/"})


@pytest.mark.parametrize("path", NEW_EXACT_PATHS)
def test_new_exact_paths_protected_including_variants(tmp_path, path):
    manifest = FleetManifest.load(_write_manifest(tmp_path, "services: {}"))
    for variant in (path, path.upper(), "./" + path, "/" + path, path.replace("/", "\\"), path + ".", path + "::$DATA"):
        assert manifest.is_path_protected(variant), variant


@pytest.mark.parametrize(
    "path",
    [
        "services/common/__init__.py",
        "services/common/new_helper.py",
        "services/common/sub/deep.py",
        "services/common",
        "SERVICES/COMMON/x.py",
        "services\\common\\x.py",
        "services/x/../common/y.py",
        ".github/workflows/test.yml",
        ".github/CODEOWNERS",
        ".github",
        ".GITHUB/workflows/test.yml",
        "./.github/x",
        ".github./x",
    ],
)
def test_prefix_protection_including_case_variants(tmp_path, path):
    manifest = FleetManifest.load(_write_manifest(tmp_path, "services: {}"))
    assert manifest.is_path_protected(path)


@pytest.mark.parametrize(
    "path",
    [
        "services/commonplace/x.py",
        "services/common_extra.py",
        ".githubx/y",
        "docs/.github/x",
        "services/self_dev_mcp/tools.py",
        "requirements-dev.txt",
    ],
)
def test_prefix_protection_does_not_overmatch(tmp_path, path):
    manifest = FleetManifest.load(_write_manifest(tmp_path, "services: {}"))
    assert not manifest.is_path_protected(path)


def test_canonicalize_path_strips_windows_aliases():
    assert canonicalize_path(".GIT./Config ") == ".git/config"
    assert canonicalize_path("a\\b::$DATA") == "a/b"
    assert canonicalize_path("./x/../Y") == "y"


def test_real_fleet_manifest_self_dev_entry_is_unprotected_and_compose_managed():
    import os

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    manifest = FleetManifest.load(os.path.join(repo_root, "fleet_manifest.yaml"))
    self_dev = manifest.get("self-dev-mcp")
    assert self_dev.protected is False
    # I-7: compose-managed only for this release -- the watcher skips it.
    assert self_dev.container is None
    assert not manifest.is_path_protected("services/self_dev_mcp/tools.py")


def test_codeowners_mirrors_every_always_protected_entry():
    import os

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo_root, ".github", "CODEOWNERS"), encoding="utf-8") as f:
        patterns = {line.split()[0] for line in f if line.strip() and not line.startswith("#")}

    for path in ALWAYS_PROTECTED_PATHS:
        assert "/" + path in patterns, path
    for prefix in ALWAYS_PROTECTED_PREFIXES:
        assert "/" + prefix in patterns, prefix
    manifest = FleetManifest.load(os.path.join(repo_root, "fleet_manifest.yaml"))
    for service in manifest.all_services():
        if service.protected:
            assert "/" + service.path.rstrip("/") + "/" in patterns, service.path
