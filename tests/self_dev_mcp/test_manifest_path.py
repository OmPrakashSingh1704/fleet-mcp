from flotilla_mcp.self_dev_mcp import server


def test_manifest_path_defaults_to_cwd_file(monkeypatch):
    monkeypatch.delenv("FLEET_MANIFEST_PATH", raising=False)
    assert server.manifest_path() == "fleet_manifest.yaml"


def test_manifest_path_honors_env(monkeypatch, tmp_path):
    p = tmp_path / "m.yaml"
    monkeypatch.setenv("FLEET_MANIFEST_PATH", str(p))
    assert server.manifest_path() == str(p)
