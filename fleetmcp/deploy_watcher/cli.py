from __future__ import annotations

import argparse
import sys

from fleetmcp import __version__


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="fleetmcp-watcher",
        description="Fleet MCP Deploy Watcher: polls main, builds, and blue/green-deploys fleet services. "
        "Configured via environment variables (see .env.example).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)

    try:
        import docker  # noqa: F401
    except ModuleNotFoundError:
        print(
            'fleetmcp-watcher needs the Docker SDK. Install it with: pip install "fleetmcp[watcher]"',
            file=sys.stderr,
        )
        raise SystemExit(2)

    from fleetmcp.deploy_watcher.main import run

    run()
