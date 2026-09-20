from __future__ import annotations

import asyncio
import inspect
import logging
import subprocess
import threading
from unittest.mock import MagicMock, patch

import pytest
from github import GithubException

from flotilla_mcp.common.manifest import FleetManifest
from flotilla_mcp.self_dev_mcp.attempt_tracker import AttemptTracker
from flotilla_mcp.self_dev_mcp.git_ops import GitOpsError
from flotilla_mcp.self_dev_mcp.server import (
    ServerDependencies,
    handle_check_pr_status,
    handle_list_assigned_issues,
    handle_read_file,
    handle_run_tests,
    handle_start_issue,
    handle_submit_pr,
    handle_write_file,
)


def _empty_manifest(tmp_path):
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text(
        "services:\n"
        "  deploy-watcher:\n"
        "    path: flotilla_mcp/deploy_watcher\n"
        "    protected: true\n"
    )
    return FleetManifest.load(str(manifest_path))


def _deps(tmp_path):
    return ServerDependencies(
        repo_remote="https://example.com/repo.git",
        manifest=_empty_manifest(tmp_path),
        tracker=AttemptTracker(max_attempts=5),
        github_client=MagicMock(),
        workspaces={},
    )


@patch("flotilla_mcp.self_dev_mcp.server.remote_branch_exists")
@patch("flotilla_mcp.self_dev_mcp.server.create_workspace")
@patch("flotilla_mcp.self_dev_mcp.server.create_branch")
def test_handle_start_issue_creates_workspace_and_branch(
    mock_create_branch, mock_create_workspace, mock_remote_branch_exists, tmp_path
):
    mock_create_workspace.return_value = str(tmp_path / "workspace")
    mock_remote_branch_exists.return_value = False
    deps = _deps(tmp_path)

    branch_name = handle_start_issue(1, deps)

    assert branch_name == "selfdev/issue-1"
    assert deps.workspaces["1"] == str(tmp_path / "workspace")
    mock_create_branch.assert_called_once_with(str(tmp_path / "workspace"), "selfdev/issue-1")
    mock_create_workspace.assert_called_once_with(deps.repo_remote)


def test_handle_write_file_writes_to_tracked_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)

    result = handle_write_file(1, "flotilla_mcp/fixture_hello_mcp/server.py", "print('hi')", deps)

    assert result == "OK"
    assert (workspace / "flotilla_mcp" / "fixture_hello_mcp" / "server.py").read_text() == "print('hi')"


def test_handle_write_file_refuses_protected_path_and_returns_message(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)

    result = handle_write_file(1, "flotilla_mcp/deploy_watcher/deploy_manager.py", "bad", deps)

    assert result.startswith("REFUSED")
    assert not (workspace / "flotilla_mcp" / "deploy_watcher" / "deploy_manager.py").exists()


def test_handle_write_file_comments_on_issue_and_reports_when_exhausted(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)
    deps.tracker = AttemptTracker(max_attempts=1)
    handle_write_file(1, "a.py", "1", deps)

    result = handle_write_file(1, "b.py", "2", deps)

    assert result.startswith("EXHAUSTED")
    deps.github_client.comment_on_issue.assert_called_once()
    assert deps.github_client.comment_on_issue.call_args[0][0] == 1


@patch("flotilla_mcp.self_dev_mcp.server.push")
@patch("flotilla_mcp.self_dev_mcp.server.commit_all")
def test_handle_submit_pr_commits_pushes_opens_pr_and_cleans_up(mock_commit_all, mock_push, tmp_path):
    mock_commit_all.return_value = "abc123"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)
    deps.github_client.open_pr.return_value = MagicMock(number=99)

    result = handle_submit_pr(1, "Fix bug", "body", deps)

    assert result == "opened PR #99"
    mock_commit_all.assert_called_once_with(str(workspace), "Fix bug")
    mock_push.assert_called_once_with(str(workspace), "selfdev/issue-1")
    deps.github_client.open_pr.assert_called_once_with("selfdev/issue-1", base="main", title="Fix bug", body="body")
    assert "1" not in deps.workspaces


# --- Ruling 2: read_file, list_assigned_issues, check_pr_status ---


def test_handle_read_file_returns_content(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.py").write_text("hello")
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)

    result = handle_read_file(1, "a.py", deps)

    assert result == "hello"


