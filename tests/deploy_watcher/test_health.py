from unittest.mock import patch

import requests

from services.deploy_watcher.health import wait_for_healthy


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


@patch("services.deploy_watcher.health.time.sleep", return_value=None)
@patch("services.deploy_watcher.health.requests.get")
def test_wait_for_healthy_returns_true_after_required_successes(mock_get, _mock_sleep):
    mock_get.return_value = _FakeResponse(200)

    result = wait_for_healthy("http://svc/health", required_successes=3, interval_seconds=0, timeout_seconds=5)

    assert result is True
    assert mock_get.call_count >= 3


@patch("services.deploy_watcher.health.time.sleep", return_value=None)
@patch("services.deploy_watcher.health.requests.get")
def test_wait_for_healthy_resets_streak_on_failure(mock_get, _mock_sleep):
    mock_get.side_effect = [
        _FakeResponse(200),
        _FakeResponse(500),
        _FakeResponse(200),
        _FakeResponse(200),
        _FakeResponse(200),
    ]

    result = wait_for_healthy("http://svc/health", required_successes=3, interval_seconds=0, timeout_seconds=5)

    assert result is True
    assert mock_get.call_count == 5


@patch("services.deploy_watcher.health.time.monotonic")
@patch("services.deploy_watcher.health.time.sleep", return_value=None)
@patch("services.deploy_watcher.health.requests.get")
def test_wait_for_healthy_times_out_and_returns_false(mock_get, _mock_sleep, mock_monotonic):
    mock_get.side_effect = requests.RequestException("connection refused")
    mock_monotonic.side_effect = [0, 1, 2, 100]

    result = wait_for_healthy("http://svc/health", required_successes=3, interval_seconds=0, timeout_seconds=5)

    assert result is False
