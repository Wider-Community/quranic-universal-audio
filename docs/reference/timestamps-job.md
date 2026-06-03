# Timestamps subsystem (format + read-path + generation job)

Two coupled surfaces: the **v2 timestamps format** the Timestamps tab serves, and the **admin-triggered HF Job** that generates it. Audio internals (peaks, Xing, VBR) live in the `inspector-audio` skill; this doc owns the timestamps shard format + the job lifecycle.

## 1. Format — v2 occurrence-preserving shards

Per-chapter shards live at `reciters/<slug>/timestamps/<chapter>.json.gz` (gzipped; the read-path inflates). One canonical artifact — the legacy single-file `timestamps_full.json` / `timestamps.json` are **not written**.

| Concept | What |
|---|---|
| **v2 raw** | Verse-keyed map; each value is a **list of occurrences** (every accepted segment, incl. re-recitations + cross-verse bleed). Compound keys (`"37:151:3-37:152:2"`) for cross-verse segs. |
| **v1 deduped** | The historical verse→single-object shape. Re-recitation runs collapsed (widest-widx-coverage run wins), within-verse stutter kept. **What the Timestamps tab renders.** |
| `build_raw_v2()` | `qua_shared/timestamps_dedup.py` — emits the unfiltered v2 from MFA results. No skip, no merge. |
| `canonical_occurrence()` | Same file — projects a v2 chapter → v1 deduped map. Chapter-level (run detection needs the full ordered seg sequence + `seg_index` + failed segs). |
| `_dedup_core` / `_normalize_from_results` | `qua_shared/timestamps_pipeline.py` — the shared conversion + dedup core both `build_outputs` (fresh) and `canonical_occurrence` (stored v2) call, so the deduped projection can't drift from what the pipeline wrote. Guarded by `canonical_occurrence(build_raw_v2(x)) == build_outputs(x)` in `qua_shared/tests/test_timestamps_dedup.py`. |

**Word shape** (per occurrence): `[widx, start_ms, end_ms, [[char,s,e]...], [[phone,s,e]...]]` — letters/phones nested per word.

## 2. Read-path — dedup on serve, `?full` for raw

`inspector/services/reference/timestamps.py` serves shards; `inspector/services/storage/data_dir.py::read_timestamps_chapter` reads + inflates the `.json.gz`.

| Step | Behavior |
|---|---|
| `read_timestamps_chapter(slug, ch)` | Reads `timestamps/<ch>.json.gz`, gzip-inflates → raw JSON bytes. (Pre-v2 uncompressed `.json` of the 6 already-published reciters are migrated by re-running the job; no read-time fallback.) |
| `_shard_payload(raw, full)` | If the doc is v2: `project_chapter_shard(doc, full=)` — `full=False` dedups to v1 (Timestamps-tab shape), `full=True` serves every occurrence raw. v1 docs pass through unchanged. |
| `shard_bytes(slug, ch, full, allow_unreleased)` | LRU-cached on `(slug, ch, full)`. Released-gate via `_served_slugs`; `allow_unreleased` bypasses it for owner preview. |
| Route `GET /api/ts/shard/<reciter>/<int:chapter>` | `?full=1` → raw occurrences. Sets `allow_unreleased = can(user, "timestamps.view_unreleased")` so an **owner** can preview generated-but-unreleased shards (released stays public, anonymous unchanged). |

**Owner preview:** capability `timestamps.view_unreleased` (owner-only default, `qua_shared/schemas/capabilities.py`) lets the Timestamps tab render an under-review reciter's generated shards before release. The shard route honors it by URL; the manifest is still released-only.

## 3. The generation job

Admin launches it from the Reviews tab's **Generate TS** drawer (§4). It runs MFA in-container and writes v2 `.json.gz` shards back to the inspector bucket. The gitignored acoustic **model** is always pulled from the private `aligner-bucket` (`/aux`), never baked into an image.

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

Env-driven. Reads `detailed.json` from the mount; injects per-chapter audio source — **bucket `audio/<ch>.mp3` first, CDN manifest URL fallback** — then runs `process()` (in-container MFA, `WORKERS` default `min(cpu_count, 8)`; higher OOMs at simultaneous KalpyEngine model-extraction).

