# Audio Data Access — Architecture Design

## Problem Statement

The Quranic Universal Audio project serves diverse audiences — app developers building Quran apps, researchers doing speech/NLP work, offline-first mobile apps, and web players needing low-latency streaming. Each has fundamentally different access patterns:

| Dimension | Options |
|-----------|---------|
| **Granularity** | Single verse, full chapter (surah), full mushaf |
| **Audio continuity** | Gapped (cut verse segments) vs gapless (original chapter recordings) |
| **Delivery** | Streaming (real-time) vs bulk download (offline) |
| **Latency needs** | <100ms (interactive apps) vs seconds-OK (research/batch) |
| **Data scope** | Audio only, audio + timestamps, timestamps only |

This document evaluates what we have, identifies gaps, and proposes a layered access architecture.

---

## Current State

### 1. Hugging Face Dataset (`hetchyy/quranic-universal-ayahs`)

**What it contains:** Every verse as an individual row with MP3 audio bytes embedded in parquet files, plus word-level timestamps and pause-based segments.

**Schema:**
| Column | Type | Description |
|--------|------|-------------|
| `audio` | `Audio` | MP3 bytes (128kbps), trimmed to speech boundaries |
| `surah` | `int32` | Surah number (1–114) |
| `ayah` | `int32` | Verse number |
| `text` | `string` | Arabic text from alignment |
| `segments` | `[[int]]` | Pause-based segments `[word_from, word_to, start_ms, end_ms]` |
| `word_timestamps` | `[[int]]` | Word timings `[word_index, start_ms, end_ms]` |

**Key characteristics:**
- Audio is **gapped** — each verse is individually trimmed to speech boundaries. Consecutive playback will sound unnatural (abrupt cuts, missing inter-verse pauses).
- Timestamps are **relative to clip start** (not to the original chapter audio). This is correct for playback of individual clips but means they cannot be used to seek into the original chapter recording.
- Audio is embedded as binary blobs inside parquet shards (up to 10GB each). There are no external URL references.
- Organized as config=riwayah, split=reciter (e.g. `hafs_an_asim` / `minshawy_murattal`).
- Currently only covers timestamped reciters (2 full, 1 partial) out of 350+ total audio-only reciters.

**Access methods:**
```python
# Full download (~1.5GB per reciter)
ds = load_dataset("hetchyy/quranic-universal-ayahs", "hafs_an_asim", split="minshawy_murattal")
verse = ds[42]  # random access by index

# Streaming (low memory, sequential)
ds = load_dataset(..., streaming=True)
for verse in ds:
    process(verse)

# Filtering
ds = ds.filter(lambda x: x["surah"] == 2)  # all of Al-Baqarah
```

**Latency profile:**
| Operation | Latency | Notes |
|-----------|---------|-------|
| `load_dataset()` (first call) | 10–60s | Downloads parquet shard(s) to local cache |
| `load_dataset()` (cached) | 1–3s | Reads from `~/.cache/huggingface/` |
| `ds[n]` (random access) | <10ms | Memory-mapped parquet, very fast |
| `streaming=True` (first row) | 2–5s | HTTP range request for first parquet chunk |
| `streaming=True` (subsequent) | <50ms | Sequential reads within shard |
| Row-level HTTP API (`/rows`) | 200–500ms | Via HF datasets-server, audio returned as signed CDN URLs |
| Filter API (`/filter`) | 200–500ms | SQL-like column filtering, same CDN URL pattern |

**HF Datasets-Server API (no download required):**

The HF datasets-server exposes REST endpoints that query parquet directly — no Python or dataset download needed:

```bash
# Get a specific verse by surah + ayah (no need to know row offset)
GET /filter?dataset=hetchyy/quranic-universal-ayahs\
  &config=hafs_an_asim&split=minshawy_murattal\
  &where="surah"=2 AND "ayah"=255&offset=0&length=1

# Get rows by offset
GET /rows?dataset=hetchyy/quranic-universal-ayahs\
  &config=hafs_an_asim&split=minshawy_murattal&offset=0&length=7
```

