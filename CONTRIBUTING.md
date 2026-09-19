# Contributing to Fleet MCP

Thanks for your interest in Fleet MCP. This document covers how to get a dev
environment running, how we review changes, and what's different about
reviewing a pull request that a self-dev agent opened versus one a human
opened (short version: nothing — the bar is the same).

## Dev setup

Requirements: Python 3.11+.

```bash
git clone https://github.com/OmPrakashSingh1704/fleet-mcp.git
cd fleet-mcp
python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
python -m pytest tests -W error::DeprecationWarning
```

Running with `-W error::DeprecationWarning` is intentional — it's how CI
runs the suite, and it's how we've kept the codebase free of deprecation
noise (e.g. pytest-asyncio's fixture-loop-scope warning) rather than letting
warnings accumulate silently. If your change introduces a new deprecation
warning, fix it before opening a PR rather than suppressing the flag.

## Branch and PR flow

- Branch from `main`. Human contributors can use any branch name;
  `selfdev/issue-N` is reserved for Self-Dev MCP's own branches (see
  [below](#reviewing-self-dev-prs)).
- Use [Conventional Commits](https://www.conventionalcommits.org/) for
  commit messages (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`).
  This keeps history scannable and lines up with `CHANGELOG.md`.
- Open a PR against `main`. CI must pass (the same `pytest tests` run
  above). At least one human review is required before merge — this is
  meant to be enforced by GitHub branch protection, not just convention. The
  CI workflow (`.github/workflows/test.yml`) and the CODEOWNERS file
  (`.github/CODEOWNERS`) exist in this repository, but branch protection is
  not enabled automatically — see
  [Enabling branch protection](#enabling-branch-protection) below for the
  exact command the repo admin runs to turn required checks and required
  review into an actual merge gate.
- We do not squash-merge away meaningful history by default, but a PR with a
  cleaner commit sequence than "wip / wip / fix / wip" is easier to review;
  feel free to interactively clean up your own branch before requesting
  review (never rewrite a shared branch someone else is also pushing to).

## Test-driven development

Fleet MCP's own codebase was built test-first, and we ask contributions to
follow the same shape: a failing test that demonstrates the bug or the new
behavior, then the minimal implementation that makes it pass. This isn't
bureaucracy — for the protected-path and rollback logic specifically, the
test *is* the security control. A PR that changes behavior in
`services/common/manifest.py`, `services/self_dev_mcp/tools.py`, or
`services/deploy_watcher/deploy_manager.py` without a corresponding test
change will get sent back, no matter how obviously correct the diff looks.

Run the full suite before pushing:

```bash
python -m pytest tests -W error::DeprecationWarning
```

`tests/integration/` proves the git and Docker mechanics against a real
local git remote and a real local Docker daemon (skipped automatically if
Docker isn't available; CI runs with `-m "not docker"`). Before trusting a
deployment against your own GitHub repo for the first time, also work
through [docs/acceptance-checklist.md](docs/acceptance-checklist.md), the
one part of the flow — a real PR, CI, review, and merge — that can't be
automated.

## Protected core changes need CODEOWNERS approval

The fleet manifest (`fleet_manifest.yaml`), the manifest loader
(`services/common/manifest.py`), and any service marked `protected: true` in
the manifest (currently `deploy-watcher`; `permission-manager` and
`mcp-gateway` once they exist) are the protected core described in
[ARCHITECTURE.md](ARCHITECTURE.md) and [SECURITY.md](SECURITY.md).
`.github/CODEOWNERS` already lists these paths (plus `/.github/` and
`SECURITY.md`), but its owner is still the `@OWNER` placeholder — GitHub
flags those entries as invalid until someone replaces `@OWNER` with a real
GitHub user or team, and code-owner review can't be enforced until both that
replacement and branch protection (see below) are done. Once both are in
place, changes under those paths require sign-off from the designated owner,
in addition to normal review. This is by design: it's the human-side half of
the same guarantee that the Self-Dev MCP's `write_file` tool refuses to
touch those paths at all. If your PR touches protected-core paths, say so
explicitly in the PR description (the
[PR template](.github/PULL_REQUEST_TEMPLATE.md) asks) so reviewers know to
apply the extra scrutiny.

## Enabling branch protection

The CI workflow (`.github/workflows/test.yml`, job id `test`) and
`.github/CODEOWNERS` exist in this repository, but neither is enforced until
a repo admin turns on branch protection for `main` — GitHub does not do this
automatically just because the files exist. Before enabling it, replace the
`@OWNER` placeholder in `.github/CODEOWNERS` with a real GitHub user or
team; otherwise GitHub treats every CODEOWNERS entry as invalid and
"require code-owner reviews" can never be satisfied, permanently blocking
every PR that touches a protected-core path.

Once `@OWNER` is replaced, a repo admin with `gh` authenticated against
`OmPrakashSingh1704/fleet-mcp` runs:

```bash
gh api repos/OmPrakashSingh1704/fleet-mcp/branches/main/protection \
  --method PUT \
  --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["test"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "require_code_owner_reviews": true,
    "dismiss_stale_reviews": true
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
```

Use `--input -` with the JSON on stdin, as shown — `--field` with nested
JSON objects (e.g. `required_status_checks`) does not produce the same
request and silently misconfigures the protection rule. This is a
GitHub-side setting, not a file in this repository, so it can't be verified
by the test suite; confirm it by checking **Settings → Branches** on the
repo, or by re-running the same `gh api` call with `--method GET`.

## Reviewing self-dev PRs

Pull requests opened by the Self-Dev MCP are labeled `self-dev` and branched
as `selfdev/issue-N`. **Review them exactly like a human-authored PR** — CI
must pass, a human must approve, and protected-core paths get the same
CODEOWNERS gate. Nothing about the `self-dev` label grants a faster or
lighter review path; if anything, treat unfamiliar-looking changes from an
agent with the same skepticism you'd apply to an unfamiliar-looking change
from a new contributor. If a self-dev PR needs changes, leave review
comments as normal — a follow-up invocation of `start_issue` for the same
issue number resumes the same branch rather than opening a duplicate PR, so
your comments land on the branch that gets the fix.

## Adding a new fleet service

1. Create `services/<your_service>/` with your service's code and its own
   `tests/<your_service>/` mirror.
2. Add an entry to `fleet_manifest.yaml`:
   ```yaml
   services:
     your-service:
       path: services/your_service
       protected: false
       container: your-service
       health_check: http://your-service:8080/health
   ```
   Leave `protected: false` unless the service holds deploy authority or
   sits in the permission/auth path — protected services are meant to be
   rare, human-reviewed-only, and are not something you opt into casually.
3. Add a `Dockerfile` for the service under `services/<your_service>/` (repo
   root as build context, per the pattern the Deploy Watcher expects — see
   `services/deploy_watcher/image_builder.py`).
4. Expose a `/health` endpoint that returns HTTP 200 when the service is
   actually ready to serve traffic — the Deploy Watcher's blue/green swap
   depends on this being accurate, not just "the process is up."
5. Write tests before implementation, following the pattern in
   `tests/self_dev_mcp/` or `tests/deploy_watcher/`.

## Contributor License stance

Fleet MCP does not use a CLA. By submitting a contribution, you agree it's
licensed under Apache-2.0, inbound = outbound — the same license as the
rest of the project, with no separate agreement to sign.

## Questions

See [SUPPORT.md](SUPPORT.md) for where to ask. Security issues go through
[SECURITY.md](SECURITY.md), never through a public issue or PR.
