# How our timestamps compare to QUL

A side-by-side on one full mushaf — **Muhammad Siddiq Al-Minshawi (Murattal, Hafs)** — against the most widely used open word-timing source, [QUL / Tarteel](https://qul.tarteel.ai). Same reciter, same 6,236 verses, two independent pipelines. The point isn't to dismiss QUL — it's a solid baseline that we're grateful exists — but to show concretely what our alignment buys you.

- **Ours (QUA):** phoneme-level forced alignment, `mohammed_siddiq_al_minshawi_mp3quran` (mp3quran source, by-surah audio).
- **QUL:** Tarteel CDN per-ayah word segments.

Both give per-word `[word_index, start_ms, end_ms]` for every verse.

---

## The short version

| What we measured | QUL | QUA (ours) | Why it matters |
|---|---|---:|---:|
| **Word count matches the mushaf** (vs QPC Hafs ground truth) | 94.3% | **100.0%** | every word is accounted for, exactly once |
| **Reciter repetitions detected** | 53 verses | **469 verses** | follow-along doesn't desync when the reciter loops back |
| **Verse-start agreement** (first-word onset) | — | **±130 ms** | the two pipelines independently agree on where each verse begins |
| **Gaps stranded between words** | 98.9% of words | **6.4% of words** | highlighting never freezes in dead air mid-verse |

Two of these are *verifiable accuracy* claims (word count is checked against ground truth; repeats are structural facts in the audio). The timing rows are *agreement* between two independent systems — there is no third-party ground truth for millisecond boundaries, so we report where we line up and where we differ, and explain why.

---

## 1. Word accuracy — does every word get counted, exactly once?

This is the one claim we can check against an external authority: the [QPC Hafs](https://qul.tarteel.ai) word index says exactly how many words each verse contains. A timing file should have one entry per word (ignoring deliberate repeats).

| Source | Verses with the right word count | Accuracy |
|---|---|---|
| **QUA (ours)** | 6,236 / 6,236 | **100.0%** |
| QUL | 5,878 / 6,236 | 94.3% |

QUL over-counts on **358 verses** — 355 by exactly one word, 3 by two. And the pattern is systematic and easy to see: QUL splits the **vocative particle** off the following name.

| Verse | Mushaf words | QUL count | The split |
|---|---|---|---|
| 20:19 | 3 | 4 | `يَـٰمُوسَىٰ` counted as `يَ` + `مُوسَىٰ` |
| 3:43 | 7 | 8 | `يَـٰمَرْيَمُ` split |
| 19:12 | 7 | 8 | `يَـٰيَحْيَىٰ` split |
| 37:102 | 26 | 28 | two such splits in one verse |

Our pipeline matches the canonical one-word reading every time. This isn't just tidiness: a downstream app that maps word index → mushaf text will silently misalign on every one of those 358 verses if it trusts the over-counted source.

---

## 2. Repetition detection — the structural win

Reciters loop back. They repeat a phrase for emphasis, restart after a breath, or re-recite a passage. A timing file that ignores this will run out of words mid-verse and desync the highlight for the rest of the ayah.

| | QUL | QUA (ours) |
|---|---:|---:|
| Verses containing a detected repeat | 53 | **469** |
| Repeats QUL found that we also found | 53 | 53 |
| Repeats only this source found | 0 | **416** |

We detect **8.8× more** reciter loopbacks — and crucially, **every repeat QUL marks, we also mark** (QUL's 53 are a perfect subset of our 469). We add 416 that QUL misses entirely.

This falls straight out of how the pipeline works: it cuts the recording at the reciter's pauses and aligns each piece independently, so a repeated phrase is aligned to the words actually spoken rather than forced onto a single left-to-right pass.

**Examples QUL reads as plain sequential, where the reciter actually repeats** (seek the surah audio to hear it):

| Verse | Our word path | Repeated span | Listen |
|---|---|---|---|
| 2:14 | 1–6, **5–6**, 7–16 | words 5–6 | [002.mp3 @ 196s](https://server10.mp3quran.net/minsh/002.mp3) |
| 2:17 | 1–12, **6–12**, 13–17 | words 6–12 | [002.mp3 @ 246s](https://server10.mp3quran.net/minsh/002.mp3) |
| 2:31 | 1–10, **9–10**, 11–15 | words 9–10 | [002.mp3 @ 662s](https://server10.mp3quran.net/minsh/002.mp3) |
| 2:38 | 1–8, **5–8**, 9–17 | words 5–8 | [002.mp3 @ 835s](https://server10.mp3quran.net/minsh/002.mp3) |

When both sources *do* mark a repeat but disagree on where, it traces back to §1: QUL's extra word shifts its indices by one. We match the canonical word count, so our repeat span is the correct one.

| Verse | QUL repeats | QUA repeats (correct) |
|---|---|---|
| 2:61 | words 10–12 | words 9–11 |
| 2:213 | words 11–12 | words 10–12 |
| 3:118 | words 13–15 | words 12–14 |

---

## 3. Timing — where two independent pipelines line up

There's no millisecond ground truth, so this is *agreement*, not a scoreboard. The honest summary: **the two systems independently agree on verse structure and where verses begin; they differ on per-word boundaries, and that difference is a deliberate convention, not drift.**

The cleanest cross-check is the **verse start** — the onset of the first word, which neither pipeline can fudge with padding:

| Boundary | Mean difference | Typical error (MAE) |
|---|---:|---:|
| First word of the verse (start) | +66 ms | **130 ms** |
| Last word of the verse (end) | −515 ms | 595 ms |

Two pipelines built from completely different audio and code agree on verse starts to within ~130 ms. Verse *ends* differ more — QUL tends to extend the final word through trailing silence and elongation (madd), where we cut closer to the articulated sound.

Comparing each word's **midpoint** (robust to boundary padding) across the 5,520 verses where both agree on the word sequence:

| Within | Words agreeing |
|---|---|
| 200 ms | 40.4% |
| 500 ms | **75.6%** |

Three-quarters of all word centers land within half a second of each other — expected for two systems that disagree on how to treat the silence around each word, which is exactly what §4 is about.

---

## 4. Duration — why our words look "longer" (on purpose)

Our words are ~1.7× longer than QUL's on average. This is not over-reach — it's a different, more useful convention.

| | QUL | QUA (ours) |
|---|---:|---:|
| Median word duration | 640 ms | 1,090 ms |
| Median gap *between* words | 440 ms | **0 ms** |
| Words with a gap before them | 98.9% | 6.4% |

**QUL measures speech-only intervals and leaves the silence between words unassigned.** We **fill the gaps within a continuous breath** — each word extends to where the next begins — and only leave a gap at a real pause (a segment boundary).

For follow-along highlighting this is the difference between a smooth, continuous highlight and one that freezes in dead air between every single word. Recitation inside a breath group *is* continuous; our timing reflects that. If you need speech-only spans, the per-word onset still marks where each word is articulated — you simply have the choice, and QUL doesn't give you the gap-free option.

---

## What this means for you

**If you're reviewing recitations (contributors):** the pipeline you're correcting already gets word counts exactly right and catches ~9× more repetitions than the established source — your review starts from a strong baseline, and the validators flag the genuinely hard cases (boundary nudges, the occasional missed or extra repeat) rather than wholesale errors. The places worth your ear are verse endings and repeated passages.

**If you're building on the data (developers / researchers):** word index → mushaf text is safe to trust (100% against ground truth); repeats are preserved, so highlighting stays in sync across loopbacks; word timings are gap-free within a breath, so you get continuous highlighting for free; and verse onsets are solid to ~130 ms. Treat per-word durations as "until the next word" within a segment, not as speech-only spans.

---

<details><summary>Method &amp; reproducibility</summary>

- **Inputs:** QUL = `ayah-recitation-muhammad-siddiq-al-minshawi-murattal-hafs-959.json` (Tarteel CDN export); QUA = `mohammed_siddiq_al_minshawi_mp3quran` release zip (`word_timestamps.json.gz`). Ground truth = `data/surah_info.json` per-verse word counts (QPC Hafs).
- **Frames:** QUL segments are per-ayah; our word times are within-surah, so each verse's words are rebased by the verse start before any timing comparison.
- **Word match:** durations/onsets compared on the first occurrence of each word index; sequence/repeat/count metrics use the full index list per verse.
- **Repeat:** a verse "has a repeat" when its word-index sequence is ever non-increasing.
- All numbers above were produced by `.local/qul_compare/analyse.py` over all 6,236 verses.

</details>