Key characteristics:
- **Audio is served as signed CloudFront CDN URLs** (not embedded bytes). The response JSON contains `"audio": {"src": "https://datasets-server.huggingface.co/cached-assets/...?Expires=...&Signature=..."}`. Fetching the actual audio is a second HTTP request.
- **`/filter` supports SQL-like `where` clauses**: column names in double quotes, numeric values unquoted, `AND`/`OR`/parentheses for compound conditions, plus `orderby` and pagination (`offset`/`length`, max 100 rows).
- **Signed URLs expire** — they cannot be cached long-term or shared across users.
- **Rate limits**: 5-minute fixed windows, exact numbers undisclosed. Unauthenticated requests are heavily throttled — always pass `HF_TOKEN`. Implement exponential backoff for 429s.
- **Two-hop latency**: metadata request → get signed URL → fetch audio file. Not ideal for latency-sensitive apps but workable for moderate-traffic use cases.

### 2. GitHub Releases (metadata only)

**What it contains:** Per-reciter zip files with:
- `info.json` — reciter metadata (name, riwayah, coverage, version)
- `audio.json` — audio manifest (URLs to original CDN sources, not audio bytes)
- `segments.json` — pause-based recitation segments
- `timestamps.json` — word-level timestamps
- `timestamps_full.json` — word + letter + phoneme timestamps (when available)

Plus shared reference files: `manifest.json`, `surah_info.json`, `qpc_hafs.json`.

**Key characteristics:**
- No audio data — just URLs pointing to third-party CDNs
- Timestamps in these files are **relative to the original audio source** (not clip-normalized like the HF dataset)
- Small downloads (KBs–MBs per reciter)
- Versioned with checksums for reproducibility

### 3. Audio Manifests (`data/audio/`)

**What they contain:** JSON files mapping surah numbers or verse references to URLs on third-party CDNs.

**Sources:** everyayah.com, mp3quran.net, qul.tarteel.ai, surah-quran.com, YouTube

**Two categories:**
- `by_surah/` — full chapter recordings (114 URLs per reciter). **These are gapless.**
- `by_ayah/` — individual verse recordings (6,236 URLs per reciter). **These are pre-cut by the source, may or may not be gapless.**

---

## Gap Analysis

### Gap 1: No Gapless Playback Path

**The problem:** The HF dataset contains only trimmed verse clips. Playing verses 1:1, 1:2, 1:3... consecutively produces audible gaps and abrupt transitions. For Quran apps where users listen to full surahs, this is unacceptable.

**What exists but isn't surfaced:** The `by_surah` audio manifests point to original, gapless chapter recordings. The `timestamps.json` in GitHub releases has timestamps relative to those original recordings. Together, these *could* enable gapless playback with verse-level seeking — but there's no unified interface or documentation telling developers to combine them this way.

**Proposed fix:** `source_url` + `source_offset_ms` + `audio_category` columns on verse rows, plus `sources` config with URL templates (see Layer 2 enhancements below).

### Gap 2: Timestamp Frame of Reference Is Fragmented

**The problem:** Timestamps exist in two frames of reference:
1. **Clip-relative** (HF dataset `word_timestamps`): `start_ms=0` means start of the trimmed verse clip
2. **Source-relative** (GitHub releases `timestamps.json`): `start_ms` is relative to the original audio file (chapter or verse recording from the CDN)

For gapless chapter playback, developers need source-relative timestamps. For individual verse clip playback, they need clip-relative. Currently you have to know which is which and pair the right timestamps with the right audio. This is not documented.

**Proposed fix:** `source_offset_ms` bridges the two frames. Source-relative = clip-relative + `source_offset_ms`. One column, one addition. Both frames accessible from the same row.

### Gap 3: Dependence on Third-Party CDNs

**The problem:** Audio manifests point to everyayah.com, mp3quran.net, etc. These are community-run services with no SLA. They could:
- Go offline temporarily or permanently
- Change URL structures
- Throttle or block programmatic access
- Have inconsistent global latency

