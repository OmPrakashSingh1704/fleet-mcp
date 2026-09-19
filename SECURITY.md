# Security Policy

Fleet MCP grants an autonomous agent the ability to edit source code, open
pull requests, and (indirectly, after human merge) trigger a production
deploy of a fleet of services. This document describes what we guarantee,
what we assume, how to report a problem, and what we know is still weak.

## Supported versions

Fleet MCP is pre-1.0. Only the latest `0.x` release receives security fixes.
There is no long-term support branch yet; if you're running an older `0.x`
version, upgrade before relying on it.

| Version | Supported |
|---|---|
| Latest `0.x` | Yes |
| Older `0.x` | No |

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
- Secrets (tokens, keys) leaking into logs, error messages, committed
  files, or built images. (The Deploy Watcher's checkout errors are
  deliberately redacted of the remote URL, which can embed a token —
  a regression there is in scope.)
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

- **Protected core.** `fleet_manifest.yaml` and
  `services/common/manifest.py` are protected unconditionally, independent
  of manifest content — hardcoded in `ALWAYS_PROTECTED_PATHS`. Services
  marked `protected: true` (`deploy-watcher`, `permission-manager` (planned),
  `mcp-gateway` (planned)) are unwritable by Self-Dev MCP across their
  entire path prefix. Path comparisons normalize `\` to `/`, resolve `..`
  segments, and case-fold, and any path that still resolves outside the
  repo root after normalization is treated as protected.
- **Workspace containment.** Every `write_file`/`read_file` call resolves
  the target against the issue's ephemeral workspace directory
  (`os.path.realpath`) and refuses absolute paths, drive letters, UNC paths,
  and any resolved path outside that workspace root — before anything
  touches disk.
- **No auto-merge.** Nothing in this codebase can merge a pull request.
  `open_pr` is idempotent (re-submitting returns the existing open PR
  instead of opening a duplicate) and never force-pushes. Merging to `main`
  requires a human, enforced by GitHub branch protection and CODEOWNERS —
  configure both before trusting this in a real repo (see the checklist
  below; this is a platform control this codebase cannot enforce on its
  own).
- **No deploy authority in Self-Dev MCP.** The Self-Dev MCP process holds no
  Docker socket access and no deploy credentials, and does not import
  `docker`. Only the Deploy Watcher can build an image, start a container,
  or flip the service registry.
- **Secrets never committed.** The Deploy Watcher's checkout errors redact
  the remote URL (which may embed a token) before raising. No component in
  this repository writes credentials to a tracked file.
- **Known-good floor.** An image is recorded as known-good only after it
  survives a full probation window (default 30 minutes) with zero failed
  checks. Rollback always targets the last *proven* image; if none exists
  yet, rollback is a no-op rather than stopping the only running container.
- **Attempt cap.** Writes for a given issue are capped (default 5); the cap
  check and the increment are atomic, and a refused write (protected path,
  workspace escape) never consumes an attempt — only writes that actually
  reach disk count against the cap.
- **Retired shas are never redeployed.** If a container for a given commit
  sha already exists but isn't active (it was previously promoted, then
  rolled back or superseded), the Deploy Watcher refuses to redeploy it
  rather than silently reviving a bad build.

### Assumptions

- The GitHub token issued to the Self-Dev MCP is scoped to only the repos
  it's meant to operate on, and branch protection + CODEOWNERS are actually
  configured on any repo you don't want auto-merged into. This codebase
  enforces the tool-level and workspace-level controls above; it cannot
  enforce GitHub-side branch protection for you.
- The Docker daemon the Deploy Watcher talks to is not shared with anything
  the Self-Dev MCP (or an attacker who compromises it) can reach. If
  Self-Dev MCP's container can reach the Deploy Watcher's Docker socket by
  some other path (a misconfigured volume mount, a shared network
  namespace), every guarantee above is void — "no Docker access" is a
  property of how you deploy these two services, not just of the Self-Dev
  MCP's own source code.
- The machine running the Deploy Watcher is otherwise trusted. Fleet MCP
  defends against a misbehaving or successfully-prompt-injected *agent*; it
  is not a sandbox against a host-level attacker who can already run
  arbitrary code on the Deploy Watcher's host.

## Known limitations

These are documented, accepted gaps, not secrets — treat them as inputs to
your own risk assessment, not as an invitation to assume they're fixed:

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
- **The Self-Dev MCP runs code inside its own container by design.**
  `run_tests` executes the target repo's own test suite (`pytest`) inside
  the Self-Dev MCP's container, on whatever the agent just wrote. This is
  necessary for TDD-style self-patching, but it means the Self-Dev MCP
  container should be treated as "will execute arbitrary Python the agent
  generates" — network and filesystem isolation for that container matter
  as much as the write-tool checks in this document.

## Hardening checklist for operators

Before pointing Fleet MCP at a repository you care about:

- [ ] Enable GitHub branch protection on `main` requiring the CI status
      check and at least one human review.
- [ ] Add a `CODEOWNERS` entry for the protected-core paths (the deploy
      watcher, permission manager, gateway directories, and
      `fleet_manifest.yaml`) naming a real human owner.
- [ ] Scope the Self-Dev MCP's GitHub token to only the repos/orgs it needs;
      do not issue an org-wide admin token.
- [ ] Run the Self-Dev MCP container with no Docker socket mount and no
      deploy credentials in its environment — verify this at the
      docker-compose/deployment level, not just by trusting the source.
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
