# Schemas

One schema per file. Each doc covers exactly one storage shape — its DDL or JSON shape, field semantics, write path, validation rules. Two screens or less.

Same convention as the parent reference dir ([`../README.md`](../README.md)): present tense, tables over prose, no rationale (link to planning doc for *why*), audit script catches drift.

## Index

### Source-of-truth stores (Inspector-managed)

| File | Storage | Doc | Phase |
|---|---|---|---|
| `<bucket>/state/reciter_state.sqlite` | private bucket, SQLite WAL | [`state.md`](state.md) | 0 |
| `<bucket>/catalog/reciter_catalog.sqlite` | public bucket, SQLite WAL | [`catalog.md`](catalog.md) | 0 |

The catalog SQLite contains three tables — `reciters`, `audio_sources`, `reciter_aliases`. All documented in [`catalog.md`](catalog.md).

### Append-only logs

| File | Storage | Doc | Phase |
|---|---|---|---|
| `<bucket>/state/audit/<YYYY>-<MM>.jsonl` | private bucket | [`audit-state.md`](audit-state.md) | 0 |
| `<bucket>/catalog/audit/<YYYY>-<MM>.jsonl` | public bucket | [`audit-catalog.md`](audit-catalog.md) | 0 |

### Per-reciter editing files

| File | Storage | Doc | Phase |
|---|---|---|---|
| `<wip>/<slug>/segments.json` | bucket mount | [`segments.md`](segments.md) | 0 |
| `<wip>/<slug>/detailed.json` | bucket mount | [`detailed.md`](detailed.md) | 0 |
| `<wip>/<slug>/edit_history.jsonl` | bucket mount, append-only | [`edit-history.md`](edit-history.md) | 5 (refined here; initial doc Phase 0) |
| `<wip>/<slug>/edit_history_peaks.jsonl` | bucket mount, append-only | [`edit-history-peaks.md`](edit-history-peaks.md) | 0 |
| `<wip>/<slug>/low_confidence_v2.json` | bucket mount, read-only sidecar | [`low-confidence.md`](low-confidence.md) | 0 |

### Per-reciter published files (HF dataset)

| File | Storage | Doc | Phase |
|---|---|---|---|
| `inspector/segments/<slug>/v<n>/segments.json.gz` | HF dataset CDN | [`segments.md`](segments.md) (gz wrapping noted) | 1 |
| `inspector/segments/<slug>/v<n>/detailed.json.gz` | HF dataset CDN | [`detailed.md`](detailed.md) | 1 |
| `inspector/segments/<slug>/v<n>/edit_history.jsonl.gz` | HF dataset CDN | [`edit-history.md`](edit-history.md) | 1 |
| `inspector/segments/<slug>/v<n>/edit_history_peaks.jsonl.gz` | HF dataset CDN | [`edit-history-peaks.md`](edit-history-peaks.md) | 1 |
| `inspector/segments/<slug>/v<n>/low_confidence_v2.json.gz` | HF dataset CDN | [`low-confidence.md`](low-confidence.md) | 1 |
| `inspector/segments/<slug>/CURRENT` | HF dataset (mutable pointer) | [`current-pointer.md`](current-pointer.md) | 1 |
| `timestamps/<slug>/<chapter>.json.gz` | HF dataset CDN | [`timestamps.md`](timestamps.md) | 1 |
| `timestamps_full/<slug>/<chapter>.json.gz` | HF dataset CDN (per-letter timing, optional) | [`timestamps-full.md`](timestamps-full.md) | 1 |
| `segments/<slug>/<chapter>.json.gz` | HF dataset CDN (slim shards for Aligner Space) | [`segments-slim.md`](segments-slim.md) | 1 |
| `manifest.json.gz` (extended) | HF dataset, top-level | [`dataset-manifest.md`](dataset-manifest.md) | 6 |

### Static reference data

| File | Storage | Doc | Phase |
|---|---|---|---|
| `data/audio_catalog.json.gz` | server image | [`audio-catalog.md`](audio-catalog.md) | 1 |
| `<bucket>/access/inspector_roles.json` | HF bucket | [`roles.md`](roles.md) | 0 |
| `data/surah_info.json` | server image | [`surah-info.md`](surah-info.md) | 0 |
| `data/qpc_hafs.json` | server image + HF `_resources/` | [`qpc-hafs.md`](qpc-hafs.md) | 0 |
| `data/digital_khatt_v2_script.json` | server image + HF `_resources/` | [`digital-khatt.md`](digital-khatt.md) | 0 |
| `data/phoneme_sub_costs.json` | server image | [`phoneme-sub-costs.md`](phoneme-sub-costs.md) | 0 |
| `data/{riwayat,sources,styles}.json` | server image (controlled vocab) | [`controlled-vocab.md`](controlled-vocab.md) | 0 |
| `data/.audio_meta.json`, `.audio_durations.json` | server image (caches) | [`audio-meta.md`](audio-meta.md) | 0 |

### Discovery (per-reciter audio source manifests, dev-only — consumed at build time only)

| File | Storage | Doc | Phase |
|---|---|---|---|
| `data/audio/<cat>/<src>/<slug>.json` | repo (build-time input only) | [`audio-source-manifest.md`](audio-source-manifest.md) | 0 |

These are the build-time input to `audio_catalog.json.gz`; not shipped in the deployed image.

## Conventions per schema doc

Every schema doc uses this skeleton:

```markdown
# <Schema name>

One-line purpose.

## Shape

<DDL for SQLite, or JSON example, or JSONL record example>

## Fields

| Field | Type | Required | Notes |
|---|---|---|---|
...

## Write path

Who writes, when, with what semantics. Include atomicity guarantees.

## Read path

Who reads, with what consistency.

## Validation

What `services/<x>.py::_validate*()` checks.

## See also

- Planning doc link
- Related schema docs
```

If a section is empty (e.g. read-only sidecar has no write path), say "n/a — read-only" and move on. Don't fluff.

## Audit (runs in CI on main)

`scripts/lib/verify_reference_docs.py` (lands in Phase 0):

- Every SQLite schema doc's DDL must match the actual `CREATE TABLE` in `inspector/services/{state,catalog}.py`'s schema bootstrap.
- Every JSON schema doc's example must validate against the in-code TypedDict / pydantic model.
- Every file path mentioned in the index above must be referenced by code (or be future-tagged with a phase).

CI fails on drift in main.
