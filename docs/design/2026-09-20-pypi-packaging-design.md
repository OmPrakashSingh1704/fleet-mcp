> **Point-in-time design record.** Written while planning the `services` →
> `fleetmcp` rename this document itself proposes; some references below
> (e.g. `python -m services....`) describe the pre-rename state on purpose.
> It also predates the later Fleet MCP → Flotilla MCP product/package
> rename, so every `fleetmcp`/`Fleet MCP` reference below is stale; the
> shipped package is `flotilla_mcp` (PyPI distribution `flotilla-mcp`).
> The code plus [ARCHITECTURE.md](../../ARCHITECTURE.md) are authoritative
> for the current, actually-built layout and names.

# PyPI Packaging and Release — Design Spec

Date: 2026-09-20
Status: approved design, pending implementation plan

## Purpose

Publish Fleet MCP to public PyPI as the `fleetmcp` distribution. `pip install fleetmcp`
(or `uvx fleetmcp`) runs the Self-Dev MCP server; `pip install "fleetmcp[watcher]"` adds
the Deploy Watcher. Releases are cut by pushing a version tag, which triggers CI to build,
test, and publish via PyPI Trusted Publishing, with no long-lived API token anywhere.

## Decisions (made with the product owner)

- **Distribution name: `fleetmcp`.** `fleet-mcp` (and therefore `fleet_mcp`, which PyPI
  normalizes to the same name) is already taken by an unrelated Fleet DM integration. The
  product name stays "Fleet MCP"; only the install/import name differs.
- **Public source.** Publishing uploads the full source (sdist). This is accepted: the
  project is Apache-2.0.
- **One package with extras.** The base install is the Self-Dev MCP server; the
  `[watcher]` extra adds the Deploy Watcher's Docker dependency. The fixture service is
  test-only and is not shipped.
- **Release flow:** tag → CI → TestPyPI → PyPI (manually approved) → GitHub Release, all
  via Trusted Publishing (OIDC).
