{{ release_title }}

## What to download

| Asset | What it gives you |
|---|---|
| `manifest.json` | Release index: reciter zips, download URLs, checksums, sizes, coverage, and change type. |
| `catalog.json` | Reciter names, riwayah, style, coverage, audio metadata, and the audio URLs paired with the timestamp data. |
| `<reciter>.zip` | One recitation's verse, word, and letter timestamp files. |
| `shard.py` | Optional helper that splits a large timestamp file into one JSON file per surah. |
| `check_updates.py` | Optional helper that checks the latest release for updates to the reciters you use; add `--sync` to re-download them. |
| `surah_info.json` | Surah names, ayah counts, and word counts. |
| `qpc_hafs.json` | QPC Hafs word reference used by the word and letter indexes. |
| `LICENSE` | CC-BY-4.0 license text. |

## How audio and timestamps pair

`catalog.json` contains the audio URLs for each recitation, and every timestamp value is milliseconds relative to that matching source audio.

For a surah-based recitation, the verse-tier entry `"1:1": [0, 2831]` means ayah 1:1 starts at `0 ms` and ends at `2831 ms` within surah 1's audio file. (For an ayah-based recitation each ayah has its own audio file, so the same `[0, 2831]` is measured from the start of that ayah's file.)

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

{{ recitation_changes }}

## Programmatic use

Read `manifest.json`, choose a reciter from `recitations`, download its `zip_url`, and verify the zip with `sha256`.

Use `catalog.json` when you need display names, coverage, audio metadata, or the source audio URLs that the timestamps refer to.

## Staying up to date

We occasionally fix issues or batch-refresh a reciter's timestamps with an improved alignment model, so a reciter you already use can change in a later release. Two ways to keep track:

- **All releases** - click **Watch -> Custom -> Releases** at the top of the GitHub repository. GitHub emails you on every release, and the notes above always list which reciters were added or refreshed.
- **Only the reciters you use** - run `check_updates.py` against the `manifest.json` you downloaded. It exits non-zero when any of your reciters changed, so a scheduled GitHub Action or CI job notifies you automatically; add `--sync` to also re-download the changed zips.

```bash
# report which of your reciters changed (exit 1 if any)
python check_updates.py manifest.json --reciters mishary_rashid_al_afasy_mp3quran

# or keep your local copy in sync automatically
python check_updates.py manifest.json --sync
```

<details><summary>Reciter zip schemas</summary>

Each reciter zip contains `manifest.json`, `catalog.json`, and three timestamp files.

```ts
type VerseKey = "surah:ayah";
type Ms = number;
type Word = [word_idx: number, start_ms: Ms, end_ms: Ms];
type Letter = [word_idx: number, char: string, start_ms: Ms, end_ms: Ms];

type VerseTimestamps = { _meta: Meta & { tier: "verse" }, [verse: VerseKey]: [Ms, Ms] };
type WordTimestamps = { _meta: Meta & { tier: "word" }, [verse: VerseKey]: [[Ms, Ms], Word[]] };
type LetterTimestamps = { _meta: Meta & { tier: "letter" }, [verse: VerseKey]: [[Ms, Ms], Word[], Letter[]] };
```

A worked example — Surah al-Fātiḥah ayah 1:1 (`بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ`, 4 words). The three
tiers describe the **same** verse at increasing detail: each tier embeds the one above it, and every
number is milliseconds from the start of the source audio. The `//` notes below are for explanation
only — the shipped files are plain JSON with no comments.

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

`word_idx` is 1-based within the verse. When a reciter loops back or re-recites part of a verse,
`word_idx` can repeat or step backwards here — that is faithful to the audio, not an error.

**Letter tier** — the word tier, plus a single flat list of letters, each tagged with the `word_idx`
it belongs to (`[word_idx, char, start_ms, end_ms]`):

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
      [2, "ه", 1120, 1280]
      // ... words 3 and 4 continue the same flat list
    ]
  ]
}
```

Letters are one flat array for the whole verse (not nested inside each word) — read each letter's
`word_idx` to know which word it falls in. `char` values are base letters without diacritics.

</details>

<details><summary>Catalog and manifest schemas</summary>

```ts
type ReleaseManifest = {
  schema_version: 1;
  release_version: string;
  recitation_count: number;
  static_refs: Record<string, { sha256: string; bytes: number }>;
  recitations: Record<string, {
    zip: string;
    zip_url: string;
    sha256: string;
    bytes: number;
    coverage_ayahs: number;
    change_kind: "added" | "refresh" | "unchanged";
  }>;
  license: "CC-BY-4.0";
};
```

```json
{
  "release_version": "v0.1.0",
  "recitation_count": 9,
  "recitations": {
    "example_reciter": {"zip": "example_reciter.zip", "coverage_ayahs": 6236, "change_kind": "added"}
  }
}
```

`catalog.json` is `{ "schema_version": 1, "recitations": [ReciterCatalog, ...] }`.

</details>

{{ release_footer }}
