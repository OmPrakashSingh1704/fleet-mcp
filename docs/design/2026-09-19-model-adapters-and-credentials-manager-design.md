> **Planned design; not implemented.** Nothing in this document exists in
> the codebase yet. See [ARCHITECTURE.md](../../ARCHITECTURE.md) for what is built.

# Model Adapters + Credentials Manager — Design Spec

Date: 2026-09-19
Status: **Planned design; not implemented.**

## Purpose

Let the chat/orchestrating agent switch which LLM backend serves the
conversation on request (e.g. "switch to JEV"), and — when the requested
model isn't supported yet — detect the gap, ask the user whether to add it,
and (on confirmation) use the Self-Dev MCP foundation
(`docs/design/2026-09-19-self-dev-mcp-design.md`) to generate,
test, and deploy a new adapter, without ever committing a raw credential to
git or Docker.

This is a sub-project of the self-dev-mcp foundation: it consumes that
system's git/test/deploy pipeline rather than re-implementing it, and adds
two new fleet services (`model-adapters-mcp`, `credentials-manager`) plus
one small extension to Self-Dev MCP itself (a general finalize step with
three modes, instead of the single PR-only path the foundation plan built).

## Scope

1. A common `ModelAdapter` interface and a `model-adapters-mcp` fleet
   service that dispatches `chat(model_name, messages, tools)` calls to the
   right provider adapter.
2. A `credentials-manager` fleet service holding every secret in the fleet
   (not just model API keys), with per-service access scoping and a
   pluggable storage backend (local encrypted file to start).
3. The chat-side "Model Manager" flow: detect an unsupported model, ask to
   add it, collect the credential, ask **how** to add it (local / PR /
   issue-only), and drive Self-Dev MCP accordingly.
4. A `finalize_mode` extension to Self-Dev MCP's existing submit step
   (`local` / `pr` / `issue_only`), generalizing the foundation plan's
   PR-only `handle_submit_pr`.

## Non-goals

- Re-implementing git/GitHub/test/deploy mechanics already built by the
  self-dev-mcp foundation plan — this spec only adds a new trigger source
  and a new finalize mode to that existing pipeline.
- Streaming or multi-modal support in the first `ModelAdapter` version —
  adapters declare capability flags; the orchestrator degrades gracefully
  against a provider that can't do everything Claude can. Adding those
  capabilities later is an interface extension, not a redesign.
- An external secrets manager (Vault, AWS Secrets Manager, etc.) — the
  credential store starts as a local encrypted file behind a pluggable
  interface. Swapping backends later is explicitly something Self-Dev MCP
  is allowed to build, since `credentials-manager` is not part of the
  protected core (see below).

## Architecture

```
Chat / Orchestrating Agent

  User: "switch to JEV"
      │
      ▼
  Model Manager (orchestrator-side logic, not a new fleet service)
      │
      │ calls chat(model_name="jev", ...) on
      ▼
  "not found" ──▶ ask user: "add support?" ──▶ yes ──▶ ask for API key
                                                   │
                                                   ▼
                                   Credentials Manager.set_credential(
                                     name="JEV_API_KEY", scope=...,
                                     owner_service="model-adapters-mcp")
                                                   │
                                                   ▼
                                   ask user: local / PR / issue-only?
                                                   │
                                                   ▼
                                   Self-Dev MCP: scaffolds
                                   services/model_adapters/jev_adapter.py
                                   implementing ModelAdapter (skipped
                                   entirely for issue-only mode)
                                                   │
                            local: commit direct to main
                            pr: branch + PR, human merges
                            issue_only: create_issue only, no code written
                                                   │
                                                   ▼
                                   Deploy Watcher: build, health-check,
                                   blue/green swap model-adapters-mcp
                                   (local/pr modes only)
                                                   │
                                                   ▼
  Model Manager retries chat(model_name="jev", ...) ──▶ now succeeds


                        ┌──────────────────────────────┐
                        │  model-adapters-mcp (fleet     │
                        │  service, NOT protected)         │
                        │  - registry.py: name → adapter,    │
                        │    each loaded in its own try/except│
                        │    so one bad adapter can't crash     │
                        │    the others                           │
                        │  - base.py: ModelAdapter interface        │
                        │  - claude_adapter.py, gpt_adapter.py,       │
                        │    jev_adapter.py, ...                        │
                        │  - reads its own creds via Credentials         │
                        │    Manager, never touches raw secrets            │
                        │    committed anywhere                              │
                        └──────────────────────────────┘

                        ┌──────────────────────────────┐
                        │  credentials-manager (fleet      │
                        │  service, NOT protected —           │
                        │  deliberately editable by Self-Dev     │
                        │  MCP so it can add new storage           │
                        │  backends later)                           │
                        │  - store.py: CredentialStore interface,      │
                        │    LocalEncryptedFileStore implementation      │
                        │  - access_policy.yaml (protected PATH within     │
                        │    this otherwise-editable service):              │
                        │    service_name -> [allowed credential names]      │
                        │  - get_credential(name, requesting_service)          │
                        │    refuses + logs if not on the allowlist              │
                        │  - set_credential / delete_credential: usable by         │
                        │    an authorized agent call OR a human CLI                │
                        └──────────────────────────────┘
```

