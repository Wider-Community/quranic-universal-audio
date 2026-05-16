# Segments Fixtures

Shared JSON fixtures consumed by both the pytest suite (`inspector/tests/`)
and the vitest suite (`inspector/frontend/src/tabs/segments/__tests__/`).

The vitest config exposes this directory under the `@fixtures` alias so
frontend tests can `import fixture from '@fixtures/112-ikhlas.detailed.json'`
and pytest reads the same files via `load_fixture(name)` in `conftest.py`.

## File layout

| File | Origin | Purpose |
|---|---|---|
| `112-ikhlas.detailed.json` | Real Minshawi slice (Surah 112) + minimal synthetic tweak | Coverage for `qalqala` (final letter), `low_confidence` (one segment dropped to 0.65) |
| `113-falaq.detailed.json` | Real Minshawi slice (Surah 113) + injected synthetic segments | Coverage for `muqattaat` (one synthetic segment with `s_word=1` matched against a real `MUQATTAAT_VERSES` entry), `audio_bleeding`, `cross_verse` |
| `synthetic-structural.detailed.json` | Hand-crafted | Coverage for `missing_verses`, `missing_words`, `structural_errors` |
| `synthetic-classifier.detailed.json` | Hand-crafted | One segment per per-segment category for parametrized tests |
| `expected/<fixture>.classify.json` | Generated | Post-Phase-2 unified classifier baseline. Regenerated via `python -m inspector.tests.parity.snapshot_expected_outputs` |

## File format

Every `*.detailed.json` follows the canonical detailed.json shape:

```json
{
  "_meta": { ... },
  "_fixture_meta": {
    "source": "real-data-slice" | "hand-crafted" | "real+synthetic",
    "redactions": ["audio URLs"],
    "segments": [
      {"index": 0, "expected_categories": ["qalqala"], "notes": "..."}
    ],
    "synthetic_injections": [...]
  },
  "entries": [
    {
      "ref": "112",
      "audio": "https://fixture.local/audio/112.mp3",
      "segments": [
        {
          "segment_uid": "...",
          "time_start": 4700,
          "time_end": 7700,
          "matched_ref": "112:1:1-112:1:4",
          "matched_text": "...",
          "phonemes_asr": "...",
          "confidence": 1.0,
          "ignored_categories": [...],
          "wrap_word_ranges": [...]
        }
      ]
    }
  ]
}
```

The `_fixture_meta` field is read only by the fixture loader and the
expected-output regenerator; the production loader (`services/data_loader.py`)
ignores any unknown top-level keys.

## Redaction rules

- Every `entry.audio` URL is rewritten to `https://fixture.local/audio/<ref>.mp3`.
- Per-segment `audio_url` (when present, e.g. by-ayah recitations) is similarly
  redacted to `https://fixture.local/audio/<ref>/<index>.mp3`.
- All Quranic text and phoneme sequences are kept verbatim — they are not
  considered sensitive.

## Regenerating expected outputs

After Phase 2 lands the unified classifier, run:

```
python -m inspector.tests.parity.snapshot_expected_outputs
```

The script walks every fixture, classifies via the backend, and writes
`expected/<fixture>.classify.json`. Idempotent. Commit the regenerated files
together with the Phase 2 changeset.
