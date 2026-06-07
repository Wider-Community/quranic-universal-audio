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

Every adapter starts from the same bucket inputs. The bucket per-chapter shard stores every
recited segment **raw** (temporal segment-array shape — see [timestamps-job.md](timestamps-job.md));
the single canonical take per verse is a pure projection
([`project_segment_shard`](../../qua_shared/timestamps_dedup.py), completion-based occasion dedup).
Both release adapters call that one projection, so the TS-tab read path and the release/dataset
adapters cannot drift at the dedup layer.

## Release ledger (SQLite — migration `0014_releases.sql`)

Workflow state (`WIP → REVIEW → READY → released`, see [state-machine.md](state-machine.md)) is
separate from publish status. Publish status lives in three tables, all written by the Inspector
(single writer) inside a `durable_transaction`; the HF Jobs only ever READ the bucket DB.

| Table | Grain | Purpose |
|---|---|---|
| `per_recitation_releases` | one current row per `(track, slug)`, `track ∈ {ts, hf}` | TS-gen + HF-dataset push history per reciter. Partial-unique on `(track, slug) WHERE superseded_at IS NULL`. |
| `gh_releases` | one row per **cut** | Global GH release snapshot: `version`, `produced_at`, `external_uri`, `validation_summary`, `superseded_at`. |
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
2. Per reciter: reads every segment-array `timestamps/<ch>.json.gz` shard and projects the canonical
   verse map (`_load_canonical_verses` → `project_segment_shard`, the earliest completing occasion)
   → builds the three
   tier files (verse/word/letter, top-down), `catalog.json`, a per-recitation `manifest.json`; packs
   a deterministic `<slug>.zip`; computes `content_hash = SHA-256(letter_tier.gz || catalog.json)`.
   `catalog.json` is built from `catalog/audio_manifest/<slug>.json::chapters`; a GH-eligible
   recitation with no usable audio URLs is fatal.
3. Classifies each reciter `added` / `refresh` / `unchanged` (vs prior `content_hash`) and computes
   the version (below).
