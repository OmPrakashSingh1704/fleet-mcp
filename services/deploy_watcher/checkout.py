from __future__ import annotations

import os
import re
import subprocess

_SHA_RE = re.compile(r"[0-9a-fA-F]{7,40}")
_URL_USERINFO_RE = re.compile(r"(?P<scheme>\b[a-zA-Z][a-zA-Z0-9+.-]*://)[^/\s@]+@")

TOKEN_ENV_VAR = "WATCHER_GITHUB_TOKEN"

# Reads the token from the environment at call time, so the token value never
# appears in argv, a URL, .git/config or logs. The empty credential.helper
# before it clears every inherited helper.
CREDENTIAL_HELPER = (
    '!f() { echo username=x-access-token; echo "password=$' + TOKEN_ENV_VAR + '"; }; f'
)


class CheckoutError(Exception):
    pass


def _redact(remote_url: str, message: str) -> str:
    # The remote URL may embed a credential (e.g. https://<token>@github.com/...),
    # so it must never appear verbatim in a raised error message.
    if remote_url:
        message = message.replace(remote_url, "<remote>")
    token = os.environ.get(TOKEN_ENV_VAR, "")
    if token:
        message = message.replace(token, "<redacted>")
    return _URL_USERINFO_RE.sub(r"\g<scheme>", message)


def _run_git(args: list[str], remote_url: str, cwd: str | None = None) -> None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(
        [
            "git",
            "-c", "credential.helper=",
            "-c", f"credential.helper={CREDENTIAL_HELPER}",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise CheckoutError(_redact(remote_url, f"git {' '.join(args)} failed: {result.stderr}"))


def sync_checkout(remote_url: str, checkout_dir: str, sha: str) -> None:
    """Ensure ``checkout_dir`` is a checkout of ``remote_url`` at ``sha``.

    Clones on first use (when ``checkout_dir`` has no ``.git``), otherwise
    reuses the existing clone. Always fetches ``origin`` and then does a
    detached checkout of ``sha``, so the checkout ends up exactly at the
    requested commit regardless of what branch/commit it was on before.

    Authentication for private repos comes from WATCHER_GITHUB_TOKEN via a
    credential helper (see CREDENTIAL_HELPER); never embed a token in
    ``remote_url``.

    ``sha`` is validated as a plain hex commit sha before it ever reaches a
    git subprocess -- it may come from an untrusted source (e.g. a GitHub
    API response), and passing it straight into ``git checkout <sha>``
    without validation would let something shaped like an option (e.g.
    ``-B`` or ``--orphan=x``) be interpreted as a git flag instead of a
    revision. The raw value is never echoed back in the error, since it's
    attacker-shaped input.
    """
    if not _SHA_RE.fullmatch(sha):
        raise CheckoutError("invalid commit sha")

    if not os.path.isdir(os.path.join(checkout_dir, ".git")):
        _run_git(["clone", "--", remote_url, checkout_dir], remote_url)

    _run_git(["fetch", "origin"], remote_url, cwd=checkout_dir)
    _run_git(["checkout", "--detach", sha], remote_url, cwd=checkout_dir)