For research and batch processing, this is fine (download once, cache locally). For production apps serving end users, relying on these CDNs introduces fragility.

### Gap 4: No Verse-Level Random Access with Low Latency

**The problem:** For interactive apps (tap a verse, hear it immediately), the ideal is <100ms to first audio byte. Current options:

| Method | First-byte latency | Drawback |
|--------|-------------------|----------|
| HF dataset (cached locally) | <10ms | Requires 1.5GB+ download per reciter upfront |
| HF dataset (streaming) | 2–5s first, then fast | Sequential only; can't jump to verse 6000 fast |
| HF `/filter` API | 200–500ms (metadata) + audio fetch | Two-hop (get signed URL, then fetch audio); signed URLs expire; rate-limited |
| Third-party CDN (by_ayah) | 100–500ms | Depends on CDN availability and user location |
| Third-party CDN (by_surah) | 100–300ms + seek | Need byte-range or time-offset seeking |

**Mitigating factor:** The HF `/filter` API is better than initially assumed — it supports direct `"surah"=2 AND "ayah"=255` queries without knowing row offsets, and **latency does not scale with dataset size** because each config+split is an independent parquet file. Adding hundreds of reciters as new splits doesn't slow down querying any individual reciter. However, the two-hop latency (metadata → signed URL → audio fetch) and rate limits still make it unsuitable as a primary audio delivery mechanism for high-traffic consumer apps.

**Practical mitigation via URL templates:** If the HF dataset exposes the source URL template (see `sources` config proposal below), apps can bypass HF audio serving entirely and go direct to CDN — eliminating the two-hop problem for audio while still using HF for timestamp/metadata access.

### Gap 5: No Unified Developer Experience

**The problem:** A developer wanting to build a Quran app today has to:
1. Understand three separate systems (HF dataset, GitHub releases, audio manifests)
2. Know which timestamps go with which audio
3. Decide between gapped and gapless themselves
4. Handle CDN failover themselves
5. Build their own caching layer

**Proposed fix:** The enhanced HF dataset becomes the single entry point. The `sources` config provides discovery and URL templates. The verse rows provide timestamps with `source_offset_ms` bridging both frames. The data access guide documents the recommended patterns per use case. Developers no longer need to navigate the GitHub repo structure or understand three separate systems.

### Gap 6: No Reciter Discovery or Source Metadata in the Dataset

**The problem:** The HF dataset only contains timestamped reciters (currently 2–3). But the project has 350+ reciters with audio manifests across 14 riwayat. There is no programmatic way for an app to:
- Discover available reciters, their names, styles, riwayah, and sources
- Get audio URLs for non-timestamped reciters
- Know whether a reciter has timestamps or just audio

The `reciters_index.json` file exists in the repo but isn't exposed through the HF dataset or API. Developers have to navigate the GitHub repo structure manually.

---

## Proposed Architecture: Layered Access Model

Rather than one approach for everyone, provide three well-defined layers, each serving a different audience:

```
┌──────────────────────────────────────────────────────────────────┐
│  Layer 3: REST API + CDN                                        │
│  For: Production apps needing low-latency, gapless playback     │
│  Access: HTTP GET with verse/surah addressing                   │
│  Latency: <100ms (CDN-cached)                                   │
└────────────────────────┬─────────────────────────────────────────┘
                         │ built on
┌────────────────────────▼─────────────────────────────────────────┐
│  Layer 2: Hugging Face Dataset                                   │
│  For: Researchers, ML pipelines, bulk analysis                   │
│  Access: datasets library (Python), parquet (any language)       │
│  Latency: seconds (acceptable for batch)                         │
└────────────────────────┬─────────────────────────────────────────┘
                         │ built on
┌────────────────────────▼─────────────────────────────────────────┐
│  Layer 1: Raw Data + Audio Manifests (GitHub Releases)           │
│  For: Offline use, custom pipelines, full control                │
│  Access: Direct download, git                                    │
│  Latency: N/A (download once)                                    │
└──────────────────────────────────────────────────────────────────┘
```

