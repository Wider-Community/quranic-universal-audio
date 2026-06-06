---
license: cc-by-4.0
task_categories:
- automatic-speech-recognition
language:
- ar
tags:
- quran
- forced-alignment
- word-timestamps
- letter-timestamps
- audio-segmentation
- asr
pretty_name: Qur'anic Universal Ayahs
size_categories:
- 10K<n<100K
{{configs}}
---

<p align="center">
  <a href="https://huggingface.co/spaces/hetchyy/quranic-universal-aligner"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Tool-Qur'anic%20Universal%20Aligner-E8C32E" alt="Tool - Qur'anic Universal Aligner"></a>
  <a href="https://hetchyy-quranic-universal-audio.hf.space/"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Website-Qur'anic%20Universal%20Audio-E8C32E" alt="Website - Qur'anic Universal Audio"></a>
  <br>
  <a href="https://github.com/Wider-Community/quranic-universal-audio"><img src="https://img.shields.io/badge/Recitations-{{recitations}}-d4842a" alt="Timestamped recitations"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio"><img src="https://img.shields.io/badge/Riwayat-{{riwayat}}-f0ad4e" alt="Timestamped riwayat"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio"><img src="https://img.shields.io/badge/Hours-{{hours}}-d4842a" alt="Timestamped audio hours"></a>
  <br>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/releases/latest"><img src="https://img.shields.io/github/v/release/Wider-Community/quranic-universal-audio?label=Release&color=4a5568" alt="Latest Release"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio"><img src="https://img.shields.io/github/stars/Wider-Community/quranic-universal-audio?style=social" alt="GitHub stars"></a>
  <a href="https://github.com/Wider-Community/quranic-universal-audio/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-CC%20BY%204.0-4a5568" alt="License"></a>
</p>

<h1 align="center">Qur'anic Universal Ayahs</h1>

Qur'anic Universal Audio (QUA) is a community-verified project for consistent Qur'an recitation audio and timing data.

This dataset pairs ayah by ayah audio with word-level timestamps, letter timestamps, and waqf-aware segment data. Repeated words are preserved in `text_uthmani` and `word_timestamps`, so the row reflects what the reciter actually recited rather than a plain copy of canonical ayah text.

## Dataset

Mushaf configs contain one row per ayah. Each row includes embedded ayah audio, recited Uthmani text, word timestamps, letter timestamps, waqf-aware segments, and source-audio mappings.

The `mushafs` subset is the dataset catalog index. It has one row per published mushaf, joined with reciter names, riwayah/style/source/channel labels, audio metadata, and coverage.

Remaining subsets are grouped by riwayah, and splits are specific mushafs.

## Mushaf Schema

| Column | Type | Notes |
|---|---|---|
| `audio` | `Audio` | Ayah MP3 clip. |
| `surah` | `int32` | Surah number, 1-114. |
| `ayah` | `int32` | Ayah number within the surah. |
| `duration_ms` | `int32` | Clip duration. |
| `text_uthmani` | `string` | Recited Uthmani text (normalized) |
| `segments` | `[[int,int,int,int]]` | Waqf/pause-aware regions: `[word_from, word_to, start_ms, end_ms]`. |
| `word_timestamps` | `[[int,int,int]]` | `[word_idx, start_ms, end_ms]`; word indices are 1-based. |
| `letter_timestamps` | struct of lists | `word_idx`, `char`, `start_ms`, `end_ms`. |
| `source_url` | `string` | Original chapter or ayah audio URL. |
| `source_offset_ms` | `int32` | Clip start inside `source_url`. |

All row timestamps are relative to the ayah clip. Use `source_offset_ms + timestamp_ms` when mapping a row back to its source audio.

## Catalog Schema

One row per published mushaf.

| Column | Type | Notes |
|---|---|---|
| `slug` | `string` | Stable mushaf identifier (the per-riwayah split name). |
| `reciter_id` | `string` | Stable reciter identifier (shared across that reciter's mushafs). |
| `name_en`, `name_ar` | `string` | Reciter display name (English / Arabic). |
| `country` | `string` | Reciter country, ISO 3166-1 alpha-2 (e.g. `SA`). |
| `riwayah` | `string` | Readable riwayah name (e.g. `Hafs`). |
| `style` | `string` | Readable recitation style (e.g. `Murattal`, `Mujawwad`). |
| `recording_context` | `string` | Readable context (e.g. `Studio`, `Masjid`). |
| `recording_year` | `int32` | Year recorded, when known. |
| `source` | `string` | Readable upstream source name. |
| `channel` | `string` | Readable distribution channel name. |
| `audio_category` | `string` | How source audio is segmented: `by_surah` \| `by_ayah`. |
| `chapter_count` | `int32` | Number of chapters in the mushaf (114 = complete). |
| `codec` | `string` | Audio codec, e.g. `mp3`. |
| `container` | `string` | File container, e.g. `mp3`. |
| `sample_rate_hz` | `int32` | Sample rate, e.g. `44100`. |
| `channels` | `int32` | `1` = mono, `2` = stereo. |
| `bitrate_mode` | `string` | `cbr` \| `vbr` \| `mixed` \| `unknown`. `mixed` = chapters differ. |
| `bitrate_kbps_nominal` | `int32` | Nominal bitrate; `null` when `bitrate_mode` is `mixed`. |
| `total_duration_sec` | `int32` | Total mushaf audio duration. |
| `added_at` | `string` | When the mushaf was added, ISO-8601 (`...Z`). |

Audio format is a per-mushaf property: every ayah clip is a byte-exact stream-copy of its chapter master, so the `codec` / `bitrate_mode` / `sample_rate_hz` / `channels` here apply to all of that mushaf's clips. Join a per-ayah row back to its mushaf by `slug` to recover format.

## Usage

```python
from datasets import load_dataset

ds = load_dataset(
    "hetchyy/quranic-universal-ayahs",
    "hafs_an_asim",
    split="khalifa_al_tunaiji_tarteel",
)

row = ds[0]
print(row["surah"], row["ayah"])
print(row["word_timestamps"])
print(row["segments"])
```

```python
catalog = load_dataset(
    "hetchyy/quranic-universal-ayahs",
    "mushafs",
    split="all",
)

print(catalog[0]["name_en"], catalog[0]["riwayah"])
```

## Notes

- Best for quick access to verse audio and timestamps together, gapped playback, and ML research.
- For app playback from full chapter audio, [GitHub releases](https://github.com/Wider-Community/quranic-universal-audio/releases/latest) might be a more suitable format.
- **Stay updated:** click **Watch** (the bell, top-right of this dataset) and enable notifications to hear when recitations are added or refreshed.
- Recitation audio is not relicensed, and remains the property of upstream sources/reciters.

## License

CC BY 4.0.
