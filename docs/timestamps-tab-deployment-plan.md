# Timestamps Tab — Deployment Plan

Companion to `inspector-deployment-plan.md`. Captures the migration strategy for the Timestamps tab specifically, since it is the most data-heavy surface in the Inspector and needs a different read path than the Segments tab.

## Goals

- Stop the eager backend preload of every reciter's timestamps at startup. The current model is unviable at deployed scale (~22 MB per reciter × 300+ reciters → ~7 GB resident before any user shows up).
- Serve word + letter timestamps for completed reciters from a stateless, cacheable source.
- Keep audio fetching off the backend's hot path.
- Local-Docker development continues to work against on-disk JSON files (with cleanups).

## Non-goals

- Phoneme-level timestamps in the deployed view (see §3 limitation).
- Backwards-compatible serving of in-progress reciters from the deployed dataset (only completed reciters are on Hugging Face — in-review reciters fall back to the PR-branch worktree).
- Random-verse latency parity with the local model. Random buttons are inherently slower in the deployed model — accepted (see §3).

## 1. Read-path architecture

| Reciter state | Source | Backend role |
|---|---|---|
| **Completed** | Hugging Face dataset `hetchyy/quranic-universal-ayahs` via the Datasets Server `/rows` endpoint | Thin proxy with a small per-process LRU cache |
| **Under review** | PR-branch worktree (`reciter/<slug>/segments`) — same as Segments tab | Lazy load + cache, same flow as today |
| **Catalogued / Pending alignment** | n/a | Hidden from the Timestamps tab |

Audio is **not** served by the backend in either case. Browser fetches directly from `source_url` using the dataset row's `source_offset_ms` + `duration_ms` to compute byte-range bounds, falling back to the HF Datasets Server's `cached-assets` URL when origin CORS fails.

## 2. Endpoint mapping

Today's `/api/ts/*` routes map onto a new `/api/ts/*` shape (or a sibling namespace if we want them to coexist during migration):

| Old endpoint | New behaviour | Notes |
|---|---|---|
| `GET /api/ts/config` | Unchanged. | Static display config. |
| `GET /api/ts/reciters` | Reads the small `reciters` config of the HF dataset (`?config=reciters&split=all`, ~30 KB), filtered to `is_timestamped=true`. Cached server-side for 5 min. | Plus PR-branch reciters from worktree fallback for under-review entries. |
| `GET /api/ts/chapters/<reciter>` | Derived from `surah_info.json` filtered by the reciter's coverage (which lives on the `reciters` config row). No JSON parse. | The today version reads every verse key from the JSON. |
| `GET /api/ts/verses/<reciter>/<chapter>` | One `/rows` call covering the chapter's verses. Returns audio URL list + verse refs. | Bulk-fetch is the cheapest unit (see §4). |
| `GET /api/ts/data/<reciter>/<verse_ref>` | If the chapter is already cached server-side, slice it. Otherwise issue a `/rows` call covering the chapter, cache it, then slice. | Worst-case 1.5–2s cold; ~10ms warm. |
| `GET /api/ts/random/<reciter>` | Pick a random verse from the reciter's row count, fetch the chapter, return the verse. | Cold-path: 1.5–2s. |
| `GET /api/ts/random` | Pick a random reciter, then a random verse. | Cold-path: up to 2× the per-reciter cold cost (one for chapter fetch, audio is parallel). |
| `GET /api/ts/validate/<reciter>` | **Local only.** | Validator needs the full `timestamps_full.json` and is a maintainer tool; not exposed on the deployed site. |

The cache key is `(reciter, chapter)` → list of row dicts. With ~6,236 verses × ~3 KB per row = ~20 MB per fully-cached reciter. A 50-reciter LRU caps at ~1 GB; tune to the deployed instance's memory budget.

## 3. Limitations of the deployed path

These are intentional tradeoffs, captured here so they aren't rediscovered later.

### 3a. No phoneme-level timestamps

The HF dataset schema carries `word_timestamps` and `letter_timestamps` but **not phoneme intervals**. Local `timestamps_full.json` has them per-word in the `word_phones_raw` slot consumed by `services/ts_query.py::get_verse_data` (the `intervals` array, populated from `w[4]`).

