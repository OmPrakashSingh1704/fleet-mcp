from __future__ import annotations

import subprocess

import pytest

from flotilla_mcp.self_dev_mcp.repo_detect import detect_remote_url, parse_github_full_name

# --- parse_github_full_name: pure, no subprocess involved ---


@pytest.mark.parametrize(
    "remote_url, expected",
    [
        ("https://github.com/octocat/hello-world", "octocat/hello-world"),
        ("https://github.com/octocat/hello-world.git", "octocat/hello-world"),
        ("https://github.com/octocat/hello-world/", "octocat/hello-world"),
        ("https://github.com/octocat/hello-world.git/", "octocat/hello-world"),
        ("HTTPS://GITHUB.COM/octocat/hello-world.git", "octocat/hello-world"),
        ("https://x-access-token@github.com/octocat/hello-world.git", "octocat/hello-world"),
        ("git@github.com:octocat/hello-world.git", "octocat/hello-world"),
        ("git@github.com:octocat/hello-world", "octocat/hello-world"),
        ("git@github.com:octocat/hello-world.git/", "octocat/hello-world"),
        ("ssh://git@github.com/octocat/hello-world.git", "octocat/hello-world"),
        ("ssh://git@github.com/octocat/hello-world", "octocat/hello-world"),
        ("  https://github.com/octocat/hello-world.git  ".strip(), "octocat/hello-world"),
    ],
)
def test_parse_github_full_name_handles_known_url_forms(remote_url, expected):
    assert parse_github_full_name(remote_url) == expected


@pytest.mark.parametrize(
    "remote_url",
    [
        "",
        "not a url",
        "https://gitlab.com/octocat/hello-world.git",
        "git@gitlab.com:octocat/hello-world.git",
        "/home/user/repos/hello-world",
        "C:\\repos\\hello-world",
        "file:///home/user/repos/hello-world",
        "https://github.com/",
        "https://github.com/octocat",
        "ssh://example.com/octocat/hello-world.git",
    ],
)
def test_parse_github_full_name_returns_none_for_non_github_or_junk(remote_url):
    assert parse_github_full_name(remote_url) is None


# --- detect_remote_url: real subprocess calls against real git repos ---


def _init_repo(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    return repo_dir


def test_detect_remote_url_returns_origin_url(tmp_path):
    repo_dir = _init_repo(tmp_path)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/octocat/hello-world.git"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    assert detect_remote_url(str(repo_dir)) == "https://github.com/octocat/hello-world.git"


def test_detect_remote_url_returns_none_when_no_origin_remote(tmp_path):
    repo_dir = _init_repo(tmp_path)

    assert detect_remote_url(str(repo_dir)) is None


def test_detect_remote_url_returns_none_outside_a_git_repo(tmp_path):
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()

    assert detect_remote_url(str(not_a_repo)) is None


def test_detect_remote_url_returns_none_when_git_missing(tmp_path, monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr("flotilla_mcp.self_dev_mcp.repo_detect.subprocess.run", fake_run)

    assert detect_remote_url(str(tmp_path)) is None