### Layer 1: Raw Data + Audio Manifests (Exists Today — Enhance)

**Audience:** Offline apps, custom pipelines, developers who want full control.

**What stays the same:**
- GitHub releases with metadata zips (segments, timestamps, audio manifests)
- `surah_info.json`, `qpc_hafs.json` as reference data

**What to add:**

1. **Unified timestamp file per reciter** that includes both frames of reference:
   ```json
   {
     "1:1": {
       "source_audio": "by_surah",
       "words": [
         {
           "word": 1,
           "clip_start_ms": 0,
           "clip_end_ms": 400,
           "source_start_ms": 560,
           "source_end_ms": 960
         }
       ],
       "clip_offset_ms": 560
     }
   }
   ```
   `clip_offset_ms` is the offset from source audio start to clip start. This lets developers convert between frames trivially: `source_ms = clip_ms + clip_offset_ms`.

2. **Playback guide** in release notes explaining:
   - For gapless: use `audio.json` (by_surah URLs) + `source_start_ms`/`source_end_ms` timestamps
   - For verse-by-verse: use HF dataset or `audio.json` (by_ayah URLs) + `clip_start_ms`/`clip_end_ms` timestamps

### Layer 2: Hugging Face Dataset (Exists Today — Enhance)

**Audience:** Researchers, ML engineers, app developers, anyone needing structured access.

**What stays the same:**
- Embedded MP3 audio per verse
- Word-level timestamps and segments (clip-relative)
- Config=riwayah, split=reciter

#### Enhancement A: Three New Columns on Verse Rows

Add columns that bridge the gap between verse clips and original chapter audio. All three values are already computed during `build_reciter.py` but currently discarded:

| New Column | Type | Description |
|------------|------|-------------|
| `source_url` | `string` | Original CDN audio URL (chapter or verse) |
| `source_offset_ms` | `int32` | Clip start position in the source audio |
| `audio_category` | `string` | `"by_surah"` or `"by_ayah"` — how to interpret the source URL |

**No `source_end_ms` or `source_duration_ms` needed** — the embedded audio's own duration gives you the clip length.

**Parquet overhead of these columns is negligible.** Measured via pyarrow: the `source_url` column (6,236 rows with only 114 unique URLs for a by_surah reciter) compresses to **972 bytes** (~1 KB) thanks to parquet dictionary encoding. All three columns combined add ~32 KB to a 1.5 GB dataset — 0.002% overhead. The URL "duplication" across verses of the same surah is a non-issue.

**Usage — gapped playback (verse clips):**
```python
verse = ds[0]
# Play embedded audio directly — timestamps are already clip-relative
Audio(verse["audio"]["array"], rate=verse["audio"]["sampling_rate"])
print(verse["word_timestamps"])  # [[1, 0, 400], [2, 400, 800]]
```

**Usage — gapless playback (full chapter):**
```python
# All verses of surah 1 share the same source_url (for by_surah reciters)
fatiha = ds.filter(lambda x: x["surah"] == 1)
chapter_url = fatiha[0]["source_url"]  # https://server8.mp3quran.net/afs/001.mp3

# Convert clip-relative timestamps to chapter-relative
for verse in fatiha:
    offset = verse["source_offset_ms"]
    for word_idx, start, end in verse["word_timestamps"]:
        abs_start = start + offset
        abs_end = end + offset
        # Use abs_start/abs_end to seek within the chapter audio stream
```

**Usage — via HF `/filter` API (no download):**
```bash
# Get verse 2:255 with source info — one HTTP call
GET /filter?dataset=hetchyy/quranic-universal-ayahs\
  &config=hafs_an_asim&split=minshawy_murattal\
  &where="surah"=2 AND "ayah"=255&offset=0&length=1
# Response includes source_url, source_offset_ms, audio_category
# alongside timestamps and a signed URL for the verse clip
```

