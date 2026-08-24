# Timestamp shards

Timestamp shards store a compact, renderer-neutral projection of native
phonemizer readings plus audio timing. Full native documents are generation
and audit inputs; they are not repeated in every reciter's runtime shards.

## Contract

Each object at `reciters/<slug>/timestamps/<chapter>.json.br` is a closed
schema-v12 JSON document compressed with deterministic Brotli quality 6:

```json
{
  "_meta": {
    "schema_version": 12,
    "chapter": 1,
    "audio_category": "by_surah",
    "phonemizer_version": "2.14.0",
    "native_schema_version": 2,
    "renderer_codec_version": 1,
    "native_profile": {
      "riwayah": "hafs",
      "script": "uthmani",
      "variant": {},
      "extra_phonemes": ["emphatic_fatha", "emphatic_ikhfaa", "imala", "tashil"]
    }
  },
  "readings": [{
    "id": "r1",
    "parts": [["1:3", 1200, 5400, 0, 2]],
    "render": {
      "v": 1,
      "m": ["1:3", "canonical-digest", "native-documents-sha256"],
      "p": [], "r": [], "w": [], "b": []
    },
    "timing": {"w": [], "s": [], "l": [], "c": []}
  }]
}
```

There is no v11 reader. Historical v11 objects are accepted only by the
one-time restamper, which emits this final v12 shape and validates it before
upload.

## Why the compact codec is native

The SDK builds the complete schema-v2 `analysis`, `source`, and `cells`
documents first. Codec 1 then removes only fields unused by the renderer or
audio surfaces and packs repeated records into fixed-position tuples. It does
not regroup cells, rename rules, infer ownership, or match glyphs.

`@quranic-phonemizer/cells` owns `decodeCompact()` and `parseCompact()`. The
decoded payload enters the same schema-v2 `parse()` path as live phonemizer
documents. The Inspector therefore has no cell adapter. Python consumers use
`qua_shared.timestamps_codec` for the same storage contract.

Before encoding, the SDK proves for the whole reading that word, sound, rule
occurrence, source-unit, and analysis-boundary IDs equal their array positions;
cell words are positional, post-word boundary IDs equal `word_id + 1`, and all
timing rows follow native ID order. Column IDs are not positional and remain
explicit. Any failed invariant blocks generation.

## Reading tuples

A reading spans the maximal connected chain in the recording. A segment whose
`wasl` flag connects to the next segment stays in the same reading, including
cross-verse wasl. The full chain is phonemized once.

Each part is:

```text
[ref, start_ms, end_ms, first_word_id, word_count]
```

The word IDs are the contiguous range beginning at `first_word_id`. Retakes
and loopbacks remain separate readings or parts. Cross-verse focus changes
opacity and editability only; it never changes phonemes or geometry.

## Renderer payload

`render` has these keys:

| Key | Meaning |
| --- | --- |
| `v` | Compact codec version, always `1`. |
| `m` | `[reading_ref, canon_digest, native_documents_sha256]`. |
| `p` | Phoneme tokens indexed by native sound ID. |
| `r` | Producer rule IDs indexed by native rule-occurrence ID. |
| `w` | Words indexed by native word ID. |
| `b` | Post-word boundaries; item `i` has native boundary ID `i + 1`. |

A word is:

```text
[ref, text, columns, sounds, groups, runs, bridges]
```

A post-word boundary is:

```text
[state_code, columns, sounds, bridges, verse_end, exclusive_group]
```

Columns use:

```text
[id, role_code, text, source_unit_ids, slot_ids, tier_code,
 attached_column_id, status_code, anchor_unit_id, side_code,
 owned_sound_ids, presented_sound_ids, rule_occurrence_ids, silence]
```

The enum tables are defined together in the SDK encoder and renderer decoder.
`silence` is an occurrence ID, `null`, `-1` for `orthographic_silence`, or `-2`
for `variant_silence`. Sounds, groups, runs, and bridges retain every native ID
and ordered span. Source-character IDs and selected-variant annotations are
omitted because no renderer or Inspector surface reads them; the resolved
variant profile remains in `_meta` for reproducibility.

## Timing payload

`timing` uses positional arrays:

| Key | Tuple | Meaning |
| --- | --- | --- |
| `w` | `[start_ms, end_ms]` | Word span indexed by word ID. |
| `s` | `[start_ms, end_ms]` | Sound span indexed by sound ID. |
| `l` | `[unit_id, word_id, text, start_ms, end_ms, silent]` | Native letter-unit timing; nullable spans are retained. |
| `c` | `[column_id, start_ms, end_ms]` | Sparse exact column-span override; a null pair suppresses a derived span. |

Non-letter source units are omitted. A column span is normally reconstructed
from its timed letter units and native cell-sound spans. During encoding the
SDK compares that result with the full source-unit calculation and stores an
entry in `c` only when they differ. This preserves highlighting exactly without
repeating every mark-unit interval.

Boundary timing is derived losslessly: the initial/final boundaries use the
reading part edges, and each internal boundary runs from the preceding word end
to the following word start, clamped to an empty interval on overlap. Boundary
timing never changes the native semantic state.

## Renderer policy is not shard schema

The shard excludes names, localized labels, legend groups, colors, duration
labels, toggles, underline stacks, and renderer options. The Inspector uses:

```ts
parseCompact(reading.render, defineInspectorRule, {
  iqlabTanween: 'mini-meem',
  iqlabNoon: 'mini-meem',
  openTanween: true
})
```

The shared package owns native groups, compact mergers, sakt extraction,
Digital Khatt boundary text, iqlab display synthesis, and tanween glyph choice.
The Inspector owns timing, highlighting, seeking, looping, reports,
translations, context opacity, locale, and rule presentation. Stable
`data-qc-*` hooks address words, columns, sounds, groups, boundaries, and
bridges; group keys are ordered native column IDs.

## Generation and serving

```text
raw timing occurrences
  -> maximal connected readings
  -> full native schema-v2 documents
  -> exact timing transfer and source-unit recut
  -> compact codec 1 + sparse timing overrides
  -> deterministic Brotli quality 6
```

The main entry points are:

| Purpose | Entry point |
| --- | --- |
| Native documents | `qua_sdk.integrations.native` |
| Compact encoder | `qua_sdk.integrations.cells_codec` |
| v12 builder | `qua_sdk.integrations.shards.build_native_shards` |
| Compression | `qua_shared.timestamps_shards.brotli_shard` |
| Structural audit | `qua_shared.timestamps_v12_audit` |
| Python decoder | `qua_shared.timestamps_codec` |
| Canonical release projection | `qua_shared.timestamps_native` |

The Flask shard route passes the stored bytes through as `application/json`
with `Content-Encoding: br`; browsers perform HTTP decompression and parse
normal JSON. Manifest and reference-resource compression remain independent.

## Validation and cutover gate

For every reciter, the audit requires 114 objects, schema 12/native schema 2/
codec 1, complete ID closure, byte-identical word and sound intervals, exact
letter recutting, complete part coverage, valid sparse overrides,
deterministic Brotli output, retained known cross-verse wasl chains, and zero
heuristic fallbacks. A sound-count or sound-order mismatch blocks that reading
and is the only reason to consider acoustic realignment.
