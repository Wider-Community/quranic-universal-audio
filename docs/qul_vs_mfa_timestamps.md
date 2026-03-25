# QUL vs MFA Timestamp Comparison

**Reciter:** Muhammad Siddiq Al-Minshawi (Murattal)
**Date:** 2026-03-01

Comparison between:
- **QUL**: `data/qul_downloads/by_ayah/muhammad_siddiq_al_minshawi_murattal.json` (Tarteel CDN word segments)
- **TS (MFA)**: `data/timestamps/by_ayah_audio/minshawy_murattal/timestamps.json` (our MFA forced alignment pipeline via EveryAyah audio)

Both files cover 6236 verses with per-word `[word_idx, start_ms, end_ms]` segments.

---

## 1. Word Sequence Comparison

### Overview

| Metric | Count |
|--------|-------|
| Identical word sequences | 5519/6236 (88.5%) |
| TS has extra words (repeats/loopbacks) | 433 |
| QUL has more words (convention diff) | 284 |

### QUL Repeats

QUL **does** have repeats — 53 verses contain non-increasing word indices. However, every QUL repeat verse is also a TS repeat (perfect subset).

| | QUL | TS |
|---|---|---|
| Verses with repeats | 53 | 469 |
| Both repeat same verse | 53 | 53 |
| Only this source repeats | 0 | 416 |

TS detects 8.8x more reciter loopbacks than QUL. For the 53 shared repeats, the repeat points usually agree or differ by 1 word index.

### Against Ground Truth (surah_info.json)

Unique word count per verse compared to ground truth:

| Source | Matches GT | Accuracy |
|--------|-----------|----------|
| TS (unique words) | 6235/6236 | **99.98%** |
| QUL | 5837/6236 | 93.6% |

QUL word count errors (overcounting):
- Off by +1: 348 verses
- Off by +2 to +9: 51 verses

This is a word-count convention difference or error, QUL splits words differently.

### Identical Sequences Breakdown

Of the 5519 identical sequences:
- **5483 are consecutive 1..N** (simple sequential reading)
- **36 have repeats that both sources agree on** (e.g. `2:85`: both show `...10, 6, 7, 8, 9, 10, 11...`)

---

## 2. Word Duration Comparison

77,428 words matched by first occurrence of each word index.

### Duration Statistics (ms)

| Stat | QUL | TS (MFA) |
|------|-----|----------|
| Mean | 757 | 1161 |
| Median | 640 | 1070 |
| Std | 789 | 577 |
| Min | 30 | 40 |
| Max | 17360 | 10380 |

TS words are ~400ms longer on average (median ratio 1.61x).

### Duration Difference (TS - QUL)

| Stat | Value (ms) |
|------|-----------|
| Mean | +404 |
| Median | +350 |
| Std | 728 |
| P5 | -410 |
| P25 | +130 |
| P75 | +690 |
| P95 | +1450 |

### Duration Agreement

| Threshold | Words within |
|-----------|-------------|
| 50ms | 4604 (5.9%) |
| 100ms | 9396 (12.1%) |
| 200ms | 19835 (25.6%) |
| 500ms | 45716 (59.0%) |

### Explanation

The duration difference is almost entirely due to **inter-word gap handling**:
- QUL leaves gaps between words (mean 605ms, 98.9% of words have gaps)
- TS pads words to fill gaps within continuous-speech segments (81.6% have zero gap)

QUL durations represent speech-only intervals. TS durations include surrounding silence up to the next word boundary.

---

## 3. Onset & Offset Timing Comparison

### Raw Onset/Offset (ms)

| Metric | Onset (start) | Offset (end) |
|--------|--------------|-------------|
| Mean diff | +138 | +542 |
| Median diff | +140 | +430 |
| Std | 618 | 762 |
| MAE | 341 | 652 |

