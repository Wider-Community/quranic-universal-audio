# Data Directory

Reference data and all pipeline I/O for the Quran forced alignment toolkit. See [RECITERS.md](RECITERS.md) for the full list of available sources, reciters and their metadata.

```
data/
├── surah_info.json                                       # Ground truth: 114 surahs, 6236 verses, word counts
├── qpc_hafs.json                                         # Every Quran word keyed by surah:ayah:word
├── audio/                                                # Audio URL indexes (no actual audio files)
│   ├── by_surah/<source>/<reciter>.json                  # Full-surah recordings (keyed by surah number)
│   └── by_ayah/<source>/<reciter>.json                   # Per-verse recordings (keyed by surah:ayah)
├── recitation_segments/<reciter>/                        # Alignment pipeline output
│   ├── segments.json                                     # Word-level time segments per verse
│   ├── detailed.json                                     # Full entries with ASR metadata
│   └── validation.log
├── timestamps/<by_ayah_audio|by_surah_audio>/<reciter>/  # Timestamps output
│   ├── timestamps.json                                   # Word-level timing
│   ├── timestamps_full.json                              # Word + letter + phoneme timing
│   └── validation.log
└── qul_downloads/                                        # Raw segment files from Tarteel QUL
    ├── by_ayah/
    └── by_surah/
```

---

## Audio Inputs (`audio/`)

Audio manifests map surah or verse identifiers to URLs (or local paths). No actual audio files are stored in this directory. The pipeline and validators accept **4 input formats**, auto-detected by `detect_input_format()`:

### Format 1: `sura_json` — Surah-level JSON

A single JSON file where keys are surah numbers (`"1"` to `"114"`) mapping to audio URLs.

```json
{
  "_meta": {
    "reciter": "mishary_alafasi",
    "name_en": "Mishary Alafasi",
    "name_ar": "مشاري العفاسي",
    "riwayah": "hafs_an_asim",
    "style": "murattal",
    "audio_category": "by_surah",
    "source": "https://mp3quran.net/",
    "country": "unknown"
  },
  "1": "https://server8.mp3quran.net/afs/001.mp3",
  "2": "https://server8.mp3quran.net/afs/002.mp3",
  ...
  "114": "https://server8.mp3quran.net/afs/114.mp3"
}
```

- **Location:** `audio/by_surah/<source>/<reciter>.json`
- **Sources:** `mp3quran`, `qul`, `surah-quran`, `youtube`
- **Expected coverage:** 114 surahs
- **Note:** YouTube URLs are supported — the pipeline downloads audio via `yt-dlp` at extraction time

### Format 2: `verse_json` — Verse-level JSON

A single JSON file where keys are `"surah:ayah"` pairs mapping to audio URLs.

```json
{
  "_meta": {
    "reciter": "mohammed_siddiq_al_minshawi",
    "name_en": "Mohammed Siddiq Al-Minshawi",
    "name_ar": "محمد صديق المنشاوي",
    "riwayah": "hafs_an_asim",
    "style": "murattal",
    "audio_category": "by_ayah",
    "source": "https://everyayah.com/",
    "country": "unknown"
  },
  "1:1": "https://everyayah.com/data/Minshawy_Murattal_128kbps/001001.mp3",
  "1:2": "https://everyayah.com/data/Minshawy_Murattal_128kbps/001002.mp3",
  ...
  "114:6": "https://everyayah.com/data/Minshawy_Murattal_128kbps/114006.mp3"
}
```

- **Location:** `audio/by_ayah/<source>/<reciter>.json`
- **Expected coverage:** 6,236 verses

### Format 3: `sura_dir` — Surah-level Directory

A directory of audio files named by surah number.

```
my_reciter/
├── 1.mp3
├── 2.mp3
├── ...
└── 114.mp3
```

- **Supported extensions:** `.mp3`, `.wav`, `.flac`, `.m4a`, `.ogg`

