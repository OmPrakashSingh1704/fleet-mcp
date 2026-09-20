from __future__ import annotations

import re
import subprocess

# Matches https://github.com/o/r, https://user@github.com/o/r.git, with an
# optional trailing slash. Case-insensitive: GitHub hostnames are not
# case-sensitive, and neither is the https:// scheme.
_HTTPS_RE = re.compile(
    r"^https?://(?:[^@/]+@)?github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
# Matches the SCP-like form: git@github.com:o/r(.git)?
_SCP_RE = re.compile(
    r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
# Matches the explicit ssh:// form: ssh://git@github.com/o/r(.git)?
_SSH_RE = re.compile(
    r"^ssh://git@github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)

_PATTERNS = (_HTTPS_RE, _SCP_RE, _SSH_RE)


def detect_remote_url(cwd: str | None = None) -> str | None:
    """Return the ``origin`` remote URL for the git repo at ``cwd``, or None.

    Never raises: git not installed, ``cwd`` not a git repo, or no
    ``origin`` remote all come back as "nothing detected" rather than an
    exception -- callers decide what a missing remote means.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    return url or None


def parse_github_full_name(remote_url: str) -> str | None:
    """Parse ``owner/repo`` out of a GitHub remote URL.

    Handles ``https://github.com/o/r(.git)``,
    ``git@github.com:o/r(.git)``, ``ssh://git@github.com/o/r.git``, and a
    trailing slash on any of those. Returns None for a non-GitHub host, a
    local filesystem path, or anything else that doesn't match -- a wrong
    guess is worse than no guess.
    """
    if not remote_url:
        return None
    candidate = remote_url.strip()
    for pattern in _PATTERNS:
        match = pattern.match(candidate)
        if match:
            return f"{match.group('owner')}/{match.group('repo')}"
    return None
