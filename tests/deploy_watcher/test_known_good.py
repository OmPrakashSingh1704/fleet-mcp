from fleetmcp.deploy_watcher.known_good import KnownGoodStore


def test_record_and_get(tmp_path):
    store = KnownGoodStore(str(tmp_path / "known_good.json"))
    store.record("svc", "svc:sha1")

    assert store.get("svc") == "svc:sha1"


def test_get_returns_none_when_unset(tmp_path):
    store = KnownGoodStore(str(tmp_path / "known_good.json"))

    assert store.get("unknown-service") is None


def test_record_overwrites_previous_value(tmp_path):
    store = KnownGoodStore(str(tmp_path / "known_good.json"))
    store.record("svc", "svc:sha1")
    store.record("svc", "svc:sha2")

    assert store.get("svc") == "svc:sha2"
