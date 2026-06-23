# Schemas

The shared Pydantic v2 layer at `qua_shared/schemas/` — one source of truth for every JSON shape that crosses a boundary: bucket-resident artefacts, HTTP wire bodies, and SQLite-backed config blobs. Imported at runtime by the Inspector app AND by HF jobs, and the origin of the codegen'd FE types. When a shape and the code that produces it disagree, the producer wins — fix the model.

Deep rationale (writer/reader drift root cause): [`data-migrations.md`](data-migrations.md) §5. Layering context: [`architecture.md`](architecture.md).

## Folder convention — where a shape lives decides its folder

`qua_shared/schemas/` is three subpackages keyed on *where the shape physically lives*, plus a thin root.

| Folder | Holds | `extra=` policy | Examples |
|---|---|---|---|
| `bucket/` | External JSON artefacts resident in `reciters/<slug>/` + `catalog/` | Pure `extra="forbid"` — an unknown field raises `ValidationError`. A few intake/provenance artefacts carry `extra="allow"` for forward-compat (`playlist_map`, `ts_validation`, and `ts_shard`'s `_meta`) — these ship a forward-compat round-trip fixture. | `segment`, `edit_history`, `peaks_history`, `catalog`, `pipeline_meta`, `ts_validation`, `ts_job_record`, `playlist_map`, `ts_shard`, `segments_doc` |
| `wire/` | HTTP request + response bodies | `extra="forbid"` is the target for shapes we control the producer of (the seg/ts/public/audio models authored in this refactor). `extra="ignore"` for slim FE projections over a fuller wire body. | `seg`, `timestamps`, `public`, `audio`, `_envelopes` (`ErrorEnvelope`/`OkAck`), `admin_*`, `intake_requests`, `mark_ready`, `release` |
| `config/` | SQLite-backed state/config blobs (Inspector is the sole writer) | `extra="forbid"`. One `extra="ignore"` (`activity_state`, tolerates a retired key) and one `extra="allow"` (`automation`, forward-compat for a newer-FE key). | `state`, `access`, `audit`, `capabilities`, `automation`, `activity_state`, `pending_requests` |

Root keeps: `__init__.py` (the full barrel — re-exports every model from the three folders; import from `qua_shared.schemas` directly, never the subpath), `fe_types.py` (the slim codegen surface), `_extras.py` (`strip_and_warn`), `smoke.py`.

### The `extra=` policy, direction-aware

The principle is "forbid by default; tolerate only with a reason":

- **`bucket/` artefacts** → pure `extra="forbid"`. An unexpected or legacy field raises `ValidationError` rather than being silently absorbed — the prod-data migration cleaned every on-disk artefact, so there is nothing left to tolerate. The forward-compat exceptions still carry `extra="allow"` (the open provenance metas `TsShardMeta`, `TsValidation*`, `PlaylistMap*`); each ships a round-trip fixture proving an unknown field rides through unchanged.
- **`wire/` + `config/`** → `extra="forbid"`; the producer is internal and emits a closed key set. `extra="allow"` is permitted **only** alongside a forward-compat round-trip fixture that proves an unknown field rides through unchanged (e.g. the open provenance metas `TsShardMeta`, `SegValProbeMeta`, `TsValidation*`). `extra="ignore"` is for a model that is a *slim projection* of a fuller wire body it does not own (the `TsCatalog*` models read a subset of the full `ReciterCatalog` dump).

Implementation note: the wire models written/rewritten in this refactor (`seg`, `timestamps`, `public`, `audio`, `_envelopes`) follow `forbid`. The pre-existing admin/release/intake/mark_ready wire models carry `extra="allow"` (their own docstrings cite forward-compat for read-only FE-facing rows). The refactor tightens *producer-controlled response shapes* to `forbid`; prefer `forbid` for new wire models unless a documented forward-compat need (with a round-trip fixture) genuinely applies.

## Codegen pipeline — Pydantic → TypeScript

FE types are generated, never hand-edited. One narrow surface drives the whole pipeline:

```
qua_shared/schemas/fe_types.py     (slim re-export of just the FE-consumed models)
        │  scripts/codegen/regen_fe_types.py
        │    → pydantic2ts.generate_typescript_defs(module="qua_shared.schemas.fe_types")
        │    → Pydantic .model_json_schema() → json2ts (json-schema-to-typescript, pinned 15.0.4)
        ▼
inspector/frontend/src/lib/types/generated/schemas.ts   (committed; banner-stamped)
        │  CI job schema-codegen-check
        ▼
git diff --exit-code  (fails the build if the committed file is stale)
```

- `fe_types.py` exists to give `pydantic-to-typescript` a narrow entry point that avoids the catalog/state/audit nested forward-ref graph the codegen can't resolve in one pass. **A new FE-referenced model must be added to `fe_types.py` BEFORE running regen** — the codegen only walks what `fe_types.py` re-exports.
- After ANY edit under `qua_shared/schemas/`, run `python scripts/codegen/regen_fe_types.py` and commit `schemas.ts`. CI runs the identical command and `git diff --exit-code`s the result.
- `regen_fe_types.py` resolves `json2ts` from the FE's local `node_modules/.bin` first (pinned version), falls back to `$PATH`, and prepends an `// AUTOGENERATED … DO NOT EDIT` banner. (Note: `lint-staged` excludes `generated/` so `eslint --fix` can't strip that banner and break the check.)

