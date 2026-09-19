# Self-Dev MCP Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the foundation pipeline for the self-development MCP subsystem — protected-core enforcement, the Self-Dev MCP's git/GitHub primitives, and the Deploy Watcher's blue/green deploy + rollback machinery — proven end to end against a fixture service. This covers the self-healing and self-patching capability tiers from the spec (self-healing is this same pipeline plus an immediate rollback step). Self-extending (scaffolding brand-new MCP servers) is out of scope for this plan.

**Architecture:** Monorepo with path-scoped protection. A shared `FleetManifest` (backed by `fleet_manifest.yaml`, itself hardcoded-protected) is the single source of truth for which paths are off-limits. Self-Dev MCP exposes primitive MCP tools only (clone, write, test, commit, open PR) — it holds no Docker socket access and no deploy credentials, and the actual code-generation reasoning is supplied by whatever external agent calls it through the gateway. Deploy Watcher is a separate service holding all deploy authority (Docker socket access), polling GitHub for merged commits and performing blue/green swaps with health checks, a known-good floor, and post-promotion probation rollback.

**Tech Stack:** Python 3.11+, pytest, PyYAML, PyGithub, docker (docker-py), requests, Flask (fixture service only), the `mcp` Python SDK (FastMCP).

**Spec:** `docs/superpowers/specs/2026-09-19-self-dev-mcp-design.md`

## Global Constraints

- Protected core (never writable by Self-Dev MCP, enforced independent of manifest content): `fleet_manifest.yaml` and `services/common/manifest.py` are hardcoded-protected; `deploy-watcher`, `permission-manager`, and `mcp-gateway` services are marked `protected: true` in the manifest.
- No auto-merge, ever. A human is the only thing that can merge a PR (enforced via GitHub branch protection + CODEOWNERS, configured in Task 12 — not enforceable from inside this codebase).
- Self-Dev MCP has no Docker socket access and no deploy credentials — it must never import `docker` or receive Docker/deploy environment variables.
- Default attempt cap: 5 write attempts per issue before Self-Dev MCP refuses further writes for that issue.
- Default health-check requirement: 3 consecutive successes before a new container is promoted.
- Default post-promotion probation period: 1800 seconds (30 minutes); a single failed check during probation triggers automatic rollback.
- Known-good floor: the last successfully-deployed image tag per service is recorded and is never overwritten except by a subsequent successful deploy.
- Scope simplifications explicitly deferred (not bugs, follow-up work): Deploy Watcher redeploys every non-protected service on any new commit to `main` rather than diffing which service's files changed; there is no image-pruning/retention job yet (acceptable because nothing in this plan deletes images, so the known-good floor is trivially satisfied); the end-to-end integration test exercises git/GitHub-shaped operations against a local bare repo rather than live GitHub, since automated tests should not depend on live GitHub credentials — a live-GitHub acceptance run is a manual step, per the spec's "manual acceptance check" requirement.

---

## Task 1: Project scaffolding, fleet manifest, and protection engine

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `fleet_manifest.yaml`
- Create: `services/__init__.py`
- Create: `services/common/__init__.py`
- Create: `services/common/manifest.py`
- Create: `tests/__init__.py`
- Test: `tests/test_manifest.py`

**Interfaces:**
- Produces: `FleetManifest.load(manifest_path: str) -> FleetManifest`, `FleetManifest.get(name: str) -> ServiceConfig`, `FleetManifest.all_services() -> list[ServiceConfig]`, `FleetManifest.is_path_protected(relative_path: str) -> bool`, `ServiceConfig(name, path, protected, protected_paths, container, health_check)`, constant `ALWAYS_PROTECTED_PATHS: frozenset[str]`.

- [ ] **Step 1: Create project scaffolding**

`requirements.txt`:
```
PyYAML==6.0.2
PyGithub==2.4.0
docker==7.1.0
requests==2.32.3
flask==3.0.3
mcp==1.2.0
pytest==8.3.3
pytest-mock==3.14.0
```

`pyproject.toml`:
```toml
[project]
name = "generalist-mcp"
version = "0.1.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`services/__init__.py`, `services/common/__init__.py`, `tests/__init__.py`: empty files.

- [ ] **Step 2: Write the failing tests for the protection engine**

`tests/test_manifest.py`:
```python
import textwrap

from services.common.manifest import FleetManifest


def _write_manifest(tmp_path, content: str) -> str:
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text(textwrap.dedent(content))
    return str(manifest_path)


def test_protected_service_blocks_all_paths_under_it(tmp_path):
    path = _write_manifest(tmp_path, """
        services:
          deploy-watcher:
            path: services/deploy_watcher
            protected: true
    """)
    manifest = FleetManifest.load(path)
    assert manifest.is_path_protected("services/deploy_watcher/deploy_manager.py")


def test_unprotected_service_path_is_allowed(tmp_path):
    path = _write_manifest(tmp_path, """
        services:
          fixture-hello-mcp:
            path: services/fixture_hello_mcp
            protected: false
    """)
    manifest = FleetManifest.load(path)
    assert not manifest.is_path_protected("services/fixture_hello_mcp/server.py")


def test_fleet_manifest_yaml_itself_is_always_protected(tmp_path):
    path = _write_manifest(tmp_path, "services: {}")
    manifest = FleetManifest.load(path)
    assert manifest.is_path_protected("fleet_manifest.yaml")


def test_manifest_loader_module_is_always_protected(tmp_path):
    path = _write_manifest(tmp_path, "services: {}")
    manifest = FleetManifest.load(path)
    assert manifest.is_path_protected("services/common/manifest.py")


def test_specific_protected_path_within_unprotected_service(tmp_path):
    path = _write_manifest(tmp_path, """
        services:
          self-dev-mcp:
            path: services/self_dev_mcp
            protected: false
            protected_paths:
              - services/self_dev_mcp/config.py
    """)
    manifest = FleetManifest.load(path)
    assert manifest.is_path_protected("services/self_dev_mcp/config.py")
    assert not manifest.is_path_protected("services/self_dev_mcp/tools.py")


def test_get_and_all_services(tmp_path):
    path = _write_manifest(tmp_path, """
        services:
          fixture-hello-mcp:
            path: services/fixture_hello_mcp
            container: fixture-hello-mcp
            health_check: http://fixture-hello-mcp:8080/health
    """)
    manifest = FleetManifest.load(path)
    service = manifest.get("fixture-hello-mcp")
    assert service.container == "fixture-hello-mcp"
    assert service.health_check == "http://fixture-hello-mcp:8080/health"
    assert manifest.all_services() == [service]
```

- [ ] **Step 2b: Run tests to verify they fail**

Run: `pip install -r requirements.txt && pytest tests/test_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.common.manifest'`

- [ ] **Step 3: Implement the manifest and protection engine**

`services/common/manifest.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field

import yaml

ALWAYS_PROTECTED_PATHS = frozenset({
    "fleet_manifest.yaml",
    "services/common/manifest.py",
})


@dataclass
class ServiceConfig:
    name: str
    path: str
    protected: bool = False
    protected_paths: list[str] = field(default_factory=list)
    container: str | None = None
    health_check: str | None = None


class FleetManifest:
    def __init__(self, services: dict[str, ServiceConfig]):
        self._services = services

    @classmethod
    def load(cls, manifest_path: str) -> "FleetManifest":
        with open(manifest_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        services: dict[str, ServiceConfig] = {}
        for name, cfg in (raw.get("services") or {}).items():
            services[name] = ServiceConfig(
                name=name,
                path=cfg["path"],
                protected=cfg.get("protected", False),
                protected_paths=cfg.get("protected_paths", []),
                container=cfg.get("container"),
                health_check=cfg.get("health_check"),
            )
        return cls(services)

    def get(self, name: str) -> ServiceConfig:
        return self._services[name]

    def all_services(self) -> list[ServiceConfig]:
        return list(self._services.values())

    def is_path_protected(self, relative_path: str) -> bool:
        normalized = relative_path.replace("\\", "/").lstrip("/")
        if normalized in ALWAYS_PROTECTED_PATHS:
            return True
        for service in self._services.values():
            service_prefix = service.path.rstrip("/") + "/"
            if service.protected and normalized.startswith(service_prefix):
                return True
            for protected_path in service.protected_paths:
                if normalized == protected_path.replace("\\", "/"):
                    return True
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_manifest.py -v`
Expected: all 6 tests PASS

- [ ] **Step 5: Create the real fleet manifest for this repo**

