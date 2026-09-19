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
