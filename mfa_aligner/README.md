---
title: MFA Aligner
emoji: 🎙
colorFrom: green
colorTo: blue
sdk: docker
pinned: false
---

# Quran Phoneme MFA Aligner

Phoneme-level forced alignment service for Quranic recitations, built on [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/) and deployed as a Hugging Face Space (`hetchyy/Quran-phoneme-mfa`).

Given an audio recording of a Quran verse and a reference (e.g. `7:2`), the service produces **word-level**, **letter-level**, and **phoneme-level** timestamps — how long each word, Arabic character, and individual phoneme lasts in the recitation.

## Table of Contents

- [How It Works](#how-it-works)
- [Alignment Pipeline](#alignment-pipeline)
- [Relationship with quranic-phonemizer](#relationship-with-quranic-phonemizer)
- [The Identity Dictionary](#the-identity-dictionary)
- [Phoneme Transform Pipeline](#phoneme-transform-pipeline)
- [Word Timestamp Construction](#word-timestamp-construction)
- [Letter-Level Timestamps](#letter-level-timestamps)
- [Handling Geminates, Silent Letters, and Assimilation](#handling-geminates-silent-letters-and-assimilation)
- [Special Segments: Basmala and Isti'adha](#special-segments-basmala-and-istiadha)
- [KalpyEngine](#kalpyengine)
- [Alignment Methods and Fallback Chain](#alignment-methods-and-fallback-chain)
- [Parameters and Settings](#parameters-and-settings)
- [API Endpoints](#api-endpoints)
- [Reference Format](#reference-format)
- [Deployment](#deployment)

## How It Works

```
Audio (WAV) ──┐
              ├──► MFA Alignment ──► Phone Intervals ──► Word Timestamps
Reference ────┘                                      └──► Letter Timestamps
  "7:2"   → phonemizer → phonemes → .lab file                └──► Phoneme Timestamps
```

1. The **quranic-phonemizer** converts the verse reference into a sequence of IPA phonemes with word-level and character-level mappings
2. Phonemes are written to a `.lab` file after applying [transforms](#phoneme-transform-pipeline) (colon normalization, qalqala removal, emphatic cleanup, geminate splitting)
3. **MFA** aligns the audio against the phoneme sequence, producing time-stamped phone intervals
4. Phone intervals are mapped back to **words** using word-phoneme counts from the phonemizer
5. Phone intervals are mapped to **letters** (Arabic characters) using many-to-many flat mappings from the phonemizer

## Alignment Pipeline

The full alignment flow for a single request:

```
parse_ref("7:2:3-7:4:1")
    │
    ▼
_phonemize_ref("7:2-7:4")          ◄── quranic-phonemizer
    │
    ├── words: [{location, text, phonemes}, ...]
    └── flat_entries: [(chars, phonemes), ...]   ◄── build_letter_phoneme_mapping()
    │
    ▼
_prepare_ref()
    │
    ├── Filter words to requested range (word 3 of 7:2 → word 1 of 7:4)
    ├── Prepend special segments if present (Basmala, Isti'adha)
    └── Build lab_content: transform_phonemes(normalize_phonemes(phonemes))
    │
    ▼
run_mfa(wav_path, lab_content, method, beam, retry_beam)
    │
    └── Returns: [{start, end, phone}, ...]     ◄── raw phone intervals
    │
    ▼
build_words_from_mapping(intervals, word_maps)
    │
    └── Returns: [{location, text, start, end, phone_indices}, ...]
    │
    ▼
build_reverse_mapped_intervals(intervals, words)
    │
    └── Restores original phoneme names, merges geminate pairs
    │
    ▼
_pad_intervals(intervals, padding="forward")
    │
    └── Fills timing gaps between consecutive phones
    │
    ▼
build_letter_timestamps(intervals, flat_entries, phoneme_sequence)
    │
    └── Returns: [{chars, start, end, is_word_end}, ...]
    │
    ▼
group_letters_by_word(letter_groups, words)
    │
    └── Returns: [{location, text, start, end, letters: [{char, start, end}, ...]}, ...]
```

## Relationship with quranic-phonemizer

The [quranic-phonemizer](https://pypi.org/project/quranic-phonemizer/) package (`>=2.0`) is used for two purposes:

### 1. Phonemization

```python
from quranic_phonemizer import Phonemizer

phonemizer = Phonemizer()
result = phonemizer.phonemize(ref="7:2")
mapping = result.get_mapping()
```

This returns a `PhonemizationMapping` containing a list of `WordMapping` objects. For example, 7:2 produces:

```python
WordMapping(location="7:2:1",  text="كِتَـٰبٌ",          phonemes=["k", "i", "t", "a:", "b", "u", "n"])
WordMapping(location="7:2:2",  text="أُنزِلَ",           phonemes=["ʔ", "u", "ŋ", "z", "i", "l", "a"])
WordMapping(location="7:2:3",  text="إِلَيْكَ",           phonemes=["ʔ", "i", "l", "a", "j", "k", "a"])
WordMapping(location="7:2:4",  text="فَلَا",             phonemes=["f", "a", "l", "a:"])
WordMapping(location="7:2:5",  text="يَكُن",             phonemes=["j", "a", "k", "u", "ŋ"])
WordMapping(location="7:2:6",  text="فِى",              phonemes=["f", "i:"])
WordMapping(location="7:2:7",  text="صَدْرِكَ",           phonemes=["sˤ", "aˤ", "d", "Q", "r", "i", "k", "a"])
WordMapping(location="7:2:8",  text="حَرَجٌ",            phonemes=["ħ", "a", "rˤ", "aˤ", "ʒ", "u"])
WordMapping(location="7:2:9",  text="مِّنْهُ",            phonemes=["m̃", "i", "n", "h", "u"])
WordMapping(location="7:2:10", text="لِتُنذِرَ",          phonemes=["l", "i", "t", "u", "ŋ", "ð", "i", "rˤ", "aˤ"])
WordMapping(location="7:2:11", text="بِهِۦ",             phonemes=["b", "i", "h", "i:"])
WordMapping(location="7:2:12", text="وَذِكْرَىٰ",         phonemes=["w", "a", "ð", "i", "k", "rˤ", "aˤ:"])
WordMapping(location="7:2:13", text="لِلْمُؤْمِنِينَ",     phonemes=["l", "i", "l", "m", "u", "ʔ", "m", "i", "n", "i:", "n"])
```

Notable phonemes: `ŋ` is ikhfaa (hidden noon), `Q` is qalqala, `m̃` is idgham with ghunnah, `rˤ` is heavy raa, `aˤ` is emphatic vowel.

The phoneme list is what MFA aligns against. Word boundaries are recovered by counting how many phonemes belong to each word.

### 2. Letter-Phoneme Mapping

```python
lpm = result.letter_phoneme_mappings()
flat_entries = lpm.to_list()
```

For 1:1 (Basmala: بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ), this returns:

```python
[
    ("ب",   ["b", "i"]),          # بِسْمِ: ba with kasra
    ("س",   ["s"]),               #         sin (sukun = no vowel)
    ("م ",  ["m", "i"]),          #         mim with kasra (trailing space = word boundary)
    ("ٱلل", ["ll", "a:"]),       # ٱللَّهِ: hamza wasl + lam merge into geminate lam
    ("ه ",  ["h", "i"]),          #         ha with kasra
    ("ٱلر", ["rˤrˤ", "aˤ"]),    # ٱلرَّحْمَـٰنِ: hamza wasl + lam assimilate into heavy raa geminate
    ("ح",   ["ħ"]),               #         haa (sukun)
    ("م",   ["m"]),               #         mim
    ("ٰ",   ["a:"]),              #         superscript alef (long vowel)
    ("ن ",  ["n", "i"]),          #         nun with kasra
    ("ٱلر", ["rˤrˤ", "aˤ"]),    # ٱلرَّحِيمِ: same assimilation pattern
    ("ح",   ["ħ"]),               #         haa
    ("ي",   ["i:"]),              #         yaa (long vowel)
    ("م",   ["m"]),               #         mim (end of verse, no trailing space)
]
```

These are many-to-many mappings between groups of Arabic characters and groups of phonemes. The mappings encode:

- Which characters are **silent** (e.g. hamza wasl `ٱ` before lam in definite articles)
- Which phonemes span **multiple characters** (e.g. idgham assimilation)
- Which characters produce **multiple phonemes** (e.g. voweled consonants)

The aligner does not modify or configure the phonemizer — it uses default settings. The dependency is one-directional: `mfa_aligner` depends on `quranic-phonemizer`, not the reverse.

## The Identity Dictionary

The file `dictionary.txt` maps each phoneme to itself:

```
a	a
aː	aː
b	b
dˤ	dˤ
bb	bb
rˤrˤ	rˤrˤ
sil	sil
sp	sp
...
```

This is an **identity dictionary** — every entry's pronunciation is the same as its spelling. This works because inputs are already phonemized by `quranic-phonemizer`. MFA needs a dictionary to recognize tokens, but no grapheme-to-phoneme conversion is needed. The dictionary contains 72 entries covering all Quranic Arabic phonemes, their geminate forms, and silence tokens (`sil`, `sp`).

## Phoneme Transform Pipeline

Before phonemes are passed to MFA, they go through a fixed transform chain. The same transforms are applied consistently across the entire codebase (`extract_segments.py`, `mfa_aligner/app.py`, `scripts/prepare_labs.py`, `inspector/server.py`).

### Step 1: `normalize_phonemes()`

Converts ASCII colon `:` to IPA length marker `ː` (U+02D0):

```
aː  ←  a:
iː  ←  i:
```

### Step 2: `transform_phonemes()`

Applied token-by-token after splitting on spaces:

| Transform | Before | After | Reason |
|-----------|--------|-------|--------|
| Remove qalqala marker | `Q` | *(skipped)* | `Q` marks glottal closure quality, not a distinct phone in the acoustic model |
| Drop emphatics from r, a, l | `rˤ` → `r`, `aˤ` → `a`, `lˤ` → `l` | Simplified | The acoustic model doesn't distinguish these emphatic variants for these specific consonants |
| Split geminates | `bb` | `b b` | MFA aligns individual phones; geminates are two consecutive instances of the same phone |

**Example — 1:1:3 ٱلرَّحْمَـٰنِ** (phonemes: `rˤrˤ aˤ ħ m a: n i`):

```
Raw:         rˤrˤ aˤ ħ m a: n i
Step 1:      rˤrˤ aˤ ħ m aː n i       (a: → aː)
Step 2:      rˤ rˤ a ħ m aː n i       (geminate split, emphatic aˤ → a)
```

**Example — 7:2:7 صَدْرِكَ** (phonemes: `sˤ aˤ d Q r i k a`):

```
Raw:         sˤ aˤ d Q r i k a
Step 1:      sˤ aˤ d Q r i k a        (no ASCII colons)
Step 2:      sˤ a d r i k a           (Q removed, emphatic aˤ → a)
```

**Example — 1:1 full Basmala:**

```
Raw:         b i s m i ll a: h i rˤrˤ aˤ ħ m a: n i rˤrˤ aˤ ħ i: m
Step 1:      b i s m i ll aː h i rˤrˤ aˤ ħ m aː n i rˤrˤ aˤ ħ iː m
Step 2:      b i s m i l l aː h i rˤ rˤ a ħ m aː n i rˤ rˤ a ħ iː m
```

## Word Timestamp Construction

**Function:** `build_words_from_mapping()` in `app.py`

Given MFA's raw phone intervals and the phonemizer's word mappings, word timestamps are recovered by counting phonemes:

1. Filter phone intervals to **non-silence** phones (exclude `sil`, `sp`, `spn`)
2. For each word in the phonemizer's word list:
   - Get its phoneme list (e.g. `["b", "i", "s", "m", "i"]` for بِسْمِ)
   - Apply `normalize_phonemes()` + `transform_phonemes()` to get the expected count
   - Consume that many consecutive non-silence intervals from the cursor
   - Word **start** = first consumed interval's start time
   - Word **end** = last consumed interval's end time
3. Track which interval indices belong to each word (`phone_indices`)

**Example — Basmala (1:1):**

```
                                    transform
Word          Phonemes              count     Intervals consumed
────          ────────              ─────     ──────────────────
بِسْمِ         [b, i, s, m, i]     → 5        b i s m i           → start=0.10, end=0.70
ٱللَّهِ        [ll, a:, h, i]      → 5        l l aː h i          → start=0.70, end=1.20
                                              (ll splits to l l = 2, plus aː h i = 3, total 5)
ٱلرَّحْمَـٰنِ    [rˤrˤ, aˤ, ħ, m, a:, n, i] → 8   rˤ rˤ a ħ m aː n i  → start=1.20, end=2.10
                                              (rˤrˤ splits to rˤ rˤ = 2, aˤ → a = 1, total 8)
ٱلرَّحِيمِ      [rˤrˤ, aˤ, ħ, i:, m]       → 6   rˤ rˤ a ħ iː m      → start=2.10, end=2.80
```

## Letter-Level Timestamps

**Function:** `build_letter_timestamps()` in `app.py`

Letter timestamps map MFA phone intervals back to individual Arabic characters. This is the most complex part of the system because the relationship between characters and phonemes is **many-to-many**.

### The Problem

Arabic script doesn't have a 1:1 character-to-phoneme relationship:

- **One character → multiple phonemes:** The ص in صَدْرِكَ (7:2:7) produces `sˤ aˤ` (emphatic consonant + emphatic vowel)
- **Multiple characters → one phoneme:** In ٱللَّهِ, the three characters ٱلل produce just `ll a:` — hamza wasl is silent and lam assimilates into the shaddah lam
- **Silent characters:** Hamza wasl (ٱ) is silent in ٱلرَّحْمَـٰنِ; the `Q` (qalqala) phoneme in دْ of صَدْرِكَ has no acoustic realization in the model
- **Cross-word effects:** In مِّنْهُ (7:2:9), the initial mim carries idgham with ghunnah (`m̃`) from the preceding word's nun

### The Solution: Flat Mappings

The `letter_phoneme_mappings()` method from `quranic-phonemizer` returns a flat list of `(characters, phonemes)` tuples that encode all these relationships. For the Basmala (1:1), the full mapping is:

```python
("ب",   ["b", "i"])          # بِسْمِ: ba produces 2 phonemes (consonant + kasra vowel)
("س",   ["s"])               #         sin with sukun → 1 phoneme (no vowel)
("م ",  ["m", "i"])          #         mim + kasra; trailing space marks word boundary
("ٱلل", ["ll", "a:"])       # ٱللَّهِ: 3 characters → 2 phonemes
                              #         hamza wasl (ٱ) is silent, lam assimilates into
                              #         the next lam (shaddah), producing geminate "ll"
("ه ",  ["h", "i"])          #         ha with kasra
("ٱلر", ["rˤrˤ", "aˤ"])    # ٱلرَّحْمَـٰنِ: hamza wasl silent, lam assimilates into
                              #         heavy raa (sun letter rule), producing geminate "rˤrˤ"
("ح",   ["ħ"])               #         haa with sukun
("م",   ["m"])               #         mim
("ٰ",   ["a:"])              #         superscript alef → long vowel
("ن ",  ["n", "i"])          #         nun with kasra
```

For 7:2:7 صَدْرِكَ (which contains qalqala):

```python
("ص",   ["sˤ", "aˤ"])       # saad with fatha → emphatic consonant + emphatic vowel
("د",   ["d", "Q"])          # dal with sukun → consonant + qalqala bounce
("ر",   ["r", "i"])          # raa with kasra
("ك ",  ["k", "a"])          # kaf with fatha; space marks word end
```

### The Algorithm

1. **Build an index from original phonemes to MFA intervals.** Walk the original phoneme sequence and the list of non-silence MFA intervals in parallel. Phonemes marked `Q` (qalqala) get no interval (they're silent). Every other phoneme maps to one MFA interval.

2. **Process each flat entry.** For each `(chars, phonemes)` tuple, advance through the original phoneme sequence and collect the corresponding MFA interval indices. The letter group's start time is the earliest interval's start; its end time is the latest interval's end.

3. **Handle gaps.** If a flat entry maps entirely to `Q` phonemes (no intervals), it inherits the start time of the next group.

4. **Group by word.** The `group_letters_by_word()` function splits letter groups at word boundaries (detected by spaces in the `chars` field) and assigns them to the correct word.

5. **Split into individual characters.** Within each letter group, `split_into_letters()` separates base characters from diacritics. Diacritics attach to their preceding base character. The `SPLITTABLE_CHARS` set defines the 28 Arabic base letters plus extensions (madd marks, hamza forms).

### Output Structure

Example for 1:1:1 بِسْمِ (flat mappings: `ب→[b,i]`, `س→[s]`, `م→[m,i]`):

```json
{
  "location": "1:1:1",
  "text": "بِسْمِ",
  "start": 0.10,
  "end": 0.70,
  "letters": [
    {"char": "بِ", "start": 0.10, "end": 0.25},
    {"char": "سْ", "start": 0.25, "end": 0.45},
    {"char": "مِ", "start": 0.45, "end": 0.70}
  ]
}
```

## Handling Geminates, Silent Letters, and Assimilation

### Geminates (Shaddah)

A geminate like the لّ in ٱللَّهِ produces the phoneme `ll`. The transform pipeline splits this into two MFA phones: `l l`. Similarly, the رّ in ٱلرَّحْمَـٰنِ produces `rˤrˤ` which splits to `rˤ rˤ`. After alignment, `build_reverse_mapped_intervals()` re-merges them:

- The first phone gets the original name and `geminate_start: true`
- The second phone's name is emptied with `geminate_end: true`
- This prevents double-counting when building letter timestamps

### Silent Letters

Characters that produce no sound (e.g. hamza wasl before lam, alef after certain constructions) are handled by the flat mappings. When a character group maps to phonemes that are all `Q` or when the character is grouped with adjacent characters that share its phonemes, the silent character inherits timing from its neighbors.

### Cross-Word Assimilation (Idgham)

When a word-final consonant assimilates into the next word's initial consonant, the flat mapping spans both words with a space in the `chars` field. For example, in the Basmala the mim of بِسْمِ connects to the next word ٱللَّهِ — the space in `"م "` marks the word boundary. In cases of nun idgham (e.g. مِن رَّبِّهِمْ where nun assimilates into raa), the mapping would span across: `"ن ر", ["rˤrˤ"]`.

`group_letters_by_word()` detects the space and splits the entry: the part before the space goes to the current word, the part after is saved as pending for the next word. Both share the same time span.

## Special Segments: Basmala and Isti'adha

The Basmala (بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ) and Isti'adha (أَعُوذُ بِٱللَّهِ مِنَ ٱلشَّيْطَانِ ٱلرَّجِيمِ) are not Quranic verses — they appear before recitation but aren't in the phonemizer's verse database. They are handled with hardcoded data:

- **`SPECIAL_PHONEMES`** — Full phoneme sequences
- **`SPECIAL_WORDS`** — Word-level breakdown with locations like `"0:0:1"`, `"0:0:2"`, etc.
- **`SPECIAL_FLAT_MAPPINGS`** — Character-to-phoneme mappings for letter-level timestamps, manually derived from phonemizer output for Surah 1 (Al-Fatiha) verse 1

These are prepended to the reference when the `ref` string starts with `"Basmala+"` or `"Isti'adha+"`:

```
"Isti'adha+Basmala+7:2:1-7:2:5"
→ Isti'adha phonemes + Basmala phonemes + verse 7:2 words 1-5 phonemes
```

## KalpyEngine

The `KalpyEngine` class is the primary alignment backend. It uses [kalpy](https://github.com/MontrealCorpusTools/kalpy) (Python bindings for Kaldi) for direct alignment without subprocess overhead, achieving ~0.01s per segment.

### Architecture

```python
KalpyEngine.__init__():
    ├── Load acoustic model from quran_aligner_model.zip
    ├── Build LexiconCompiler from dictionary.txt
    │     └── Uses model-derived silence probabilities
    ├── Create SimpleTokenizer
    ├── Initialize CMVN computer
    └── Cache: _aligner_cache = {}  # keyed by (beam, retry_beam)
```

### Single Alignment

```python
engine.align(wav_path, lab_content, beam=10, retry_beam=40)
```

1. Parse WAV file → audio features
2. Generate MFCCs (Mel-Frequency Cepstral Coefficients)
3. Apply per-utterance CMVN normalization
4. Run Viterbi alignment via `KalpyAligner.align_utterance()`
5. Convert `HierarchicalCtm` → list of phone interval dicts

### Batch Alignment with Shared CMVN

```python
engine.align_batch(segments, beam=10, retry_beam=40, shared_cmvn=False)
```

When `shared_cmvn=True`, CMVN statistics are computed across **all** utterances in the batch before applying normalization. This produces more consistent results when audio segments come from varied recording conditions or recitation styles.

When `shared_cmvn=False` (default), each utterance gets its own CMVN normalization independently.

### Aligner Caching

`KalpyAligner` instances are cached by `(beam, retry_beam)` tuple. If the same beam parameters are used across requests, the cached aligner is reused without re-initialization.

## Alignment Methods and Fallback Chain

Four alignment methods are available, tried in order if the preferred method fails:

| Method | Speed | Mechanism |
|--------|-------|-----------|
| **kalpy** | ~0.01s/seg | Direct Kaldi API via KalpyEngine. No subprocess, no database. |
| **align_one** | ~1-2s/seg | MFA CLI: `mfa align_one wav lab dict model output`. Single-file, no corpus setup. |
| **python_api** | ~0.3-0.5s/seg | MFA's `PretrainedAligner` class with cached model. Re-initializes corpus per request but skips model reload. |
| **cli** | ~5-10s/seg | Full MFA CLI: `mfa align corpus/ dict model output/ --clean --single_speaker`. Complete corpus pipeline. |

The `run_mfa()` dispatcher selects the requested method and automatically falls back to `align_one` if kalpy fails, or to the next method in the chain.

## Parameters and Settings

### Alignment Parameters

| Parameter | Default | Range | Description |
|-----------|---------|-------|-------------|
| `beam` | 10 | 1–50 | Viterbi beam width for the main alignment pass. Narrower = faster but more likely to fail on difficult audio. |
| `retry_beam` | 40 | 10–100 | Beam width for the retry pass if the first alignment fails. Wider = more robust but slower. |
| `shared_cmvn` | `false` | `true`/`false` | Compute CMVN normalization across the entire batch instead of per-utterance. Only applies to kalpy method. Better for batches with varied audio conditions. |
| `method` | `"kalpy"` | `"kalpy"`, `"align_one"`, `"python_api"`, `"cli"` | Which alignment engine to use. |

### Post-Processing Parameters

| Parameter | Default | Options | Description |
|-----------|---------|---------|-------------|
| `padding` | `"forward"` | `"forward"`, `"symmetric"`, `"none"` | How to fill timing gaps between consecutive phones. |
| `include_letters` | `false` | `true`/`false` | Whether to compute and return letter-level timestamps (adds processing time). |

### Padding Strategies

MFA phone intervals often have small gaps between them. The padding strategy fills these gaps:

- **forward:** Extend each phone's end time to match the next phone's start time. Gaps disappear; all time is assigned to the preceding phone.
- **symmetric:** Split each gap at its midpoint — half goes to the preceding phone, half to the following phone.
- **none:** Leave gaps as-is. Timestamps may not be contiguous.

### Acoustic Model Parameters

These are loaded from `quran_aligner_model.zip` and used by KalpyEngine's lexicon compiler:

- `silence_probability` — Prior probability of silence between words
- `initial_silence_probability` — Probability of silence at utterance start
- `final_silence_correction` / `final_non_silence_correction` — Adjustments for utterance boundaries
- `position_dependent_phones` — Whether phone models are context-dependent (beginning/middle/end of word)

## API Endpoints

The Gradio app exposes several API endpoints:

### `align_batch` — Primary Production Endpoint

Aligns multiple audio segments against multiple verse references in a single request.

**Input:**

| Field | Type | Description |
|-------|------|-------------|
| `refs` | JSON array of strings | Verse references (e.g. `["7:2", "Basmala+7:3"]`) |
| `files` | list of audio files | One audio file per reference |
| `method` | string | Alignment method (default: `"kalpy"`) |
| `beam` | int | Beam width (default: 10) |
| `retry_beam` | int | Retry beam width (default: 40) |
| `shared_cmvn` | bool | Use shared CMVN (default: false) |
| `padding` | string | Gap-filling strategy (default: `"forward"`) |

**Output:**

```json
{
  "status": "ok",
  "results": [
    {
      "ref": "1:1",
      "status": "ok",
      "words": [
        {
          "location": "1:1:1",
          "text": "بِسْمِ",
          "start": 0.10,
          "end": 0.70,
          "letters": [
            {"char": "بِ", "start": 0.10, "end": 0.25},
            {"char": "سْ", "start": 0.25, "end": 0.45},
            {"char": "مِ", "start": 0.45, "end": 0.70}
          ]
        },
        {
          "location": "1:1:2",
          "text": "ٱللَّهِ",
          "start": 0.70,
          "end": 1.20,
          "letters": [
            {"char": "ٱ", "start": 0.70, "end": 0.80},
            {"char": "لَّ", "start": 0.80, "end": 1.00},
            {"char": "هِ", "start": 1.00, "end": 1.20}
          ]
        }
      ]
    }
  ],
  "timing": {
    "total": 0.45,
    "phonemize": 0.02,
    "mfa": 0.01,
    "words": 0.001,
    "letters": 0.003
  }
}
```

### `align_phonemes` — Raw Phoneme Alignment

Aligns audio against a pre-transformed phoneme string (no phonemizer involved).

**Input:** audio file + phoneme string + method + beam parameters

**Output:** `{"status": "ok", "intervals": [{start, end, phone}, ...], "num_intervals": N}`

### `compare_methods` — Method Comparison

Runs both kalpy and align_one on the same input and reports differences in phone counts, phone names, and timing.

### `batch_benchmark` — Performance Benchmarking

Duplicates a single segment N times and aligns with all four methods, reporting per-method timing breakdown.

## Reference Format

The `ref` parameter supports flexible verse and word-range specifications:

| Format | Meaning |
|--------|---------|
| `7:2` | Surah 7, ayah 2, all words |
| `7:2-7:5` | Surah 7, ayah 2 through ayah 5 |
| `7:2:3` | Surah 7, ayah 2, word 3 only |
| `7:2:3-7:2:5` | Surah 7, ayah 2, words 3 through 5 |
| `7:2:3-7:4:1` | Cross-ayah range: surah 7, ayah 2 word 3 through ayah 4 word 1 |
| `Basmala+7:2` | Basmala prepended before verse |
| `Isti'adha+Basmala+7:2` | Both Isti'adha and Basmala prepended |

## Deployment

### Docker (HF Spaces)

The app runs as a Docker-based Hugging Face Space:

```dockerfile
FROM condaforge/mambaforge:latest
# Python 3.11 (pinned; 3.14 breaks Path.copy() in MFA)
# System: ffmpeg for audio conversion
# Conda: montreal-forced-aligner
# Pip: gradio, soundfile, tgt, numpy, PyYAML, quranic-phonemizer>=2.0
# Port: 7860
```

### Local

```bash
cd mfa_aligner/
# Install MFA via conda
conda create -n mfa -c conda-forge montreal-forced-aligner python=3.11
conda activate mfa
pip install gradio soundfile tgt numpy PyYAML quranic-phonemizer>=2.0
mfa server init
python app.py
# Gradio UI at http://localhost:7860
```

### Audio Requirements

All input audio is converted to **16kHz mono WAV** (PCM 16-bit) before alignment. The conversion tries Python's `soundfile` first, falling back to `ffmpeg` if that fails.

## Timing Breakdown

Each request returns timing measurements:

| Key | What it measures |
|-----|-----------------|
| `phonemize` | `Phonemizer.phonemize()` call |
| `flat_map` | `build_letter_phoneme_mapping()` call |
| `mfa` | MFA alignment (all methods) |
| `words` | `build_words_from_mapping()` |
| `letters` | `build_letter_timestamps()` + `group_letters_by_word()` |

## Error Handling

The system degrades gracefully:

- **KalpyEngine init fails** → falls back to `align_one` CLI method
- **Individual segment fails in batch** → that segment returns `{"status": "error", "error": "..."}`, other segments continue
- **Letter timestamp building fails** → words returned without `letters` field
- **Audio conversion fails with soundfile** → falls back to ffmpeg
