# Phoneme Timestamp Distribution Analysis

## Background

Forced-alignment output gives per-phoneme intervals. Each phoneme is annotated with the tajweed rules (madd + ghunnah only) that apply to it.

### Phoneme inventory (Hafs)

- **28 base consonants**: `b, t, θ, ʒ, ħ, x, d, ð, r, z, s, ʃ, sˤ, dˤ, tˤ, ðˤ, ʕ, ɣ, f, q, k, l, m, n, h, w, j, ʔ`
- **Shaddah / gemination**: doubled phoneme symbol (`bb, tt, …`), *except* `m` and `n` whose shaddah always carries ghunnah and uses nasalized symbols (`m̃, ñ`)
- **Short vowels (haraka)**: `a u i`
- **Long vowels (madd)**: `a: u: i:`
- **Emphatic variants**: `aˤ, aˤ:` (vowel after istilaa consonants); `rˤ, rˤrˤ` (heavy raa); `lˤlˤ` (heavy lam — only in Allah)
- **Tajweed-specific**: `ŋ` (ikhfaa noon/tanween); `ñ, m̃, j̃, w̃` (ghunnah)

### JSON structure (`timestamps_tajweed.json`)

Mirrors `timestamps_full.json` (compact, array-based). One key per verse:

```
"<surah>:<ayah>": {
  "verse_start_ms", "verse_end_ms",
  "words": [
    [word_idx, start_ms, end_ms,
      [ [char, start_ms, end_ms], ... ],                 # letters (no rules)
      [ [phoneme, start_ms, end_ms]                      # no rule
        | [phoneme, start_ms, end_ms, "rule_name"], ... ]  # rule attached
    ], ...
  ]
}
```

**2:18:1 `صُمٌّ`** — `meem_ghunnah` + `iqlab_tanween`

```json
[1, 278625, 280735,
  [ ["ص", 278625, 278885], ["م", 278885, 280735] ],
  [
    ["sˤ", 278625, 278685],
    ["u",  278685, 278885],
    ["m̃", 278885, 279735, "meem_ghunnah"],
    ["u",  279735, 280465],
    ["ŋ",  280465, 280735, "iqlab_tanween"]
  ]
]
```

**17:40:7 `إِنَـٰثًا ۚ`** (mid-verse stop) — `madd_tabii` (dagger alef) + `madd_tabii` (iwad from tanween at stop)

```json
[7, 678295, 679285,
  [ ["إ", 678295, 678475], ["ن", 678475, 678565], ["ٰ", 678565, 678835], ["ث", 678835, 679025], ["ا", 679025, 679285] ],
  [
    ["ʔ",  678295, 678315],
    ["i",  678315, 678475],
    ["n",  678475, 678565],
    ["a:", 678565, 678835, "madd_tabii"],
    ["θ",  678835, 679025],
    ["a:", 679025, 679285, "madd_tabii"]
  ]
]
```

Rules apply **only to phonemes**. A phoneme carries at most one rule (the 4th element is a single string when present). Rule names belong to a fixed set:

- **Madd**: `madd_tabii`, `madd_wajib_muttasil`, `madd_jaiz_munfasil`, `madd_lazim`, `madd_arid_lissukun`, `madd_leen`
- **Ghunnah**: `noon_ghunnah`, `meem_ghunnah`, `ikhfaa_noon`, `ikhfaa_tanween`, `ikhfaa_shafawi`, `iqlab_noon`, `iqlab_tanween`, `idgham_ghunnah_noon`, `idgham_ghunnah_tanween`, `idgham_shafawi`


## Goal

Build notebooks/scripts that explore the duration landscape of phonemes (and words) and surface trends, expected ratios, anomalies, and likely alignment errors.

## Suggested directions (not exhaustive)

### General distributions
- Per-phoneme duration distributions across the whole Quran
- Word-level duration distributions

### Consonants & shaddah
- Geminated vs. plain consonant duration (`bb` vs `b`, `tt` vs `t`, …) — expected ratio, outliers
- Shaddah relationships per consonant family
- Consistencies / Inconsistencies across consonant phonemes
- Consistencies / Inconsistencies across shaddah phonemes

### Vowels
- Short vs. long vowel ratio (use `madd_tabii` only as the clean long-vowel baseline; other madd rules vary)
- Per-vowel-letter consistency: `a:`, `i:`, `u:` should behave the same under the same rule

### Allophones / emphatic variants
- `r` vs `rˤ` 
- `rr` vs `rˤrˤ`
- `ll` vs `lˤlˤ`
- `a` vs `aˤ`, `a:` vs `aˤ:`
- Same rule, different variant — duration should match

### Garbage timestamps 
- Extremely short durations (e.g. < 20ms/40ms/60ms or as suitable based on averages in data) are likely garbage/alignment errors — check distribution of these and surface worst offenders (e.g. specific phonemes/contexts/patterns)
- Extremely long durations (e.g. > 500ms/1s or as suitable based on data) for non-ghunnah/non-madd are also likely garbage/alignment errors — check distribution and surface worst offenders

### Ghunnah
- Per-rule duration distributions (10 ghunnah rules - can be classified/grouped semantically, by rule type, by phoneme, etc.)
- Per-sound distributions over the **five ghunnah carriers**: `ŋ` (ikhfaa), `m̃`, `ñ`, `w̃`, `j̃`
- Consonant ↔ ghunnah ↔ shaddah comparisons:
  - `m` vs `m̃` 
  - `n` vs `ñ`
  - `w` vs `w̃` vs `ww`
  - `j` vs `j̃` vs `jj`

### Madd
Expected counts per rule (in harakat, where 1 harakah ≈ short-vowel duration):
- `madd_tabii` — 2
- `madd_jaiz_munfasil` — 2 or 4
- `madd_wajib_muttasil` — 4 or 5
- `madd_lazim` — 6
- `madd_arid_lissukun` — 2, 4, or 6
- `madd_leen` — 2, 4, or 6

After normalizing duration by reciter's harakah baseline (e.g. mean of plain short vowels), distributions per rule should cluster near these counts. Same rule across the 3 vowel letters should not differ.

Another approach is to normalize by mean of `madd_tabii` durations, and calculate ratios for the other rules.

### Specific patterns worth probing
- **`madd_jaiz_munfasil`** (long vowel at word-end + hamza in next word): hamza (`ʔ`) is a fast phoneme but acoustically similar to the preceding vowel — expect the long vowel timestamp to be eaten by the following hamza in many cases. Check the distribution of vowel/hamza ratio.
- **`madd_lazim` + `noon_ghunnah` / `meem_ghunnah`** (e.g. `الٓم`): both rules have long obligatory durations on adjacent phonemes — check whether each gets its own time or one absorbs the other.
- Any other linguistic edge cases, or as surfaced by the data (e.g. outliers, anomalies, unexpected patterns in specific verses/words/phonemes)

## Deliverables

- Scripts / Notebook(s) with clear plots (e.g. histograms, violin/box, ECDFs, ratio plots; not exhaustive) covering the directions above
- Short written summary of findings — surprises, suspected alignment errors, phonemes/contexts to flag back to the pipeline
- Lists/Examples of verses/words for the worst outliers, so they can be spot-checked in the Inspector
- Currently, only Minshawi is timestamped - future analysis can compare different reciters. Design so adding more reciters is easy.

## Inputs

- `data/timestamps/by_surah_audio/<reciter>/timestamps_tajweed.json`
- `data/surah_info.json` (verse/word counts, ground truth)