The seg/ts/public/audio wire shapes are modelled in `wire/` and codegen'd; the FE consumes them straight from `generated/schemas.ts`. The genuinely FE-only shapes (view-models, peaks transport, ts-client projections, public-bucket display vocabulary) live in `lib/types/{view-models,peaks-transport,ts-client,public-bucket}.ts`.

## Wire-model route contract

Routes for the segments/timestamps/public/audio tabs serialize THROUGH the wire models — they no longer hand-build dict literals:

- **Inbound:** `Model.model_validate(request_body)` parses + validates the request (e.g. `SegSaveRequest.model_validate(...)`, `SegUndoBatchRequest.model_validate(...)` in `routes/segments/edit.py`).
- **Outbound:** `response_model.model_validate(service_result).model_dump(...)` re-serializes the service output through the response model before `jsonify`. Dump flags match the on-wire shape: `exclude_none=True` to drop unset optionals, `by_alias=True` when a field has a JSON alias (`_meta`), `mode="json"` for JSON-native scalars, `exclude_unset=True` where the producer's set-vs-unset distinction is load-bearing (the public list path in `routes/public/public.py::_wire`).
- **Envelopes:** errors return `ErrorEnvelope(error=…, detail=…, code=…).model_dump(exclude_none=True)` (`wire/_envelopes.py`), trivial mutations return `OkAck` (`{"ok": true}`). Never an inline `{"error": …}` dict.
- **Hot-path exception (`routes/segments/data.py::seg_all`):** a full-mushaf reciter is tens of thousands of segments, and the response is uncached, so a per-request `SegAllResponse.model_validate(...).model_dump(...)` round-trip adds ~60 ms (typical) to ~350 ms (max) for *byte-identical* output. That route builds the exact on-wire dict (keys in field order, optionals only-when-truthy, `confidence` pre-rounded, flags with their intentional `null` leaves) and serves it raw via `orjson_response`. The byte shape is frozen by `test_seg_all_snapshot` and conformance to `SegAllResponse` is asserted at the test boundary (`test_wire_seg_models`), so the model still governs the contract without paying the cost on every request. Sibling reads (`/data`, `/validate`, `/peaks`) keep the model round-trip — they're either small per-chapter or response-cached, so the cost is amortized.

### Regression net

Two layers guard the route contract:

- **Match-route tests** — `inspector/tests/routes/test_wire_{seg,ts,public,audio}_models.py` hit the live route through the Flask test client and assert the response `model_validate`s against the wire model (proves the model matches what the route emits).
- **Response snapshots** — `inspector/tests/routes/test_response_snapshots.py` snapshots every modeled GET body to `inspector/tests/routes/snapshots/<endpoint>.json` (volatile fields like `generated_at` pinned to a sentinel by `_normalize`). First run captures the baseline; every run after asserts byte-identity. A route refactor that drifts the wire fails loudly. To intentionally rebaseline: delete the snapshot file and re-run.

## Tricky-shape cookbook

The shapes that bite. Each is real, in-tree, with a path.

