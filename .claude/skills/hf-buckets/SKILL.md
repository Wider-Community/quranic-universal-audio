---
name: hf-buckets
description: Reference for Hugging Face Storage Buckets — S3-like mutable Xet-backed object storage at hf://buckets/<owner>/<name>/.
---

# Hugging Face Storage Buckets

S3-like, mutable, non-versioned object storage on the Hub. Backed by Xet (chunk-level dedup). Addressed via `hf://buckets/<owner>/<name>/<path>`.

## When to pick a bucket vs a repo

| Need | Pick |
|------|------|
| Version history, PRs, model/dataset cards, public deliverable | Repo (model/dataset/Space) |
| Mutable storage, overwrite in place, rapid writes, no Git overhead | Bucket |
| Training checkpoints, logs, intermediate artifacts | Bucket |
| Persistent storage attached to a Space | Bucket (mount as volume) |
| Final published artifact for collaborators | Repo |

Buckets have **no PRs, no commits, no cards, no revision argument**. Deletions are immediate and permanent.

## Quick scripts (fast path)

Local CLI wrappers in `scripts/`. Use these before reaching for inline `HfFileSystem` code — each is a self-contained `python <script>` invocation with `--help`. Default bucket is dev (`hetchyy/quranic-inspector-bucket-dev`); pass `--bucket prod` for prod, and add `--yes-prod` for mutating ops.

| Script | What it does |
|---|---|
| `scripts/bucket_ls.py PATH [--detail] [--recursive]` | List dirs/files; sizes when `--detail` |
| `scripts/bucket_stat.py [PATH] [--top N]` | File count + total bytes + per-extension breakdown + top-N largest |
| `scripts/bucket_cat.py PATH [--json] [--gz] [--head N]` | Print contents; auto-gunzip for `peaks/*.json.gz`, JSON pretty-print |
| `scripts/bucket_put.py PATH (--text \| --file \| --json) [--yes-prod]` | Write a single file |
| `scripts/bucket_rm.py PATH [--recursive] [--yes-prod]` | Delete file/dir |
| `scripts/bucket_cp.py SRC DST [--src-bucket B] [--dst-bucket B] [--yes-prod]` | Server-side copy (Xet-dedup) |
| `scripts/bucket_sync.py SRC DST [--dry-run] [--delete]` | Two-way local↔bucket sync, plan-and-apply |
| `scripts/bucket_reciters.py [--sort {slug,size,audio,max}] [--slug FILTER]` | One-row-per-reciter summary table |
| `scripts/bucket_diff.py SLUG [--bucket-a B --bucket-b B]` | What artifacts exist on A but not B for that slug |

Recipe:
```
python .claude/skills/hf-buckets/scripts/bucket_stat.py reciters/mahmoud_khalil_al_husary_mp3quran --bucket prod
python .claude/skills/hf-buckets/scripts/bucket_cat.py catalog/audio_manifest/<slug>.json --json --bucket prod
python .claude/skills/hf-buckets/scripts/bucket_reciters.py --bucket prod --sort audio
```

For **what's inside `reciters/<slug>/`** (which files exist, who writes them, how they're synced) — don't re-derive, open [`docs/reference/database.md`](../../../docs/reference/database.md) (the SQLite-on-bucket substrate + sync mechanics) and the *Bucket shape* section of the repo's root `CLAUDE.md`.

## Reference index

| File | Open when working on |
|------|----------------------|
| `references/cli-and-python.md` | Creating/listing/deleting buckets, uploading or downloading files, the `hf buckets` CLI, `batch_bucket_files` / `download_bucket_files` / `sync_bucket` / `copy_files` / `list_bucket_tree` / `bucket_info` Python APIs, sync filtering and plan-and-apply |
| `references/access-patterns.md` | Reading buckets via `HfFileSystem` / fsspec `hf://buckets/` URIs, mounting a bucket as a local filesystem with `hf-mount` (NFS/FUSE), choosing between sync vs mount vs fsspec |
| `references/jobs-and-spaces.md` | Mounting buckets/datasets/models into HF Jobs (`hf jobs run -v ...`) or HF Spaces (`hf spaces volumes set ...`), the `Volume` Python class, ro/rw defaults per source type, attaching persistence to a Space's `/data` |
| `references/integrations.md` | Library-specific snippets: pandas, Polars, Dask, PyArrow, PySpark (`pyspark_huggingface`), DuckDB (`register_filesystem`), 🤗 Datasets, Zarr, `hffs`, OpenDAL |
| `references/rest-api.md` | Direct Hub HTTP API — 13 bucket endpoints, NDJSON batch contract, paths-info 2000-cap, resolve endpoint Accept-header trick, Xet token exchange, CDN/region/resource-group fields not exposed in the SDK. Open when writing a custom client or hitting endpoints with no Python wrapper (`PUT /settings`, resource-group ops). |

## Always-true essentials

- **Path scheme:** `hf://buckets/<owner>/<bucket>[/<path>]`. Same scheme used everywhere — CLI args, fsspec URIs, volume mount sources.
- **Default permissions on volume mounts:** models and datasets are read-only; buckets are read-write. Append `:ro` to force a bucket read-only.
- **Server-side copy is one-way.** `repo → bucket` and `bucket → bucket` for Xet-tracked files (no re-upload). `bucket → repo` is **not yet supported**.
- **No revisions.** The `revision=` arg in `HfFileSystem` is incompatible with buckets — buckets are mutable, there is no commit.
- **Volume-mount Python API requires `huggingface_hub >= 1.8.0`** (`Volume` class, `run_job(volumes=…)`).
- **Pricing / free tier:** see `hf.co/storage`. Enterprise plans get dedup-based billing (shared chunks reduce billed footprint).
- **S3 protocol:** not yet supported (on roadmap).

## Auth

`hf auth login` for CLI. `HfApi(token=...)` or `HfFileSystem(token=...)` in Python. For HF Jobs, forward your local token with `--secrets HF_TOKEN`. Same token rules as the rest of the Hub.

## Maintenance

These reference files are self-contained — no live URLs are read at runtime. When the HF docs change, refresh the relevant file rather than adding a link. Keep each file under ~300 lines; split when a single file starts mixing concerns (e.g. CLI ops vs Python types).
