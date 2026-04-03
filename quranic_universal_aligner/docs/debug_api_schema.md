# Debug Process API — Response Schema

Hidden endpoint for development debugging. Returns comprehensive structured data from every pipeline stage.

## Endpoint

```
POST /api/debug_process
```

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `audio_data` | Audio (numpy) | Audio file to process |
| `min_silence_ms` | int | Minimum silence duration for VAD segment splitting |
| `min_speech_ms` | int | Minimum speech duration to keep a segment |
| `pad_ms` | int | Padding added to each segment boundary |
| `model_name` | str | ASR model: `"Base"` or `"Large"` |
| `device` | str | `"GPU"` or `"CPU"` |
| `hf_token` | str | HF token for authentication |

## Usage

```python
from gradio_client import Client

client = Client("hetchyy/quranic-universal-aligner")
result = client.predict(
    "path/to/audio.mp3",
    300, 100, 50,        # silence, speech, pad
    "Base", "GPU",
    "hf_xxxx...",        # HF token
    api_name="/debug_process"
)
```

---

## Response Schema

### Top Level

```json
{
  "status": "ok",
  "timestamp": "2026-04-03T12:00:00+00:00",
  "profiling": { ... },
  "vad": { ... },
  "asr": { ... },
  "anchor": { ... },
  "specials": { ... },
  "alignment_detail": [ ... ],
  "events": [ ... ],
  "segments": [ ... ]
}
```

On error: `{"error": "message"}` (auth failure, pipeline failure, no speech).

---

### `profiling`

All timing fields from `ProfilingData` plus computed fields. Times in seconds unless noted.

| Field | Type | Description |
|-------|------|-------------|
| `resample_time` | float | Audio resampling to 16kHz |
| `vad_model_load_time` | float | VAD model loading |
| `vad_model_move_time` | float | VAD model GPU transfer |
| `vad_inference_time` | float | VAD model inference |
| `vad_gpu_time` | float | Actual VAD GPU execution |
| `vad_wall_time` | float | VAD wall-clock (includes queue wait) |
| `asr_time` | float | ASR wall-clock (includes queue wait) |
| `asr_gpu_time` | float | Actual ASR GPU execution |
| `asr_model_move_time` | float | ASR model GPU transfer |
| `asr_sorting_time` | float | Duration-sorting for batching |
| `asr_batch_build_time` | float | Dynamic batch construction |
| `asr_batch_profiling` | array | Per-batch timing (see below) |
| `anchor_time` | float | N-gram voting anchor detection |
| `phoneme_total_time` | float | Overall phoneme matching |
| `phoneme_ref_build_time` | float | Chapter reference build |
| `phoneme_dp_total_time` | float | Total DP across all segments |
| `phoneme_dp_min_time` | float | Min DP time per segment |
| `phoneme_dp_max_time` | float | Max DP time per segment |
| `phoneme_dp_avg_time` | float | Average DP time per segment (computed) |
| `phoneme_window_setup_time` | float | Total window slicing |
| `phoneme_result_build_time` | float | Result construction |
| `phoneme_num_segments` | int | Number of DP alignment calls |
| `match_wall_time` | float | Total matching wall-clock |
| `tier1_attempts` | int | Tier 1 retry attempts |
| `tier1_passed` | int | Tier 1 retries that succeeded |
| `tier1_segments` | int[] | Segment indices that went to tier 1 |
| `tier2_attempts` | int | Tier 2 retry attempts |
| `tier2_passed` | int | Tier 2 retries that succeeded |
| `tier2_segments` | int[] | Segment indices that went to tier 2 |
| `consec_reanchors` | int | Times consecutive-failure reanchor triggered |
| `segments_attempted` | int | Total segments processed |
| `segments_passed` | int | Segments that matched successfully |
| `special_merges` | int | Basmala-fused wins |
| `transition_skips` | int | Transition segments detected |
| `phoneme_wraps_detected` | int | Repetition wraps |
| `result_build_time` | float | Total result building |
| `result_audio_encode_time` | float | Audio int16 conversion |
| `gpu_peak_vram_mb` | float | Peak GPU VRAM (MB) |
| `gpu_reserved_vram_mb` | float | Reserved GPU VRAM (MB) |
| `total_time` | float | End-to-end pipeline time |
| `summary_text` | str | Formatted profiling summary (same as terminal output) |

