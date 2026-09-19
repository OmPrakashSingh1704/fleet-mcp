from __future__ import annotations

from github import Auth, Github


class GitHubPoller:
    def __init__(self, token: str, repo_full_name: str, branch: str = "main"):
        # PyGithub 2.4.0 deprecates passing the token positionally to
        # Github(); always use the auth= kwarg with an explicit Auth.Token.
        self._repo = Github(auth=Auth.Token(token)).get_repo(repo_full_name)
        self._branch = branch
        self._last_seen_sha: str | None = None

    def get_latest_commit_sha(self) -> str:
        return self._repo.get_branch(self._branch).commit.sha

    def poll_once(self) -> str | None:
        latest = self.get_latest_commit_sha()
        if latest != self._last_seen_sha:
            self._last_seen_sha = latest
            return latest
        return None