def test_handle_read_file_refuses_escaping_path(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)

    result = handle_read_file(1, "../escape.py", deps)

    assert result.startswith("REFUSED")


def test_handle_list_assigned_issues_formats_open_issues(tmp_path):
    deps = _deps(tmp_path)
    issue1 = MagicMock(number=5, title="Fix the thing")
    issue2 = MagicMock(number=7, title="Add the feature")
    deps.github_client.list_issues_by_label.return_value = [issue1, issue2]

    result = handle_list_assigned_issues(deps)

    assert result == "#5 Fix the thing\n#7 Add the feature"
    deps.github_client.list_issues_by_label.assert_called_once_with("self-dev")


def test_handle_list_assigned_issues_handles_empty(tmp_path):
    deps = _deps(tmp_path)
    deps.github_client.list_issues_by_label.return_value = []

    result = handle_list_assigned_issues(deps)

    assert result == "No open issues labeled self-dev"


def test_handle_check_pr_status_delegates(tmp_path):
    deps = _deps(tmp_path)
    deps.github_client.get_pr_status.return_value = "success"

    result = handle_check_pr_status(42, deps)

    assert result == "success"
    deps.github_client.get_pr_status.assert_called_once_with(42)


# --- Ruling 3: run_tests must not escape the workspace ---


def test_handle_run_tests_refuses_escaping_service_path(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)

    with patch("flotilla_mcp.self_dev_mcp.server._run_local_tests") as mock_run:
        result = handle_run_tests(1, "../../escape", deps)

    assert result.startswith("REFUSED")
    mock_run.assert_not_called()


def test_handle_run_tests_runs_for_valid_path(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)

    with patch("flotilla_mcp.self_dev_mcp.server._run_local_tests") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        result = handle_run_tests(1, "services/foo", deps)

    mock_run.assert_called_once_with(str(workspace), "services/foo", timeout_seconds=600.0)
    assert result == "OK (exit 0)\nok"


# --- Ruling 4: duplicate-attempt guard ---


@patch("flotilla_mcp.self_dev_mcp.server.remote_branch_exists")
@patch("flotilla_mcp.self_dev_mcp.server.create_workspace")
@patch("flotilla_mcp.self_dev_mcp.server.create_branch")
def test_handle_start_issue_twice_returns_error_and_does_not_reclone(
    mock_create_branch, mock_create_workspace, mock_remote_branch_exists, tmp_path
):
    mock_create_workspace.return_value = str(tmp_path / "workspace")
    mock_remote_branch_exists.return_value = False
    deps = _deps(tmp_path)

    first = handle_start_issue(1, deps)
    second = handle_start_issue(1, deps)

    assert first == "selfdev/issue-1"
    assert second == "ERROR: issue 1 already has an active workspace"
    mock_create_workspace.assert_called_once()


# --- Ruling 5: missing-workspace handling ---


def test_handle_write_file_missing_workspace_returns_error(tmp_path):
    deps = _deps(tmp_path)

    result = handle_write_file(1, "a.py", "content", deps)

    assert result == "ERROR: no active workspace for issue 1; call start_issue first"


def test_handle_read_file_missing_workspace_returns_error(tmp_path):
    deps = _deps(tmp_path)

    result = handle_read_file(1, "a.py", deps)

    assert result == "ERROR: no active workspace for issue 1; call start_issue first"


def test_handle_run_tests_missing_workspace_returns_error(tmp_path):
    deps = _deps(tmp_path)

    result = handle_run_tests(1, "services/foo", deps)

    assert result == "ERROR: no active workspace for issue 1; call start_issue first"


def test_handle_submit_pr_missing_workspace_returns_error(tmp_path):
    deps = _deps(tmp_path)

    result = handle_submit_pr(1, "title", "body", deps)

    assert result == "ERROR: no active workspace for issue 1; call start_issue first"


# --- Fix round 1, Part A: error-handling contract (handlers never raise) ---


@patch("flotilla_mcp.self_dev_mcp.server.commit_all")
def test_handle_submit_pr_commit_failure_returns_error_and_keeps_workspace(mock_commit_all, tmp_path):
    mock_commit_all.side_effect = GitOpsError("nothing to commit")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)

    result = handle_submit_pr(1, "Fix bug", "body", deps)

    assert result == "ERROR: nothing to commit"
    assert deps.workspaces["1"] == str(workspace)
    assert workspace.exists()