#### `asr_batch_profiling[]`

| Field | Type | Description |
|-------|------|-------------|
| `batch_num` | int | Batch index (1-based) |
| `size` | int | Number of segments in batch |
| `time` | float | Total batch processing time |
| `feat_time` | float | Feature extraction + GPU transfer |
| `infer_time` | float | Model inference |
| `decode_time` | float | CTC greedy decode |
| `min_dur` | float | Shortest audio in batch (seconds) |
| `max_dur` | float | Longest audio in batch (seconds) |
| `avg_dur` | float | Average audio duration |
| `total_seconds` | float | Sum of all segment durations |
| `pad_waste` | float | Fraction of padding waste (0–1) |

---

### `vad`

VAD segmentation details — raw model output vs. cleaned intervals.

| Field | Type | Description |
|-------|------|-------------|
| `raw_interval_count` | int | Intervals from VAD model before cleaning |
| `raw_intervals` | float[][] | `[[start, end], ...]` before silence merge / min_speech filter |
| `cleaned_interval_count` | int | Intervals after cleaning |
| `cleaned_intervals` | float[][] | `[[start, end], ...]` final segment boundaries |
| `params` | object | `{min_silence_ms, min_speech_ms, pad_ms}` |

---

### `asr`

ASR phoneme recognition results per segment.

| Field | Type | Description |
|-------|------|-------------|
| `model_name` | str | `"Base"` or `"Large"` |
| `num_segments` | int | Total segments transcribed |
| `per_segment_phonemes` | array | Per-segment phoneme output (see below) |

#### `per_segment_phonemes[]`

| Field | Type | Description |
|-------|------|-------------|
| `segment_idx` | int | Segment index (0-based) |
| `phonemes` | str[] | Array of phoneme strings from CTC decode |

---

### `anchor`

N-gram voting for chapter/verse anchor detection.

| Field | Type | Description |
|-------|------|-------------|
| `segments_used` | int | Number of segments used for voting |
| `combined_phoneme_count` | int | Total phonemes in combined segments |
| `ngrams_extracted` | int | N-grams extracted from ASR output |
| `ngrams_matched` | int | N-grams found in Quran index |
| `ngrams_missed` | int | N-grams not in index |
| `distinct_pairs` | int | Distinct (surah, ayah) pairs voted for |
| `surah_ranking` | array | Candidate surahs ranked by best run weight |
| `winner_surah` | int | Winning surah number |
| `winner_ayah` | int | Starting ayah of best contiguous run |
| `start_pointer` | int | Word index corresponding to winner ayah |

#### `surah_ranking[]`

| Field | Type | Description |
|-------|------|-------------|
| `surah` | int | Surah number |
| `total_weight` | float | Sum of all vote weights |
| `best_run` | object | `{start_ayah, end_ayah, weight}` — best contiguous ayah run |

---

### `specials`

