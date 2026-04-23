# How the Timestamp Pipeline Handles Repetitions and Verse Boundaries

This doc explains how `extract_timestamps.py` decides which word timings to keep when multiple segments of a recording contribute to the same verse. It covers the normal case, within-verse repetitions, and verse-boundary handling. Examples use Minshawi's real data.

## The setup

A recitation is cut into **segments** — contiguous audio ranges, each labeled with a `matched_ref` like `"2:14:1-2:14:6"` (surah 2, ayah 14, words 1 through 6). Each segment is sent to MFA, which aligns **exactly** the words we pass — no more, no less.

The pipeline writes two files per reciter:

- `timestamps.json` — compact: `[word_idx, start_ms, end_ms]` per verse
- `timestamps_full.json` — same plus per-letter and per-phoneme timings

Downstream, `scripts/build_reciter.py` turns these into the HF dataset, **one row per ayah**.

## Home vs. cross-verse segments

A segment is **home** for verse `S:A` when its `matched_ref` covers that one ayah and nothing else:

```
"2:14:1-2:14:6"      → home for 2:14
"37:151:1-37:151:5"  → home for 37:151
```

A **cross-verse** segment straddles an ayah boundary (reciter didn't pause between verses):

```
"37:151:3-37:152:2"  → cross-verse; covers end of 37:151 + start of 37:152
```

Cross-verse segments are treated as **transition audio** — content that bridges two ayahs. When the dataset is built, each cross-verse segment's words get routed by their location (`"37:151:X"` → 37:151 row, `"37:152:Y"` → 37:152 row), but their timings are treated as lower-priority fill. See merge rules below.

## Case 1 — One home segment per verse

The boring majority. One segment covers the verse exactly. MFA returns timings. Done.

```
1:1  →  matched_ref "1:1:1-1:1:4"  — single seg, 4 words
```

## Case 2 — Within-verse repetition (two home segments)

Reciter reads a verse, pauses, repeats some words for emphasis or correction. The segmenter produces **two overlapping home segments** for the same verse.

**Minshawi, 2:14:**

```
seg A: "2:14:1-2:14:6"   →  "وَإِذَا لَقُوا۟ ٱلَّذِينَ ءَامَنُوا۟ قَالُوٓا۟ ءَامَنَّا"
seg B: "2:14:5-2:14:16"  →  "قَالُوٓا۟ ءَامَنَّا وَإِذَا خَلَوْا۟ إِلَىٰ شَيَـٰطِينِهِمْ ..."
```

Words 1–6, pause, then repeated 5–6 ("قَالُوٓا۟ ءَامَنَّا" — "they said: we believe"), continued to 16. Both segs are home for 2:14; ranges overlap on widx 5, 6.

**Minshawi, 27:37:**

```
seg A: "27:37:1-27:37:11"  →  "... وَلَنُخْرِجَنَّهُم مِّنْهَآ أَذِلَّةً"
seg B: "27:37:9-27:37:13"  →  "وَلَنُخْرِجَنَّهُم مِّنْهَآ أَذِلَّةً وَهُمْ صَـٰغِرُونَ"
```

Repeated widx 9–11 before finishing.

**Behavior:** both segments' timings are kept. The verse's `word_timestamps` contains each repeated widx twice, ordered by start time. Dataset consumers see this as expected — the dataset schema explicitly allows repeated `word_idx` and the README documents it ("When the reciter repeats a word, the same `word_idx` may appear multiple times and indices may go backward").

There are **547 such within-verse repetition pairs** across Minshawi's full recording.

## Case 3 — Verse boundary: cross-verse segment beside home coverage

This is where the dedup matters.

**Minshawi, 37:151 + 37:152** (verses: "أَلَآ إِنَّهُم مِّنْ إِفْكِهِمْ لَيَقُولُونَ" / "وَلَدَ ٱللَّهُ وَإِنَّهُمْ لَكَـٰذِبُونَ"):

```
seg 1 (home 37:151):     "أَلَآ إِنَّهُم مِّنْ إِفْكِهِمْ لَيَقُولُونَ"
seg 2 (cross 151→152):   "مِّنْ إِفْكِهِمْ لَيَقُولُونَ  |  وَلَدَ ٱللَّهُ"
seg 3 (home 37:152):     "وَإِنَّهُمْ لَكَـٰذِبُونَ"
```

(The `|` in seg 2 marks the ayah boundary inside the seg.)

What physically happened:
1. Read 37:151 in full: "أَلَآ إِنَّهُم مِّنْ إِفْكِهِمْ لَيَقُولُونَ" (seg 1)
2. Short pause
3. Went back and re-read from "مِّنْ إِفْكِهِمْ لَيَقُولُونَ" and continued without pausing into "وَلَدَ ٱللَّهُ" (seg 2, cross-verse)
4. Short pause
5. Finished 37:152: "وَإِنَّهُمْ لَكَـٰذِبُونَ" (seg 3)

Seg 2 overlaps with seg 1 on the three words "مِّنْ إِفْكِهِمْ لَيَقُولُونَ" — the end of 37:151. At this verse boundary we don't want the 37:151 dataset row to contain both copies (home and cross-verse) of those three words, because the dataset row is meant to represent one canonical pass over each word, with repetitions only when they're on **home segments of the same verse**. The cross-verse audio is "transition content" — per the HF dataset card:

> Content not covered by timestamps (e.g. basmalas, cross-verse transitions) plays naturally in the original audio without word highlighting.

So the cross-verse seg's "مِّنْ إِفْكِهِمْ لَيَقُولُونَ" timings are dropped; the home seg's timings for those words win. The cross-verse seg still contributes "وَلَدَ ٱللَّهُ" to the 37:152 row (no home seg covers those two words).

Result:

```
37:151 row:  "أَلَآ إِنَّهُم مِّنْ إِفْكِهِمْ لَيَقُولُونَ"            (all from seg 1 — home)
37:152 row:  "وَلَدَ ٱللَّهُ"  +  "وَإِنَّهُمْ لَكَـٰذِبُونَ"      (seg 2 cross-verse + seg 3 home)
```

## Case 4 — Cross-verse segment with no overlapping home coverage

If a verse has no home segment, any cross-verse segment that touches it still contributes. That's exactly what happens for "وَلَدَ ٱللَّهُ" (the first two words of 37:152) in the example above — no home seg covers them, so the cross-verse seg's timing is used. If several cross-verse segs claimed the same word with no home alternative, first-seen wins.

## The merge rules in plain words

For each `(verse, word_idx)` the pipeline collects every contribution and classifies each one:

- **Primary** — from a home segment for this verse, and the widx is within the segment's declared range.
- **Transition** — from a cross-verse segment, or outside a home segment's declared range.

Then:

| Already have     | New arrives      | Result |
|------------------|------------------|--------|
| nothing          | primary          | keep it |
| nothing          | transition       | keep it (fills verse-boundary gap) |
| primary          | another primary  | **keep both** (within-verse repetition) |
| primary          | transition       | ignore the transition (cross-verse audio isn't duplicated in the home verse row) |
| transition       | primary          | drop the transition, keep the primary |
| transition       | another transition | ignore the second (first-seen wins) |

The third line is what makes within-verse repetitions work. The fourth and sixth lines are what keeps verse-boundary rows clean when a cross-verse segment overlaps existing home coverage.

## Why this asymmetry

Two home segments overlapping on the same verse represent **the reciter repeating within the verse** — two distinct utterances, both belong in that verse's row.

A cross-verse segment overlapping a home segment represents **a transition across ayah boundaries** — the audio exists and is preserved in the source, but the canonical word-level timing for a widx that already has home coverage is the home seg's. Dropping the cross-verse transition's timing for those widx keeps each row consistent with "widx is repeated only when another home segment of the same verse claims it."

## What consumers should expect

`timestamps.json` and `timestamps_full.json` can contain the **same `word_idx` more than once** within a verse. Order is by `start_ms`, so repeated occurrences appear chronologically.

Readers must iterate the word array, not index by widx. The HF dataset schema explicitly allows repeated `word_idx`. The Inspector TS tab iterates correctly — repetitions render as extra boundary lines on the waveform and as extra entries in the word list.

For gapless chapter playback, use `source_url` + `source_offset_ms` and let cross-verse transition audio play naturally without word highlighting (as documented in the HF dataset card).