| Env | Effect |
|---|---|
| `SLUG`, `BEAMS`, `WORKERS`, `BATCH_SIZE`, `DOWNLOAD_WORKERS`, `PADDING`, `METHOD` | Pipeline tunables. `BEAMS` = `[alignment, *probe]`; canonical = max. The probe beams feed the verse-level `ts_validation.json` sidecar (§3b), not per-beam shards. |
| `PERSIST_AUDIO=1` | For chapters missing from the bucket: download CDN → **Xing-remux** (`ffmpeg -c:a copy -f mp3`, mirrors `audio_persist.py::_ensure_xing`) → write `reciters/<slug>/audio/<ch>.mp3`, and align against the persisted copy. |
| `GEN_PEAKS=1` | `_bake_missing_peaks` computes v3 slim peaks (`qua_shared/peaks_compute.py::compute_audio_peaks` → `pack_slim`) → `reciters/<slug>/peaks/<ch>.json.gz` for any by_surah chapter lacking them (decoupled from `PERSIST_AUDIO` so already-on-bucket audio also gets peaks). |
| `JOB_ID` (HF-injected) | Self-writes the durable record at completion/failure (§3a). |

`qua_shared/peaks_compute.py` is a **config-free** mirror of `inspector/services/audio/peaks.py::compute_audio_peaks` (the job stages only `scripts/`, not Flask `config`); `pack_slim` is re-exported from the pure `peaks_slim`.

**Durability note:** persisted `audio/`+`peaks/` are never GC'd (the wip-audio sweeper was removed) — they persist for the life of the reciter.

### 3a. Durable job record — `reciters/<slug>/jobs/ts/<job_id>.json`

Per-reciter, colocated with the reciter's other content (consistent with the bucket convention — everything for a reciter under its folder). Schema `qua_shared/schemas/ts_job_record.py` (`TsJobRecord` + `TsJobSettings`, codegen'd to FE types). Makes a run's settings + status + logs viewable any time after HF log retention expires.

| Writer | When |
|---|---|
| `launch()` `_write_job_record` | At launch — `status="running"` stub. |
| Job `_write_record` | On completion/failure — final status + settings (self-writes under `JOB_ID`, **no logs**). |
| `job_status()` backstop | On terminal HF status, backfills **idempotently**: sets the terminal status if the record still says `running`/`unknown`, **and** writes the captured log tail whenever the record has no logs (the job self-write omits them, so a `succeeded` record would otherwise stay logless — the original "history shows no logs" bug). |

`read_job_record(slug, job_id)` / `list_job_records(slug)` read these back (falling back to the legacy top-level `jobs/ts/<id>.json` for pre-move records). The drawer also backfills a past run's logs via `job_status` on open if its record has none (job finished while the drawer was closed).

### 3b. Verse-level validation — `reciters/<slug>/ts_validation.json`

The probe (narrower) beams no longer write per-beam `<ch>.beam_<N>.json` sidecar shards. Instead the run emits **one** verse-level sidecar — the analogue of the segment-level `low_confidence_v2.json`, but flagging **verses** rather than segments.

