# Peaks — chapter overview + per-segment fallback

How the inspector gets waveform peaks onto a `<canvas>`. One pre-baked
representation on the bucket (slim int8 packed gzip), one runtime fallback
(ffmpeg HTTP-Range decode per segment). No middle tier, no dequantization
inside the request path, no legacy float-JSON shape — that all went away in
the slim-peaks migration (commit `e0417238`, doc context in
`docs/proposals/peaks-int8-drawer.md`).

## Two-tier shape

| Tier | Source | Wire shape | Cost | When it fires |
|---|---|---|---|---|
| **1. Chapter overview** | `<wip\|published>/<slug>/peaks/<ch>.json.gz` baked offline on Katana | int8 envelope `{q:'int8', n, peaks_b64, bps, duration_ms}` per URL — sent verbatim, no dequant | sub-ms per chapter on warm bucket; ~21 KiB wire / chapter avg | On accordion open: `_prefetchAccordionPeaks` fires one batch fetch for every chapter the accordion touches. FE caches the typed-array view per URL. |
| **2. Per-segment ffmpeg** | Live HTTP Range decode against the CDN | nested float `PeakBucket[]` at HD 30 bps | ~1 s per segment (ffmpeg cold), variable | Card click for a chapter whose overview peaks aren't loaded (rare on prewarmed reciters after Tier 1 ran). |

Tier 1 is the fast path; Tier 2 is the only fallback. There is no in-between
("slice chapter peaks server-side and emit a sub-range") — every card's
canvas slices its own range out of the typed array client-side via
`peaks-view.ts` + the drawer in `lib/utils/waveform-draw.ts`.

## On-disk format (`<ch>.json.gz`, schema v3)

Produced by `inspector/services/audio/peaks_slim.py::pack_slim`. One gzip
member containing one JSON document:

```json
{
  "schema_version": 3,
  "duration_ms": 6888280,
  "q": "int8",
  "bps": 10,
  "n": 68883,
  "peaks_b64": "AAA... (n*2 base64-encoded signed bytes)"
}
```

- `n*2` interleaved int8 values, `[mn₀, mx₀, mn₁, mx₁, ...]`, each in
  `[-127, 127]`. Dequant at read is `v / 127`.
- 10 buckets per second after symmetric decimation from the HD 30 bps source
  (`compute_audio_peaks`). Chapter-overview canvases are ≤ ~1100 px wide;
  even a 3-hour chapter at 10 bps oversamples by ~100×. Per-segment zoom
  uses Tier 2's 30 bps fidelity.
- gzip level 6 with `mtime=0` → byte-identical output for the same input
  (CDN cache key stays stable across re-bakes that didn't change the
  payload).

Concatenating multiple `pack_slim` outputs is valid gzip (RFC 1952), but the
inspector reader/route operate per-file — concatenation isn't used today.

