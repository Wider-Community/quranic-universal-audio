{{ release_title }}

Every release contains all reciters aligned up to date, not just new ones from the previous release. 

## What to download

| Asset | What it gives you |
|---|---|
| `manifest.json` | Release-level index: reciter zips, download URLs, checksums, sizes, coverage, and change type. |
| `catalog.json` | Release-level catalog: reciter names, riwayah, style, coverage, audio metadata, and the audio URLs paired with the timestamp data. |
| `<recitation>.zip` | One recitation's verse, word, and letter timestamp files, plus its own `catalog.json`. |
| `shard.py` | Optional helper that splits a large timestamp file into one JSON file per surah. |
| `check_updates.py` | Optional helper that checks the latest release for updates to the reciters you use; add `--sync` to re-download them. |
| `download_audio.py` | Optional helper that fetches a reciter's source audio (YouTube/Drive/CDN) re-encoded so the timestamps line up. |
| `surah_info.json` | Surah names, ayah counts, and word counts. |
| `qpc_hafs.json` | QPC Hafs word reference used by the word and letter indexes. |
| `letter_vocab_hafs_qpc.csv` | Optional letter-tier character vocabulary (`char,codepoint,name`). |
| `LICENSE` | CC-BY-4.0 license text. |

The release-level `manifest.json` and `catalog.json` index the whole release; each zip also carries its own `catalog.json` describing just that recitation.

{{ recitation_changes }}

> ⚠️ Missing verses are almost always upstream (the source omits it, audio issue, missing words, or reciter mistake). As such, we deliberately do not release their timings. This is usually discovered during alignment and review, and get manually flagged by a reviewer. The segments tab in the website should pinpoint the root cause of the issue/removal.

## How audio and timestamps pair

`catalog.json` contains the audio URLs for each recitation which can be streamed/downloaded directly, and every timestamp value is milliseconds relative to that matching source audio.

**Combined sources.** Most reciters serve one audio file per chapter, so each chapter's timestamps start at `0 ms` of its file. Some non-CDN sources (a YouTube video or Drive file holding several surahs) instead serve **one file for many chapters**. For those, `catalog.json` carries an `audio.chapter_offsets_ms` map: chapter `C`'s timestamps are relative to `chapter_offsets_ms[C]` inside `chapter_urls[C]`, i.e. `source_ms = chapter_offsets_ms.get(C, 0) + timestamp_ms`.

**Downloading source audio.** `download_audio.py` fetches a reciter's audio and re-encodes it to the same profile the alignment used (192 kbps CBR MP3, 44.1 kHz, mono by default), so the timestamps land correctly. Two layouts:

```bash
# one file per surah (001.mp3 … 114.mp3); timestamps apply directly (offset 0)
python download_audio.py catalog.json --reciter ibrahim_al_akhdar_drive

# the source files as published, plus a chapter -> file + offset map
python download_audio.py catalog.json --reciter ibrahim_al_akhdar_drive --format original
```

It uses `yt-dlp` + `ffmpeg` for YouTube/Drive sources and needs neither for direct CDN MP3s. `--bitrate`, `--sample-rate`, and `--channels` are configurable; see `--help`.

## Timestamp levels

| File | Use it when you need | Why it is separate |
|---|---|---|
| `verse_timestamps.json.gz` | verse playback or verse clips | smallest download |
| `word_timestamps.json.gz` | word highlighting | faster than loading letters when you only need words |
| `letter_timestamps.json.gz` | fine-grained alignment | full detail for research and advanced UI |

The files are split and gzipped for storage, speed, and network efficiency. Download only the level you need.

Use `shard.py` when your app prefers per-surah files locally:

```bash
python shard.py word_timestamps.json.gz --out-dir per_surah
```

By design, timestamps have no gaps between them except at pauses, making highlighting appear smooth and continuous during one breath. 

## Programmatic use

Read `manifest.json`, choose a reciter from `recitations`, download its `zip_url`, and verify the zip with `sha256`.

