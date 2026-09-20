"""Fail unless a release tag (vX.Y.Z) matches flotilla_mcp.__version__."""
from __future__ import annotations

import pathlib
import re
import sys

_TAG = re.compile(r"^v(\d+\.\d+\.\d+)$")


def check(tag: str, version: str) -> None:
    m = _TAG.match(tag)
    if not m or m.group(1) != version:
        print(f"tag {tag!r} does not match flotilla_mcp.__version__ {version!r} (expected 'v{version}')", file=sys.stderr)
        raise SystemExit(1)


def _read_version() -> str:
    init = pathlib.Path(__file__).resolve().parents[1] / "flotilla_mcp" / "__init__.py"
    m = re.search(r'^__version__ = "([^"]+)"', init.read_text(encoding="utf-8"), re.M)
    if not m:
        print("could not read __version__ from flotilla_mcp/__init__.py", file=sys.stderr)
        raise SystemExit(1)
    return m.group(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: check_tag_version.py <tag>", file=sys.stderr)
        raise SystemExit(1)
    check(sys.argv[1], _read_version())
    print("tag matches version")
