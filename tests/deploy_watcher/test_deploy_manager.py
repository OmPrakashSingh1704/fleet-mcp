from unittest.mock import MagicMock, patch

import docker.errors

from services.deploy_watcher.deploy_manager import DeployManager
from services.deploy_watcher.known_good import KnownGoodStore
from services.deploy_watcher.registry import ServiceRegistry


def _manager(tmp_path, docker_client, probation_seconds=1800.0, repo_root="."):
    registry = ServiceRegistry(str(tmp_path / "registry.json"))
    known_good = KnownGoodStore(str(tmp_path / "known_good.json"))
    manager = DeployManager(
        docker_client, registry, known_good, probation_seconds=probation_seconds, repo_root=repo_root
    )
    return manager, registry, known_good


def _docker_client(known_containers: dict | None = None) -> MagicMock:
    """A MagicMock docker client whose containers.get() mimics real Docker:
    docker.errors.NotFound for any name that wasn't explicitly registered.

    This matters once DeployManager starts probing containers.get() as a
    guard (e.g. the retired-sha check) -- a bare MagicMock() would silently
    "find" any container name and trip guards that expect NotFound.
    """
    client = MagicMock()
    containers = dict(known_containers or {})

    def fake_get(name):
        if name in containers:
            return containers[name]
        raise docker.errors.NotFound(f"no such container: {name}")

    client.containers.get.side_effect = fake_get
    return client


# ---------------------------------------------------------------------------
# deploy(): promotion path
# ---------------------------------------------------------------------------


@patch("services.deploy_watcher.deploy_manager.threading.Thread")
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=True)
@patch("services.deploy_watcher.deploy_manager.build_image", return_value="sha256:new")
def test_deploy_promotes_new_container_on_healthy_check(mock_build, mock_wait, mock_thread, tmp_path):
    docker_client = _docker_client()
    manager, registry, known_good = _manager(tmp_path, docker_client)

    result = manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    assert result.success is True
    assert result.image_tag == "fixture-hello-mcp:abc123"
    assert registry.get_active_container("fixture-hello-mcp") == "fixture-hello-mcp-abc123"
    # Ruling 1: known-good is only recorded after a full probation window
    # passes, never at promotion time.
    assert known_good.get("fixture-hello-mcp") is None
    docker_client.containers.run.assert_called_once_with(
        "fixture-hello-mcp:abc123", detach=True, name="fixture-hello-mcp-abc123", network="mcp-fleet"
    )
    mock_thread.assert_called_once()
    # A probation monitor thread is started for the right service/container.
    _args, kwargs = mock_thread.call_args
    assert kwargs["target"] == manager._run_probation
    assert kwargs["args"] == ("fixture-hello-mcp", "fixture-hello-mcp-abc123", 8080, "fixture-hello-mcp:abc123")
    assert kwargs["daemon"] is True


@patch("services.deploy_watcher.deploy_manager.threading.Thread")
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=True)
@patch("services.deploy_watcher.deploy_manager.build_image", return_value="sha256:new")
def test_deploy_builds_image_with_repo_root_context_and_service_dockerfile(
    mock_build, mock_wait, mock_thread, tmp_path
):
    docker_client = _docker_client()
    manager, _registry, _known_good = _manager(tmp_path, docker_client, repo_root="/repo/root")

    manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    mock_build.assert_called_once_with(
        docker_client,
        context_path="/repo/root",
        dockerfile="services/fixture_hello_mcp/Dockerfile",
        tag="fixture-hello-mcp:abc123",
    )


@patch("services.deploy_watcher.deploy_manager.threading.Thread")
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=False)
@patch("services.deploy_watcher.deploy_manager.build_image", return_value="sha256:new")
def test_deploy_kills_new_container_and_keeps_old_on_failed_health_check(mock_build, mock_wait, mock_thread, tmp_path):
    docker_client = _docker_client()
    new_container = MagicMock()
    docker_client.containers.run.return_value = new_container
    manager, registry, known_good = _manager(tmp_path, docker_client)
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-old")
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:old")

    result = manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    assert result.success is False
    assert result.reason == "failed initial health check"
    new_container.stop.assert_called_once()
    new_container.remove.assert_called_once()
    assert registry.get_active_container("fixture-hello-mcp") == "fixture-hello-mcp-old"
    assert known_good.get("fixture-hello-mcp") == "fixture-hello-mcp:old"
    mock_thread.assert_not_called()


