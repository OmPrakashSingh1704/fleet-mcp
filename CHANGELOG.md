# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(pre-1.0: the public API and configuration surface may still change between
minor versions).

## [Unreleased]

### Added

- Product documentation set: README, SECURITY, CONTRIBUTING, CODE_OF_CONDUCT,
  ARCHITECTURE, SUPPORT, GOVERNANCE, and GitHub issue/PR templates.
- Apache License 2.0 `LICENSE` and `NOTICE` files.
- Project logo (`assets/logo.svg`, `assets/logo-mark.svg`, and
  `assets/logo-dark.svg` for a dark-mode variant, switched via a README
  `<picture>` element based on `prefers-color-scheme`).
- Project metadata in `pyproject.toml` (package name `fleet-mcp`,
  description, license, readme).
- `services/fixture_hello_mcp/`: a minimal Flask service (`GET /health`,
  `GET /`) used as the Deploy Watcher's local build/run/health-check smoke
  test target.
- Per-service Dockerfiles (`services/fixture_hello_mcp/Dockerfile`,
  `services/self_dev_mcp/Dockerfile`, `services/deploy_watcher/Dockerfile`),
  `docker-compose.yml` (the `mcp-fleet` network plus all three services),
  and a committed `.env.example` template for the secrets `docker-compose.yml`
  reads via `${VAR}` interpolation from a gitignored `.env`.
- Self-Dev MCP `--transport {stdio,http}` (default `stdio`): `http` serves
  the server over SSE (`/sse`, `/messages/`) plus `GET /health` on port
  8080, so its container can be health-checked.
- `services/deploy_watcher/entrypoint.sh`: a runtime entrypoint that starts
  the watcher container as root, joins its non-root `watcher` user to
  whatever group actually owns the host's `/var/run/docker.sock` (its GID
  varies by host and isn't known at image build time), and then drops to
  `watcher` via `setpriv` before running the real command.
- `services/self_dev_mcp/github_client.py`: `GitHubClient` now resolves the
  GitHub repo lazily, on first use, instead of in `__init__` — a bad or
  unreachable `GITHUB_TOKEN` no longer crashes the process at startup
  (previously this made Self-Dev MCP's HTTP server fail to bind before
  `/health` could ever respond); it now surfaces as an `"ERROR: ..."` string
  from the first tool call that needs GitHub.
- `.github/CODEOWNERS`, covering the protected core
  (`fleet_manifest.yaml`, `services/common/manifest.py`,
  `services/deploy_watcher/`, the planned `services/permission_manager/`
  and `services/mcp_gateway/` directories, `/.github/`, and `SECURITY.md`)
  with a placeholder `@OWNER` — GitHub will flag these entries as invalid,
  and code-owner review cannot be enforced, until `@OWNER` is replaced.
- `.github/workflows/test.yml`: the CI workflow (job id `test`, so the
  required-check context is `test`), running on `pull_request` and `push`
  to `main` with least-privilege `contents: read` permissions and a
  concurrency group that cancels a superseded run on the same ref. A
  second, non-required `docker-integration` job runs the Docker-marked
  integration suite on GitHub's Docker-capable `ubuntu-latest` runners.