Use `catalog.json` when you need display names, coverage, audio metadata, or the source audio URLs that the timestamps refer to.

<details><summary>Reciter zip schemas</summary>

Each reciter zip contains `catalog.json` and three timestamp files.

```ts
type VerseKey = "surah:ayah";
type Ms = number;
type Word = [word_idx: number, start_ms: Ms, end_ms: Ms];
type Letter = [word_idx: number, char: string, start_ms: Ms, end_ms: Ms];

type VerseTimestamps = { _meta: Meta & { tier: "verse" }, [verse: VerseKey]: [Ms, Ms] };
type WordTimestamps = { _meta: Meta & { tier: "word" }, [verse: VerseKey]: [[Ms, Ms], Word[]] };
type LetterTimestamps = { _meta: Meta & { tier: "letter" }, [verse: VerseKey]: [[Ms, Ms], Word[], Letter[]] };
```

The three tiers describe the **same** verse at increasing detail: each tier embeds the one above it, and every number is milliseconds from the start of the source audio.

**Verse tier** — just the verse span (`[start_ms, end_ms]`):

```jsonc
{
  "_meta": { "schema_version": 1, "slug": "example_reciter", "tier": "verse", "verse_count": 6236 },
  // "surah:ayah": [verse_start_ms, verse_end_ms]
  "1:1": [0, 2831]
}
```

**Word tier** — the verse span, then one `[word_idx, start_ms, end_ms]` per recited word:

```jsonc
{
  "_meta": { "schema_version": 1, "slug": "example_reciter", "tier": "word", "verse_count": 6236 },
  // "surah:ayah": [ [verse_start_ms, verse_end_ms], [ [word_idx, start_ms, end_ms], ... ] ]
  "1:1": [
    [0, 2831],
    [
      [1,   70,  770],   // بِسْمِ
      [2,  770, 1280],   // ٱللَّهِ
      [3, 1280, 2050],   // ٱلرَّحْمَٰنِ
      [4, 2050, 2790]    // ٱلرَّحِيمِ
    ]
  ]
}
```

`word_idx` is 1-based within the verse. When a reciter loops back or re-recites part of a verse, `word_idx` can repeat or step backwards.

**Letter tier** — the word tier, plus a single flat list of letters, each tagged with the `word_idx` it belongs to (`[word_idx, char, start_ms, end_ms]`):

```jsonc
{
  "_meta": { "schema_version": 1, "slug": "example_reciter", "tier": "letter", "verse_count": 6236 },
  // "surah:ayah": [ [verse_start, verse_end], words[], [ [word_idx, char, start_ms, end_ms], ... ] ]
  "1:1": [
    [0, 2831],
    [ [1, 70, 770], [2, 770, 1280], [3, 1280, 2050], [4, 2050, 2790] ],
    [
      [1, "ب",  70, 300],   // word 1: بِسْمِ
      [1, "س", 300, 560],
      [1, "م", 560, 770],
      [2, "ا", 770, 900],   // word 2: ٱللَّهِ
      [2, "ل", 900, 1120],
      [2, "ل", 900, 1120],
      [2, "ه", 1120, 1280]
      // ... words 3 and 4
    ]
  ]
}
```

Letters are one flat array for the whole verse (not nested inside each word) — read each letter's `word_idx` to know which word it falls in.

Each `char` is one token from a fixed 42-token alphabet where distinct letters are kept apart — including the silent/structural ones (the superscript "dagger" alef, alef-wasla, the small waw/yeh, and each hamza shape). The full token list (`char,codepoint,name`) ships as `letter_vocab_hafs_qpc.csv` in this release.

</details>

<details><summary>Catalog and manifest schemas</summary>

`manifest.json` is release-level only — the download index. `catalog.json` exists at two grains: the release-level file indexes every recitation, and each zip carries a per-recitation copy scoped to itself.

