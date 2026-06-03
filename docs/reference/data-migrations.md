# Data migrations & one-shot scripts

Playbook for one-shot migrations / backfills against bucket data (`reciters/<slug>/` per-reciter artefacts, and the SQLite substrate). Completed migrations live in `scripts/migrations/` (frozen); re-runnable backfills in `scripts/backfills/`. Shared shape: **dry-run by default**, write to a parallel `archive/<migration>/<slug>/…` (or `.bak`) path before mutating, drift- or parity-check, then atomically promote. Per-reciter loops process independently — a mid-loop failure leaves earlier slugs done, later ones untouched.

> The historical per-reciter scan-count tables and bug-forensics that used to live here are dropped — they're frozen in commit history. This doc keeps the durable bits an agent needs to *re-run* a migration: detection predicate, apply CLI, archive/rollback path, idempotency, and what each does NOT touch.

## Script catalogue

| Script | Kind | Target | Idempotent | Notes |
|---|---|---|---|---|
| `migrate_json_to_sqlite.py` | substrate | 7 bucket JSON stores + audit → `db/inspector.db` | yes (`--force` to overwrite) | The JSON→SQLite cutover. See [database.md](database.md). |
| `migrate_pending_orphans.py` | substrate | legacy pending-request orphans → `requests/completed.json` | yes | Archives orphans whose state moved past `awaiting_alignment`. |
| `migrate_to_reciters_prefix.py` | bucket layout | `wip/<slug>/` + `published/<slug>/` → `reciters/<slug>/` | yes (skip-existing) | One-shot prefix unification. Copy → verify → `--delete-old`. |
| `purge_stale_wraps.py` | detailed.json | strip stale `wrap_word_ranges` | yes | Migration #1. |
| `backfill_qalqala_letter.py` | detailed.json | persist `qalqala_letter` per seg | yes (drift-gated) | Migration #2. See [validation.md](validation.md). |
| `backfill_boundary_adj.py` | detailed.json | persist `is_boundary_adj` per seg | yes (drift-gated) | Migration #2. Needs `quranic_phonemizer` (offline-only). |
| `purge_pad_migration.py` | edit_history.jsonl | strip `batch_type=="pad_migration"` batches | yes (noop on clean) | Migration #3. |
| `convert_peaks_v2_to_v3.py` | peaks/ | plain `<ch>.json` v2 → slim `<ch>.json.gz` v3 | yes | Migration #5 wire shape. See the inspector-audio skill. |
| `backfill_deleted_basmala.py` | pipeline_meta.json | derive `deleted_basmala_chapters` sidecar | yes (byte-equal) | Migration #5. |
| `derive_pipeline_meta.py` | pipeline_meta.json | derive sidecar for a local slug dir | yes (modulo `generated_at`) | New-pipeline + legacy fallback paths. |
| `backfill_pipeline_peaks.py` | edit_history_peaks.jsonl | resync per-op pipeline peaks with history | yes | Migration #5 catch-up tool. |
| `backfill_peaks_slim.py` / `rollback_peaks_slim.py` | peaks/ | legacy `.json` → slim `.json.gz` (+ reverse) | yes | See the inspector-audio skill. |
| `backfill_deleted_basmala.py` is paired with extraction's native write | — | — | — | New reciters land pre-stamped; backfill is legacy catch-up only. |
| `unignore_category.py` | edit_history.jsonl | bulk-revert `ignore_issue` ops for a category | yes (skips reverted) | Data fix, not a migration — drives `services.segments.undo.undo_ops`. |
| `audit_bucket_reciter.py` | (read-only) | per-reciter integrity audit | n/a | Run before publishing a reciter. |

Tooling (not migrations): `download_bucket_reciter.py`, `upload_bucket_reciter.py` (download → migrate → re-upload workflow), `bench_storage.py`, `regen_fe_types.py` (FE codegen — see CLAUDE.md schema convention).

## Bucket layout: `wip/` + `published/` → `reciters/` (`migrate_to_reciters_prefix.py`)

One-shot unification of the two state-driven per-reciter prefixes into a single `reciters/<slug>/`. Content location is now lifecycle-independent: a publish (or any) transition is a pure DB write and never moves files. The old `wip/` and `published/` slug sets were disjoint, so this is a conflict-free union — no per-slug merge.

