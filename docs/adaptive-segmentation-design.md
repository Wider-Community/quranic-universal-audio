# Adaptive Segmentation & Probability-Guided Refinement

> Design notes for using the VAD cache (speech probabilities) to dynamically improve segmentation quality, rather than relying on fixed `min_silence` thresholds.

---

## 1. VAD & Pipeline Overview

### Voice Activity Detection (VAD)

VAD is the first stage of the pipeline. Its job is to take a raw audio file (a full surah recitation, typically 5-90 minutes) and determine which portions contain speech and which are silence. The output is a set of **speech intervals** — time ranges where the model believes someone is speaking.

Our VAD model (`obadx/recitation-segmenter-v2`) is a Wav2Vec2Bert binary classifier fine-tuned on Quranic recitation audio. It processes audio in ~20s windows and outputs a **probability for every frame** (one frame = 20ms of audio). Each probability is the model's confidence in its prediction — high values near 1.0 mean "definitely speech" or "definitely silence" (whichever class won), and values near 0.5 mean the model is uncertain. The distribution is strongly bimodal — ~52% of frames below 0.1, ~42% above 0.9. The model is decisive.

The raw output is two things:
1. **Speech intervals** — start/end sample pairs at 16kHz, marking where speech was detected
2. **Speech probabilities** — a continuous probability value for every 20ms frame across the entire audio

These are the model's **raw, unprocessed** outputs. They capture every detected transition between speech and silence, including very short gaps (breath pauses, micro-silences within words, qalqala bounces) and very short speech bursts (noise, clicks).

### Post-Processing: The Cleaning Step

The raw intervals are too granular for alignment — a 30-minute surah might have 800+ raw intervals, many of which are just breathing pauses within a verse. The **cleaning step** (`clean_speech_intervals()` in `recitations_segmenter/segment.py:225-314`) applies three sequential operations to produce usable segments:

1. **Merge short silences** (`min_silence`): Any gap between speech intervals shorter than this threshold is removed, merging the adjacent intervals into one continuous segment. This is the primary tuning parameter — it determines how short a pause must be to count as a "real" silence.

2. **Remove short speech** (`min_speech`): Any speech interval shorter than this threshold is discarded entirely. We set this to 0 (disabled) so that no detected speech is silently dropped — short segments surface as failed alignments instead, which can be diagnosed.

3. **Add padding** (`pad`): Each interval is extended by this amount on both sides, ensuring the alignment has acoustic context around speech boundaries. Typically `pad = 0.4 × min_silence`.

