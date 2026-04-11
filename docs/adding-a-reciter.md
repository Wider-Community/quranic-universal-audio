# Adding a New Reciter

This guide walks you through adding a new reciter's audio manifest to the repository so it becomes available for alignment requests and appears in all tooling.

## Before You Start: Check for Duplicates

Before creating a new manifest, verify the reciter doesn't already exist under a different name or spelling. Reciters are often transliterated inconsistently across sources — the same person may appear as:

- **Spelling variations:** "Al-Hussary" vs "Alhussary" vs "El Hosary"
- **Missing or extra names:** "Abdulbasit" vs "Abdulbasit Abdulsamad" vs "Abdul Basit Abdul Samad"
- **Title/honorific differences:** "Sheikh Mishary" vs "Mishary Alafasi"
- **Transliteration style:** "Mohammad" vs "Muhammad" vs "Mohammed", "Abdul" vs "Abdel"

**How to check:**

1. **Browse [RECITERS.md](../data/RECITERS.md)** — search for parts of the reciter's name (first name, last name) rather than the full name.

2. **Search existing manifests** — look in `data/audio/by_surah/` and `data/audio/by_ayah/` across all sources:
   ```bash
   # Search by partial name in manifest metadata
   grep -rl "hussary" data/audio/
   ```

3. **Check across sources** — the same reciter may already exist in a different source (e.g., MP3Quran, EveryAyah, QUL, Surah-Quran). Within this project, each reciter's riwayah/style combination is served by exactly one source. If the reciter already exists under the same riwayah and style from another source, do not add a duplicate — instead, open an issue if the existing source has problems.

4. **Check different riwayat/styles** — the same reciter _can_ have multiple entries for different riwayah or style combinations (e.g., Abdulbasit Abdulsamad has separate entries for Hafs Murattal, Hafs Mujawwad, and Warsh). Make sure you're adding a genuinely new combination, not duplicating one that already exists.

If you find a match with a different spelling, use the existing name for consistency. If you believe the existing name is incorrect, open an issue to discuss renaming.

## Step 1: Choose the Right Path

Audio manifests live under `data/audio/` organized by granularity and source:

```
data/audio/
├── by_surah/<source>/<reciter>.json    # Full-surah recordings
└── by_ayah/<source>/<reciter>.json     # Per-verse recordings
```

```bash
mkdir data/audio/by_surah/my-source
echo "https://example.com/quran-audio" > data/audio/by_surah/my-source/SOURCE
```

No other configuration is needed — the pipeline, inspector, and `scripts/list_reciters.py` auto-discover source directories.

## Step 2: Create the Manifest

The manifest is a JSON file mapping surah numbers (or verse keys) to audio URLs, plus a `_meta` block with reciter metadata.

### Filename

Use the reciter's name in `snake_case`. For non-Hafs riwayat, append the riwayah to the filename:

- `mishary_alafasi.json` (Hafs — default, no suffix)
- `ali_alhuthaifi_qalon.json` (Qalon an Nafi')
- `omar_al_qazabri_warsh.json` (Warsh an Nafi')

### Surah-level format (`by_surah`)

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
    "country": "Kuwait"
  },
  "1": "https://server8.mp3quran.net/afs/001.mp3",
  "2": "https://server8.mp3quran.net/afs/002.mp3",
  ...
  "114": "https://server8.mp3quran.net/afs/114.mp3"
}
```

### Verse-level format (`by_ayah`)

```json
{
  "_meta": { ... },
  "1:1": "https://everyayah.com/data/Alafasy_128kbps/001001.mp3",
  "1:2": "https://everyayah.com/data/Alafasy_128kbps/001002.mp3",
  ...
  "114:6": "https://everyayah.com/data/Alafasy_128kbps/114006.mp3"
}
```

### `_meta` Fields

| Field | Required | Description |
|-------|:--------:|-------------|
| `reciter` | Yes | Reciter slug in `snake_case` (e.g., `"ahmad_alnufais"`) — must have a real value |
| `name_en` | Yes | English display name (e.g., `"Ahmad Al-Nufais"`) — must have a real value |
| `name_ar` | | Arabic name (e.g., `"أحمد النفيس"`) — use `"unknown"` if unsure |
| `riwayah` | | Riwayah slug from [`riwayat.json`](../data/riwayat.json) (e.g., `"hafs_an_asim"`) — use `"unknown"` if unsure |
| `style` | | One of: `murattal`, `mujawwad`, `muallim`, `children_repeat`, `taraweeh` — use `"unknown"` if unsure |
| `audio_category` | | `"by_surah"` or `"by_ayah"` — must match the manifest's directory |
| `source` | | Source URL (e.g., `"https://mp3quran.net/"`) — use `"unknown"` if unsure |
| `country` | | Country of origin (e.g., `"Saudi Arabia"`) — use `"unknown"` if unsure |
| `fetched` | | ISO date string (e.g., `"2026-03-28"`) — when the manifest was created or last refreshed |
| `_timing` | | Verse timing data from the source API (see below) |

**Important:** `reciter` and `name_en` must have real values — never `"unknown"` or empty strings. All other optional fields accept `"unknown"` but should never be empty strings.

Audio entries must always be plain URL strings, never objects or dicts.

### Optional: Verse Timing Data

Some sources (e.g., MP3Quran) provide verse-level timing information. If available, include it in `_meta._timing`:

```json
"_timing": {
  "source": "mp3quran_api",
  "type": "verse",
  "data": {
    "1": [[6420, 11120], [11120, 17640], ...],
    "2": [[0, 5230], [5230, 12100], ...]
  }
}
```

Each entry in `data` is keyed by surah number and contains an array of `[start_ms, end_ms]` pairs — one per verse. This timing data is not required but improves alignment accuracy when present.

## Step 3: Validate

Run the audio validator to check metadata completeness, coverage, and URL reachability:

```bash
# Basic validation (metadata + coverage)
python3 validators/validate_audio.py data/audio/by_surah/<source>/<reciter>.json

