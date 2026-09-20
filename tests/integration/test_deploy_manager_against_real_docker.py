"""End-to-end proof of the Deploy Watcher's build/deploy/probation/rollback
mechanics against a real, local Docker daemon -- no mocked docker client,
no mocked health checks.

The centerpiece is scenario (c): a release that passes its *initial* health
check (so it goes live and the old release is stopped) and then starts
failing *during probation*. The proof this test exists to deliver is that
the rollback that follows always lands on the previously-proven image
(``known_good``), never on the image that just failed -- i.e. a probation
failure can never roll back onto an unproven image.

Skipped automatically (with a clear reason) when Docker isn't available.
Marked ``docker`` so CI can exclude it via ``-m "not docker"``.
"""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import docker
import docker.errors
import pytest

from fleetmcp.deploy_watcher.deploy_manager import DeployManager
from fleetmcp.deploy_watcher.known_good import KnownGoodStore
from fleetmcp.deploy_watcher.registry import ServiceRegistry

NETWORK_NAME = "mcp-fleet"


def _check_docker_available() -> tuple[bool, str]:
    if shutil.which("docker") is None:
        return False, "docker CLI not found on PATH"
    try:
        client = docker.from_env()
        try:
            client.ping()
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001 - any failure means "not available"
        return False, f"Docker daemon not reachable: {exc}"
    return True, ""


_DOCKER_AVAILABLE, _DOCKER_SKIP_REASON = _check_docker_available()

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason=_DOCKER_SKIP_REASON),
]


# ---------------------------------------------------------------------------
# Fixture Flask services
# ---------------------------------------------------------------------------

_HEALTHY_SERVER = """from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/health")
def health():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
"""

_FAILING_SERVER = """from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/health")
def health():
    return jsonify(status="fail"), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
"""

# Passes its first _HEALTHY_LIMIT /health calls, then fails forever after.
# _HEALTHY_LIMIT is set to exactly the number of consecutive successes
# wait_for_healthy's real default (required_successes=3) needs for the
# *initial* deploy health check to pass -- so the very next call (the first
# probation check) is the one that fails, proving the failure happens
# during probation, not at initial promotion.
_FLAKY_SERVER_TEMPLATE = """from flask import Flask, jsonify

app = Flask(__name__)
_calls = {{"n": 0}}
_HEALTHY_LIMIT = {healthy_limit}


@app.route("/health")
def health():
    _calls["n"] += 1
    if _calls["n"] <= _HEALTHY_LIMIT:
        return jsonify(status="ok"), 200
    return jsonify(status="fail"), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
"""


def _write_service(root: Path, name: str, server_source: str) -> None:
    service_dir = root / name
    service_dir.mkdir(parents=True, exist_ok=True)
    (service_dir / "server.py").write_text(server_source)
    (service_dir / "Dockerfile").write_text(
        "FROM python:3.11-slim\n"
        "WORKDIR /app\n"
        "RUN pip install --no-cache-dir flask==3.0.3\n"
        f"COPY {name}/server.py .\n"
        'CMD ["python", "server.py"]\n'
    )


def _resolve_health_url(container, port: int) -> str:
    # The host can't resolve container names on the mcp-fleet network, so
    # we publish the container's port to a random host port and hit it via
    # 127.0.0.1 instead. Right after container creation the port mapping
    # may not be populated yet -- return a URL that will fail cleanly so
    # wait_for_healthy retries rather than raising a KeyError/IndexError.
    container.reload()
    bindings = container.ports.get(f"{port}/tcp")
    if not bindings:
        return "http://127.0.0.1:1/health"
    host_port = bindings[0]["HostPort"]
    return f"http://127.0.0.1:{host_port}/health"


def _poll(predicate: Callable[[], bool], deadline_seconds: float, interval: float = 1.0) -> bool:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def docker_client():
    client = docker.from_env()
    yield client
    client.close()


@pytest.fixture
def fleet_network(docker_client):
    created = False
    try:
        docker_client.networks.get(NETWORK_NAME)
    except docker.errors.NotFound:
        docker_client.networks.create(NETWORK_NAME, driver="bridge")
        created = True
    yield
    if created:
        try:
            docker_client.networks.get(NETWORK_NAME).remove()
        except docker.errors.NotFound:
            pass
        except docker.errors.APIError:
            pass  # best-effort: don't fail the test over network cleanup


