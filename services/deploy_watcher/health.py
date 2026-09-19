from __future__ import annotations

import time

import requests


def wait_for_healthy(
    url: str,
    required_successes: int = 3,
    interval_seconds: float = 2.0,
    timeout_seconds: float = 60.0,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    consecutive = 0
    while time.monotonic() < deadline:
        if _check_once(url):
            consecutive += 1
            if consecutive >= required_successes:
                return True
        else:
            consecutive = 0
        time.sleep(interval_seconds)
    return False


def _check_once(url: str) -> bool:
    try:
        response = requests.get(url, timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False