# Also probe audio files with ffprobe (slower, checks actual audio integrity)
python3 validators/validate_audio.py <path> --ffprobe

# Coverage check only, skip URL reachability (useful offline)
python3 validators/validate_audio.py <path> --no-check-sources
```

The validator checks:
- **Metadata completeness** — all `_meta` fields present and valid
- **Coverage** — all 114 surahs (or 6,236 verses for by-ayah) accounted for against `surah_info.json`
- **Duplicate keys** — no repeated surah/verse entries
- **URL reachability** — parallel HEAD requests to verify audio URLs are live (YouTube URLs use `yt-dlp --simulate` instead)

Fix any errors before submitting. Warnings (e.g., `"unknown"` metadata values, missing surahs) are acceptable but should be resolved where possible.

## Playlist / Collection Audio

For audio hosted on YouTube, archive.org, SoundCloud, Spreaker, or any other yt-dlp-supported site, use the helper script instead of creating the manifest manually. It auto-detects the source and writes to the appropriate subdirectory.

### From a playlist or collection

```bash
# YouTube playlist
python3 scripts/playlist_manifest.py "https://www.youtube.com/playlist?list=..."

# archive.org item (direct MP3 URLs — no yt-dlp needed at download time)
python3 scripts/playlist_manifest.py "https://archive.org/details/<item-id>"

# SoundCloud set
python3 scripts/playlist_manifest.py "https://soundcloud.com/<user>/sets/<playlist>"
```

The script fetches collection metadata, matches each entry's title to a surah by name (fuzzy English/Arabic matching with surah number fallback), then prompts you for reciter metadata. The source subdirectory (e.g., `youtube/`, `archive/`) is auto-detected from the URL; override with `--source <name>`.

### From individual URLs

If the recitation is spread across separate uploads rather than a single playlist, create a text file with one `<surah_number> <url>` per line (any URL supported):

```
1 https://www.youtube.com/watch?v=abc123
2 https://archive.org/download/some-item/002.mp3
3 https://soundcloud.com/user/surah-003
```

Then run:

```bash
python3 scripts/playlist_manifest.py --from-file urls.txt
```

**Requirements:** `yt-dlp` and `thefuzz` — the script will prompt to install them if missing.

After generating, validate and submit as usual (Steps 3–4).

## Step 4: Submit a PR

Create a branch, commit the manifest, and open a pull request:

```bash
git checkout -b feat/add-audio-<reciter_slug>
git add data/audio/by_surah/<source>/<reciter>.json
git commit -m "chore: add audio manifest for <Reciter Name>"
git push -u origin feat/add-audio-<reciter_slug>
gh pr create --title "Add audio manifest for <Reciter Name>" --body "Adds <source> manifest for <Reciter Name>."
```

Once merged, the reciter will automatically appear in:
- The [RECITERS.md](../data/RECITERS.md) catalog
- The [reciter request form](https://huggingface.co/spaces/hetchyy/Quran-reciter-requests) dropdown
- The inspector's Audio browser

## What's Next?

Adding the manifest makes the reciter _available_ — it doesn't produce alignment or timestamps. To get word-level segments and timestamps:

- **Request processing** — [Submit a request](https://huggingface.co/spaces/hetchyy/Quran-reciter-requests) through the form, or see the full [Requesting a Reciter](requesting-a-reciter.md) guide for details on choosing parameters and reviewing results.