@patch("flotilla_mcp.self_dev_mcp.server.push")
@patch("flotilla_mcp.self_dev_mcp.server.commit_all")
def test_handle_submit_pr_open_pr_failure_returns_error_and_keeps_workspace(mock_commit_all, mock_push, tmp_path):
    mock_commit_all.return_value = "abc123"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)
    deps.github_client.open_pr.side_effect = GithubException(500, "boom", None)

    result = handle_submit_pr(1, "Fix bug", "body", deps)

    assert result.startswith("ERROR")
    assert deps.workspaces["1"] == str(workspace)
    assert workspace.exists()


@patch("flotilla_mcp.self_dev_mcp.server.destroy_workspace")
@patch("flotilla_mcp.self_dev_mcp.server.remote_branch_exists")
@patch("flotilla_mcp.self_dev_mcp.server.create_workspace")
@patch("flotilla_mcp.self_dev_mcp.server.create_branch")
def test_handle_start_issue_create_branch_failure_destroys_workspace(
    mock_create_branch, mock_create_workspace, mock_remote_branch_exists, mock_destroy_workspace, tmp_path
):
    mock_create_workspace.return_value = str(tmp_path / "workspace")
    mock_remote_branch_exists.return_value = False
    mock_create_branch.side_effect = GitOpsError("checkout failed")
    deps = _deps(tmp_path)

    result = handle_start_issue(1, deps)

    assert result == "ERROR: checkout failed"
    mock_destroy_workspace.assert_called_once_with(str(tmp_path / "workspace"))
    assert "1" not in deps.workspaces


def test_handle_read_file_missing_file_returns_error(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)

    result = handle_read_file(1, "nope.py", deps)

    assert result == "ERROR: file not found: nope.py"


def test_handle_write_file_exhausted_and_comment_fails_still_reports_exhausted(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)
    deps.tracker = AttemptTracker(max_attempts=1)
    deps.github_client.comment_on_issue.side_effect = GithubException(500, "boom", None)
    handle_write_file(1, "a.py", "1", deps)

    result = handle_write_file(1, "b.py", "2", deps)

    assert result.startswith("EXHAUSTED")
    assert "failed to comment on issue" in result


def test_handle_list_assigned_issues_github_failure_returns_error(tmp_path):
    deps = _deps(tmp_path)
    deps.github_client.list_issues_by_label.side_effect = GithubException(500, "boom", None)

    result = handle_list_assigned_issues(deps)

    assert result.startswith("ERROR")


def test_handle_check_pr_status_github_failure_returns_error(tmp_path):
    deps = _deps(tmp_path)
    deps.github_client.get_pr_status.side_effect = GithubException(500, "boom", None)

    result = handle_check_pr_status(42, deps)

    assert result.startswith("ERROR")


# --- Fix round 1, Part D: follow-up commits to an existing PR branch ---


@patch("flotilla_mcp.self_dev_mcp.server.checkout_remote_branch")
@patch("flotilla_mcp.self_dev_mcp.server.remote_branch_exists")
@patch("flotilla_mcp.self_dev_mcp.server.create_workspace")
@patch("flotilla_mcp.self_dev_mcp.server.create_branch")
def test_handle_start_issue_resumes_existing_remote_branch(
    mock_create_branch, mock_create_workspace, mock_remote_branch_exists, mock_checkout_remote_branch, tmp_path
):
    mock_create_workspace.return_value = str(tmp_path / "workspace")
    mock_remote_branch_exists.return_value = True
    deps = _deps(tmp_path)

    branch_name = handle_start_issue(1, deps)

    assert branch_name == "selfdev/issue-1"
    mock_checkout_remote_branch.assert_called_once_with(str(tmp_path / "workspace"), "selfdev/issue-1")
    mock_create_branch.assert_not_called()


