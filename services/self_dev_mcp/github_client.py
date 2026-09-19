from __future__ import annotations

from github import Github


class GitHubClient:
    def __init__(self, token: str, repo_full_name: str):
        self._gh = Github(token)
        self._repo = self._gh.get_repo(repo_full_name)

    def list_issues_by_label(self, label: str) -> list:
        return list(self._repo.get_issues(state="open", labels=[label]))

    def open_pr(self, branch: str, base: str, title: str, body: str):
        return self._repo.create_pull(title=title, body=body, head=branch, base=base)

    def get_pr_status(self, pr_number: int) -> str:
        pr = self._repo.get_pull(pr_number)
        latest_commit = pr.get_commits().reversed[0]
        return latest_commit.get_combined_status().state

    def comment_on_issue(self, issue_number: int, body: str) -> None:
        issue = self._repo.get_issue(issue_number)
        issue.create_comment(body)