**Apply** — server-side Xet-hash `backend.copy()` of every file under `wip/<slug>/…` and `published/<slug>/…` to `reciters/<slug>/…`. Idempotent (skips a file whose destination exists), so re-run to catch a delta before deploy. `--bucket {dev,prod}` (prod requires `--allow-prod`), `--verify` (assert every source file landed under `reciters/`), `--dry-run`, `--delete-old` (remove the legacy trees — run only after the deploy is confirmed reading `reciters/`).
**Sequence** — copy (dev) → deploy → verify → copy (prod) → deploy → verify → `--delete-old`. The old trees are the rollback until the final delete. `--delete-old` is two-key (`--confirm-delete`); without it, it only previews.
**⚠ Prod `--delete-old` needs the aligner Space redeployed first.** The `quranic-universal-aligner` HF Space reads released reciters' `segments.json` + `timestamps/` from the **prod** inspector bucket via a read-only mount. It has been migrated (quranic-universal-aligner repo: `src/preload/{repo_loader,manifest_client}.py`) to read content from `reciters/<slug>/` and derive its released set from `db/inspector.db` (`delivery_states.state='released' AND visibility='public'`, ∩ segments present) instead of enumerating the `published/` folder — so it no longer depends on `published/`, and won't leak WIP reciters (folder presence alone would). **Redeploy the aligner (`upload-aligner`) + verify, THEN** prod `--delete-old` is safe. Dev cleanup was always unaffected (the aligner mounts prod).
**Does NOT** — touch `db/inspector.db` (state rows unchanged — only content location moves); change any lifecycle state; rewrite the audit/`transitions` stream.
**Status (2026-05-31)** — COMPLETE on **prod**. Legacy `wip/` (18 slugs) + `published/` (6 slugs) trees deleted from the prod bucket after verifying `reciters/` held an equal-or-newer superset of every file. The legacy pre-SQLite JSON stores (`access/ activity/ audit/ requests/ state/`) were removed in the same pass (`catalog/` kept as the read-only backup). `wip` was dropped from `auto_detect._SCAN_PREFIXES` — it now scans `reciters/` only.

## Substrate migrations

### JSON → SQLite (`migrate_json_to_sqlite.py`)
The cutover. Reads the legacy stores via the configured backend, decomposes into SQLite tables, runs a **semantic** parity readback (list order normalized, not byte), optionally uploads to `db/inspector.db`. Refuses to overwrite an existing bucket DB without `--force`. Decomposition + parity gate fully documented in [database.md](database.md). `python scripts/migrations/migrate_json_to_sqlite.py --bucket dev [--force] [--allow-orphans] [--dry-run]`.

### Pending orphans (`migrate_pending_orphans.py`)
Legacy boot-time reconcile *deleted* pending-request orphans (losing proposed_edits + comments + auto_claim). New design archives at each terminal transition; this catches up legacy data by writing orphans into `requests/completed.json` with a synthetic system actor + `reason="migrated from orphan"`. Dry-run default; `--apply` to commit. Idempotent (second run archives zero).

## detailed.json migrations

### #1 Stale `wrap_word_ranges` purge (`purge_stale_wraps.py`)
**Detection** — `inspector/utils/repetitions.py::is_wrap_consistent`: a wrap is stale when its word positions fall outside the seg's `matched_ref` range (the split/edit-ref/merge inheritance bug, now closed at the reducer + `adapters/save_payload.py::make_seg` guard). `classify_wrap` returns `None`/`"stale"`/`"corrupted"`.
**Apply** — `--apply` writes `archive/stale_wraps/<slug>/detailed.json.<ts>.bak` then overwrites. Flags `--slug`, `--show-details`.
**Does NOT** — touch `edit_history.jsonl`; invalidate caches (restart / reciter-switch to see); re-segment the corrupted-geometry segs (wrap stripped, re-segment manually if needed).

### #2 `qalqala_letter` + `is_boundary_adj` backfill (`backfill_qalqala_letter.py`, `backfill_boundary_adj.py`)
Persist two classifier fields per seg so the runtime validate loop is a dict-lookup. **One source-of-truth helper each** (`services/segments/qalqala.py::compute_qalqala_letter`, `services/validation/classifier.py::compute_is_boundary_adj`) shared by save / extraction / backfill. Field semantics + write-vs-read ownership in [validation.md](validation.md).
**Apply** — `--slug <s> --dry-run` / `--all`. Each slug **drift-gated** independently: stamp → run validate against persisted fields → compare to `bench/ground_truth/<slug>.json` → promote only on byte-equal; else abort. Writes `archive/backfill/<slug>/detailed.json` before promotion.
**Re-run after** — restoring an old `archive/` snapshot, a `quranic_phonemizer` version bump (re-stamps phonemic side of `is_boundary_adj`), or a manual catalog import that bypasses extraction/save. Legacy segs missing the field fall through to live compute (identical answer, slower).
**Does NOT** — touch `edit_history.jsonl`; cross-process cache invalidate; delete `quranic_phonemizer` (still imported by the backfill + extraction).

