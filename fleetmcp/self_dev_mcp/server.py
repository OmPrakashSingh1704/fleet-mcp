from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field

import anyio.to_thread
import requests
from github import GithubException
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from fleetmcp import __version__
from fleetmcp.common.manifest import FleetManifest
from fleetmcp.self_dev_mcp.attempt_tracker import AttemptsExhaustedError, AttemptTracker
from fleetmcp.self_dev_mcp.config import load_settings
from fleetmcp.self_dev_mcp.git_ops import (
    GitOpsError,
    checkout_remote_branch,
    commit_all,
    create_branch,
    push,
    remote_branch_exists,
)
from fleetmcp.self_dev_mcp.github_client import GitHubClient
from fleetmcp.self_dev_mcp.tools import DEFAULT_TEST_TIMEOUT_SECONDS, ProtectedPathError, validate_test_path
from fleetmcp.self_dev_mcp.tools import read_file as _read_file
from fleetmcp.self_dev_mcp.tools import run_local_tests as _run_local_tests
from fleetmcp.self_dev_mcp.tools import write_file as _write_file
from fleetmcp.self_dev_mcp.workspace import create_workspace, destroy_workspace

# Policy-denial audit trail (spec-required): every REFUSED / EXHAUSTED
# decision is logged here. Only the repr of the requested path is logged --
# never file content.
audit_logger = logging.getLogger("fleet_mcp.audit")

# GitHub-facing errors a handler converts to "ERROR: ..." instead of raising
# (never-raise contract for MCP tool handlers).
_GITHUB_ERRORS = (GithubException, requests.RequestException)


def _audit_denial(tool: str, issue_number: int, path: str, reason: str) -> None:
    audit_logger.warning(
        "policy-denial tool=%s issue=%s path=%r reason=%s", tool, issue_number, path, reason
    )


@dataclass
class ServerDependencies:
    repo_remote: str
    manifest: FleetManifest
    tracker: AttemptTracker
    github_client: GitHubClient
    workspaces: dict = field(default_factory=dict)
    test_timeout_seconds: float = DEFAULT_TEST_TIMEOUT_SECONDS
    # Tool handlers run in worker threads (see build_mcp_app), so workspace
    # bookkeeping is guarded by this lock; `starting` reserves an issue while
    # its clone is in flight so two concurrent start_issue calls can't both
    # clone it.
    lock: threading.Lock = field(default_factory=threading.Lock)
    starting: set = field(default_factory=set)


def _branch_name(issue_number: int) -> str:
    return f"selfdev/issue-{issue_number}"


def _missing_workspace_error(issue_number: int) -> str:
    return f"ERROR: no active workspace for issue {issue_number}; call start_issue first"


def _workspace_for(issue_number: int, deps: ServerDependencies) -> str | None:
    with deps.lock:
        return deps.workspaces.get(str(issue_number))


def handle_start_issue(issue_number: int, deps: ServerDependencies) -> str:
    issue_key = str(issue_number)
    with deps.lock:
        if issue_key in deps.workspaces or issue_key in deps.starting:
            return f"ERROR: issue {issue_number} already has an active workspace"
        deps.starting.add(issue_key)
    try:
        branch_name = _branch_name(issue_number)
        try:
            workspace_dir = create_workspace(deps.repo_remote)
        except (GitOpsError, OSError) as exc:
            return f"ERROR: {exc}"
        try:
            # A follow-up invocation (e.g. after review comments) must resume on
            # the same remote branch instead of branching fresh off main, so a
            # later push can fast-forward rather than being rejected.
            if remote_branch_exists(workspace_dir, branch_name):
                checkout_remote_branch(workspace_dir, branch_name)
            else:
                create_branch(workspace_dir, branch_name)
        except (GitOpsError, OSError) as exc:
            destroy_workspace(workspace_dir)
            return f"ERROR: {exc}"
        with deps.lock:
            deps.workspaces[issue_key] = workspace_dir
        return branch_name
    finally:
        with deps.lock:
            deps.starting.discard(issue_key)