@patch("services.deploy_watcher.deploy_manager.threading.Thread")
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=True)
@patch("services.deploy_watcher.deploy_manager.build_image", return_value="sha256:new")
def test_deploy_stops_old_container_after_promotion(mock_build, mock_wait, mock_thread, tmp_path):
    old_container = MagicMock()
    docker_client = _docker_client({"fixture-hello-mcp-old": old_container})
    manager, registry, known_good = _manager(tmp_path, docker_client)
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-old")

    manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    # First call is the retired-sha guard checking the new container name
    # (NotFound -- proceed); second is the old-container lookup to stop it.
    calls = [c.args for c in docker_client.containers.get.call_args_list]
    assert calls == [("fixture-hello-mcp-abc123",), ("fixture-hello-mcp-old",)]
    old_container.stop.assert_called_once()
    old_container.remove.assert_not_called()


# ---------------------------------------------------------------------------
# deploy(): idempotency and docker-error handling (ruling 4)
# ---------------------------------------------------------------------------


@patch("services.deploy_watcher.deploy_manager.threading.Thread")
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy")
@patch("services.deploy_watcher.deploy_manager.build_image")
def test_deploy_is_idempotent_when_commit_already_active(mock_build, mock_wait, mock_thread, tmp_path):
    docker_client = MagicMock()
    manager, registry, _known_good = _manager(tmp_path, docker_client)
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")

    result = manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    assert result.success is True
    assert result.image_tag == "fixture-hello-mcp:abc123"
    assert result.reason == "already active"
    mock_build.assert_not_called()
    docker_client.containers.run.assert_not_called()
    mock_wait.assert_not_called()
    mock_thread.assert_not_called()


@patch("services.deploy_watcher.deploy_manager.build_image")
def test_deploy_returns_failure_when_build_image_raises_build_error(mock_build, tmp_path):
    mock_build.side_effect = docker.errors.BuildError("boom", iter([]))
    docker_client = _docker_client()
    manager, registry, known_good = _manager(tmp_path, docker_client)

    result = manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    assert result.success is False
    assert result.image_tag == "fixture-hello-mcp:abc123"
    assert "build failed" in result.reason
    docker_client.containers.run.assert_not_called()
    assert registry.get_active_container("fixture-hello-mcp") is None
    assert known_good.get("fixture-hello-mcp") is None


@patch("services.deploy_watcher.deploy_manager.build_image", return_value="sha256:new")
def test_deploy_returns_failure_when_containers_run_raises_api_error(mock_build, tmp_path):
    docker_client = _docker_client()
    docker_client.containers.run.side_effect = docker.errors.APIError("container name conflict")
    manager, registry, known_good = _manager(tmp_path, docker_client)

    result = manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    assert result.success is False
    assert result.image_tag == "fixture-hello-mcp:abc123"
    assert "run failed" in result.reason
    assert registry.get_active_container("fixture-hello-mcp") is None
    assert known_good.get("fixture-hello-mcp") is None


@patch("services.deploy_watcher.deploy_manager.build_image")
def test_deploy_returns_failure_when_build_image_raises_image_not_found(mock_build, tmp_path):
    mock_build.side_effect = docker.errors.ImageNotFound("base image missing")
    docker_client = _docker_client()
    manager, _registry, _known_good = _manager(tmp_path, docker_client)

    result = manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    assert result.success is False
    assert "build failed" in result.reason
    docker_client.containers.run.assert_not_called()


# ---------------------------------------------------------------------------
# rollback()
# ---------------------------------------------------------------------------