#### Enhancement B: `sources` Config — Reciter Discovery and URL Templates

A new lightweight config (no audio column) covering **all 350+ reciters**, not just the timestamped ones. One row per reciter.

**Purpose:** Let apps discover reciters, show a picker, and construct audio URLs directly — without downloading any audio data or navigating the GitHub repo.

**Schema:**
| Column | Type | Example |
|--------|------|---------|
| `reciter` | `string` | `mishary_alafasi` |
| `name_en` | `string` | `Mishary Alafasi` |
| `name_ar` | `string` | `مشاري العفاسي` |
| `riwayah` | `string` | `hafs_an_asim` |
| `style` | `string` | `murattal` |
| `audio_category` | `string` | `by_surah` |
| `source` | `string` | `mp3quran` |
| `url_template` | `string` | `https://server8.mp3quran.net/afs/{surah:03d}.mp3` |
| `coverage_surahs` | `int32` | `114` |
| `coverage_ayahs` | `int32` | `6236` |
| `has_timestamps` | `bool` | `true` |

**Feasibility validated:** 380 out of 381 audio manifests follow a templatable URL pattern — the template approach works for virtually all reciters.

**URL template format:**
- By-surah: `https://server8.mp3quran.net/afs/{surah:03d}.mp3` — replace `{surah:03d}` with zero-padded surah number
- By-ayah: `https://everyayah.com/data/Minshawy_Murattal_128kbps/{surah:03d}{ayah:03d}.mp3` — replace both `{surah:03d}` and `{ayah:03d}`

**Usage — app reciter picker:**
```python
# Tiny download, instant — no audio data
sources = load_dataset("hetchyy/quranic-universal-ayahs", "sources", split="train")

# Show all Hafs reciters with murattal style
murattal = sources.filter(lambda r: r["style"] == "murattal" and r["riwayah"] == "hafs_an_asim")
for r in murattal:
    print(f"{r['name_en']} ({r['coverage_surahs']} surahs, timestamps: {r['has_timestamps']})")
```

**Usage — direct CDN audio (bypasses HF rate limits):**
```python
reciter = sources.filter(lambda r: r["reciter"] == "mishary_alafasi")[0]
url = reciter["url_template"].format(surah=2)
# → https://server8.mp3quran.net/afs/002.mp3
# Fetch directly from CDN — no HF rate limits, no signed URLs, no expiry
```

**Why this is a separate config, not extra columns on verse rows:**
- Covers all 350+ reciters, not just the 2–3 with timestamps
- One row per reciter (not one per verse) — completely different granularity
- Tiny parquet file — instant to load as a lookup table
- No duplication of template URL across 6,236 verse rows

#### Enhancement C: Parquet-Only Access Documentation

For non-Python users, document how to read parquet files directly (Arrow, DuckDB, Spark) and extract audio bytes. The HF datasets-server also exposes a `/parquet` endpoint listing all parquet file URLs for direct download.

#### Scaling Characteristics

**Adding more reciters does not degrade query performance.** Each config+split maps to independent parquet file(s). The HF datasets-server `/rows` and `/filter` endpoints query per-split parquet files — they never touch other splits. At 6,236 rows per reciter (~1.5 GB), each split fits in 1–2 parquet row groups with O(1) offset access.

**5 GB indexing threshold:** The datasets-server fully indexes the first 5 GB of a dataset. Beyond that, filter responses may include `partial: true`. At ~1.5 GB per timestamped reciter, this threshold is reached around 3 reciters — but since each split is queried independently, this should not affect per-split row access in practice. The `sources` config (metadata-only, kilobytes) is unaffected.

### Layer 3: REST API + CDN (New — Build When Needed)

**Audience:** Production apps needing low-latency, gapless playback for end users.

**This is the most complex layer and should only be built when there is clear demand.** The HF dataset and raw data layers serve most use cases. Build this when:
- Multiple production apps are hitting third-party CDNs and need reliability
- The project has the infrastructure budget and maintenance capacity
- Gapless playback is confirmed as a top user need

