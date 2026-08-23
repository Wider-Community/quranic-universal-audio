# Timestamp generation job

The timestamp job aligns recorded audio and writes native timestamp-shard v12. The complete stored contract is [shards.md](shards.md).

## Responsibilities

The job owns acoustic work only:

- resolve recorded segments and their connected-wasl relationships;
- obtain chapter audio;
- run MFA with the pinned acoustic model and emphatic-fatha-only token inventory;
- recover word, sound, and written-letter intervals;
- pass timing occurrences to the SDK v12 builder;
- validate and deterministically gzip each chapter;
- stage result objects and validation metadata.

It does not construct frontend cells, rename tajweed rules, synthesize bridges, add silent flags, or assign renderer ownership.

## Native build

`qua_shared.timestamps_pipeline` calls `qua_shared.timestamps_shards.build_timestamp_shards`, which delegates to `qua_sdk.integrations.shards.build_native_shards`.

For each chapter the builder:

1. Orders original occurrences by absolute audio time.
2. Joins adjacent occurrences while the preceding occurrence carries `wasl`.
3. Phonemizes each maximal connected reading once with quranic-phonemizer 2.14.
4. Builds native schema-2 analysis, source, and transformed-cell documents using `emphatic_fatha`, `emphatic_ikhfaa`, `imala`, and `tashil` for display.
5. Checks the recovered acoustic sound sequence against the acoustic native surface.
6. Transfers word and sound intervals to native IDs and recuts written-letter intervals to source-unit IDs.
7. Writes shard schema 12 with deterministic gzip headers.

Cross-verse wasl is never split or rephonemized as pausal. Known chains such as `1:3→1:4`, `14:1→14:2`, and the connected chapter-79 chain are release gates.

## Version pinning

The staged SDK marker records the timestamp-shard schema version. The generation environment pins quranic-phonemizer `2.14.*`; a mismatched package or staged SDK marker blocks the job before alignment output is published.

MFA remains acoustic emphatic-fatha-only. The additional display phonemes are same-cardinality notation choices and never enter the acoustic model or redistribute intervals.

## Inputs and outputs

The input is the reviewed timestamp source plus chapter audio. Chapter audio uses the bucket object first and the manifest URL only as a transient fallback.

The output is:

```text
reciters/<slug>/timestamps/<chapter>.json.gz
```

During migration and review, generation writes a versioned staging prefix. It does not change the active catalogue/manifest pointer. Production exposure is an atomic cutover after all chapters and reports pass their audits.

## Failure policy

The following block a connected reading or reciter:

- stored/native word identity drift;
- sound count, order, or selected-surface token drift;
- a non-unique source-letter recut;
- an unresolved native timing ID;
- an invalid native document or shard schema;
- nondeterministic gzip output;
- an unresolved or ambiguous report target.

There is no nearest-token, nearest-cell, glyph-first, or positional fallback. Only a true sound count/sequence change authorizes realignment of the affected connected reading.

## One-time v11 restamp

`scripts/migrations/restamp_timestamps_v12.py` is a local cutover tool. It reads complete historical v11 chapters, reconstructs maximal connected readings, preserves the stored display-token surface and intervals, emits only v12, and runs the normal v12 audit.

The tool is not a server compatibility reader. It requires a fresh output directory and can require an exact chapter count. The two historical seen/saad choices and heavy rāʾ at `89:4:3` are explicit restamp policy because v11 timed those readings that way; fresh v12 generation uses the phonemizer 2.14 defaults.

Example:

```powershell
$env:PYTHONPATH='C:\path\to\quranic-universal-audio;C:\path\to\qua\packages\sdk\src'
python scripts/migrations/restamp_timestamps_v12.py C:\staging\v11 C:\staging\v12 --require-chapters 114 --summary C:\staging\audit.json
```

Nothing is uploaded by this command.

## Acceptance

Before a reciter can move to the v12 prefix:

- all 114 chapters validate;
- old and native word/sound intervals are byte-identical;
- all letter rows recut uniquely;
- all connected-wasl tests pass;
- canonical release projection closes over every verse;
- every existing report maps exactly to a native target;
- two serializations of every chapter produce identical gzip bytes.

The cutover process and report migration are documented in [data-migrations.md](data-migrations.md) and [ts-reports.md](ts-reports.md).