`fleet_manifest.yaml`:
```yaml
services:
  fixture-hello-mcp:
    path: services/fixture_hello_mcp
    protected: false
    container: fixture-hello-mcp
    health_check: http://fixture-hello-mcp:8080/health
  self-dev-mcp:
    path: services/self_dev_mcp
    protected: false
    container: self-dev-mcp
    health_check: http://self-dev-mcp:8080/health
  deploy-watcher:
    path: services/deploy_watcher
    protected: true
  permission-manager:
    path: services/permission_manager
    protected: true
  mcp-gateway:
    path: services/mcp_gateway
    protected: true
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.txt fleet_manifest.yaml services/__init__.py services/common/ tests/__init__.py tests/test_manifest.py
git commit -m "feat: add fleet manifest and protection engine"
```

---

## Task 2: Self-Dev MCP workspace, git ops, and config

**Files:**
- Create: `services/self_dev_mcp/__init__.py`
- Create: `services/self_dev_mcp/config.py`
- Create: `services/self_dev_mcp/git_ops.py`
- Create: `services/self_dev_mcp/workspace.py`
- Test: `tests/self_dev_mcp/__init__.py`
- Test: `tests/self_dev_mcp/test_git_ops.py`
- Test: `tests/self_dev_mcp/test_config.py`

**Interfaces:**
- Consumes: nothing from Task 1 directly (git/workspace are manifest-agnostic).
- Produces: `git_ops.clone(remote_url, dest_dir) -> None`, `git_ops.create_branch(repo_dir, branch_name) -> None`, `git_ops.commit_all(repo_dir, message) -> str` (returns commit sha), `git_ops.push(repo_dir, branch_name) -> None`, `git_ops.current_commit_sha(repo_dir) -> str`, `git_ops.GitOpsError`; `workspace.create_workspace(remote_url: str) -> str`, `workspace.destroy_workspace(workspace_dir: str) -> None`; `config.Settings(repo_remote, github_token, github_repo_full_name, max_attempts)`, `config.load_settings() -> Settings`.

- [ ] **Step 1: Write the failing test for git_ops**

`tests/self_dev_mcp/__init__.py`: empty file.

`tests/self_dev_mcp/test_git_ops.py`:
```python
import subprocess

from services.self_dev_mcp import git_ops


def _init_bare_remote(tmp_path) -> str:
    remote_dir = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote_dir)], check=True, capture_output=True)

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    subprocess.run(["git", "init"], cwd=seed_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "seed@example.com"], cwd=seed_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Seed"], cwd=seed_dir, check=True)
    (seed_dir / "README.md").write_text("seed")
    subprocess.run(["git", "add", "-A"], cwd=seed_dir, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=seed_dir, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=seed_dir, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote_dir)], cwd=seed_dir, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=seed_dir, check=True, capture_output=True)
    return str(remote_dir)


def test_clone_branch_commit_push_round_trip(tmp_path):
    remote_url = _init_bare_remote(tmp_path)
    workspace = tmp_path / "workspace"

    git_ops.clone(remote_url, str(workspace))
    git_ops.create_branch(str(workspace), "selfdev/issue-1")
    (workspace / "new_file.txt").write_text("hello")
    sha = git_ops.commit_all(str(workspace), "add new_file")
    git_ops.push(str(workspace), "selfdev/issue-1")

    check_dir = tmp_path / "check"
    git_ops.clone(remote_url, str(check_dir))
    subprocess.run(["git", "checkout", "selfdev/issue-1"], cwd=check_dir, check=True, capture_output=True)
    assert (check_dir / "new_file.txt").read_text() == "hello"
    assert git_ops.current_commit_sha(str(check_dir)) == sha


def test_commit_all_raises_on_empty_commit(tmp_path):
    remote_url = _init_bare_remote(tmp_path)
    workspace = tmp_path / "workspace"
    git_ops.clone(remote_url, str(workspace))

    import pytest
    with pytest.raises(git_ops.GitOpsError):
        git_ops.commit_all(str(workspace), "nothing changed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/self_dev_mcp/test_git_ops.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.self_dev_mcp'`

- [ ] **Step 3: Implement git_ops and workspace**

`services/self_dev_mcp/__init__.py`: empty file.

`services/self_dev_mcp/git_ops.py`:
```python
from __future__ import annotations

import subprocess


class GitOpsError(Exception):
    pass


def _run_git(args: list[str], cwd: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GitOpsError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout.strip()


def clone(remote_url: str, dest_dir: str) -> None:
    subprocess.run(["git", "clone", remote_url, dest_dir], check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "self-dev-mcp@fleet.local"], cwd=dest_dir, check=True)
    subprocess.run(["git", "config", "user.name", "self-dev-mcp"], cwd=dest_dir, check=True)


def create_branch(repo_dir: str, branch_name: str) -> None:
    _run_git(["checkout", "-b", branch_name], cwd=repo_dir)


def commit_all(repo_dir: str, message: str) -> str:
    _run_git(["add", "-A"], cwd=repo_dir)
    _run_git(["commit", "-m", message], cwd=repo_dir)
    return _run_git(["rev-parse", "HEAD"], cwd=repo_dir)


def push(repo_dir: str, branch_name: str) -> None:
    _run_git(["push", "-u", "origin", branch_name], cwd=repo_dir)


def current_commit_sha(repo_dir: str) -> str:
    return _run_git(["rev-parse", "HEAD"], cwd=repo_dir)
```

`services/self_dev_mcp/workspace.py`:
```python
from __future__ import annotations

import shutil
import tempfile

from services.self_dev_mcp.git_ops import clone


def create_workspace(remote_url: str) -> str:
    workspace_dir = tempfile.mkdtemp(prefix="selfdev-")
    clone(remote_url, workspace_dir)
    return workspace_dir


def destroy_workspace(workspace_dir: str) -> None:
    shutil.rmtree(workspace_dir, ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/self_dev_mcp/test_git_ops.py -v`
Expected: both tests PASS

- [ ] **Step 5: Write the failing test for config**

`tests/self_dev_mcp/test_config.py`:
```python
from services.self_dev_mcp.config import load_settings


def test_load_settings_reads_env(monkeypatch):
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "git@example.com:org/repo.git")
    monkeypatch.setenv("GITHUB_TOKEN", "token-123")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")
    monkeypatch.delenv("SELF_DEV_MAX_ATTEMPTS", raising=False)

    settings = load_settings()

    assert settings.repo_remote == "git@example.com:org/repo.git"
    assert settings.github_token == "token-123"
    assert settings.github_repo_full_name == "org/repo"
    assert settings.max_attempts == 5


def test_load_settings_respects_max_attempts_override(monkeypatch):
    monkeypatch.setenv("SELF_DEV_REPO_REMOTE", "git@example.com:org/repo.git")
    monkeypatch.setenv("GITHUB_TOKEN", "token-123")
    monkeypatch.setenv("GITHUB_REPO_FULL_NAME", "org/repo")
    monkeypatch.setenv("SELF_DEV_MAX_ATTEMPTS", "3")

    settings = load_settings()

    assert settings.max_attempts == 3
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/self_dev_mcp/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.self_dev_mcp.config'`

- [ ] **Step 7: Implement config**

`services/self_dev_mcp/config.py`:
```python
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    repo_remote: str
    github_token: str
    github_repo_full_name: str
    max_attempts: int


def load_settings() -> Settings:
    return Settings(
        repo_remote=os.environ["SELF_DEV_REPO_REMOTE"],
        github_token=os.environ["GITHUB_TOKEN"],
        github_repo_full_name=os.environ["GITHUB_REPO_FULL_NAME"],
        max_attempts=int(os.environ.get("SELF_DEV_MAX_ATTEMPTS", "5")),
    )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/self_dev_mcp/ -v`
Expected: all tests PASS

- [ ] **Step 9: Commit**

```bash
git add services/self_dev_mcp/__init__.py services/self_dev_mcp/config.py services/self_dev_mcp/git_ops.py services/self_dev_mcp/workspace.py tests/self_dev_mcp/__init__.py tests/self_dev_mcp/test_git_ops.py tests/self_dev_mcp/test_config.py
git commit -m "feat: add self-dev-mcp git ops, workspace, and config"
```

---

## Task 3: Self-Dev MCP protected file tools and attempt tracker

This is the most important task in the plan: it must be structurally impossible for the Self-Dev MCP's own write tool to touch a protected path, regardless of what an external agent asks it to do.

**Files:**
- Create: `services/self_dev_mcp/attempt_tracker.py`
- Create: `services/self_dev_mcp/tools.py`
- Test: `tests/self_dev_mcp/test_attempt_tracker.py`
- Test: `tests/self_dev_mcp/test_tools.py`

