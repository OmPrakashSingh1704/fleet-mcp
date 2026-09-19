from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from github import GithubException

from services.common.manifest import FleetManifest
from services.self_dev_mcp.attempt_tracker import AttemptTracker
from services.self_dev_mcp.git_ops import GitOpsError
from services.self_dev_mcp.server import (
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
        "    path: services/deploy_watcher\n"
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


@patch("services.self_dev_mcp.server.remote_branch_exists")
@patch("services.self_dev_mcp.server.create_workspace")
@patch("services.self_dev_mcp.server.create_branch")
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

    result = handle_write_file(1, "services/fixture_hello_mcp/server.py", "print('hi')", deps)

    assert result == "OK"
    assert (workspace / "services" / "fixture_hello_mcp" / "server.py").read_text() == "print('hi')"


def test_handle_write_file_refuses_protected_path_and_returns_message(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)

    result = handle_write_file(1, "services/deploy_watcher/deploy_manager.py", "bad", deps)

    assert result.startswith("REFUSED")
    assert not (workspace / "services" / "deploy_watcher" / "deploy_manager.py").exists()


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


@patch("services.self_dev_mcp.server.push")
@patch("services.self_dev_mcp.server.commit_all")
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

    with patch("services.self_dev_mcp.server._run_local_tests") as mock_run:
        result = handle_run_tests(1, "../../escape", deps)

    assert result.startswith("REFUSED")
    mock_run.assert_not_called()


def test_handle_run_tests_runs_for_valid_path(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    deps = _deps(tmp_path)
    deps.workspaces["1"] = str(workspace)

    with patch("services.self_dev_mcp.server._run_local_tests") as mock_run:
        mock_run.return_value = MagicMock(stdout="ok", stderr="")
        result = handle_run_tests(1, "services/foo", deps)

    mock_run.assert_called_once_with(str(workspace), "services/foo")
    assert result == "ok"


# --- Ruling 4: duplicate-attempt guard ---


@patch("services.self_dev_mcp.server.remote_branch_exists")
@patch("services.self_dev_mcp.server.create_workspace")
@patch("services.self_dev_mcp.server.create_branch")
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


@patch("services.self_dev_mcp.server.commit_all")
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


@patch("services.self_dev_mcp.server.push")
@patch("services.self_dev_mcp.server.commit_all")
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


@patch("services.self_dev_mcp.server.destroy_workspace")
@patch("services.self_dev_mcp.server.remote_branch_exists")
@patch("services.self_dev_mcp.server.create_workspace")
@patch("services.self_dev_mcp.server.create_branch")
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


@patch("services.self_dev_mcp.server.checkout_remote_branch")
@patch("services.self_dev_mcp.server.remote_branch_exists")
@patch("services.self_dev_mcp.server.create_workspace")
@patch("services.self_dev_mcp.server.create_branch")
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


@patch("services.self_dev_mcp.server.checkout_remote_branch")
@patch("services.self_dev_mcp.server.remote_branch_exists")
@patch("services.self_dev_mcp.server.create_workspace")
@patch("services.self_dev_mcp.server.create_branch")
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


@patch("services.self_dev_mcp.server.destroy_workspace")
@patch("services.self_dev_mcp.server.checkout_remote_branch")
@patch("services.self_dev_mcp.server.remote_branch_exists")
@patch("services.self_dev_mcp.server.create_workspace")
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


@pytest.mark.asyncio
async def test_build_mcp_app_registers_all_tools(tmp_path, monkeypatch):
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text(
        "services:\n"
        "  deploy-watcher:\n"
        "    path: services/deploy_watcher\n"
        "    protected: true\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "https://example.com/repo.git")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")

    with patch("services.self_dev_mcp.server.GitHubClient") as mock_github_client:
        mock_github_client.return_value = MagicMock()

        from services.self_dev_mcp.server import build_mcp_app

        app = build_mcp_app()
        tools = await app.list_tools()

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