def handle_write_file(issue_number: int, relative_path: str, content: str, deps: ServerDependencies) -> str:
    issue_key = str(issue_number)
    workspace_dir = _workspace_for(issue_number, deps)
    if workspace_dir is None:
        return _missing_workspace_error(issue_number)
    try:
        _write_file(workspace_dir, relative_path, content, deps.manifest, issue_key, deps.tracker)
    except ProtectedPathError as exc:
        _audit_denial("write_file", issue_number, relative_path, f"REFUSED: {exc}")
        return f"REFUSED: {exc}"
    except AttemptsExhaustedError as exc:
        _audit_denial("write_file", issue_number, relative_path, f"EXHAUSTED: {exc}")
        try:
            deps.github_client.comment_on_issue(issue_number, f"Giving up: {exc}")
        except _GITHUB_ERRORS as comment_exc:
            return f"EXHAUSTED: {exc} (failed to comment on issue: {comment_exc})"
        return f"EXHAUSTED: {exc}"
    except OSError as exc:
        return f"ERROR: {exc}"
    return "OK"


def handle_read_file(issue_number: int, relative_path: str, deps: ServerDependencies) -> str:
    workspace_dir = _workspace_for(issue_number, deps)
    if workspace_dir is None:
        return _missing_workspace_error(issue_number)
    try:
        return _read_file(workspace_dir, relative_path)
    except ProtectedPathError as exc:
        _audit_denial("read_file", issue_number, relative_path, f"REFUSED: {exc}")
        return f"REFUSED: {exc}"
    except FileNotFoundError:
        return f"ERROR: file not found: {relative_path}"
    except (OSError, UnicodeDecodeError) as exc:
        return f"ERROR: {exc}"


def _format_test_result(result: subprocess.CompletedProcess) -> str:
    status = "OK" if result.returncode == 0 else "FAILED"
    return f"{status} (exit {result.returncode})\n{result.stdout}{result.stderr}"


def handle_run_tests(issue_number: int, service_relative_path: str, deps: ServerDependencies) -> str:
    workspace_dir = _workspace_for(issue_number, deps)
    if workspace_dir is None:
        return _missing_workspace_error(issue_number)
    try:
        # Validation only (option-like, .git, escape). run_local_tests runs
        # with cwd=workspace_dir and passes the path after "--".
        validate_test_path(workspace_dir, service_relative_path)
    except ProtectedPathError as exc:
        _audit_denial("run_tests", issue_number, service_relative_path, f"REFUSED: {exc}")
        return f"REFUSED: {exc}"
    timeout = deps.test_timeout_seconds
    try:
        result = _run_local_tests(workspace_dir, service_relative_path, timeout_seconds=timeout)
    except subprocess.TimeoutExpired:
        return f"ERROR: tests timed out after {timeout:g}s"
    except OSError as exc:
        return f"ERROR: {exc}"
    return _format_test_result(result)


def handle_submit_pr(issue_number: int, title: str, body: str, deps: ServerDependencies) -> str:
    issue_key = str(issue_number)
    workspace_dir = _workspace_for(issue_number, deps)
    if workspace_dir is None:
        return _missing_workspace_error(issue_number)
    branch_name = _branch_name(issue_number)
    try:
        commit_all(workspace_dir, title)
        push(workspace_dir, branch_name)
        pr = deps.github_client.open_pr(branch_name, base="main", title=title, body=body)
    except (GitOpsError, OSError, *_GITHUB_ERRORS) as exc:
        # Keep the workspace (and its deps.workspaces entry) on failure so
        # the agent can fix the problem and retry submit_pr without having
        # to start_issue (and re-clone) again.
        return f"ERROR: {exc}"
    destroy_workspace(workspace_dir)
    with deps.lock:
        deps.workspaces.pop(issue_key, None)
    return f"opened PR #{pr.number}"


def handle_list_assigned_issues(deps: ServerDependencies, label: str = "self-dev") -> str:
    try:
        issues = deps.github_client.list_issues_by_label(label)
    except _GITHUB_ERRORS as exc:
        return f"ERROR: {exc}"
    if not issues:
        return f"No open issues labeled {label}"
    return "\n".join(f"#{issue.number} {issue.title}" for issue in issues)


def handle_check_pr_status(pr_number: int, deps: ServerDependencies) -> str:
    try:
        return deps.github_client.get_pr_status(pr_number)
    except _GITHUB_ERRORS as exc:
        return f"ERROR: {exc}"


def manifest_path() -> str:
    return os.environ.get("FLEET_MANIFEST_PATH", "fleet_manifest.yaml")


