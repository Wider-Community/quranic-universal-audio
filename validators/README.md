# Validators

Standalone CLI scripts that bookend the extraction and timestamp pipelines. Each can run against a single reciter directory (detailed report) or a parent directory containing multiple reciters (summary comparison table). All validators use `data/surah_info.json` as ground truth and write a `validation.log` file alongside their output.

## Overview

| Validator | Stage | Input | Purpose |
|-----------|-------|-------|---------|
| `validate_audio.py` | Pre-extraction | Audio JSON/directory | Checks `_meta` presence, coverage against 114 surahs / 6236 verses, validates URL reachability or local file integrity, flags duplicates |
| `validate_segments.py` | Post-extraction | `segments.json` + `detailed.json` | Checks time ordering, word coverage completeness, segment duration stats, alignment confidence |
| `validate_timestamps.py` | Post-timestamping | `timestamps.json` + `timestamps_full.json` | Validates structural correctness (meta fields, verse key format), word coverage (missing/extra indices), temporal plausibility (negative timestamps, zero-duration words), letter-level integrity, and cross-file consistency with `segments.json` |
| `validate_edit_history.py` | PR gate | `edit_history.jsonl` + `detailed.json` | Validates Inspector edit audit trail integrity before merging segment PRs |

## validate_audio.py

Pre-extraction validator that ensures audio inputs are complete and accessible before running the pipeline.

### Usage

```bash
python validators/validate_audio.py <path>                      # auto-detect & validate
python validators/validate_audio.py <path> --ffprobe            # also probe with ffprobe
python validators/validate_audio.py <path> --no-check-sources   # coverage only
python validators/validate_audio.py <path> --top 50             # show top 50 per category
```

### Input Format Detection

Auto-detects the input format from the given path:

| Format | Detection | Granularity |
|--------|-----------|-------------|
| `sura_json` | `.json` file, keys are plain integers (surah numbers) | Surah-level |
| `verse_json` | `.json` file, keys contain `:` (e.g. `1:1`) | Verse-level |
| `sura_dir` | Directory of audio files with numeric stems | Surah-level |
| `verse_dir` | Directory of audio files with `<sura>_<verse>` stems | Verse-level |

Supported audio extensions: `.mp3`, `.wav`, `.flac`, `.m4a`, `.ogg`.

### Validations Performed

#### 1. Metadata Validation

For JSON inputs, checks that a `_meta` block is present with the required keys: `reciter`, `riwayah`, `audio_category`, `source`, `country`. A missing `_meta` block or missing key is an error (exit code 1). A key that is present but has an empty value is a warning.

#### 2. Coverage Analysis

Checks how many of the expected surahs or verses are present in the input.

**Surah-level** (for `sura_json` / `sura_dir`):
- Reports X / 114 surahs found
- Lists missing surahs by number and name

**Verse-level** (for `verse_json` / `verse_dir`):
- Reports X / 6236 verses found
- Categorizes missing content into fully missing surahs vs partially missing surahs
- Lists specific missing verse numbers for partial surahs

#### 3. Duplicate Detection

Flags any surah or verse key that maps to more than one audio source. Reported as warnings with the list of conflicting sources.

#### 4. URL Reachability (for remote audio)

For inputs that reference URLs:
- Sends parallel HTTP HEAD requests (16 threads, 10s timeout by default)
- Falls back to ranged GET (`Range: bytes=0-0`) if HEAD returns 405
- Reports reachable vs unreachable counts
- Lists each failed URL with its HTTP status or error reason

Configurable via `--max-workers` and `--url-timeout`.

#### 5. Local File Integrity (for local audio)

For inputs that reference local file paths:
- Checks file existence
- Checks file is non-zero bytes
- Optionally probes with `ffprobe` (`--ffprobe` flag):
  - Validates the file is a decodable audio format
  - Extracts and validates duration (must be > 0)
  - Reports ffprobe errors (corrupt files, unrecognized formats)
  - 5-second timeout per file to avoid hanging on problematic files

#### 6. Source Type Classification

Classifies the overall input as `url`, `file`, or `mixed` based on whether sources are HTTP URLs, local paths, or a combination.

### Output

Prints a structured report with sections:
- **Metadata** -- `_meta` field values or error if missing
- **Coverage** -- surah/verse counts and percentages
- **Missing details** -- specific missing surahs or verses (capped by `--top`)
- **Duplicates** -- entries with multiple audio sources
- **Source Validation** -- URL reachability or file integrity results with error details
- **Summary** -- total source count, source type, error and warning counts

The report is saved to `validation.log` in the same directory as the input (or inside the directory for directory inputs). Exit code is 1 if any errors were found.

## validate_segments.py

Post-extraction validator that checks the output of `extract_segments.py` for correctness, completeness, and alignment quality.

### Usage

```bash
python validators/validate_segments.py <reciter_dir>        # single reciter → detailed report
python validators/validate_segments.py <parent_dir>         # all reciter subdirs → summary table
python validators/validate_segments.py <dir> --top 50       # show top 50 failures/low-conf
```

### Input Files

