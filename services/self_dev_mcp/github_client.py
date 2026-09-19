from __future__ import annotations

from github import Auth, Github


class GitHubClient:
    def __init__(self, token: str, repo_full_name: str):
        self._gh = Github(auth=Auth.Token(token))
        self._repo = self._gh.get_repo(repo_full_name)

    def list_issues_by_label(self, label: str) -> list:
        issues = self._repo.get_issues(state="open", labels=[label])
        # GitHub's issues endpoint also returns pull requests; filter those
        # out so the agent never treats its own PR as a work item.
        return [issue for issue in issues if issue.pull_request is None]

    def open_pr(self, branch: str, base: str, title: str, body: str):
        owner = self._repo.owner.login
        existing = list(self._repo.get_pulls(state="open", head=f"{owner}:{branch}", base=base))
        if existing:
            return existing[0]
        return self._repo.create_pull(title=title, body=body, head=branch, base=base)

    def get_pr_status(self, pr_number: int) -> str:
        pr = self._repo.get_pull(pr_number)
        commit = self._repo.get_commit(pr.head.sha)
        runs = list(commit.get_check_runs())
        failure_conclusions = {
            "failure",
            "cancelled",
            "timed_out",
            "action_required",
            "startup_failure",
        }
        if any(run.conclusion in failure_conclusions for run in runs):
            return "failure"
        if not runs or any(run.status != "completed" for run in runs):
            return "pending"
        return "success"

    def comment_on_issue(self, issue_number: int, body: str) -> None:
        issue = self._repo.get_issue(issue_number)
        issue.create_comment(body)