## edit_history migrations

### #3 `pad_migration` batch purge (`purge_pad_migration.py`)
**Detection** — `record.get("batch_type") == "pad_migration"`. Whole batch is the unit; ops never inspected. NOT purged: `null` (user edits), `"strip_specials"`.
**Apply** — backup → `archive/pad_migration/<slug>/edit_history.jsonl.<ts>.bak`, purged batches → `archive/pad_migration/<slug>/edit_history.jsonl`, kept batches → live file (atomic in that order). Flags `--apply`, `--slug`. Idempotent (zero pad batches ⇒ `noop`).
**Does NOT** — delete data (archived + recoverable); touch `detailed.json`/`segments.json`; edit the state `transitions`/audit stream; bump `HISTORY_SCHEMA_VERSION`.

### Edit-history schema slim-down (code change, no script)
Writer-side only: new batches drop op timestamps (`started/applied/ready_at_utc`), `validation_summary_*`, top-level `reciter`, and snapshot `matched_text` (derived server-side via `dk_text_for_ref`). Legacy records keep their shape forever; readers tolerate both via pydantic `extra="allow"` + `seg.get("matched_text") or dk_text_for_ref(...)` fall-through. No backfill exists — if storage cleanup of legacy records is ever needed, mirror #3's archive-then-overwrite shape.

### `unignore_category.py` (data fix)
Bulk-reverse `ignore_issue` ops for one `--category` on a reciter by driving `services.segments.undo.undo_ops` (real undo path: audit trail + cache evict + schema-correct `revert` records). Selects segs currently ignored for the category whose origin `ignore_issue` op isn't already reverted. Dry-run default; `--apply` to mutate.

## Migration #5 — peaks slim + pipeline_meta + snapshot stamping

A pipeline-era cluster of changes; the post-#5 invariants are: every history snapshot carries a `chapter` + `audio_url` stamp, and every peaks record on disk uses the slim `peaks_b64` + `bps` shape.

- **`convert_peaks_v2_to_v3.py`** — walks a dir of plain `peaks/<ch>.json` (v2: `schema_version:2`, nested float `peaks`) → emits slim `<ch>.json.gz` siblings (mirrors `services/audio/peaks_slim.py::pack_slim`). Deletes the plain files unless `--keep-legacy`. Runs in a download → migrate → re-upload flow; orphaned plain `.json` on the bucket need a separate delete pass. Peaks shape detail lives in the **inspector-audio skill**.
- **`derive_pipeline_meta.py`** — derives `<dir>/pipeline_meta.json` for a local slug dir. New path: walk `strip_specials` snapshots, collect Basmala-class chapters from the `chapter` stamp. Legacy fallback: pair each Basmala-class op with the next `batch.chapters[]` entry (valid because strip ops emit in chapter+time order). Idempotent modulo `generated_at`.
- **`backfill_deleted_basmala.py`** — same derivation via `qua_shared/pipeline_meta.py::collect_deleted_basmalas` (the helper extraction calls — byte-identical), writing the `deleted_basmala_chapters` sidecar field for legacy reciters. The post-#5 inspector reads this sidecar instead of re-deriving from `edit_history.jsonl` on every cold validate. `--slug` / `--all --dry-run`. Deterministic — re-run as a drift check.
- **`backfill_pipeline_peaks.py`** — catch-up when `edit_history_peaks.jsonl` drifts from `edit_history.jsonl` (partial migration / manual mutation / pre-#5 reciter). Assumes the #5 invariants — if unmet, fix source data (`.local/extraction/scripts/migrate_wip5_in_place.py`) or re-extract rather than adding fallbacks here.

## Source of truth for byte shapes

All these scripts read/write through the shared pydantic schemas in `qua_shared/schemas/` (and `qua_shared/pipeline_meta.py` for the sidecar) — never dict literals. Extraction and the inspector save flow stamp the same fields natively, so new reciters land pre-migrated and only legacy / archive-restored data needs a backfill pass.
