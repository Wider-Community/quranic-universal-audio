# Schema Documentation & Generation

Cross-cutting plan for how schemas are **defined, validated, and surfaced** across the repo. Lands AFTER inspector v2 is shipped and stable.

> **Status:** plan only. No code lands until trigger conditions in §6 are met.
> **Scope boundary:** explicitly excludes `.local/spaces/*` (gitignored, separate lifecycle) and `reciter_requests/` (separate Space, separate concern). Inspector + shared pipeline code only.

## 1. Why this is a separate doc (deferred from v2)

The inspector v2 deploy ships pydantic models for runtime validation of `state`, `catalog`, `audit`, `edit_history`, and the per-reciter editing files. Those models are in v2 scope as plain Python classes used by services — that's the **essential** part.

This plan covers the **layer above** that, which is convenience, not essential:

- Centralized placement rules for cross-component schemas (so the same shape isn't redefined in 4 places)
- A generator that emits JSON Schema, TypeScript types, and rendered MD reference pages from the pydantic models
- IDE integration (VS Code JSON-schema association on raw JSON files)
- CI drift gate

It's deferred from v2 because v2 is on the critical path. Pydantic models used directly by services is enough until contributors or frontend devs feel pain from shape drift. Solving "the next person needs nice rendered docs" before that person exists is premature.

## 2. The tier model

**Principle:** schemas live with the component that owns the writes. Multi-writer / multi-consumer shapes lift to `scripts/lib/schemas/`. This avoids both extremes — neither a god-folder at the repo root nor 5 silently-drifting copies of `SegmentsFile`.

### Tier 1 — Cross-component (`scripts/lib/schemas/`)

Highest drift cost; these flow through 3+ components.

| Schema | Producer | Consumers |
|---|---|---|
| `segments.py` | extraction | validators, inspector, release packager, HF dataset |
| `detailed.py` | extraction | validators, inspector, MFA timestamp extractor |
| `edit_history.py` | inspector | validators, release packager |
| `audio_source_manifest.py` | hand-authored (`data/audio/<cat>/<src>/<slug>.json`) | `build_audio_catalog`, `list_reciters.py`, validators |
| `audio_catalog.py` | catalog builder | inspector boot |
| `release_history.py` | `package_release.py` | `list_reciters.py`, version-bump logic |
| `dataset_layout.py` | release packager | HF dataset sync, future re-import |
| `timestamps.py` / `timestamps_full.py` | MFA pipeline | inspector, validators, dataset |

Full essential treatment: pydantic models, runtime validation at every read/write, CI drift gate, JSON-Schema export.

### Tier 2 — Component-internal (`<component>/schemas/`)

Owned by one component, never imported from outside.

- `inspector/schemas/{state,catalog,audit}.py` — already in v2 scope as runtime validators

### Tier 3 — Static reference data

Hand-edited JSON committed to the repo. Nothing writes them at runtime; failure mode is "human typo in a PR." Pydantic adds little; a small load-time test that `json.loads()` and spot-checks invariants suffices.

- `surah_info.json`, `qpc_hafs.json`, `digital_khatt_v2_script.json`, `phoneme_sub_costs.json`
- `data/{riwayat,sources,styles}.json` controlled vocab
- **Exception:** `data/inspector_roles.json` — authz-load-bearing, gets a real model

Recommendation: pydantic only where validation has bite.

### Tier 4 — Skip

- `.audio_meta.json` / `.audio_durations.json` caches — regeneratable, ad-hoc, no consumers depend on stable shape
- GitHub release zip layout — folder structure, not data; existing `scripts/lib/release_layout.py` is enough
- Workflow templates (`.github/templates/`) — markdown text, not data
- `RECITERS.md` — generated artifact; the generator is the spec

## 3. Layout

```
scripts/lib/schemas/                       # tier 1 — cross-component
├── __init__.py
├── segments.py
├── detailed.py
├── edit_history.py
├── audio_source_manifest.py
├── audio_catalog.py
├── release_history.py
├── dataset_layout.py
├── timestamps.py
└── _generated/                            # JSON Schema exports (CI-verified)
    └── *.json

inspector/schemas/                         # tier 2 — inspector-only (lands in v2)
├── state.py
├── catalog.py
├── audit.py
└── edit_history.py                        # may move to tier 1 if validators import

scripts/gen_schemas.py                     # one generator, walks all schemas/ dirs
.vscode/settings.json                      # JSON Schema association for raw JSON
```

## 4. Generator

One script, ~80 LoC:

```python
# scripts/gen_schemas.py
# 1. Walk inspector/schemas/ + scripts/lib/schemas/
# 2. For each pydantic model: emit Model.model_json_schema() → _generated/<name>.json
# 3. Optionally: render MD via json-schema-for-humans → docs/reference/schemas/<name>.md
# 4. Optionally: pydantic-to-typescript → inspector/frontend/src/lib/generated/schemas.ts
```

Wired into pre-commit. CI runs `python scripts/gen_schemas.py && git diff --exit-code` to catch "model changed but generated artifacts didn't."

## 5. Essential / convenience / stretch

| Layer | Tier 1 schemas | Tier 2 schemas (inspector v2) | Tier 3 (static) |
|---|---|---|---|
| **Essential** | pydantic models; runtime validation in producers + consumers | already in v2 scope | small `json.loads()` smoke test |
| **Convenience (when pain shows)** | JSON Schema export + `.vscode/settings.json` association; rendered MD docs via `json-schema-for-humans` | same as tier 1 | n/a |
| **Stretch** | TypeScript types via `pydantic-to-typescript`; per-schema MD page indexed in `docs/reference/schemas/README.md` | TS types if frontend bug shows up | n/a |
| **Skip** | Mermaid ERD, DBML, OpenAPI, Atlas/Prisma/Alembic | same | same |

The `.vscode/settings.json` line is the highest-ROI thing in the whole table for ~zero cost — autocomplete + inline errors when manually editing raw JSON. Include early.

## 6. Trigger to start

Wait for inspector v2 to be **shipped, stable for 2+ weeks**, AND at least ONE of:

- A second contributor needs to write code against a Tier-1 schema (drift risk crosses person boundary).
- A frontend bug is traced to schema shape mismatch (TS-types-from-pydantic suddenly earns its keep).
- A new component is added that needs to consume a Tier-1 schema (centralization is now strictly cheaper than copy-paste).
- Someone manually edits a raw JSON file and trips a validator that should have been caught at edit time (`.vscode/settings.json` would have prevented).

If none of these has happened in 6 months, this plan is wrong — revisit whether centralization adds more cost than it saves at our scale.

## 7. Rollout phases

Each phase ships independently; can stop at any point.

### Phase A — Lift cross-component schemas to `scripts/lib/schemas/`

- Identify the Tier-1 producers/consumers in code (grep for `segments.json` reads/writes, `audio_source_manifest` shape access, etc.)
- One PR per schema: define pydantic model in `scripts/lib/schemas/<name>.py`, replace one consumer's ad-hoc dict access with the model
- No behavior change; `model_validate()` errors should match what the code already raised on bad data
- Acceptance: every Tier-1 schema has a single canonical pydantic definition, all consumers import it

### Phase B — Generator + drift gate

- `scripts/gen_schemas.py` walks both `inspector/schemas/` and `scripts/lib/schemas/`
- Emits `_generated/<name>.json` (JSON Schema)
- Pre-commit hook runs it
- CI workflow: `python scripts/gen_schemas.py && git diff --exit-code _generated/`
- Acceptance: a deliberate model change without re-running the generator fails CI

### Phase C — VS Code JSON-schema association

- `.vscode/settings.json` maps `wip/*/segments.json` → `_generated/segments.json`, etc.
- Editor gives autocomplete + red squiggles
- Acceptance: dev opens a corrupted `segments.json`, sees errors before save

### Phase D — Rendered MD docs (only if asked for)

- Add `json-schema-for-humans` step to `gen_schemas.py`
- Output to `docs/reference/schemas/<name>.md`
- Index in `docs/reference/schemas/README.md`
- Acceptance: a non-Python audience (e.g., a contributor PR review) can read a schema without opening the .py file

### Phase E — TypeScript types (only if asked for)

- Add `pydantic-to-typescript` step
- Output to `inspector/frontend/src/lib/generated/schemas.ts`
- Acceptance: frontend imports from generated file, type errors flag drift

## 8. What's already in `docs/reference/inspector/`

Pre-v2 sketches that exist today but are NOT load-bearing:

- `docs/reference/inspector/README.md` — index
- `docs/reference/inspector/state-machine.md` — concrete sample reference doc
- `docs/reference/inspector/schemas/README.md` — per-schema index (skeleton)

These were written as a design exploration for the convention. They will be **revisited when this plan is implemented** — likely most content stays, but the `schemas/` folder gets superseded by the generator output, and the README index gets updated to match the generator's actual output paths.

Until then they are reference-quality but not authoritative — code is the contract, these docs are best-effort.

## 9. Out of scope

- **`.local/spaces/*` schemas** (`mfa_aligner`, `quranic_universal_aligner`) — gitignored, separate lifecycle, separate deployment cadence. If they ever need a shared schema with the inspector, lift just that schema to Tier 1; don't try to centralize the whole Space.
- **`reciter_requests/` schemas** — separate Space with its own deploy. The `/api/request` payload is the only cross-boundary contract; if it grows, lift only that to Tier 1.
- **Workflow YAML schemas** — GH Actions owns that.
- **Image build manifests** — Dockerfile owns that.
- **Migration tooling** (Atlas, Alembic, Prisma) — overkill for 2 SQLite tables managed by `_bootstrap_schema()`.

## 10. See also

- [`inspector-deploy/v2/inspector-cleanup-registry.md`](inspector-deploy/v2/inspector-cleanup-registry.md) §10 — pointer here, confirms doc generation is out of v2 scope
- [`inspector-deploy/v2/inspector-data-storage.md`](inspector-deploy/v2/inspector-data-storage.md) — Tier-2 inspector schemas defined here at design level
- [`inspector-deploy/v2/inspector-state-management.md`](inspector-deploy/v2/inspector-state-management.md) — state SQLite DDL