4. Builds the dataset-level `manifest.json`, `catalog.json`, and `CHANGELOG.md` (the release body — see
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
├── catalog.json          # dataset-level: reciter rows with audio URLs paired to timestamps
├── shard.py              # consumer helper (per-surah file splitter)
├── check_updates.py      # consumer helper (per-reciter update check)
├── surah_info.json       # static reference
├── qpc_hafs.json         # static reference (mushaf text)
├── letter_vocab_hafs_qpc.csv  # letter-tier char alphabet (42 tokens): char,codepoint,name
└── LICENSE               # CC-BY-4.0
```

Each `<slug>.zip` contains:

```
verse_timestamps.json.gz   # tier 1: "surah:ayah": [start_ms, end_ms]
word_timestamps.json.gz    # tier 2: + [[widx, start, end], ...]
letter_timestamps.json.gz  # tier 3: + [[widx, char, start, end], ...]
catalog.json               # this reciter's catalog projection (carries audio chapter_urls)
```

The zip carries no per-reciter `manifest.json`: zip integrity is the release-level `manifest.json`'s
per-zip `sha256`, and the in-zip `catalog.json` already self-identifies the reciter (`slug`). Only
the release-level `manifest.json` exists.

Each tier self-contains the level below; all times are relative to the matching source audio in
`catalog.json`; all ship the canonical (deduplicated) take. The three `.json.gz` layers keep storage,
startup speed, and network transfer cheap: download verse, word, or letter detail independently.
Use `shard.py` when an app prefers local per-surah files. There is no per-reciter `README.md`.

**Letter-tier `char` alphabet.** Internal shards (`reciters/<slug>/timestamps/<ch>.json.gz`)
carry a 57-token grapheme alphabet (haraka stripped upstream, but the maddah mark and madd
composites retained). At publish time **both** `cut_release` and `publish_hf` map each `char`
through `qua_shared/letter_vocab.to_external_char`, which drops the maddah mark (`U+0653`) to
yield a stable **42-token** external alphabet — a non-lossy, prolongation-only collapse (no two
distinct letters merge). The mapping is **fail-loud**: an unknown token aborts the cut so a new
riwayah/orthography is caught rather than silently shipped. The alphabet is published as a flat
`char,codepoint,name` CSV at `letter_vocab_hafs_qpc.csv` (release root + the HF dataset repo) —
the riwayah/script are in the *filename* so a future riwayah adds its own file
(`letter_vocab_warsh_qpc.csv`, …); the tokenization rule lives here + in the release notes.
Generated from the same module so it cannot drift from the emitted data. Internal shards and the
Inspector animation are unchanged. See `qua_shared/letter_vocab.py`.

### Audio policy (as-built)

Audio is **not** bundled. `catalog.json` carries `audio.chapter_urls` (the upstream/source URLs the
recitation actually serves) plus codec/bitrate/sample-rate/channels meta; consumers fetch audio
from those URLs and read timestamps relative to those exact files. The fuller
`redistribution_policy` registry (cdn_link / embedded_consent /
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

The release body is rendered from
[`docs/templates/release_body.md`](../templates/release_body.md) by
[`render_changelog`](../../qua_shared/release_changelog.py), called by BOTH the cut job (the body
POSTed to GitHub) and the cut-modal preview endpoint. The template uses fixed `{{ placeholders }}`
only; no template dependency. The text stays human-editable, while the renderer owns the generated
asset table, change tables, examples, and links.

Format (display names only — never slugs):

- Title `# {date}`. GitHub already shows the tag above the body.
- First visible section: `## What to download` asset table.
- Short guide sections for audio/timestamp pairing, timestamp levels, recitations, and
  programmatic use.
- `<details>` **Reciter zip schemas**: verse/word/letter timestamp shapes plus a small example.
- `<details>` **Catalog and manifest schemas**: release-level `manifest.json` and `catalog.json`.
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
| `POST /api/admin/cut-release` | Launch the global cut. `release.cut_gh`. Body accepts only `version` and `expected_version_at_preview`; echoes the preview version to 409 stale state. |
| `POST /api/admin/publish-hf/<slug>` | Launch per-reciter HF dataset publish (single). `release.publish_hf`. |
| `POST /api/admin/publish-hf-batch` | Launch ONE job publishing a batch of slugs. Body `{slugs: [...]}`. `release.publish_hf`. |
| `POST /api/admin/release-jobs/<job_id>/cancel` | Cancel any in-flight release job (publish / batch / cut / timestamps). Outer gate `reviews.view`; the cancel itself is re-gated per kind. |

### Batch publish (the `hf_publish_batch` kind)

`publish-hf-batch` launches one HF Job running
[qua_jobs/publish_hf_batch.py](../../qua_jobs/publish_hf_batch.py), which loops
[`publish_hf.publish_slug`](../../qua_jobs/publish_hf.py) over each slug (one slug failing never
aborts the batch) and re-renders the dataset catalog/card **once** at the end. The job:

1. writes a durable batch record to `jobs/_global/hf_publish_batch/<job_id>.json`
   (`{completed_at, members:[{slug, status, version, external_uri, error}]}`), then
2. POSTs `/api/webhooks/hf-publish-batch-complete` →
   [`services.admin.jobs.hf_publish_batch.complete()`](../../inspector/services/admin/jobs/hf_publish_batch.py),
   which calls the single-publish `hf_publish.complete()` per **succeeded** member (idempotent
   `per_recitation_releases(track='hf')` insert + `released` event) and leaves failures in the
   record. The 120 s poll fallback reconciles by reading the same record (no webhook payload).

Global single-flight: one batch at a time; a single publish or a cut is rejected while a batch is in
flight, and vice-versa (labels `task=hf_publish_batch`, `reciter=_batch`).

`GET /api/admin/releases/status` reads the newest batch record and derives **failed** slugs (a
failure clears once a current `hf` release lands at/after the batch). The status payload adds
`recitations[].publish_error` (per-row, → the FE "Failed to publish" bucket) and a top-level
`last_batch {job_id, at, published_count, failed_count}` (→ the dismissable summary banner). In-flight
job entries carry `url` for the FE "Open on HF" link; cancel is the generic route above.

The Releases tab is **select-only**: publishable rows (waiting / stale / failed / published) carry a
checkbox; a sticky action bar publishes the selection as one batch (a single selection = a batch of
one). There are no per-row publish buttons. In-flight rows show a minimal status (badge + elapsed +
Open-on-HF + Cancel); the global cut/batch job surfaces the same in the summary card strip.

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

### Dataset catalog config

HF config `mushafs`, split `all`, is the dataset catalog projection. It is rebuilt by
[`qua_shared.hf_dataset_catalog`](../../qua_shared/hf_dataset_catalog.py) from the Inspector SQLite
`ReciterCatalog` v2 and pushed by the active admin HF publish job after a recitation split lands.

Grain is one published delivery row. Rows include delivery slug, reciter identity,
readable riwayah/style/channel labels, audio metadata, duration, and HF-publish timestamps
(`published_at` = first publish, `updated_at` = last publish/refresh, from
`per_recitation_releases(track='hf')`) — see `CATALOG_COLUMNS`. Admin lifecycle / publish-ledger
fields, the internal release-gating signal `gh_release_eligible`, the niche `variant_label`, and the
upstream `source` label all stay out of the public dataset. The underlying
`Channel.gh_release_eligible` / `Delivery.variant_label` / `Delivery.source` fields remain in the
catalog — they drive GH release-cut eligibility and admin UI, just not the public projection.

This is separate from GitHub release `catalog.json`: the release artifact pairs timestamp tiers with
source audio URLs for offline consumers, while the HF `mushafs` config is a parquet catalog for
dataset discovery and filtering.

### Dataset card (README) — rendered at release time

The dataset card is not uploaded verbatim. [`docs/templates/hf_dataset_card.md`](../templates/hf_dataset_card.md) is a
**template** with `{{configs}}` (frontmatter) and `{{recitations}}` / `{{riwayat}}` / `{{hours}}`
(header badges) placeholders. On each publish, `_sync_dataset_catalog_and_card` enumerates the actual
hub splits once via `hub_published_splits_by_config` (the just-pushed split is already present;
`mushafs`/`segments`/`timestamps` excluded), then `render_dataset_card` builds the `configs:` block
(one `config_name` per riwayah + `mushafs`/`all` last) and fills the badges from the same
`HfDatasetCatalogStats` (`_stats_from_published_splits`) used for the `mushafs` projection. So
frontmatter, badges, and catalog stats can't drift from the published set. The GitHub repo README
badges are a separate, broader metric maintained by `update-badges.yml` CI and are unaffected.

### Audio: preserve, don't normalize

Embedded bytes are stream-copied from the bucket Xing-injected chapter master — source codec /
bitrate / sample-rate / channels preserved; slice frame-snapped (≤26 ms earlier than first word,
word timestamps re-based). Consumers resample at load; filter by codec/SR/channels via the
`mushafs` config columns. For full-chapter app playback, prefer the GitHub release assets.

## Dedup semantics — what projection loses / preserves

Bucket stores every recited segment raw (temporal segment array, faithful). `project_segment_shard`
(completion-based occasion dedup — full detail in [timestamps-job.md §1a](timestamps-job.md)) reduces
each verse to its single canonical take; the same projection feeds the TS-tab per-verse clip and the
release/dataset adapters.

| Lost in projection | Preserved |
|---|---|
| A non-canonical occasion's word/letter timestamps (an interleaved re-recitation of the same verse) | The whole verse `{1..N}` — the canonical occasion reaches full word coverage by construction |
| A leading false-start prefix + trailing post-completion redundancy (an abandoned/redundant re-do within the canonical occasion) | Every recited segment in the bucket shard, time-ordered, addressable via `source_url` + offsets |

The projection picks a single **occasion** (maximal contiguous run, no foreign verse interleaved)
that completes word coverage `{1..N}`; within-pass backward **lookbacks** (a jump back to a
non-first word) inside that occasion are kept verbatim, so the canonical row is never missing a widx.
Among multiple completing occasions the **earliest** (first recited) wins; a **leading false-start**
(a restart at word 1 whose run re-covers the verse) and **trailing** post-completion segments are
trimmed. Consumers wanting alternate takes read the raw bucket shards (every segment present).

### Failed-alignment & deletes at publish

`failed_alignment` (recorded in `_meta.mfa_failures`) and `deleted` (filtered at intake) both
collapse to "never reached the bucket shard" — the segment-array shard carries only aligned,
accepted segments. Per-verse, `project_segment_shard` keeps the canonical occasion; if no occasion
reaches full coverage `{1..N}` it falls back to the widest-coverage occasion, and a verse with no
shippable coverage is dropped from both the dataset and the GH tier files (logged for transparency).
Post-mark-ready, only in-verse segments exist (the TS job blocks compound cross-verse refs), so there
are no cross-verse dedup cases.

## Validation at publish

Each artifact runs a fail-blocking validation pass before it is produced; the summary is persisted
to the `gh_releases.validation_summary` / `per_recitation_releases.validation_summary` row.
Block on: pydantic round-trip of all rows; every non-dropped verse has a contributing segment;
`duration_ms == last_word_end - first_word_start`; `word_timestamps` sorted by `start_ms`; dropped
verses ≤ threshold (default 0 for full reciters). Warn on: audio-slice checksum drift; TS-tab vs
dataset-slice parity probe. Boundary checks run at cut time via
[dataset_validation.py](../../qua_shared/dataset_validation.py); fatal violations abort the cut.

## TS-tab vs dataset-row parity

Word timestamps and verse text are identical — both the TS-tab clip and the dataset row reach the
same `project_segment_shard` canonical take over the same raw bucket segments. Audio bytes are a
byte-substring of the bucket chapter (after per-slice Xing if VBR); the dataset slice may start
≤26 ms before the first word (frame snap), with word timestamps re-based. **No intentional drift** —
if they diverge where they should match, it's a bug.

## Event classification

Publish actions fire events into
[activity_classification.py](../../inspector/services/activity/activity_classification.py): the
in-app publish milestone `reciter.published` (TS-gen completion → `released` state) is public on
the rail; `released` / dataset-publish events (HF push + GH cut) are hidden operator infrastructure.
