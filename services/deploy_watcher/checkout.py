from __future__ import annotations

import os
import re
import subprocess

_SHA_RE = re.compile(r"[0-9a-fA-F]{7,40}")


class CheckoutError(Exception):
    pass


def _redact(remote_url: str, message: str) -> str:
    # The remote URL may embed a token (e.g. https://<token>@github.com/...),
    # so it must never appear verbatim in a raised error message.
    return message.replace(remote_url, "<remote>")


def _run_git(args: list[str], remote_url: str, cwd: str | None = None) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise CheckoutError(_redact(remote_url, f"git {' '.join(args)} failed: {result.stderr}"))


def sync_checkout(remote_url: str, checkout_dir: str, sha: str) -> None:
    """Ensure ``checkout_dir`` is a checkout of ``remote_url`` at ``sha``.

    Clones on first use (when ``checkout_dir`` has no ``.git``), otherwise
    reuses the existing clone. Always fetches ``origin`` and then does a
    detached checkout of ``sha``, so the checkout ends up exactly at the
    requested commit regardless of what branch/commit it was on before.

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
        _run_git(["clone", remote_url, checkout_dir], remote_url)

    _run_git(["fetch", "origin"], remote_url, cwd=checkout_dir)
    _run_git(["checkout", "--detach", sha], remote_url, cwd=checkout_dir)
