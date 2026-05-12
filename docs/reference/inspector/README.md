# Inspector — Reference Docs

What the system **is**, right now. Concise, human-readable, immediately understandable. One topic per file. Updated as each phase lands.

For *why* a thing was chosen, see [`docs/planning/inspector-deploy/v2/`](../../planning/inspector-deploy/v2/). For *what's not in scope*, see [`inspector-deferred.md`](../../planning/inspector-deploy/v2/inspector-deferred.md). For *what's left to do*, see [`inspector-cleanup-registry.md`](../../planning/inspector-deploy/v2/inspector-cleanup-registry.md).

When this doc and a planning doc disagree on **behavior**, this doc is the contract — fix the planning doc to match (or fix the code if the planning doc is right and the code drifted).

## Index

### Foundations (Phase 0)

| Doc | What it covers |
|---|---|
| [`schemas/`](schemas/) | One file per storage shape — see [`schemas/README.md`](schemas/README.md) for the per-schema index. Covers state SQLite, catalog SQLite, audit logs, edit history, segments, detailed, timestamps, timestamps_full, audio catalog, roles, controlled vocab, etc. |
| [`state-machine.md`](state-machine.md) | Lifecycle states + orthogonal flags (marked_ready, visibility) + transition matrix |
| [`events.md`](events.md) | Canonical event vocabulary (`<noun>.<verb>`); event payload shapes |
| [`folder-structures.md`](folder-structures.md) | Bucket layouts (data + meta), HF dataset namespace, image layout, container `/tmp` |
| [`env-vars.md`](env-vars.md) | Single canonical env var table |

### Read-only deploy (Phase 1)

| Doc | What it covers |
|---|---|
| [`api-endpoints.md`](api-endpoints.md) | API surface — extended per phase. Phase 1: read-only set. |
| [`image-build.md`](image-build.md) | Dockerfile, COPY list, gunicorn invocation, single-worker assertion |
| [`dataset-layout.md`](dataset-layout.md) | HF dataset `inspector/segments/<slug>/v<n>/` + CURRENT pointer convention |

### Auth + claim (Phase 3)

| Doc | What it covers |
|---|---|
| [`auth-flow.md`](auth-flow.md) | HF OAuth callback URL, signed cookie payload, role resolution at session bind |
| [`claim-endpoints.md`](claim-endpoints.md) | `/api/claim`, `/api/release`, `/api/mark-ready`, `/api/unmark-ready` contracts |

### Admin (Phase 4)

| Doc | What it covers |
|---|---|
| [`admin-dashboard.md`](admin-dashboard.md) | `/admin` panels, override endpoints |

### Writes (Phase 5)

| Doc | What it covers |
|---|---|
| [`save-flow.md`](save-flow.md) | `data_dir.resolve` resolver, flat layout, force-flush default |
| [`edit-history-schema.md`](edit-history-schema.md) | `edit_history.jsonl` shape post-refinement |
| [`force-claim.md`](force-claim.md) | Force-claim semantics, 30-min lease, persistence in SQLite |

### Publish (Phase 6)

| Doc | What it covers |
|---|---|
| [`publish-pipeline.md`](publish-pipeline.md) | Publish event flow, fan-out triggers |
| [`hf-jobs.md`](hf-jobs.md) | HF Job specs (snapshot, timestamps, audio) |
| [`workflows.md`](workflows.md) | GH Actions inventory after decommissions |

### Cross-cutting

| Doc | What it covers |
|---|---|
| [`runbook.md`](runbook.md) | Operational quick-reference (rotate token, force rebuild, reading audit, etc.) |
| [`accordion-guides.md`](accordion-guides.md) | Frontend-authored validation accordion guide templates and example records |

## Convention

Each reference doc:

- **One topic.** Don't conflate.
- **Two screens or less.** If it's longer, split.
- **Tables over prose.** When in doubt, table.
- **No "should" or "will" or "planned to."** Present tense, what IS true.
- **Link to planning doc for rationale.** Don't repeat the why.
- **Optional `_meta` line at top** if there's a breaking change vs prior shape: `_meta: schema_v1 → schema_v2 on 2026-MM-DD; see <commit>`.

## Audit (runs in CI on main)

`scripts/lib/verify_reference_docs.py` (lands in Phase 0) cross-checks every reference doc against the codebase:

- Every event in `events.md` exists in `inspector/services/state.py` and vice versa.
- Every state in `state-machine.md` exists in the SQLite CHECK constraint.
- Every endpoint in `api-endpoints.md` has a registered Flask route.
- Every env var in `env-vars.md` is read by code (and vice versa).
- Every schema doc in `schemas/` matches its in-code DDL or TypedDict — see [`schemas/README.md`](schemas/README.md) audit section for specifics.
- Every doc listed in this index exists.

CI fails on drift in main.

## Adding a new reference doc

1. Create the file under this directory.
2. Add a row to the index above.
3. If the doc covers something the audit script can verify, extend the script (or list it as un-audited and explain why).
4. Open a PR; CI runs the audit.
