# inspector/scripts/

Inspector-coupled operational CLIs — every script here does `from services.*`
(or operates on the inspector bucket/DB), so it lives beside `inspector/` to keep
that package on `sys.path` naturally. These are **invoked**, never imported by the
running app; they are pruned from the deployed image by `.dockerignore`.

Files are **flat** — the name-prefix is the grouping. The only subfolder is
[`migrations/`](migrations/), reserved for frozen one-shot schema moves.

## Where does a NEW script go?

```
Is it IMPORTED by app/job runtime?            → it's a package, not a script:
                                                 qua_shared/ (lib) or qua_jobs/ (job entrypoint)
Does it import inspector internals             → inspector/scripts/   (here)
  (services.*/routes.*) or touch its bucket/DB?   └─ one-shot schema move, never re-applied?
                                                       → inspector/scripts/migrations/  (frozen)
Invoked ONLY by a GitHub Action, touches            otherwise → flat, here
  only repo-root files (no services.* import)?  → .github/scripts/
Its unit of work is the WHOLE repo             → scripts/  (root)
```

When in doubt it's almost always "inspector-coupled, re-runnable" → flat here.
A migration belongs in `migrations/` **only if re-running it on current state is a
no-op-or-error by design** (it assumes the pre-migration shape). Idempotent
`backfill_*`/`convert_*`/`purge_*` tools stay flat.

## Catalogue

**Dev-env & fixtures**
- `bootstrap_dev_env.py` — provision a contributor's personal HF bucket + Space
- `seed_fixtures.py` — download the public fixtures dataset → `.fixtures` (offline tier-0)
- `make_fixtures_dataset.py` — maintainer: (re)build the PII-free public fixtures dataset

**Deploy**
- `deploy_space.py` — deploy the inspector to any HF Space (contributor cousin of root `scripts/upload_inspector.py`)
- `smoke_boot.py` — build the image, boot it on fixtures, assert `/healthz` (CI boot gate)

**Codegen**
- `regen_fe_types.py` — regenerate the FE TypeScript types from `qua_shared/schemas/` (CI-checked)

**Bucket round-trip** (download → migrate → audit → upload)
- `download_bucket_reciter.py` — pull a reciter folder bucket → local
- `audit_bucket_reciter.py` — validate every artefact in `reciters/<slug>/` against `qua_shared.schemas`
- `upload_bucket_reciter.py` — push a migrated local reciter folder back to the bucket

**Backfills / converters** (re-runnable legacy-data catch-up)
- `backfill_boundary_adj.py` · `backfill_qalqala_letter.py` — stamp classifier fields on `detailed.json`
- `backfill_deleted_basmala.py` · `derive_pipeline_meta.py` — derive `pipeline_meta.json` sidecars
- `backfill_peaks_slim.py` · `convert_peaks_v2_to_v3.py` · `rollback_peaks_slim.py` — peaks wire-shape conversion
- `backfill_pipeline_peaks.py` — recompute missing per-op pipeline peaks
- `purge_pad_migration.py` · `purge_stale_wraps.py` — strip stale records from `detailed.json` / `edit_history`
- `unignore_category.py` — bulk-revert `ignore_issue` ops for a category (re-runnable data-fix)

**Diagnostics**
- `bench_storage.py` — benchmark backend read/write hot paths
- `check_eligibility_parity.py` — assert DB-backed eligibility == legacy git-tracked set

**[`migrations/`](migrations/)** — frozen, completed one-shot schema moves (see its README).