The order matters: merge first (so tiny gaps don't fragment speech), then filter (on merged result), then pad (on final clean intervals).

The cleaning step is **purely parameter-driven** — it doesn't use the speech probabilities at all. It just applies duration thresholds to the raw intervals. This is where the opportunity for improvement lies: the probabilities contain rich information about the *nature* of each gap (deep silence vs. shallow dip vs. continuous speech) that the cleaning step currently ignores.

### The VAD Cache

Because VAD model inference is expensive (~minutes per surah on GPU), the raw outputs are cached to `vad_cache/<surah>.pt` after the first run (`extract_segments.py:398-409`). Each cache file is a `torch.save`'d dict:

| Field | Type | Description |
|-------|------|-------------|
| `speech_intervals` | `LongTensor (N, 2)` | Raw start/end sample pairs at 16kHz — pre-cleaning |
| `speech_probs` | `Float16Tensor (T,)` | Per-frame probability at 20ms resolution (hop=160×stride=2=320 samples) |
| `is_complete` | `bool` | Whether the audio ended in silence (vs cut mid-speech) |

The `--reuse-vad` flag skips model inference entirely and re-runs only the cleaning step with new parameters. This is why parameter re-runs are ~75% faster — they only need ASR + DP alignment, not VAD inference.

The cache preserves the **pre-cleaning** state, meaning any parameter combination can be applied to the same raw data. This is what makes iterative tuning and adaptive approaches feasible — the expensive computation is done once, and all subsequent analysis operates on the cached probabilities and intervals.

### What Comes After VAD

The cleaned segments flow through two more stages:

**ASR (phoneme recognition):** `transcribe_batch()` in `phoneme_asr.py` runs wav2vec2 CTC on each segment, producing a flat phoneme list per segment (`List[str]`). No per-phoneme confidences or timestamps — the CTC decode is a hard argmax, and the raw logits are discarded immediately (`phoneme_asr.py:295`).

**DP alignment:** Matches ASR phonemes against the known Quranic reference text via dynamic programming. Produces an `AlignmentResult` with word indices, `confidence = 1.0 - (edit_cost / max(len(phonemes), ref_len))`, and repetition detection data (`wrap_points`, `wrap_word_ranges`). Acceptance threshold: `norm_dist > 0.3` rejects the match (relaxed to 0.45 in retry tiers).

---

## 2. The Problem

The current pipeline uses a single `min_silence` parameter applied uniformly to all gaps in all surahs for a reciter. Different reciters — and different regions within the same recitation — have different pause patterns. Tuning is manual: run the pipeline, check error counts, adjust, re-run.

The pipeline also runs in strict stages with no backflow:

```
VAD probs → fixed threshold → segments → ASR (logits discarded) → DP alignment → output
```

Two critical pieces of information are thrown away:
1. **Speech probabilities** — used once for interval detection, then ignored during cleaning
2. **ASR logits** — discarded immediately after argmax decode (these contain per-frame posterior probabilities that could yield per-phoneme confidence)

And the DP alignment discovers problems (cross-verse, repetitions, failed matches) *after* it's too late to re-segment.

**Evidence from batch tuning (April 2026):**

| Reciter | 400ms CV | 200ms CV | 100ms CV | 100ms Failed |
|---------|:--------:|:--------:|:--------:|:------------:|
| mohammed_alghazali | 599 | 41 | — | — |
| bandar_balilah | 1103 | 107 | — | — |
| ahmad_talib_bin_humaid | 766 | 153 | — | — |
| abdulwadood_haneef | 1541 | 515 | 401 | 25 |
| mohammed_ayyub | — | 751 | 484 | 18 |

Lower thresholds reduce cross-verse but increase failed alignments — it's always a trade-off with fixed values.

---

## 3. Error Types as Feedback Signals

The validator categories flag segments that *may* need attention. Not all flagged items are errors — cross-verse segments from continuous recitation are correct behavior, for example. And some real problems go unflagged — a missed gap within a single verse where the DP managed to align anyway but produced a suboptimal segmentation.

That said, each category points to a specific kind of segmentation issue and maps to a specific fix:

| Error Category | What happened | What the data tells us | Potential fix |
|---|---|---|---|
| **Cross-verse** (pause missed) | Gap existed but was below `min_silence` | VAD cache has the gap's prob profile — find the dip | Prob-guided split at estimated verse boundary |
| **Cross-verse** (continuous recitation) | No gap — reciter genuinely continued | Prob stays high throughout — no dip to split at | Leave it — correct behavior |
| **Detected repetitions** | Reciter paused, went back, re-recited — VAD merged the pause | There MUST be a dip in probs where they stopped | Split at deepest prob dip, re-ASR both halves, keep the one that matches forward text |
| **Boundary adjustment** (word cut short) | Segment end is too early — ASR's last phoneme matches 2nd-to-last canonical phoneme | Probs near segment boundary show where speech actually ends | Extend segment end to where prob drops below threshold |
| **Failed alignment** | Segment is too long/messy for DP to match | Either needs splitting (merged pause) or audio is genuinely problematic | Search for prob dips within the segment, try splitting at each, re-ASR+DP |
| **Qalqala false cuts** | Short silence between consonant and its qalqala bounce splits the word | Gap is very short (20-60ms), prob dip is shallow | Merge with adjacent segment if gap prob is high AND merged ASR matches better |
| **Missing words** | A word fell in a gap between segments | The gap contains speech (prob > threshold) that was classified as silence | Extend adjacent segment to cover the gap, or create a micro-segment |

The pattern: every fix is either "split here," "merge here," or "extend here" — and the speech probabilities inform whether the fix is safe. But flagged errors are only part of the picture. Unflagged issues (suboptimal segmentation that the DP papered over) require broader approaches — stats-based analysis, global param adjustment, or per-chapter tuning.

---

## 4. Tuning Strategy Landscape

The approaches below are not mutually exclusive — the final solution may combine several of them. They operate at different granularities and use different signals.

### Strategy 1: Global Reparameterization (Data-Guided)

What we did manually in April 2026 — change `min_silence` for the entire reciter — but driven by data instead of trial-and-error.

**How it works:** Analyze the VAD cache gap distribution and alignment stats to **recommend** the right global param without running the pipeline first:
- Gap histogram from raw intervals tells you the natural pause distribution for this reciter
- Expected stats (segment duration, word count per segment, silence distribution) set a baseline
- After a run, alignment stats (cross-verse rate, failed rate, segment duration distribution) validate whether the param worked

**When it's the right tool:** When the param was genuinely wrong for the reciter's overall style. This catches everything — cross-verse, within-verse missed gaps, over-segmentation — not just errors flagged by the validator. Many errors are "silent" (a missed gap within a verse that the DP managed to align anyway but produced a suboptimal segmentation). A global param change catches these too.

**Limitation:** Still a single number applied uniformly. A reciter with mixed dynamics (e.g., slow tajweed in long surahs, fast murattal in short surahs) can't be fully served by one value.

### Strategy 2: Stats-Based Adaptation

There are natural expectations for a well-aligned reciter: segment duration median in a certain range, silence gap distribution following certain patterns, word-per-segment ratios matching the verse structure. Deviations from these expectations signal parameter problems even when no specific error is flagged.

**Examples:**
- Median segment duration of 14s (like haneef at 400ms) when the expected range is ~8s signals too many segments are merged — even if DP managed to align them
- A silence gap distribution with no gaps below 300ms when the reference text has many short verses suggests gaps are being merged that shouldn't be
- An unusually high ratio of multi-segment verses vs. single-segment verses may indicate over-segmentation

**How it differs from Strategy 1:** Strategy 1 looks at the raw VAD data to pick a param. Strategy 2 looks at the *results* of a run (segments, alignment, validation) and compares them to expectations. It answers "did this param work?" rather than "what param should I pick?"

**Combined with Strategy 1:** Run with the param suggested by gap analysis → check stats → if stats deviate from expectations, adjust and re-run. The VAD cache makes re-runs cheap.

### Strategy 3: Per-Chapter / Per-Region Tuning

A reciter's pause dynamics vary across the Quran:
- Shorter surahs at the end tend to have faster recitation with shorter pauses
- Mujawwad reciters may elongate pauses in certain emotional passages
- Rhyming patterns (فواصل) at verse endings affect pause lengths — some rhyme groups naturally flow into each other
- Certain surahs have long verses with multiple natural pause points within the verse

The VAD cache is already per-surah, so per-surah analysis is natural.

**How it works:**
1. After a global run, identify outlier surahs — those with disproportionately high cross-verse, failed alignments, or stat deviations
2. Analyze the VAD cache gap distribution for those specific surahs
3. Re-run those surahs with adjusted params (using `--reuse-vad` for speed)
4. Keep the per-surah results that improved, fall back to global for those that didn't

**When it's the right tool:** When the global param works for 90% of surahs but a handful are outliers due to genuinely different recitation dynamics.

### Strategy 4: Local Surgical Fixes (Error-Targeted)

Use flagged errors from the validator + speech probabilities to split/merge/extend at specific locations. Only touches the segments that need it.

**The approach — a diagnose-then-fix loop:**

```
Pass 1: Conservative run (e.g. 300ms) → segments + alignment + errors
    ↓
Diagnose: Categorize errors, look up VAD cache at each error location
    ↓
For each fixable error:
    - Compute the fix (split/merge/extend) using prob data
    - Re-run ASR + DP on just the affected segment(s)
    - If improved → keep. If not → revert.
    ↓
Output: Improved segments with fewer errors
```

**For split-type fixes (cross-verse, repetitions, failed):**

1. From the alignment result, identify the approximate time position of the issue (verse boundary from `matched_ref`, or deepest prob dip for repetitions)
2. Load speech probs from VAD cache, extract the window around the estimated position (±500ms for verse boundaries, ±30% of segment duration for repetitions)
3. Find the frame with the lowest speech probability — that's the split candidate
4. **Quality gate:** If min_prob in the window > 0.7, the reciter genuinely didn't pause → flag for Inspector, don't force a bad split
5. Slice audio at the split point, re-run ASR + DP on both halves against expected text
6. If both halves align cleanly → keep the split. If not → keep original

**For merge-type fixes (qalqala, boundary adjustment):**

1. Identify the gap between the affected segments
2. Check gap duration and speech prob during the gap
3. If gap is short (<60ms) and mean prob is high (>0.5) → merge candidate
4. Re-run ASR + DP on the merged segment
5. If merged alignment is better → keep. If not → revert

**Why repetitions are guaranteed fixable:** A reciter cannot repeat without pausing. Every detected repetition has a split point somewhere in the segment. The prob-guided search just needs to find it, split, and verify which half aligns forward.

**Cost:** For a typical reciter with ~5-15% flagged segments out of ~6,000 total, this adds ~300-900 extra ASR calls (two per split attempt). At ~50ms per segment on GPU, that's 15-45 seconds — negligible.

**Where it fits:** After `align_sura()` returns (~line 575 in `extract_segments.py`) but before `write_outputs()`, or as a standalone post-processing script. The VAD cache loading infrastructure already exists in `batch_vad()`.

**Important nuance:** Flagged errors don't capture all problems. A within-verse missed gap (where the DP aligned both parts to the same verse but the segmentation is suboptimal) is not flagged. This is why local fixes alone are insufficient — they need to be combined with global or stats-based approaches that catch unflagged issues.

### Strategy 5: Probability-Driven Segmentation

The most ambitious approach — don't use a fixed threshold at all. Instead of "merge all gaps below X ms," score each gap individually based on multiple features:

- **Gap duration** (what we use now, but as a feature not a hard cutoff)
- **Probability depth** — how low does the speech prob go during the gap?
- **Edge gradient** — how sharply does speech probability drop at the gap boundaries?
- **Surrounding context** — how long are the adjacent speech intervals?

A per-gap scoring function like `effective_threshold = base × (0.5 + 0.5 × min_gap_prob)` would mean deep gaps (min_prob near 0) split at half the base threshold, while shallow gaps (min_prob near 1) need the full threshold to split.

**Advantage:** Subsumes strategies 1-3 — no global tuning needed, no per-chapter overrides, each gap is handled on its merits.

**Challenge:** Requires careful calibration of the scoring function, and the 58% accuracy ceiling for probability-only classification means additional features (duration, context) are essential.

### Strategy 6: Edit History Mining

Using human corrections from past reciters (stored in `edit_history.jsonl`) to learn patterns — what types of segments tend to be manually split, merged, or adjusted?

**Potential insights:**
- Common gap durations at manually-split points → calibrate probability thresholds
- Patterns in which error categories lead to which fix operations
- Reciter-style-specific correction patterns (murattal vs. mujawwad)

**Current assessment:** High effort to extract useful insights, small sample size (only a few reciters have been manually reviewed so far). More valuable once more reciters have been through the Inspector review cycle. Low priority for now.

### Strategy Summary

| Strategy | Granularity | Catches unflagged errors? | Requires re-run? | Complexity |
|---|---|---|---|---|
| Global reparameterization | Entire reciter | Yes | Full pipeline (fast with `--reuse-vad`) | Low |
| Stats-based adaptation | Entire reciter | Yes (via stat deviations) | Diagnostic only | Low |
| Per-chapter tuning | Per surah | Yes (within that surah) | Targeted surahs only | Medium |
| Local surgical fixes | Per segment | No (only flagged errors) | ASR+DP on affected segments | Medium |
| Probability-driven segmentation | Per gap | Yes | Full pipeline | High |
| Edit history mining | Per pattern | Depends on coverage | No | High (analysis effort) |

The likely practical approach is a combination: **global param via gap analysis (Strategy 1) → validate via stats (Strategy 2) → fix outlier surahs (Strategy 3) → surgical fixes for remaining flagged errors (Strategy 4)**. Strategy 5 (probability-driven) is the long-term goal that could replace 1-4. Strategy 6 becomes more viable as more reciters are reviewed.

### Future Explorations

- **Preserve ASR logits** → per-phoneme confidence → better alignment quality signals and split-point verification
- **Adaptive gap scoring in DP** — pass gap depth as a cost modifier rather than hard merge/split decisions before alignment
- **Inspector feedback loop** — the split/merge/re-reference operations performed manually in the Inspector could inform automated refinement

---

## Appendix: Empirical Data from April 2026 Analysis

### VAD Gap Characterization (34,201 gaps across 3 reciters)

- Gaps are strongly bimodal in probability — 42% have min_prob < 0.1, 52% have min_prob >= 0.9
- Verse-boundary gaps: mean prob 0.62-0.68, min prob 0.40-0.50
- Within-verse gaps: mean prob 0.73-0.79, min prob 0.54-0.63
- ~44% of verse-boundary gaps have high speech prob (continuous recitation) — acoustically unsolvable, only text alignment can resolve
- ~60% of verse-boundary gaps with deep prob dips are separable from within-verse gaps
- Duration alone is nearly identical between classes (median ~460ms for both)

### Reciter-Specific Patterns

- **abdulwadood_haneef:** Highest fraction of deep verse-boundary gaps (61%), most amenable to prob-based separation, but very short pauses overall (median gap 360ms)
- **bandar_balilah:** Most within-verse gaps, indicating more mid-verse pausing
- **mohammed_alghazali:** 47% of verse-boundary gaps have min_prob >= 0.9 — connects verses smoothly, making prob-based detection hardest (but 200ms threshold alone reduced CV from 599 to 41)

### Pipeline Information Flow

| Between stages | Data available | What could be tuned |
|---|---|---|
| VAD → ASR | Speech probs (cached), interval durations/gaps | Re-clean with different params, prob-guided splits |
| ASR → DP | Phoneme lists (no confidences currently; logits discarded) | If logits preserved: per-segment ASR quality → adjust thresholds |
| DP per-segment | `confidence`, `consecutive_failures`, gap detection | Already partially done via retry tiers; could feed back to re-segment |
| Post-alignment | Full per-surah statistics, error categorization | Re-run specific segments with targeted fixes |