**Interfaces:**
- Consumes: `FleetManifest` from Task 1 (`services.common.manifest.FleetManifest`).
- Produces: `attempt_tracker.AttemptTracker(max_attempts: int)` with `.record_attempt(issue_key: str) -> int`, `.attempts_remaining(issue_key: str) -> int`, `.is_exhausted(issue_key: str) -> bool`; `attempt_tracker.AttemptsExhaustedError`; `tools.write_file(workspace_dir, relative_path, content, manifest, issue_key, tracker) -> None`, `tools.read_file(workspace_dir, relative_path) -> str`, `tools.run_local_tests(workspace_dir, service_relative_path) -> subprocess.CompletedProcess`, `tools.ProtectedPathError`.

- [ ] **Step 1: Write the failing test for attempt_tracker**

`tests/self_dev_mcp/test_attempt_tracker.py`:
```python
from services.self_dev_mcp.attempt_tracker import AttemptTracker


def test_attempts_remaining_decreases_with_each_record():
    tracker = AttemptTracker(max_attempts=3)
    assert tracker.attempts_remaining("issue-1") == 3
    tracker.record_attempt("issue-1")
    assert tracker.attempts_remaining("issue-1") == 2


def test_is_exhausted_after_max_attempts():
    tracker = AttemptTracker(max_attempts=2)
    tracker.record_attempt("issue-1")
    assert not tracker.is_exhausted("issue-1")
    tracker.record_attempt("issue-1")
    assert tracker.is_exhausted("issue-1")


def test_attempts_are_scoped_per_issue():
    tracker = AttemptTracker(max_attempts=1)
    tracker.record_attempt("issue-1")
    assert tracker.is_exhausted("issue-1")
    assert not tracker.is_exhausted("issue-2")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/self_dev_mcp/test_attempt_tracker.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement attempt_tracker**

`services/self_dev_mcp/attempt_tracker.py`:
```python
from __future__ import annotations

import threading


class AttemptsExhaustedError(Exception):
    pass


class AttemptTracker:
    def __init__(self, max_attempts: int = 5):
        self._max_attempts = max_attempts
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def record_attempt(self, issue_key: str) -> int:
        with self._lock:
            count = self._counts.get(issue_key, 0) + 1
            self._counts[issue_key] = count
            return count

    def attempts_remaining(self, issue_key: str) -> int:
        with self._lock:
            return max(0, self._max_attempts - self._counts.get(issue_key, 0))

    def is_exhausted(self, issue_key: str) -> bool:
        return self.attempts_remaining(issue_key) <= 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/self_dev_mcp/test_attempt_tracker.py -v`
Expected: all 3 tests PASS

- [ ] **Step 5: Write the failing tests for tools.py, including the protected-write adversarial test**

`tests/self_dev_mcp/test_tools.py`:
```python
import pytest

from services.common.manifest import FleetManifest
from services.self_dev_mcp.attempt_tracker import AttemptTracker, AttemptsExhaustedError
from services.self_dev_mcp import tools


def _manifest_with_protected_deploy_watcher(tmp_path):
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text(
        "services:\n"
        "  deploy-watcher:\n"
        "    path: services/deploy_watcher\n"
        "    protected: true\n"
    )
    return FleetManifest.load(str(manifest_path))


def test_write_file_refuses_protected_path(tmp_path):
    manifest = _manifest_with_protected_deploy_watcher(tmp_path)
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(tools.ProtectedPathError):
        tools.write_file(
            str(workspace),
            "services/deploy_watcher/deploy_manager.py",
            "malicious content",
            manifest,
            "issue-1",
            tracker,
        )

    assert not (workspace / "services" / "deploy_watcher" / "deploy_manager.py").exists()


def test_write_file_refuses_hardcoded_protected_path_even_with_permissive_manifest(tmp_path):
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text("services: {}")
    manifest = FleetManifest.load(str(manifest_path))
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(tools.ProtectedPathError):
        tools.write_file(str(workspace), "fleet_manifest.yaml", "services: {}", manifest, "issue-1", tracker)


def test_write_file_succeeds_for_unprotected_path(tmp_path):
    manifest = _manifest_with_protected_deploy_watcher(tmp_path)
    tracker = AttemptTracker(max_attempts=5)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tools.write_file(str(workspace), "services/fixture_hello_mcp/server.py", "print('hi')", manifest, "issue-1", tracker)

    written = workspace / "services" / "fixture_hello_mcp" / "server.py"
    assert written.read_text() == "print('hi')"


def test_write_file_raises_once_attempts_exhausted(tmp_path):
    manifest = _manifest_with_protected_deploy_watcher(tmp_path)
    tracker = AttemptTracker(max_attempts=1)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    tools.write_file(str(workspace), "a.py", "1", manifest, "issue-1", tracker)

    with pytest.raises(AttemptsExhaustedError):
        tools.write_file(str(workspace), "b.py", "2", manifest, "issue-1", tracker)