### Format 4: `verse_dir` — Verse-level Directory

A directory of audio files named `<surah>_<verse>`.

```
my_reciter/
├── 1_1.mp3
├── 1_2.mp3
├── ...
└── 114_6.mp3
```

- **Supported extensions:** `.mp3`, `.wav`, `.flac`, `.m4a`, `.ogg`

### `_meta` Fields (JSON formats)

All JSON audio manifests must include a `_meta` object. Fields marked **required** must have a real value; other fields must be present but may be `"unknown"` if not known. Empty strings are never allowed — use `"unknown"` instead.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `reciter` | string | **yes** | Reciter name in snake_case (e.g., `"ahmad_alnufais"`) |
| `name_en` | string | **yes** | English display name (e.g., `"Ahmad Al-Nufais"`) |
| `name_ar` | string | | Arabic display name (e.g., `"أحمد النفيس"`) |
| `riwayah` | string | | Quranic reading tradition (e.g., `"hafs_an_asim"`) |
| `style` | string | | Recitation style: `murattal`, `mujawwad`, `muallim`, `hadr`, or `unknown` |
| `audio_category` | string | | `"by_surah"` or `"by_ayah"` |
| `source` | string | | Source URL or description |
| `country` | string | | Country of origin |
| `fetched` | string | | ISO date when manifest was created/refreshed (e.g., `"2026-03-28"`) |

### Adding a New Reciter

See the [Adding a New Reciter](../docs/adding-a-reciter.md) guide for the full walkthrough — including duplicate checking, manifest creation, validation, and PR submission.

---

## Alignment Output (`recitation_segments/`)

Speech segments split by pauses/silences. One subdirectory per reciter containing `segments.json` and `detailed.json`.

### `segments.json`

Flat dictionary keyed by verse reference. Each verse maps to an array of word-level segments.

```json
{
  "_meta": {
    "created_at": "2025-03-15T14:32:45Z",
    "asr_model": "hetchyy/r7",
    "vad_model": "obadx/recitation-segmenter-v2",
    "min_silence_ms": 1000,
    "min_speech_ms": 1000,
    "pad_ms": 500,
    "audio_source": "by_ayah/everyayah"
  },
  "1:1": [[1, 4, 4000, 11900]],
  "1:2": [[1, 4, 3900, 11240]],
  "1:2:1-1:3:2": [[1, 2, 3440, 16940]],
  ...
}
```

**Segment array format:** `[start_word, end_word, time_from_ms, time_to_ms]`

| Index | Field | Description |
|-------|-------|-------------|
| 0 | `start_word` | First word number in the matched range (1-indexed) |
| 1 | `end_word` | Last word number in the matched range |
| 2 | `time_from_ms` | Segment start time in milliseconds |
| 3 | `time_to_ms` | Segment end time in milliseconds |

**Verse keys:**
- **Regular:** `"surah:ayah"` (e.g., `"1:1"`, `"2:255"`)
- **Cross-verse:** `"surah:ayah:word-surah:ayah:word"` (e.g., `"1:2:1-1:3:2"`) — used when a continuous speech region spans multiple verses

### `detailed.json`

Object with metadata and an entries array. Each entry represents one audio file with its aligned segments.

```json
{
  "_meta": { ... },
  "entries": [
    {
      "ref": "1:1",
      "audio": "https://everyayah.com/data/Minshawy_Mujawwad_192kbps/001001.mp3",
      "segments": [
        {
          "time_start": 4000,
          "time_end": 11900,
          "matched_ref": "1:1:1-1:1:4",
          "matched_text": "بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ",
          "phonemes_asr": "b i s m i ll a: h i rˤrˤ aˤ ħ m a: n i rˤrˤ aˤ ħ i: m",
          "confidence": 1.0
        }
      ]
    },
    ...
  ]
}
```

The `_meta` block is identical to `segments.json`.