`unpack_slim_envelope` (the route's reader) skips the dequant step and
returns the envelope verbatim. `unpack_slim` (the dequantized
`list[list[float]]` variant) is kept for the offline extraction's history
JSONL writer, which still emits float-list records.

## Generation — where peaks come from

Two writers, both producing the same v3 slim format. Single-source: both
import `peaks_slim.pack_slim`.

### Primary: Katana extraction

`.local/extraction/segments/audio_persist.py::persist_audio_and_peaks`
runs alongside segment extraction on Katana for every reciter. Computes HD
peaks via `compute_audio_peaks`, packs via `pack_slim`, writes to
`<peaks_dir>/<ch>.json.gz` next to the chapter MP3. Upload to bucket
(`upload_to_bucket.py --include-audio`) lands audio + peaks + sentinel
atomically; Inspector reads the same paths described below.

### No in-Flask fallback

The inspector used to run an in-Space background worker
(`audio_fetch.fetch_and_persist_chapter`) that would download from upstream
and write fresh peaks alongside the audio. That worker was removed once
Katana extraction became the only writer of bucket audio + peaks. Peaks
missing on the bucket today fall through to the per-segment ffmpeg
fallback in `routes/segments/peaks.py::seg_segment_peaks` — there's no
runtime re-bake path. See [wip-audio-sweeper.md](wip-audio-sweeper.md)
for the removal rationale.

## Storage paths (state-aware)

`inspector/services/storage/storage_paths.py::prefetched_peaks_path`
consults `data_dir.kind_for(slug)` to resolve the bucket root:

```
<wip|published>/<slug>/peaks/<chapter>.json.gz
```

`wip/` for in-flight reciters, `published/` for shipped ones. Published
reciters today have no peaks baked — the path is forward-looking
infrastructure for when peaks ride the publish flow.

Legacy `.json.bak` files may sit alongside `.json.gz` during a backfill —
they're rollback targets for `inspector/scripts/rollback_peaks_slim.py`,
not read by any runtime code.

## Serving — the routes

### `GET /api/seg/peaks/<reciter>?chapters=<csv>`

Returns chapter-overview peaks for the listed chapters, slim envelope
verbatim:

```json
{
  "peaks": {
    "https://cdn/.../1.mp3": { "q":"int8", "n":68883, "peaks_b64":"...", "bps":10, "duration_ms":6888280, "schema_version":3 },
    "https://cdn/.../2.mp3": { ... }
  },
  "complete": true
}
```

`complete` is preserved on the wire for FE forward-compat but always true:
there is no background-compute path. Missing chapter files (extraction
didn't bake peaks, or backfill not yet run) simply drop out of the response
— FE handles the absence by firing Tier 2 on a card click.

Server-side caching:

- **Per-URL cache** (`_PEAKS_CACHE` in `services/storage/cache.py`) —
  unbounded process-lifetime dict of `{reciter: {url: envelope_dict}}`.
  Skips bucket reads when two different `?chapters=` requests overlap on
  the same URL.
- **LRU response-bytes cache** (`_PEAKS_RESPONSE_CACHE`, max 50 entries) —
  bounded cache of the `orjson.dumps(body)` bytes keyed by
  `(reciter, sorted_chapter_tuple)`. Skips both `orjson` and `jsonify`
  on warm hits. `flask-compress` still re-gzips per request.
- **Bucket fan-out** — `ThreadPoolExecutor(max_workers=8)` for misses.
  Bucket reads release the GIL (FUSE I/O), threads are the right
  primitive. `cache.set_peaks_for_url` takes a lock internally — the route
  MUST NOT wrap it in an outer `with lock:` block (non-reentrant Lock →
  deadlock; tested in `test_peaks_no_lock_deadlock_on_misses`).

Cache-Control:

- `?h=<hash>` present → `public, max-age=31536000, immutable` (1 year).
  FE computes the hash over the response's audio URLs so a delivery flip
  invalidates the URL.
- `?h=` absent or empty response → `public, max-age=86400` / `no-store`.

### `POST /api/seg/segment-peaks/<reciter>`

Tier 2: ffmpeg + HTTP Range fallback. Body:

```json
{ "segments": [{ "url": "...", "start_ms": 12345, "end_ms": 13456, "chapter": 3, "pad_ms": 0 }] }
```

Returns `{peaks: {"<url>:<start>:<end>": {peaks, start_ms, end_ms, duration_ms}}}`
with nested `PeakBucket[]` floats at HD 30 bps. `pad_ms` widens the decoded
range symmetrically for split / scrubber UIs. No server-side caching —
each request decodes fresh.

The FE only calls this for cards whose chapter peaks aren't loaded.
`getWaveformPeaks(url)?.peaks?.length` short-circuits the call when the
Tier 1 typed-array view is already in the cache.

### `GET / POST /api/seg/history-peaks/<reciter>`

Persisted per-op peaks for the History panel. Stored as `PeakBucket[]`
floats on the bucket (`edit_history_peaks.jsonl`) — separate format from
Tier 1, separate migration story. Written by extraction's
`write_edit_history_peaks` and runtime by the History panel on first play.

## Caches + invalidation policy

| Cache | Lifetime | Evicted by |
|---|---|---|
| `_PEAKS_RESPONSE_CACHE` (LRU 50, response bytes) | Process | Own LRU cap, `pop_reciter_peaks_response_cache(reciter)` (manual peaks rebuild only). **NOT** evicted on save/undo — peaks are tied to immutable audio bytes, not segment edits. Autosave fires `invalidate_seg_caches` every few seconds; that helper deliberately leaves the peaks LRU alone. |
| `_PEAKS_CACHE` (per-URL envelope dicts) | Process | Manual via `pop_peaks_cache(reciter)`; no auto-eviction. Acceptable: envelope dicts are tiny (~200 bytes header + b64 string ≤ 150 KB). |
| FE `waveform-cache` (per-URL `AudioPeaks` Map) | Tab | `clearWaveformCache()` on reciter change. Held as `Int8Array` for Tier 1 peaks (~140 KB/chapter) and `PeakBucket[]` for Tier 2 + history (~3 MB/chapter — already a hot regret, captured in the int8-drawer proposal). |

## FE consumer

`inspector/frontend/src/tabs/segments/utils/waveform/utils.ts::_fetchPeaks`
fires one batched request per accordion open (driven by
`ValidationPanel.svelte::_prefetchAccordionPeaks`). For each URL in the
response, decodes `peaks_b64` → `Int8Array(n * 2)` once and stashes it via
`setWaveformPeaks(url, { peaks: view, duration_ms })`.

Downstream drawing goes through `inspector/frontend/src/lib/utils/peaks-view.ts`,
a shape-adapter exposing `length / min(i) / max(i)` over either an
`Int8Array` (Tier 1) or a nested `PeakBucket[]` (Tier 2 / history). The
hot-path drawer (`waveform-draw.ts`, `draw-seg.ts::_slicePeaks`,
`op-peaks.ts::_sliceFromChapterPeaks`) branches on shape once at view
construction; per-pixel reads are shape-free.

Per-segment slicing happens client-side: `_slicePeaks` slices the typed
array via `subarray(i0*2, i1*2)` (zero-copy) and resamples to canvas
buckets. No server roundtrip for in-cache segments.

## Backfill + audit

- **`inspector/scripts/backfill_peaks_slim.py`** — walks both `wip/*/peaks/`
  and `published/*/peaks/` for any reciter that still has legacy `.json`
  (pre-slim) files, packs them via `pack_slim`, writes `.json.gz`, renames
  the original to `.json.bak` for rollback. Idempotent — skips chapters
  whose `.json.gz` already exists.
- **`inspector/scripts/rollback_peaks_slim.py`** — symmetric reverse.
- **`inspector/scripts/audit_bucket_reciter.py::_audit_peaks_slim`** —
  validates every `<ch>.json.gz` on a reciter's folder against the schema
  envelope (`schema_version == 3`, `peaks_b64` / `bps` / `duration_ms`
  present, gzip + JSON parse cleanly). Run as part of the broader audit
  before releasing a reciter.

None of these need updating when the runtime shape changes — they operate
on the on-disk envelope, which has been stable since schema v3 shipped.

## Performance notes

- Single-worker Flask: keep route latency ≪ 100 ms warm. The LRU
  response-bytes cache + the per-URL cache together guarantee that a
  repeat-open accordion in the same session hits in ~50 ms (orjson skip +
  jsonify skip + zero bucket reads).
- Cold bucket reads: ~3 ms/file (FUSE mount) × 8 workers ≈ ~45 ms for a
  worst-case 114-chapter request. CDN-direct (`hffs.cat_file` fallback,
  ~50–500× slower) makes cold opens dominated by I/O — bucket-mount in
  production avoids this.
- FE side: parse cost is the int8-envelope route's biggest sandbox win
  (~33× faster `JSON.parse` than the dropped nested-float shape).
  Heap: ~25× less retained per chapter as `Int8Array(2N)` vs
  `Array<[number, number]>`. Both numbers came from the bench in
  `docs/proposals/peaks-int8-drawer.md`.

## Module index

| Module | Role |
|---|---|
| `inspector/services/audio/peaks_slim.py` | `pack_slim`, `unpack_slim` (float-list, for extraction history), `unpack_slim_envelope` (raw, for runtime route) |
| `inspector/services/audio/audio_fetch.py` | `read_prefetched_peaks` (runtime envelope reader), `fetch_and_persist_chapter` (prefetch fallback writer) |
| `inspector/services/audio/peaks.py` | `compute_audio_peaks` (HD source), `compute_segment_peaks` (Tier 2 ffmpeg + Range), `is_current_schema` |
| `inspector/routes/segments/peaks.py` | `/api/seg/peaks` (Tier 1), `/api/seg/segment-peaks` (Tier 2), `/api/seg/history-peaks` (history) |
| `inspector/services/storage/cache.py` | `_PEAKS_CACHE` (per-URL), `_PEAKS_RESPONSE_CACHE` (LRU 50), `get_peaks_lock`, `pop_reciter_peaks_response_cache` |
| `inspector/services/storage/storage_paths.py` | `prefetched_peaks_path` (state-aware) |
| `inspector/frontend/src/lib/utils/peaks-view.ts` | Shape adapter (`Int8Array` vs `PeakBucket[]`) |
| `inspector/frontend/src/lib/utils/waveform-cache.ts` | Per-URL FE cache (`AudioPeaks` Map) |
| `inspector/frontend/src/lib/utils/waveform-draw.ts` | Pure drawer (canvas pixel → `peaks-view` read) |
| `inspector/frontend/src/tabs/segments/utils/waveform/utils.ts` | `_fetchPeaks` (decode b64 → `Int8Array`), `_fetchPeaksForClick` (Tier 2 trigger) |
| `inspector/frontend/src/tabs/segments/components/validation/ValidationPanel.svelte` | `_prefetchAccordionPeaks` (fires the Tier 1 batch on accordion open) |
| `inspector/scripts/{backfill,rollback}_peaks_slim.py` | One-shot bucket migration |
| `inspector/scripts/audit_bucket_reciter.py::_audit_peaks_slim` | Per-reciter integrity check |
| `.local/extraction/segments/audio_persist.py` | Katana-side primary writer (Tier 1 + history JSONL) |
