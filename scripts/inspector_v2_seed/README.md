# Inspector v2 cutover seed scripts

One-shot scripts that promote the current repo `data/` snapshot into the
v2 layout on `hetchyy/quranic-inspector-bucket-dev` (the dev bucket).

These scripts are **not** part of the runtime Inspector code path —
they run once at cutover and become obsolete the moment the bucket is
the source of truth. Kept under `scripts/` for discoverability and
re-runnability (e.g. after a bucket reset during testing).

## Run order

```bash
# 1. Bootstrap the first OWNER member into <bucket>/access/inspector_roles.json
python -m scripts.inspector_v2_seed.bootstrap_access \
    --hf-user-id <your_hf_user_id> --login <your_hf_login>

# 2a. Seed <bucket>/catalog/reciter_catalog.json with vocab-only stub
#     (run only when the dedup pipeline output isn't ready yet)
python -m scripts.inspector_v2_seed.seed_catalog_stub

# 2b. Promote the real catalog + 864 sidecars from .local/dedup/
#     (preferred — supersedes the vocab-only stub once the dedup artifacts
#     are available in the worktree). Validates through pydantic before
#     uploading; raw-bytes upload preserves the artifact exactly.
python -m scripts.inspector_v2_seed.promote_catalog

# 3. Seed <bucket>/state/reciter_state.json with the 14 existing reciters
#    (6 completed → state="completed", 8 wip → state="awaiting_review")
python -m scripts.inspector_v2_seed.seed_state

# 4. Upload per-reciter data files to <bucket>/{wip,published}/<slug>/
python -m scripts.inspector_v2_seed.seed_reciter_data
```

All four read `INSPECTOR_BUCKET_REPO` (default
`hetchyy/quranic-inspector-bucket-dev`) and `HF_TOKEN` from the
environment (the repo-root `.env`).

## Prereqs

- `HF_TOKEN` with write scope to the bucket namespace.
- `huggingface_hub >= 1.10`.
- The 14 reciter directories present under `data/recitation_segments/<slug>/`
  and timestamps under `data/timestamps/by_*_audio/<slug>/` for the
  completed six.

## Idempotency

- `bootstrap_access` refuses to run if the roles file already has active
  members.
- `seed_catalog_stub` overwrites the catalog file in-place; safe to re-run.
- `seed_state` overwrites the state file in-place; safe to re-run, but any
  in-progress claims will be wiped.
- `seed_reciter_data` uses `batch_bucket_files(add=…)` which is overwrite-
  by-path; re-running re-uploads everything (no diff check).
