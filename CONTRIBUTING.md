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
pip install -r requirements-dev.txt
python -m pytest tests -m "not docker" -v -W error::DeprecationWarning -W error::pytest.PytestUnhandledCoroutineWarning
```

`requirements-dev.txt` pulls in `requirements.txt` plus the packaging tools
(`build`, `twine`, `hatchling`, `hatch-fancy-pypi-readme`) that
`tests/test_packaging.py` needs to build a wheel as part of the suite.

Both `-W error` flags are intentional and match CI.
`error::DeprecationWarning` keeps the codebase free of deprecation noise.
`error::pytest.PytestUnhandledCoroutineWarning` turns an `async def` test
that pytest would silently *skip* (no async plugin is installed or needed)
into a hard failure. Write async checks as sync tests that drive the
coroutine with `asyncio.run(...)`. pytest-asyncio is not a dependency; if
you have it installed globally, it may print a harmless loop-scope warning,
or you can add `-p no:asyncio`. If your change introduces a new deprecation
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
`fleetmcp/common/manifest.py`, `fleetmcp/self_dev_mcp/tools.py`, or
`fleetmcp/deploy_watcher/deploy_manager.py` without a corresponding test
change will get sent back, no matter how obviously correct the diff looks.

Run the full suite before pushing:

```bash
python -m pytest tests -m "not docker" -v -W error::DeprecationWarning -W error::pytest.PytestUnhandledCoroutineWarning
python -m pytest tests -m docker -v   # needs a reachable Docker daemon
```

`tests/integration/` proves the git and Docker mechanics against a real
local git remote and a real local Docker daemon (skipped automatically if
Docker isn't available; CI runs with `-m "not docker"`). Before trusting a
deployment against your own GitHub repo for the first time, also work
through [docs/acceptance-checklist.md](docs/acceptance-checklist.md), the
one part of the flow — a real PR, CI, review, and merge — that can't be
automated.

## Protected core changes need CODEOWNERS approval

The protected core described in [ARCHITECTURE.md](ARCHITECTURE.md) and
[SECURITY.md](SECURITY.md) is:

- the exact files in `ALWAYS_PROTECTED_PATHS`: `fleet_manifest.yaml`,
  `fleetmcp/common/manifest.py`, `fleetmcp/__init__.py`, `requirements.txt`,
  `requirements-dev.txt`, `docker-compose.yml`, `pyproject.toml`,
  `.gitattributes`, `.gitignore`;
- the subtrees in `ALWAYS_PROTECTED_PREFIXES`: `fleetmcp/common/` and
  `.github/`;
- every service marked `protected: true` in the manifest (currently
  `deploy-watcher`; `permission-manager` and `mcp-gateway` once they exist).

`.github/CODEOWNERS` mirrors all of these (plus `SECURITY.md`), and
`tests/test_manifest.py` fails if a hardcoded entry is missing from it. If
you add to the protected core, update both. Its owner is now the real
GitHub user `@OmPrakashSingh1704`, so the entries are valid, but code-owner
review still can't be enforced until branch protection (see below) is
enabled. Once branch protection is on, changes under those paths require
sign-off from the designated owner,
in addition to normal review. This is by design: it's the human-side half of
the same guarantee that the Self-Dev MCP's `write_file` tool refuses to
touch those paths at all. If your PR touches protected-core paths, say so
explicitly in the PR description (the
[PR template](.github/PULL_REQUEST_TEMPLATE.md) asks) so reviewers know to
apply the extra scrutiny.

## Enabling branch protection

### Supported setup for `OmPrakashSingh1704/fleet-mcp`

The repository is **private, on GitHub Pro**. Protection is turned on in
this order:

1. ~~The owner replaces the CODEOWNERS placeholder owner with
   `@OmPrakashSingh1704`.~~ Done.
2. **The owner merges the foundation branch.** Until then there is no
   protection on `main`.
3. **Right after that merge**, full branch protection is applied to
   `main` with the command below: required `test` check, 1 approving
   review, code-owner review, dismiss stale reviews, `enforce_admins`, no
   force-push, no deletions.
4. **From then on, self-dev uses a separate bot identity** (a machine user
   or a GitHub App) for `SELF_DEV_GITHUB_TOKEN`, so its PRs are authored by
   the bot and the owner can approve them. A live agent is not pointed at
   the repo before steps 3 and 4 are done.

### Details

The CI workflow (`.github/workflows/test.yml`, job id `test`) and
`.github/CODEOWNERS` exist in this repository, but neither is enforced until
a repo admin turns on branch protection for `main` — GitHub does not do this
automatically just because the files exist. `.github/CODEOWNERS` already
names a real GitHub user, `@OmPrakashSingh1704`, as owner, so its entries
are valid; enabling branch protection with "require code-owner reviews" is
the only remaining step to make that review actually required.

**Plan requirement:** branch protection on a **private** repository needs a
paid GitHub plan (Pro for personal accounts, Team or Enterprise for
organizations). On GitHub Free it is available only for public repos, and
the API call below fails with a 403 ("Upgrade to GitHub Pro or make this
repository public") on a private one.

**Use a separate bot identity for self-dev.** Branch protection and
self-dev must be set up together. If `SELF_DEV_GITHUB_TOKEN` is the
owner's own PAT, self-dev PRs are authored by the owner, and a sole owner
cannot approve their own PR with `enforce_admins` on. Give Self-Dev MCP a
machine user or a GitHub App with fine-grained contents, pull requests and
issues read/write on this repo only. Both are
[preconditions](SECURITY.md#preconditions-before-pointing-a-live-agent-at-a-repo)
before a live agent is pointed at the repo.

CODEOWNERS already names the real owner, so a repo admin with `gh`
authenticated against `OmPrakashSingh1704/fleet-mcp` can run:

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

1. Create `fleetmcp/<your_service>/` with your service's code and its own
   `tests/<your_service>/` mirror.
2. Add an entry to `fleet_manifest.yaml`:
   ```yaml
   services:
     your-service:
       path: fleetmcp/your_service
       protected: false
       container: your-service
       health_check: http://your-service:8080/health
   ```
   Leave `protected: false` unless the service holds deploy authority or
   sits in the permission/auth path — protected services are meant to be
   rare, human-reviewed-only, and are not something you opt into casually.
   `container` opts the service into Deploy Watcher blue/green deploys;
   omit it for a compose-managed service (as `self-dev-mcp` does). The
   watcher cannot yet pass environment variables to the containers it
   starts. `health_check` is informational only: the watcher always probes
   `http://<service>-<sha>:8080/health` on the `mcp-fleet` network, so the
   service must listen on port 8080.
3. Add a `Dockerfile` for the service under `fleetmcp/<your_service>/` (repo
   root as build context, per the pattern the Deploy Watcher expects — see
   `fleetmcp/deploy_watcher/image_builder.py`).
4. Expose a `/health` endpoint that returns HTTP 200 when the service is
   actually ready to serve traffic — the Deploy Watcher's blue/green swap
   depends on this being accurate, not just "the process is up."
5. Write tests before implementation, following the pattern in
   `tests/self_dev_mcp/` or `tests/deploy_watcher/`.

## Cutting a release

Releases (the `fleetmcp` PyPI package and its console scripts) are cut by a
maintainer following [RELEASING.md](RELEASING.md) — version bump, changelog,
tag, and the Trusted Publishing workflow. Contributors outside that process
don't need it; it's documented for maintainers only.

## Contributor License stance

Fleet MCP does not use a CLA. By submitting a contribution, you agree it's
licensed under Apache-2.0, inbound = outbound — the same license as the
rest of the project, with no separate agreement to sign.

## Questions

See [SUPPORT.md](SUPPORT.md) for where to ask. Security issues go through
[SECURITY.md](SECURITY.md), never through a public issue or PR.