def test_rollback_returns_failure_when_no_known_good_recorded(tmp_path):
    docker_client = MagicMock()
    manager, _registry, _known_good = _manager(tmp_path, docker_client)

    result = manager.rollback("never-deployed-service")

    assert result.success is False
    assert result.reason == "no known-good image on record"
    docker_client.containers.run.assert_not_called()


def test_rollback_with_no_known_good_does_not_stop_active_container(tmp_path):
    docker_client = MagicMock()
    manager, registry, _known_good = _manager(tmp_path, docker_client)
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")

    result = manager.rollback("fixture-hello-mcp")

    assert result.success is False
    docker_client.containers.get.assert_not_called()
    docker_client.containers.run.assert_not_called()
    assert registry.get_active_container("fixture-hello-mcp") == "fixture-hello-mcp-abc123"


def test_rollback_starts_known_good_image_and_updates_registry(tmp_path):
    docker_client = MagicMock()
    manager, registry, known_good = _manager(tmp_path, docker_client)
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:good-sha")

    result = manager.rollback("fixture-hello-mcp")

    assert result.success is True
    assert result.image_tag == "fixture-hello-mcp:good-sha"
    docker_client.containers.run.assert_called_once()
    args, kwargs = docker_client.containers.run.call_args
    assert args[0] == "fixture-hello-mcp:good-sha"
    assert kwargs["network"] == "mcp-fleet"
    assert kwargs["detach"] is True
    assert registry.get_active_container("fixture-hello-mcp") is not None


def test_rollback_stops_currently_active_failing_container(tmp_path):
    docker_client = MagicMock()
    failing_container = MagicMock()
    docker_client.containers.get.return_value = failing_container
    manager, registry, known_good = _manager(tmp_path, docker_client)
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:good-sha")
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")

    manager.rollback("fixture-hello-mcp")

    docker_client.containers.get.assert_called_once_with("fixture-hello-mcp-abc123")
    failing_container.stop.assert_called_once()
    failing_container.remove.assert_not_called()


# ---------------------------------------------------------------------------
# _run_probation(): tested directly and synchronously per ruling 6
# ---------------------------------------------------------------------------


@patch("services.deploy_watcher.deploy_manager.time.sleep", return_value=None)
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=True)
@patch("services.deploy_watcher.deploy_manager.time.monotonic")
def test_probation_passes_records_known_good_with_new_tag(mock_monotonic, mock_wait, mock_sleep, tmp_path):
    docker_client = MagicMock()
    manager, registry, known_good = _manager(tmp_path, docker_client, probation_seconds=30.0)
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:old-sha")

    # start=0 (deadline=30); loop checks at 5, 15, 25 (< 30, three healthy
    # checks); then 35 (>= 30) ends the loop.
    mock_monotonic.side_effect = [0, 5, 15, 25, 35]

    manager._run_probation("fixture-hello-mcp", "fixture-hello-mcp-abc123", 8080, "fixture-hello-mcp:abc123")

    assert known_good.get("fixture-hello-mcp") == "fixture-hello-mcp:abc123"
    docker_client.containers.run.assert_not_called()
    assert registry.get_active_container("fixture-hello-mcp") == "fixture-hello-mcp-abc123"


@patch("services.deploy_watcher.deploy_manager.time.sleep", return_value=None)
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy")
@patch("services.deploy_watcher.deploy_manager.time.monotonic")
def test_probation_failure_triggers_rollback_to_previous_known_good(mock_monotonic, mock_wait, mock_sleep, tmp_path):
    docker_client = MagicMock()
    failing_container = MagicMock()
    docker_client.containers.get.return_value = failing_container
    manager, registry, known_good = _manager(tmp_path, docker_client, probation_seconds=1800.0)
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:previous-good")

    mock_monotonic.side_effect = [0, 5]  # single loop iteration
    mock_wait.return_value = False  # the one probation check fails

    manager._run_probation("fixture-hello-mcp", "fixture-hello-mcp-abc123", 8080, "fixture-hello-mcp:abc123")

    # Rollback starts a container from the PREVIOUS known-good tag, not the
    # new (failed) tag.
    docker_client.containers.run.assert_called_once()
    args, kwargs = docker_client.containers.run.call_args
    assert args[0] == "fixture-hello-mcp:previous-good"
    assert kwargs["network"] == "mcp-fleet"

    # The failing container is stopped (not removed). containers.get is
    # called once to resolve the health-check container and again inside
    # rollback to stop it -- both times for the same watched container.
    assert docker_client.containers.get.call_count == 2
    for call in docker_client.containers.get.call_args_list:
        assert call.args == ("fixture-hello-mcp-abc123",)
    failing_container.stop.assert_called_once()
    failing_container.remove.assert_not_called()

    # Registry now points at the rollback container, not the failed one.
    active = registry.get_active_container("fixture-hello-mcp")
    assert active != "fixture-hello-mcp-abc123"
    assert active is not None

    # known-good floor is untouched by the failed probation.
    assert known_good.get("fixture-hello-mcp") == "fixture-hello-mcp:previous-good"