| Piece | Detail |
|---|---|
| `build_ts_validation(chapters, results_by_beam, beams, …)` | `qua_shared/timestamps_pipeline.py` — a verse passes under beam `b` when every segment mapping to it aligned (`status=="ok"`); a verse is flagged when it fails under ≥1 beam it was tested under. Output: `{"_meta": {beams, canonical_beam, …}, "verses": {key: {failed_beams, min_passing_beam}}}`. Single-beam run → empty `verses`. |
| Schema | `qua_shared/schemas/ts_validation.py` (`TsValidationDoc`/`Meta`/`Verse`, codegen'd to FE types). Written as a plain dict by the pipeline (runs in-job, no pydantic dep); the models are for readers + FE. |
| Serve | `ts_serve.ts_validation_doc(reciter, allow_unreleased)` reads it, same released/`view_unreleased` gate as shards. Route `GET /api/ts/validation/<reciter>` → `{_meta, verses}` (empty doc when viewable-but-absent; 404 when not viewable). |
| Render | Timestamps-tab `TsValidationPanel.svelte` (owner preview) — a Low-Confidence-v2-style expandable accordion; clicking a flagged verse jumps the cascade to it. Fetched lazily on reciter change, **gated FE-side on `view_unreleased`** so public users never trigger the bucket read. Store `tabs/timestamps/stores/validation.ts`. |

## 4. Reviews-tab UI

`Generate TS` button on under-review rows → `reviewsStore.open(slug, 'timestamps')` opens `ReviewsTimestampsDrawer.svelte`:

- **Settings form** — beam, probe beams, persist-audio + gen-peaks toggles; collapsible **Advanced** (workers/flavor/timeout). Launch → `generateTimestamps(slug, settings)`; 409 single-flight surfaced inline.
- **Live log pane** — `visiblePoll` on `GET /api/admin/reciters/<slug>/jobs/<job_id>` (status + bounded log tail) while running. Shows a **live elapsed timer** (client-side from launch time / the resumed record's `started_at` — no per-poll bucket read).
- **Job history** — `GET /api/admin/reciters/<slug>/ts-jobs` lists past runs with **total duration** (`ended_at − started_at`); clicking one loads `GET /api/admin/reciters/<slug>/jobs/<job_id>/record` and renders its persisted logs read-only (backfilling logs from HF if the record has none).

API client `lib/api/admin-reviews.ts`: `generateTimestamps`, `fetchJobStatus`, `fetchJobRecord`, `fetchTsJobRecords`. (The old `ReviewsOpsDrawer` is deleted; `ReviewsDrawerKind = 'general' | 'timestamps'`.)

## 5. Routes (`inspector/routes/admin/reviews.py`, all `@require_capability("reviews.generate_timestamps")`, maintainer+)

| Route | Purpose |
|---|---|
| `POST /api/admin/generate-timestamps/<slug>` | Launch. Body → `_parse_ts_settings` → `TsJobSettings`. 202 `{job_id, url}`; 409 if running; 400 invalid; 404 unknown slug. `@require_same_origin`. |
| `GET /api/admin/reciters/<slug>/jobs/<job_id>` | Live status + bounded log tail (HF authoritative). Reciter-scoped — the record lives under `reciters/<slug>/jobs/ts/`, so the slug is needed to read/backstop it. |
| `GET /api/admin/reciters/<slug>/jobs/<job_id>/record` | Persisted record (settings + status + full logs); 404 if none. |
| `GET /api/admin/reciters/<slug>/ts-jobs` | Persisted records for the slug (newest first). |

`GET /api/ts/validation/<reciter>` (`inspector/routes/timestamps/timestamps.py`) serves the verse-level `ts_validation.json` (§3b), gated by `timestamps.view_unreleased` like the `?full=1` shard preview.

## Key files

- Format/dedup: `qua_shared/timestamps_dedup.py`, `qua_shared/timestamps_pipeline.py`, `qua_shared/timestamps_shards.py`, tests `qua_shared/tests/test_timestamps_dedup.py`
- Read-path: `inspector/services/reference/timestamps.py`, `inspector/services/storage/{data_dir,storage_paths}.py`, `inspector/routes/timestamps/timestamps.py`
- Job: `inspector/services/admin/timestamps_jobs.py`, `qua_jobs/generate_timestamps.py`, `qua_shared/peaks_compute.py`, `qua_shared/schemas/ts_job_record.py`
- ts-validation: `qua_shared/timestamps_pipeline.py::build_ts_validation`, `qua_shared/schemas/ts_validation.py`, `inspector/frontend/src/tabs/timestamps/{components/TsValidationPanel.svelte,stores/validation.ts}`
- Job image: `.local/quran_ts_job/Dockerfile` (public Docker Space `hetchyy/quran-ts-job`)
- UI: `inspector/frontend/src/tabs/dashboard/components/admin/reviews/ReviewsTimestampsDrawer.svelte`, `lib/api/admin-reviews.ts`
- Capability: `reviews.generate_timestamps` (maintainer+), `timestamps.view_unreleased` (owner) — `qua_shared/schemas/capabilities.py`
- Planning (the *why*): `docs/planning/inspector-deploy/v2/phases/13-timestamps-job.md`