- **Positional tuples → `RootModel[tuple[...]]`.** A shard word is a flat 5-slot tuple `[word_idx, start_ms, end_ms, letters[], phones[]]`, modelled as `TsShardWord(RootModel[tuple[int, int, int, list[LetterTiming], list[PhoneTiming]]])` (`bucket/ts_shard.py`) so the FE gets a positional TS tuple, not an object. **json2ts limitation:** Pydantic v2 emits JSON-Schema-2020-12 `prefixItems` for tuples (correctly typed), but the pinned json2ts (15.0.4) only understands the Draft-07 `items: [...]` form and renders tuple ELEMENTS as `unknown`. The models are correct; making the FE tuple typed is a codegen-pipeline fix (down-convert `prefixItems` → `items`), deferred. Same caveat applies to every `t: tuple[int, int]` span and `peaks: list[tuple[float, float]]`. The shard word is now a 5-**or**-6 tuple — the optional 6th slot is `cells: list[CellTiming]`, a per-character haraka/cell row.
- **Enums that appear only inside a positional tuple → a parallel object model as the codegen vehicle.** Each shard cell row's `role`/`status` are the `CellRole`/`CellStatus` enums (`bucket/cell_vocab.py` — a mirror of the phonemizer's vocabulary, guarded by `qua_shared/tests/test_cell_vocab_parity.py` since the phonemizer must stay off the Inspector import path). Because they are referenced ONLY inside the positional `CellTiming` tuple, json2ts renders them as `unknown` and never emits the named unions. To give the FE importable `CellRole`/`CellStatus` string unions, `bucket/ts_shard.py` also defines `TsShardCell` — a plain object model over the same fields — re-exported by `fe_types.py` purely as the codegen vehicle. The wire cell stays positional; the FE reads it by name through `parseShardCell` (`lib/types/ts-client.ts`), the mirror of `qua_shared/ts_shard_cells.parse_cell`. The cell `tag` (slot 5) is deliberately **open-form `str | None`** (NOT enum-mirrored) — the phonemizer owns the tajweed-rule vocabulary, so new tag values ride through with no schema/parity/codegen change. `SEGMENT_SCHEMA_VERSION` bumped **v6→v7** when that vocabulary expanded (madd subtypes, plain ghunnah, ikhfaa/idgham shafawi for per-rule colour badges); the row shape is unchanged, so the bump only triggers a re-stamp.
- **No discriminator field → plain union keyed by response-key.** Validation items carry NO intrinsic on-wire discriminator. The category is the RESPONSE KEY (`failed` / `low_confidence` / …); the FE switches on that key (passed as a `category` prop), never read off the item. So `SegValAnyItem` (`wire/seg.py`) is a plain `RootModel[Union[…every variant…]]`, NOT a Pydantic `Field(discriminator=…)` union — a discriminator would force inventing an off-wire `kind` field and violate `forbid` + "model what the route emits". json2ts renders the plain union as a clean named `A | B | C` (every member is a `$ref` under a top-level `anyOf`), not `unknown` soup.
- **Literal-discriminated enums.** Finite string fields the FE switches on are `Literal[...]`, not `str`: `SegReciterState`, `SegReciterVisibility`, `audio_category: Literal["by_surah","by_ayah"]`, `OkAck.ok: Literal[True] = True`. Gives the FE a closed switch surface.
- **Dynamic-keyed maps → `dict[str, T]`.** JSON-object maps whose keys are data (chapter numbers, audio URLs, range strings) are `dict[str, T]` (TS `Record<string, T>`): `chapter_bitrate_kbps: dict[str, int]`, `peaks: dict[str, SegSlimPeaks]`, `audio_by_chapter: dict[str, str]`. JSON object keys are always strings on the wire even when they're conceptually ints.
- **No `ge=0` on offset-relative times.** `TsVerseData.time_start_ms` / `time_end_ms` (`wire/timestamps.py`) deliberately omit a `ge=0` bound — in `by_surah` mode the per-verse start is offset relative to the chapter audio and can be negative. (Contrast: `DetailedSegment.time_start` / `time_end` in `bucket/segment.py` DO carry `ge=0` — those are absolute ms offsets within the chapter audio, plus an after-validator enforcing `time_end >= time_start`.)
- **`_meta` alias.** The on-disk JSON key `_meta` (leading underscore) can't be a Python field name; models expose it as `meta` with `Field(alias="_meta")` + `populate_by_name=True`, and Pydantic resolves the alias natively. Serialize with `model_dump(by_alias=True)`. See `DetailedDocument` (pure `forbid`, native alias) and `TsShardDoc` (whose forward-compat `_meta` still surfaces extras via a `strip_and_warn` pre-validator that adds `_meta` to its declared set, since alias resolution runs *after* the pre-validator).

