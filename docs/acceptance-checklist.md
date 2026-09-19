# Manual acceptance checklist: first real run against a live GitHub repo

The automated test suite (`tests/integration/`) proves Cycle A's git
mechanics against a real local git remote and the Deploy Watcher's
build/deploy/probation/rollback mechanics against a real local Docker
daemon. Neither one talks to live GitHub — per the design's global
constraints, driving a real `open_pr` / merge / branch-protection flow
against your actual repository is a manual, one-time acceptance step, not
something the suite automates.

Run through this checklist once, against your own fork or repo, before
trusting Fleet MCP with real issues.

## Steps

1. **Create a `self-dev`-labeled issue** in your GitHub repo describing a
   small, safe change (e.g. a fix in `services/fixture_hello_mcp`).
2. **Drive Self-Dev MCP to a PR**: call `list_assigned_issues`,
   `start_issue`, `write_file`, `run_local_tests`, and `submit_pr` against
   that issue and confirm a real pull request appears on
   `selfdev/issue-N`.
3. **Verify CI and the required review block the merge**: confirm the PR
   cannot be merged until CI passes and a human review is submitted (branch
   protection configured per [CONTRIBUTING.md](../CONTRIBUTING.md)).
4. **Merge** the PR once CI is green and it's approved.
5. **Observe the watcher deploy**: confirm the Deploy Watcher picks up the
   new commit on `main`, builds the image, and promotes it — check the
   service registry and container logs.
6. **Observe probation and known-good**: wait out the probation window and
   confirm the new image tag is recorded in the known-good store only after
   probation completes.
7. **Force a bad deploy and observe the rollback**: ship a change whose
   `/health` endpoint starts failing after promotion (mirroring
   `tests/integration/test_deploy_manager_against_real_docker.py` scenario
   c) and confirm the watcher rolls back to the last known-good image
   without ever promoting the failing one.

Record the outcome (pass/fail per step, with links to the PR and any
rollback evidence) wherever your team tracks release readiness.
