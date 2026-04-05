---
license: apache-2.0
task_categories:
- automatic-speech-recognition
language:
- ar
tags:
- quran
- recitation
- forced-alignment
- word-timestamps
- letter-timestamps
- audio-segmentation
- speech-recognition
- asr
- vad
- phoneme
version: v0.1.3
pretty_name: Qur'anic Universal Ayahs
size_categories:
- 1K<n<10K
configs:
- config_name: hafs_an_asim
  data_files:
  - split: ali_jaber
    path: hafs_an_asim/ali_jaber-*
  - split: minshawy_murattal
    path: hafs_an_asim/minshawy_murattal-*
- config_name: reciters
  data_files:
  - split: all
    path: reciters/all-*
dataset_info:
- config_name: hafs_an_asim
  features:
  - name: audio
    dtype: audio
  - name: surah
    dtype: int32
  - name: ayah
    dtype: int32
  - name: text
    dtype: string
  - name: segments
    sequence:
      sequence: int32
  - name: word_timestamps
    sequence:
      sequence: int32
  - name: letter_timestamps
    sequence:
    - name: word_idx
      dtype: int32
    - name: letters
      sequence:
      - name: char
        dtype: string
      - name: start_ms
        dtype: int32
      - name: end_ms
        dtype: int32
  - name: source_url
    dtype: string
  - name: source_offset_ms
    dtype: int32
  splits:
  - name: ali_jaber
    num_bytes: 0
    num_examples: 6236
  - name: minshawy_murattal
    num_bytes: 1571705367
    num_examples: 6236
  download_size: 1569809077
  dataset_size: 1571705367
- config_name: reciters
  features:
  - name: reciter
    dtype: string
  - name: name_en
    dtype: string
  - name: name_ar
    dtype: string
  - name: riwayah
    dtype: string
  - name: style
    dtype: string
  - name: country
    dtype: string
  - name: source
    dtype: string
  - name: audio_category
    dtype: string
  - name: url_template
    dtype: string
  - name: coverage_surahs
    dtype: int32
  - name: coverage_ayahs
    dtype: int32
  - name: is_timestamped
    dtype: bool
  splits:
  - name: all
    num_bytes: 0
    num_examples: 338
---

<p align="center">
  <a href="https://huggingface.co/spaces/hetchyy/quranic-universal-aligner"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Demo-Qur'anic%20Universal%20Aligner-E8C32E" alt="Demo - Qur'anic Universal Aligner"></a>
  <a href="https://huggingface.co/spaces/hetchyy/Quran-reciter-requests"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Request-Align%20a%20Reciter-E8C32E" alt="Request - Align a Reciter"></a>
  <br>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/blob/main/data/RECITERS.md"><img src="https://img.shields.io/badge/Audio%20Only-252%20Full%20%C2%B7%2086%20Partial%20%C2%B7%207,853h-d4842a" alt="Audio Only"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/blob/main/data/RECITERS.md"><img src="https://img.shields.io/badge/Riwayat-14%20%2F%2020-f0ad4e" alt="Riwayat"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/blob/main/data/RECITERS.md"><img src="https://img.shields.io/badge/Timestamped-2%20Full%20%C2%B7%200%20Partial%20%C2%B7%2025h-d4842a" alt="Timestamped"></a>
  <br>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/releases/latest"><img src="https://img.shields.io/github/v/release/Wider-Community/quranic-universal-audio?label=Release&color=4a5568" alt="Latest Release"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio"><img src="https://img.shields.io/github/stars/Wider-Community/quranic-universal-audio?style=social" alt="GitHub stars"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-4a5568" alt="License"></a>
</p>

<h1 align="center">Qur'anic Universal Ayahs</h1>

<p align="center">
  Word-level and letter-level aligned Qur'an recitation audio with precise timestamps derived from phoneme-level forced alignment.<br>
  A community-verified dataset of 300+ reciters across 14 riwayat.
</p>


## Dataset Description