- **`segments.json`** (required) — flat dict of `{verse_key: [[word_from, word_to, time_from_ms, time_to_ms], ...]}` with a `_meta` field containing VAD settings (pad_ms, min_silence_ms, min_speech_ms).
- **`detailed.json`** (optional) — entries array with per-segment confidence scores, ASR phonemes, matched text, and audio source paths. Enables confidence analysis when present.

Both regular verse keys (`"37:151"`) and cross-verse compound keys (`"37:151:3-37:152:2"`) are supported.

### Validations Performed

#### 1. Meta Validation

Checks the `_meta` block for required fields: `pad_ms`, `min_silence_ms`, `min_speech_ms`, `audio_source`.

#### 2. Empty Verse Keys

Flags verse keys with zero segments (error). These would appear as present for coverage but contribute nothing.

#### 3. Time Ordering

Per-segment checks within each verse:
- `time_from < time_to` — flags inverted or zero-duration segments
- No time overlap between consecutive segments — checks that each segment starts after the previous one ends

#### 4. Word Index Validity

- `word_from >= 1` for all segments
- `word_to >= word_from` for regular verse keys
- `word_to >= 1` for cross-verse keys (word ranges span multiple verses)
- Cross-verse keys referencing unknown verses (not in `surah_info.json`) are flagged as errors

#### 5. Verse Coverage

Compares verses present in `segments.json` against the full 6236 verses in `surah_info.json`:
- Reports X / 6236 verses found
- Lists specific missing verses with their expected word counts

#### 6. Word Coverage

For each verse present in the file, checks that every expected word index (1 through `num_words`) is covered by at least one segment:
- **Missing words** — word indices not covered by any segment
- **Extra words** — word indices beyond the expected count for that verse

Cross-verse keys expand coverage tracking across all verses in their range.

#### 7. Segment Duration Statistics

Computes min, median, mean, and max across all segment durations (in ms).

#### 8. True Silence Duration

For multi-segment verses, computes the actual silence between consecutive segments by reversing the VAD padding: `true_pause = (next_start - prev_end) + 2 * pad_ms`. Reports min/median/mean/max.

#### 9. Alignment Confidence (from `detailed.json`)

When `detailed.json` is present:
- **Confidence distribution** — min, median, mean, max of confidence scores
- **Low confidence** — counts segments below 60% and below 80% thresholds
- **Failed alignments** — segments with no matched reference (alignment failure)
- **Empty ASR** — segments that matched a reference but had no recognized phonemes
- **Lowest confidence detail** — lists the N worst segments with their confidence score, reference, time range, audio source, matched text, and ASR phonemes

#### 10. Cross-file Consistency (detailed.json ↔ segments.json)

When `detailed.json` is present, rebuilds the expected `segments.json` verse keys from the detailed entries and compares:
- Verse keys present in one file but not the other
- Segment count mismatches per shared verse key

#### 11. Audio Bleeding (by_ayah only)

For by_ayah audio sources, detects segments whose `matched_ref` points to a different verse than the entry's audio file. This happens when a verse recording contains the tail end of the previous verse or the start of the next one.

### Inspector Integration

The segment validations surface as collapsible accordion panels in the inspector's Segments tab (error section at the top). Each panel lists affected segments with navigation buttons and a "Load All" option to render full cards with waveforms.

