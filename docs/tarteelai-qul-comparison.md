# TarteelAI QUL vs Quranic Universal Audio: Segments & Timestamps Analysis

**Date:** 2026-03-28

Deep comparison of [TarteelAI/quranic-universal-library](https://github.com/TarteelAI/quranic-universal-library) (QUL) against this project (QUA) — focused on segments, timestamps, quality, structure, editing, and reliability.

---

## 1. Architecture & Philosophy

| Aspect | **QUL (TarteelAI)** | **QUA (This Project)** |
|--------|---------------------|------------------------|
| Stack | Ruby on Rails + PostgreSQL CMS | Python pipeline + JSON flat files |
| Approach | Database-driven, web admin panel | File-driven, CLI validators + Flask inspector |
| Segment storage | PostgreSQL `audio_segments` table | JSON files (`segments.json`, `detailed.json`) |
| Timestamp storage | DB columns + JSONB `segments` column | JSON files (`timestamps.json`, `timestamps_full.json`) |
| Granularity | Word-level only | Word + letter + phoneme (3 tiers) |
| Alignment engine | pydub dBFS silence detection | MFA forced alignment (kalpy/CLI/python_api) |
| Scope | Full CMS (translations, tafsirs, scripts, audio) | Audio alignment specialist |

QUA has significantly deeper granularity (phoneme/letter-level) and a more sophisticated alignment pipeline. QUL is broader in scope but shallower on audio timing.

---

## 2. Timestamp Quality & Structure

### QUL

- **Verse-level**: `timestamp_from`, `timestamp_to`, `timestamp_median`, `duration_ms` (integers, milliseconds)
- **Word-level**: JSONB `segments` column: `[[word_idx, start_ms, end_ms], ...]`
- Optional metadata per word: `[word_idx, start_ms, end_ms, {waqaf: true}]`
- **No letter or phoneme tier** — stops at word level
- **Validation**: `validate_segments_data` checks missing ayahs, malformed timestamps, word count mismatches, excessive repetitions (danger/warning/info severity levels)

### QUA

- **Word-level**: `timestamps.json` — `{verse_key: [[word_idx, start_ms, end_ms], ...]}`
- **Letter-level**: `timestamps_full.json` — `[[char, start_ms, end_ms], ...]` per word
- **Phoneme-level**: `timestamps_full.json` — `[[phone, start_ms, end_ms], ...]` per word
- **Compound keys**: `"37:151:3-37:152:2"` for cross-verse spans (not supported in QUL)
- **Validation**: 8 deep checks including temporal plausibility, forward gap detection, letter/phoneme integrity, inter-verse overlap detection, cross-file consistency

**Verdict:** QUA's 3-tier hierarchy (word → letter → phoneme) with compound key support is a significant advantage for karaoke, tajweed highlighting, and research.

---

## 3. Segment Boundary Detection

### QUL Approach: Audio-Level dBFS Analysis

QUL has a dedicated `tools/segments/` pipeline with a notable boundary refinement approach:

**Per-gap adaptive thresholds** (`calculate_gap_thresholds.py`):
- Instead of one global silence threshold, computes per-gap thresholds using percentile-based volume analysis
- Samples each gap at 50ms intervals, computes 10th/25th/50th percentile of dBFS readings
- Formula: `threshold = gap_volume - offset_dB` (default offset: 5dB)
- Handles complete silence (`-inf` → `-80.0 dBFS`) separately
- Selects the maximum threshold across strategies to minimize false positives

**Gap volume diagnostics** (`check_gap_volume.py`):
- Tests each gap against multiple thresholds: -30, -35, -40, -45, -50, -60, -68 dBFS
- Reports "DETECTABLE" vs "NOT DETECTABLE" per gap per threshold
- Recommends custom per-gap thresholds

**5-step iterative refinement** (`segment_boundary_workflow.sh`):
1. Export current boundaries from DB to JSON
2. Calculate per-gap optimal silence thresholds
3. Detect silences using `find_boundary_silences.py` (supports absolute, relative, and per-gap thresholds)
4. Refine boundaries in database
5. Generate visualization for review

### QUA Approach: ML-Based VAD + ASR

- VAD model (`obadx/recitation-segmenter-v2`) with presets: MUJAWWAD (600/1500/300ms), MURATTAL (200/750/100ms), FAST (75/750/40ms)
- ASR model for text matching with confidence scoring
- Three parameters: `min_silence_ms`, `min_speech_ms`, `pad_ms`
- MFA forced alignment for precise phoneme-level boundaries

**Key difference**: QUL uses audio-level dBFS analysis for boundary refinement. QUA uses ML-based segmentation. These approaches are complementary — QUL's adaptive thresholds could serve as a post-processing refinement step on QUA's VAD output.

---

## 4. Data Quality & Validation

### QUL

| Feature | Details |
|---------|---------|
| Model-level validation | `validate_segments_data` — danger/warning/info severity |
| Auto-fix pipeline | Rake task swaps inverted times, inserts missing words, fixes overlaps |
| Change tracking | `Audio::ChangeLog` model with date, description, RSS description |
| Segment locking | `segment_locked` boolean prevents accidental edits |
| Percentile tracking | 101-point timestamp percentile distribution for seeking |
| Repetition detection | `find_repeated_segments` identifies recurring word patterns |
| Arabic text-weighted time division | Assigns character scores (alif-madda=6pts, regular=1pt) for proportional time allocation when inserting missing words |
| Export validation | Tarteel export verifies 6,236 segments, 3-element word arrays |
| CI/CD | Only CodeQL security scanning — no automated segment validation |

### QUA

| Feature | Details |
|---------|---------|
| 3 standalone validators | `validate_audio.py` (pre-extraction), `validate_segments.py` (10 checks), `validate_timestamps.py` (8 checks) |
| CI integration | GitHub Actions auto-validates PRs modifying segments or audio |
| Cross-file consistency | Validates segments ↔ timestamps ↔ detailed alignment |
| Inspector UI | Interactive validation with categorized error buckets |
| Edit history validation | `validate_edit_history.py` prevents regression on merge |
| Multi-reciter comparison | Summary tables when validating parent directories |
| Post-merge automation | Generates edit summaries, updates linked issues |

**Verdict:** QUA's validation is more thorough and CI-automated. QUL has no segment validation in CI. However, QUL's segment locking, change logs, auto-fix pipeline, and Arabic-weighted time division are useful additions.

---

## 5. Inspector / Editing Tools

### QUL

- Rails admin panel with "Validate segments" button and severity-colored modal
- `tools/plot_segments_timeline.html` — interactive timeline visualization
- Segment builder tool linked from admin (`segment_builder_ayah_audio_file_path`)
- No standalone inspector application

### QUA

- Flask web app (`inspector/`) with 3 tabs: Timestamps, Segments, Audio
- Interactive waveform with karaoke-style highlighting
- 8 validation categories in expandable accordions (structural errors, missing verses, missing words, failed alignments, low confidence, oversegmented, cross-verse, audio bleeding)
- Editing: drag handles, split/merge segments, edit reference text, auto-fix missing words, ignore issues
- Auto-revalidation on save
- `validation.log` written per reciter

**Verdict:** QUA's inspector is far more capable. QUL's admin panel is basic in comparison.

---

## 6. Data Formats & Export

### QUL

QUL supports three export formats:

**JSON** (per-surah):
```json
[
  {"ayah": 1, "start": 0, "end": 5230, "words": [[1, 0, 1200], [2, 1200, 2800]]}
]
```

**CSV**:
```csv
sura,ayah,start_time,end_time,words
1,1,0,5230,"[[1,0,1200],[2,1200,2800]]"
```

**SQLite** (`timings` table):
```
sura | ayah | start_time | end_time | words
```

**Flexible import**: Accepts multiple column naming conventions (`timestart`→`start_time`, `wordtiming`→`words`) and word data formats (JSON arrays or colon-delimited).

**Contiguity enforcement on export**: First ayah starts at 0ms, verse boundaries made contiguous (`start = max(prev_end + 1, current_from)`), last word end adjusted to match verse end. No gaps or overlaps.

### QUA

- JSON only (`segments.json`, `detailed.json`, `timestamps.json`, `timestamps_full.json`)
- Rich `_meta` blocks with pipeline provenance (model versions, parameters, creation timestamps)
- Compound verse keys for cross-verse spans

---

## 7. Adoptable Features from QUL

### A. Per-Gap Adaptive Silence Thresholds — High Impact

**What**: Post-process VAD output by analyzing actual dBFS profile of each inter-segment gap and computing per-gap detection thresholds.

**Implementation**:
1. New script (e.g. `tools/refine_boundaries.py`) that:
   - For each pair of consecutive segments, extracts the audio gap
   - Samples volume at 50ms intervals, computes 10th percentile dBFS
   - Sets threshold = 10th percentile − 5dB
   - Re-evaluates segment boundaries
   - Flags gaps where silence is "NOT DETECTABLE" for inspector review
2. Integrate as optional refinement step after VAD in `quranic_universal_aligner/`
3. Add results to `detailed.json` (per-gap dBFS readings, threshold used)

### B. Arabic Text-Weighted Time Division — Medium Impact

**What**: When inserting missing word segments, allocate time proportionally based on Arabic character complexity scores instead of equal division.

**Implementation**:
- Character scoring: alif-madda (6pts), shadda combinations (6pts), regular letters (1pt), diacritics (0.5pt)
- Add `calculate_word_score(text)` utility
- Use in inspector auto-fix and in `validate_segments.py` missing-word suggestions

### C. Segment Locking — Medium Impact

**What**: Prevent accidental edits on verified recitations.

**Implementation**:
- Add `"locked": true` to `_meta` in `segments.json` and `timestamps.json`
- Inspector: show lock icon, disable editing controls, require explicit unlock
- Validators: warn if locked data is modified in PR

### D. Auto-Fix Pipeline — Medium Impact

**What**: Automated batch fixes for common issues (inverted times, missing words, overlapping boundaries).

**Implementation**:
- New script `tools/auto_fix_segments.py` that sequentially:
  1. Swaps inverted `time_from > time_to`
  2. Removes out-of-order word segments
  3. Inserts missing words using Arabic text-weighted time division
  4. Adjusts overlapping word boundaries
  5. Extends last word to match verse end
- Run as optional step before validation

### E. Repetition Detection — Low-Medium Impact

**What**: Detect when a reciter repeats word sequences within an ayah (common in mujawwad).

**Implementation**:
- Add check in `validate_segments.py` looking for duplicate word-index patterns within a verse
- Flag in inspector as a distinct category

### F. Multi-Format Export — Low Impact

**What**: Add CSV and SQLite export alongside JSON.

**Implementation**:
- New `tools/export_segments.py` with `--format json|csv|sqlite` flag
- CSV: `surah,ayah,start_time,end_time,words`
- SQLite: `timings` table indexed on `(reciter, surah, ayah)`

---

## 8. Inspector Improvement Recommendations

### 8a. Gap Volume Visualization

Overlay dBFS readings in gaps between segments on the waveform view. Color-code: green (clearly silent), yellow (marginal), red (likely speech in gap). Helps editors spot boundary errors at a glance.

### 8b. Segment Lock/Unlock Toggle

Lock button per reciter. When locked: editing controls disabled, save requires explicit unlock confirmation, lock state persisted in `_meta`.

### 8c. Diff View Before Save

Before saving edits, show a summary: "Changed 5 segments in 3 verses. Timing shifted by avg 45ms. Word coverage: 100% → 100%." Display as a confirmation dialog to prevent accidental regressions.

### 8d. Batch Validation Dashboard

New tab showing all reciters in a comparison table (like CLI multi-reciter mode, but in the web UI). Columns: reciter, verse coverage %, word coverage %, error count, warning count, last validated.

### 8e. Confidence Heatmap

Visual heatmap of confidence scores across 114 surahs × verses. Red cells = low confidence. Clicking a cell jumps to that verse in the segments tab.

### 8f. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `←` / `→` | Nudge segment boundary ±10ms |
| `Shift+←` / `Shift+→` | Nudge ±50ms |
| `Space` | Play/pause |
| `S` | Split at cursor |
| `M` | Merge with next |
| `Tab` | Next segment |

### 8g. Export for Cross-Project Sharing

Export endpoints producing QUL-compatible formats (CSV with `verse_key, timestamp_from, timestamp_to, segments_json`) to enable data sharing between projects.

---

## 9. Summary Matrix

| Feature | QUL | QUA | Winner / Action |
|---------|-----|-----|-----------------|
| Timestamp granularity | Word-only | Word+Letter+Phoneme | **QUA** — keep |
| Alignment method | dBFS silence detection | MFA forced alignment | **QUA** — adopt adaptive thresholds as post-processing |
| Segment validation | Basic (model-level) | Comprehensive (3 validators, CI) | **QUA** — add repetition detection |
| CI/CD for segments | None (CodeQL only) | GitHub Actions on PRs | **QUA** — already ahead |
| Change tracking | DB ChangeLog model | File-based edit history | **Adopt**: structured audit trail from QUL |
| Segment locking | `segment_locked` boolean | None | **Adopt**: add lock flag |
| Per-gap adaptive thresholds | Yes (Python tools) | No | **Adopt**: high-impact improvement |
| Arabic text-weighted time division | Yes | No | **Adopt**: smarter missing-word insertion |
| Auto-fix pipeline | Rake task (5 steps) | Manual via inspector | **Adopt**: batch auto-fix script |
| Repetition detection | `find_repeated_segments` | No | **Adopt**: useful for mujawwad |
| Inspector/editing UI | Basic admin panel | Full Flask app + waveform | **QUA** — enhance with recommendations above |
| Cross-verse handling | Basic | Compound keys | **QUA** |
| Export formats | JSON, CSV, SQLite | JSON only | **Adopt**: multi-format export |
| Data portability | DB-dependent | Self-contained JSON files | **QUA** — more portable |
| Flexible import | Multiple column naming conventions | Strict schema | **Consider**: flexible import parsing |
| Contiguity enforcement | On export (no gaps/overlaps) | Not enforced | **Adopt**: enforce contiguous verse boundaries |