#### API Design (When Ready)

**Principles:**
- Audio-first: return audio bytes, not JSON-wrapped base64
- HTTP semantics: support `Range` headers for seeking, `Accept` for format negotiation
- Cacheable: every response has stable URLs suitable for CDN caching
- Simple addressing: `/{reciter}/{surah}:{ayah}` for verses, `/{reciter}/{surah}` for chapters

**Endpoints:**

```
# Individual verse audio (gapped — trimmed clip)
GET /v1/audio/{reciter}/{surah}:{ayah}
    → audio/mpeg (MP3 bytes)
    Headers: Content-Length, Accept-Ranges: bytes, Cache-Control: public, max-age=31536000
    Query: ?format=mp3|opus|wav (default: mp3)

# Full chapter audio (gapless — original recording)
GET /v1/audio/{reciter}/{surah}
    → audio/mpeg
    Headers: Accept-Ranges: bytes (supports HTTP Range for seeking)
    Query: ?format=mp3|opus

# Verse timestamps (for use with chapter audio)
GET /v1/timestamps/{reciter}/{surah}:{ayah}
    → application/json
    Response: { "words": [[1, 560, 960], ...], "source_offset_ms": 560 }

# Chapter timestamps (all verses in a surah)
GET /v1/timestamps/{reciter}/{surah}
    → application/json
    Response: { "verses": { "1": {...}, "2": {...}, ... } }

# Reciter metadata
GET /v1/reciters
GET /v1/reciters/{reciter}
```

**Format considerations:**

| Format | Bitrate | Quality | Browser support | Size per verse |
|--------|---------|---------|-----------------|----------------|
| MP3 128k | 128kbps | Good | Universal | ~15–50KB |
| Opus 64k | 64kbps | Equal to MP3 128k | Modern browsers | ~7–25KB |
| Opus 32k | 32kbps | Acceptable | Modern browsers | ~4–12KB |

Opus at 64kbps matches MP3 128kbps quality at half the size. For a CDN-backed API, offering both MP3 (compatibility) and Opus (efficiency) is worthwhile. The HF dataset should stay MP3 for universal compatibility.

#### CDN Architecture

```
Client → CDN Edge (Cloudflare/BunnyCDN) → Origin (Object Storage)
                                              ↑
                                    Populated by build pipeline
```

**Origin storage structure:**
```
/audio/
  /{reciter}/
    /chapters/
      {surah}.mp3          # Gapless chapter audio (from original CDN, cached)
      {surah}.opus          # Transcoded to Opus
    /verses/
      {surah}_{ayah}.mp3    # Trimmed verse clips (from HF dataset build)
      {surah}_{ayah}.opus   # Transcoded to Opus
```

**Cost estimate** (rough, per reciter):
- ~1.5GB MP3 audio per reciter (chapter-level)
- ~1.5GB verse-level clips
- With Opus: ~0.75GB per format
- 10 reciters ≈ 30–45GB storage total
- At scale: dominated by bandwidth, not storage

**Build pipeline:**
1. Source chapter audio from `by_surah` manifests → store in object storage
2. Source verse clips from HF dataset build → store in object storage
3. Optionally transcode to Opus via ffmpeg
4. CDN pulls from object storage with long cache TTLs (audio is immutable once released)

---

## Gapless vs Gapped: Decision Framework

| Use Case | Recommended | How (with proposed enhancements) |
|----------|-------------|----------------------------------|
| Listen to full surah | **Gapless** | `source_url` (chapter) + `source_offset_ms` for verse seeking |
| Tap a verse to hear it | **Gapped** | Embedded `audio` column or `source_url` (by_ayah) |
| Memorization (repeat verse) | **Gapped** | Loop embedded verse clip |
| Research / ASR training | **Gapped** | `load_dataset()` — clean, labeled segments |
| Verse-by-verse with transitions | **Gapless** | Stream chapter audio, use offsets for verse boundaries |
| Offline mobile app | **Both** | Download chapter audio + all verse timestamps with offsets |

