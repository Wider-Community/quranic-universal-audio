# Dataset and releases

The bucket per-reciter folder (`reciters/<slug>/`) is canonical. Two public delivery formats
are adapter-projections of that canonical state: a **GitHub release** (versioned, offline-first)
and an **HF dataset** (parquet, ML-first). A third interactive format (HTTP API) is deferred.

Audio (peaks, proxy, VBR/Xing) lives in the `inspector-audio` skill. Catalog model:
[catalog.md](catalog.md). Lifecycle: [state-machine.md](state-machine.md). TS-tab read path:
[timestamps-job.md](timestamps-job.md). DB substrate + migrations:
[database.md](database.md), [data-migrations.md](data-migrations.md).

> **As-built note.** Releases ship as **one global GitHub release per version** containing every
> currently-eligible reciter as a `<slug>.zip` asset — NOT a per-reciter release tag. The release
> ledger is three tables (migration 0014), not one. This doc describes what the code does today.

## The three artifacts

| Artifact | Lives at | Who reads it | Why it exists |
|---|---|---|---|
| **Bucket canonical** | `reciters/<slug>/` | Internal (TS tab, the cut/publish jobs, future API) | Zero loss, full reproducibility, single source of truth |
| **GH release** | `gh:releases/v{X.Y.Z}` → `<slug>.zip` assets | Mobile apps, offline kiosks, archives | One version-pinned, fully-offline snapshot of all reciters |
| **HF dataset** | `hetchyy/quranic-universal-ayahs` | ML researchers, training, analysis | Parquet-native, queryable, embedded audio |

Every adapter starts from the same bucket inputs; dedup runs in exactly one place
(`_dedup_core` in [timestamps_pipeline.py](../../qua_shared/timestamps_pipeline.py), reached via
[`canonical_occurrence`](../../qua_shared/timestamps_dedup.py) or already-projected when reading
bucket `.json.gz` shards). TS-tab and the release/dataset adapters cannot drift at the dedup layer.

## Release ledger (SQLite — migration `0014_releases.sql`)

Workflow state (`WIP → REVIEW → READY → released`, see [state-machine.md](state-machine.md)) is
separate from publish status. Publish status lives in three tables, all written by the Inspector
(single writer) inside a `durable_transaction`; the HF Jobs only ever READ the bucket DB.

| Table | Grain | Purpose |
|---|---|---|
| `per_recitation_releases` | one current row per `(track, slug)`, `track ∈ {ts, hf}` | TS-gen + HF-dataset push history per reciter. Partial-unique on `(track, slug) WHERE superseded_at IS NULL`. |
| `gh_releases` | one row per **cut** | Global GH release snapshot: `version`, `produced_at`, `external_uri`, `operator_note`, `validation_summary`, `superseded_at`. |
| `gh_release_recitations` | N rows per `gh_releases` | Frozen membership: `slug`, `catalog_snapshot` (JSON), `zip_sha256`, `zip_bytes`, `coverage_ayahs`, `content_hash`, `ts_version`, `change_kind`, `stale_since`. Immutable post-cut. |

- **Supersede, never delete.** A new cut supersedes the prior `gh_releases` current row; a new
  TS/HF row supersedes the prior `(track, slug)` row. History is retained for audit.
- **`stale_since`.** When TS is regenerated for a slug, `repo_releases.stamp_stale_on_ts_regen`
  stamps that slug's current `hf` row AND its membership in the most-recent `gh_releases` as stale
  — surfaced in the Releases tab as "needs re-publish / re-cut". TS regen never auto-unpublishes.
- **Idempotency.** `complete()` handlers no-op when a row already exists for the version
  (`gh_release_by_version` / `release_by_version`), so a webhook retried after a later cut can't
  replay.

Repository: [services/db/repo_releases.py](../../inspector/services/db/repo_releases.py).

## Eligibility gate

A reciter is GH-release-eligible iff its channel has `gh_release_eligible = 1` **and** it has a
current `per_recitation_releases(track='ts')` row. This is a pure DB query (no `git ls-files`).
The same predicate drives the Releases-tab buckets and the cut job's member discovery.

| Action | Eligibility |
|---|---|
| TS gen | `state == READY` + segments saved + `pipeline_meta.json` present |
| HF publish (per-reciter) | current `ts` row (`release.publish_hf` cap) |
| GH cut (global) | ≥1 eligible reciter (`release.cut_gh` cap, owner-only by default) |

## Cut flow (the HF Job)

`POST /api/admin/cut-release` launches an HF Job running
[qua_jobs/cut_release.py](../../qua_jobs/cut_release.py). The job:

1. Reads the bucket DB read-only → eligible reciters + the prior release's membership.
2. Per reciter: projects canonical verses → builds the three tier files (verse/word/letter,
   top-down), `catalog.json`, a per-recitation `manifest.json`; packs a deterministic `<slug>.zip`;
   computes `content_hash = SHA-256(letter_tier.gz || catalog.json)`.
