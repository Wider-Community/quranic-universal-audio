# Wip-audio sweeper

Hourly daemon that GCs bucket audio + peaks for reciters released ≥ 7 days ago. Without it `wip/<slug>/audio/` accumulates indefinitely as reciters move through the pipeline.

> **Renamed from `audio-prefetch.md`.** The original page also documented an in-Space background prefetch worker that downloaded chapters from upstream CDNs to warm the bucket on state transitions. That worker was removed once the Katana extraction pipeline became the only writer of bucket audio:
>
> - Katana's `.local/extraction/segments/audio_persist.py` writes `wip/<slug>/audio/<ch>.mp3` and `wip/<slug>/peaks/<ch>.json.gz` directly, then `.local/extraction/upload_to_bucket.py::_write_done_sentinel` writes `_done.json`.
> - The worker's `_remux_mp3_to_xing` step had also been silently no-op'ing for months — it called `-bsf:a mp3_to_xing`, a non-existent ffmpeg filter — so the worker shipped raw upstream bytes anyway. No correctness advantage over the CDN passthrough that already serves un-extracted slugs.
>
> Removal landed via the same change that documents this file rename. The sweeper survives because nothing else GCs the wip/ subtree.

## Storage

| Path | Contents |
|---|---|
| `wip/<slug>/audio/<chapter>.mp3` | Chapter audio written at extraction time (Xing/Info header injected by `audio_persist::_ensure_xing` using `ffmpeg -c:a copy -f mp3`). |
| `wip/<slug>/peaks/<chapter>.json.gz` | Slim packed waveform peaks (schema v3, int8 + gzip). See [peaks.md](./peaks.md) for the envelope. |
| `wip/<slug>/audio/_done.json` | Sentinel written atomically last by katana's `upload_to_bucket.py`. Presence ⇒ extraction completed in full. |

Chapter keys follow the audio-manifest sidecar (`"1"`..`"114"` for `by_surah`, `"<surah>:<ayah>"` for `by_ayah`).

## When the sweeper runs

Boot wiring: `inspector/app.py::_hydrate_bucket_stores` calls `audio_prefetch.start_cleanup_daemon()` iff `INSPECTOR_WIP_SWEEPER=1` (Dockerfile sets it on prod; local dev defaults off so a mistyped `INSPECTOR_BUCKET_REPO` can't accidentally delete prod data). The pytest guard also skips it.

The daemon ticks every `_CLEANUP_INTERVAL_S = 3600` seconds.

## Trigger flow

| State transition | Effect on `prefetch_purge_at` |
|---|---|
| `reciter.timestamps_completed → RELEASED` | Stamp `ReciterRow.prefetch_purge_at = now + 7d`. |
| `admin.unlocked_for_revision → AWAITING_REVIEW` | Clear the stamp. |
| `admin.clear_prefetch_purge_at` | Cleared by the sweeper itself after purge. |

Each tick `sweep_due()`:

1. Scans `state.all_rows()` for rows with `prefetch_purge_at ≤ now`.
2. Calls `audio_fetch.clear_prefetch(slug)` — deletes `wip/<slug>/audio/` and `peaks/` via the bucket backend.
3. Deletes the `_done.json` sentinel.
4. Emits `audio_prefetch.purged` to the audit log.
5. Fires `state.transition(slug, "admin.clear_prefetch_purge_at", ...)` so the same row doesn't re-trigger every hour.

Single-worker invariant (`app.py::_assert_single_worker`) guarantees exactly one sweeper per deploy. Actor for every audit event is `Actor(hf_user_id="system", login_at_time="audio_prefetch", role=MAINTAINER)`.

## Audit events

| Event | When | Status |
|---|---|---|
| `audio_prefetch.purged` | Sweeper deleted `wip/<slug>/audio/` + `peaks/` | **Current** — only event the post-removal code emits. |
| `audio_prefetch.{queued,started,chapter_done,chapter_failed,completed,failed}` | Worker activity (download progress, success, partial failure) | **Historic only** — no new emissions after worker removal. Old entries stay queryable in `audit/<YYYY>-<MM>.jsonl`. |

## Read paths (for context)

Bucket audio + peaks are read by:

- `inspector/services/audio/audio_source.py::resolve` (audio proxy) — `read_prefetched_audio_local_path` / `read_prefetched_audio_bytes`.
- `inspector/routes/segments/peaks.py::seg_peaks` — `read_prefetched_peaks` (slim envelope).
- `inspector/services/audio/audio_prefetch.py::sweep_due` — `clear_prefetch` (delete on TTL).

All three live in `audio_fetch.py`, the only surviving primitives after the worker removal.

## What's gone

- The "Download all audio" + "Delete audio cache" buttons (removed earlier — endpoints `/api/seg/prepare-audio/*`, `/api/seg/audio-cache-status/*`, `/api/seg/delete-audio-cache/*` and their TS types).
- The background prefetch worker, post-transition fetch hook, boot-time `resume_orphaned`, admin re-trigger endpoint `POST /api/admin/prefetch/rerun/<slug>`, `INSPECTOR_AUDIO_PREFETCH` env var, `AUDIO_PREFETCH_RESUME_ON_BOOT` env var, `AUDIO_DL_WORKER_COUNT` config, `_AUDIO_DL_PROGRESS` cache + helpers, `audio_fetch::fetch_and_persist_chapter` / `_remux_mp3_to_xing` / `_download_to_temp` / `_recompute_peaks_for_existing_audio` / `ChapterArtifact` / `ChapterFetchError` / `write_done_marker` / `now_ms`, `audio_prefetch::{enqueue,_run_one,_worker_loop,on_state_transition,progress,resume_orphaned}` plus worker-queue module state.