**Entry fields:**

| Field | Type | Description |
|-------|------|-------------|
| `ref` | string | Input reference identifier (e.g., `"1:1"` for by-ayah, surah number for by-surah) |
| `audio` | string | Full URL or path to the source audio file |
| `segments` | array | Aligned segments found in this audio |

**Segment object fields:**

| Field | Type | Description |
|-------|------|-------------|
| `time_start` | int | Start time in milliseconds |
| `time_end` | int | End time in milliseconds |
| `matched_ref` | string | Matched word range as `"surah:ayah:word_from-surah:ayah:word_to"` |
| `matched_text` | string | Arabic text of the matched words |
| `phonemes_asr` | string | Space-separated phonemes as recognized by the ASR model |
| `confidence` | float | Alignment confidence score (0.0–1.0) |

---

##  Timestamps (`timestamps/`)

Word-level timestamps (and letter/phoneme timestamps). Organized by audio source type (`by_ayah_audio/` or `by_surah_audio/`), then by reciter.

### `timestamps.json`

Word-level timing for each verse.

```json
{
  "_meta": {
    "created_at": "2025-03-25T14:30:45Z",
    "audio_source": "by_ayah/everyayah",
    "aligner_model": "quran_aligner_model",
    "method": "kalpy",
    "beam": 15,
    "retry_beam": 50,
    "shared_cmvn": false,
    "padding": "forward",
    "mfa_failures": [...]
  },
  "1:1": [[1, 560, 960], [2, 960, 1640], [3, 1640, 2760], [4, 2760, 4410]],
  ...
}
```

**Word array format:** `[word_idx, start_ms, end_ms]`

| Index | Field | Description |
|-------|-------|-------------|
| 0 | `word_idx` | Word number within the verse (1-indexed) |
| 1 | `start_ms` | Word start time in milliseconds |
| 2 | `end_ms` | Word end time in milliseconds |

### `timestamps_full.json`

Word, letter, and phoneme-level timing for each verse, plus verse boundaries.

```json
{
  "_meta": { ... },
  "1:1": {
    "verse_start_ms": 560,
    "verse_end_ms": 4410,
    "words": [
      [1, 560, 960,
        [["ب", 560, 620], ["س", 620, 860], ["م", 860, 960]],
        [["b", 560, 590], ["i", 590, 620], ["s", 620, 860], ["m", 860, 870], ["i", 870, 960]]
      ],
      [2, 960, 1640,
        [["ٱ", 960, 960], ["ل", 960, 1100], ["ل", 1100, 1250], ["ه", 1250, 1640]],
        [["l", 960, 1100], ["l", 1100, 1250], ["a", 1250, 1370], ["h", 1370, 1490], ["i", 1490, 1640]]
      ],
      ...
    ]
  },
  ...
}
```

**Word array format:** `[word_idx, start_ms, end_ms, letters, phones]`

| Index | Field | Description |
|-------|-------|-------------|
| 0 | `word_idx` | Word number within the verse (1-indexed) |
| 1 | `start_ms` | Word start time in milliseconds |
| 2 | `end_ms` | Word end time in milliseconds |
| 3 | `letters` | Array of `[character, start_ms, end_ms]` for each letter |
| 4 | `phones` | Array of `[phoneme, start_ms, end_ms]` for each phoneme |

**Verse-level fields:**

| Field | Type | Description |
|-------|------|-------------|
| `verse_start_ms` | int | Start time of the first word |
| `verse_end_ms` | int | End time of the last word |

---

## Key Conventions

- **All timestamps are in milliseconds** in output files.
- **Verse keys** use `surah:ayah` format (e.g., `"1:1"`, `"114:6"`).
- **Cross-verse segments** use compound keys: `"surah:ayah:word-surah:ayah:word"` (e.g., `"1:2:1-1:3:2"`).
- **Word indices are 1-indexed** throughout all output files.
