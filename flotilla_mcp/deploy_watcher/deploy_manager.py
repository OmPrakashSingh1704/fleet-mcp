from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

import docker.errors

from flotilla_mcp.deploy_watcher.health import wait_for_healthy
from flotilla_mcp.deploy_watcher.image_builder import build_image
from flotilla_mcp.deploy_watcher.known_good import KnownGoodStore
from flotilla_mcp.deploy_watcher.registry import ServiceRegistry

_logger = logging.getLogger(__name__)

_DOCKER_ERRORS = (docker.errors.BuildError, docker.errors.APIError, docker.errors.ImageNotFound)

# These are always set explicitly by DeployManager and can never be
# overridden by a caller-supplied run_options dict.
_RESERVED_RUN_KWARGS = {"image", "detach", "name", "network"}


@dataclass
class DeployResult:
    success: bool
    image_tag: str
    reason: str = ""


def _default_health_url_resolver(container: Any, port: int) -> str:
    return f"http://{container.name}:{port}/health"


class DeployManager:
    """Blue/green deploy orchestrator for a single fleet service.

    Flow: build a new image, start a new container alongside the old one,
    wait for it to prove healthy, flip routing in the registry, stop (but
    keep, for rollback) the old container, then watch the new container
    through a probation window. Only a probation window that completes
    without a single failed check promotes the new tag to "known-good" --
    recording it any earlier would let a probation failure roll back onto
    the same broken image that just failed.

    Every docker-facing operation is defensive: deploy() and rollback()
    never raise, and the probation monitor never dies silently on an
    unexpected error -- it logs and treats the error as a failed check.
    """

    def __init__(
        self,
        docker_client,
        registry: ServiceRegistry,
        known_good: KnownGoodStore,
        probation_seconds: float = 1800.0,
        repo_root: str = ".",
        run_options: Optional[dict] = None,
        health_url_resolver: Optional[Callable[[Any, int], str]] = None,
    ):
        self._docker = docker_client
        self._registry = registry
        self._known_good = known_good
        self._probation_seconds = probation_seconds
        self._repo_root = repo_root
        self._run_options = run_options
        self._health_url_resolver = health_url_resolver or _default_health_url_resolver
        # Per-service locks serialize every registry "read active -> act ->
        # write active" section (deploy's flip, rollback's check-and-perform,
        # probation's promotion), so a probation rollback can never interleave
        # with a newer deploy's flip. Never held across a build or the initial
        # health wait.
        self._locks_guard = threading.Lock()
        self._service_locks: dict[str, threading.Lock] = {}

    def _service_lock(self, service_name: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._service_locks.get(service_name)
            if lock is None:
                lock = threading.Lock()
                self._service_locks[service_name] = lock
            return lock

    def deploy(
        self,
        service_name: str,
        service_path: str,
        commit_sha: str,
        health_check_port: int = 8080,
    ) -> DeployResult:
        image_tag = f"{service_name}:{commit_sha}"
        new_container_name = f"{service_name}-{commit_sha}"

        # Idempotency: a watcher restart re-polls the current commit SHA. If
        # it is already the active container, there is nothing to do -- and
        # trying to redo it would collide on the container name.
        if self._registry.get_active_container(service_name) == new_container_name:
            return DeployResult(success=True, image_tag=image_tag, reason="already active")

        # Retired-sha guard: a container for this exact sha already exists
        # but isn't active, meaning it was previously promoted-then-retired
        # (rolled back, or superseded and stopped). Redeploying it would
        # collide on the container name for no benefit -- refuse instead.
        if self._container_exists(new_container_name):
            return DeployResult(success=False, image_tag=image_tag, reason="sha previously retired; not redeploying")

        phase = "build"
        try:
            build_image(
                self._docker,
                context_path=self._repo_root,
                dockerfile=f"{service_path}/Dockerfile",
                tag=image_tag,
            )
            phase = "run"
            new_container = self._docker.containers.run(image_tag, **self._run_kwargs(new_container_name))
        except _DOCKER_ERRORS as exc:
            if phase == "run":
                # docker-py's containers.run() creates the container before
                # starting it; if starting fails, run() raises but the
                # created container is left behind under the name we asked
                # for. Clean it up so a future deploy of this sha doesn't
                # collide.
                self._force_remove_if_exists(new_container_name)
            return DeployResult(success=False, image_tag=image_tag, reason=f"{phase} failed: {exc}")

        health_check_url = self._health_url_resolver(new_container, health_check_port)
        if not wait_for_healthy(health_check_url):
            self._stop_and_remove(new_container)
            return DeployResult(success=False, image_tag=image_tag, reason="failed initial health check")

        with self._service_lock(service_name):
            old_container_name = self._registry.get_active_container(service_name)
            self._registry.set_active_container(service_name, new_container_name)

            # Best-effort: a failure stopping the old container must not stop
            # the new release from going live or from being watched by
            # probation -- the registry has already flipped.
            if old_container_name:
                self._stop_ignore_not_found(old_container_name)

        threading.Thread(
            target=self._run_probation,
            args=(service_name, new_container_name, health_check_port, image_tag),
            daemon=True,
        ).start()

        return DeployResult(success=True, image_tag=image_tag)

    def rollback(self, service_name: str) -> DeployResult:
        """Roll back whatever is currently active for ``service_name``."""
        good_tag = self._known_good.get(service_name)
        if good_tag is None:
            # Nothing has ever proven itself for this service (e.g. the
            # first-ever deploy is still in probation) -- there is no
            # better image to serve, so leave whatever is running alone.
            return DeployResult(success=False, image_tag="", reason="no known-good image on record")

        with self._service_lock(service_name):
            active_container_name = self._registry.get_active_container(service_name)
            return self._perform_rollback(service_name, active_container_name, good_tag)

    def _rollback(self, service_name: str, expected_active: str) -> DeployResult:
        """Roll back only if ``expected_active`` is still the active container.

        Used by the probation monitor, which may be racing a newer deploy:
        re-reads the registry immediately before acting, and does nothing
        at all if the service has moved on.
        """
        with self._service_lock(service_name):
            active_container_name = self._registry.get_active_container(service_name)
            if active_container_name != expected_active:
                return DeployResult(success=False, image_tag="", reason="superseded")

            good_tag = self._known_good.get(service_name)
            if good_tag is None:
                return DeployResult(success=False, image_tag="", reason="no known-good image on record")

            return self._perform_rollback(service_name, active_container_name, good_tag)

    def _perform_rollback(
        self, service_name: str, active_container_name: Optional[str], good_tag: str
    ) -> DeployResult:
        rollback_container_name = f"{service_name}-rollback-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        try:
            if active_container_name:
                self._stop_ignore_not_found(active_container_name)
            self._docker.containers.run(good_tag, **self._run_kwargs(rollback_container_name))
        except (docker.errors.APIError, docker.errors.ImageNotFound, docker.errors.NotFound) as exc:
            # Starting the known-good image failed. We may have already
            # stopped the (failing) active container -- try to bring it
            # back rather than leave the service with nothing running.
            # Leave the registry untouched: it still points at whatever we
            # just tried (and failed) to restore.
            if active_container_name:
                self._try_restart(active_container_name)
            return DeployResult(success=False, image_tag=good_tag, reason=f"rollback run failed: {exc}")

        self._registry.set_active_container(service_name, rollback_container_name)
        return DeployResult(success=True, image_tag=good_tag, reason="rolled back to known-good")

    def _run_probation(
        self, service_name: str, container_name: str, health_check_port: int, image_tag: str
    ) -> None:
        deadline = time.monotonic() + self._probation_seconds

        while time.monotonic() < deadline:
            if self._registry.get_active_container(service_name) != container_name:
                # A newer deploy superseded this one; this monitor is stale
                # and must not act.
                return

            try:
                healthy = self._check_probation_once(container_name, health_check_port)
            except Exception:
                # A custom health_url_resolver, containers.get, or anything
                # else in the check path can raise. The monitor must never
                # die silently -- log it and treat it like a failed check,
                # which routes through the normal (staleness-checked)
                # rollback path.
                _logger.warning(
                    "Unexpected error during probation health check for %s (%s); treating as a failed check",
                    service_name,
                    container_name,
                    exc_info=True,
                )
                healthy = False

            if not healthy:
                self._rollback(service_name, container_name)
                return

            time.sleep(10)

        with self._service_lock(service_name):
            if self._registry.get_active_container(service_name) == container_name:
                self._known_good.record(service_name, image_tag)

    def _check_probation_once(self, container_name: str, health_check_port: int) -> bool:
        try:
            container = self._docker.containers.get(container_name)
        except docker.errors.NotFound:
            return False
        health_check_url = self._health_url_resolver(container, health_check_port)
        return wait_for_healthy(
            health_check_url, required_successes=1, interval_seconds=2.0, timeout_seconds=5.0
        )

    def _run_kwargs(self, container_name: str) -> dict:
        extra = {k: v for k, v in (self._run_options or {}).items() if k not in _RESERVED_RUN_KWARGS}
        return {**extra, "detach": True, "name": container_name, "network": "mcp-fleet"}

    def _container_exists(self, container_name: str) -> bool:
        try:
            self._docker.containers.get(container_name)
        except docker.errors.NotFound:
            return False
        except docker.errors.APIError as exc:
            _logger.warning(
                "Could not check whether container %s already exists: %s; assuming it does not",
                container_name,
                exc,
            )
            return False
        return True

    def _try_restart(self, container_name: str) -> None:
        try:
            self._docker.containers.get(container_name).start()
        except Exception as exc:  # best-effort recovery; must never raise
            _logger.warning(
                "Failed to restart previously active container %s after a rollback failure: %s",
                container_name,
                exc,
            )

    def _force_remove_if_exists(self, container_name: str) -> None:
        try:
            self._docker.containers.get(container_name).remove(force=True)
        except docker.errors.NotFound:
            pass
        except docker.errors.APIError as exc:
            _logger.warning("Failed to force-remove leftover container %s: %s", container_name, exc)

    def _stop_and_remove(self, container) -> None:
        try:
            container.stop()
        except docker.errors.NotFound:
            pass
        except docker.errors.APIError as exc:
            _logger.warning("Failed to stop container %r: %s", container, exc)
        try:
            container.remove()
        except docker.errors.NotFound:
            pass
        except docker.errors.APIError as exc:
            _logger.warning("Failed to remove container %r: %s", container, exc)

    def _stop_ignore_not_found(self, container_name: str) -> None:
        try:
            self._docker.containers.get(container_name).stop()
        except docker.errors.NotFound:
            pass
        except docker.errors.APIError as exc:
            _logger.warning("Failed to stop container %s: %s", container_name, exc)
