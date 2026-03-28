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
| Row-level HTTP API | 200–500ms | Via HF datasets server `/rows` endpoint |

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

### Gap 2: Timestamp Frame of Reference Is Fragmented

**The problem:** Timestamps exist in two frames of reference:
1. **Clip-relative** (HF dataset `word_timestamps`): `start_ms=0` means start of the trimmed verse clip
2. **Source-relative** (GitHub releases `timestamps.json`): `start_ms` is relative to the original audio file (chapter or verse recording from the CDN)

For gapless chapter playback, developers need source-relative timestamps. For individual verse clip playback, they need clip-relative. Currently you have to know which is which and pair the right timestamps with the right audio. This is not documented.

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
| HF datasets server API | 200–500ms | Not designed for audio serving; returns base64 |
| Third-party CDN (by_ayah) | 100–500ms | Depends on CDN availability and user location |
| Third-party CDN (by_surah) | 100–300ms + seek | Need byte-range or time-offset seeking |

None of these is ideal for a production app wanting instant verse-by-verse playback without pre-downloading gigabytes.

### Gap 5: No Unified Developer Experience

**The problem:** A developer wanting to build a Quran app today has to:
1. Understand three separate systems (HF dataset, GitHub releases, audio manifests)
2. Know which timestamps go with which audio
3. Decide between gapped and gapless themselves
4. Handle CDN failover themselves
5. Build their own caching layer

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

**Audience:** Researchers, ML engineers, anyone using Python for batch processing.

**What stays the same:**
- Embedded MP3 audio per verse
- Word-level timestamps and segments (clip-relative)
- Config=riwayah, split=reciter

**What to add:**

1. **`source_offset_ms` column** — the offset from source audio start to clip start. This single number lets anyone reconstruct source-relative timestamps:
   ```python
   verse = ds[0]
   # Clip-relative (for playing the embedded audio):
   print(verse["word_timestamps"])  # [[1, 0, 400], [2, 400, 800]]

   # Source-relative (for seeking in chapter audio):
   offset = verse["source_offset_ms"]  # 560
   for w, start, end in verse["word_timestamps"]:
       print(w, start + offset, end + offset)  # [1, 560, 960], [2, 960, 1360]
   ```

2. **`audio_url` column** (optional, string) — the source URL from the audio manifest. Enables:
   - Fetching original (non-trimmed) audio for gapless playback
   - Verifying/refreshing audio if needed
   - Using the HF dataset as a unified index even for gapless use cases

3. **Parquet-only access documentation** — for non-Python users, document how to read parquet files directly (Arrow, DuckDB, Spark) and extract audio bytes.

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

| Use Case | Recommended | Why |
|----------|-------------|-----|
| Listen to full surah | **Gapless** (chapter audio + source-relative timestamps) | Natural flow, no artifacts |
| Tap a verse to hear it | **Gapped** (verse clips from HF dataset or API) | Fast, self-contained |
| Memorization app (repeat verse) | **Gapped** | Loop a single clip |
| Research / ASR training | **Gapped** (HF dataset) | Clean, labeled segments |
| Verse-by-verse with transitions | **Gapless** with verse seeking | Smooth transitions between verses |
| Offline mobile app | **Both** — download chapter audio + verse timestamps | Gapless playback, verse-level seeking |

**The key insight:** gapless and gapped aren't alternatives — they serve different purposes and apps often need both. The architecture should make both easy.

---

## Recommendation: Phased Implementation

### Phase 1: Documentation + Metadata Enhancements (Immediate)

Low effort, high impact. No new infrastructure needed.

1. **Add `source_offset_ms` to the HF dataset schema** — a single integer column bridging the two timestamp frames. Requires updating `build_reciter.py` to compute and include it.

2. **Add `audio_url` to the HF dataset schema** — the source URL for each verse's audio. Already available in the build pipeline (`entry["audio"]`).

3. **Write a "Data Access Guide"** documenting:
   - The three layers and when to use each
   - How to achieve gapless playback (chapter audio + source timestamps)
   - How to achieve verse-by-verse playback (HF dataset)
   - Code examples for common use cases (Python, JavaScript, mobile)
   - Timestamp frame of reference explanation

4. **Add `clip_offset_ms` to GitHub release timestamp files** — same bridge value, for non-HF users.

### Phase 2: Evaluate HF Dataset Adequacy (Short-term)

Before building a custom API, measure whether the HF dataset is sufficient for most use cases:

1. **Benchmark HF datasets server API** — measure actual latency for random verse access via the HTTP API from multiple regions.

2. **Test HF parquet direct access** — can a JavaScript app read individual verses from parquet over HTTP using Apache Arrow JS? What's the latency?

3. **Survey users** — what are the top 5 apps being built? What are their actual latency requirements?

4. **Prototype gapless playback** — build a minimal web player using chapter audio from manifests + source-relative timestamps. Does it work well enough without a custom API?

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

| Audience | Layer | Access Method | Gapless? |
|----------|-------|--------------|----------|
| **ML researcher** | Layer 2 | `load_dataset()` in Python | No (not needed) |
| **Data scientist** | Layer 2 | Parquet via DuckDB/Arrow | No |
| **Offline mobile app** | Layer 1 | Download release zips + chapter audio from manifests | Yes |
| **Web Quran player** | Layer 3 (or Layer 1 + manifest CDNs) | REST API or direct CDN | Yes |
| **Memorization app** | Layer 2 or 3 | Verse clips | No |
| **Custom pipeline** | Layer 1 | Raw files, full control | Developer's choice |

The HF dataset is the right default for most programmatic use. The gap isn't latency for most cases — it's **documentation and the gapless playback story**. Phase 1 (documentation + `source_offset_ms`) addresses the biggest pain point with zero infrastructure cost.