def test_read_file_returns_contents(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.py").write_text("hello")

    assert tools.read_file(str(workspace), "a.py") == "hello"


def test_run_local_tests_reports_failure_without_raising(tmp_path):
    workspace = tmp_path / "workspace"
    service_dir = workspace / "service"
    service_dir.mkdir(parents=True)
    (service_dir / "test_fail.py").write_text("def test_fail():\n    assert False\n")

    result = tools.run_local_tests(str(workspace), "service")

    assert result.returncode != 0
    assert "test_fail" in result.stdout
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/self_dev_mcp/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.self_dev_mcp.tools'`

- [ ] **Step 7: Implement tools.py**

`services/self_dev_mcp/tools.py`:
```python
from __future__ import annotations

import os
import subprocess

from services.common.manifest import FleetManifest
from services.self_dev_mcp.attempt_tracker import AttemptTracker, AttemptsExhaustedError


class ProtectedPathError(Exception):
    pass


def write_file(
    workspace_dir: str,
    relative_path: str,
    content: str,
    manifest: FleetManifest,
    issue_key: str,
    tracker: AttemptTracker,
) -> None:
    if tracker.is_exhausted(issue_key):
        raise AttemptsExhaustedError(f"attempt cap reached for {issue_key}")
    if manifest.is_path_protected(relative_path):
        raise ProtectedPathError(f"refused to write protected path: {relative_path}")

    tracker.record_attempt(issue_key)
    target_path = os.path.join(workspace_dir, relative_path)
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)


def read_file(workspace_dir: str, relative_path: str) -> str:
    target_path = os.path.join(workspace_dir, relative_path)
    with open(target_path, "r", encoding="utf-8") as f:
        return f.read()


def run_local_tests(workspace_dir: str, service_relative_path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python", "-m", "pytest", service_relative_path, "-v"],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
    )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/self_dev_mcp/test_tools.py -v`
Expected: all 6 tests PASS

- [ ] **Step 9: Commit**

```bash
git add services/self_dev_mcp/attempt_tracker.py services/self_dev_mcp/tools.py tests/self_dev_mcp/test_attempt_tracker.py tests/self_dev_mcp/test_tools.py
git commit -m "feat: add self-dev-mcp protected write tools and attempt tracker"
```

---

## Task 4: Self-Dev MCP GitHub client

**Files:**
- Create: `services/self_dev_mcp/github_client.py`
- Test: `tests/self_dev_mcp/test_github_client.py`

**Interfaces:**
- Produces: `github_client.GitHubClient(token: str, repo_full_name: str)` with `.list_issues_by_label(label: str) -> list`, `.open_pr(branch: str, base: str, title: str, body: str) -> object` (PyGithub `PullRequest`), `.get_pr_status(pr_number: int) -> str` (one of `"pending"`, `"success"`, `"failure"`), `.comment_on_issue(issue_number: int, body: str) -> None`.

- [ ] **Step 1: Write the failing tests, mocking PyGithub**

`tests/self_dev_mcp/test_github_client.py`:
```python
from unittest.mock import MagicMock, patch

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/self_dev_mcp/test_github_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.self_dev_mcp.github_client'`

- [ ] **Step 3: Implement github_client.py**

`services/self_dev_mcp/github_client.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/self_dev_mcp/test_github_client.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/self_dev_mcp/github_client.py tests/self_dev_mcp/test_github_client.py
git commit -m "feat: add self-dev-mcp github client"
```

---

## Task 5: Self-Dev MCP server wiring

**Files:**
- Create: `services/self_dev_mcp/server.py`
- Test: `tests/self_dev_mcp/test_server.py`

**Interfaces:**
- Consumes: `create_workspace`/`destroy_workspace` (Task 2), `git_ops.create_branch`/`commit_all`/`push` (Task 2), `tools.write_file`/`read_file`/`run_local_tests`/`ProtectedPathError` (Task 3), `AttemptTracker`/`AttemptsExhaustedError` (Task 3), `GitHubClient` (Task 4), `FleetManifest` (Task 1), `load_settings` (Task 2).
- Produces: plain, directly-testable functions `handle_start_issue(issue_number, deps) -> str`, `handle_write_file(issue_number, relative_path, content, deps) -> str`, `handle_run_tests(issue_number, service_relative_path, deps) -> str`, `handle_submit_pr(issue_number, title, body, deps) -> str`, plus a `ServerDependencies` container dataclass bundling `manifest`, `tracker`, `github_client`, `workspaces: dict[str, str]`. These plain functions are registered as MCP tools at module load time via FastMCP so the decorator layer never has to be exercised in tests.

- [ ] **Step 1: Write the failing tests against the plain handler functions**

`tests/self_dev_mcp/test_server.py`:
```python
from unittest.mock import MagicMock, patch

import pytest

from services.common.manifest import FleetManifest
from services.self_dev_mcp.attempt_tracker import AttemptTracker, AttemptsExhaustedError
from services.self_dev_mcp.tools import ProtectedPathError
from services.self_dev_mcp.server import ServerDependencies, handle_start_issue, handle_write_file, handle_submit_pr


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
        manifest=_empty_manifest(tmp_path),
        tracker=AttemptTracker(max_attempts=5),
        github_client=MagicMock(),
        workspaces={},
    )


@patch("services.self_dev_mcp.server.create_workspace")
@patch("services.self_dev_mcp.server.create_branch")
def test_handle_start_issue_creates_workspace_and_branch(mock_create_branch, mock_create_workspace, tmp_path):
    mock_create_workspace.return_value = str(tmp_path / "workspace")
    deps = _deps(tmp_path)

    branch_name = handle_start_issue(1, deps)

    assert branch_name == "selfdev/issue-1"
    assert deps.workspaces["1"] == str(tmp_path / "workspace")
    mock_create_branch.assert_called_once_with(str(tmp_path / "workspace"), "selfdev/issue-1")


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/self_dev_mcp/test_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.self_dev_mcp.server'`

- [ ] **Step 3: Implement server.py**

`services/self_dev_mcp/server.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field

from mcp.server.fastmcp import FastMCP

from services.common.manifest import FleetManifest
from services.self_dev_mcp.attempt_tracker import AttemptsExhaustedError, AttemptTracker
from services.self_dev_mcp.config import load_settings
from services.self_dev_mcp.git_ops import commit_all, create_branch, push
from services.self_dev_mcp.github_client import GitHubClient
from services.self_dev_mcp.tools import ProtectedPathError
from services.self_dev_mcp.tools import run_local_tests as _run_local_tests
from services.self_dev_mcp.tools import write_file as _write_file
from services.self_dev_mcp.workspace import create_workspace, destroy_workspace


@dataclass
class ServerDependencies:
    manifest: FleetManifest
    tracker: AttemptTracker
    github_client: GitHubClient
    workspaces: dict = field(default_factory=dict)


def _branch_name(issue_number: int) -> str:
    return f"selfdev/issue-{issue_number}"


def handle_start_issue(issue_number: int, deps: ServerDependencies) -> str:
    issue_key = str(issue_number)
    workspace_dir = create_workspace(load_settings().repo_remote)
    branch_name = _branch_name(issue_number)
    create_branch(workspace_dir, branch_name)
    deps.workspaces[issue_key] = workspace_dir
    return branch_name


def handle_write_file(issue_number: int, relative_path: str, content: str, deps: ServerDependencies) -> str:
    issue_key = str(issue_number)
    workspace_dir = deps.workspaces[issue_key]
    try:
        _write_file(workspace_dir, relative_path, content, deps.manifest, issue_key, deps.tracker)
    except ProtectedPathError as exc:
        return f"REFUSED: {exc}"
    except AttemptsExhaustedError as exc:
        deps.github_client.comment_on_issue(issue_number, f"Giving up: {exc}")
        return f"EXHAUSTED: {exc}"
    return "OK"


def handle_run_tests(issue_number: int, service_relative_path: str, deps: ServerDependencies) -> str:
    workspace_dir = deps.workspaces[str(issue_number)]
    result = _run_local_tests(workspace_dir, service_relative_path)
    return result.stdout + result.stderr


def handle_submit_pr(issue_number: int, title: str, body: str, deps: ServerDependencies) -> str:
    issue_key = str(issue_number)
    workspace_dir = deps.workspaces[issue_key]
    branch_name = _branch_name(issue_number)
    commit_all(workspace_dir, title)
    push(workspace_dir, branch_name)
    pr = deps.github_client.open_pr(branch_name, base="main", title=title, body=body)
    destroy_workspace(workspace_dir)
    del deps.workspaces[issue_key]
    return f"opened PR #{pr.number}"


def build_mcp_app() -> FastMCP:
    settings = load_settings()
    deps = ServerDependencies(
        manifest=FleetManifest.load("fleet_manifest.yaml"),
        tracker=AttemptTracker(max_attempts=settings.max_attempts),
        github_client=GitHubClient(settings.github_token, settings.github_repo_full_name),
    )

    app = FastMCP("self-dev-mcp")

    @app.tool(name="start_issue")
    def start_issue(issue_number: int) -> str:
        return handle_start_issue(issue_number, deps)

    @app.tool(name="write_file")
    def write_file(issue_number: int, relative_path: str, content: str) -> str:
        return handle_write_file(issue_number, relative_path, content, deps)

    @app.tool(name="run_tests")
    def run_tests(issue_number: int, service_relative_path: str) -> str:
        return handle_run_tests(issue_number, service_relative_path, deps)

    @app.tool(name="submit_pr")
    def submit_pr(issue_number: int, title: str, body: str) -> str:
        return handle_submit_pr(issue_number, title, body, deps)

    return app


if __name__ == "__main__":
    build_mcp_app().run()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/self_dev_mcp/test_server.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/self_dev_mcp/server.py tests/self_dev_mcp/test_server.py
git commit -m "feat: wire self-dev-mcp tools into an MCP server"
```

---

## Task 6: Deploy Watcher service registry and known-good store

**Files:**
- Create: `services/deploy_watcher/__init__.py`
- Create: `services/deploy_watcher/registry.py`
- Create: `services/deploy_watcher/known_good.py`
- Test: `tests/deploy_watcher/__init__.py`
- Test: `tests/deploy_watcher/test_registry.py`
- Test: `tests/deploy_watcher/test_known_good.py`

**Interfaces:**
- Produces: `registry.ServiceRegistry(registry_path: str)` with `.set_active_container(service_name, container_name) -> None`, `.get_active_container(service_name) -> str | None`; `known_good.KnownGoodStore(store_path: str)` with `.record(service_name, image_tag) -> None`, `.get(service_name) -> str | None`.

- [ ] **Step 1: Write the failing tests**

`tests/deploy_watcher/__init__.py`: empty file.

`tests/deploy_watcher/test_registry.py`:
```python
from services.deploy_watcher.registry import ServiceRegistry


def test_set_and_get_active_container(tmp_path):
    registry = ServiceRegistry(str(tmp_path / "registry.json"))
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-abc123")

    assert registry.get_active_container("fixture-hello-mcp") == "fixture-hello-mcp-abc123"


def test_get_active_container_returns_none_when_unset(tmp_path):
    registry = ServiceRegistry(str(tmp_path / "registry.json"))

    assert registry.get_active_container("unknown-service") is None


def test_registry_persists_across_instances(tmp_path):
    registry_path = str(tmp_path / "registry.json")
    ServiceRegistry(registry_path).set_active_container("svc", "container-1")

    reloaded = ServiceRegistry(registry_path)
    assert reloaded.get_active_container("svc") == "container-1"
```

`tests/deploy_watcher/test_known_good.py`:
```python
from services.deploy_watcher.known_good import KnownGoodStore


def test_record_and_get(tmp_path):
    store = KnownGoodStore(str(tmp_path / "known_good.json"))
    store.record("svc", "svc:sha1")

    assert store.get("svc") == "svc:sha1"


def test_get_returns_none_when_unset(tmp_path):
    store = KnownGoodStore(str(tmp_path / "known_good.json"))

    assert store.get("unknown-service") is None


def test_record_overwrites_previous_value(tmp_path):
    store = KnownGoodStore(str(tmp_path / "known_good.json"))
    store.record("svc", "svc:sha1")
    store.record("svc", "svc:sha2")

    assert store.get("svc") == "svc:sha2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/deploy_watcher/ -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.deploy_watcher'`

- [ ] **Step 3: Implement registry.py and known_good.py**

`services/deploy_watcher/__init__.py`: empty file.

`services/deploy_watcher/registry.py`:
```python
from __future__ import annotations

import json
import os
import threading


class ServiceRegistry:
    """File-backed stand-in for the MCP gateway's routing table.

    A real gateway would expose an API for this; until it exists, the
    Deploy Watcher writes the active container name per service here, and
    a future gateway integration reads from this same file.
    """

    def __init__(self, registry_path: str):
        self._path = registry_path
        self._lock = threading.Lock()
        if not os.path.exists(self._path):
            self._write({})

    def set_active_container(self, service_name: str, container_name: str) -> None:
        with self._lock:
            data = self._read()
            data[service_name] = container_name
            self._write(data)

    def get_active_container(self, service_name: str) -> str | None:
        with self._lock:
            return self._read().get(service_name)

    def _read(self) -> dict:
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: dict) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
```

`services/deploy_watcher/known_good.py`:
```python
from __future__ import annotations

import json
import os
import threading


class KnownGoodStore:
    """Tracks the last successfully-deployed image tag per service.

    Never overwritten except by a subsequent successful deploy, which is
    what guarantees the "known-good floor" from the design spec.
    """

    def __init__(self, store_path: str):
        self._path = store_path
        self._lock = threading.Lock()
        if not os.path.exists(self._path):
            self._write({})

    def record(self, service_name: str, image_tag: str) -> None:
        with self._lock:
            data = self._read()
            data[service_name] = image_tag
            self._write(data)

    def get(self, service_name: str) -> str | None:
        with self._lock:
            return self._read().get(service_name)

    def _read(self) -> dict:
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: dict) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/deploy_watcher/ -v`
Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/deploy_watcher/__init__.py services/deploy_watcher/registry.py services/deploy_watcher/known_good.py tests/deploy_watcher/__init__.py tests/deploy_watcher/test_registry.py tests/deploy_watcher/test_known_good.py
git commit -m "feat: add deploy-watcher service registry and known-good store"
```

---

## Task 7: Deploy Watcher image builder and health checker

**Files:**
- Create: `services/deploy_watcher/image_builder.py`
- Create: `services/deploy_watcher/health.py`
- Test: `tests/deploy_watcher/test_image_builder.py`
- Test: `tests/deploy_watcher/test_health.py`

**Interfaces:**
- Produces: `image_builder.build_image(docker_client, service_path: str, tag: str) -> str` (returns image id); `health.wait_for_healthy(url: str, required_successes: int = 3, interval_seconds: float = 2.0, timeout_seconds: float = 60.0) -> bool`.

- [ ] **Step 1: Write the failing test for image_builder, mocking the docker client**

`tests/deploy_watcher/test_image_builder.py`:
```python
from unittest.mock import MagicMock

from services.deploy_watcher.image_builder import build_image


def test_build_image_delegates_to_docker_client_and_returns_image_id():
    docker_client = MagicMock()
    mock_image = MagicMock(id="sha256:abc123")
    docker_client.images.build.return_value = (mock_image, iter([]))

    image_id = build_image(docker_client, "services/fixture_hello_mcp", "fixture-hello-mcp:abc123")

    assert image_id == "sha256:abc123"
    docker_client.images.build.assert_called_once_with(
        path="services/fixture_hello_mcp", tag="fixture-hello-mcp:abc123", rm=True
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/deploy_watcher/test_image_builder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement image_builder.py**

`services/deploy_watcher/image_builder.py`:
```python
from __future__ import annotations


def build_image(docker_client, service_path: str, tag: str) -> str:
    image, _logs = docker_client.images.build(path=service_path, tag=tag, rm=True)
    return image.id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/deploy_watcher/test_image_builder.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing tests for health.py, mocking requests**

`tests/deploy_watcher/test_health.py`:
```python
from unittest.mock import patch

import requests

from services.deploy_watcher.health import wait_for_healthy


class _FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


@patch("services.deploy_watcher.health.time.sleep", return_value=None)
@patch("services.deploy_watcher.health.requests.get")
def test_wait_for_healthy_returns_true_after_required_successes(mock_get, _mock_sleep):
    mock_get.return_value = _FakeResponse(200)

    result = wait_for_healthy("http://svc/health", required_successes=3, interval_seconds=0, timeout_seconds=5)

    assert result is True
    assert mock_get.call_count >= 3


@patch("services.deploy_watcher.health.time.sleep", return_value=None)
@patch("services.deploy_watcher.health.requests.get")
def test_wait_for_healthy_resets_streak_on_failure(mock_get, _mock_sleep):
    mock_get.side_effect = [
        _FakeResponse(200),
        _FakeResponse(500),
        _FakeResponse(200),
        _FakeResponse(200),
        _FakeResponse(200),
    ]

    result = wait_for_healthy("http://svc/health", required_successes=3, interval_seconds=0, timeout_seconds=5)

    assert result is True
    assert mock_get.call_count == 5


@patch("services.deploy_watcher.health.time.monotonic")
@patch("services.deploy_watcher.health.time.sleep", return_value=None)
@patch("services.deploy_watcher.health.requests.get")
def test_wait_for_healthy_times_out_and_returns_false(mock_get, _mock_sleep, mock_monotonic):
    mock_get.side_effect = requests.RequestException("connection refused")
    mock_monotonic.side_effect = [0, 1, 2, 100]

    result = wait_for_healthy("http://svc/health", required_successes=3, interval_seconds=0, timeout_seconds=5)

    assert result is False
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `pytest tests/deploy_watcher/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 7: Implement health.py**

`services/deploy_watcher/health.py`:
```python
from __future__ import annotations

import time

import requests


def wait_for_healthy(
    url: str,
    required_successes: int = 3,
    interval_seconds: float = 2.0,
    timeout_seconds: float = 60.0,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    consecutive = 0
    while time.monotonic() < deadline:
        if _check_once(url):
            consecutive += 1
            if consecutive >= required_successes:
                return True
        else:
            consecutive = 0
        time.sleep(interval_seconds)
    return False


def _check_once(url: str) -> bool:
    try:
        response = requests.get(url, timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/deploy_watcher/test_health.py -v`
Expected: all 3 tests PASS

- [ ] **Step 9: Commit**

```bash
git add services/deploy_watcher/image_builder.py services/deploy_watcher/health.py tests/deploy_watcher/test_image_builder.py tests/deploy_watcher/test_health.py
git commit -m "feat: add deploy-watcher image builder and health checker"
```

---

## Task 8: Deploy Watcher blue/green deploy manager

**Files:**
- Create: `services/deploy_watcher/deploy_manager.py`
- Test: `tests/deploy_watcher/test_deploy_manager.py`

**Interfaces:**
- Consumes: `build_image` (Task 7), `wait_for_healthy` (Task 7), `ServiceRegistry` (Task 6), `KnownGoodStore` (Task 6).
- Produces: `deploy_manager.DeployResult(success: bool, image_tag: str, reason: str = "")`, `deploy_manager.DeployManager(docker_client, registry, known_good, probation_seconds=1800.0)` with `.deploy(service_name, service_path, commit_sha, health_check_port=8080) -> DeployResult` and `.rollback(service_name) -> DeployResult`.

- [ ] **Step 1: Write the failing tests, mocking docker/health/time**

`tests/deploy_watcher/test_deploy_manager.py`:
```python
from unittest.mock import MagicMock, patch

from services.deploy_watcher.deploy_manager import DeployManager
from services.deploy_watcher.known_good import KnownGoodStore
from services.deploy_watcher.registry import ServiceRegistry


def _manager(tmp_path, docker_client, probation_seconds=1800.0):
    registry = ServiceRegistry(str(tmp_path / "registry.json"))
    known_good = KnownGoodStore(str(tmp_path / "known_good.json"))
    return DeployManager(docker_client, registry, known_good, probation_seconds=probation_seconds), registry, known_good


@patch("services.deploy_watcher.deploy_manager.threading.Thread")
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=True)
@patch("services.deploy_watcher.deploy_manager.build_image", return_value="sha256:new")
def test_deploy_promotes_new_container_on_healthy_check(mock_build, mock_wait, mock_thread, tmp_path):
    docker_client = MagicMock()
    manager, registry, known_good = _manager(tmp_path, docker_client)

    result = manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    assert result.success is True
    assert result.image_tag == "fixture-hello-mcp:abc123"
    assert registry.get_active_container("fixture-hello-mcp") == "fixture-hello-mcp-abc123"
    assert known_good.get("fixture-hello-mcp") == "fixture-hello-mcp:abc123"
    docker_client.containers.run.assert_called_once_with(
        "fixture-hello-mcp:abc123", detach=True, name="fixture-hello-mcp-abc123", network="mcp-fleet"
    )
    mock_thread.assert_called_once()


@patch("services.deploy_watcher.deploy_manager.threading.Thread")
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=False)
@patch("services.deploy_watcher.deploy_manager.build_image", return_value="sha256:new")
def test_deploy_kills_new_container_and_keeps_old_on_failed_health_check(mock_build, mock_wait, mock_thread, tmp_path):
    docker_client = MagicMock()
    new_container = MagicMock()
    docker_client.containers.run.return_value = new_container
    manager, registry, known_good = _manager(tmp_path, docker_client)
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-old")
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:old")

    result = manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    assert result.success is False
    assert result.reason == "failed initial health check"
    new_container.stop.assert_called_once()
    new_container.remove.assert_called_once()
    assert registry.get_active_container("fixture-hello-mcp") == "fixture-hello-mcp-old"
    assert known_good.get("fixture-hello-mcp") == "fixture-hello-mcp:old"
    mock_thread.assert_not_called()


@patch("services.deploy_watcher.deploy_manager.threading.Thread")
@patch("services.deploy_watcher.deploy_manager.wait_for_healthy", return_value=True)
@patch("services.deploy_watcher.deploy_manager.build_image", return_value="sha256:new")
def test_deploy_stops_old_container_after_promotion(mock_build, mock_wait, mock_thread, tmp_path):
    docker_client = MagicMock()
    old_container = MagicMock()
    docker_client.containers.get.return_value = old_container
    manager, registry, known_good = _manager(tmp_path, docker_client)
    registry.set_active_container("fixture-hello-mcp", "fixture-hello-mcp-old")

    manager.deploy("fixture-hello-mcp", "services/fixture_hello_mcp", "abc123")

    docker_client.containers.get.assert_called_once_with("fixture-hello-mcp-old")
    old_container.stop.assert_called_once()


def test_rollback_returns_failure_when_no_known_good_recorded(tmp_path):
    docker_client = MagicMock()
    manager, _registry, _known_good = _manager(tmp_path, docker_client)

    result = manager.rollback("never-deployed-service")

    assert result.success is False
    assert result.reason == "no known-good image on record"


def test_rollback_starts_known_good_image_and_updates_registry(tmp_path):
    docker_client = MagicMock()
    manager, registry, known_good = _manager(tmp_path, docker_client)
    known_good.record("fixture-hello-mcp", "fixture-hello-mcp:good-sha")

    result = manager.rollback("fixture-hello-mcp")

    assert result.success is True
    assert result.image_tag == "fixture-hello-mcp:good-sha"
    docker_client.containers.run.assert_called_once()
    args, kwargs = docker_client.containers.run.call_args
    assert args[0] == "fixture-hello-mcp:good-sha"
    assert kwargs["network"] == "mcp-fleet"
    assert registry.get_active_container("fixture-hello-mcp") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/deploy_watcher/test_deploy_manager.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement deploy_manager.py**

`services/deploy_watcher/deploy_manager.py`:
```python
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import docker.errors

from services.deploy_watcher.health import wait_for_healthy
from services.deploy_watcher.image_builder import build_image
from services.deploy_watcher.known_good import KnownGoodStore
from services.deploy_watcher.registry import ServiceRegistry


@dataclass
class DeployResult:
    success: bool
    image_tag: str
    reason: str = ""


class DeployManager:
    def __init__(
        self,
        docker_client,
        registry: ServiceRegistry,
        known_good: KnownGoodStore,
        probation_seconds: float = 1800.0,
    ):
        self._docker = docker_client
        self._registry = registry
        self._known_good = known_good
        self._probation_seconds = probation_seconds

    def deploy(self, service_name: str, service_path: str, commit_sha: str, health_check_port: int = 8080) -> DeployResult:
        image_tag = f"{service_name}:{commit_sha}"
        build_image(self._docker, service_path, image_tag)

        new_container_name = f"{service_name}-{commit_sha}"
        new_container = self._docker.containers.run(
            image_tag, detach=True, name=new_container_name, network="mcp-fleet"
        )
        health_check_url = f"http://{new_container_name}:{health_check_port}/health"

        if not wait_for_healthy(health_check_url):
            new_container.stop()
            new_container.remove()
            return DeployResult(success=False, image_tag=image_tag, reason="failed initial health check")

        old_container_name = self._registry.get_active_container(service_name)
        self._registry.set_active_container(service_name, new_container_name)
        self._known_good.record(service_name, image_tag)

        if old_container_name:
            try:
                self._docker.containers.get(old_container_name).stop()
            except docker.errors.NotFound:
                pass

        self._start_probation_monitor(service_name, new_container_name, health_check_port)
        return DeployResult(success=True, image_tag=image_tag)

    def rollback(self, service_name: str) -> DeployResult:
        good_tag = self._known_good.get(service_name)
        if good_tag is None:
            return DeployResult(success=False, image_tag="", reason="no known-good image on record")

        container_name = f"{service_name}-rollback-{int(time.time())}"
        self._docker.containers.run(good_tag, detach=True, name=container_name, network="mcp-fleet")
        self._registry.set_active_container(service_name, container_name)
        return DeployResult(success=True, image_tag=good_tag, reason="rolled back to known-good")

    def _start_probation_monitor(self, service_name: str, container_name: str, health_check_port: int) -> None:
        def monitor() -> None:
            health_check_url = f"http://{container_name}:{health_check_port}/health"
            deadline = time.monotonic() + self._probation_seconds
            while time.monotonic() < deadline:
                healthy = wait_for_healthy(
                    health_check_url, required_successes=1, interval_seconds=2.0, timeout_seconds=5.0
                )
                if not healthy:
                    self.rollback(service_name)
                    return
                time.sleep(10)

        threading.Thread(target=monitor, daemon=True).start()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/deploy_watcher/test_deploy_manager.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/deploy_watcher/deploy_manager.py tests/deploy_watcher/test_deploy_manager.py
git commit -m "feat: add deploy-watcher blue/green deploy manager"
```

---

## Task 9: Deploy Watcher GitHub poller and main loop

**Files:**
- Create: `services/deploy_watcher/github_poller.py`
- Create: `services/deploy_watcher/main.py`
- Test: `tests/deploy_watcher/test_github_poller.py`

**Interfaces:**
- Consumes: `FleetManifest` (Task 1), `DeployManager` (Task 8), `ServiceRegistry`/`KnownGoodStore` (Task 6).
- Produces: `github_poller.GitHubPoller(token, repo_full_name, branch="main")` with `.get_latest_commit_sha() -> str`, `.poll_once() -> str | None` (returns new sha only if it changed since the last call); `main.run() -> None` (the container entrypoint, not unit tested — exercised by the Task 11 integration test).

- [ ] **Step 1: Write the failing tests for github_poller, mocking PyGithub**

`tests/deploy_watcher/test_github_poller.py`:
```python
from unittest.mock import MagicMock, patch

from services.deploy_watcher.github_poller import GitHubPoller


@patch("services.deploy_watcher.github_poller.Github")
def test_get_latest_commit_sha_reads_branch_head(mock_github_cls):
    mock_repo = MagicMock()
    mock_repo.get_branch.return_value.commit.sha = "sha-1"
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    poller = GitHubPoller("token", "org/repo")

    assert poller.get_latest_commit_sha() == "sha-1"
    mock_repo.get_branch.assert_called_once_with("main")


@patch("services.deploy_watcher.github_poller.Github")
def test_poll_once_returns_sha_only_on_change(mock_github_cls):
    mock_repo = MagicMock()
    mock_repo.get_branch.return_value.commit.sha = "sha-1"
    mock_github_cls.return_value.get_repo.return_value = mock_repo

    poller = GitHubPoller("token", "org/repo")

    assert poller.poll_once() == "sha-1"
    assert poller.poll_once() is None

    mock_repo.get_branch.return_value.commit.sha = "sha-2"
    assert poller.poll_once() == "sha-2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/deploy_watcher/test_github_poller.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement github_poller.py and main.py**

`services/deploy_watcher/github_poller.py`:
```python
from __future__ import annotations

from github import Github


class GitHubPoller:
    def __init__(self, token: str, repo_full_name: str, branch: str = "main"):
        self._repo = Github(token).get_repo(repo_full_name)
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
```

`services/deploy_watcher/main.py`:
```python
from __future__ import annotations

import os
import time

import docker

from services.common.manifest import FleetManifest
from services.deploy_watcher.deploy_manager import DeployManager
from services.deploy_watcher.github_poller import GitHubPoller
from services.deploy_watcher.known_good import KnownGoodStore
from services.deploy_watcher.registry import ServiceRegistry


def run() -> None:
    # NOTE (scope simplification, see plan Global Constraints): this
    # redeploys every non-protected service on every new main commit
    # rather than diffing which service's files actually changed. Correct
    # but wasteful; per-service change detection is a follow-up.
    manifest = FleetManifest.load("fleet_manifest.yaml")
    docker_client = docker.from_env()
    registry = ServiceRegistry(os.environ.get("REGISTRY_PATH", "/data/service_registry.json"))
    known_good = KnownGoodStore(os.environ.get("KNOWN_GOOD_PATH", "/data/known_good.json"))
    manager = DeployManager(docker_client, registry, known_good)
    poller = GitHubPoller(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPO_FULL_NAME"])

    poll_interval = float(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
    while True:
        new_sha = poller.poll_once()
        if new_sha:
            for service in manifest.all_services():
                if service.protected:
                    continue
                manager.deploy(service.name, service.path, new_sha)
        time.sleep(poll_interval)


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/deploy_watcher/test_github_poller.py -v`
Expected: both tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/deploy_watcher/github_poller.py services/deploy_watcher/main.py tests/deploy_watcher/test_github_poller.py
git commit -m "feat: add deploy-watcher github poller and main loop"
```

---

## Task 10: Fixture service, Dockerfiles, and compose file

**Files:**
- Create: `services/fixture_hello_mcp/__init__.py`
- Create: `services/fixture_hello_mcp/server.py`
- Create: `services/fixture_hello_mcp/Dockerfile`
- Create: `services/self_dev_mcp/Dockerfile`
- Create: `services/deploy_watcher/Dockerfile`
- Create: `docker-compose.yml`
- Test: `tests/test_fixture_hello_mcp.py`

**Interfaces:**
- Produces: a Flask app in `services/fixture_hello_mcp/server.py` exposing `GET /health` (200 `{"status": "ok"}`) and `GET /` (200 `{"service": "fixture-hello-mcp"}`), used by Task 11's integration test as the thing that actually gets built/deployed/health-checked.

- [ ] **Step 1: Write the failing test for the fixture service**

`tests/test_fixture_hello_mcp.py`:
```python
from services.fixture_hello_mcp.server import app


def test_health_endpoint_returns_ok():
    client = app.test_client()

    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_index_endpoint_returns_service_name():
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert response.get_json() == {"service": "fixture-hello-mcp"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fixture_hello_mcp.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement the fixture service and Dockerfiles**

`services/fixture_hello_mcp/__init__.py`: empty file.

`services/fixture_hello_mcp/server.py`:
```python
from __future__ import annotations

from flask import Flask, jsonify

app = Flask(__name__)


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/")
def index():
    return jsonify({"service": "fixture-hello-mcp"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
```

`services/fixture_hello_mcp/Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir flask==3.0.3
COPY services/fixture_hello_mcp /app/services/fixture_hello_mcp
COPY services/common /app/services/common
ENV PYTHONPATH=/app
CMD ["python", "-m", "services.fixture_hello_mcp.server"]
```

`services/self_dev_mcp/Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services /app/services
COPY fleet_manifest.yaml /app/fleet_manifest.yaml
ENV PYTHONPATH=/app
CMD ["python", "-m", "services.self_dev_mcp.server"]
```

`services/deploy_watcher/Dockerfile`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services /app/services
COPY fleet_manifest.yaml /app/fleet_manifest.yaml
ENV PYTHONPATH=/app
CMD ["python", "-m", "services.deploy_watcher.main"]
```

`docker-compose.yml`:
```yaml
networks:
  mcp-fleet:
    name: mcp-fleet

volumes:
  watcher-data:

services:
  self-dev-mcp:
    build:
      context: .
      dockerfile: services/self_dev_mcp/Dockerfile
    networks:
      - mcp-fleet
    environment:
      SELF_DEV_REPO_REMOTE: ${SELF_DEV_REPO_REMOTE}
      GITHUB_TOKEN: ${GITHUB_TOKEN}
      GITHUB_REPO_FULL_NAME: ${GITHUB_REPO_FULL_NAME}
    # Deliberately no docker.sock mount and no deploy credentials here —
    # this service must never gain build/deploy authority.

  deploy-watcher:
    build:
      context: .
      dockerfile: services/deploy_watcher/Dockerfile
    networks:
      - mcp-fleet
    environment:
      GITHUB_TOKEN: ${GITHUB_TOKEN}
      GITHUB_REPO_FULL_NAME: ${GITHUB_REPO_FULL_NAME}
      REGISTRY_PATH: /data/service_registry.json
      KNOWN_GOOD_PATH: /data/known_good.json
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - watcher-data:/data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fixture_hello_mcp.py -v`
Expected: both tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/fixture_hello_mcp/ services/self_dev_mcp/Dockerfile services/deploy_watcher/Dockerfile docker-compose.yml tests/test_fixture_hello_mcp.py
git commit -m "feat: add fixture service, dockerfiles, and compose file"
```

---

## Task 11: End-to-end integration test

This proves Cycle A's git/protection mechanics against a real local git remote, and the Deploy Watcher's build/deploy/rollback mechanics against a real local Docker daemon. It does not hit live GitHub (no `open_pr`/`comment_on_issue` calls against a real API) — per the plan's Global Constraints, that is a manual acceptance step, not an automated test.

**Files:**
- Create: `tests/integration/__init__.py`
- Test: `tests/integration/test_self_dev_git_flow.py`
- Test: `tests/integration/test_deploy_manager_against_real_docker.py`

**Interfaces:**
- Consumes: everything from Tasks 1–10. No new production code in this task.

- [ ] **Step 1: Write the git-flow integration test**

`tests/integration/__init__.py`: empty file.

`tests/integration/test_self_dev_git_flow.py`:
```python
import subprocess

import pytest

from services.common.manifest import FleetManifest
from services.self_dev_mcp import git_ops
from services.self_dev_mcp.attempt_tracker import AttemptTracker
from services.self_dev_mcp.tools import ProtectedPathError, write_file


def _init_bare_remote_with_manifest(tmp_path, manifest_yaml: str) -> str:
    remote_dir = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote_dir)], check=True, capture_output=True)

    seed_dir = tmp_path / "seed"
    seed_dir.mkdir()
    subprocess.run(["git", "init"], cwd=seed_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "seed@example.com"], cwd=seed_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Seed"], cwd=seed_dir, check=True)
    (seed_dir / "fleet_manifest.yaml").write_text(manifest_yaml)
    (seed_dir / "services").mkdir()
    (seed_dir / "services" / "deploy_watcher").mkdir()
    (seed_dir / "services" / "deploy_watcher" / "deploy_manager.py").write_text("# real deploy watcher code")
    subprocess.run(["git", "add", "-A"], cwd=seed_dir, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=seed_dir, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=seed_dir, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote_dir)], cwd=seed_dir, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=seed_dir, check=True, capture_output=True)
    return str(remote_dir)


def test_full_cycle_a_git_mechanics_including_protected_path_refusal(tmp_path):
    manifest_yaml = (
        "services:\n"
        "  deploy-watcher:\n"
        "    path: services/deploy_watcher\n"
        "    protected: true\n"
    )
    remote_url = _init_bare_remote_with_manifest(tmp_path, manifest_yaml)
    manifest_path = tmp_path / "fleet_manifest.yaml"
    manifest_path.write_text(manifest_yaml)
    manifest = FleetManifest.load(str(manifest_path))
    tracker = AttemptTracker(max_attempts=5)

    workspace = tmp_path / "workspace"
    git_ops.clone(remote_url, str(workspace))
    git_ops.create_branch(str(workspace), "selfdev/issue-1")

    with pytest.raises(ProtectedPathError):
        write_file(
            str(workspace),
            "services/deploy_watcher/deploy_manager.py",
            "malicious change",
            manifest,
            "issue-1",
            tracker,
        )

    write_file(str(workspace), "services/fixture_hello_mcp/server.py", "# a real fix", manifest, "issue-1", tracker)
    sha = git_ops.commit_all(str(workspace), "fix: patch fixture service")
    git_ops.push(str(workspace), "selfdev/issue-1")

    verify_dir = tmp_path / "verify"
    git_ops.clone(remote_url, str(verify_dir))
    subprocess.run(["git", "checkout", "selfdev/issue-1"], cwd=verify_dir, check=True, capture_output=True)

    assert (verify_dir / "services" / "fixture_hello_mcp" / "server.py").read_text() == "# a real fix"
    assert (verify_dir / "services" / "deploy_watcher" / "deploy_manager.py").read_text() == "# real deploy watcher code"
    assert git_ops.current_commit_sha(str(verify_dir)) == sha
```

- [ ] **Step 2: Run test to verify it fails, then implement (it should already pass since it only composes Task 1-3 code)**

Run: `pytest tests/integration/test_self_dev_git_flow.py -v`
Expected: PASS immediately, since this test composes only already-implemented functions. If it fails, the failure indicates a real integration bug between Tasks 1–3 — fix the composing code before proceeding, do not change the test's assertions to match broken behavior.

- [ ] **Step 3: Write the deploy-manager-against-real-docker integration test**

`tests/integration/test_deploy_manager_against_real_docker.py`:
```python
import shutil
import time

import docker
import pytest

from services.deploy_watcher.deploy_manager import DeployManager
from services.deploy_watcher.known_good import KnownGoodStore
from services.deploy_watcher.registry import ServiceRegistry

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="Docker is not available in this environment")