@patch("services.deploy_watcher.deploy_manager.time.sleep", return_value=None)
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy")
@patch("services.deploy_watcher.deploy_manager.time.monotonic")
def test_stale_probation_monitor_takes_no_action(mock_monotonic, mock_wait, mock_sleep, tmp_path):
    docker_client = MagicMock()
    manager, registry, known_good = _manager(tmp_path, docker_client, probation_seconds=1800.0)
    # A newer deploy has already superseded the container this monitor is
    # watching.
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-newer")
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:previous-good")

    mock_monotonic.side_effect = [0, 5, 15]
    mock_wait.return_value = False

    manager._run_probation("fixture-hello-mcp", "fixture-hello-mcp-abc123", 8080, "fixture-hello-mcp:abc123")

    mock_wait.assert_not_called()
    docker_client.containers.run.assert_not_called()
    docker_client.containers.get.assert_not_called()
    assert known_good.get("fixture-hello-mcp") == "fixture-hello-mcp:previous-good"
    assert registry.get_active_container("fixture-hello-mcp") == "fixture-hello-mcp-newer"


@patch("services.deploy_watcher.deploy_manager.time.sleep", return_value=None)
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy")
@patch("services.deploy_watcher.deploy_manager.time.monotonic")
def test_probation_treats_container_not_found_as_failed_check(mock_monotonic, mock_wait, mock_sleep, tmp_path):
    docker_client = MagicMock()
    docker_client.containers.get.side_effect = docker.errors.NotFound("gone")
    manager, registry, known_good = _manager(tmp_path, docker_client, probation_seconds=1800.0)
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:previous-good")
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")

    mock_monotonic.side_effect = [0, 5]

    manager._run_probation("fixture-hello-mcp", "fixture-hello-mcp-abc123", 8080, "fixture-hello-mcp:abc123")

    # A missing container is treated as a failed health check -- wait_for_healthy
    # is never even reached -- and that failed check still drives a rollback.
    mock_wait.assert_not_called()
    assert known_good.get("fixture-hello-mcp") == "fixture-hello-mcp:previous-good"
    assert registry.get_active_container("fixture-hello-mcp") != "fixture-hello-mcp-abc123"


# ---------------------------------------------------------------------------
# Ruling 7: run_options and health_url_resolver hooks
# ---------------------------------------------------------------------------


@patch("services.deploy_watcher.deploy_manager.threading.Thread")
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=True)
@patch("services.deploy_watcher.deploy_manager.build_image", return_value="sha256:new")
def test_deploy_merges_run_options_without_overriding_reserved_kwargs(mock_build, mock_wait, mock_thread, tmp_path):
    docker_client = _docker_client()
    registry = ServiceRegistry(str(tmp_path / "registry.json"))
    known_good = KnownGoodStore(str(tmp_path / "known_good.json"))
    manager = DeployManager(
        docker_client,
        registry,
        known_good,
        run_options={
            "environment": {"FOO": "bar"},
            "name": "evil-name",
            "network": "evil-net",
            "detach": False,
            "image": "evil-image",
        },
    )

    manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    docker_client.containers.run.assert_called_once_with(
        "fixture-hello-mcp:abc123",
        environment={"FOO": "bar"},
        detach=True,
        name="fixture-hello-mcp-abc123",
        network="mcp-fleet",
    )


