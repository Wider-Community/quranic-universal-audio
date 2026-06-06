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

`catalog.json` contains the audio URLs for each recitation. Timestamp values are relative to that matching source audio.

For a surah-based recitation, a value like `"100:1": [0, 2831]` means ayah 100:1 starts at `0 ms` and ends at `2831 ms` in the matching surah audio.

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

Small example:

```json
{
  "_meta": {"schema_version": 1, "slug": "example_reciter", "tier": "verse", "verse_count": 6236},
  "1:1": [0, 2831]
}
```

```json
{
  "_meta": {"schema_version": 1, "slug": "example_reciter", "tier": "word", "verse_count": 6236},
  "1:1": [[0, 2831], [[1, 70, 1550], [2, 1550, 2790]]]
}
```

```json
{
  "_meta": {"schema_version": 1, "slug": "example_reciter", "tier": "letter", "verse_count": 6236},
  "1:1": [[0, 2831], [[1, 70, 1550]], [[1, "ب", 70, 180]]]
}
```

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
