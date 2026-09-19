from unittest.mock import MagicMock, patch

from github import Auth
from fleetmcp.self_dev_mcp.github_client import GitHubClient


@patch("fleetmcp.self_dev_mcp.github_client.Github")
def test_list_issues_by_label_delegates_to_repo(mock_github_cls):
    mock_repo = MagicMock()
    issue1 = MagicMock(pull_request=None)
    issue2 = MagicMock(pull_request=None)
    mock_repo.get_issues.return_value = [issue1, issue2]
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    issues = client.list_issues_by_label("self-dev")

    assert issues == [issue1, issue2]
    mock_repo.get_issues.assert_called_once_with(state="open", labels=["self-dev"])


@patch("fleetmcp.self_dev_mcp.github_client.Github")
def test_list_issues_by_label_filters_out_pull_requests(mock_github_cls):
    mock_repo = MagicMock()
    real_issue = MagicMock(pull_request=None)
    pr_disguised_as_issue = MagicMock(pull_request=MagicMock())
    mock_repo.get_issues.return_value = [real_issue, pr_disguised_as_issue]
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    issues = client.list_issues_by_label("self-dev")

    assert issues == [real_issue]


@patch("fleetmcp.self_dev_mcp.github_client.Github")
def test_open_pr_delegates_to_repo(mock_github_cls):
    mock_repo = MagicMock()
    mock_repo.get_pulls.return_value = []
    mock_pr = MagicMock()
    mock_repo.create_pull.return_value = mock_pr
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    result = client.open_pr("selfdev/issue-1", "main", "Fix bug", "body text")

    assert result is mock_pr
    mock_repo.create_pull.assert_called_once_with(
        title="Fix bug", body="body text", head="selfdev/issue-1", base="main"
    )


@patch("fleetmcp.self_dev_mcp.github_client.Github")
def test_open_pr_returns_existing_pr_without_creating_duplicate(mock_github_cls):
    mock_repo = MagicMock()
    mock_repo.owner.login = "org"
    existing_pr = MagicMock()
    mock_repo.get_pulls.return_value = [existing_pr]
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    result = client.open_pr("selfdev/issue-1", "main", "Fix bug", "body text")

    assert result is existing_pr
    mock_repo.get_pulls.assert_called_once_with(state="open", head="org:selfdev/issue-1", base="main")
    mock_repo.create_pull.assert_not_called()


@patch("fleetmcp.self_dev_mcp.github_client.Github")
def test_get_pr_status_all_check_runs_success(mock_github_cls):
    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_pr.head.sha = "abc123"
    mock_commit = MagicMock()
    run1 = MagicMock(status="completed", conclusion="success")
    run2 = MagicMock(status="completed", conclusion="success")
    mock_commit.get_check_runs.return_value = [run1, run2]
    mock_repo.get_pull.return_value = mock_pr
    mock_repo.get_commit.return_value = mock_commit
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    status = client.get_pr_status(42)

    assert status == "success"
    mock_repo.get_pull.assert_called_once_with(42)
    mock_repo.get_commit.assert_called_once_with("abc123")


@patch("fleetmcp.self_dev_mcp.github_client.Github")
def test_get_pr_status_one_check_run_failure(mock_github_cls):
    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_pr.head.sha = "abc123"
    mock_commit = MagicMock()
    run1 = MagicMock(status="completed", conclusion="success")
    run2 = MagicMock(status="completed", conclusion="failure")
    mock_commit.get_check_runs.return_value = [run1, run2]
    mock_repo.get_pull.return_value = mock_pr
    mock_repo.get_commit.return_value = mock_commit
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    status = client.get_pr_status(42)

    assert status == "failure"


@patch("fleetmcp.self_dev_mcp.github_client.Github")
def test_get_pr_status_one_check_run_in_progress(mock_github_cls):
    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_pr.head.sha = "abc123"
    mock_commit = MagicMock()
    run1 = MagicMock(status="completed", conclusion="success")
    run2 = MagicMock(status="in_progress", conclusion=None)
    mock_commit.get_check_runs.return_value = [run1, run2]
    mock_repo.get_pull.return_value = mock_pr
    mock_repo.get_commit.return_value = mock_commit
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    status = client.get_pr_status(42)

    assert status == "pending"


@patch("fleetmcp.self_dev_mcp.github_client.Github")
def test_get_pr_status_no_check_runs(mock_github_cls):
    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_pr.head.sha = "abc123"
    mock_commit = MagicMock()
    mock_commit.get_check_runs.return_value = []
    mock_repo.get_pull.return_value = mock_pr
    mock_repo.get_commit.return_value = mock_commit
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    status = client.get_pr_status(42)

    assert status == "pending"


@patch("fleetmcp.self_dev_mcp.github_client.Github")
def test_comment_on_issue_delegates_to_repo(mock_github_cls):
    mock_repo = MagicMock()
    mock_issue = MagicMock()
    mock_repo.get_issue.return_value = mock_issue
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    client.comment_on_issue(7, "giving up")

    mock_repo.get_issue.assert_called_once_with(7)
    mock_issue.create_comment.assert_called_once_with("giving up")


@patch("fleetmcp.self_dev_mcp.github_client.Github")
def test_github_client_uses_auth_token(mock_github_cls):
    mock_repo = MagicMock()
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token-123", "org/repo")

    # Verify Github was NOT called with positional arguments
    assert mock_github_cls.call_args.args == ()
    # Verify Github was called with auth keyword argument
    auth = mock_github_cls.call_args.kwargs["auth"]
    assert isinstance(auth, Auth.Token)
    assert auth.token == "token-123"


# --- Ruling A: lazy repo resolution (a bad token must not crash __init__) ---


@patch("fleetmcp.self_dev_mcp.github_client.Github")
def test_constructing_client_makes_no_get_repo_call(mock_github_cls):
    GitHubClient("token", "org/repo")

    mock_github_cls.return_value.get_repo.assert_not_called()


@patch("fleetmcp.self_dev_mcp.github_client.Github")
def test_first_method_call_resolves_repo_once_and_second_call_reuses_it(mock_github_cls):
    mock_repo = MagicMock()
    mock_issue = MagicMock()
    mock_repo.get_issue.return_value = mock_issue
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    client.comment_on_issue(1, "first")
    client.comment_on_issue(2, "second")

    mock_github_cls.return_value.get_repo.assert_called_once_with("org/repo")