Consequences for the Timestamps tab:

- The **Analysis view** will show **letters only** in the deployed model. The phoneme sub-row collapses or hides.
- Components affected: `UnifiedDisplay.svelte`, `AnimationDisplay.svelte`, anything reading the `intervals` payload field. Need a graceful "no phoneme data available" path that doesn't break layout.
- Local dev path retains phoneme display unchanged.

Options for closing the gap later:

- Add `phoneme_timestamps` as a column to the HF dataset (additive, safe). Requires `build_reciter.py` change + dataset rebuild for all splits.
- Or expose a separate `phonemes/<reciter>/<verse_ref>.json` companion file in the dataset repo for the small subset of users who care.

For v1, we accept "letters only" on the deployed site and document it as a known limitation.

### 3b. Random-same-reciter is slower

Today's `GET /api/ts/random/<reciter>` picks a verse from the in-RAM dict — instant.

Deployed: pick a random verse offset, fetch the chapter (1.5–2s cold), slice the verse. UX implications:

- The "random within reciter" button needs a loading state (spinner / skeleton).
- Subsequent random clicks hitting the same chapter are instant (warm cache).
- Pre-warm strategy: when the reciter is opened, kick off a background fetch of the next likely chapter the user will land on.

### 3c. Random-any-reciter is even slower (and unpredictable)

`GET /api/ts/random` picks a *random reciter* and *random verse*. Cold-path requires:

- One `/rows` call against a possibly never-touched reciter+chapter (1.5–2s, occasionally 7s).
- One audio fetch from a possibly never-touched `source_url` (~430ms cold, instant warm).

Under bad luck both are cold and both compound into 2–8s. This is the worst-case UX in the new model.

Mitigations:

- Restrict "random any reciter" to a curated allowlist of ~5 reciters that the backend keeps warm via a periodic background task. Trades exploration breadth for predictable latency.
- Show a longer skeleton with a "Loading random verse..." message; users notice the delay less when it's expected.
- Cache the most recent ~10 random picks on the client so back-button to a recent random feels instant.

### 3d. No `_meta.mfa_failures` / pipeline metadata

The HF dataset is the polished output. Pipeline diagnostics (failed alignments, beam search outcomes, raw ASR phonemes) live in `timestamps_full.json` and are not exposed on the dataset. The Inspector's existing `TimestampsValidationPanel.svelte` consumes some of this — it goes silent on the deployed path for completed reciters.

This is acceptable: validation panels are most useful for in-review reciters, which keep using the PR-branch worktree path (full data available).

### 3e. Datasets Server availability

`datasets-server.huggingface.co` has no published SLA. We've observed both ~1.5s typical and 7s outliers. The backend cache absorbs most of the variance; the first user per (reciter, chapter) pays the cliff.

If outages happen frequently in practice, fall back option: the same Parquet file is also reachable directly via `huggingface.co/datasets/.../resolve/refs%2Fconvert%2Fparquet/<config>/<split>/0000.parquet` (CDN-fronted, S3 backend), which we could read with PyArrow. That's option 3 in §6.

## 4. Why bulk per-chapter, not per-verse

Empirically (benchmarks captured during planning):

| Request shape | Cold TTFB | Size |
|---|---|---|
| `length=1` | 1.6–2.0 s | ~3 KB |
| `length=10` | ~5 s (variable) | ~35 KB |
| `length=100` | ~1.3 s | ~291 KB |

The Datasets Server's per-call overhead dominates. Fetching one row is roughly the same wall-clock cost as fetching a whole chapter. So we always fetch a whole chapter at once and slice client-side / server-side.

Average chapter has ~55 verses; max (Al-Baqarah) has 286. All comfortably fit in a single `length` ≤ 300 call.

## 5. Local development path

Keep the JSON file flow for local Docker. `INSPECTOR_DATA_DIR=/data` already mounts on-disk timestamps. Two cleanups while we're here:

### Stop the eager preload