**The key insight:** gapless and gapped aren't alternatives — they serve different purposes and apps often need both. The architecture should make both easy.

**Important limitation:** Gapless playback is only possible for **by_surah** reciters, where the original recording is a continuous chapter. For **by_ayah** reciters (e.g. everyayah.com), each verse was recorded or cut separately — there is no gapless source. The `audio_category` column lets developers detect this and adjust their UI accordingly (e.g. hide "continuous play" mode for by_ayah reciters, or fall back to concatenated playback with crossfade).

---

## Recommendation: Phased Implementation

### Phase 1: HF Dataset Enhancements (Immediate)

Low effort, high impact. No new infrastructure needed.

**1a. Add 3 columns to verse rows** (`build_reciter.py` change — ~15 lines):
   - `source_url` (string) — original CDN audio URL
   - `source_offset_ms` (int32) — clip start position in source audio
   - `audio_category` (string) — `"by_surah"` or `"by_ayah"`
   - All values already computed during the build; just need to stop discarding them.

**1b. Add `sources` config** (new build script — ~100 lines):
   - One row per reciter across all 350+ reciters
   - Includes URL templates, metadata, coverage, timestamp availability
   - Derived from existing `data/audio/` manifests + `reciters_index.json`

**1c. Add `clip_offset_ms` to GitHub release timestamp files** — same bridge value, for non-HF users.

**1d. Write a "Data Access Guide"** documenting:
   - The three layers and when to use each
   - How to achieve gapless playback (chapter audio + source timestamps)
   - How to achieve verse-by-verse playback (HF dataset)
   - How to use the `/filter` API for quick verse lookup without downloading
   - How to use `sources` config + URL templates for direct CDN access
   - Code examples for common use cases (Python, JavaScript, mobile)
   - Timestamp frame of reference explanation

### Phase 2: Validate and Prototype (Short-term)

The HF `/filter` API and `sources` config together cover most access patterns. Before building a custom API, validate this in practice:

1. **Benchmark HF `/filter` latency** — measure actual end-to-end time (metadata + audio fetch) for random verse access from multiple regions. Key metrics: TTFB for metadata, TTFB for audio CDN URL, total time to first audio byte.

2. **Prototype gapless web player** — build a minimal player using:
   - `sources` config to get chapter URL template
   - Verse rows (via `/filter`) for `source_offset_ms` + word timestamps
   - HTML5 `<audio>` with `currentTime` seeking for verse navigation
   - Does it work well enough without a custom API?

3. **Test direct CDN reliability** — for the top 5 sources (mp3quran, everyayah, qul, surah-quran, archive.org), measure availability, latency, and CORS headers from common user regions.

4. **Survey users** — what are the top apps being built? What are their actual latency requirements? Do they need gapless, gapped, or both?

### Phase 3: API + CDN (When Justified)

Only build this when:
- Phase 2 benchmarks show HF dataset latency is insufficient for production apps
- Third-party CDN reliability becomes a real problem (not hypothetical)
- There are multiple production apps that would benefit

When building:
1. Start with a thin proxy that reads from HF dataset parquet + audio manifests
2. Add CDN caching in front (Cloudflare Workers or BunnyCDN)
3. Add Opus transcoding as a background job
4. Add chapter-level audio endpoints backed by cached copies of manifest URLs
5. Version the API (`/v1/`) from day one

---

## Summary: Recommended Access Pattern by Audience