@patch("flotilla_mcp.self_dev_mcp.server.checkout_remote_branch")
@patch("flotilla_mcp.self_dev_mcp.server.remote_branch_exists")
@patch("flotilla_mcp.self_dev_mcp.server.create_workspace")
@patch("flotilla_mcp.self_dev_mcp.server.create_branch")
def test_handle_start_issue_creates_new_branch_when_no_remote_branch(
    mock_create_branch, mock_create_workspace, mock_remote_branch_exists, mock_checkout_remote_branch, tmp_path
):
    mock_create_workspace.return_value = str(tmp_path / "workspace")
    mock_remote_branch_exists.return_value = False
    deps = _deps(tmp_path)

    branch_name = handle_start_issue(1, deps)

    assert branch_name == "selfdev/issue-1"
    mock_create_branch.assert_called_once_with(str(tmp_path / "workspace"), "selfdev/issue-1")
    mock_checkout_remote_branch.assert_not_called()


@patch("flotilla_mcp.self_dev_mcp.server.destroy_workspace")
@patch("flotilla_mcp.self_dev_mcp.server.checkout_remote_branch")
@patch("flotilla_mcp.self_dev_mcp.server.remote_branch_exists")
@patch("flotilla_mcp.self_dev_mcp.server.create_workspace")
def test_handle_start_issue_checkout_remote_branch_failure_destroys_workspace(
    mock_create_workspace, mock_remote_branch_exists, mock_checkout_remote_branch, mock_destroy_workspace, tmp_path
):
    mock_create_workspace.return_value = str(tmp_path / "workspace")
    mock_remote_branch_exists.return_value = True
    mock_checkout_remote_branch.side_effect = GitOpsError("checkout --track failed")
    deps = _deps(tmp_path)

    result = handle_start_issue(1, deps)

    assert result == "ERROR: checkout --track failed"
    mock_destroy_workspace.assert_called_once_with(str(tmp_path / "workspace"))
    assert "1" not in deps.workspaces


# --- Smoke test: build_mcp_app registers exactly the expected tools ---


def test_build_mcp_app_registers_all_tools(tmp_path, monkeypatch):
    # Deliberately a sync test driving the coroutine with asyncio.run():
    # an `async def` test silently skips when pytest-asyncio isn't installed
    # (it isn't in requirements.txt, so it never ran in CI).
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text(
        "services:\n"
        "  deploy-watcher:\n"
        "    path: flotilla_mcp/deploy_watcher\n"
        "    protected: true\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "https://example.com/repo.git")
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")

    with patch("flotilla_mcp.self_dev_mcp.server.GitHubClient") as mock_github_client:
        mock_github_client.return_value = MagicMock()

        from flotilla_mcp.self_dev_mcp.server import build_mcp_app

        app = build_mcp_app()
        tools = asyncio.run(app.list_tools())

    tool_names = {tool.name for tool in tools}
    assert tool_names == {
        "start_issue",
        "read_file",
        "write_file",
        "run_tests",
        "submit_pr",
        "list_assigned_issues",
        "check_pr_status",
    }


# --- Ruling 1: HTTP transport (/health + mounted SSE app) ---


def _write_minimal_manifest(tmp_path):
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text(
        "services:\n"
        "  deploy-watcher:\n"
        "    path: flotilla_mcp/deploy_watcher\n"
        "    protected: true\n"
    )


def _set_server_env(monkeypatch, tmp_path):
    _write_minimal_manifest(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "https://example.com/repo.git")
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")


def test_build_http_app_health_endpoint_returns_ok(tmp_path, monkeypatch):
    _set_server_env(monkeypatch, tmp_path)

    with patch("flotilla_mcp.self_dev_mcp.server.GitHubClient") as mock_github_client:
        mock_github_client.return_value = MagicMock()

        from starlette.testclient import TestClient

        from flotilla_mcp.self_dev_mcp.server import build_http_app

        http_app = build_http_app()
        client = TestClient(http_app)
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_build_http_app_mounts_sse_route(tmp_path, monkeypatch):
    _set_server_env(monkeypatch, tmp_path)

    with patch("flotilla_mcp.self_dev_mcp.server.GitHubClient") as mock_github_client:
        mock_github_client.return_value = MagicMock()

        from flotilla_mcp.self_dev_mcp.server import build_http_app

        http_app = build_http_app()

    route_paths = {getattr(route, "path", None) for route in http_app.routes}
    assert "/sse" in route_paths
    assert "/health" in route_paths


def test_parse_args_defaults_to_stdio_transport():
    from flotilla_mcp.self_dev_mcp.server import _parse_args

    args = _parse_args([])

    assert args.transport == "stdio"
    assert args.host == "0.0.0.0"
    assert args.port == 8080


def test_parse_args_accepts_http_transport_with_host_and_port():
    from flotilla_mcp.self_dev_mcp.server import _parse_args

    args = _parse_args(["--transport", "http", "--host", "127.0.0.1", "--port", "9000"])

    assert args.transport == "http"
    assert args.host == "127.0.0.1"
    assert args.port == 9000


def test_fastmcp_still_exposes_private_mcp_server_attribute():
    # build_http_app() relies on FastMCP._mcp_server -- a private attribute
    # with no public accessor in mcp==1.2.0 -- to mirror run_sse_async()'s
    # own route construction. If a future mcp version removes or renames it,
    # this must fail loudly instead of build_http_app() silently breaking.
    from mcp.server.fastmcp import FastMCP

    assert hasattr(FastMCP("x"), "_mcp_server")


# --- Final fix wave: I-6 run_tests hardening ---


def _deps_with_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)
    return deps, workspace