Each row is one verse (ayah) of the Qur'an, with:
- **Audio clip** of the verse recitation, trimmed to speech boundaries
- **Word-level timestamps** in milliseconds, relative to the audio clip
- **Letter-level timestamps** (when available) for individual Arabic characters, derived from phoneme-level alignment
- **Pause-based segments** showing how the recitation was naturally divided by silences
- **Arabic text** from alignment matching (reflects what was actually recited, including any repetitions)

## Usage

```python
from datasets import load_dataset

# Load a specific reciter (subset = riwayah, split = reciter)
ds = load_dataset("hetchyy/quranic-universal-ayahs", "hafs_an_asim", split="minshawy_murattal")

# Access a verse
verse = ds[0]
print(verse["surah"], verse["ayah"])  # 1 1
print(verse["text"])                   # Arabic text
print(verse["word_timestamps"])         # [[1, 0, 400], [2, 400, 800], ...]

# Letter-level timestamps (if available)
lt = verse["letter_timestamps"]
if lt:
    for entry in lt:
        word_idx = entry["word_idx"]
        for letter in entry["letters"]:
            print(f"  Word {word_idx}: {letter['char']} [{letter['start_ms']}-{letter['end_ms']}]ms")

# Play audio (in a notebook)
from IPython.display import Audio
Audio(verse["audio"]["array"], rate=verse["audio"]["sampling_rate"])
```
## Schema

| Column | Type | Description |
|--------|------|-------------|
| `audio` | `Audio` | Verse audio (MP3), trimmed to speech boundaries |
| `surah` | `int32` | Surah number (1-114) |
| `ayah` | `int32` | Verse number within surah |
| `text` | `string` | Arabic text of the verse from alignment |
| `segments` | `[[int, int, int, int]]` | Pause-based segments (ms, relative to clip) |
| `word_timestamps` | `[[int, int, int]]` | Word-level timestamps (ms, relative to clip) |
| `letter_timestamps` | `[{word_idx, [{char, start_ms, end_ms}]}]` | Letter-level timestamps per word (ms, relative to clip). Empty if not available. |
| `source_url` | `string` | Original audio file URL (chapter or verse) |
| `source_offset_ms` | `int32` | Offset in source audio where this verse starts (ms) |

### Column Details

**`segments`** — Each segment is `[word_from, word_to, start_ms, end_ms]`. A continuous speech region between pauses.

Segments capture the natural pausing points in a recitation. A gap between consecutive segments is a pause. The word ranges tell you whether the reciter continued from where they left off or went back and repeated:

- **Sequential** word ranges (next `word_from` = previous `word_to` + 1) — the reciter paused and continued.
- **Overlapping** word ranges (next `word_from` ≤ previous `word_to`) — the reciter paused and **repeated** those words before continuing. The `text` field includes the repeated words.

**`word_timestamps`** — Each entry is `[word_index, start_ms, end_ms]`. When a verse contains repeated segments, the same word index appears multiple times.

**`letter_timestamps`** — Per-word letter (character) timestamps from phoneme-level forced alignment. Each entry has `word_idx` (matching the word_timestamps word index) and `letters` — a list of `{char, start_ms, end_ms}` for each Arabic character. Empty for reciters without letter-level alignment data.

**`source_url`** — URL of the original audio file. For by-surah reciters, all verses in a surah share one URL; for by-ayah reciters, each verse has its own.

**`source_offset_ms`** — Millisecond offset in `source_url` where this verse begins. Convert clip-relative timestamps to source-relative: `source_ms = clip_ms + source_offset_ms`.

### Example: Segments & Repetitions

Verse **21:73**

| # | Words | Time (ms) | Text |
|---|-------|-----------|------|
| 1 | 1–8 | 0–15,030 | وَجَعَلْنَـٰهُمْ أَئِمَّةً يَهْدُونَ بِأَمْرِنَا **وَأَوْحَيْنَآ إِلَيْهِمْ فِعْلَ ٱلْخَيْرَٰتِ** |
| | | *pause (repeat back)* | |
| 2 | 5–12 | 16,310–30,125 | **وَأَوْحَيْنَآ إِلَيْهِمْ فِعْلَ ٱلْخَيْرَٰتِ** وَإِقَامَ ٱلصَّلَوٰةِ وَإِيتَآءَ ٱلزَّكَوٰةِ |
| | | *pause (continue)* | |
| 3 | 13–15 | 30,345–34,725 | وَكَانُوا۟ لَنَا عَـٰبِدِينَ |