- **Timing:** the package rename lands on the open foundation PR (#1) before it is merged
  and before branch protection is enabled, so the first protected-core change under
  protection is not a repo-wide rename.

## Why the rename is required

The code currently lives in a top-level import package named `services`. Installing that
from PyPI would put a generic `services` package into every user's site-packages, where it
could collide with unrelated code. The package becomes `fleetmcp`.

## Layout

Flat layout (no `src/`). A `src/` layout would add another path level to every protected
path, every Dockerfile path and every manifest path, for little benefit in this repo.

```
fleetmcp/
  __init__.py            # __version__ = "0.1.0" (single source of truth)
  common/manifest.py
  self_dev_mcp/...
  deploy_watcher/...
  fixture_hello_mcp/...  # test-only; excluded from the wheel
```

Everything that references `services` is updated:
- imports and `python -m services....` invocations;
- the always-protected paths (`fleetmcp/common/manifest.py`, prefix `fleetmcp/common/`,
  `fleetmcp/__init__.py`), plus their tests;
- `fleet_manifest.yaml` service paths;
- CODEOWNERS, the Dockerfiles, docker-compose, CI, and the docs.

## Build and dependencies

- Build backend: `hatchling`; the version is read from `fleetmcp/__init__.py`.
- Wheel: includes `fleetmcp/`, excluding `fleetmcp/fixture_hello_mcp/`, every
  `Dockerfile`, and `entrypoint.sh`.
- Sdist: source, tests, `LICENSE`, `NOTICE`, `README.md`.
- `requirements.txt` stays the pinned lockfile for Docker images and CI.
- `pyproject.toml` declares ranged runtime dependencies for pip users:
  - base: `mcp` (bounded to `>=1.2,<1.3`, because the SSE app mirrors private
    `FastMCP.run_sse_async` internals that a test guards), `PyGithub`, `PyYAML`,
    `starlette`, `uvicorn`, `anyio`, `requests`;
  - `[watcher]`: `docker`.
- Required metadata: `license = "Apache-2.0"` with `LICENSE` and `NOTICE` as license
  files, `readme`, `requires-python = ">=3.11"`, classifiers, and project URLs (homepage,
  source, issues, changelog, security).

## Entry points

- `fleetmcp`, the `uvx` default, and `fleetmcp-self-dev` both run the Self-Dev MCP server
  (`--transport stdio|http`, default stdio).
- `fleetmcp-watcher` runs the Deploy Watcher. It needs the `[watcher]` extra; without the
  `docker` package it exits with a clear message naming the extra.
- New env var `FLEET_MANIFEST_PATH`, default `./fleet_manifest.yaml`. Today the manifest is
  read from the current directory, which is fragile for an installed tool.
- The README gains a "Use with an MCP client" section with a Claude Desktop / Claude Code
  config snippet.

## Release pipeline

The version's single source of truth is `fleetmcp.__version__`. At release time
CHANGELOG `[Unreleased]` becomes `[X.Y.Z]`.

`.github/workflows/release.yml`, triggered by pushing a tag matching `v*.*.*`:

1. **verify**: the tag (minus `v`) must equal `__version__`, then run the full non-docker
   test suite.
2. **build**: `python -m build` produces the sdist and wheel, and `twine check` runs on
   both. The wheel is smoke-installed into a fresh virtualenv: `import fleetmcp` works and
   `fleetmcp-self-dev --help` exits 0. The artifacts are uploaded for the later jobs.
3. **publish-testpypi**: `pypa/gh-action-pypi-publish` against TestPyPI, environment
   `testpypi`, `id-token: write`.
4. **publish-pypi**: the same against PyPI, environment `pypi`, which requires owner
   approval in GitHub.
5. **github-release**: creates the GitHub Release for the tag and attaches the artifacts.

Default workflow permissions are read-only; only the publish jobs get `id-token: write`,
and only the release job gets `contents: write`. No secrets are used.

### One-time owner setup (documented in `RELEASING.md`)

- On pypi.org and test.pypi.org, add a **pending publisher**: owner
  `OmPrakashSingh1704`, repository `fleet-mcp`, workflow `release.yml`, environment `pypi`
  (respectively `testpypi`).
- In GitHub, create the environments `testpypi` and `pypi`, with the owner as required
  reviewer on `pypi`.
- Optional but recommended at the first release: make the GitHub repository public so
  that the PyPI project links resolve.

## Error handling and edge cases

- **Tag/version mismatch:** the verify job fails before anything is built.
- **Re-running an already published version:** PyPI rejects the upload. Versions are
  immutable, so a fix is shipped as a new patch release.
- **TestPyPI succeeds but PyPI fails:** only the PyPI job needs re-running, which is safe.
- **Private repository:** Trusted Publishing works, but the PyPI project page will link to
  a repository users cannot open. `RELEASING.md` says so.
- **Protected-core semantics:** the always-protected paths describe Fleet MCP's own
  repository. When a user points Self-Dev MCP at a different repository, the `.git`,
  `.github/`, `requirements.txt` and similar entries still apply; the `fleetmcp/...`
  entries are simply inert. Making the always-protected set configurable per target repo
  is roadmap.

## Testing

- The existing suite passes after the rename, with the protected-path tests updated to the
  new paths.
- New tests:
  - Wheel contents: build the wheel in a test and assert it contains no
    `fixture_hello_mcp`, no `Dockerfile` and no `entrypoint.sh`, and that it does contain
    `fleetmcp/common/manifest.py`.
  - Console scripts: `--help` works; `fleetmcp-watcher` without `docker` exits with the
    extra's name.
  - `FLEET_MANIFEST_PATH` is honored.
  - The tag-vs-version check (a small script under `scripts/`, unit-tested).
- Docker: all three images rebuild, `docker compose config` validates, and the Docker
  integration test passes.
- A local dry run of `python -m build` + `twine check`. No upload happens until a tag is
  pushed.

## Out of scope

- Publishing Docker images to a registry.
- A per-target-repo configurable protected set.
- Changing the product name.