@pytest.mark.parametrize("bad_path", ["-p", "--basetemp=/app", "-", "--", "-x/services"])
def test_handle_run_tests_refuses_option_like_path(tmp_path, bad_path):
    deps, _workspace = _deps_with_workspace(tmp_path)

    with patch("flotilla_mcp.self_dev_mcp.server._run_local_tests") as mock_run:
        result = handle_run_tests(1, bad_path, deps)

    assert result.startswith("REFUSED")
    mock_run.assert_not_called()


def test_handle_run_tests_timeout_returns_error(tmp_path):
    deps, _workspace = _deps_with_workspace(tmp_path)
    deps.test_timeout_seconds = 7

    with patch(
        "flotilla_mcp.self_dev_mcp.tools.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="pytest", timeout=7),
    ) as mock_run:
        result = handle_run_tests(1, "services/foo", deps)

    assert result == "ERROR: tests timed out after 7s"
    assert mock_run.call_args.kwargs["timeout"] == 7


def test_handle_run_tests_reports_failed_exit_code(tmp_path):
    deps, _workspace = _deps_with_workspace(tmp_path)

    with patch("flotilla_mcp.self_dev_mcp.server._run_local_tests") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="1 failed", stderr="warn")
        result = handle_run_tests(1, "services/foo", deps)

    assert result == "FAILED (exit 1)\n1 failedwarn"


