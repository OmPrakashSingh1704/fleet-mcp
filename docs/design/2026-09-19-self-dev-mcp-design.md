> **Historical design document.** This is the original design; the shipped behavior differs (e.g. a monorepo manifest instead of per-repo remotes, 7 tools, and the hardening in SECURITY.md). The code, [ARCHITECTURE.md](../../ARCHITECTURE.md) and [SECURITY.md](../../SECURITY.md) are authoritative.

# Self-Dev MCP — Design Spec

Date: 2026-09-19
Status: approved design, pending implementation plan

## Purpose

Add a "self-development" capability to the Python/Docker MCP fleet: an MCP
server that can autonomously fix bugs, respond to GitHub issues, heal itself
after crashes, and eventually generate new plugin/tool modules — for itself
*and* for other MCP servers in the fleet — without ever being able to take a
running system down by editing it, and without ever being able to weaken the
permission system that constrains it.

This sits inside the broader MCP + Agent architecture already agreed on
(agent → MCP gateway → permission manager → capability servers). The Self-Dev
MCP is one more capability server behind that gateway; "editing code" is
classified as a write/irreversible-adjacent action subject to the same
permission model as sending an email or submitting a form, plus the
additional, stronger controls described below because its blast radius is
the whole fleet, not one external side effect.

## Scope

Target capabilities, built in stages (staging detail belongs in the
implementation plan, not here — this spec describes the end state each stage
is aiming at):

1. **Self-healing** — recover a crashed/erroring fleet member automatically
   (rollback to last known-good image), and separately investigate root
   cause via a normal reviewed fix.
2. **Self-patching** — given a GitHub issue or direct request, edit source,
   open a PR, and (after human merge) get redeployed.
3. **Self-extending** — write new MCP tool modules/plugins to add
   capabilities, without touching a target server's own runtime/framework
   code (as distinct from the "protected core" repos defined below, which
   are off-limits at every stage regardless of capability tier).

The agent can act on **any repo in the fleet**, including its own, *except*
the protected core (see below), which is permanently off-limits regardless
of stage.

## Non-goals

- This spec does not cover the design of the MCP gateway or permission
  manager themselves (assumed to exist per the earlier architecture
  discussion) — only how the Self-Dev MCP and Deploy Watcher integrate with
  them.
- No auto-merge path exists at any stage. A human always merges. This is a
  hard requirement, not a default that gets relaxed later without a new
  design discussion.

## Architecture

```
GitHub (system of record for review + enforcement)

  Issues ──▶ picked up by ──▶ Self-Dev MCP
                                   │ opens branch + PR
                                   ▼
  PR ──▶ GitHub Actions (tests) ──▶ Branch protection
             │                         │  (human review +
             │ status checks           │   CODEOWNERS; protects
             ▼                         │   core repos at the
        pass/fail                      │   platform level)
                                        ▼
                                  merge to main
                                       │ webhook / poll
                                       ▼
Your Docker host

  ┌───────────────┐     ┌────────────────┐     ┌────────────────────┐
  │ Self-Dev MCP  │     │ Deploy Watcher  │     │  MCP Gateway +      │
  │ (git/PR ops    │     │ (polls GitHub,  │     │  Permission Manager │
  │  only; no       │     │  builds image,  │     │  (PROTECTED CORE)   │
  │  build/deploy    │     │  blue/green      │     │                     │
  │  credentials)     │     │  swap, health     │     │                     │
  │                    │     │  check, keeps      │     │                     │
  │                    │     │  last-known-good)  │     │                     │
  └───────────────┘     └────────────────┘     └────────────────────┘
                                       │
                                       ▼
                          ┌────────────────────────┐
                          │  Fleet containers         │
                          │  (Gmail-MCP, Browser-MCP,  │
                          │   Files-MCP, Self-Dev-MCP   │
                          │   itself, ...)                │
                          └────────────────────────┘
```

The Self-Dev MCP's own container is redeployed by the same Deploy Watcher
pipeline as every other fleet member — it is not special-cased. It can edit
its own source, but only the Watcher ever builds/swaps a running container,
and the Watcher only acts on commits that already passed GitHub's
server-side review gate. Self-editing can never take effect without going
through the human-reviewed pipeline first.

## Protected core

The following are permanently off-limits to the Self-Dev MCP's write tools,
enforced at multiple independent layers (defense in depth):

- **Permission manager** (repo: `protected: true`)
- **MCP gateway / auth** (repo: `protected: true`)
- **Deploy Watcher** (repo: `protected: true`) — it holds real build/deploy
  authority; if the Self-Dev MCP could weaken its health-check or swap
  logic, it could indirectly defeat every other safeguard in this design.
