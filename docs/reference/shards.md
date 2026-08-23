# Timestamp shards

Timestamp shards store phonemizer-native readings and audio timing sidecars. They do not contain an Inspector cell projection.

## Contract

Each object at `reciters/<slug>/timestamps/<chapter>.json.gz` is a closed schema-v12 document:

```json
{
  "_meta": {
    "schema_version": 12,
    "chapter": 1,
    "audio_category": "by_surah",
    "phonemizer_version": "2.14.0",
    "native_schema_version": 2
  },
  "readings": [
    {
      "id": "r1",
      "parts": [
        {"ref": "1:3", "t": [1200, 5400], "word_ids": [0, 1]}
      ],
      "analysis": {"schema_version": 2, "result": {}},
      "source": {"schema_version": 2, "view": {}},
      "cells": {"schema_version": 2, "view": {}},
      "timing": {
        "words": [{"word_id": 0, "start_ms": 1200, "end_ms": 1800}],
        "sounds": [{"sound_id": 0, "start_ms": 1200, "end_ms": 1300}],
        "units": [{"source_unit_id": 0, "start_ms": 1200, "end_ms": 1300}],
        "boundaries": [{"boundary_id": 0, "start_ms": 1200, "end_ms": 1200}]
      }
    }
  ]
}
```

`analysis`, `source`, and `cells` are untouched documents from quranic-phonemizer native schema 2. Consumers validate both the outer shard version and all three native document versions.

There is no v11 reader. Historical v11 objects are accepted only by the one-time local cutover command, which produces a new v12 object and then runs the same v12 validator as fresh generation.

## Metadata

Required `_meta` fields are:

| Field | Meaning |
| --- | --- |
| `schema_version` | Always `12`. |
| `chapter` | Chapter addressed by the object path. |
| `audio_category` | Audio layout, normally `by_surah` or `by_ayah`. |
| `phonemizer_version` | Producer version used for the native documents. Cutover requires 2.14. |
| `native_schema_version` | Always `2`. |

Generation provenance such as `padding`, `beam`, `method`, `aligner_model`, `shared_cmvn`, `audio_source`, and `created_at` may also be retained. Presentation policy never appears here.

## Readings and parts

A reading is the maximal connected chain in the recording. A segment whose `wasl` flag connects to the next segment remains in the same reading. The entire reading is phonemized once, so cross-verse wasl is preserved rather than rederived as verse-final waqf.

`parts[]` preserves the original recording occasions:

| Field | Meaning |
| --- | --- |
| `ref` | Original verse reference. |
| `t` | Absolute audio start/end in milliseconds. |
| `word_ids` | Native word identities belonging to this part, in recited order. |

Retakes and loopbacks therefore produce multiple readings or multiple parts. They are not deduplicated in storage. Release publishing chooses an earliest complete canonical occasion through `qua_shared.timestamps_native`; the Inspector keeps all occasions.

Cross-verse readings render as separate inline verse blocks. The native bridge and the two boundary words form an unbreakable junction. Changing the focused verse changes opacity and editability only; it cannot change the reading, phonemes, geometry, or timings.

## Native documents

The three documents divide domain ownership as follows:

| Document | Owns |
| --- | --- |
| `analysis` | Words, ordered sounds, semantic boundaries, rule occurrences, mergers, selected variants, extra-phoneme policy. |
| `source` | Stable source-unit identities, source text, sound ownership/presentation, rule and merger placements. |
| `cells` | Native columns, groups, bridges, boundary marks, transformed glyph/status/tier state. |

The Inspector does not synthesize cells, split or rename rules, assign sounds by position, create bridges, or infer groups by proximity. `@quranic-phonemizer/cells` parses and renders these documents.

Display documents are generated with `emphatic_fatha`, `emphatic_ikhfaa`, `imala`, and `tashil`. MFA remains trained on the acoustic emphatic-fatha-only surface. The distinction is token substitution only: sound identity and timing order stay invariant.

The v11 restamper additionally records the three historical choices used by the stamped v11 corpus: ṣād at `2:245:14` and `7:69:22`, and heavy rāʾ at `89:4:3`. Fresh v12 generation uses the explicit phonemizer 2.14 defaults.