def test_rollback_merges_run_options_without_overriding_reserved_kwargs(tmp_path):
    docker_client = MagicMock()
    registry = ServiceRegistry(str(tmp_path / "registry.json"))
    known_good = KnownGoodStore(str(tmp_path / "known_good.json"))
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:good-sha")
    manager = DeployManager(
        docker_client,
        registry,
        known_good,
        run_options={"labels": {"x": "y"}, "network": "evil-net", "name": "evil-name", "detach": False},
    )

    manager.rollback("fixture-hello-mcp")

    args, kwargs = docker_client.containers.run.call_args
    assert args[0] == "fixture-hello-mcp:good-sha"
    assert kwargs["network"] == "mcp-fleet"
    assert kwargs["labels"] == {"x": "y"}
    assert kwargs["detach"] is True
    assert kwargs["name"] != "evil-name"


@patch("services.deploy_watcher.deploy_manager.threading.Thread")
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=True)
@patch("services.deploy_watcher.deploy_manager.build_image", return_value="sha256:new")
def test_deploy_uses_custom_health_url_resolver_for_initial_check(mock_build, mock_wait, mock_thread, tmp_path):
    docker_client = _docker_client()
    new_container = MagicMock()
    docker_client.containers.run.return_value = new_container
    resolver = MagicMock(return_value="http://custom-host:9999/healthz")
    registry = ServiceRegistry(str(tmp_path / "registry.json"))
    known_good = KnownGoodStore(str(tmp_path / "known_good.json"))
    manager = DeployManager(docker_client, registry, known_good, health_url_resolver=resolver)

    manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    resolver.assert_called_once_with(new_container, 8080)
    mock_wait.assert_called_once_with("http://custom-host:9999/healthz")


@patch("services.deploy_watcher.deploy_manager.time.sleep", return_value=None)
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=True)
@patch("services.deploy_watcher.deploy_manager.time.monotonic")
def test_probation_uses_custom_health_url_resolver(mock_monotonic, mock_wait, mock_sleep, tmp_path):
    docker_client = MagicMock()
    watched_container = MagicMock()
    docker_client.containers.get.return_value = watched_container
    resolver = MagicMock(return_value="http://custom-host:9999/healthz")
    registry = ServiceRegistry(str(tmp_path / "registry.json"))
    known_good = KnownGoodStore(str(tmp_path / "known_good.json"))
    manager = DeployManager(
        docker_client, registry, known_good, probation_seconds=30.0, health_url_resolver=resolver
    )
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")

    mock_monotonic.side_effect = [0, 5, 35]

    manager._run_probation("fixture-hello-mcp", "fixture-hello-mcp-abc123", 8080, "fixture-hello-mcp:abc123")

    resolver.assert_called_once_with(watched_container, 8080)
    mock_wait.assert_called_once_with(
        "http://custom-host:9999/healthz", required_successes=1, interval_seconds=2.0, timeout_seconds=5.0
    )
    assert known_good.get("fixture-hello-mcp") == "fixture-hello-mcp:abc123"


# ---------------------------------------------------------------------------
# Fix round 1 -- Important #1: rollback() error handling
# ---------------------------------------------------------------------------


def test_rollback_restarts_previous_container_when_run_raises_api_error(tmp_path):
    previous_container = MagicMock()
    docker_client = _docker_client({"fixture-hello-mcp-abc123": previous_container})
    docker_client.containers.run.side_effect = docker.errors.APIError("no room on daemon")
    manager, registry, known_good = _manager(tmp_path, docker_client)
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:good-sha")
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")

    result = manager.rollback("fixture-hello-mcp")

    assert result.success is False
    assert result.image_tag == "fixture-hello-mcp:good-sha"
    assert "rollback run failed" in result.reason
    # The (failing) active container was stopped, then restarted as a
    # best-effort recovery once starting the known-good image failed.
    previous_container.stop.assert_called_once()
    previous_container.start.assert_called_once()
    # The registry is left pointing at whatever was active before -- never
    # flipped to a container that doesn't exist.
    assert registry.get_active_container("fixture-hello-mcp") == "fixture-hello-mcp-abc123"