## Protected core (delta from the foundation spec)

No changes to the foundation spec's protected core (permission manager,
gateway, deploy watcher, fleet manifest, `services/common/manifest.py`).

**`credentials-manager` is deliberately NOT part of the protected core** —
unlike deploy-watcher, this service should remain editable by Self-Dev MCP
so it can be extended with new storage backends (e.g. Vault) without a human
having to hand-write that integration. The residual risk (a bug introduced
here has unusually high blast radius, since this service touches every
secret in the fleet) is accepted in exchange for that self-extensibility,
and is mitigated by:

- `access_policy.yaml` is still a **protected path** within this otherwise
  editable service — Self-Dev MCP can improve the storage backend but
  cannot grant a service read access to a credential it wasn't already
  entitled to.
- New credential names default to an allowlist of just their declared
  `owner_service` — nothing is fetchable-by-default, so a bug has to
  actively grant excess access rather than merely fail to restrict it.
- The access-scoping check gets the same "adversarial test" treatment as
  protected-path writes in the foundation plan (see Testing strategy).

## Components

### 1. `ModelAdapter` interface (`services/model_adapters/base.py`)

Minimal common contract: `chat(messages, tools) -> ChatResponse`, plus
capability flags `supports_streaming: bool` and `supports_tool_calling:
bool`, and a declared `required_credential: str` naming the credential the
registry must fetch on the adapter's behalf.

### 2. `model-adapters-mcp` (fleet service, not protected)

Exposes MCP tools `chat(model_name, messages, tools) -> response` and
`list_supported_models() -> list[str]`. Loads each adapter module in its
own try/except at startup; a broken adapter is logged and marked
unavailable without affecting any other already-working adapter — the one
resilience property specific to "many adapters, one process" that the
foundation plan's blue/green mechanics don't provide on their own.

### 3. Model Manager (orchestrator-side logic, no new service)