**Release-level `manifest.json`** — the download index (one entry per reciter, with its `zip_url`):

```ts
type ReleaseManifest = {
  schema_version: 1;
  release_version: string;
  recitation_count: number;
  static_refs: Record<string, { sha256: string; bytes: number }>;
  recitations: Record<string, {
    zip: string;
    zip_url: string;        // direct download URL for this reciter's zip
    sha256: string;
    bytes: number;
    coverage_ayahs: number;
    change_kind: "added" | "refresh" | "unchanged";
  }>;
  license: "CC-BY-4.0";
};
```

```jsonc
{
  "schema_version": 1,
  "release_version": "v0.1.0",
  "recitation_count": 13,
  "recitations": {
    "example_reciter": {
      "zip": "example_reciter.zip",
      "zip_url": "https://github.com/<owner>/<repo>/releases/download/v0.1.0/example_reciter.zip",
      "sha256": "…", "bytes": 1234567,
      "coverage_ayahs": 6236,
      "change_kind": "added"
    }
  }
}
```

**Release-level `catalog.json`** — reciter metadata plus the source audio URLs the timestamps refer to:

```ts
type ReleaseCatalog = { schema_version: 1; recitations: ReciterCatalog[] };
type ReciterCatalog = {
  schema_version: 1;
  slug: string;
  name_en?: string; name_ar?: string;
  riwayah?: string; style?: string; channel?: string;
  audio_category?: "by_surah" | "by_ayah";
  audio: {
    chapter_urls: Record<string, string>;        // chapter number -> source audio URL
    chapter_offsets_ms?: Record<string, number>; // present only for combined sources:
                                                 // chapter -> ms offset within its (shared) source file
    sample_rate_hz?: number; channels?: number;
    bitrate_mode?: string; bitrate_kbps_nominal?: number;
  };
  coverage: {
    surahs: number; ayahs: number;
    missing_surahs?: string;  // surahs not covered at all, e.g. "1-84" or "4,7,9,37,39-40,45,65"
    missing_verses?: string;  // within-surah gaps, e.g. "75:18-40" or "7:116, 41:15"
  };
};
```

`coverage.missing_surahs` and `coverage.missing_verses` describe what a recitation does **not** cover in concise `surah` / `surah:ayah` notation (consecutive numbers collapse as `18-40`). A whole missing surah appears only in `missing_surahs`; a partly-covered surah's gaps appear only in `missing_verses`. Both keys are omitted when the recitation is complete.

```jsonc
{
  "schema_version": 1,
  "recitations": [
    {
      "slug": "example_reciter",
      "name_en": "Example Reciter", "name_ar": "...",
      "audio_category": "by_surah",
      "audio": { "chapter_urls": { "1": "https://cdn.example/001.mp3", "2": "https://cdn.example/002.mp3" } },
      "coverage": { "surahs": 114, "ayahs": 6236 }
    }
  ]
}
```

**Per-recitation `catalog.json` (inside each zip):** a single `ReciterCatalog` — the same object as one entry of the release-level `recitations` array.

</details>

## Staying up to date

We occasionally fix issues or batch-refresh a reciter's timestamps with an improved alignment model, so a reciter you already use can change in a later release. Three ways to keep track:

- **Custom events** - use the Email notifications feature on the website to subscribe to custom events.
- **All releases** - click **Watch -> Custom -> Releases** at the top of the GitHub repository. GitHub emails you on every release, and the notes above always list which reciters were added or refreshed.
- **Only the reciters you use** - run `check_updates.py` against the `manifest.json` you downloaded. It exits non-zero when any of your reciters changed, so a scheduled GitHub Action or CI job notifies you automatically; add `--sync` to also re-download the changed zips.

```bash
# report which of your reciters changed (exit 1 if any)
python check_updates.py manifest.json --reciters mishary_rashid_al_afasy_mp3quran

# or keep your local copy in sync automatically
python check_updates.py manifest.json --sync
```

{{ release_footer }}
