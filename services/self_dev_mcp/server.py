from __future__ import annotations

from dataclasses import dataclass, field

from github import GithubException
from mcp.server.fastmcp import FastMCP

from services.common.manifest import FleetManifest
from services.self_dev_mcp.attempt_tracker import AttemptsExhaustedError, AttemptTracker
from services.self_dev_mcp.config import load_settings
from services.self_dev_mcp.git_ops import (
    GitOpsError,
    checkout_remote_branch,
    commit_all,
    create_branch,
    push,
    remote_branch_exists,
)
from services.self_dev_mcp.github_client import GitHubClient
from services.self_dev_mcp.tools import ProtectedPathError
from services.self_dev_mcp.tools import _resolve_inside_workspace
from services.self_dev_mcp.tools import read_file as _read_file
from services.self_dev_mcp.tools import run_local_tests as _run_local_tests
from services.self_dev_mcp.tools import write_file as _write_file
from services.self_dev_mcp.workspace import create_workspace, destroy_workspace


@dataclass
class ServerDependencies:
    repo_remote: str
    manifest: FleetManifest
    tracker: AttemptTracker
    github_client: GitHubClient
    workspaces: dict = field(default_factory=dict)


def _branch_name(issue_number: int) -> str:
    return f"selfdev/issue-{issue_number}"


def _missing_workspace_error(issue_number: int) -> str:
    return f"ERROR: no active workspace for issue {issue_number}; call start_issue first"


def handle_start_issue(issue_number: int, deps: ServerDependencies) -> str:
    issue_key = str(issue_number)
    if issue_key in deps.workspaces:
        return f"ERROR: issue {issue_number} already has an active workspace"
    branch_name = _branch_name(issue_number)
    try:
        workspace_dir = create_workspace(deps.repo_remote)
    except GitOpsError as exc:
        return f"ERROR: {exc}"
    try:
        # A follow-up invocation (e.g. after review comments) must resume on
        # the same remote branch instead of branching fresh off main, so a
        # later push can fast-forward rather than being rejected.
        if remote_branch_exists(workspace_dir, branch_name):
            checkout_remote_branch(workspace_dir, branch_name)
        else:
            create_branch(workspace_dir, branch_name)
    except GitOpsError as exc:
        destroy_workspace(workspace_dir)
        return f"ERROR: {exc}"
    deps.workspaces[issue_key] = workspace_dir
    return branch_name


def handle_write_file(issue_number: int, relative_path: str, content: str, deps: ServerDependencies) -> str:
    issue_key = str(issue_number)
    if issue_key not in deps.workspaces:
        return _missing_workspace_error(issue_number)
    workspace_dir = deps.workspaces[issue_key]
    try:
        _write_file(workspace_dir, relative_path, content, deps.manifest, issue_key, deps.tracker)
    except ProtectedPathError as exc:
        return f"REFUSED: {exc}"
    except AttemptsExhaustedError as exc:
        try:
            deps.github_client.comment_on_issue(issue_number, f"Giving up: {exc}")
        except GithubException as comment_exc:
            return f"EXHAUSTED: {exc} (failed to comment on issue: {comment_exc})"
        return f"EXHAUSTED: {exc}"
    return "OK"


def handle_read_file(issue_number: int, relative_path: str, deps: ServerDependencies) -> str:
    issue_key = str(issue_number)
    if issue_key not in deps.workspaces:
        return _missing_workspace_error(issue_number)
    workspace_dir = deps.workspaces[issue_key]
    try:
        return _read_file(workspace_dir, relative_path)
    except ProtectedPathError as exc:
        return f"REFUSED: {exc}"
    except FileNotFoundError:
        return f"ERROR: file not found: {relative_path}"
    except IsADirectoryError as exc:
        return f"ERROR: {exc}"


def handle_run_tests(issue_number: int, service_relative_path: str, deps: ServerDependencies) -> str:
    issue_key = str(issue_number)
    if issue_key not in deps.workspaces:
        return _missing_workspace_error(issue_number)
    workspace_dir = deps.workspaces[issue_key]
    try:
        # Validation only: this rejects a service_relative_path that would
        # escape the workspace. run_local_tests itself always runs with
        # cwd=workspace_dir, so the original (unresolved) relative path is
        # what actually gets passed to pytest below.
        _resolve_inside_workspace(workspace_dir, service_relative_path)
    except ProtectedPathError as exc:
        return f"REFUSED: {exc}"
    result = _run_local_tests(workspace_dir, service_relative_path)
    return result.stdout + result.stderr


def handle_submit_pr(issue_number: int, title: str, body: str, deps: ServerDependencies) -> str:
    issue_key = str(issue_number)
    if issue_key not in deps.workspaces:
        return _missing_workspace_error(issue_number)
    workspace_dir = deps.workspaces[issue_key]
    branch_name = _branch_name(issue_number)
    try:
        commit_all(workspace_dir, title)
        push(workspace_dir, branch_name)
        pr = deps.github_client.open_pr(branch_name, base="main", title=title, body=body)
    except (GitOpsError, GithubException) as exc:
        # Keep the workspace (and its deps.workspaces entry) on failure so
        # the agent can fix the problem and retry submit_pr without having
        # to start_issue (and re-clone) again.
        return f"ERROR: {exc}"
    destroy_workspace(workspace_dir)
    del deps.workspaces[issue_key]
    return f"opened PR #{pr.number}"


def handle_list_assigned_issues(deps: ServerDependencies, label: str = "self-dev") -> str:
    try:
        issues = deps.github_client.list_issues_by_label(label)
    except GithubException as exc:
        return f"ERROR: {exc}"
    if not issues:
        return f"No open issues labeled {label}"
    return "\n".join(f"#{issue.number} {issue.title}" for issue in issues)


def handle_check_pr_status(pr_number: int, deps: ServerDependencies) -> str:
    try:
        return deps.github_client.get_pr_status(pr_number)
    except GithubException as exc:
        return f"ERROR: {exc}"


def build_mcp_app() -> FastMCP:
    settings = load_settings()
    deps = ServerDependencies(
        repo_remote=settings.repo_remote,
        manifest=FleetManifest.load("fleet_manifest.yaml"),
        tracker=AttemptTracker(max_attempts=settings.max_attempts),
        github_client=GitHubClient(settings.github_token, settings.github_repo_full_name),
    )

    app = FastMCP("self-dev-mcp")

    @app.tool(name="start_issue")
    def start_issue(issue_number: int) -> str:
        return handle_start_issue(issue_number, deps)

    @app.tool(name="read_file")
    def read_file(issue_number: int, relative_path: str) -> str:
        return handle_read_file(issue_number, relative_path, deps)

    @app.tool(name="write_file")
    def write_file(issue_number: int, relative_path: str, content: str) -> str:
        return handle_write_file(issue_number, relative_path, content, deps)

    @app.tool(name="run_tests")
    def run_tests(issue_number: int, service_relative_path: str) -> str:
        return handle_run_tests(issue_number, service_relative_path, deps)

    @app.tool(name="submit_pr")
    def submit_pr(issue_number: int, title: str, body: str) -> str:
        return handle_submit_pr(issue_number, title, body, deps)

    @app.tool(name="list_assigned_issues")
    def list_assigned_issues(label: str = "self-dev") -> str:
        return handle_list_assigned_issues(deps, label)

    @app.tool(name="check_pr_status")
    def check_pr_status(pr_number: int) -> str:
        return handle_check_pr_status(pr_number, deps)

    return app


if __name__ == "__main__":
    build_mcp_app().run()