def test_rollback_never_raises_when_restart_attempt_also_fails(tmp_path):
    previous_container = MagicMock()
    previous_container.start.side_effect = docker.errors.APIError("daemon unreachable")
    docker_client = _docker_client({"fixture-hello-mcp-abc123": previous_container})
    docker_client.containers.run.side_effect = docker.errors.APIError("no room on daemon")
    manager, registry, known_good = _manager(tmp_path, docker_client)
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:good-sha")
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")

    result = manager.rollback("fixture-hello-mcp")  # must not raise

    assert result.success is False
    assert "rollback run failed" in result.reason


def test_rollback_container_names_are_unique_within_same_second(tmp_path):
    docker_client = _docker_client()
    manager, registry, known_good = _manager(tmp_path, docker_client)
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:good-sha")

    manager.rollback("fixture-hello-mcp")
    first_name = docker_client.containers.run.call_args.kwargs["name"]

    manager.rollback("fixture-hello-mcp")
    second_name = docker_client.containers.run.call_args.kwargs["name"]

    assert first_name != second_name


# ---------------------------------------------------------------------------
# Fix round 1 -- Important #2: deploy() must not raise after the registry
# flip, and the probation thread must always start once it has flipped.
# ---------------------------------------------------------------------------


@patch("services.deploy_watcher.deploy_manager.threading.Thread")
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=True)
@patch("services.deploy_watcher.deploy_manager.build_image", return_value="sha256:new")
def test_deploy_succeeds_and_starts_probation_even_if_stopping_old_container_raises(
    mock_build, mock_wait, mock_thread, tmp_path
):
    old_container = MagicMock()
    old_container.stop.side_effect = docker.errors.APIError("boom")
    docker_client = _docker_client({"fixture-hello-mcp-old": old_container})
    manager, registry, known_good = _manager(tmp_path, docker_client)
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-old")

    result = manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")  # must not raise

    assert result.success is True
    assert registry.get_active_container("fixture-hello-mcp") == "fixture-hello-mcp-abc123"
    mock_thread.assert_called_once()


# ---------------------------------------------------------------------------
# Fix round 1 -- Important #3: leftover container from a failed run() is
# force-removed so a future deploy of the same sha doesn't collide.
# ---------------------------------------------------------------------------


def test_deploy_force_removes_leftover_container_when_run_raises_api_error(tmp_path):
    leftover_container = MagicMock()
    docker_client = MagicMock()
    call_count = {"n": 0}

    def fake_get(name):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First call: the retired-sha guard, before the container
            # existed.
            raise docker.errors.NotFound("not found")
        # Second call: cleanup after containers.run() created-but-failed
        # to start the container.
        return leftover_container

    docker_client.containers.get.side_effect = fake_get
    docker_client.containers.run.side_effect = docker.errors.APIError("failed to start")

    with patch("services.deploy_watcher.deploy_manager.build_image", return_value="sha256:new"):
        manager, registry, known_good = _manager(tmp_path, docker_client)
        result = manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    assert result.success is False
    assert "run failed" in result.reason
    leftover_container.remove.assert_called_once_with(force=True)
    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# Fix round 1 -- Minor #5: retired-sha guard
# ---------------------------------------------------------------------------


@patch("services.deploy_watcher.deploy_manager.build_image")
def test_deploy_refuses_to_redeploy_a_retired_sha(mock_build, tmp_path):
    existing_but_inactive = MagicMock()
    docker_client = _docker_client({"fixture-hello-mcp-abc123": existing_but_inactive})
    manager, registry, known_good = _manager(tmp_path, docker_client)
    # Registry does NOT point at fixture-hello-mcp-abc123 -- it was
    # previously promoted then retired (or rolled back away from).

    result = manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    assert result.success is False
    assert result.reason == "sha previously retired; not redeploying"
    mock_build.assert_not_called()
    docker_client.containers.run.assert_not_called()


