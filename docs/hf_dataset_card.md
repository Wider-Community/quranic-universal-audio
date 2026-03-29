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
dataset_info:
  config_name: hafs_an_asim
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
  splits:
  - name: ali_jaber
    num_bytes: 0
    num_examples: 6236
  - name: minshawy_murattal
    num_bytes: 1571705367
    num_examples: 6236
  download_size: 1569809077
  dataset_size: 1571705367
---

<p align="center">
  <a href="https://github.com/Wider-Community/quranic-universal-audio/blob/main/data/RECITERS.md"><img src="https://img.shields.io/badge/Audio%20Only-252%20Full%20%C2%B7%2086%20Partial%20%C2%B7%207,853h-d4842a" alt="Audio Only"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/blob/main/data/RECITERS.md"><img src="https://img.shields.io/badge/Riwayat-14%20%2F%2020-f0ad4e" alt="Riwayat"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/blob/main/data/RECITERS.md"><img src="https://img.shields.io/badge/Timestamped-2%20Full%20%C2%B7%200%20Partial%20%C2%B7%2025h-d4842a" alt="Timestamped"></a>
  <a href="https://huggingface.co/spaces/hetchyy/Quran-multi-aligner"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Demo-Qur'anic%20Universal%20Aligner-E8C32E" alt="Demo - Qur'anic Universal Aligner"></a>
  <a href="https://huggingface.co/spaces/hetchyy/Quran-reciter-requests"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Request-Align%20a%20Reciter-E8C32E" alt="Request - Align a Reciter"></a>
  <br>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/releases/latest"><img src="https://img.shields.io/github/v/release/Wider-Community/quranic-universal-audio?label=Release&color=4a5568" alt="Latest Release"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio"><img src="https://img.shields.io/github/stars/Wider-Community/quranic-universal-audio?style=social" alt="GitHub stars"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-4a5568" alt="License"></a>
</p>

<h1 align="center">Qur'anic Universal Ayahs</h1>

<p align="center">
  Word-level aligned Qur'an recitation audio with precise timestamps derived from phoneme-level forced alignment.<br>
  A community-verified dataset of 300+ reciters across 14 riwayat.
</p>


## Dataset Description

Each row is one verse (ayah) of the Qur'an, with:
- **Audio clip** of the verse recitation, trimmed to speech boundaries
- **Word-level timestamps** in milliseconds, relative to the audio clip
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

# Play audio (in a notebook)
from IPython.display import Audio
Audio(verse["audio"]["array"], rate=verse["audio"]["sampling_rate"])
```
## Schema

| Column | Type | Description |
|--------|------|-------------|
| `audio` | `Audio` | Verse audio clip, trimmed to speech boundaries |
| `surah` | `int32` | Surah number (1-114) |
| `ayah` | `int32` | Verse number within surah |
| `text` | `string` | Arabic text of the verse from alignment |
| `segments` | `[[int, int, int, int]]` | Pause-based segments (ms, relative to clip) |
| `word_timestamps` | `[[int, int, int]]` | Word-level timestamps (ms, relative to clip) |

### Column Details

**`segments`** — Each segment is `[word_from, word_to, start_ms, end_ms]`. Represents a continuous speech region between pauses. Word indices are 1-based.

**`word_timestamps`** — Each word is `[word_index, start_ms, end_ms]`. Word-level timestamps from phoneme-level forced alignment (MFA). Word indices are 1-based.

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

## Notes

- All timestamps are in **milliseconds**, relative to the start of the audio clip
- Word indices are **1-based**
- Word timestamps are padded forward within each segment so there are no gaps between consecutive words. Gaps only occur across segment boundaries (pauses in recitation).
- Text is derived from segment alignment and preserves any repetitions in the recitation
- Audio clips are trimmed to the first/last word boundaries (silence before/after is removed)

## License

[Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0)