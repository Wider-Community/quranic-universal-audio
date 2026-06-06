# QUL timestamp comparison

A comparison of our word timestamps against [QUL / Tarteel](https://qul.tarteel.ai) on one full mushaf: **Muhammad Siddiq Al-Minshawi (Murattal, Hafs)**, all 6,236 verses.

- **QUA (ours):** phoneme-level forced alignment, `mohammed_siddiq_al_minshawi_mp3quran` (mp3quran source, by-surah audio).
- **QUL:** Tarteel CDN per-ayah word segments.

Both provide per-word `[word_index, start_ms, end_ms]` for every verse. Word counts can be checked against the QPC Hafs reference; timing has no third-party ground truth, so those sections report agreement between the two systems rather than accuracy.

---

## Summary

| Metric | QUL | QUA |
|---|---|---:|
| Word count matches QPC Hafs | 94.3% | 100.0% |
| Verses with a detected repeat | 53 | 469 |
| First-word onset agreement (MAE) | — | 130 ms |
| Words with a gap before them | 98.9% | 6.4% |

---

## 1. Word count

QPC Hafs defines how many words each verse contains. A timing file should have one entry per word, ignoring deliberate repeats.

| Source | Verses with correct word count | Accuracy |
|---|---|---|
| QUA | 6,236 / 6,236 | 100.0% |
| QUL | 5,878 / 6,236 | 94.3% |

QUL over-counts on 358 verses (355 by one word, 3 by two). The pattern is consistent: QUL splits the vocative particle from the following name.

| Verse | Mushaf words | QUL count | Split |
|---|---|---|---|
| 20:19 | 3 | 4 | `يَـٰمُوسَىٰ` as `يَ` + `مُوسَىٰ` |
| 3:43 | 7 | 8 | `يَـٰمَرْيَمُ` split |
| 19:12 | 7 | 8 | `يَـٰيَحْيَىٰ` split |
| 37:102 | 26 | 28 | two such splits in one verse |

QUA matches the canonical word count on every verse. An app mapping word index to mushaf text will misalign on the over-counted verses.

---

## 2. Repetition

When a reciter repeats a phrase — for emphasis, after a breath, or re-reciting a passage — the word indices step backwards. A timing file that ignores this runs out of words before the end of the verse.

| | QUL | QUA |
|---|---:|---:|
| Verses with a detected repeat | 53 | 469 |
| Repeats both sources marked | 53 | 53 |
| Repeats only this source marked | 0 | 416 |

QUA marks 469 verses with repeats to QUL's 53. QUL's 53 are a subset of QUA's, so QUA adds 416 that QUL does not mark. The pipeline cuts the recording at the reciter's pauses and aligns each segment independently, so a repeated phrase aligns to the words actually recited.

Verses QUL reads as sequential but where the reciter repeats (seek the surah audio to verify):

| Verse | QUA word path | Repeated span | Audio |
|---|---|---|---|
| 2:14 | 1–6, 5–6, 7–16 | words 5–6 | [002.mp3 @ 196s](https://server10.mp3quran.net/minsh/002.mp3) |
| 2:17 | 1–12, 6–12, 13–17 | words 6–12 | [002.mp3 @ 246s](https://server10.mp3quran.net/minsh/002.mp3) |
| 2:31 | 1–10, 9–10, 11–15 | words 9–10 | [002.mp3 @ 662s](https://server10.mp3quran.net/minsh/002.mp3) |
| 2:38 | 1–8, 5–8, 9–17 | words 5–8 | [002.mp3 @ 835s](https://server10.mp3quran.net/minsh/002.mp3) |

Where both mark a repeat but disagree on the span, the offset follows from §1: QUL's extra word shifts its indices by one.

| Verse | QUL span | QUA span |
|---|---|---|
| 2:61 | words 10–12 | words 9–11 |
| 2:213 | words 11–12 | words 10–12 |
| 3:118 | words 13–15 | words 12–14 |

---

## 3. Timing

There is no millisecond ground truth, so this section reports agreement between the two systems. The clearest reference point is the verse start — the onset of the first word, which is not affected by how either system pads word boundaries.

| Boundary | Mean difference | MAE |
|---|---:|---:|
| First word, start | +66 ms | 130 ms |
| Last word, end | −515 ms | 595 ms |

The two systems agree on verse starts to within ~130 ms. Verse ends differ more: QUL extends the final word through trailing silence and elongation (madd); QUA ends closer to the articulated sound.

Word midpoints (less sensitive to boundary padding), over the 5,520 verses where both agree on the word sequence:

| Within | Words agreeing |
|---|---|
| 200 ms | 40.4% |
| 500 ms | 75.6% |

Most word centers fall within half a second. The remaining spread comes from the duration convention in §4.

---

## 4. Duration

QUA words are ~1.7× longer than QUL words on average.

| | QUL | QUA |
|---|---:|---:|
| Median word duration | 640 ms | 1,090 ms |
| Median gap between words | 440 ms | 0 ms |
| Words with a gap before them | 98.9% | 6.4% |

The two systems use different conventions. QUL measures speech-only intervals and leaves the silence between words unassigned. QUA extends each word to the start of the next within a continuous segment, and only leaves a gap at a real pause (a segment boundary). The word onset still marks where each word is articulated, so speech-only spans can be recovered; QUL does not provide the gap-free form.

For follow-along highlighting, the gap-free form keeps the highlight continuous through a breath group instead of dropping between every word.

---

## Notes for consumers

- Word index to mushaf text is reliable (100% against QPC Hafs).
- Repeats are preserved, so highlighting stays aligned when the reciter loops back.
- Word durations are "until the next word" within a segment, not speech-only intervals.
- Verse onsets agree with QUL to ~130 ms; verse ends differ by the madd/trailing-silence convention.

For review work, the word counts and repeat detection are a solid starting point; verse endings and repeated passages are where manual checks are most useful.

---

<details><summary>Method</summary>

- **Inputs:** QUL = `ayah-recitation-muhammad-siddiq-al-minshawi-murattal-hafs-959.json` (Tarteel CDN export); QUA = `mohammed_siddiq_al_minshawi_mp3quran` release zip (`word_timestamps.json.gz`). Ground truth = `data/surah_info.json` per-verse word counts (QPC Hafs).
- **Frames:** QUL segments are per-ayah; QUA word times are within-surah, so each verse's words are rebased by the verse start before any timing comparison.
- **Word match:** durations and onsets are compared on the first occurrence of each word index; sequence, repeat, and count metrics use the full index list per verse.
- **Repeat:** a verse has a repeat when its word-index sequence is non-increasing at any step.
- All numbers were produced by `.local/qul_compare/analyse.py` over all 6,236 verses.

</details>