# ---------------------------------------------------------------------------
# Fix round 1 -- Minor #4: _rollback(service, expected_active) staleness
# guard, used internally by the probation monitor.
# ---------------------------------------------------------------------------


def test_internal_rollback_with_mismatched_expected_active_does_nothing(tmp_path):
    docker_client = _docker_client()
    manager, registry, known_good = _manager(tmp_path, docker_client)
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:good-sha")
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-newer")

    result = manager._rollback("fixture-hello-mcp", "fixture-hello-mcp-abc123")

    assert result.success is False
    assert result.reason == "superseded"
    docker_client.containers.get.assert_not_called()
    docker_client.containers.run.assert_not_called()
    assert registry.get_active_container("fixture-hello-mcp") == "fixture-hello-mcp-newer"


@patch("services.deploy_watcher.deploy_manager.time.sleep", return_value=None)
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=False)
@patch("services.deploy_watcher.deploy_manager.time.monotonic")
def test_probation_no_rollback_when_registry_changes_before_recheck(mock_monotonic, mock_wait, mock_sleep, tmp_path):
    docker_client = _docker_client({"fixture-hello-mcp-abc123": MagicMock()})
    manager, registry, known_good = _manager(tmp_path, docker_client, probation_seconds=1800.0)
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:previous-good")
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")

    # First read (top-of-loop staleness check) still matches; the second
    # read (inside _rollback, right before acting) reflects a newer deploy
    # having already promoted a different container in the meantime.
    registry.get_active_container = MagicMock(
        side_effect=["fixture-hello-mcp-abc123", "fixture-hello-mcp-newer"]
    )

    mock_monotonic.side_effect = [0, 5]

    manager._run_probation("fixture-hello-mcp", "fixture-hello-mcp-abc123", 8080, "fixture-hello-mcp:abc123")

    docker_client.containers.run.assert_not_called()
    assert known_good.get("fixture-hello-mcp") == "fixture-hello-mcp:previous-good"


@patch("services.deploy_watcher.deploy_manager.time.sleep", return_value=None)
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=False)
@patch("services.deploy_watcher.deploy_manager.time.monotonic")
def test_probation_failure_on_first_ever_deploy_does_not_stop_active_container(
    mock_monotonic, mock_wait, mock_sleep, tmp_path
):
    watched_container = MagicMock()
    docker_client = _docker_client({"fixture-hello-mcp-abc123": watched_container})
    manager, registry, known_good = _manager(tmp_path, docker_client, probation_seconds=1800.0)
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")
    # No known-good recorded yet -- this is the very first deploy of this
    # service, so there is nothing better to roll back to.

    mock_monotonic.side_effect = [0, 5]

    manager._run_probation("fixture-hello-mcp", "fixture-hello-mcp-abc123", 8080, "fixture-hello-mcp:abc123")

    watched_container.stop.assert_not_called()
    docker_client.containers.run.assert_not_called()
    assert known_good.get("fixture-hello-mcp") is None
    assert registry.get_active_container("fixture-hello-mcp") == "fixture-hello-mcp-abc123"


# ---------------------------------------------------------------------------
# Fix round 1 -- Minor #6: the probation loop body must never silently die.
# ---------------------------------------------------------------------------


@patch("services.deploy_watcher.deploy_manager.time.sleep", return_value=None)
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy")
@patch("services.deploy_watcher.deploy_manager.time.monotonic")
def test_probation_resolver_exception_is_treated_as_failed_check_and_rolls_back(
    mock_monotonic, mock_wait, mock_sleep, tmp_path
):
    watched_container = MagicMock()
    docker_client = _docker_client({"fixture-hello-mcp-abc123": watched_container})
    resolver = MagicMock(side_effect=ValueError("boom"))
    registry = ServiceRegistry(str(tmp_path / "registry.json"))
    known_good = KnownGoodStore(str(tmp_path / "known_good.json"))
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:previous-good")
    manager = DeployManager(
        docker_client, registry, known_good, probation_seconds=1800.0, health_url_resolver=resolver
    )
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")

    mock_monotonic.side_effect = [0, 5]

    manager._run_probation("fixture-hello-mcp", "fixture-hello-mcp-abc123", 8080, "fixture-hello-mcp:abc123")

    resolver.assert_called_once()
    mock_wait.assert_not_called()  # never reached -- resolver raised first
    docker_client.containers.run.assert_called_once()
    args, _kwargs = docker_client.containers.run.call_args
    assert args[0] == "fixture-hello-mcp:previous-good"
    assert registry.get_active_container("fixture-hello-mcp") != "fixture-hello-mcp-abc123"
    assert known_good.get("fixture-hello-mcp") == "fixture-hello-mcp:previous-good"