def test_handle_run_tests_passes_path_after_double_dash_and_strips_tokens(tmp_path, monkeypatch):
    deps, workspace = _deps_with_workspace(tmp_path)
    monkeypatch.setenv("SELF_DEV_GITHUB_TOKEN", "secret-self-dev")

    with patch("flotilla_mcp.self_dev_mcp.tools.subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        handle_run_tests(1, "services/foo", deps)

    argv = mock_run.call_args.args[0]
    assert argv == ["python", "-m", "pytest", "--", "services/foo"]
    assert mock_run.call_args.kwargs["cwd"] == str(workspace)
    assert "SELF_DEV_GITHUB_TOKEN" not in mock_run.call_args.kwargs["env"]


def test_handle_run_tests_oserror_returns_error(tmp_path):
    deps, _workspace = _deps_with_workspace(tmp_path)

    with patch("flotilla_mcp.self_dev_mcp.server._run_local_tests", side_effect=FileNotFoundError("python")):
        result = handle_run_tests(1, "services/foo", deps)

    assert result.startswith("ERROR")


def test_registered_tools_are_coroutine_functions(tmp_path, monkeypatch):
    _set_server_env(monkeypatch, tmp_path)

    with patch("flotilla_mcp.self_dev_mcp.server.GitHubClient") as mock_github_client:
        mock_github_client.return_value = MagicMock()
        from flotilla_mcp.self_dev_mcp.server import build_mcp_app

        app = build_mcp_app()

    for name in ("run_tests", "start_issue", "submit_pr", "write_file"):
        tool = app._tool_manager.get_tool(name)
        assert inspect.iscoroutinefunction(tool.fn), name
        assert tool.is_async, name


def test_async_tool_runs_handler_off_the_event_loop_thread(tmp_path, monkeypatch):
    _set_server_env(monkeypatch, tmp_path)
    seen = {}

    def fake_handle_run_tests(issue_number, path, deps):
        seen["thread"] = threading.get_ident()
        return "OK (exit 0)\n"

    with patch("flotilla_mcp.self_dev_mcp.server.GitHubClient") as mock_github_client:
        mock_github_client.return_value = MagicMock()
        from flotilla_mcp.self_dev_mcp.server import build_mcp_app

        app = build_mcp_app()

    async def call():
        seen["loop_thread"] = threading.get_ident()
        # Call the registered coroutine directly (Tool.run goes through a
        # pydantic path that emits a DeprecationWarning on newer pydantic).
        return await app._tool_manager.get_tool("run_tests").fn(issue_number=1, service_relative_path="x")

    with patch("flotilla_mcp.self_dev_mcp.server.handle_run_tests", fake_handle_run_tests):
        result = asyncio.run(call())

    assert result == "OK (exit 0)\n"
    assert seen["thread"] != seen["loop_thread"]


# --- Final fix wave: C-1 .git refused through every tool ---

GIT_PATHS = [".git/config", ".git/hooks/pre-commit", ".GIT/config", "sub/../.git/config", "./.git/x"]


@pytest.mark.parametrize("git_path", GIT_PATHS)
def test_handlers_refuse_git_metadata_paths(tmp_path, git_path):
    deps, workspace = _deps_with_workspace(tmp_path)
    (workspace / ".git" / "hooks").mkdir(parents=True)
    (workspace / ".git" / "config").write_text("[core]\n")

    write_result = handle_write_file(1, git_path, '[remote "origin"]\n', deps)
    read_result = handle_read_file(1, git_path, deps)
    with patch("flotilla_mcp.self_dev_mcp.server._run_local_tests") as mock_run:
        tests_result = handle_run_tests(1, git_path, deps)

    assert write_result.startswith("REFUSED"), write_result
    assert read_result.startswith("REFUSED"), read_result
    assert tests_result.startswith("REFUSED"), tests_result
    mock_run.assert_not_called()
    assert (workspace / ".git" / "config").read_text() == "[core]\n"
    assert not (workspace / ".git" / "hooks" / "pre-commit").exists()
    assert not (workspace / ".git" / "x").exists()


# --- Final fix wave: I-8 policy-denial audit log ---


def _audit_records(caplog):
    return [r for r in caplog.records if r.name == "flotilla_mcp.audit"]


def test_audit_log_on_protected_write(tmp_path, caplog):
    deps, _workspace = _deps_with_workspace(tmp_path)

    with caplog.at_level(logging.WARNING, logger="flotilla_mcp.audit"):
        handle_write_file(1, "flotilla_mcp/deploy_watcher/x.py", "SECRET-CONTENT", deps)

    records = _audit_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    assert records[0].levelno == logging.WARNING
    assert message.startswith(
        "policy-denial tool=write_file issue=1 path='flotilla_mcp/deploy_watcher/x.py' reason=REFUSED"
    )
    assert "SECRET-CONTENT" not in message


def test_audit_log_on_git_write(tmp_path, caplog):
    deps, _workspace = _deps_with_workspace(tmp_path)

    with caplog.at_level(logging.WARNING, logger="flotilla_mcp.audit"):
        handle_write_file(1, ".git/config", "[remote]", deps)

    records = _audit_records(caplog)
    assert len(records) == 1
    assert "path='.git/config'" in records[0].getMessage()
    assert "git metadata" in records[0].getMessage()


def test_audit_log_on_escape_uses_repr_of_path(tmp_path, caplog):
    deps, _workspace = _deps_with_workspace(tmp_path)
    newline_path = "../esc" + chr(10) + "ape.py"

    with caplog.at_level(logging.WARNING, logger="flotilla_mcp.audit"):
        handle_write_file(1, newline_path, "x", deps)
        handle_read_file(1, "../escape.py", deps)
        handle_run_tests(1, "../escape", deps)

    records = _audit_records(caplog)
    assert [r.args[0] for r in records] == ["write_file", "read_file", "run_tests"]
    # %r keeps a newline in an attacker-chosen path from forging a log line.
    assert chr(10) not in records[0].getMessage()
    assert repr(newline_path) in records[0].getMessage()


def test_audit_log_on_exhausted(tmp_path, caplog):
    deps, _workspace = _deps_with_workspace(tmp_path)
    deps.tracker = AttemptTracker(max_attempts=1)
    handle_write_file(1, "a.py", "1", deps)

    with caplog.at_level(logging.WARNING, logger="flotilla_mcp.audit"):
        handle_write_file(1, "b.py", "2", deps)

    records = _audit_records(caplog)
    assert len(records) == 1
    assert "reason=EXHAUSTED" in records[0].getMessage()


# --- Final fix wave: M-2 never-raise gaps ---


def test_handle_read_file_non_utf8_returns_error(tmp_path):
    deps, workspace = _deps_with_workspace(tmp_path)
    (workspace / "bin.dat").write_bytes(b"\xff\xfe\x00bad")

    assert handle_read_file(1, "bin.dat", deps).startswith("ERROR")


def test_handle_read_file_directory_returns_error(tmp_path):
    deps, workspace = _deps_with_workspace(tmp_path)
    (workspace / "adir").mkdir()

    assert handle_read_file(1, "adir", deps).startswith("ERROR")


def test_handle_write_file_oserror_returns_error(tmp_path):
    deps, _workspace = _deps_with_workspace(tmp_path)

    with patch("flotilla_mcp.self_dev_mcp.server._write_file", side_effect=PermissionError("denied")):
        assert handle_write_file(1, "a.py", "x", deps) == "ERROR: denied"


@pytest.mark.parametrize("method", ["list_issues_by_label", "get_pr_status"])
def test_github_network_errors_return_error(tmp_path, method):
    import requests

    deps = _deps(tmp_path)
    getattr(deps.github_client, method).side_effect = requests.ConnectionError("down")

    if method == "list_issues_by_label":
        result = handle_list_assigned_issues(deps)
    else:
        result = handle_check_pr_status(1, deps)

    assert result.startswith("ERROR")


@patch("flotilla_mcp.self_dev_mcp.server.push")
@patch("flotilla_mcp.self_dev_mcp.server.commit_all")
def test_handle_submit_pr_network_error_returns_error_and_keeps_workspace(mock_commit_all, mock_push, tmp_path):
    import requests

    deps, workspace = _deps_with_workspace(tmp_path)
    deps.github_client.open_pr.side_effect = requests.ConnectionError("down")

    assert handle_submit_pr(1, "t", "b", deps).startswith("ERROR")
    assert deps.workspaces["1"] == str(workspace)


def test_handle_write_file_exhausted_comment_network_error(tmp_path):
    import requests

    deps, _workspace = _deps_with_workspace(tmp_path)
    deps.tracker = AttemptTracker(max_attempts=1)
    deps.github_client.comment_on_issue.side_effect = requests.ConnectionError("down")
    handle_write_file(1, "a.py", "1", deps)

    result = handle_write_file(1, "b.py", "2", deps)

    assert result.startswith("EXHAUSTED") and "failed to comment" in result


@patch("flotilla_mcp.self_dev_mcp.server.create_workspace", side_effect=OSError("disk full"))
def test_handle_start_issue_oserror_returns_error(mock_create_workspace, tmp_path):
    deps = _deps(tmp_path)

    assert handle_start_issue(1, deps) == "ERROR: disk full"
    assert "1" not in deps.workspaces and "1" not in deps.starting


def test_handle_start_issue_concurrent_calls_clone_once(tmp_path):
    deps = _deps(tmp_path)
    release = threading.Event()
    entered = threading.Event()
    clone_calls = []

    def slow_create_workspace(remote):
        clone_calls.append(remote)
        entered.set()
        release.wait(5)
        return str(tmp_path / "ws")

    with patch("flotilla_mcp.self_dev_mcp.server.create_workspace", side_effect=slow_create_workspace), patch(
        "flotilla_mcp.self_dev_mcp.server.remote_branch_exists", return_value=False
    ), patch("flotilla_mcp.self_dev_mcp.server.create_branch"):
        results = []
        worker = threading.Thread(target=lambda: results.append(handle_start_issue(1, deps)))
        worker.start()
        assert entered.wait(5)
        second = handle_start_issue(1, deps)
        release.set()
        worker.join(5)

    assert second == "ERROR: issue 1 already has an active workspace"
    assert results == ["selfdev/issue-1"]
    assert len(clone_calls) == 1
