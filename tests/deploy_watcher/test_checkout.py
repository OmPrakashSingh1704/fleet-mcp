import subprocess

import pytest

from services.deploy_watcher.checkout import CheckoutError, sync_checkout


def _run(args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_bare_remote(tmp_path) -> str:
    remote_dir = tmp_path / "remote.git"
    _run(["init", "--bare", str(remote_dir)])

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    _run(["init"], cwd=seed_dir)
    _run(["config", "user.email", "seed@example.com"], cwd=seed_dir)
    _run(["config", "user.name", "Seed"], cwd=seed_dir)
    (seed_dir / "README.md").write_text("seed")
    _run(["add", "-A"], cwd=seed_dir)
    _run(["commit", "-m", "seed"], cwd=seed_dir)
    _run(["branch", "-M", "main"], cwd=seed_dir)
    _run(["remote", "add", "origin", str(remote_dir)], cwd=seed_dir)
    _run(["push", "origin", "main"], cwd=seed_dir)
    return str(remote_dir)


def _push_new_commit(remote_url: str, tmp_path, filename: str, content: str) -> str:
    """Push a new commit containing ``filename`` to the bare remote, from a
    throwaway clone, and return its sha."""
    pusher_dir = tmp_path / f"pusher-{filename}"
    _run(["clone", remote_url, str(pusher_dir)])
    _run(["checkout", "-B", "main", "origin/main"], cwd=pusher_dir)
    _run(["config", "user.email", "seed@example.com"], cwd=pusher_dir)
    _run(["config", "user.name", "Seed"], cwd=pusher_dir)
    (pusher_dir / filename).write_text(content)
    _run(["add", "-A"], cwd=pusher_dir)
    _run(["commit", "-m", f"add {filename}"], cwd=pusher_dir)
    _run(["push", "origin", "main"], cwd=pusher_dir)
    sha = _run(["rev-parse", "HEAD"], cwd=pusher_dir).stdout.strip()
    return sha


def test_sync_checkout_clones_then_updates_to_new_pushed_commit(tmp_path):
    remote_url = _init_bare_remote(tmp_path)
    checkout_dir = tmp_path / "checkout"

    sha_a = _run(["ls-remote", remote_url, "main"]).stdout.split()[0]

    sync_checkout(remote_url, str(checkout_dir), sha_a)
    head_a = _run(["rev-parse", "HEAD"], cwd=checkout_dir).stdout.strip()
    assert head_a == sha_a

    sha_b = _push_new_commit(remote_url, tmp_path, "new_file.txt", "hello")

    sync_checkout(remote_url, str(checkout_dir), sha_b)

    assert (checkout_dir / "new_file.txt").read_text() == "hello"
    head_b = _run(["rev-parse", "HEAD"], cwd=checkout_dir).stdout.strip()
    assert head_b == sha_b


def test_sync_checkout_raises_checkout_error_on_invalid_sha(tmp_path):
    remote_url = _init_bare_remote(tmp_path)
    checkout_dir = tmp_path / "checkout"

    with pytest.raises(CheckoutError):
        sync_checkout(remote_url, str(checkout_dir), "not-a-real-sha")


def test_sync_checkout_redacts_remote_url_containing_token_on_error(tmp_path):
    checkout_dir = tmp_path / "checkout"
    bogus_remote = "https://secret-token@example.invalid/nonexistent/repo.git"

    with pytest.raises(CheckoutError) as exc_info:
        sync_checkout(bogus_remote, str(checkout_dir), "deadbeef")

    message = str(exc_info.value)
    assert "secret-token" not in message
    assert "<remote>" in message