- **The fleet manifest and deny-list files within the Self-Dev MCP's own
  repo** (`protected_paths`) — it cannot edit the file that defines what it
  cannot edit.

Enforcement layers:

1. **Tool-level**: the Self-Dev MCP's `write_file` tool checks the fleet
   manifest before every write and refuses protected repos/paths
   unconditionally — independent of what the agent's plan or reasoning says.
2. **Git-level**: GitHub branch protection + CODEOWNERS on protected repos
   requires a designated human owner's approval, enforced server-side by
   GitHub regardless of what the Self-Dev MCP's own code does. This is the
   layer that still holds even if the tool-level check has a bug.
3. **Credential-level**: the Self-Dev MCP is issued a GitHub token scoped
   only to non-protected repos where feasible; it holds no Docker socket
   access and no deploy credentials at all, so it structurally cannot build
   or swap containers regardless of what it writes.

The manifest and this set of protected repos is human-edited only; the
Self-Dev MCP has no tool capable of modifying it.

## Components

### 1. Self-Dev MCP server (Python)

MCP tools exposed: `list_assigned_issues`, `create_branch`, `read_file`,
`write_file`, `run_local_tests`, `commit_and_push`, `open_pr`,
`check_pr_status`, `comment_on_issue`.

Behavior:
- Clones/pulls the target repo into an ephemeral, per-task workspace inside
  its own container — never a shared volume with any live fleet container.
- Checks the fleet manifest before every `write_file` call; refuses and
  logs a policy-denial (not a crash) on any protected repo/path.
- Runs the target repo's own test command locally as an informational
  pre-check only. The **authoritative** test run is always GitHub Actions,
  triggered after push.
- Holds no Docker socket access, no deploy credentials, no ability to merge
  its own PRs.
- Retry/iteration cap per issue (default 5 attempts) before it gives up and
  comments on the issue explaining what it tried, instead of looping
  forever or force-pushing something broken.

### 2. Fleet manifest

Human-edited YAML, itself part of the protected core:

```yaml
repos:
  gmail-mcp:
    remote: git@github.com:org/gmail-mcp.git
    protected_paths: []
    container: gmail-mcp
    health_check: http://gmail-mcp:8080/health
  permission-manager:
    remote: git@github.com:org/permission-manager.git
    protected: true
  mcp-gateway:
    remote: git@github.com:org/mcp-gateway.git
    protected: true
  deploy-watcher:
    remote: git@github.com:org/deploy-watcher.git
    protected: true
  self-dev-mcp:
    remote: git@github.com:org/self-dev-mcp.git
    protected_paths: ["fleet_manifest.yaml", "deny_list.py"]
    container: self-dev-mcp
    health_check: http://self-dev-mcp:8080/health
```

### 3. Deploy Watcher (Python)

- Polls GitHub (or receives a webhook) for new commits on each non-protected
  repo's `main` branch.
- On a new commit: builds a Docker image tagged with the commit SHA, starts
  it alongside the currently-live container, polls its `health_check`
  endpoint for N consecutive successes.
- On success: flips gateway routing/service-discovery to the new container;
  stops (does not delete) the old container, retained for a configurable
  rollback window.
- On failure: kills the new container, leaves the old one untouched and
  serving. A failed self-dev deploy never takes down the working system.
- **Post-promotion probation**: continues monitoring a newly-promoted
  container for a probation period (default 30 min) after swap; if it
  degrades within that window, automatically rolls back to the previous
  image without waiting for a human.
- **Known-good floor**: never removes the *only* known-good image for a
  service regardless of retention settings, even if that means keeping an
  old image indefinitely until a new one proves itself.
- On repeated build failure from a merged commit: alerts and stops
  attempting that repo's deploy until a human or a follow-up fix lands — no
  infinite build-retry loop.

### 4. GitHub configuration (not code, one-time setup)

- Branch protection on every repo: required status check = CI test suite,
  required reviewers = 1 human.
- CODEOWNERS file naming a human owner for the protected repos and the
  protected paths inside the Self-Dev MCP's own repo.
- A GitHub App / token for the Self-Dev MCP scoped to only the repos it's
  allowed to touch.

### 5. Trigger sources

- **On-demand**: another agent/orchestrator calls Self-Dev MCP tools
  directly (e.g. `fix_issue(repo, issue_number)`).
- **GitHub issues**: polls (or is invoked via webhook) for issues labeled
  `self-dev` in non-protected repos.
- **Health-check failure**: Deploy Watcher detects a live container failing
  repeatedly, immediately rolls back (ops action, pre-approved, reversible,
  no code edit), and separately notifies the Self-Dev MCP to root-cause and
  open a real fix PR through the normal reviewed pipeline.
