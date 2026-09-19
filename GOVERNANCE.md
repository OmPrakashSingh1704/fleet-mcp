# Governance

Fleet MCP is currently maintained by a small group of maintainers with
commit access to this repository. This document describes how decisions get
made and, specifically, the rule that constrains automation the same way it
constrains people.

## Maintainers

Maintainers are the individuals listed as code owners in
[`.github/CODEOWNERS`](.github/CODEOWNERS), which now exists in this
repository. Its owner is still the `@OWNER` placeholder, though, so until
someone replaces it with a real GitHub user or team (and a repo admin
enables branch protection — see
[CONTRIBUTING.md#enabling-branch-protection](CONTRIBUTING.md#enabling-branch-protection)),
code-owner review cannot actually be enforced. Until both of those are done,
the maintainers are the people with write access to this repository, and any
substantial change to project direction should go through a pull request
and issue discussion rather than a direct push, so it's visible and
reviewable regardless of who technically could have pushed directly.

## How decisions are made

- **Day-to-day changes** (bug fixes, small features, documentation) are
  decided through normal pull request review: at least one maintainer
  approval, CI passing, and no unresolved objection from another
  maintainer.
- **Design-level changes** (new fleet services, changes to the protected
  core, changes to the safety model described in
  [SECURITY.md](SECURITY.md) and [ARCHITECTURE.md](ARCHITECTURE.md)) should
  start as a written spec or an issue for discussion before implementation,
  following the pattern already used in `docs/design/`. Lazy
  consensus applies: if no maintainer objects within a reasonable review
  window, the change proceeds. A maintainer with a substantive objection
  can block until it's resolved through discussion.
- **Disagreements among maintainers** that can't be resolved through
  discussion are decided by a simple majority of active maintainers. This
  hasn't come up yet; if it does, this document will be updated with
  whatever process actually gets used, rather than pretending a heavier
  process already exists.

## Protected-core changes can never be merged by automation

This is the one governance rule that isn't a matter of maintainer judgment:
**changes to the protected core (`fleet_manifest.yaml`,
`fleetmcp/common/manifest.py`, and any service marked `protected: true` in
the manifest) require a maintainer's review and approval, and can never be
merged by an automated process** — not Self-Dev MCP, not any future
extension of it, regardless of what task it was given or what an
orchestrating agent's reasoning concluded. This mirrors the technical
guarantee in [SECURITY.md](SECURITY.md#guarantees): the code-level
enforcement (Self-Dev MCP's `write_file` refusing those paths) and the
process-level enforcement (a human, via CODEOWNERS and branch protection,
approving any change that does reach those paths through a different route)
are meant to hold independently of each other. Neither is allowed to become
the only thing standing between an agent and the protected core. The
CODEOWNERS file and CI workflow that back the process-level enforcement now
exist; the repo admin still has to replace the `@OWNER` placeholder and
enable branch protection before that enforcement is actually active — see
[CONTRIBUTING.md#enabling-branch-protection](CONTRIBUTING.md#enabling-branch-protection).

## Adding or removing a maintainer

New maintainers are proposed by an existing maintainer and confirmed by
lazy consensus among current maintainers. A maintainer may step down at any
time; a maintainer who is unreachable or inactive for an extended period may
be removed by consensus of the remaining maintainers.

## Releases

Publishing a `fleetmcp` release to PyPI requires the same human-approval
gate as any other change reaching `main`, plus one more: the `pypi`
GitHub environment used by `.github/workflows/release.yml` requires the
repository owner's manual approval before the publish job runs, in addition
to the tag having gone through normal PR review. See
[RELEASING.md](RELEASING.md) for the exact procedure.

## Changing this document

Changes to `GOVERNANCE.md` itself follow the same design-level change
process above: propose it, allow time for discussion, proceed on lazy
consensus. This document is not part of the protected core in the technical
sense (it's documentation, not code the manifest tracks), but changes to it
still deserve the same visibility.