Special segment detection (Isti'adha, Basmala, Takbir at recording start).

| Field | Type | Description |
|-------|------|-------------|
| `candidates_tested` | array | Every detection attempt with edit distance |
| `detected` | array | Confirmed special segments |
| `first_quran_idx` | int | Index where Quran content starts (after specials) |

#### `candidates_tested[]`

| Field | Type | Description |
|-------|------|-------------|
| `segment_idx` | int | Which segment was tested |
| `type` | str | Candidate type (`"Isti'adha"`, `"Basmala"`, `"Combined Isti'adha+Basmala"`, `"Takbir"`) |
| `edit_distance` | float | Normalized edit distance (0 = exact match) |
| `threshold` | float | Maximum edit distance for acceptance |
| `matched` | bool | Whether distance ≤ threshold |

#### `detected[]`

| Field | Type | Description |
|-------|------|-------------|
| `segment_idx` | int | Segment index |
| `type` | str | Special type |
| `confidence` | float | 1 − edit_distance |

---

### `alignment_detail[]`

Per-segment DP alignment results. One entry per alignment attempt (primary + retries appear separately).

| Field | Type | Description |
|-------|------|-------------|
| `segment_idx` | int | 1-based segment display index |
| `asr_phonemes` | str | Space-separated ASR phonemes (truncated to 60) |
| `asr_phoneme_count` | int | Full phoneme count |
| `window` | object | `{pointer, surah}` — DP search window info |
| `expected_pointer` | int | Word pointer at time of alignment |
| `retry_tier` | str\|null | `null` for primary, `"tier1"` or `"tier2"` for retries |
| `result` | object\|null | Alignment result (null if failed) |
| `timing` | object | `{window_setup_ms, dp_ms, result_build_ms}` |
| `failed_reason` | str\|null | Why alignment failed (if applicable) |

#### `result` (when present)

| Field | Type | Description |
|-------|------|-------------|
| `matched_ref` | str | Reference location (`"2:255:1-2:255:3"`) |
| `start_word_idx` | int | First matched word index in chapter reference |
| `end_word_idx` | int | Last matched word index |
| `edit_cost` | float | Raw edit distance (with substitution costs) |
| `confidence` | float | 1 − normalized_edit_distance |
| `j_start` | int | Start position in reference phoneme window |
| `best_j` | int | End position in reference phoneme window |
| `basmala_consumed` | bool | Whether Basmala prefix was consumed |
| `n_wraps` | int | Number of repetition wraps |
| `wrap_points` | array\|null | `[(i, j_end, j_start), ...]` for each wrap |

---

### `events[]`

Pipeline events in chronological order. Each has a `type` field plus event-specific data.

#### Event Types

| Type | Fields | Description |
|------|--------|-------------|
| `gap` | `position`, `segment_before`/`segment_after`/`segment_idx`, `missing_words` | Missing words between consecutive segments or at boundaries |
| `reanchor` | `at_segment`, `reason`, `new_surah`, `new_ayah`, `new_pointer` | Global re-anchor after consecutive failures or transition mode exit |
| `chapter_transition` | `at_segment`, `from_surah`, `to_surah` | Sequential chapter boundary crossing |
| `chapter_end` | `at_segment`, `from_surah`, `next_action` | End of chapter detected |
| `basmala_fused` | `segment_idx`, `fused_conf`, `plain_conf`, `chose` | Basmala merged with first verse (chosen when fused > plain) |
| `transition_detected` | `segment_idx`, `transition_type`, `confidence`, `context` | Non-Quranic transition segment (Amin, Takbir, Tahmeed, etc.) |
| `tahmeed_merge` | `segment_idx`, `merged_segment` | Two Tahmeed segments merged |
| `retry_tier1` | `segment_idx`, `passed`, `confidence` | Tier 1 retry succeeded |
| `retry_tier2` | `segment_idx`, `passed`, `confidence` | Tier 2 retry succeeded |
| `retry_failed` | `segment_idx`, `tier1`, `tier2` | All retry tiers exhausted |

---

### `segments[]`

Final alignment output (same schema as `/process_audio_session` response).

| Field | Type | Description |
|-------|------|-------------|
| `segment` | int | 1-based segment number |
| `time_from` | float | Start time (seconds) |
| `time_to` | float | End time (seconds) |
| `ref_from` | str | Reference start (`"surah:ayah:word"`) |
| `ref_to` | str | Reference end |
| `matched_text` | str | Matched Quran text |
| `confidence` | float | Alignment confidence (0–1) |
| `has_missing_words` | bool | Gap detected before/after this segment |
| `error` | str\|null | Error message if alignment failed |
| `special_type` | str | Present only for special segments |
