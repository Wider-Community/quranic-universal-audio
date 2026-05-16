# Audio prefetch

Background pipeline that lands every chapter MP3 + waveform peaks on the bucket the moment a reciter is ready for review. Editors hit instant playback + same-time peak rendering; no manual "download all" button.

> **Status note (May 2026):** For newly-extracted reciters, audio + peaks are now produced by Katana at extraction time (`.local/extraction/segments/audio_persist.py`) and uploaded atomically as part of `upload_to_bucket.py --include-audio` — the `_done.json` sentinel lands on the bucket BEFORE Inspector ever sees the row. The in-Flask `audio_prefetch.py` worker described below is kept as a **fallback for legacy reciters** that pre-date this migration. Once every reciter has been re-extracted via the new pipeline, the worker + its triggers + the CDN-streaming branch in `audio_proxy.py` can be deleted in a follow-up migration. See `.claude/skills/segments-extraction/SKILL.md` Stage 9 (Upload) for the Katana-side flow.

## Storage

| Path | Contents |
|---|---|
| `wip/<slug>/audio/<chapter>.mp3` | Prefetched chapter audio. VBR chapters carry an ffmpeg-injected Xing TOC so the browser seeks correctly. |
| `wip/<slug>/peaks/<chapter>.json` | `{duration_ms, peaks}` paired with each MP3. |
| `wip/<slug>/audio/_done.json` | Sentinel written atomically last; presence ⇒ prefetch completed in full. |

Chapter keys follow the audio-manifest sidecar (`"1"`..`"114"` for `by_surah`, `"<surah>:<ayah>"` for `by_ayah`). `by_ayah` deliveries are not prefetched today.

## Triggers

| State transition | Action |
|---|---|
| `* → AWAITING_REVIEW` (`reciter.alignment_completed`, `reciter.released`, `reciter.unpublished`, `claim.force_released`, `admin.force_set_state`, `admin.unlocked_for_revision`) | Enqueue prefetch. Clears any stale `prefetch_purge_at`. |
| `reciter.claimed → UNDER_REVIEW` and sentinel absent | Lazy fallback — enqueue prefetch. |
| `reciter.timestamps_completed → RELEASED` | Stamp `ReciterRow.prefetch_purge_at = now + 7d`. Sweeper deletes after the date passes. |

The post-transition observer lives in `inspector/services/state/state.py::register_transition_hook` and is wired by `inspector/app.py::_hydrate_bucket_stores` at boot.

## Queue + worker

`inspector/services/audio_prefetch.py` owns one daemon thread and a single FIFO queue. Max one slug runs at a time; per-slug fan-out uses `ThreadPoolExecutor(max_workers=AUDIO_DL_WORKER_COUNT)`. Enqueue is idempotent: a slug already active or queued is a no-op.

Per-chapter pipeline (`inspector/services/audio_fetch.py::fetch_and_persist_chapter`):

1. HTTP-stream the upstream URL → temp file.
2. If `audio_meta.is_vbr_for_url` ⇒ run `ffmpeg -c:a copy -bsf:a mp3_to_xing`. Failure falls back to the un-remuxed bytes (logged).
3. `write_bytes_atomic` the MP3 to `wip/<slug>/audio/<chapter>.mp3`.
4. `compute_audio_peaks` on the local temp → `write_json_atomic` to `wip/<slug>/peaks/<chapter>.json`.

`_done.json` is only written when every chapter succeeded. Partial failures leave the sentinel absent so the next trigger fills the gaps.

## Audit events

Every step lands in `audit/<YYYY>-<MM>.jsonl` so the timeline for a reciter is queryable by scanning the partition:

| Event | When |
|---|---|
| `audio_prefetch.queued` | Enqueue call (skip-flag in payload when the sentinel already exists). |
| `audio_prefetch.started` | Worker picked up the slug. `payload.total = chapter count`. |
| `audio_prefetch.chapter_done` | Chapter MP3 + peaks written. `payload = {chapter, bytes, duration_ms, ffmpeg_remuxed}`. |
| `audio_prefetch.chapter_failed` | One chapter failed; job continues. `payload.stage` is one of `download` / `upload_audio` / `unknown`. |
| `audio_prefetch.completed` | All chapters succeeded; sentinel written. |
| `audio_prefetch.failed` | At least one chapter failed; sentinel absent. |
| `audio_prefetch.purged` | Sweeper deleted `wip/<slug>/audio/` + `peaks/`. |

Actor for every event is `Actor(hf_user_id="system", login_at_time="audio_prefetch", role=MAINTAINER)` — the queue runs unattended.

## Sweeper

`audio_prefetch.start_cleanup_daemon()` spawns one daemon thread that wakes every hour, scans `state.all_rows()`, and for each row with `prefetch_purge_at ≤ now`:

1. Deletes `wip/<slug>/audio/` and `wip/<slug>/peaks/` via the bucket backend.
2. Deletes `_done.json`.
3. Emits `audio_prefetch.purged`.
4. Fires `state.transition(slug, "admin.clear_prefetch_purge_at", ...)` to clear the stamp.

Single-worker invariant (`app.py::_assert_single_worker`) guarantees exactly one sweeper per deploy.

## Read paths

Audio (`routes/audio/proxy.py::seg_audio_proxy`) lookup order:

1. `wip/<slug>/audio/<chapter>.mp3` — bucket prefetch.
2. CDN stream-through for slugs the prefetch hasn't reached yet.

Peaks (`routes/segments/peaks.py::seg_peaks`) checks the in-memory cache, then `wip/<slug>/peaks/<chapter>.json`, then schedules background computation (no disk cache; results land back in the bucket via `_persist_recomputed_chapter_peaks`).

## Admin re-trigger

`POST /api/admin/prefetch/rerun/<slug>` — maintainer+ only. Force-overwrites existing artifacts and re-enqueues the slug; useful after an ffmpeg-version bump or when an upstream URL set changed.

## What's gone

The "Download all audio" + "Delete audio cache" buttons have been removed. The associated endpoints (`/api/seg/prepare-audio/*`, `/api/seg/audio-cache-status/*`, `/api/seg/delete-audio-cache/*`) are deleted; their TypeScript response types are gone too.
