import subprocess
from unittest.mock import patch

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


def test_sync_checkout_redacts_remote_url_containing_token_on_fetch_failure(tmp_path):
    # A clone can succeed against a legitimate remote, then a later sync
    # against the same checkout_dir can be pointed at a different (bad)
    # remote -- exercising the fetch failure path (as opposed to the clone
    # failure path already covered above) still must not leak a token
    # embedded in that remote URL.
    remote_url = _init_bare_remote(tmp_path)
    checkout_dir = tmp_path / "checkout"
    sha_a = _run(["ls-remote", remote_url, "main"]).stdout.split()[0]

    sync_checkout(remote_url, str(checkout_dir), sha_a)

    bad_remote = "https://secret-token@example.invalid/nonexistent/repo.git"
    _run(["remote", "set-url", "origin", bad_remote], cwd=checkout_dir)

    with pytest.raises(CheckoutError) as exc_info:
        sync_checkout(bad_remote, str(checkout_dir), sha_a)

    # Note: git itself already strips embedded credentials from the URL it
    # echoes back in a "fatal: unable to access ..." message on a host
    # resolution failure, so this doesn't also assert "<remote>" is in the
    # message the way the clone-failure case above does -- what matters is
    # that the token never appears.
    message = str(exc_info.value)
    assert "secret-token" not in message


@pytest.mark.parametrize(
    "bad_sha",
    ["-B", "--orphan=x", "abc", "g" * 40, ""],
)
def test_sync_checkout_rejects_option_shaped_or_malformed_sha_without_invoking_git(tmp_path, bad_sha):
    checkout_dir = tmp_path / "checkout"

    with patch("services.deploy_watcher.checkout.subprocess.run") as mock_run:
        with pytest.raises(CheckoutError):
            sync_checkout("git@example.invalid:org/repo.git", str(checkout_dir), bad_sha)

    mock_run.assert_not_called()


# --- Final fix wave: I-2 credential helper + redaction for the watcher ---

WATCHER_SECRET = "ghp_WATCHERSECRETVALUE456"


def test_clone_and_fetch_use_env_reading_credential_helper_without_token_in_argv(tmp_path, monkeypatch):
    import subprocess as _subprocess

    from services.deploy_watcher import checkout

    monkeypatch.setenv("WATCHER_GITHUB_TOKEN", WATCHER_SECRET)

    def ok(*args, **kwargs):
        return _subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

    with patch("services.deploy_watcher.checkout.subprocess.run", side_effect=ok) as mock_run:
        sync_checkout("https://github.com/org/private.git", str(tmp_path / "co"), "a" * 40)

    subcommands = []
    for call in mock_run.call_args_list:
        argv = call.args[0]
        subcommands.append(argv[5])
        assert argv[1:5] == ["-c", "credential.helper=", "-c", f"credential.helper={checkout.CREDENTIAL_HELPER}"]
        assert "$WATCHER_GITHUB_TOKEN" in checkout.CREDENTIAL_HELPER
        assert WATCHER_SECRET not in " ".join(argv)
        assert call.kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert subcommands == ["clone", "fetch", "checkout"]


def test_checkout_error_strips_userinfo_and_token(monkeypatch, tmp_path):
    import subprocess as _subprocess

    monkeypatch.setenv("WATCHER_GITHUB_TOKEN", WATCHER_SECRET)
    stderr = f"fatal: https://bob:pw123@evil.example/x failed; token={WATCHER_SECRET}"

    def fail(*args, **kwargs):
        return _subprocess.CompletedProcess(args=args[0], returncode=128, stdout="", stderr=stderr)

    with patch("services.deploy_watcher.checkout.subprocess.run", side_effect=fail):
        with pytest.raises(CheckoutError) as exc_info:
            sync_checkout("https://github.com/org/repo.git", str(tmp_path / "co"), "a" * 40)

    message = str(exc_info.value)
    assert "pw123" not in message
    assert "bob:" not in message
    assert WATCHER_SECRET not in message
    assert "https://evil.example/x" in message
