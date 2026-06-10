# Timestamps subsystem (format + read-path + generation job)

Two coupled surfaces: the **temporal segment-array format** the Timestamps tab serves, and the **admin-triggered HF Job** that generates it. Audio internals (peaks, Xing, VBR) live in the `inspector-audio` skill; this doc owns the timestamps shard format + the job lifecycle.

## 1. Format — temporal segment-array shards

Per-chapter shards live at `reciters/<slug>/timestamps/<chapter>.json.gz` (gzipped). The bucket gz body **is the wire body** — the read path is a byte pass-through (no inflate/reshape/recompress on serve). One canonical artifact — no single-file `timestamps_full.json` / `timestamps.json` is written.

A shard is a flat `segments[]` array in recitation order, every accepted segment stored **raw** (re-recitations + within-pass loopbacks retained verbatim — recitation truth). Dedup is not applied at write; it is a consumer-side projection (§1a).

```jsonc
{
  "_meta": { "schema_version": 2, "chapter": 1, "audio_category": "by_surah",
             /* aligner provenance: padding, beam, method, aligner_model,
                shared_cmvn, audio_source, created_at */ },
  "segments": [
    { "ref": "1:1", "t": [start_ms, end_ms],
      "words": [[widx, start_ms, end_ms, [[char,s,e]...], [[phone,s,e]...]], ...] },
    ...                                  // recitation order == array order (sortable by t[0])
  ]
}
```