def build_mcp_app() -> FastMCP:
    settings = load_settings()
    deps = ServerDependencies(
        repo_remote=settings.repo_remote,
        manifest=FleetManifest.load(manifest_path()),
        tracker=AttemptTracker(max_attempts=settings.max_attempts),
        github_client=GitHubClient(settings.github_token, settings.github_repo_full_name),
        test_timeout_seconds=settings.test_timeout_seconds,
    )

    app = FastMCP("self-dev-mcp")

    # Every tool is async and runs its blocking (git, pytest, GitHub API)
    # sync handler in a worker thread, so a long run_tests can never stall
    # the event loop -- which also serves /health.

    @app.tool(name="start_issue")
    async def start_issue(issue_number: int) -> str:
        return await anyio.to_thread.run_sync(handle_start_issue, issue_number, deps)

    @app.tool(name="read_file")
    async def read_file(issue_number: int, relative_path: str) -> str:
        return await anyio.to_thread.run_sync(handle_read_file, issue_number, relative_path, deps)

    @app.tool(name="write_file")
    async def write_file(issue_number: int, relative_path: str, content: str) -> str:
        return await anyio.to_thread.run_sync(handle_write_file, issue_number, relative_path, content, deps)

    @app.tool(name="run_tests")
    async def run_tests(issue_number: int, service_relative_path: str) -> str:
        return await anyio.to_thread.run_sync(handle_run_tests, issue_number, service_relative_path, deps)

    @app.tool(name="submit_pr")
    async def submit_pr(issue_number: int, title: str, body: str) -> str:
        return await anyio.to_thread.run_sync(handle_submit_pr, issue_number, title, body, deps)

    @app.tool(name="list_assigned_issues")
    async def list_assigned_issues(label: str = "self-dev") -> str:
        return await anyio.to_thread.run_sync(handle_list_assigned_issues, deps, label)

    @app.tool(name="check_pr_status")
    async def check_pr_status(pr_number: int) -> str:
        return await anyio.to_thread.run_sync(handle_check_pr_status, pr_number, deps)

    return app


def build_http_app() -> Starlette:
    """Build a Starlette ASGI app serving Self-Dev MCP over HTTP, plus /health.

    The compose deployment health-checks this service over HTTP (see the
    self-dev-mcp healthcheck in docker-compose.yml), so it must be servable
    as an ASGI app with a /health route rather than only over stdio, which
    has no health endpoint at all.

    mcp==1.2.0's FastMCP has no sse_app()/streamable_http_app() convenience
    method (those were added in later mcp releases) -- only
    FastMCP.run_sse_async(), which builds a Starlette app internally and
    blocks forever on uvicorn.serve(), so it can't be mounted alongside a
    /health route. This function instead mirrors the exact route
    construction run_sse_async() itself uses: SseServerTransport (a public
    class in mcp.server.sse, whose own module docstring documents this same
    "Starlette app with an SSE route and a POST-message mount" pattern as
    intended usage) wired to the low-level mcp.server.lowlevel.Server that
    FastMCP.__init__ already sets up with this app's tool/resource/prompt
    handlers (self._setup_handlers()). No MCP/SSE/JSON-RPC framing is
    reimplemented here -- only the ASGI routing glue around the SDK's own
    transport.
    """
    mcp_app = build_mcp_app()
    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            # Mirrors FastMCP.run_sse_async in mcp==1.2.0, which has no public
            # sse_app(); _mcp_server is private, so re-verify this against any
            # mcp version bump.
            await mcp_app._mcp_server.run(
                streams[0],
                streams[1],
                mcp_app._mcp_server.create_initialization_options(),
            )

    async def health(request):
        return JSONResponse({"status": "ok"})

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Self-Dev MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="Transport to serve over (default: stdio, for local/CLI use)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="HTTP bind host (--transport http only)")
    parser.add_argument("--port", type=int, default=8080, help="HTTP bind port (--transport http only)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    # Logs -- including the fleet_mcp.audit policy-denial trail -- go to
    # stderr: with --transport stdio, stdout is the MCP protocol channel.
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv)
    if args.transport == "http":
        import uvicorn

        uvicorn.run(build_http_app(), host=args.host, port=args.port)
    else:
        build_mcp_app().run()


if __name__ == "__main__":
    main()
