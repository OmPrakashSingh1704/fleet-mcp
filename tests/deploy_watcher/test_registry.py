from services.deploy_watcher.registry import ServiceRegistry


def test_set_and_get_active_container(tmp_path):
    registry = ServiceRegistry(str(tmp_path / "registry.json"))
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")

    assert registry.get_active_container("fixture-hello-mcp") == "fixture-hello-mcp-abc123"


def test_get_active_container_returns_none_when_unset(tmp_path):
    registry = ServiceRegistry(str(tmp_path / "registry.json"))

    assert registry.get_active_container("unknown-service") is None


def test_registry_persists_across_instances(tmp_path):
    registry_path = str(tmp_path / "registry.json")
    ServiceRegistry(registry_path).set_active_container("svc", "container-1")

    reloaded = ServiceRegistry(registry_path)
    assert reloaded.get_active_container("svc") == "container-1"