- **`ref` is always a single verse** `"surah:ayah"`. Cross-verse refs cannot be expressed; the job blocks on them upstream (§3) so the bucket never carries one. `_meta` is slim — `reciter` (it's the path) and `url_template`/`audio_urls` (catalog + audio-manifest sidecar are ground truth) are excluded.
- **Word shape** (per segment): `[widx, start_ms, end_ms, [[char,s,e]...], [[phone,s,e]...]]` — letters/phones nested per word.

| Concept | What |
|---|---|
| `build_raw_v2()` | `qua_shared/timestamps_dedup.py` — in-memory unfiltered v2 occurrence doc from MFA results (every accepted segment its own occurrence; no skip, no merge). Feeds the segment-array builder; never written to the bucket. |
| `build_segment_shards()` | `qua_shared/timestamps_shards.py` — flattens the `build_raw_v2` doc into per-chapter `{_meta, segments[]}` shards (one segment per occurrence, verbatim, sorted by `time_start`). Rejects compound cross-verse / `_transitions` keys. The **single** segment-array builder — both the offline writer and the one-off reshape (§6) converge on it, so a reshaped shard is byte-shape identical to a freshly-generated one. |
| `gzip_shard()` | Same file — deterministic `gzip(level=6, mtime=0)` so unchanged input → byte-identical output. |
| `_normalize_from_results` | `qua_shared/timestamps_pipeline.py` — the one conversion core `build_raw_v2` reuses (so the occurrence shape can't drift from what the pipeline produces). |

### 1a. Consumer-side dedup — `project_segment_shard()`

The bucket is recitation truth (every segment raw); a single canonical take per verse is a **pure projection** consumers apply (releases, the HF dataset, and conceptually the default per-verse clip). `project_segment_shard(shard)` in `qua_shared/timestamps_dedup.py` returns `{ref: {words, verse_start_ms, verse_end_ms}}`:

> Group a verse's segments into **occasions** (maximal runs adjacent in the chapter timeline with no other verse interleaved). Within an occasion accumulate word coverage in time order — within-pass backward loops retained verbatim — and the occasion **completes** when coverage first reaches `{1..N}` (N = max widx across the verse's segments). Canonical clip = the segments around the completing one, with **both** a **leading false-start** (an abandoned prefix before a segment that restarts at word 1 whose run still covers the whole verse) and **trailing** post-completion redundancy trimmed; the middle of audio is never cut. Among multiple completing occasions, pick the **earliest** (first recited); fall back to the **widest-coverage** occasion when none complete. Drop non-canonical occasions.

A leading/trailing repeat (the reciter restarts the verse) is deduped; a within-pass backward **lookback** (a jump back to a non-first word) is recitation truth and kept verbatim. The TS-tab read path serves segments raw — the same `project_segment_shard` shape feeds the FE's per-verse default clip (`occasion-dedup.ts` mirror) and the release/dataset adapters, so they cannot drift at the dedup layer.

## 2. Read-path — byte pass-through

`inspector/services/reference/timestamps.py` serves shards; `inspector/services/storage/data_dir.py` reads them from the bucket.

| Step | Behavior |
|---|---|
| `read_timestamps_chapter_gz(slug, ch)` | Reads `timestamps/<ch>.json.gz` and returns it **uninflated** — the gz body is exactly the wire body. (`read_timestamps_chapter` inflates it for callers wanting JSON bytes; the serve path never does.) |
| `_load_bucket_shard(reciter, ch)` | LRU lookup → `read_timestamps_chapter_gz` → cache → return. No inflate, no reshape, no recompress. The LRU keeps chapter scrubbing within one reciter from re-paying the bucket fetch. |
| `shard_bytes(slug, ch, allow_unreleased)` | Released-gate via `_served_slugs`; `allow_unreleased` bypasses it for owner preview. Returns the raw gz body. |
| Route `GET /api/ts/shard/<reciter>/<int:chapter>` | Streams the gz body with a 24h `Cache-Control`. Sets `allow_unreleased = can(user, "timestamps.view_unreleased")` so an **owner** can preview generated-but-unreleased shards (released stays public, anonymous unchanged). |

**Owner preview:** capability `timestamps.view_unreleased` (owner-only default, `qua_shared/schemas/config/capabilities.py`) lets the Timestamps tab render an under-review reciter's generated shards before release. The shard route honors it by URL; the manifest is still released-only.

## 3. The generation job

Admin launches it from the Releases tab's in-row **Generate / Regenerate** expand (§4). It runs MFA in-container and writes segment-array `.json.gz` shards back to the inspector bucket. The gitignored acoustic **model** is always pulled from the private `aligner-bucket` (`/aux`), never baked into an image.

**Image (`INSPECTOR_JOB_IMAGE`, two modes — `_job_command()` picks the command):**
- **Prebuilt (default)** `hf.co/spaces/hetchyy/quran-ts-job` — a Docker Space (`.local/quran_ts_job/Dockerfile`) that bakes the open-source MFA framework + pip deps into `/env`. No ~300 MB conda solve per launch (job ~80-100 s vs ~3-5 min). Command: `conda run -p /env … generate_timestamps.py`. Runs as **root** (a non-root `USER` gets EACCES writing the `/data` bucket mount).
- **Bootstrap (rollback)** `condaforge/mambaforge:latest` + `INSPECTOR_JOB_IMAGE_BOOTSTRAP=1` — runtime `mamba install montreal-forced-aligner` + pip, then the entrypoint. The original strategy A.

> The job image **must be public**: HF Jobs cannot pull a *private* Space image — `hf.co/spaces/…` 500s at submission, `registry.hf.space/…` 401s at pull (the `HF_TOKEN` secret is in-container only, not image-pull auth). The image holds only open-source software; the model stays bucket-mounted, so public is safe.

### Launch (`inspector/services/admin/timestamps_jobs.py`)

| Piece | Detail |
|---|---|
| `launch(slug, *, settings: TsJobSettings)` | Stages `scripts/{lib,jobs}` → `aligner-bucket/code/`, then `run_job()` (image `JOB_IMAGE`, command `_job_command()`, flavor `cpu-upgrade` default, mounts inspector bucket rw at `/data` + `aligner-bucket` ro at `/aux`, label `{task: timestamps, reciter: slug}`). |
| **Canonical job id** | `run_job()` returns a **transient** id ≠ the container's injected `JOB_ID`. `_resolve_launched_job_id(slug)` resolves the real id from `list_jobs()` by label so the launcher link + the job's self-written record agree. (Verified: a run showed `…e80a` from `run_job` vs `…880b` canonical.) |
| Linkage | Appends the canonical id to `delivery_states.timestamps_job_ids` via `state.record_timestamps_job` — **no lifecycle transition** (reciter stays UNDER_REVIEW). |
| Single-flight | `running_job_for(slug)` rejects a 2nd in-flight job (two would race the same `timestamps/` shards). |

### Entrypoint (`qua_jobs/generate_timestamps.py`)

Env-driven. **Alignment-only** — the job never persists audio nor bakes peaks (both are populated offline by katana extraction). Reads `detailed.json` from the mount; **blocks before any alignment** if any saved segment carries a compound cross-verse `matched_ref` (`_find_cross_verse_segments` → records the failure + notifies, so the offending segs surface in the Reviews tab) — the segment-array shard requires single-verse refs. Otherwise injects per-chapter audio source — **bucket `audio/<ch>.mp3` first, CDN manifest URL fallback (transient, streamed)** — then runs `process()` (in-container MFA, `WORKERS` default `min(cpu_count, 8)`; higher OOMs at simultaneous KalpyEngine model-extraction). On success `build_raw_v2` → `build_segment_shards` (§1) writes one `{_meta, segments[]}` shard per chapter.

| Env | Effect |
|---|---|
| `SLUG`, `BEAMS`, `WORKERS`, `BATCH_SIZE`, `DOWNLOAD_WORKERS`, `PADDING`, `METHOD` | Pipeline tunables. `BEAMS` = `[alignment, *probe]`; canonical = max. The probe beams feed the verse-level `ts_validation.json` sidecar (§3b), not per-beam shards. |
| `CHAPTERS=5,12` | **Affected-only regen.** Scopes the run to those surah numbers (`process(refresh_chapters=…)`) — only those chapters download + align + re-emit shards; untouched shards stay on the bucket. The whole-reciter `ts_validation.json` is **merged** (`_merge_ts_validation`), keeping non-refreshed chapters' flags. Absent = full reciter. Set by `launch` from `TsJobSettings.chapters`; the Releases-tab Regenerate expand defaults to the chapters edited since the last generation (`ts_staleness.ts_stale_info`). |
| `JOB_ID` (HF-injected) | Self-writes the durable record at completion/failure (§3a). |

**Audio + peaks are out of scope for this job.** Chapter audio (`reciters/<slug>/audio/`) and waveform peaks (`reciters/<slug>/peaks/`) are written offline by katana extraction (`upload_to_bucket.py`). Their completeness is verified offline, not surfaced in-app — the Releases status route no longer probes bucket dirs per reciter (that per-row `list_dir` cost was removed; it never gated generation or publishing).

### 3a. Durable job record — `reciters/<slug>/jobs/ts/<job_id>.json`

Per-reciter, colocated with the reciter's other content (consistent with the bucket convention — everything for a reciter under its folder). Schema `qua_shared/schemas/bucket/ts_job_record.py` (`TsJobRecord` + `TsJobSettings`, codegen'd to FE types). Makes a run's settings + status + logs viewable any time after HF log retention expires.