@pytest.fixture
def docker_client():
    client = docker.from_env()
    yield client
    for container in client.containers.list(all=True, filters={"name": "it-fixture-hello-mcp"}):
        container.remove(force=True)


def _write_fixture_service(tmp_path, health_status_code: int) -> str:
    service_dir = tmp_path / "fixture_service"
    service_dir.mkdir()
    (service_dir / "server.py").write_text(
        "from flask import Flask, jsonify\n"
        "app = Flask(__name__)\n"
        f"STATUS = {health_status_code}\n"
        "@app.route('/health')\n"
        "def health():\n"
        "    return jsonify({'status': 'ok'}), STATUS\n"
        "if __name__ == '__main__':\n"
        "    app.run(host='0.0.0.0', port=8080)\n"
    )
    (service_dir / "Dockerfile").write_text(
        "FROM python:3.11-slim\n"
        "WORKDIR /app\n"
        "RUN pip install --no-cache-dir flask==3.0.3\n"
        "COPY server.py .\n"
        "CMD [\"python\", \"server.py\"]\n"
    )
    return str(service_dir)


def test_deploy_promotes_healthy_fixture_and_rollback_restores_it(tmp_path, docker_client):
    docker_client.networks.get("mcp-fleet") if _network_exists(docker_client) else docker_client.networks.create("mcp-fleet")
    registry = ServiceRegistry(str(tmp_path / "registry.json"))
    known_good = KnownGoodStore(str(tmp_path / "known_good.json"))
    manager = DeployManager(docker_client, registry, known_good, probation_seconds=5)

    good_service_path = _write_fixture_service(tmp_path, health_status_code=200)
    result_v1 = manager.deploy("it-fixture-hello-mcp", good_service_path, "v1")
    assert result_v1.success is True
    assert known_good.get("it-fixture-hello-mcp") == "it-fixture-hello-mcp:v1"

    broken_service_path = _write_fixture_service(tmp_path, health_status_code=500)
    result_v2 = manager.deploy("it-fixture-hello-mcp", broken_service_path, "v2")
    assert result_v2.success is False
    assert known_good.get("it-fixture-hello-mcp") == "it-fixture-hello-mcp:v1"

    rollback_result = manager.rollback("it-fixture-hello-mcp")
    assert rollback_result.success is True
    assert rollback_result.image_tag == "it-fixture-hello-mcp:v1"