- Branch-protection documentation: a
  [CONTRIBUTING.md#enabling-branch-protection](CONTRIBUTING.md#enabling-branch-protection)
  section with the exact `gh api` command a repo admin runs to require the
  `test` status check and code-owner review on `main`, plus updates across
  README, SECURITY.md, CONTRIBUTING.md, GOVERNANCE.md, and ARCHITECTURE.md
  clarifying that the workflow and CODEOWNERS file now exist but
  enforcement still requires the admin to enable branch protection.
- `run_tests` timeout: `SELF_DEV_TEST_TIMEOUT_SECONDS` (default 600). A run
  that exceeds it returns `"ERROR: tests timed out after Ns"`.
- Policy-denial audit log: every `REFUSED`/`EXHAUSTED` decision in
  `write_file`, `read_file` and `run_tests` is logged at WARNING on the
  `fleet_mcp.audit` logger (stderr) as
  `policy-denial tool=… issue=… path=<repr> reason=…`. Content is never
  logged.
- `restart: unless-stopped` on every compose service.

### Security

- **Critical: `.git/` was readable and writable through the tools.**
  `write_file('.git/config', …)` could plant a `remote.origin.push` refmap
  that made `submit_pr` force-push the agent's branch onto `main`, and
  `.git/hooks/*` / `core.fsmonitor` gave code execution. `read_file`,
  `write_file` and `run_tests` now refuse any path with a `.git` component
  (case-insensitive, Windows-canonicalized, checked on both the typed and
  the resolved path).
- Every self-dev git call now runs with `core.hooksPath=<empty dir>` and
  `core.fsmonitor=false`, and `push` uses the explicit, non-forcing refspec
  `refs/heads/selfdev/issue-N:refs/heads/selfdev/issue-N`. A tampered
  `.git/config` can no longer move `main` or run a hook.
- Symlink/junction bypass closed: `write_file` re-checks the manifest
  against the symlink-resolved target, so `innocent -> services/deploy_watcher`
  can't be used to write a protected file.
- Protected core expanded: `ALWAYS_PROTECTED_PATHS` adds
  `services/__init__.py`, `requirements.txt`, `docker-compose.yml`,
  `pyproject.toml`, `.gitattributes` and `.gitignore`. A new
  `ALWAYS_PROTECTED_PREFIXES` protects `services/common/` and `.github/`.
  Path canonicalization also strips NTFS stream suffixes and trailing
  dots/spaces. CODEOWNERS mirrors the list, and a test enforces that.
- Git authentication for private repos goes through a credential helper
  that reads the token from the environment at call time. The token never
  appears in argv, a URL, `.git/config` or logs. `GitOpsError` and
  `CheckoutError` redact the remote URL, any URL userinfo and the token
  value. `GIT_TERMINAL_PROMPT=0` is set for every git call.
- `run_tests` refuses paths starting with `-` and passes the path after
  `--`, so it can't smuggle pytest options such as `--basetemp`. Tokens are
  stripped from the test subprocess environment (hygiene only; see
  SECURITY.md).
- The Self-Dev MCP image keeps its app source root-owned and read-only to
  the `selfdev` user. Only `/app/tmp` is writable. The fixture image now
  runs as a non-root user.
- Security docs rewritten to be honest about the model. The tool checks
  bind a *cooperative* agent. `run_tests` runs agent code with the self-dev
  token, and that code can write protected files that `submit_pr` commits
  and can call the GitHub API directly. Branch protection plus a separate
  bot identity is now a stated **precondition** before pointing a live
  agent at a repo. Also documented: branch protection on a private repo
  needs a paid GitHub plan.

### Changed

- **Breaking (env rename, token split):** the shared `GITHUB_TOKEN` is
  gone. Self-Dev MCP reads `SELF_DEV_GITHUB_TOKEN` (fine-grained: contents,
  pull requests and issues read/write) for both the GitHub API and git. The
  Deploy Watcher reads `WATCHER_GITHUB_TOKEN` (contents read-only) for
  polling and checkout. Update your `.env` (see `.env.example`).
- `run_tests` output is now `"OK (exit 0)\n<output>"` or
  `"FAILED (exit N)\n<output>"`.
- MCP tools are `async` and run their handlers in a worker thread, so a
  long `run_tests` no longer blocks the event loop or `/health`.
- `self-dev-mcp` is compose-managed only for this release. Its manifest
  entry no longer has `container`/`health_check`, so the Deploy Watcher
  skips it. Update it with `docker compose up --build self-dev-mcp`.
- The manifest `health_check` field is documented as informational. The
  watcher always probes `http://<service>-<sha>:8080/health`.
- `anyio` is pinned (`4.12.1`) as a direct dependency. Newer anyio releases
  break Starlette's `TestClient` under `-W error::DeprecationWarning`.
- `asyncio_default_fixture_loop_scope` removed from `pyproject.toml`
  (pytest-asyncio is not a dependency). The smoke test that relied on it
  was silently skipped; it now runs via `asyncio.run`, and CI adds
  `-W error::pytest.PytestUnhandledCoroutineWarning`.
- Root `.gitignore` now also covers `.superpowers/`, virtualenvs, caches,
  build output and editor folders.

### Fixed

- The deploy manager takes a per-service lock around the registry flip,
  rollback's check-and-perform, and probation's known-good promotion, so a
  probation rollback can't interleave with a newer deploy.
- Tool handlers never raise on `OSError`, `UnicodeDecodeError` or
  `requests.RequestException`; they return `"ERROR: …"`.
- Concurrent `start_issue` calls for the same issue clone only once.
- `create_workspace` removes its temp directory if the clone fails.

## [0.1.0] - 2026-09-19

Foundation release: the protected-core enforcement engine, the Self-Dev MCP
server, and the Deploy Watcher's blue/green deploy and rollback machinery,
proven end to end in the test suite. This covers the self-healing and
self-patching capability tiers described in the design spec; self-extending
(scaffolding brand-new MCP servers) is not yet built.

### Added

- `services/common/manifest.py`: `FleetManifest`, the fleet manifest loader
  and protected-path engine. `fleet_manifest.yaml` and the manifest loader
  itself are protected unconditionally, independent of manifest content.
  Path checks canonicalize separators, resolve `..` segments, and
  case-fold; a path that escapes the repo root after normalization is
  always treated as protected.
- `services/self_dev_mcp/`: the Self-Dev MCP server (FastMCP), exposing
  `start_issue`, `read_file`, `write_file`, `run_tests`, `submit_pr`,
  `list_assigned_issues`, and `check_pr_status`.
  - Writes and reads are confined to an ephemeral per-issue workspace;
    absolute paths, drive-letter paths, UNC paths, and `..` escapes are
    refused before anything touches disk.
  - A per-issue attempt cap (default 5) is enforced atomically; a refused
    write never consumes an attempt.
  - Handlers never raise to their caller — they return `OK`, `REFUSED`,
    `EXHAUSTED`, or `ERROR` strings.
  - `start_issue` resumes an existing `selfdev/issue-N` remote branch when
    one exists, so follow-up commits land on the same PR; there is no
    force-push anywhere in the pipeline. `open_pr` is idempotent. CI status
    is read from the GitHub Checks API. Issue listings exclude pull
    requests.
  - No Docker socket access, no deploy credentials, no ability to merge a
    pull request.
- `services/deploy_watcher/`: the Deploy Watcher.
  - Polls `main` for new commits, syncs a git checkout of the new commit
    (redacting the remote URL, which may embed a token, from any error),
    and builds each non-protected service's image from that checkout
    (repo-root build context, per-service Dockerfile).
  - Blue/green deploy: 3 consecutive health-check successes before
    promotion, followed by a post-promotion probation window (default 30
    minutes); a single failed check during probation triggers automatic
    rollback.
  - Known-good is recorded only after a deploy survives probation in full;
    rollback always targets the last proven image, and does nothing (rather
    than stopping the live container) if no proven image exists yet. A
    retired commit sha is never redeployed.
  - Service registry and known-good state are persisted as JSON, written
    atomically (temp file + `os.replace`) so a crash mid-write can't leave
    a corrupt state file.
  - `deploy()` and the probation monitor never raise on a Docker error —
    failures are recorded as a failed `DeployResult` or logged and treated
    as a failed probation check.
- `fleet_manifest.yaml`: the real fleet manifest for this repo. Marks
  `deploy-watcher`, `permission-manager`, and `mcp-gateway` as
  `protected: true`.
- 125 tests covering the manifest/protection engine, Self-Dev MCP's git
  ops/workspace/tools/attempt-tracker/GitHub client/server wiring, and the
  Deploy Watcher's registry, known-good store, image builder, health
  checker, checkout, GitHub poller, deploy manager, and main loop —
  including adversarial tests for protected-path writes and probation
  rollback.

### Known gaps (tracked, not regressions)

See [SECURITY.md](SECURITY.md#known-limitations) and the
[README roadmap](README.md#status--roadmap): MCP gateway, permission
manager, model-adapters-mcp, credentials-manager, and the Model Manager
chat flow are not built yet; Docker Compose/Dockerfiles and CI/CODEOWNERS
are in progress.

[Unreleased]: https://github.com/OmPrakashSingh1704/fleet-mcp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/OmPrakashSingh1704/fleet-mcp/releases/tag/v0.1.0