## Timing sidecar

Every timing row points at a native identity in the same reading.

### Words

`timing.words[]` contains `word_id`, `start_ms`, and `end_ms`. Cutover copies existing intervals byte-for-byte.

### Sounds

`timing.sounds[]` contains `sound_id`, `start_ms`, and `end_ms`. The strict builder requires the stored token sequence to equal the chosen native token surface before it transfers any interval. A mismatch blocks the reading; there is no nearest-token fallback.

### Source units

`timing.units[]` contains `source_unit_id`, `start_ms`, and `end_ms`.

Legacy written-letter intervals are recut against native letter units by exact normalized text coverage. A letter unit gets that exact interval. A mark unit gets the union of the native sounds it owns or presents. A truly untimed unit has both values `null`.

### Boundaries

`timing.boundaries[]` contains `boundary_id`, `start_ms`, and `end_ms`. These rows describe recorded audio gaps. They never modify the semantic boundary state in `analysis` or turn a join into a stop.

The initial and final boundary use the reading edge. An internal gap runs from the preceding timed word end to the following timed word start and is clamped to an empty interval if the recording overlaps.

## Renderer policy is not shard schema

The shard excludes names, localized labels, legend groups, colors, duration labels, toggles, underline stacks, and renderer options. Those are host policy.

The Inspector calls the shared parser with:

```ts
parse(payload, defineInspectorRule, {
  iqlabTanween: 'mini-meem',
  iqlabNoon: 'mini-meem',
  openTanween: true
})
```

The package owns native groups, compact mergers, sakt extraction, Digital Khatt boundary text, iqlab display synthesis, and open/closed tanween glyph selection. The Inspector owns audio timing, highlighting, seeking, looping, reports, translations, context opacity, locale, and its rule-display table.

Sakt is static and pausal in the Inspector. It has no click callback. At a verse-final sakt, the verse marker wins and the sakt glyph is not duplicated.

## Identity hooks

The shared renderer exposes stable `data-qc-*` hooks for words, columns, sounds, groups, boundaries, and bridges. Timing and report code indexes these hooks by native identity.

A group is addressed by the package's documented group key: the native group's ordered column IDs. It is never addressed by visual position. Report targets are described in [ts-reports.md](ts-reports.md).

## Generation

Fresh timestamp generation and one-time restamping converge on the SDK native builder:

```text
raw timing occurrences
  -> maximal connected readings
  -> one native phonemizer request per reading
  -> exact word/sound timing transfer
  -> exact source-unit recut
  -> native v12 chapter documents
  -> deterministic gzip (mtime=0)
```

The production entry points are:

| Purpose | Entry point |
| --- | --- |
| Native analysis and source/cell documents | `qua_sdk.integrations.native` |
| Fresh v12 builder | `qua_sdk.integrations.shards.build_native_shards` |
| Shared job wrapper | `qua_shared.timestamps_shards.build_timestamp_shards` |
| One-time v11 restamp | `scripts/migrations/restamp_timestamps_v12.py` |
| Structural/data audit | `qua_shared.timestamps_v12_audit` |
| Canonical release projection | `qua_shared.timestamps_native` |

The one-time restamper is not imported by any server or frontend reader.

## Validation and cutover gate

For every reciter and every chapter, the audit requires:

- 114 expected chapter objects;
- outer schema 12 and all native documents schema 2;
- exact word identity/order closure;
- exact stored/native token sequence on the selected reading surface;
- byte-for-byte preservation of every word and sound interval;
- unique exact recutting of every old letter row;
- every part, timing row, source unit, boundary, and native ID resolving;
- deterministic gzip output;
- the established connected cross-verse chains retaining their wasl phonemes, including `1:3→1:4`, `14:1→14:2`, and the connected chapter-79 chain;
- zero heuristic fallbacks.

A real sound-count or sound-order change blocks only that connected reading and is the sole reason to consider acoustic realignment. Token spelling alone does not authorize redistribution.

Before cutover, v12 objects are written under a staging prefix. Reports are mapped and audited against the same objects. The v12-only application, catalogue pointer, and report database move together. Live v11 objects/readers are then removed; repository and bucket history remain the recovery path.