def _network_exists(docker_client) -> bool:
    return any(n.name == "mcp-fleet" for n in docker_client.networks.list())
```

- [ ] **Step 4: Run the Docker integration test**

Run: `pytest tests/integration/test_deploy_manager_against_real_docker.py -v -s`
Expected: PASS if Docker is available locally; SKIPPED with a clear reason if not. If it fails with a real Docker daemon available, this indicates a genuine bug in `deploy_manager.py` — investigate and fix rather than loosening the test.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/
git commit -m "test: add end-to-end integration tests for self-dev git flow and blue/green deploy"
```

---

## Task 12: GitHub repository configuration (CODEOWNERS, branch protection, CI)

Unlike the previous tasks, the branch-protection step here changes settings on a shared GitHub repository, not just files in this working tree — run it yourself (or have whoever owns the GitHub org run it) rather than letting an agent execute it unattended, and confirm the org/repo name before running.

**Files:**
- Create: `.github/CODEOWNERS`
- Create: `.github/workflows/test.yml`

**Interfaces:** none — this task produces GitHub configuration, not importable code.

- [ ] **Step 1: Add CODEOWNERS for the protected core**

`.github/CODEOWNERS`:
```
/fleet_manifest.yaml             @YOUR_GITHUB_ORG/platform-admins
/services/common/manifest.py     @YOUR_GITHUB_ORG/platform-admins
/services/deploy_watcher/        @YOUR_GITHUB_ORG/platform-admins
/services/permission_manager/    @YOUR_GITHUB_ORG/platform-admins
/services/mcp_gateway/           @YOUR_GITHUB_ORG/platform-admins
```

