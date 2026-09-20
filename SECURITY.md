# Security Policy

Flotilla MCP grants an autonomous agent the ability to edit source code, open
pull requests, and (indirectly, after human merge) trigger a production
deploy of a fleet of services. This document describes what we guarantee,
what we assume, how to report a problem, and what we know is still weak.

## Supported versions

Flotilla MCP is pre-1.0. Only the latest `0.x` release receives security fixes.
There is no long-term support branch yet; if you're running an older `0.x`
version, upgrade before relying on it.

| Version | Supported |
|---|---|
| Latest `0.x` | Yes |
| Older `0.x` | No |

## Preconditions before pointing a live agent at a repo

Do **not** connect a live agent to Self-Dev MCP for a repository until
**both** of these are true:

1. **Branch protection is enabled on `main`**: the required `test` status
   check, at least one required approving review, required code-owner
   review (`.github/CODEOWNERS` already names a real owner,
   `@OmPrakashSingh1704`), and
   `enforce_admins`. See
   [CONTRIBUTING.md#enabling-branch-protection](CONTRIBUTING.md#enabling-branch-protection).
   Branch protection on a **private** repository requires a paid GitHub
   plan (Pro, Team or Enterprise). On GitHub Free it is only available for
   public repositories.
2. **Self-Dev MCP runs as a separate bot identity**, meaning a machine user
   or a GitHub App, not the repo owner's personal access token. If
   `SELF_DEV_GITHUB_TOKEN` is the owner's own PAT, every self-dev PR is
   authored by the owner. A sole owner cannot approve their own PR, so with
   `enforce_admins` on, those PRs can never be merged. Owners are then
   tempted to switch protection off, which removes the only real backstop.

For this repository (`OmPrakashSingh1704/flotilla-mcp`, private, on GitHub
Pro) the supported sequence is: the owner merges the foundation branch;
CODEOWNERS already names `@OmPrakashSingh1704` as owner, so right after that
merge full branch
protection is applied (required `test` check, 1 approving review,
code-owner review, dismiss stale reviews, `enforce_admins`, no force-push,
no deletions); from then on self-dev runs as a separate bot identity so the
owner can approve its PRs. See
[CONTRIBUTING.md#enabling-branch-protection](CONTRIBUTING.md#enabling-branch-protection).

These are preconditions because the tool-level checks described below bind
a *cooperative* agent only (see [Guarantees](#guarantees) and
[Known limitations](#known-limitations)). Against an agent that turns
hostile, branch protection plus a separate, narrowly scoped bot identity is
what keeps a change from reaching `main` without a human.

## Reporting a vulnerability

**Do not open a public issue for a security report.**

Report privately using GitHub's private security advisories: go to this
repository's **Security** tab and select **Report a vulnerability**. That
creates a private advisory visible only to you and the maintainers, and lets
us collaborate on a fix (including a draft patch) before anything is
public. We do not publish a separate contact email for security reports —
GitHub private advisories are the only supported channel.

Please include:

- What you found and why it matters (which guarantee in the
  [Security model](#security-model) below does it break, or what new one
  should exist)
- Steps to reproduce, or a minimal PoC — a failing test against this
  codebase is ideal (e.g. "this write should have been refused and wasn't")
- The affected version/commit
- Your assessment of impact: can it write a protected path, escape the
  workspace, exhaust the attempt cap without effect, bypass health checks,
  or otherwise weaken a guarantee this document makes

### Response targets

- **Acknowledgement:** within 3 business days of the report.
- **Triage** (confirmed/not confirmed, initial severity): within 10 business
  days.
- We'll keep you updated on progress toward a fix inside the private
  advisory thread. Timelines for a fix depend on severity and complexity;
  we'll tell you what to expect once triage is done.

### Coordinated disclosure

We ask that you give us the chance to ship a fix (or a documented
mitigation) before any public disclosure. Once a fix is released, we'll
work with you on a disclosure timeline and, if you'd like, credit you in the
advisory and the changelog. If we go quiet for longer than the targets
above, it's fair to follow up in the same thread — that's not us asking you
to wait indefinitely.

## Scope

**In scope:**

- Any way to make `Self-Dev MCP`'s `write_file`/`read_file` touch a path
  outside its ephemeral workspace, or a path the fleet manifest (or the
  hardcoded protected paths) marks off-limits — including via `..`,
  absolute paths, drive letters, UNC paths, symlinks, case tricks, or
  encoding tricks.
- Any way for the Self-Dev MCP to gain Docker socket access, deploy
  credentials, or the ability to merge its own pull request.
- Any way for the Deploy Watcher to promote a build to "known-good" without
  a full, uninterrupted probation window, or to roll back onto an
  unproven/retired image.
- Any way to bypass or disable the per-issue attempt cap.
- Any way to read or write `.git/` through the Self-Dev MCP tools, or to
  make a self-dev `git` invocation run a hook, an fsmonitor command, or push
  to a ref other than `refs/heads/selfdev/issue-N`.
- Secrets (tokens, keys) leaking into logs, error messages, argv, committed
  files, `.git/config`, or built images. Both services' git errors are
  deliberately redacted (remote URL, URL userinfo, token value). A
  regression there is in scope.
- Denial of service against the Deploy Watcher's poll loop or a fleet
  service's health endpoint that an attacker could trigger without
  privileged access.

**Out of scope:**

- The MCP gateway, permission manager, model-adapters-mcp, and
  credentials-manager — these are not implemented yet (see the [README
  roadmap](README.md#status--roadmap)); there is nothing to audit.
- Vulnerabilities that require GitHub organization/repo admin access to
  exploit (e.g. "an admin could disable branch protection") — that's a
  process control, not a code control, and is covered by the [hardening
  checklist](#hardening-checklist-for-operators) below, not by a patch.
- Findings that only apply to a deployment that ignores this document's
  hardening checklist (e.g. running the Deploy Watcher without a scoped
  Docker context, or without CODEOWNERS configured).
- Generic dependency CVEs with no demonstrated exploit path against Fleet
  MCP's actual usage of that dependency — please still report these, but
  they're handled as routine maintenance rather than under disclosure
  timelines.

## Security model

### Guarantees

**Read this first: what the tool-level checks bind.** The file-tool
guarantees below (protected core, `.git` blocking, workspace containment,
attempt cap) apply to the `write_file` / `read_file` / `run_tests` tool
calls. They bind a *cooperative* agent, one that edits the repo only through
those tools. They do **not** bind code the agent writes and then executes
through `run_tests`. That code runs with the self-dev token, can write any
file in the workspace (including protected paths and `.git/`), and
`submit_pr` then commits all of it with `git add -A`. It can also call the
GitHub API directly. See [Known limitations](#known-limitations). The real
backstop against a hostile agent is GitHub-side: branch protection
(required `test` check, required review, code-owner review,
`enforce_admins`) plus a **separate bot identity** for self-dev. Both are
[preconditions](#preconditions-before-pointing-a-live-agent-at-a-repo).

- **Protected core.** Hardcoded in `flotilla_mcp/common/manifest.py`,
  independent of manifest content:
  - `ALWAYS_PROTECTED_PATHS` (exact files): `fleet_manifest.yaml`,
    `flotilla_mcp/common/manifest.py`, `flotilla_mcp/__init__.py`,
    `requirements.txt`, `requirements-dev.txt`, `docker-compose.yml`,
    `pyproject.toml`, `.gitattributes`, `.gitignore`.
  - `ALWAYS_PROTECTED_PREFIXES` (whole subtrees): `flotilla_mcp/common/`,
    `.github/`.

  Services marked `protected: true` (`deploy-watcher`, `permission-manager`
  (planned), `mcp-gateway` (planned)) are unwritable by `write_file` across
  their entire path prefix. Every comparison canonicalizes both sides the
  same way: `\` becomes `/`, `.`/`..` segments and duplicate slashes are
  collapsed, NTFS stream suffixes (`::$DATA`) and trailing dots/spaces are
  stripped, and the result is case-folded. Any path that still resolves
  outside the repo root is treated as protected. `.github/CODEOWNERS`
  mirrors this list (a test enforces that).
- **Symlink- and junction-aware.** `write_file` checks the path as typed
  *and* the real target after resolving symlinks/junctions (relative to the
  resolved workspace root). A link such as `innocent -> flotilla_mcp/deploy_watcher`
  cannot be used to write a protected file.
- **`.git/` is off-limits to the tools.** `read_file`, `write_file` and
  `run_tests` refuse any path with a `.git` component (case-insensitive,
  Windows-canonicalized, checked on the typed path and on the resolved
  target). This covers `.GIT/config`, `sub/../.git/config` and
  `./.git/x`.
- **Hardened git invocations.** Every self-dev `git` call runs with
  `core.hooksPath` set to an empty directory (no hook ever runs),
  `core.fsmonitor=false`, inherited credential helpers cleared, and
  `GIT_TERMINAL_PROMPT=0`. `submit_pr` pushes with a fully explicit,
  non-forcing refspec (`refs/heads/selfdev/issue-N:refs/heads/selfdev/issue-N`),
  so a `remote.origin.push` setting cannot redirect the push onto `main`.
- **Workspace containment.** Every `write_file`/`read_file`/`run_tests` call
  resolves the target against the issue's ephemeral workspace directory
  (`os.path.realpath`) and refuses absolute paths, drive letters, UNC paths,
  and any resolved path outside that workspace root, before anything
  touches disk. `run_tests` also refuses a path starting with `-`, passes it
  to pytest after `--`, and enforces a timeout
  (`SELF_DEV_TEST_TIMEOUT_SECONDS`, default 600).
- **No merge code path.** Nothing in this codebase calls a merge API, and
  there is no force-push. `open_pr` is idempotent (re-submitting returns the
  existing open PR). This is *not* the same as "the agent cannot merge": the
  self-dev token has contents and pull-request write access, and agent code
  run through `run_tests` can call the GitHub API with it. Merge-only-by-a-human
  is enforced by branch protection, which the repo admin enables. See
  [CONTRIBUTING.md#enabling-branch-protection](CONTRIBUTING.md#enabling-branch-protection).
- **No deploy authority in Self-Dev MCP.** The Self-Dev MCP process holds no
  Docker socket access, no deploy credentials and no watcher token, and does
  not import `docker`. Only the Deploy Watcher can build an image, start a
  container, or flip the service registry.
- **Separate, minimal tokens.** `SELF_DEV_GITHUB_TOKEN` (self-dev: contents
  read/write, pull requests read/write, issues read/write, on this repo only)
  and `WATCHER_GITHUB_TOKEN` (watcher: contents read-only) are separate
  variables delivered only to their own container.
- **Tokens stay out of argv, URLs, config and logs.** Both services
  authenticate git through a credential helper that reads the token from
  the environment at call time
  (`!f() { echo username=x-access-token; echo "password=$SELF_DEV_GITHUB_TOKEN"; }; f`,
  and the watcher equivalent). The token value never appears in a process
  argument, a remote URL or `.git/config`. `GitOpsError` and
  `CheckoutError` messages have the remote URL, any `user:pass@` URL
  userinfo, and the token value redacted. No component writes credentials
  to a tracked file.
- **Policy-denial audit log.** Every `REFUSED` / `EXHAUSTED` decision in
  `write_file`, `read_file` and `run_tests` is logged at WARNING on the
  `flotilla_mcp.audit` logger (stderr) as
  `policy-denial tool=… issue=… path=<repr> reason=…`. File content is never
  logged.
- **Known-good floor.** An image is recorded as known-good only after it
  survives a full probation window (default 30 minutes) with zero failed
  checks. Rollback always targets the last *proven* image; if none exists
  yet, rollback is a no-op rather than stopping the only running container.
- **Attempt cap.** `write_file` calls for a given issue are capped (default
  5). The cap check and the increment are atomic, and a refused write
  (protected path, `.git`, workspace escape) never consumes an attempt. Only
  writes that actually reach disk count against the cap. Files written by
  code running under `run_tests` are not counted.
- **Retired shas are never redeployed.** If a container for a given commit
  sha already exists but isn't active (it was previously promoted, then
  rolled back or superseded), the Deploy Watcher refuses to redeploy it
  rather than silently reviving a bad build.

### Assumptions

- The [preconditions](#preconditions-before-pointing-a-live-agent-at-a-repo)
  hold: branch protection (required `test` check, required review,
  code-owner review, `enforce_admins`) is enabled on `main`, and
  `SELF_DEV_GITHUB_TOKEN` belongs to a separate bot identity, scoped as
  fine-grained contents/pull-requests/issues read-write on this one repo.
  This codebase enforces the tool-level and workspace-level controls above;
  it cannot enforce GitHub-side branch protection for you, and those
  controls do not stop a hostile agent on their own.
- The Docker daemon the Deploy Watcher talks to is not shared with anything
  the Self-Dev MCP (or an attacker who compromises it) can reach. If
  Self-Dev MCP's container can reach the Deploy Watcher's Docker socket by
  some other path (a misconfigured volume mount, a shared network
  namespace), every guarantee above is void — "no Docker access" is a
  property of how you deploy these two services, not just of the Self-Dev
  MCP's own source code.
- The machine running the Deploy Watcher is otherwise trusted. Flotilla MCP
  defends against a misbehaving or successfully-prompt-injected *agent*; it
  is not a sandbox against a host-level attacker who can already run
  arbitrary code on the Deploy Watcher's host.

## Known limitations

These are documented, accepted gaps, not secrets — treat them as inputs to
your own risk assessment, not as an invitation to assume they're fixed:

- **The always-protected paths describe Flotilla MCP's own repository, not
  whatever repository Self-Dev MCP is pointed at.** `ALWAYS_PROTECTED_PATHS`
  and `ALWAYS_PROTECTED_PREFIXES` in `flotilla_mcp/common/manifest.py` are a
  fixed list of paths from *this* repository's own layout
  (`flotilla_mcp/__init__.py`, `flotilla_mcp/common/`, and so on). When Self-Dev MCP
  is configured against a different repository (a different
  `SELF_DEV_REPO_REMOTE`/`GITHUB_REPO_FULL_NAME`), the `flotilla_mcp/...`
  entries are inert there — that target repo has no `flotilla_mcp/` directory
  for them to match — while the repository-shape-independent entries
  (`.git`, `.github/`, `requirements*.txt`, `docker-compose.yml`,
  `pyproject.toml`, `.gitattributes`, `.gitignore`, and anything the
  *target* repo's own `fleet_manifest.yaml` marks `protected`) still apply.
  Per-repository protected-path configuration (so the hardcoded list can
  describe the target repo's own layout, not this one's) is roadmap, not
  built yet.
- **Running without a fleet manifest leaves only the built-in protections.**
  If `FLEET_MANIFEST_PATH` is unset and no `fleet_manifest.yaml` is found (in
  the current directory or the git repo root), Self-Dev MCP starts with an
  empty manifest instead of failing. `ALWAYS_PROTECTED_PATHS` and
  `ALWAYS_PROTECTED_PREFIXES` (and the `.git`/absolute-path/`..`-escape
  checks, which don't depend on the manifest at all) still apply, but no
  service is `protected: true` and no `protected_paths` exist — nothing in
  the target repo beyond the hardcoded list is service-protected until a
  manifest is added. The server logs one WARNING naming the paths it
  checked when this happens; that warning is the signal to look for.
- **Probation doesn't survive a watcher restart.** The probation monitor is
  an in-process thread. If the Deploy Watcher process restarts mid-probation,
  the newly-promoted container keeps serving traffic but is no longer being
  watched for a probation failure, and it will not be recorded as
  known-good until the next successful deploy.
- **Rollback containers are not health-monitored.** Once `rollback()` starts
  the known-good image, nothing continues to poll its health. If the
  known-good image itself has since developed a problem (e.g. an expired
  external dependency), a rollback will not detect that.
- **Stopped containers are not pruned.** The watcher stops old containers on
  promotion and rollback but does not remove them or their images. Disk
  usage grows over time; operators need their own cleanup job until a
  retention/pruning job is built.
- **A checkout failure skips that sha until the next commit.** If
  `sync_checkout` fails for a given commit (network blip, bad ref), the
  watcher does not retry that sha — it will only be picked up again if the
  poller sees a newer commit. A single-commit outage on your git host can
  cause one deploy cycle to be silently skipped.
- **`run_tests` executes agent-written code, which the tool checks do not
  bind.** `run_tests` runs `pytest` inside the Self-Dev MCP container on
  whatever the agent just wrote, including any `conftest.py`. That is
  necessary for TDD-style self-patching, and it means:
  - the code runs as the same OS user as the server and can obtain the
    self-dev token. The token is removed from the test subprocess's
    environment, but that is hygiene, not a barrier: the code can read it
    from the server process (`/proc/1/environ` in the container);
  - it can write **any** file in the workspace, including protected paths,
    `.github/` and `.git/` (for example git config or hooks, which later
    self-dev git calls neutralize only partly: hooks, fsmonitor and push
    refspecs are pinned, but not every git config key is). `submit_pr`
    commits everything with `git add -A`, so protected-path edits made this
    way reach the PR branch. The manifest check applies to `write_file`,
    not to commit contents;
  - it can call the GitHub API directly with the token: push other
    branches, open or comment on PRs and issues, and merge or push to `main`
    if branch protection allows it.

  The app source in the image is root-owned and read-only to the `selfdev`
  user (only `/app/tmp` is writable), so this code cannot rewrite the
  running server itself. Everything else is caught only by GitHub: branch
  protection with required review and code-owner review, and a separate
  bot identity. Those are the
  [preconditions](#preconditions-before-pointing-a-live-agent-at-a-repo).
  Also restrict the container's network egress.
- **Using the owner's own PAT as `SELF_DEV_GITHUB_TOKEN` defeats review.**
  Self-dev PRs are then authored by the owner, and a sole owner can't
  approve their own PR under `enforce_admins`. Use a machine user or a
  GitHub App for self-dev.
- **Branch protection on a private repo needs a paid plan.** GitHub Free
  offers branch protection only on public repositories. A private repo
  needs GitHub Pro, Team or Enterprise. See
  [CONTRIBUTING.md#enabling-branch-protection](CONTRIBUTING.md#enabling-branch-protection).
- **Self-Dev MCP is compose-managed, not watcher-deployed.** For this
  release `fleet_manifest.yaml` gives `self-dev-mcp` no `container`, so the
  Deploy Watcher never rebuilds it. An operator updates it with
  `docker compose up --build self-dev-mcp` after a merge. The watcher cannot
  yet inject a service's environment (tokens, remotes) into containers it
  starts; that is on the roadmap. Separately, a watcher deploy of another
  service (e.g. `fixture-hello-mcp-<sha>`) runs *beside* any compose-managed
  instance of the same service (`fixture-hello-mcp`); the watcher neither
  stops nor replaces compose's container.
- **A `run_tests` timeout kills pytest, not its descendants.** On timeout the
  pytest process is killed, but processes that the test code spawned or
  daemonized may keep running until the container restarts.
- **The Self-Dev MCP's SSE endpoint has no authentication of its own.**
  `--transport http` exposes `/sse` and `/messages/` with no auth, API key,
  or session check beyond what MCP's SSE transport itself does — anyone who
  can reach the port can drive every Self-Dev MCP tool (including
  `write_file`, `submit_pr`, and every other write path documented in this
  file). Deploy it only on a private network, never expose it to the
  internet, and put it behind the planned MCP gateway once that exists. See
  the Hardening checklist below.
- **Docker socket access is root-equivalent, regardless of the watcher's
  non-root user.** `flotilla_mcp/deploy_watcher/entrypoint.sh` runs the watcher
  process as a non-root `watcher` user, but only after joining it to
  whichever group owns `/var/run/docker.sock` on the host. On Docker
  Desktop that socket is owned by GID 0 (`root`), so `watcher` joins the
  `root` group to reach it. This is documented, not accidental: anyone who
  can talk to `docker.sock` can run arbitrary containers with arbitrary
  host mounts no matter which uid holds that access, so the non-root user
  is defense-in-depth for the watcher's other code paths (checkout, image
  builds, `/data` I/O), not a sandbox around the socket itself.

## Hardening checklist for operators

Before pointing Flotilla MCP at a repository you care about:

- [ ] **(Precondition)** Enable GitHub branch protection on `main`: required
      `test` status check, at least one required review, required
      code-owner review, and `enforce_admins`. The workflow and CODEOWNERS
      file already exist in this repository, but branch protection is not
      enabled automatically, and on a private repo it needs a paid plan. See
      [CONTRIBUTING.md#enabling-branch-protection](CONTRIBUTING.md#enabling-branch-protection)
      for the exact command.
- [ ] **(Precondition)** Give Self-Dev MCP its own bot identity (a machine
      user or a GitHub App), never the owner's PAT.
- [x] `.github/CODEOWNERS` names a real human owner, `@OmPrakashSingh1704`
      (it covers the protected core: every `ALWAYS_PROTECTED_PATHS` file,
      the `flotilla_mcp/common/` and `.github/` subtrees, the deploy watcher,
      permission manager and gateway directories, `flotilla_mcp/self_dev_mcp/`,
      and `SECURITY.md`). Code-owner review still cannot be enforced until
      branch protection above is enabled.
- [ ] Use fine-grained tokens on this repo only: `SELF_DEV_GITHUB_TOKEN` with
      contents, pull requests and issues read/write; `WATCHER_GITHUB_TOKEN`
      with contents read-only. Never an org-wide or admin token, and never
      the same token for both.
- [ ] Run the Self-Dev MCP container with no Docker socket mount and no
      deploy credentials in its environment — verify this at the
      docker-compose/deployment level, not just by trusting the source.
- [ ] Never publish the Self-Dev MCP's HTTP port beyond `localhost` or a
      private network — its SSE endpoint has no authentication of its own
      (see Known limitations above). The default `docker-compose.yml` binds
      it to `127.0.0.1`; keep that binding, or put a real authenticating
      proxy / the planned MCP gateway in front of it before widening it.
- [ ] Run the Self-Dev MCP's `run_tests` step with network egress
      restrictions appropriate for "this executes agent-written code."
- [ ] Set up your own container/image pruning job — none exists yet.
- [ ] Monitor the Deploy Watcher process itself (process supervisor,
      restart alerting) since a crash mid-probation silently drops
      probation coverage until the next deploy.
- [ ] Keep the encryption key/config for any future credentials-manager
      instance outside git, once that service exists — it is explicitly
      not part of the protected core and is designed to be extended by
      Self-Dev MCP itself.
