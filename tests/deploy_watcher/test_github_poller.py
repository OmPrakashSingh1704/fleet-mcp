from unittest.mock import MagicMock, patch

from github import Auth

from fleetmcp.deploy_watcher.github_poller import GitHubPoller


@patch("fleetmcp.deploy_watcher.github_poller.Github")
def test_get_latest_commit_sha_reads_branch_head(mock_github_cls):
    mock_repo = MagicMock()
    mock_repo.get_branch.return_value.commit.sha = "sha-1"
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    poller = GitHubPoller("token", "org/repo")

    assert poller.get_latest_commit_sha() == "sha-1"
    mock_repo.get_branch.assert_called_once_with("main")


@patch("fleetmcp.deploy_watcher.github_poller.Github")
def test_poll_once_returns_sha_only_on_change(mock_github_cls):
    mock_repo = MagicMock()
    mock_repo.get_branch.return_value.commit.sha = "sha-1"
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    poller = GitHubPoller("token", "org/repo")

    assert poller.poll_once() == "sha-1"
    assert poller.poll_once() is None

    mock_repo.get_branch.return_value.commit.sha = "sha-2"
    assert poller.poll_once() == "sha-2"


@patch("fleetmcp.deploy_watcher.github_poller.Github")
def test_constructs_github_client_with_auth_token_kwarg(mock_github_cls):
    # Controller ruling: never pass the token positionally to Github() --
    # PyGithub 2.4.0 deprecates that and emits a DeprecationWarning. Must
    # use Github(auth=Auth.Token(token)) instead.
    GitHubPoller("my-token", "org/repo")

    mock_github_cls.assert_called_once()
    args, kwargs = mock_github_cls.call_args
    assert args == ()
    assert "auth" in kwargs
    auth = kwargs["auth"]
    assert isinstance(auth, Auth.Token)
    assert auth.token == "my-token"