@pytest.fixture
def svc(docker_client, fleet_network):
    """A unique service name for this test run, with guaranteed cleanup of
    every container and image it produced -- runs even if the test fails.
    """
    name = f"it-fleet-{uuid.uuid4().hex[:8]}"
    yield name

    for container in docker_client.containers.list(all=True):
        if container.name.startswith(name):
            container.remove(force=True)

    for image in docker_client.images.list():
        for tag in image.tags:
            if tag.startswith(f"{name}:"):
                try:
                    docker_client.images.remove(tag, force=True)
                except docker.errors.ImageNotFound:
                    pass
                break


# ---------------------------------------------------------------------------
# The test
# ---------------------------------------------------------------------------


def test_deploy_lifecycle_against_real_docker(tmp_path, docker_client, svc):
    registry = ServiceRegistry(str(tmp_path / "registry.json"))
    known_good = KnownGoodStore(str(tmp_path / "known_good.json"))
    manager = DeployManager(
        docker_client,
        registry,
        known_good,
        probation_seconds=3,
        repo_root=str(tmp_path),
        run_options={"ports": {"8080/tcp": None}},
        health_url_resolver=_resolve_health_url,
    )

    # --- (a) v1 is healthy: deploy succeeds, and known-good is recorded
    # only after probation completes. ---
    _write_service(tmp_path, svc, _HEALTHY_SERVER)
    result_v1 = manager.deploy(svc, svc, "v1")
    assert result_v1.success is True
    assert registry.get_active_container(svc) == f"{svc}-v1"

    assert _poll(lambda: known_good.get(svc) == f"{svc}:v1", deadline_seconds=60), (
        f"known_good was never recorded for v1; last seen {known_good.get(svc)!r}"
    )

    # --- (b) v2 fails its initial health check (/health always 500):
    # deploy fails, the registry and known-good floor are untouched, and
    # the failed container is cleaned up rather than left running. ---
    _write_service(tmp_path, svc, _FAILING_SERVER)
    result_v2 = manager.deploy(svc, svc, "v2")
    assert result_v2.success is False
    assert registry.get_active_container(svc) == f"{svc}-v1"
    assert known_good.get(svc) == f"{svc}:v1"
    with pytest.raises(docker.errors.NotFound):
        docker_client.containers.get(f"{svc}-v2")

    # --- (c) THE KEY PROOF: v3 passes its initial health check (so it goes
    # live and v1 is stopped) and then starts failing during probation. The
    # rollback that follows must land on the known-good image (v1) -- never
    # on v3, which was never proven. ---
    _write_service(tmp_path, svc, _FLAKY_SERVER_TEMPLATE.format(healthy_limit=3))
    result_v3 = manager.deploy(svc, svc, "v3")
    assert result_v3.success is True

    def _rolled_back() -> bool:
        active = registry.get_active_container(svc)
        return bool(active) and active.startswith(f"{svc}-rollback-")

    assert _poll(_rolled_back, deadline_seconds=90), (
        f"registry never rolled back off v3; active={registry.get_active_container(svc)!r}"
    )

    rollback_container_name = registry.get_active_container(svc)
    rollback_container = docker_client.containers.get(rollback_container_name)
    # The rollback container was started from the known-good image (v1),
    # never from v3 -- this is the assertion that matters most in this test.
    assert rollback_container.attrs["Config"]["Image"] == f"{svc}:v1"

    v3_container = docker_client.containers.get(f"{svc}-v3")
    v3_container.reload()
    assert v3_container.status == "exited"

    assert known_good.get(svc) == f"{svc}:v1"

    # --- (d) retired-sha guard: redeploying v3 (whose container still
    # exists, stopped) is refused outright, with no new build. ---
    with patch("fleetmcp.deploy_watcher.deploy_manager.build_image") as mock_build:
        result_v3_again = manager.deploy(svc, svc, "v3")

    assert result_v3_again.success is False
    assert "retired" in result_v3_again.reason
    mock_build.assert_not_called()
