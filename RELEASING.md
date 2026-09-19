# Releasing `fleetmcp`

This document is for maintainers cutting a release of the `fleetmcp` PyPI
package. It describes the one-time setup, the steps to cut a release, how to
recover from a failed release, and the security model behind the pipeline.
The pipeline itself is `.github/workflows/release.yml`.

## Prerequisites (one-time)

These only need to be done once, before the first release, by whoever
administers the `OmPrakashSingh1704/fleet-mcp` repository and the `fleetmcp`
project on PyPI/TestPyPI.

1. **A PyPI account and a TestPyPI account.** These are separate accounts on
   separate sites (https://pypi.org and https://test.pypi.org) — a PyPI
   login does not work on TestPyPI.

2. **A "pending publisher" on each, so PyPI trusts this repository's GitHub
   Actions runs without an API token.** On PyPI, under the `fleetmcp`
   project (or, before the project exists yet, via "Publish a new project"
   with a pending publisher), add a publisher with exactly:

   | Field | Value |
   |---|---|
   | PyPI project name | `fleetmcp` |
   | Owner | `OmPrakashSingh1704` |
   | Repository name | `fleet-mcp` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

   Repeat on TestPyPI with the same values except **Environment name:
   `testpypi`**.

   See [Adding a Trusted
   Publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
   for the exact UI flow. These fields must match
   `.github/workflows/release.yml` exactly — a mismatched workflow filename
   or environment name is the most common reason a Trusted Publishing
   exchange fails with an OIDC error at publish time.

3. **GitHub environments `testpypi` and `pypi`**, created under this
   repository's **Settings → Environments**. Add the repository owner as a
   required reviewer on the `pypi` environment (not on `testpypi`) — this is
   the human approval gate described in [Security](#security) below. Both
   environment names must match what's above and what
   `.github/workflows/release.yml`'s `publish-testpypi` and `publish-pypi`
   jobs declare.

4. **Trusted Publishing works from a private repository** — GitHub's OIDC
   token exchange doesn't require the repository to be public. But two
   things that make the *published package* usable do need the repository
   public first:

   - The PyPI project page's links (Homepage, Source, Issues, Changelog,
     Security, from `pyproject.toml`'s `[project.urls]`) will 404 for
     visitors until `OmPrakashSingh1704/fleet-mcp` is public.
   - The README's logo and any other image served from
     `raw.githubusercontent.com` (see
     [pyproject.toml](pyproject.toml)'s `[tool.hatch.metadata.hooks.fancy-pypi-readme]`
     substitutions) will not load on the PyPI project page until the
     repository is public — `raw.githubusercontent.com` 404s on a path
     inside a private repository for an unauthenticated request.

   Plan to make the repository public before or at the same time as the
   first real release, not after.

## Cutting a release

1. **Bump the version** in [`fleetmcp/__init__.py`](fleetmcp/__init__.py)
   (`__version__ = "X.Y.Z"`). This is the single source of truth for the
   package version — `[tool.hatch.version]` in `pyproject.toml` reads it,
   and `scripts/check_tag_version.py` checks the release tag against it.

2. **Move `[Unreleased]` to a dated version** in
   [`CHANGELOG.md`](CHANGELOG.md): rename the `## [Unreleased]` heading to
   `## [X.Y.Z] - YYYY-MM-DD`, add a fresh empty `## [Unreleased]` above it if
   there's ongoing work, and update the compare links at the bottom of the
   file (`[Unreleased]: .../compare/vX.Y.Z...HEAD` and
   `[X.Y.Z]: .../releases/tag/vX.Y.Z`).

3. **Open a PR with both changes and merge it** through normal review (see
   [CONTRIBUTING.md](CONTRIBUTING.md)). Do not tag before this merges — the
   tag in the next step must point at the merge commit that actually
   contains the bumped version.

4. **Tag the merge commit and push the tag:**

   ```bash
   git tag vX.Y.Z <merge-commit-sha>
   git push origin vX.Y.Z
   ```

   The push triggers `.github/workflows/release.yml` (it runs `on: push:
   tags: ["v*.*.*"]`).

5. **Watch the workflow, then approve the `pypi` environment.** The workflow
   runs `verify` → `build` → `publish-testpypi` → `publish-pypi` →
   `github-release` in order. `publish-pypi` is gated on the `pypi`
   environment's required reviewer (you) — approve it from the run's page
   (or the email/notification GitHub sends) once you're satisfied the
   TestPyPI publish and the build's checks look right.

6. **Verify:**

   ```bash
   pip install fleetmcp==X.Y.Z
   ```

   in a clean virtualenv, and confirm `fleetmcp-self-dev --version` prints
   `X.Y.Z`.

## Failure recovery

- **A version/tag mismatch fails before any build happens.** The `verify`
  job's `Check tag matches fleetmcp.__version__` step
  (`scripts/check_tag_version.py`) runs before `build`, so a tag pushed
  against the wrong `__version__` never reaches `python -m build`, let alone
  PyPI. Fix `fleetmcp/__init__.py`, delete the bad tag, and re-tag.

- **PyPI (and TestPyPI) versions are immutable.** Once `X.Y.Z` is uploaded,
  you cannot re-upload a different artifact under the same version, on
  either index — a bad release ships as a new patch release (`X.Y.Z+1`),
  never a re-upload of the same version number.

- **TestPyPI's `publish-testpypi` step passes `skip-existing: true`**, so
  re-running the release workflow for the same tag (for example, after
  fixing something in `publish-pypi` or a later job) does not fail just
  because that version's artifacts are already sitting on TestPyPI from a
  previous attempt — the step succeeds and moves on. **`publish-pypi` does
  not get `skip-existing`.** A second attempt to publish the same version to
  the real index fails loudly instead of silently no-op'ing, because a
  silent skip there could mask a real problem (e.g. the artifact actually
  differs from what you think was published, or you're re-running against
  the wrong tag). If `publish-pypi` fails because the version already
  exists, that is PyPI correctly telling you this exact version was already
  shipped — ship a patch release instead of trying to force it through.

- **Re-run only the failed job**, using the workflow run's "Re-run failed
  jobs" action, rather than re-tagging — `concurrency: group:
  release-${{ github.ref }}` prevents two runs for the same tag from
  overlapping, and `verify`/`build` re-running unnecessarily just wastes CI
  time (they're not harmful to re-run, but there's no need to).

- **Yanking a broken release** (one that's technically installable but known
  bad) is done in the PyPI UI — go to the project's release on
  https://pypi.org, "Options" → "Yank release", and give a reason. Yanking
  does not delete the release (existing pins that reference it still
  resolve), it only stops it from being selected by a bare `pip install
  fleetmcp` going forward. There is no API-driven yank in this pipeline;
  it's a deliberate manual, human action.

## Security

- **No PyPI or TestPyPI API tokens exist anywhere in this repository or its
  secrets.** Both `publish-testpypi` and `publish-pypi` authenticate via
  [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) — GitHub's
  OIDC identity for the running job, exchanged by
  `pypa/gh-action-pypi-publish` for a short-lived upload token scoped to
  that one publish. There is nothing long-lived to leak, rotate, or steal
  from a compromised dependency.
- **`permissions: id-token: write` is granted only on the two publish
  jobs** (`publish-testpypi`, `publish-pypi`) in `release.yml` — not at the
  workflow level, and not on `verify`, `build`, or `github-release`. Those
  other jobs can't mint an OIDC token for PyPI even if something in their
  steps were compromised.
- **The `pypi` environment's required-reviewer approval is the human gate**
  before anything reaches the real index. `publish-testpypi` runs
  unattended once `build` passes; `publish-pypi` (and therefore
  `github-release`, which depends on it) waits for that approval. This is
  the only manual step in an otherwise fully automated pipeline, by design.