`app.py`'s startup loop currently calls `load_timestamps(slug)` for every discovered reciter via a `ThreadPoolExecutor`. Strip it. `load_timestamps()` is already lazy with a per-reciter cache — first request pays ~200–400ms parse, subsequent are instant.

### Drop the audio_source peek

`discover_ts_reciters()` opens every JSON to read the first 512 bytes for `_meta.audio_source`. The new `reciters_index.json` carries this field already (per the segments deployment plan §6); read it from there instead.

### Add a memory cap (optional)

If running locally on a small machine with all 300 reciters mounted, an LRU cap (~5 reciters resident) prevents OOM after a long browse session. Single-developer use rarely hits this; ship without unless needed.

### Source switch

Add an `INSPECTOR_TS_SOURCE` env var: `local` (default for Docker) or `huggingface` (default for deployed). Backend dispatches to the right loader behind the existing `/api/ts/*` route surface — UI is unaware.

## 6. Future options (not v1)

Captured for completeness — pursue only if v1's UX or cost becomes a problem.

1. **Backend-side Parquet reader.** Drop the Datasets Server dependency and serve rows directly from the Parquet file using PyArrow. Sub-100ms cold per-verse latency once the Parquet handle is open. Cost: managing 1.5 GB × N reciters of Parquet on the deployed instance's storage (or fronting it with S3 + CloudFront). Probably overkill until usage justifies it.
2. **Phoneme column on the HF dataset.** Add `phoneme_timestamps` to the schema. Closes limitation §3a. Requires dataset rebuild.
3. **Edge cache via CloudFront / Cloudflare in front of the backend's `/api/ts/*` proxy.** Cuts variance for popular reciters to <50ms even on cold backend.
4. **Service worker prefetch.** Browser-side: when the user lands on a reciter, the SW prefetches the next 1–2 chapters worth of `/api/ts/*` calls so verse-by-verse navigation is always warm.

## 7. Phased rollout

1. **Phase A — local cleanups (independent of deployment).**
   - Remove startup preload in `app.py`.
   - Drop the file-peek in `discover_ts_reciters`.
   - Add the `INSPECTOR_TS_SOURCE` env var (default `local`, no behavioural change).

2. **Phase B — HF source loader behind a flag.**
   - New module `services/timestamps_hf.py` that talks to the Datasets Server.
   - When `INSPECTOR_TS_SOURCE=huggingface`, route `/api/ts/data` and `/api/ts/verses` through it.
   - In-memory LRU keyed on `(reciter, chapter)`.
   - Adapter shim that maps HF rows → today's `get_verse_data` payload shape (with `phoneme_indices=[]`, `intervals=[]`).
   - UI tested end-to-end against a staging deploy.

3. **Phase C — UI for the limitation.**
   - Hide the phoneme sub-row in `UnifiedDisplay`/`AnimationDisplay` when `intervals` is empty.
   - Loading skeleton on random-verse buttons.
   - Curated "warm" allowlist for `/api/ts/random` if needed.

4. **Phase D — production cutover.**
   - Default `INSPECTOR_TS_SOURCE=huggingface` on the deployed Fly.io instance.
   - Local Docker keeps `INSPECTOR_TS_SOURCE=local` via `docker-compose.yml`.
   - `discover_ts_reciters` for the deployed path reads from the HF `reciters` config + the live PR-branch state.

## Open questions

- **Should we expose `INSPECTOR_TS_SOURCE=hybrid`** that prefers local files but falls back to HF? Useful for maintainers who have *some* reciters mounted but not all. Probably not worth the complexity for v1.
- **HF token usage.** The dataset is public; no token needed. If we ever gate it (private staging), the backend uses an installation token from the GitHub App's secret store.
- **Cache invalidation on reciter re-publish.** If an existing reciter is re-released to HF (post-correction), the per-(reciter, chapter) cache must invalidate. Easy hook: cache key includes the dataset's last-modified header (HEAD of the reciter's row group) checked every N minutes.
- **Reciter index ↔ HF `reciters` config sync.** Today `reciters_index.json` is repo-side; HF `reciters` is dataset-side. Keep one as source of truth (probably repo) and let `build_reciter.py` derive HF's copy. Document the direction.
