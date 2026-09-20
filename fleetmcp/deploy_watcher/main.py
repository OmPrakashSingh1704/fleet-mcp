from __future__ import annotations

import logging
import os
import time
from typing import Callable

import docker
import requests
from github import GithubException

from fleetmcp.common.manifest import FleetManifest
from fleetmcp.deploy_watcher.checkout import CheckoutError, sync_checkout
from fleetmcp.deploy_watcher.deploy_manager import DeployManager, DeployResult
from fleetmcp.deploy_watcher.github_poller import GitHubPoller
from fleetmcp.deploy_watcher.known_good import KnownGoodStore
from fleetmcp.deploy_watcher.registry import ServiceRegistry

_logger = logging.getLogger(__name__)

CheckoutFn = Callable[[str, str, str], None]


def run_once(
    poller: GitHubPoller,
    manager: DeployManager,
    checkout_fn: CheckoutFn,
    remote_url: str,
    checkout_dir: str,
) -> list[tuple[str, DeployResult]]:
    """Poll once and, if there's a new commit, check it out and deploy it.

    Builds are done from a fresh checkout of the new commit -- never from
    the watcher's own baked-in source, which would only ever contain the
    code from when the watcher image itself was built. The fleet manifest
    is likewise read from that checkout: the newly merged commit is the
    source of truth for which services exist and are protected.

    A failure in one service's deploy is recorded but never blocks the
    others -- everything (checkout, manifest, deploys) happens under this
    single new sha, so a bad service doesn't take down a fleet-wide
    rollout.

    Known limitation: if checkout_fn raises, this raises too, and the
    caller (run()) will have already had the poller mark this sha as seen.
    That sha will not be retried until a newer commit lands.
    """
    sha = poller.poll_once()
    if sha is None:
        return []

    checkout_fn(remote_url, checkout_dir, sha)

    manifest = FleetManifest.load(os.path.join(checkout_dir, "fleet_manifest.yaml"))

    results: list[tuple[str, DeployResult]] = []
    for service in manifest.all_services():
        if service.protected or not service.container:
            continue

        try:
            result = manager.deploy(service.name, service.path, sha)
        except Exception as exc:  # noqa: BLE001 - one bad service must not block the rest
            _logger.exception("Unexpected error deploying service %s", service.name)
            result = DeployResult(success=False, image_tag="", reason=f"unexpected error: {exc}")

        if result.success:
            _logger.info("Deployed %s: %s (%s)", service.name, result.image_tag, result.reason)
        else:
            _logger.warning("Failed to deploy %s: %s", service.name, result.reason)

        results.append((service.name, result))

    return results


def _loop_iteration(
    poller: GitHubPoller,
    manager: DeployManager,
    checkout_fn: CheckoutFn,
    remote_url: str,
    checkout_dir: str,
) -> None:
    """One iteration of the poll loop: run_once(), with every failure mode
    contained so the loop itself never dies.

    Expected/known failure shapes (GitHub API errors, network errors,
    checkout failures) are logged as warnings -- transient, and the next
    poll will likely recover. Anything else (e.g. a malformed
    fleet_manifest.yaml in the merged commit -- yaml.YAMLError, KeyError,
    OSError, ...) is logged at exception level and swallowed too: the
    poller's seen-sha state resets on a fresh process, so letting an
    unexpected error propagate and kill the watcher would let a supervisor
    restart crash-loop forever on the same bad commit.
    """
    try:
        run_once(poller, manager, checkout_fn, remote_url, checkout_dir)
    except (GithubException, requests.RequestException, CheckoutError) as exc:
        _logger.warning("Poll cycle failed, will retry next interval: %s", exc)
    except Exception:
        _logger.exception("unexpected error in deploy loop; continuing")


def run() -> None:
    logging.basicConfig(level=logging.INFO)

    # Read-only token (contents: read). git auth for the checkout reads the
    # same WATCHER_GITHUB_TOKEN via a credential helper -- see checkout.py.
    token = os.environ["WATCHER_GITHUB_TOKEN"]
    repo_full_name = os.environ["GITHUB_REPO_FULL_NAME"]
    remote_url = os.environ["REPO_REMOTE"]
    checkout_dir = os.environ.get("CHECKOUT_DIR", "/data/checkout")
    registry_path = os.environ.get("REGISTRY_PATH", "/data/service_registry.json")
    known_good_path = os.environ.get("KNOWN_GOOD_PATH", "/data/known_good.json")
    poll_interval = float(os.environ.get("POLL_INTERVAL_SECONDS", "30"))

    docker_client = docker.from_env()
    registry = ServiceRegistry(registry_path)
    known_good = KnownGoodStore(known_good_path)
    manager = DeployManager(docker_client, registry, known_good, repo_root=checkout_dir)
    poller = GitHubPoller(token, repo_full_name)

    # Never log remote_url or token: the remote URL may embed a token.
    _logger.info("Deploy watcher starting; polling every %s seconds", poll_interval)

    while True:
        _loop_iteration(poller, manager, sync_checkout, remote_url, checkout_dir)
        time.sleep(poll_interval)


if __name__ == "__main__":
    run()
