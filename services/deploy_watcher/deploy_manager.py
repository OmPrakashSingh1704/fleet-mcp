from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import docker.errors

from services.deploy_watcher.health import wait_for_healthy
from services.deploy_watcher.image_builder import build_image
from services.deploy_watcher.known_good import KnownGoodStore
from services.deploy_watcher.registry import ServiceRegistry

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

        new_container = None
        phase = "build"
        try:
            build_image(
                self._docker,
                context_path=self._repo_root,
                dockerfile=f"{service_path}/Dockerfile",
                tag=image_tag,
            )
            phase = "run"
            new_container = self._docker.containers.run(
                image_tag, **self._run_kwargs(new_container_name)
            )
        except _DOCKER_ERRORS as exc:
            if new_container is not None:
                self._stop_and_remove(new_container)
            return DeployResult(success=False, image_tag=image_tag, reason=f"{phase} failed: {exc}")

        health_check_url = self._health_url_resolver(new_container, health_check_port)
        if not wait_for_healthy(health_check_url):
            self._stop_and_remove(new_container)
            return DeployResult(success=False, image_tag=image_tag, reason="failed initial health check")

        old_container_name = self._registry.get_active_container(service_name)
        self._registry.set_active_container(service_name, new_container_name)

        if old_container_name:
            self._stop_ignore_not_found(old_container_name)

        threading.Thread(
            target=self._run_probation,
            args=(service_name, new_container_name, health_check_port, image_tag),
            daemon=True,
        ).start()

        return DeployResult(success=True, image_tag=image_tag)

    def rollback(self, service_name: str) -> DeployResult:
        good_tag = self._known_good.get(service_name)
        if good_tag is None:
            # Nothing has ever proven itself for this service (e.g. the
            # first-ever deploy is still in probation) -- there is no
            # better image to serve, so leave whatever is running alone.
            return DeployResult(success=False, image_tag="", reason="no known-good image on record")

        active_container_name = self._registry.get_active_container(service_name)
        if active_container_name:
            self._stop_ignore_not_found(active_container_name)

        rollback_container_name = f"{service_name}-rollback-{int(time.time())}"
        self._docker.containers.run(good_tag, **self._run_kwargs(rollback_container_name))
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

            healthy = self._check_probation_once(container_name, health_check_port)
            if not healthy:
                if self._registry.get_active_container(service_name) != container_name:
                    return
                self.rollback(service_name)
                return

            time.sleep(10)

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

    def _stop_and_remove(self, container) -> None:
        try:
            container.stop()
        except docker.errors.NotFound:
            pass
        try:
            container.remove()
        except docker.errors.NotFound:
            pass

    def _stop_ignore_not_found(self, container_name: str) -> None:
        try:
            self._docker.containers.get(container_name).stop()
        except docker.errors.NotFound:
            pass
