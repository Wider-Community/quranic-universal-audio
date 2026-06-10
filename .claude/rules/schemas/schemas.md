---
paths:
  - "qua_shared/schemas/**/*.py"
  - "inspector/routes/**/*.py"
  - "inspector/services/storage/bucket_audit.py"
  - "scripts/diagnostics/validate_bucket.py"
  - "scripts/codegen/regen_fe_types.py"
---

# Schemas

Deep reference: `docs/reference/data-migrations.md`, `architecture.md`. These are the don't-break-this invariants only.

- **Three folders, by where the shape lives:** `bucket/` external JSON artefacts · `wire/` HTTP request/response · `config/` state+db blobs. Every shape is a model here — no hand-mirrored TS (sole exception: `lib/types/peaks-transport.ts`, when added).
- **Routes serialize through wire models:** `Model.model_validate(...)` on the way in, `model.model_dump(mode="json")` on the way out. Errors/acks use `ErrorEnvelope`/`OkAck` — never inline dicts.
- **Touch any model → regen → commit:** `python scripts/codegen/regen_fe_types.py` then commit `inspector/frontend/src/lib/types/generated/schemas.ts`. New FE-referenced shape goes in `fe_types.py` first. CI `schema-codegen-check` gates via `git diff --exit-code`.
- **`extra="forbid"` is the default everywhere.** `strip_and_warn` (legacy tolerance) only on `bucket/` artefacts. `extra="allow"` only when a forward-compat fixture proves an unknown field rides through unchanged.
- **Validate external bucket files at write/audit time, never on cached reads:** `scripts/diagnostics/validate_bucket.py` (manual/CI) + nightly `bucket-validate.yml` + `/healthz?deep=1` sample. Don't re-validate bytes already served from cache.