Detects model-switch intent (explicit command or the orchestrating LLM
recognizing it and calling its own control-flow — reasoning stays in the
agent, per the project's founding principle). Calls
`list_supported_models()`; on a miss, walks the user through: confirm add →
collect API key → `Credentials Manager.set_credential(...)` → ask
local/PR/issue-only → invoke Self-Dev MCP with a synthetic task and the
chosen `finalize_mode`. After a successful local/PR deploy, does one live
smoke call to the new adapter before telling the user it's ready, surfacing
"added, but the key seems invalid" immediately rather than only on the
user's next real request.

### 4. `credentials-manager` (fleet service, not protected)

- `store.py`: `CredentialStore` interface; `LocalEncryptedFileStore`
  implementation — Fernet-encrypted records, key held outside git (env var
  pointing at a key file, or OS keyring). Each record:
  `{name, scope: "global" | "local", owner_service, value}`. Refuses to
  start if its encryption key is missing/misconfigured, rather than falling
  back to a weaker mode.
- `access_policy.yaml` (protected path): `service_name -> [credential
  names]`.
- `get_credential(name, requesting_service)`: refuses + logs if
  `requesting_service` isn't on that name's allowlist; otherwise resolves
  local-scope override first, falling back to global-scope.
- `set_credential` / `delete_credential`: callable via an MCP tool (used by
  the Model Manager flow) or a small local CLI a human runs directly — one
  store, two entry points.

### 5. Self-Dev MCP extension: general `finalize_mode`

Replaces the foundation plan's single `handle_submit_pr` with
`handle_finalize(issue_number, title, body, mode, deps)`:

- `mode="pr"`: identical to the existing `handle_submit_pr` — branch,
  push, open PR, human merges. Always used for GitHub-issue-triggered
  Cycle A tasks, since that path is inherently shared-repo.
- `mode="local"`: commits and pushes directly to `main` instead of opening
  a PR. If a branch-protected remote rejects that push (a shared repo with
  `SELF_DEV_MODE=local` misconfigured, or any repo where `main` happens to
  be protected), falls back to opening a PR instead of failing silently —
  a misconfiguration degrades to "needs review," never to a silent bypass.
- `mode="issue_only"`: skips code generation entirely. Calls a new
  `GitHubClient.create_issue(title, body, labels=["self-dev"])` and stops.
  The request enters the normal `self-dev`-labeled issue queue for a later
  Cycle A run (on-demand, scheduled scan, or a human picking it up) —
  appropriate when the user wants a maintainer to weigh in on approach
  before any code gets written.

`GitHubClient` (foundation plan, Task 4) gains one new method,
`create_issue(title, body, labels) -> Issue`, additive to its existing
interface.

## Data flow

### Cycle D — add an unsupported model, local mode

1. User: "switch to JEV." Model Manager calls
   `model-adapters-mcp.list_supported_models()`; `"jev"` is missing.
2. Model Manager asks: "I don't have support for JEV yet — want me to add
   it?" User confirms.
3. Model Manager asks for the JEV API key, calls
   `Credentials Manager.set_credential(name="JEV_API_KEY", scope="local",
   owner_service="model-adapters-mcp", value=<key>)`. The raw key never
   passes through Self-Dev MCP or any git-tracked file.
4. Model Manager asks: "Local only, raise a PR, or just file an issue?"
   User picks local.
5. Model Manager invokes Self-Dev MCP with a synthetic task ("add a
   ModelAdapter for JEV, required_credential=JEV_API_KEY",
   `finalize_mode="local"`, issue key `model-adapter-jev` for attempt-cap
   scoping — there is no real GitHub issue number for this trigger source).
6. Self-Dev MCP runs Cycle A steps 3–5 from the foundation plan: the
   orchestrating agent's reasoning generates
   `services/model_adapters/jev_adapter.py`, writes it via the existing
   protected-path-checked `write_file` tool, runs local tests for
   `services/model_adapters/`.
7. On local test success, `handle_finalize(mode="local")` commits and
   pushes directly to `main` (falls back to opening a PR if rejected by
   branch protection).
8. Deploy Watcher's existing poller picks up the new commit, builds
   `model-adapters-mcp`, health-checks it, blue/green-swaps it in — no new
   deploy logic needed.
9. Model Manager does one live smoke call to the new adapter; if it
   succeeds, retries `chat(model_name="jev", ...)` for the user's original
   request; if it fails, reports "added, but the key seems invalid."

### Cycle D′ — PR mode

Identical through step 4 (user picks "raise a PR" instead). At step 7,
`handle_finalize(mode="pr")` opens a PR; a human reviews and merges before
Deploy Watcher ever sees the commit. The user is told "I've opened a PR to
add JEV support; it'll be available once reviewed" rather than getting it
immediately.

### Cycle D″ — issue-only mode

Identical through step 4 (user picks "just file an issue"). Steps 5–9 are
replaced by a single call: `handle_finalize(mode="issue_only")` →
`GitHubClient.create_issue("Add ModelAdapter for JEV", <body describing the
request and required credential>, labels=["self-dev"])`. No code is
written; no deploy happens. The request now sits in the normal issue queue
for the foundation plan's existing on-demand/scheduled Cycle A to pick up
later.

### Cycle E — access-scoping violation (defensive path)

1. A service calls `get_credential("GITHUB_TOKEN", requesting_service=
   "model-adapters-mcp")`.
2. `access_policy.yaml` doesn't list `model-adapters-mcp` as allowed to
   read `GITHUB_TOKEN`.
3. Refused and logged to the audit trail, exactly like a protected-path
   write attempt in the foundation plan — the caller gets an error, never
   the secret.

## Error handling & edge cases

- **A bad new adapter must not take down every other model** — per-adapter
  try/except at registry load time (Component 2).
- **Local tests pass but the new adapter fails at a real runtime call**
  (e.g. the provider's API returns an unexpected schema) — not caught by
  Deploy Watcher's health check, which only proves the service process is
  up. Surfaces as a normal tool-call error to the user on their next
  request, not a deploy-time rollback.
- **Invalid or expired API key at collection time** — Credentials Manager
  can't validate arbitrary providers' key formats, so the Model Manager's
  post-deploy smoke call (Component 3) is the actual catch point.
- **Self-Dev MCP's attempt cap applies to synthetic tasks too** — issue key
  `model-adapter-jev` (not a real GitHub issue number) scopes the existing
  `AttemptTracker`; on exhaustion, the Model Manager reports the failure in
  chat directly, since there's no GitHub issue to comment on for this
  trigger path.
- **Concurrent "add support for X" requests for the same model** — the
  foundation plan's existing duplicate-open-attempt guard applies
  unchanged.
- **Local-mode direct push rejected by branch protection** — falls back to
  PR mode automatically (Component 5).
- **Credentials Manager's encryption key missing/misconfigured at
  startup** — refuses to start rather than degrading to plaintext storage.
- **Access-scoping violation** — refused and logged (Cycle E), regardless
  of who's asking or why.

## Testing strategy

- **Registry adapter isolation** (most important test in this spec): one
  good adapter + one deliberately broken adapter registered together;
  assert `list_supported_models()` still returns the good one and the
  service doesn't crash.
- **Credentials Manager access policy** (adversarial, mirrors the
  foundation plan's protected-path test): a service not on a credential's
  allowlist calls `get_credential`; assert refusal and an audit-log entry.
- **Credentials Manager storage round-trip**: set then get returns the same
  value; the on-disk file's raw bytes never contain the plaintext secret;
  local-scope override takes precedence over global-scope for the same
  name.
- **`ModelAdapter` contract test**: one parametrized suite run against
  every registered adapter (mocking that provider's HTTP client), asserting
  each implements `chat()`, declares `required_credential`, and reports its
  capability flags — new adapters get this coverage automatically.
- **Self-Dev MCP `handle_finalize` modes**: `mode="local"` commits directly
  to a local bare-repo fixture's `main` with no branch/PR created;
  `mode="local"` against a branch-protected fixture remote falls back to
  opening a PR; `mode="issue_only"` calls `create_issue` and confirms no
  workspace write/test/commit ever happens.
- **End-to-end integration test (Cycle D)**: a fixture "fake provider"
  adapter plus a fake Credentials Manager store, driving the full sequence
  — missing model detected, credential set, Self-Dev MCP scaffolds and
  locally finalizes a trivial adapter, Deploy Watcher (real Docker, same
  pattern as the foundation plan's integration test) blue/green-swaps
  `model-adapters-mcp`, and a final `chat(model_name=...)` call succeeds
  against the newly-added fixture adapter.
- **Manual acceptance check before trusting this on a real provider**: one
  real run against an actual new provider's API (not a fixture), confirming
  the post-deploy smoke call actually catches a bad key, before relying on
  this for real.

## Open items for the implementation plan (not decided here)

- Exact CLI shape for a human to `set_credential`/`delete_credential`
  manually (interactive prompt vs. flags vs. a config file diff).
- Whether `list_supported_models()` should distinguish "known but
  currently unhealthy" from "never configured" for better error messages.
- Concrete library choice for Fernet/encryption-at-rest and where the
  encryption key itself is expected to live in a Docker Compose deployment
  (env var vs. mounted file vs. OS keyring — the last one doesn't
  straightforwardly apply inside a Linux container and needs a decision).