| Audience | Layer | Access Method | Audio Source | Gapless? |
|----------|-------|--------------|-------------|----------|
| **ML researcher** | Layer 2 | `load_dataset()` in Python | Embedded verse clips | No (not needed) |
| **Data scientist** | Layer 2 | Parquet via DuckDB/Arrow | Embedded verse clips | No |
| **App: verse playback** | Layer 2 | HF `/filter` API for timestamps, `sources` config → direct CDN for audio | CDN via URL template | No |
| **App: chapter playback** | Layer 2 | `sources` config → chapter CDN URL + `/filter` for `source_offset_ms` | CDN chapter audio | Yes |
| **Offline mobile app** | Layer 1+2 | Download release zips + chapter audio from manifests | Local files | Yes |
| **Web Quran player** | Layer 2 (→ 3 if needed) | `sources` config for discovery + CDN for audio + HF for timestamps | CDN direct | Yes |
| **Memorization app** | Layer 2 | HF `/filter` for verse clip + timestamps | Embedded or CDN | No |
| **Custom pipeline** | Layer 1 | Raw files, full control | Developer's choice | Developer's choice |
| **Reciter browser/picker** | Layer 2 | `sources` config (tiny, instant) | N/A | N/A |

### Two Paths to Gapless Playback

With the proposed enhancements, developers have two clear paths to gapless chapter playback:

**Path A: GitHub Releases (offline-first)**
1. Download reciter zip from GitHub release → get `timestamps.json` + `audio.json`
2. `audio.json` has chapter URLs → fetch/cache chapter audio
3. `timestamps.json` has source-relative timestamps → seek within chapter audio

**Path B: HF Dataset (API-first)**
1. Load `sources` config → get reciter's `url_template` + `audio_category`
2. Construct chapter URL from template → stream chapter audio from CDN
3. Query verse rows (via `/filter` or `load_dataset`) → use `source_offset_ms` + `word_timestamps` to compute chapter-relative word positions

Both paths arrive at the same result: chapter audio + absolute timestamps for verse-level seeking. Path A is self-contained (no API calls at runtime). Path B requires no upfront downloads.

### Key Insight

The HF dataset is the right default for most programmatic use. The primary gaps are not latency — they are **the gapless playback story** (solved by `source_offset_ms` + `source_url` columns) and **reciter discovery** (solved by the `sources` config). Phase 1 addresses both with zero infrastructure cost. A custom API (Phase 3) should only be built when CDN reliability or rate limits become real bottlenecks for production apps.

---

## Appendix: External Reference — spa5k/quran-timings-api

Investigated [spa5k/quran-timings-api](https://github.com/spa5k/quran-timings-api) as a reference for API/CDN design. Key observations:

**Architecture:** Not a running API — a CLI pipeline (Python/Typer) that generates static JSON files committed to the repo, intended to be served via GitHub raw URLs or JSDelivr. No dynamic server.

**Alignment pipeline (interesting):** Multi-engine forced alignment with candidate fusion:
- NeMo (NVIDIA FastConformer) → WhisperX → MFA, tries all engines and picks best per-ayah result via composite scoring
- Iterative refinement for weak ayahs with expanded audio windows (up to 3 passes)
- Detailed QC provenance: boundary error medians, engine selection scores, quantization step detection

**Current state: very early.** 3 reciters enabled (out of 201 cataloged), covering only surahs 65-114. Cloudflare Worker and JSDelivr CDN both non-functional (403). Quality concerns in output (20ms word durations, 300ms+ boundary error medians).

**Data sources they have that we don't:**
- QuranicAudio.com (110 reciters) — potential future source for our manifests
- Quran.com verse segment API (12 reciters)

**What they lack that we have:** 381 reciters (vs 3), 14 riwayat, letter/phoneme-level timestamps, gapless playback design, HF dataset with embedded audio, working infrastructure.

**Takeaways for our project:**
1. **Multi-engine fusion** — worth studying if we need to improve alignment robustness for difficult reciters. Their approach of running multiple engines and scoring candidates could complement our current single-engine (MFA via Kalpy) pipeline.
2. **QuranicAudio.com** as a future audio source — 110 additional reciters with surah-level audio.
3. **Static JSON on CDN** is a viable MVP for API delivery but doesn't scale well in git (repo size limits on JSDelivr, no dynamic filtering). Validates our decision to use HF parquet + datasets-server instead.
4. **Their project does not solve our needs** — too limited in coverage, no gapless support, no audio hosting. But the alignment pipeline design is a useful reference.
