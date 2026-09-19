from unittest.mock import MagicMock, patch

import yaml

from services.deploy_watcher.deploy_manager import DeployResult
from services.deploy_watcher.main import _loop_iteration, run_once

_MANIFEST_YAML = """
services:
  service-a:
    path: services/service_a
    protected: false
    container: service-a
  service-b:
    path: services/service_b
    protected: false
    container: service-b
  protected-service:
    path: services/protected_service
    protected: true
    container: protected-service
  no-container-service:
    path: services/no_container_service
    protected: false
"""

_DIFFERENT_MANIFEST_YAML = """
services:
  only-in-checkout:
    path: services/only_in_checkout
    protected: false
    container: only-in-checkout
"""


class FakePoller:
    def __init__(self, sha):
        self._sha = sha

    def poll_once(self):
        return self._sha


def _write_manifest(dir_path, contents=_MANIFEST_YAML):
    (dir_path / "fleet_manifest.yaml").write_text(contents)


def test_no_new_sha_means_no_checkout_and_no_deploys(tmp_path):
    poller = FakePoller(None)
    manager = MagicMock()
    checkout_fn = MagicMock()
    checkout_dir = tmp_path / "checkout"
    checkout_dir.mkdir()

    results = run_once(poller, manager, checkout_fn, "git@remote", str(checkout_dir))

    assert results == []
    checkout_fn.assert_not_called()
    manager.deploy.assert_not_called()


def test_new_sha_checks_out_and_deploys_only_unprotected_services_with_container(tmp_path):
    poller = FakePoller("sha-123")
    manager = MagicMock()
    manager.deploy.return_value = DeployResult(success=True, image_tag="tag:sha-123")
    checkout_dir = tmp_path / "checkout"
    checkout_dir.mkdir()

    def checkout_fn(remote_url, dir_path, sha):
        _write_manifest(tmp_path / "checkout")

    results = run_once(poller, manager, checkout_fn, "git@remote", str(checkout_dir))

    assert manager.deploy.call_count == 2
    deployed_names = {call.args[0] for call in manager.deploy.call_args_list}
    assert deployed_names == {"service-a", "service-b"}
    for call in manager.deploy.call_args_list:
        assert call.args[2] == "sha-123"

    assert {name for name, _ in results} == {"service-a", "service-b"}


def test_checkout_fn_called_with_remote_and_dir_and_sha(tmp_path):
    poller = FakePoller("sha-abc")
    manager = MagicMock()
    manager.deploy.return_value = DeployResult(success=True, image_tag="t")
    checkout_dir = tmp_path / "checkout"
    checkout_dir.mkdir()
    checkout_fn = MagicMock(side_effect=lambda remote_url, dir_path, sha: _write_manifest(checkout_dir))

    run_once(poller, manager, checkout_fn, "git@my-remote", str(checkout_dir))

    checkout_fn.assert_called_once_with("git@my-remote", str(checkout_dir), "sha-abc")


def test_one_deploy_raising_does_not_block_the_others(tmp_path):
    poller = FakePoller("sha-999")
    manager = MagicMock()

    def fake_deploy(service_name, service_path, sha, *args, **kwargs):
        if service_name == "service-a":
            raise RuntimeError("boom")
        return DeployResult(success=True, image_tag=f"{service_name}:{sha}")

    manager.deploy.side_effect = fake_deploy
    checkout_dir = tmp_path / "checkout"
    checkout_dir.mkdir()

    def checkout_fn(remote_url, dir_path, sha):
        _write_manifest(checkout_dir)

    results = run_once(poller, manager, checkout_fn, "git@remote", str(checkout_dir))

    results_by_name = dict(results)
    assert set(results_by_name) == {"service-a", "service-b"}
    assert results_by_name["service-a"].success is False
    assert "boom" in results_by_name["service-a"].reason
    assert results_by_name["service-b"].success is True


def test_manifest_is_read_from_checkout_dir_not_repo_root(tmp_path, monkeypatch):
    # Write a different manifest at the "repo root" (cwd) than in the
    # checkout dir, to prove the checkout dir's manifest wins.
    repo_root = tmp_path / "repo_root"
    repo_root.mkdir()
    (repo_root / "fleet_manifest.yaml").write_text(_MANIFEST_YAML)
    monkeypatch.chdir(repo_root)

    checkout_dir = tmp_path / "checkout"
    checkout_dir.mkdir()

    poller = FakePoller("sha-1")
    manager = MagicMock()
    manager.deploy.return_value = DeployResult(success=True, image_tag="t")

    def checkout_fn(remote_url, dir_path, sha):
        _write_manifest(checkout_dir, _DIFFERENT_MANIFEST_YAML)

    results = run_once(poller, manager, checkout_fn, "git@remote", str(checkout_dir))

    assert {name for name, _ in results} == {"only-in-checkout"}


def test_loop_iteration_swallows_unexpected_error_and_does_not_propagate(tmp_path):
    # A malformed fleet_manifest.yaml in a merged commit (or any other
    # unanticipated failure) must not kill the poll loop: the poller's
    # seen-sha state resets on process restart, so letting this escape
    # would crash-loop the watcher on the same bad commit forever.
    poller = MagicMock()
    manager = MagicMock()
    checkout_fn = MagicMock()

    with patch(
        "services.deploy_watcher.main.run_once",
        side_effect=yaml.YAMLError("bad manifest"),
    ) as mock_run_once, patch("services.deploy_watcher.main._logger") as mock_logger:
        _loop_iteration(poller, manager, checkout_fn, "git@remote", str(tmp_path))

    mock_run_once.assert_called_once()
    mock_logger.exception.assert_called_once()