- **Scheduled scan**: cron-triggered sweep of all non-protected repos for
  open `self-dev`-labeled issues, run through the same on-demand path.

## Data flow

### Cycle A — on-demand or issue-triggered change (main path)

1. Trigger arrives (direct call or issue poll).
2. Manifest check: if repo is `protected: true`, refuse immediately —
   never attempts an edit.
3. Clone into ephemeral workspace, create branch `selfdev/issue-<n>`.
4. Edit files via `write_file` (rejects protected paths).
5. Run local tests informationally; iterate up to the retry cap.
6. Push branch, open PR linking the issue, request CODEOWNERS review.
7. GitHub Actions runs authoritative CI as a required status check.
8. Human (optionally alongside an AI reviewer that can comment but not
   approve/merge) reviews the PR.
9. Human approves and merges to `main`. If changes requested, Self-Dev MCP
   can be re-invoked with review comments to push follow-up commits.
10. Deploy Watcher detects the new commit, builds a SHA-tagged image.
11. Watcher starts new container alongside old, polls health check.
12. Success → routing flips, old container retained for rollback window.
    Failure → new container killed, old untouched; next cycle can treat
    this as a new issue.

### Cycle B — health-check failure (self-heal)

1. Watcher's health polling on a live container starts failing.
2. Immediate mitigation: rollback to last known-good image (pre-approved,
   reversible, no code edit), service restored, incident logged.
3. Watcher notifies Self-Dev MCP with failure context (logs, commit,
   health-check output).
4. Self-Dev MCP proceeds as Cycle A step 3 onward against the real bug.

### Cycle C — scheduled scan

Same as Cycle A, self-initiated on a timer instead of an external trigger,
across all non-protected repos' open `self-dev`-labeled issues.

## Error handling & edge cases

- **Protected-path violation attempt**: rejected by `write_file`, logged to
  the audit trail as a policy hit — expected control flow, not a crash.
- **Local tests fail repeatedly**: capped retries, then a comment on the
  issue explaining what was tried; no infinite loop, no broken force-push.
- **CI fails after push**: Self-Dev MCP can be re-invoked to read the
  failure log and push a fix commit, up to the same retry cap.
- **Merge conflict against `main`**: rebase/merge and retest automatically;
  if conflicts are semantic and unclear, comment asking a human instead of
  guessing.
- **Concurrent cycles on the same repo**: branch names are scoped per issue
  (`selfdev/issue-<n>`); a check for an already-open PR on that branch
  prevents duplicate PRs for the same issue.
- **Deploy build failure post-merge**: rare since CI already ran pre-merge;
  Watcher alerts and stops retrying that repo rather than looping.
- **Health-check flapping post-promotion**: probation-period monitoring
  triggers automatic rollback without waiting for a human.
- **Rollback window exhaustion**: the known-good floor guarantees at least
  one working image is never evicted, even past the normal retention
  window.
- **Deploy Watcher itself compromised or buggy**: mitigated structurally by
  making its repo part of the protected core (Self-Dev MCP cannot touch it
  at all) — this is a design decision, not runtime error handling, but it's
  the reason the runtime error handling above can be trusted.

## Testing strategy

- **Self-Dev MCP unit tests**: mock GitHub API and git operations; the
  deny-list check blocking protected-path/repo writes *before anything
  touches disk* is the single most important test in the system and must
  be explicit, not just incidentally covered.
- **Deploy Watcher unit tests**: mock image builds; verify blue/green swap,
  known-good floor, and probation-period auto-rollback against a fake
  health-check endpoint that can be flipped healthy/unhealthy on command.
- **Integration test (docker-compose based)**: a trivial fixture "hello
  world" MCP server registered in a test fleet manifest, run through the
  full Cycle A end-to-end against a disposable test-org GitHub repo (issue
  → PR → merge → deploy → health check → old container retired). Runs in
  CI for the self-dev-mcp and deploy-watcher repos themselves.
- **Adversarial test**: deliberately attempt a protected write in a test;
  assert refusal and audit-log entry — a regression test for the one thing
  that must never silently break.
- **Manual acceptance check before first real use**: run one real self-heal
  cycle against a deliberately-broken fixture container and confirm
  automatic rollback before trusting the system on real fleet members.

## Open items for the implementation plan (not decided here)

- Exact staging order across the three capability tiers (self-healing /
  self-patching / self-extending) and what "done" looks like per stage.
- Concrete tech choices: GitHub API client library, YAML schema validation
  library, health-check protocol details, image tagging/retention specifics.
- Where the fleet manifest physically lives relative to the gateway's own
  service-discovery config (avoiding two sources of truth).