Replace `YOUR_GITHUB_ORG/platform-admins` with the real GitHub team that should own these approvals before committing.

- [ ] **Step 2: Add the CI workflow that branch protection will require**

`.github/workflows/test.yml`:
```yaml
name: test

on:
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: pytest tests/ -v --ignore=tests/integration
```

(The Docker-dependent integration tests in `tests/integration/` are intentionally excluded from this workflow; running them in CI needs a Docker-enabled runner and is a follow-up, not required for this plan's deliverable.)

- [ ] **Step 3: Commit the CODEOWNERS and workflow files**

```bash
git add .github/CODEOWNERS .github/workflows/test.yml
git commit -m "chore: add CODEOWNERS and CI workflow for protected core"
```

- [ ] **Step 4: Push this branch and configure branch protection manually (requires GitHub org-admin permissions — confirm the repo slug with the repo owner before running)**

```bash
git push -u origin main
gh api repos/YOUR_GITHUB_ORG/GENERALIST_MCP/branches/main/protection \
  --method PUT \
  --field required_status_checks='{"strict":true,"contexts":["test"]}' \
  --field enforce_admins=true \
  --field required_pull_request_reviews='{"required_approving_review_count":1,"require_code_owner_reviews":true}' \
  --field restrictions=null
```

- [ ] **Step 5: Manual acceptance check (per spec — not automated)**

Before trusting this system with a real fleet member: run one real self-heal cycle by hand — deliberately deploy a broken fixture image via `DeployManager.deploy`, confirm the health check fails and the old container is untouched, then manually trigger `DeployManager.rollback` and confirm service is restored. This was already exercised in Task 11's Docker integration test; this step is the sign-off that the same behavior holds against your actual GitHub repo and org permissions, not just the local test fixture.

---

## Self-Review Notes

- **Spec coverage:** protected core (Task 1, 3), blue/green + health checks (Task 7, 8), known-good floor (Task 6, 8), probation rollback (Task 8), attempt cap (Task 3), GitHub issue/PR flow primitives (Task 4, 5, 9), human-required merge gate (Task 12, enforced outside this codebase by GitHub itself as the spec requires). Self-extending capability tier is explicitly out of scope for this plan, as stated in the Goal section.
- **Deferred/simplified (called out inline, not silently dropped):** per-service change detection on deploy (Task 9 redeploys all non-protected services per commit), image pruning/retention (no code deletes images yet, so the known-good floor holds trivially), and live-GitHub PR/issue round-tripping in automated tests (covered by mocks in Tasks 4/5/9, and by a manual acceptance step in Task 12 instead of an automated test against live GitHub).
- **Type/name consistency checked:** `FleetManifest`, `ServiceConfig`, `AttemptTracker`, `AttemptsExhaustedError`, `ProtectedPathError`, `ServiceRegistry`, `KnownGoodStore`, `DeployManager`, `DeployResult`, and `GitHubClient` are each defined once and referenced with identical names/signatures in every later task that consumes them.