| Accordion | Source Validation |
|-----------|-------------------|
| Failed Alignments | Confidence (#9) — segments with no matched reference |
| Missing Verses | Verse coverage (#5) — within covered surahs only |
| Missing Words | Word coverage (#6), with auto-fix for single-word gaps |
| Structural Errors | Meta (#1), empty keys (#2), time ordering (#3), word index validity (#4) |
| Low Confidence | Confidence (#9) — segments below 80% |
| Detected Repetitions | `wrap_word_ranges` set by alignment pipeline |
| May Require Boundary Adjustment | 1-word segments (excluding muqatta'at, single-word verses, standalone words/refs) |
| Cross-verse | `matched_ref` spans multiple ayahs, confidence < 1.0 |
| Audio Bleeding | Audio bleeding (#11) — by_ayah verse mismatch |
| Muqatta'at | Word 1 of a huruf muqatta'at verse, confidence < 1.0 |
| Qalqala | Last letter of matched_text is a qalqala letter, confidence < 1.0 |

## validate_timestamps.py

Checks the output of `extract_timestamps.py` for structural correctness, temporal plausibility, and consistency with the upstream segment pipeline.

### Usage

```bash
python validators/validate_timestamps.py <reciter_dir>        # single reciter → detailed report
python validators/validate_timestamps.py <parent_dir>         # all reciter subdirs → summary table
python validators/validate_timestamps.py <dir> --top 50       # show top 50 issues
```

### Input Files

- **`timestamps.json`** (required) — flat dict of `{verse_key: [[word_idx, start_ms, end_ms], ...]}` with a `_meta` field recording MFA settings.
- **`timestamps_full.json`** (optional) — same structure but words include letter and phoneme sub-arrays: `[word_idx, start_ms, end_ms, [[char, start, end], ...], [[phone, start, end], ...]]`.
- **`segments.json`** (optional, from upstream) — looked up at `data/recitation_segments/<reciter>/` for cross-file boundary checks.

Both regular verse keys (`"5:69"`) and compound cross-verse keys (`"37:151:3-37:152:2"`) are supported throughout.

### Validations Performed

#### 1. Meta Validation

Checks the `_meta` block for required fields: `audio_source`, `method`, `beam`, `retry_beam`, `shared_cmvn`. Also surfaces any MFA alignment failures recorded during extraction (`mfa_failures` array in meta).

#### 2. Verse Coverage

Compares verse keys in the output against the full 6236 verses in `surah_info.json`. Reports missing verses, expanding compound keys across their ayah ranges.

#### 3. Word Coverage

For each verse, checks that all expected word indices (1 through `num_words`) are covered. Reports missing and extra indices. Coverage accumulates across both regular and compound keys targeting the same verse.

#### 4. Forward Gap Detection

Within each verse key's word list, detects non-consecutive jumps in word indices (e.g. word 3 followed by word 6, skipping 4-5). For compound keys, resets the high-water mark at verse boundaries.

#### 5. Temporal Plausibility

Per-word checks:
- **Negative timestamps** — start or end < 0
- **Zero-duration words** — start == end
- **Inverted timestamps** — start > end

Computes word duration statistics (min/median/mean/max) from valid words.

#### 6. Letter and Phoneme Integrity (from `timestamps_full.json`)

When the full format is present:
- Checks for negative or inverted letter timestamps
- Checks for negative or inverted phoneme timestamps
- Checks phoneme ordering within each word (start times should be non-decreasing)

Note: letter duration sums are intentionally not compared to word spans — MFA geminates, idgham, and cross-word assimilation cause letters to overlap or extend beyond word boundaries.

#### 7. Verse Timestamps

Derives verse-level timing (first word start → last word end) and checks:
- **Short verses** — verse duration < 500ms (warning)
- **Inter-verse overlaps** (by_surah only) — consecutive verses where the next starts before the previous ends (error)
- **Large inter-verse gaps** (by_surah only) — > 10 seconds between consecutive verses, which may indicate missing content (warning)

Computes verse duration statistics (min/median/mean/max).

#### 8. Cross-file Consistency (with `segments.json`)

When `segments.json` is found in the upstream reciter directory:
- Compares the first word's start time against the first segment's start time per verse
- Compares the last word's end time against the last segment's end time per verse
- Tolerance is 2x the VAD pad duration (from segment meta), defaulting to 500ms
- Reports boundary mismatches ranked by magnitude

### Output Modes

**Single reciter** — detailed report with sections: MFA Settings, Coverage, Word Duration, MFA Failures, Temporal Issues, Verse Timestamps, Full Format (letters/phones), Cross-file Consistency, and Validation Issues.

**Multi-reciter** — four summary comparison tables:
1. **Coverage** — verse count, missing verses, total words, coverage issues, forward gaps, MFA failures, errors, warnings
2. **Word Duration** — min/median/mean/max per reciter with zero-duration and negative counts
3. **Verse Duration** — min/median/mean/max per reciter with short verse, overlap, and large gap counts
4. **Consistency** — presence of full/segments files, letter errors, phone issues, boundary mismatches

Reports are saved to `validation.log` in each reciter directory (single mode) or in the parent directory (multi mode).

## validate_edit_history.py

PR gate validator that checks the integrity of `edit_history.jsonl` audit trails before merging any PR that touches `data/recitation_segments/**`. Run automatically by the `validate-segments-pr.yml` CI workflow on every PR.

### Usage

```bash
python validators/validate_edit_history.py --base-sha <SHA> --reciters slug1 [slug2 ...]
```

### Validations Performed (6 checks per reciter)

#### 1. Genesis Record

Checks that `edit_history.jsonl` exists, is non-empty, and that the first record has `record_type: genesis` with all required fields: `schema_version`, `batch_id`, `reciter`, `created_at_utc`, `file_hash_after`.

#### 2. History Chain Integrity

Verifies every record has a `batch_id` and `file_hash_after`. Detects missing or duplicate `batch_id` values across the chain.

#### 3. File Hash Verification

Computes the SHA-256 of the current `detailed.json` on disk and compares it against `file_hash_after` from the last history record. A mismatch means the file was modified outside of the Inspector.

#### 4. _meta Tampering Detection

Compares the `_meta` block in `detailed.json` and `segments.json` between base SHA and HEAD. Any change to `_meta` is flagged as an error — these fields are set once during extraction and must not be modified.

#### 5. Diff vs History Cross-reference

Diffs `detailed.json` between base and HEAD to find all changed segments. Cross-references each change against the `targets_before`/`targets_after` in new history records (matched by `segment_uid` or `(time_start, time_end)` pair). Any segment change not covered by a history operation is an unexplained modification.

#### 6. History-only Change Detection

Flags the suspicious case where `edit_history.jsonl` changed but `detailed.json` did not — indicating the history was manually edited without a corresponding data change.

### Output

Prints a per-reciter table of `[PASS]` / `[FAIL]` lines for each check. Exits with code 1 if any check fails, which blocks the PR from merging.