# ---------------------------------------------------------------------------
# M-1: per-service lock -- rollback's check-and-perform and deploy's registry
# flip never interleave.
# ---------------------------------------------------------------------------

import threading  # noqa: E402


def _locked_scenario_manager(tmp_path):
    docker_client = _docker_client({"svc-old": MagicMock(name="svc-old")})
    manager, registry, known_good = _manager(tmp_path, docker_client)
    registry.set_active_container("svc", "svc-old")
    known_good.record("svc", "svc:good")
    # Keep the probation monitor out of these tests.
    manager._run_probation = lambda *args, **kwargs: None
    return manager, registry, known_good, docker_client


def test_rollback_waits_for_in_flight_deploy_flip(tmp_path):
    manager, registry, _known_good, docker_client = _locked_scenario_manager(tmp_path)
    in_flip = threading.Event()
    release = threading.Event()
    real_set = registry.set_active_container

    def paused_set(service, name):
        if name == "svc-new":
            in_flip.set()
            assert release.wait(5)
        real_set(service, name)

    registry.set_active_container = paused_set
    rollback_result = {}
    rollback_done = threading.Event()

    def do_rollback():
        rollback_result["r"] = manager._rollback("svc", "svc-old")
        rollback_done.set()

    with patch("services.deploy_watcher.deploy_manager.build_image"), patch(
        "services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=True
    ):
        deployer = threading.Thread(target=manager.deploy, args=("svc", "services/svc", "new"))
        deployer.start()
        assert in_flip.wait(5)

        roller = threading.Thread(target=do_rollback)
        roller.start()
        # The deploy is paused mid-flip while holding the service lock: the
        # rollback must not get to check-and-perform yet.
        assert not rollback_done.wait(0.5)
        assert not any(c.args and c.args[0] == "svc:good" for c in docker_client.containers.run.call_args_list)

        release.set()
        deployer.join(5)
        roller.join(5)

    # Once it ran, the rollback saw the flipped registry and stood down.
    assert rollback_result["r"].reason == "superseded"
    assert registry.get_active_container("svc") == "svc-new"


def test_deploy_flip_waits_for_in_flight_rollback(tmp_path):
    manager, registry, _known_good, docker_client = _locked_scenario_manager(tmp_path)
    in_rollback = threading.Event()
    release = threading.Event()

    def fake_run(image, **kwargs):
        if image == "svc:good":
            in_rollback.set()
            assert release.wait(5)
        return MagicMock(name=kwargs.get("name"))

    docker_client.containers.run.side_effect = fake_run
    deploy_done = threading.Event()

    def do_deploy():
        manager.deploy("svc", "services/svc", "new")
        deploy_done.set()

    with patch("services.deploy_watcher.deploy_manager.build_image"), patch(
        "services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=True
    ):
        roller = threading.Thread(target=manager._rollback, args=("svc", "svc-old"))
        roller.start()
        assert in_rollback.wait(5)

        deployer = threading.Thread(target=do_deploy)
        deployer.start()
        # The new container can be built/started and health-checked, but the
        # registry flip must wait for the rollback to finish.
        assert not deploy_done.wait(0.5)
        assert registry.get_active_container("svc") == "svc-old"

        release.set()
        roller.join(5)
        deployer.join(5)

    assert deploy_done.is_set()
    assert registry.get_active_container("svc") == "svc-new"