The `text` field contains 19 words (the 4 repeated words appear twice), and `word_timestamps` has entries for words 5–8 twice.

### Gapless Playback

For by-surah reciters, combine `source_url` + `source_offset_ms` to seek within the original chapter audio:

```python
fatiha = ds.filter(lambda x: x["surah"] == 1)
chapter_url = fatiha[0]["source_url"]  # all verses share the same chapter URL
for verse in fatiha:
    offset = verse["source_offset_ms"]
    for word_idx, start, end in verse["word_timestamps"]:
        source_start = start + offset  # seek position in chapter audio
```

## Notes

- All timestamps are in **milliseconds**, relative to the start of the audio clip
- Word indices are **1-based**
- Word timestamps are padded forward within each segment so there are no gaps between consecutive words. Gaps only occur across segment boundaries (pauses in recitation).
- Audio clips are trimmed to the first/last canonical word boundaries. Segments and text are filtered to match the clip range — repetitions and cross-verse content outside the clip are not included in the dataset row (they remain in the raw pipeline files).
- For **gapless chapter playback**, use `source_url` directly (don't concatenate clips). Compute source-relative timestamps with `source_ms = clip_ms + source_offset_ms`. Content not covered by timestamps (basmalas, repetitions, cross-verse transitions) plays naturally in the original audio without word highlighting.

## Reciters Catalog

The `reciters` config is a lightweight index of all available reciters. Use it to discover reciters, filter by riwayah/style, and construct audio URLs:

```python
from datasets import load_dataset

reciters = load_dataset("hetchyy/quranic-universal-ayahs", "reciters", split="all")

# All Hafs murattal reciters with full coverage
hafs = reciters.filter(lambda r: r["riwayah"] == "hafs_an_asim" and r["coverage_surahs"] == 114)

# Construct a direct audio URL (add https:// prefix to url_template)
r = hafs[0]
url = "https://" + r["url_template"].format(surah=2)  # Al-Baqarah chapter audio
```

| Column | Type | Description |
|--------|------|-------------|
| `reciter` | `string` | Reciter slug |
| `name_en` | `string` | English display name |
| `name_ar` | `string` | Arabic name |
| `riwayah` | `string` | Riwayah slug (e.g. `hafs_an_asim`) |
| `style` | `string` | Recitation style (`murattal`, `mujawwad`, `muallim`) |
| `country` | `string` | Country of origin |
| `source` | `string` | Audio source (e.g. `mp3quran`, `everyayah`) |
| `audio_category` | `string` | `by_surah` or `by_ayah` |
| `url_template` | `string` | URL pattern (without `https://`). Use `.format(surah=N)` or `.format(surah=N, ayah=M)` |
| `coverage_surahs` | `int32` | Number of surahs with audio (max 114) |
| `coverage_ayahs` | `int32` | Number of ayahs with audio (max 6,236) |
| `is_timestamped` | `bool` | Whether word-level timestamps are available in the dataset |

## Configs

Subset (config) is the riwayah, split is the reciter.

### `hafs_an_asim`

| Reciter | Style | Verses | Audio Source |
|---------|-------|--------|-------------|
| [Ali Jaber](#ali_jaber) | murattal | 6,235 | everyayah.com |
| [Minshawy Murattal](#minshawy_murattal) | unknown | 6,235 | everyayah.com |


## Pipeline

Audio is processed through a multi-stage pipeline:
1. **VAD segmentation** — Detect speech regions using a recitation-specific VAD model
2. **Phoneme-level ASR** — CTC-based recognition with wav2vec2
3. **Dynamic programming alignment** — Match recognized phonemes against known Qur'anic reference text
4. **MFA forced alignment** — Montreal Forced Aligner produces phoneme-level timestamps, from which word boundaries are derived

## License

[Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0)