3. Classifies each reciter `added` / `refresh` / `unchanged` (vs prior `content_hash`) and computes
   the version (below).
4. Builds the dataset-level `manifest.json` + `CHANGELOG.md` (the release body — see
   [Changelog](#changelog-the-release-body)).
5. Creates ONE GH release tag via the GitHub REST API and uploads every asset.
6. POSTs the completion webhook → `/api/webhooks/release-cut-complete` →
   [`services.admin.jobs.cut_release.complete()`](../../inspector/services/admin/jobs/cut_release.py)
   inserts the `gh_releases` row + N `gh_release_recitations` rows, supersedes the prior cut, and
   fires `released({track:'gh', version, recitation_count})`.

Global single-flight: only one cut in flight at a time; a publish landing mid-cut is rejected.

### Versioning

Auto-bump from the prior version (operator `RELEASE_VERSION` override always wins):

| Situation | Result |
|---|---|
| First release | `v0.1.0` |
| Any `added` reciter | MINOR bump (`v0.N+1.0`) |
| `refresh` and/or changed static refs only | PATCH bump (`v0.N.P+1`) |
| Nothing changed | error — set `RELEASE_VERSION` to force-cut |
| MAJOR (schema / MFA model change) | manual only — operator supplies `vX.0.0` |

## GH release structure

One release per version; each reciter is a separate `<slug>.zip` asset so the GitHub page shows
per-file sizes and consumers download only what they need.

```
gh:releases/v{X.Y.Z}/
├── <slug>.zip            # one per reciter (see below)
├── manifest.json         # dataset-level: version, per-reciter sha256/bytes/coverage/change_kind, static_refs
├── CHANGELOG.md          # the rendered release body
├── catalog.json          # dataset-level: array of every reciter's catalog row
├── shard.py              # consumer helper
├── surah_info.json       # static reference
├── qpc_hafs.json         # static reference (mushaf text)
└── LICENSE               # CC-BY-4.0
```

Each `<slug>.zip` contains:

```
verse_timestamps.json.gz   # tier 1: "surah:ayah": [start_ms, end_ms]
word_timestamps.json.gz    # tier 2: + [[widx, start, end], ...]
letter_timestamps.json.gz  # tier 3: + [[widx, char, start, end], ...]
catalog.json               # this reciter's catalog projection (carries audio chapter_urls)
manifest.json              # schema_version, release_version, slug, created_at, files{sha256,bytes}
```

Each tier self-contains the level below; all times are source-relative milliseconds; all ship the
canonical (deduplicated) take. There is no per-reciter `README.md`.

### Audio policy (as-built)

Audio is **not** bundled. `catalog.json` carries `audio.chapter_urls` (the upstream/source URLs the
recitation actually serves) plus codec/bitrate/sample-rate/channels meta; consumers fetch audio
from those URLs. The fuller `redistribution_policy` registry (cdn_link / embedded_consent /
internal_only) described in early design is **not implemented** — revisit if embedded-audio
releases become a real requirement.

### `manifest.json` (dataset-level)

```json
{
  "schema_version": 1,
  "release_version": "v0.1.0",
  "created_at": "2026-06-03T10:00:00Z",
  "previous_version": null,
  "recitation_count": 9,
  "static_refs": { "surah_info.json": {"sha256": "...", "bytes": 1234}, "qpc_hafs.json": {"...": "..."} },
  "recitations": {
    "<slug>": { "zip": "<slug>.zip", "zip_url": "...", "sha256": "...", "bytes": 123,
                 "coverage_ayahs": 6236, "content_hash": "...", "change_kind": "added",
                 "ts_version": "..." }
  },
  "license": "CC-BY-4.0"
}
```

## Changelog (the release body)

The release body is rendered by **one shared function**,
[`render_changelog`](../../qua_shared/release_changelog.py), called by BOTH the cut job (the body
POSTed to GitHub) and the cut-modal preview endpoint — so the preview is faithful to what ships.
It is stdlib-only and pure; callers resolve display names + coverage and pass them in.

Format (display names only — never slugs):

- Title `# v{X.Y.Z} · {date}` + a one-line summary (`First release — N recitations.` or
  `Adds A, refreshes R (C carried) over v…`).
- Optional operator note as a blockquote (HTML-neutralised — untrusted free text).
- `<details>` **➕ Added — N** accordion → table `Reciter (name_en — name_ar) | Riwāyah | Style |
  Channel | Coverage`. A `<details>` **↻ Refreshed — N** accordion when present; a `C carried /
  unchanged.` line otherwise.
- `<details>` **📐 Schemas** accordion (verse/word/letter tier layouts + static-refs status).
- Inline `**License:** CC-BY-4.0` + repository / HF-dataset links.

Coverage shows exact **ayahs** at cut time; the DB-only preview shows **surahs** (chapter_count)
because exact ayah coverage is only computed during the cut. Riwayah/style/channel display names
come from the `riwayahs` / `styles` / `channels` vocab tables — `catalog.json` keeps the slug forms
(stable consumer identifiers), the human-facing changelog never shows them.

### Admin routes ([routes/admin/releases.py](../../inspector/routes/admin/releases.py))

| Route | Purpose |
|---|---|
| `GET /api/admin/releases/status` | Per-reciter TS/HF/GH status grid + summary + in-flight jobs (FE buckets). `reviews.view`. |
| `GET /api/admin/release-preview` | DB-only dry-run: change counts, auto-version, rendered changelog. `release.cut_gh`. |
| `POST /api/admin/cut-release` | Launch the global cut. `release.cut_gh`. Echoes `expected_version_at_preview` to 409 a stale preview. |
| `POST /api/admin/publish-hf/<slug>` | Launch per-reciter HF dataset publish. `release.publish_hf`. |

## HF dataset schema

### Per-verse row

| Column | Type | Notes |
|---|---|---|
| `audio` | `Audio` | Verse clip — bytes embedded |
| `surah` | `int32` | 1–114 |
| `ayah` | `int32` | Within surah |
| `duration_ms` | `int32` | first-word-start → last-word-end |
| `text_uthmani` | `string` | What was recited (incl. repetitions); waqf/hizb/sajdah stripped |
| `segments` | `[[int,int,int,int]]` | `[word_from, word_to, start_ms, end_ms]` |
| `word_timestamps` | `[[int,int,int]]` | `[word_idx, start_ms, end_ms]` |
| `letter_timestamps` | `[{word_idx,char,start_ms,end_ms}]` | Empty if unavailable |
| `source_url` | `string` | Chapter/verse audio URL (or `bucket://` when embedded) |
| `source_offset_ms` | `int32` | Offset within `source_url` where the verse starts |

- Audio embedded as bytes (verse-trimmed); `word_idx` is 1-based, may repeat / go backward within a
  verse; `text_uthmani` token count equals `word_timestamps` occurrence count.
- **Subset (config)** = riwayah slug (e.g. `hafs_an_asim`). **Split** = delivery slug. Readability
  comes from `name_en` / `name_ar`, not the split key.

### Audio: preserve, don't normalize

Embedded bytes are stream-copied from the bucket Xing-injected chapter master — source codec /
bitrate / sample-rate / channels preserved; slice frame-snapped (≤26 ms earlier than first word,
word timestamps re-based). Consumers resample at load; filter by codec/SR/channels via the
`reciters` config columns. For the full natural recording, stream from `source_url` directly.

## Dedup semantics — what projection loses / preserves

Bucket stores every accepted occurrence (v2 raw, faithful). The projection
(`canonical_occurrence` / `_repeat_pass_skip_indices`) feeds the TS tab and the release/dataset
adapters.

| Lost in projection | Preserved |
|---|---|
| A losing take's word/letter timestamps when a verse has multiple runs split by a different home verse | Every widx present in the row — the winning run is a superset by the reciter invariant |
| A losing take's audio slice (not in the row's embedded bytes) | All audio in the bucket chapter, addressable via `source_url` + offsets |

**Reciter invariant** (post-mark-ready): a re-pass for verse N covers `[j..m]` with `j ≤ k`,
`m ≥ k` of the prior run's `[1..k]` — the wider-coverage run-picker is non-lossy at the widx level.
Consumers wanting alternate takes use the bucket shards' `?full=true` surface.

### Failed-alignment & deletes at publish

`failed_alignment` (recorded in `_meta.mfa_failures`) and `deleted` (filtered at intake) both
collapse to "not in the valid coverage pool". Per-verse: walk occurrences in `seg_index` order,
pick the widest-coverage run; if it covers every widx 1..N the verse is shippable, else it is
dropped from both the dataset and the GH tier files (logged for transparency). Post-mark-ready,
only in-verse segments are allowed (no cross-verse dedup cases).

## Validation at publish

Each artifact runs a fail-blocking validation pass before it is produced; the summary is persisted
to the `gh_releases.validation_summary` / `per_recitation_releases.validation_summary` row.
Block on: pydantic round-trip of all rows; every non-dropped verse has a contributing segment;
`duration_ms == last_word_end - first_word_start`; `word_timestamps` sorted by `start_ms`; dropped
verses ≤ threshold (default 0 for full reciters). Warn on: audio-slice checksum drift; TS-tab vs
dataset-slice parity probe. Boundary checks run at cut time via
[dataset_validation.py](../../qua_shared/dataset_validation.py); fatal violations abort the cut.

## TS-tab vs dataset-row parity

Word timestamps and verse text are identical (both reach `canonical_occurrence` / `detailed.json`).
Audio bytes are a byte-substring of the bucket chapter (after per-slice Xing if VBR); the dataset
slice may start ≤26 ms before the first word (frame snap), with word timestamps re-based. **No
intentional drift** — if they diverge where they should match, it's a bug.

## Event classification

Publish actions fire events into
[activity_classification.py](../../inspector/services/activity/activity_classification.py): TS
generation is admin-only infrastructure; `released` / dataset-publish events are public.