| Writer | When |
|---|---|
| `launch()` `_write_job_record` | At launch — `status="running"` stub. |
| Job `_write_record` | On completion/failure — final status + settings (self-writes under `JOB_ID`, **no logs**). |
| `job_status()` backstop | On terminal HF status, backfills **idempotently**: sets the terminal status if the record still says `running`/`unknown`, **and** writes the captured log tail whenever the record has no logs (the job self-write omits them, so a `succeeded` record would otherwise stay logless — the original "history shows no logs" bug). |

`read_job_record(slug, job_id)` / `list_job_records(slug)` read these back (falling back to the legacy top-level `jobs/ts/<id>.json` for pre-move records). The Past-jobs expand also backfills a past run's logs via `job_status` on open if its record has none (job finished while the expand was closed).

### 3b. Verse-level validation — `reciters/<slug>/ts_validation.json`

The probe (narrower) beams no longer write per-beam `<ch>.beam_<N>.json` sidecar shards. Instead the run emits **one** verse-level sidecar — the analogue of the segment-level `low_confidence_v2.json`, but flagging **verses** rather than segments.

| Piece | Detail |
|---|---|
| `build_ts_validation(chapters, results_by_beam, beams, …)` | `qua_shared/timestamps_pipeline.py` — a verse passes under beam `b` when every segment mapping to it aligned (`status=="ok"`); a verse is flagged when it fails under ≥1 beam it was tested under. Output: `{"_meta": {beams, canonical_beam, …}, "verses": {key: {failed_beams, min_passing_beam}}}`. Single-beam run → empty `verses`. |
| Schema | `qua_shared/schemas/bucket/ts_validation.py` (`TsValidationDoc`/`Meta`/`Verse`, codegen'd to FE types). Written as a plain dict by the pipeline (runs in-job, no pydantic dep); the models are for readers + FE. |
| Serve | `ts_serve.ts_validation_doc(reciter, allow_unreleased)` reads it, same released/`view_unreleased` gate as shards. Route `GET /api/ts/validation/<reciter>` → `{_meta, verses}` (empty doc when viewable-but-absent; 404 when not viewable). |
| Render | Timestamps-tab `TsValidationPanel.svelte` (owner preview) — a Low-Confidence-v2-style expandable accordion; clicking a flagged verse jumps the cascade to it. Fetched lazily on reciter change, **gated FE-side on `view_unreleased`** so public users never trigger the bucket read. Store `tabs/timestamps/stores/validation.ts`. |

## 4. Releases-tab UI (generation + regeneration)

TS generation + regeneration are unified in the **Releases** tab as a compact in-row expand (no drawers, no modal). The same surface drives both first generation (Ready-to-generate rows) and regeneration (any row with existing timestamps). See [admin-dashboard.md](admin-dashboard.md) for the full Releases compartment.

- **`ReleasesTsSettings.svelte`** (the `ts` expand) — beam (default 50) + probe (default 2); collapsible **Advanced** (workers/flavor/timeout); the Full-vs-Affected scope chooser folds inline when the row has affected chapters. **No persist-audio/gen-peaks toggles** (the job is alignment-only). Launch → `generateTimestamps(slug, settings)`; 409 single-flight surfaced inline. On success the row's expansion switches to the Past-jobs view.
- **`ReleasesPastJobs.svelte`** (the `jobs` expand) — `fetchTsJobRecords` history + a live `visiblePoll` on `GET /api/admin/reciters/<slug>/jobs/<job_id>` while a launched job runs; on terminal success it triggers a status refetch so the row re-buckets. Clicking a past run loads `GET …/jobs/<job_id>/record` and renders its persisted logs read-only.

API client `lib/api/admin-reviews.ts`: `generateTimestamps`, `fetchJobStatus`, `fetchJobRecord`, `fetchTsJobRecords`. `TimestampsJobSettings` carries `beam` + `probe_beams` + optional `chapters` + Advanced (no audio/peaks fields).

## 5. Routes (`inspector/routes/admin/reviews.py`, all `@require_capability("reviews.generate_timestamps")`, maintainer+)

| Route | Purpose |
|---|---|
| `POST /api/admin/generate-timestamps/<slug>` | Launch. Body → `_parse_ts_settings` → `TsJobSettings`. 202 `{job_id, url}`; 409 if running; 400 invalid; 404 unknown slug. `@require_same_origin`. |
| `GET /api/admin/reciters/<slug>/jobs/<job_id>` | Live status + bounded log tail (HF authoritative). Reciter-scoped — the record lives under `reciters/<slug>/jobs/ts/`, so the slug is needed to read/backstop it. |
| `GET /api/admin/reciters/<slug>/jobs/<job_id>/record` | Persisted record (settings + status + full logs); 404 if none. |
| `GET /api/admin/reciters/<slug>/ts-jobs` | Persisted records for the slug (newest first). |

`GET /api/ts/validation/<reciter>` (`inspector/routes/timestamps/timestamps.py`) serves the verse-level `ts_validation.json` (§3b), gated by `timestamps.view_unreleased` like the owner shard preview.

## 6. One-off reshape (occurrence-list → segment-array)

The 10 already-released reciters' shards predate the segment-array format — they are the historical v2 occurrence-list (`{_meta, "<verse>": [occurrence,...]}`). They are migrated in place by a **reshape** (NOT a regeneration — no MFA re-run): flatten occurrences by `time_start` into the segment array. The prod-bucket audit (`.local/ts_migration_audit/`) verified all 10 are reshape-safe (clean v2, 0 cross-verse, 0 skips/orphans, every verse coverable), and the reshape converges on the SAME `build_segment_shards` the writer uses, so a reshaped shard is byte-shape identical to a regenerated one.

| Piece | Detail |
|---|---|
| `qua_shared/timestamps_reshape.py` | Pure transform — `classify_shard(shard)` (`target`/`v2`/`v1`/`empty`; `target` = already segment-array, detected by the top-level `segments` key) + `reshape_shard(shard)` (delegates to `build_segment_shards`; raises on compound cross-verse or non-single-chapter input). No Flask, no bucket I/O. |
| `qua_jobs/reshape_timestamps_shards.py` | Thin CLI. `--src-dir` of local `<chapter>.json.gz` shards (e.g. the audit cache `.local/ts_migration_audit/raw/reciters/<slug>/timestamps`); dry-run reports per-shard shape/segment-count/byte delta; optional `--out-dir` writes reshaped `.gz` locally; also reports a **delete-list** of stale shadowed `<chapter>.json` (the `mishary`/`minshawi`/`qatami` uncompressed shards next to a live `.gz`). It **never reads or writes the bucket** — the actual bucket reshape/write/delete is a deferred coordinated cutover (dev bucket first, then prod). |

See `docs/reference/data-migrations.md` and `docs/planning/ts-segment-array-migration.md`.

## Key files

- Format: `qua_shared/timestamps_shards.py` (`build_segment_shards`, `gzip_shard`), `qua_shared/timestamps_dedup.py` (`build_raw_v2`, `project_segment_shard`), `qua_shared/timestamps_pipeline.py` (`_normalize_from_results`); tests `qua_shared/tests/test_timestamps_segment_shards.py`, `test_segment_shard_dedup.py`, `test_timestamps_dedup.py`
- Reshape: `qua_shared/timestamps_reshape.py`, `qua_jobs/reshape_timestamps_shards.py`, tests `qua_shared/tests/test_timestamps_reshape.py`
- Read-path: `inspector/services/reference/timestamps.py`, `inspector/services/storage/{data_dir,storage_paths}.py`, `inspector/routes/timestamps/timestamps.py`
- FE consumption: `inspector/frontend/src/lib/recitation-data/ts-source.ts` (`TsShardResponse = {_meta, segments[]}`; `assembleVerseFromShard` / occasion grouping)
- Job: `inspector/services/admin/timestamps_jobs.py`, `qua_jobs/generate_timestamps.py`, `qua_shared/schemas/bucket/ts_job_record.py`
- ts-validation: `qua_shared/timestamps_pipeline.py::build_ts_validation`, `qua_shared/schemas/bucket/ts_validation.py`, `inspector/frontend/src/tabs/timestamps/{components/TsValidationPanel.svelte,stores/validation.ts}`
- Job image: `.local/quran_ts_job/Dockerfile` (public Docker Space `hetchyy/quran-ts-job`)
- UI: `inspector/frontend/src/tabs/dashboard/components/admin/releases/{ReleasesTsSettings,ReleasesPastJobs,ReleasesRowExpansion}.svelte`, `lib/api/admin-reviews.ts`
- Capability: `reviews.generate_timestamps` (maintainer+), `timestamps.view_unreleased` (owner) — `qua_shared/schemas/config/capabilities.py`
- Planning (the *why*): `docs/planning/inspector-deploy/v2/phases/13-timestamps-job.md`