| Threshold | Onset within | Offset within |
|-----------|-------------|--------------|
| 50ms | 6.8% | 1.4% |
| 100ms | 20.8% | 2.5% |
| 200ms | 55.7% | 8.0% |
| 500ms | 84.5% | 56.6% |
| 1000ms | 92.9% | 83.7% |

Offset is worse due to TS padding extending word endpoints.

### Gap-Aware Analysis (5519 verses with identical sequences)

**Midpoint comparison** (less sensitive to boundary padding):

| Stat | Value (ms) |
|------|-----------|
| Mean diff | +254 |
| Median diff | +260 |
| Std | 325 |
| MAE | 329 |

| Threshold | Within |
|-----------|--------|
| 50ms | 6.2% |
| 100ms | 13.0% |
| 200ms | 31.4% |
| 500ms | 82.8% |

**Boundary analysis (no padding bias):**

| Metric | Value (ms) |
|--------|-----------|
| First-word onset diff (mean) | +485 |
| First-word onset MAE | 509 |
| Last-word offset diff (mean) | -290 |
| Last-word offset MAE | 375 |

TS starts ~485ms later (trims leading silence more aggressively) and ends ~290ms earlier than QUL.

### Inter-Word Gaps

| Stat | QUL | TS |
|------|-----|-----|
| Mean gap | 598ms | 65ms |
| Median gap | 440ms | 0ms |
| Words with gap > 0 | 98.9% | 18.4% |
| Words with gap = 0 | 622 | 46016 |
| Mean gap (where > 0) | 605ms | 355ms |

TS gaps > 0 occur only at segment boundaries (between detected speech segments). Within a segment, words are padded to be sequential.

---

## 4. Notable Examples

Audio base URL: `https://everyayah.com/data/Minshawy_Murattal_128kbps/SSSAAA.mp3`


### TS Detects Repeat, QUL Doesn't (416 verses)

| Verse | QUL | TS | Repeat point | Audio |
|-------|-----|-----|-------------|-------|
| 2:14 | 1-16 sequential | 1-6, **5-6**, 7-16 | words 5-6 | `.../002014.mp3` |
| 2:17 | 1-17 sequential | 1-12, **6-12**, 13-17 | words 6-12 | `.../002017.mp3` |
| 2:22 | 1-23 sequential | 1-11, **8-11**, 12-23 | words 8-11 | `.../002022.mp3` |
| 2:23 | 1-20 sequential | 1-12, **9-12**, 13-20 | words 9-12 | `.../002023.mp3` |
| 2:31 | 1-15 sequential | 1-10, **9-10**, 11-15 | words 9-10 | `.../002031.mp3` |

### Both Repeat, Different Repeat Point (17 verses)

Pattern: QUL repeat indices are **off by +1** compared to TS. TS is correct (matches ground truth word count); QUL overcounts by 1 word consistently, shifting all indices.

| Verse | QUL repeats at | TS repeats at (correct) | Audio |
|-------|---------------|------------------------|-------|
| 2:61 | words 10-12 | words 9-11 | `.../002061.mp3` |
| 2:213 | words 11-12 | words 10-12 | `.../002213.mp3` |
| 3:118 | words 13-15 | words 12-14 | `.../003118.mp3` |
| 4:43 | words 33-35 | words 32-34 | `.../004043.mp3` |
| 4:90 | words 10-15 | words 9-14 | `.../004090.mp3` |

---

## Summary

The ~254ms systematic midpoint shift comes from TS trimming leading silence more aggressively. The main structural differences:

1. **Repeat detection**: TS catches 469 reciter loopbacks vs QUL's 53 (QUL's 53 are a subset)
2. **Word count**: TS matches ground truth 99.98% vs QUL's 93.6%
3. **Duration**: TS words are longer due to gap-filling padding, not alignment error. This is more natural and intuitive since recitation is continuous within segments, and we do not expect gaps between words.
4. **Timing**: Word midpoints agree within 500ms for 82.8% of words, with a systematic +254ms offset
