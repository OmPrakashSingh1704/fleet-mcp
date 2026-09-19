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


# ---------------------------------------------------------------------------
# deploy(): promotion path
# ---------------------------------------------------------------------------


@patch("services.deploy_watcher.deploy_manager.threading.Thread")
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=True)
@patch("services.deploy_watcher.deploy_manager.build_image", return_value="sha256:new")
def test_deploy_promotes_new_container_on_healthy_check(mock_build, mock_wait, mock_thread, tmp_path):
    docker_client = MagicMock()
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
    docker_client = MagicMock()
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
    docker_client = MagicMock()
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
    docker_client = MagicMock()
    old_container = MagicMock()
    docker_client.containers.get.return_value = old_container
    manager, registry, known_good = _manager(tmp_path, docker_client)
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-old")

    manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    docker_client.containers.get.assert_called_once_with("fixture-hello-mcp-old")
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
    docker_client = MagicMock()
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
    docker_client = MagicMock()
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
    docker_client = MagicMock()
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
    docker_client = MagicMock()
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
    docker_client = MagicMock()
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
