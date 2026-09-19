from unittest.mock import MagicMock, patch, call

from github import Auth
from services.self_dev_mcp.github_client import GitHubClient


@patch("services.self_dev_mcp.github_client.Github")
def test_list_issues_by_label_delegates_to_repo(mock_github_cls):
    mock_repo = MagicMock()
    mock_repo.get_issues.return_value = ["issue-1", "issue-2"]
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    issues = client.list_issues_by_label("self-dev")

    assert issues == ["issue-1", "issue-2"]
    mock_repo.get_issues.assert_called_once_with(state="open", labels=["self-dev"])


@patch("services.self_dev_mcp.github_client.Github")
def test_open_pr_delegates_to_repo(mock_github_cls):
    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_repo.create_pull.return_value = mock_pr
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    result = client.open_pr("selfdev/issue-1", "main", "Fix bug", "body text")

    assert result is mock_pr
    mock_repo.create_pull.assert_called_once_with(
        title="Fix bug", body="body text", head="selfdev/issue-1", base="main"
    )


@patch("services.self_dev_mcp.github_client.Github")
def test_get_pr_status_reads_combined_status(mock_github_cls):
    mock_repo = MagicMock()
    mock_pr = MagicMock()
    mock_commit = MagicMock()
    mock_commit.get_combined_status.return_value.state = "success"
    mock_pr.get_commits.return_value.reversed = [mock_commit]
    mock_repo.get_pull.return_value = mock_pr
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    status = client.get_pr_status(42)

    assert status == "success"
    mock_repo.get_pull.assert_called_once_with(42)


@patch("services.self_dev_mcp.github_client.Github")
def test_comment_on_issue_delegates_to_repo(mock_github_cls):
    mock_repo = MagicMock()
    mock_issue = MagicMock()
    mock_repo.get_issue.return_value = mock_issue
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    client = GitHubClient("token", "org/repo")
    client.comment_on_issue(7, "giving up")

    mock_repo.get_issue.assert_called_once_with(7)
    mock_issue.create_comment.assert_called_once_with("giving up")


@patch("services.self_dev_mcp.github_client.Auth.Token")
@patch("services.self_dev_mcp.github_client.Github")
def test_github_client_uses_auth_token(mock_github_cls, mock_auth_token):
    mock_repo = MagicMock()
    mock_github_cls.return_value.get_repo.return_value = mock_repo
    mock_token_instance = MagicMock()
    mock_auth_token.return_value = mock_token_instance

    client = GitHubClient("my-token", "org/repo")

    # Verify Github was called with auth=Auth.Token(...), not positional token
    mock_github_cls.assert_called_once_with(auth=mock_token_instance)
    # Verify Auth.Token was called with the input token
    mock_auth_token.assert_called_once_with("my-token")
    # Verify Github was NOT called with positional arguments
    assert mock_github_cls.call_args[0] == ()  # No positional args