## Edit-history declared fields

`EditOperation.patch` (typed `EditOpPatch`) and `op_context_category` are DECLARED fields that round-trip intact — the live save flow WRITES them and the undo / resolved-by-edit paths READ them. Conversely `save_mode` is no longer persisted — it was a save-flow presentation hint, not durable state — and is re-derived wire-side by `inspector/services/activity/history_query.py::_derive_save_mode` (structural op or pipeline `batch_type` → `"full_replace"`, else `"patch"`). The prod-data migration rewrote every on-disk batch, so the model is pure `extra="forbid"`: a stray `save_mode` (or any other unexpected key) now raises `ValidationError` instead of being absorbed. Only the v0/v1 genesis records are still tolerated — `parse_edit_history_line` detects and skips them (returns `None`) before validation. Guarded by `inspector/tests/persistence/test_edit_history_schema.py`.

## Round-trip tests

Per-reciter artefacts MUST round-trip through their `bucket/` model: parse → re-serialize → byte-equal to a canonical fixture. Writer changes land in the same change as the round-trip test. The tests live in `inspector/tests/persistence/`:

| Test | Model |
|---|---|
| `test_detailed_schema.py` / `test_segment_schema.py` / `test_segment_flag.py` | `DetailedDocument` / `DetailedSegment` / `SegmentFlag` |
| `test_edit_history_schema.py` | `EditHistoryBatch` / `EditOperation` / `EditOpPatch` |
| `test_peaks_history_schema.py` | `PeaksRecord` |
| `test_audio_manifest_schema.py` | `AudioManifestSidecar` |
| `test_pipeline_meta_schema.py` | `PipelineMeta` |
| `test_ts_shard_schema.py` | `TsShardDoc` / `TsShardWord` |
| `test_segments_doc_schema.py` / `test_segments_json.py` | `SegmentsDoc` |

A model with `extra="allow"` needs a round-trip fixture carrying an extra field through unchanged (the contract: consumers must NOT strip it). A new artefact type without a round-trip test makes writer/reader drift invisible — don't ship one without it.

## External-file validation harness

The steady-state drift gate for the external bucket — validates on-disk files at write/audit time, never on cached reads.

- **`inspector/services/storage/bucket_audit.py`** — the Flask-free engine. `audit(backend, bucket_id, slug)` walks one `reciters/<slug>/` folder and runs the per-file auditors in `TOP_LEVEL_AUDITORS` (`detailed.json` → `DetailedDocument`, `edit_history.jsonl` → `parse_edit_history_line` per row, `pipeline_meta.json` → `PipelineMeta`, peaks v3 slim round-trip, mp3 existence, audio/peaks chapter-count parity, plus structural checks for the schema-less `segments.json` / `low_confidence_v2.json` / `auto_split_v1.json`). It captures the `_extras` logger so legacy-field INFOs and unknown-field WARNINGs surface in the per-file `FileResult`. Backend-agnostic: any object with `read_bytes(path)` + `list_dir(prefix)` (the bucket singleton in prod, a `FilesystemBackend` over fixtures in tests).
- **`scripts/diagnostics/validate_bucket.py`** — the whole-bucket CLI over that engine. Three passes: every reciter folder (via `audit`), the DB catalog (`repo_catalog.snapshot()` re-validates `ReciterCatalog` from rows), and every `catalog/audio_manifest/<slug>.json` sidecar (via `AudioManifestSidecar`). Exits non-zero on any hard error; `--strict` also fails on unknown-field warnings. The dead `catalog/reciter_catalog.json` backup is never validated (no app reads it). `--bucket prod|dev` (default dev; prod needs `INSPECTOR_ALLOW_PROD_BUCKET=1`).
- **`.github/workflows/bucket-validate.yml`** — runs `validate_bucket.py` nightly (~06:00 UTC) + on demand against both buckets, read-only. A non-zero exit fails the job and alerts.
- **`/healthz?deep=1`** — `bucket_audit.sample_validation()` runs a bounded probe (DB-catalog round-trip + a small spread sample of reciter folders, default 3). Opt-in: the default `/healthz` never walks the bucket, so its latency is unchanged. A deep probe finding drift flips the response to degraded (503 in deployed mode) so misconfiguration surfaces at health-check time, not mid-request.
