# Completed migrations

One-shot scripts that transformed prod data/schema to its current shape. They are
**frozen history, not live tooling** — each ran once per bucket and assumes the
*pre*-migration shape, so re-running against current state is a no-op or error by
design. Kept for auditability: [`data-migrations.md`](../../../docs/reference/data-migrations.md)
narrates the sequence and [`database.md`](../../../docs/reference/database.md)
cross-references the schema state they produced.

| Migration | Status | What it did |
|---|---|---|
| `migrate_json_to_sqlite.py` | applied (dev + prod) | 7 bucket JSON stores + audit JSONL → `db/inspector.db` (the SQLite cutover) |
| `migrate_to_reciters_prefix.py` | applied (prod 2026-05-31) | unify `wip/<slug>/` + `published/<slug>/` bucket trees → `reciters/<slug>/` |

**A script belongs here only if** running it again on current state is a
no-op-or-error *by design* (it assumes the pre-migration shape). Idempotent,
re-runnable tools — `backfill_*`, `convert_*`, `purge_*`, `unignore_category` —
stay flat in `inspector/scripts/`.
