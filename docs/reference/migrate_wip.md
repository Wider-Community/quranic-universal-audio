# `wip/<slug>/` migrations

Playbook for one-shot data migrations against the bucket's `wip/` (and where
noted, `published/`) per-reciter `detailed.json`. Each migration here shares
the same shape: a backfill script writes new data into a parallel
`archive/<migration>/<slug>/...` path, drift- or sanity-checks the result, then
atomically promotes to the live `wip/<slug>/detailed.json`.

| # | Migration | Scope at time of writing | Script | Status |
|---|---|---|---|---|
| 1 | [`wrap_word_ranges` purge (stale wraps)](#1-stale-wrap_word_ranges-purge) | 7 reciters / 34 segs | `inspector/scripts/purge_stale_wraps.py` | shipped May 2026 |
| 2 | [`qalqala_letter` + `is_boundary_adj` backfill (validate-perf)](#2-qalqala_letter--is_boundary_adj-backfill) | 14 reciters (8 WIP + 6 published) / ~144 k segs | `inspector/scripts/backfill_qalqala_letter.py`, `inspector/scripts/backfill_boundary_adj.py` | shipped May 2026, WIP + published (extraction also stamps natively) |
| 3 | [`pad_migration` batch purge (edit-history slim)](#3-pad_migration-batch-purge) | 14 reciters / 1 388 batches / ~95 MB | `inspector/scripts/purge_pad_migration.py` | shipped May 2026, WIP + published |
| 4 | [edit-history schema slim-down (writer-side)](#4-edit-history-schema-slim-down) | All future records — legacy records untouched | code change, no script | shipped May 2026 |

Companion perf report for migration #2: [`validate_perf_report.md`](validate_perf_report.md).

---

## 1. Stale `wrap_word_ranges` purge

One-shot data migration to strip leaked `wrap_word_ranges` (and the
matching `has_repeated_words` flag) from segments where the wrap geometry
no longer fits the segment's `matched_ref`. Triggered by the auto-split
bug investigation in May 2026; the underlying code paths are now closed
(see *Code fixes* below).

Script: [`inspector/scripts/purge_stale_wraps.py`](../../inspector/scripts/purge_stale_wraps.py)

### High level

#### What the migration does

Walks every reciter's `detailed.json` (both `wip/` and `published/` tiers)
and removes `wrap_word_ranges` + `has_repeated_words` from any segment
whose wrap doesn't fit the segment's word range or whose wrap geometry is
internally invalid. Per-file backup is written before mutation.

#### Why it's needed

A long-standing bug in the inspector's split / edit-reference / merge
reducers shallow-cloned the parent segment and let `wrap_word_ranges`
ride along into the children. Subsequent ref-edits narrowed each child's
`matched_ref` while the wrap stayed put — leaving "post-split clean" segs
falsely tagged as multi-pass repetitions.

The downstream symptom is in the **Auto Split** action: it reads
`wrap_word_ranges` to reconstruct the per-section refs to send MFA. With
a stale wrap on a small child seg, the request sends N words of refs for
M seconds of audio (e.g. 25 words for 4.5s) and MFA returns
`AlignerError: Could not align the file with the current beam size`. The
silent fallback then drops the cursor at the segment midpoint, which is
exactly the bug report ("auto split always falls back to middle").

#### What's affected (May 2026 scan)

| Reciter | Tier | Wraps | Stale | Corrupted |
|---|---|---|---|---|
| `abdulwadood_haneef_mp3quran` | wip | 12 | 0 | 1 |
| `ahmed_talib_bin_humaid_mp3quran` | wip | 7 | 1 | 0 |
| `mohammed_alghazali_archive` | wip | 1 | 0 | 0 |
| `mohammed_ayyub_mp3quran` | wip | 6 | 4 | 0 |
| `raad_al_kurdi_mp3quran` | wip | 13 | 1 | 1 |
| `maher_al_muaiqly_mp3quran` | published | 10 | 4 | 0 |
| `mishary_rashid_al_afasy_mp3quran` | published | 6 | 3 | 0 |
| `yasser_al_dosari_mp3quran` | published | 24 | 19 | 0 |
| **TOTAL** | | **79** | **32** | **2** |

34 segs across 7 reciters get cleaned; 45 valid wraps survive.

#### When to re-run

The code fixes prevent new stale wraps from being written. Re-run after:

- Bulk-importing detailed.json from an external source (the offline
  pipeline in `.local/spaces/quranic_universal_aligner/`).
- Restoring a reciter from an old `archive/` snapshot.
- A future bug suspected of re-introducing stale wraps.

The BE save-time guard (see *Code fixes*) catches new bad wraps at write
time, so under normal interactive editing the count should stay at zero.

### Low level

#### Detection — `is_wrap_consistent`

Single predicate in [`inspector/utils/repetitions.py`](../../inspector/utils/repetitions.py).
A wrap is consistent iff **every** entry passes:

| Check | What it catches |
|---|---|
| `len(entry) >= 3` and all 3 parse as `surah:ayah:word` | malformed entry |
| All three refs share the same surah as `matched_ref` | cross-surah wrap |
| `jump_from >= jump_to` (linear word position in surah) | wrong-direction back-jump |
| `repeat_end >= jump_to` | repeat ends before it starts |
| Every wrap word position lies within `matched_ref`'s word range | **stale** (the inheritance bug) |

`classify_wrap` in [`inspector/scripts/purge_stale_wraps.py`](../../inspector/scripts/purge_stale_wraps.py)
returns `None` (consistent), `"stale"`, or `"corrupted"` for the report.
Anything that's opaque (unknown verse word counts) is left alone — the
script never discards data it can't positively identify as wrong.

#### The bug pattern (now closed)

Edit history makes the leak unambiguous. From
`wip/mohammed_ayyub_mp3quran/edit_history.jsonl`, verse 48:29:

```text
1. ORIGINAL (offline pipeline output):
   48:29:1-48:29:24  ts=[450370,475705]  wrap=[['48:29:11','48:29:11','48:29:24']]   ✓ valid

2. split_segment at 454900:
   AFTER  48:29:1-48:29:24  ts=[450370,454900]  wrap=[…same…]   ← inherited
   AFTER  48:29:1-48:29:24  ts=[454900,475705]  wrap=[…same…]   ← inherited

3. edit_reference (narrow left child):
   AFTER  48:29:1-48:29:3   ts=[450370,454900]  wrap=[…same…]   ← stale (1-3 doesn't contain 11-24)

4. Recurse on right child via more splits + ref-edits.
   ↓
   Final on-disk: 4 sequential segs (1-3, 4-11, 11-18, 19-24), all
   carrying the original parent's [['48:29:11','48:29:11','48:29:24']].
```

#### Code fixes

Three FE reducers and one BE adapter — see commits `e9d35fd` (initial
split fix) and `850b9f7` (edit-ref + merge + BE guard).

| Layer | File | Change |
|---|---|---|
| FE `_reduceSplit` | `inspector/frontend/src/tabs/segments/domain/apply-command.ts` | `delete piece.wrap_word_ranges; delete piece.has_repeated_words;` for every child |
| FE `_reduceEditReference` | same | drop wrap when `matched_ref` actually changes; preserve on `confirm_reference` |
| FE `_reduceMerge` | same | always drop wrap (geometry invalidated by merge) |
| BE `make_seg` | `inspector/adapters/save_payload.py` | (1) trust FE payload — no `or existing.get(…)` fallback; (2) defense-in-depth `is_wrap_consistent` check before persisting |

Tests: `inspector/frontend/src/tabs/segments/__tests__/command/split.test.ts`
covers split / edit-ref / confirm-ref / merge; `inspector/tests/persistence/test_save_clears_ignores.py`
covers FE-omits-drop, FE-sends-preserve, FE-sends-invalid-rejected.

### Apply procedure

```bash
# 1. Dry-run, full report (default — never mutates)
python inspector/scripts/purge_stale_wraps.py

# 2. Inspect a single slug's per-seg detail
python inspector/scripts/purge_stale_wraps.py --slug yasser_al_dosari_mp3quran

# 3. Per-seg detail for everything
python inspector/scripts/purge_stale_wraps.py --show-details

# 4. WIP only (skip published)
python inspector/scripts/purge_stale_wraps.py --wip-only

# 5. Apply (writes per-slug backup, then overwrites detailed.json)
python inspector/scripts/purge_stale_wraps.py --apply
```

`--apply` writes `archive/stale_wraps/<slug>/detailed.json.<UTC-stamp>.bak`
to the bucket before mutating each affected file. Restore is a copy-back.

### What it does NOT do

- Does not touch `edit_history.jsonl`. The migration is treated as a
  schema-level data fix, not a user edit. No batch is appended.
- Does not invalidate inspector caches. Restart the inspector (or wait
  for the next reciter switch) to see the cleaned state.
- Does not re-run the offline aligner on the 2 corrupted-geometry segs
  (`raad_al_kurdi 4:128`, `abdulwadood 3:153`). These are flagged in the
  report but the wrap is stripped — re-segment manually if a real
  repetition needs to be re-detected.

---

## 2. `qalqala_letter` + `is_boundary_adj` backfill

Schema additions to `wip/<slug>/detailed.json` that make the per-validate
classifier loop skip its two most expensive checks. Both fields are
deterministic functions of seg content + stable reference data; persisting
them once at backfill (and on every subsequent save) turns the runtime
classifier into a dict-lookup. **Companion perf report:
[`validate_perf_report.md`](validate_perf_report.md).**

Scripts:
- [`inspector/scripts/backfill_qalqala_letter.py`](../../inspector/scripts/backfill_qalqala_letter.py)
- [`inspector/scripts/backfill_boundary_adj.py`](../../inspector/scripts/backfill_boundary_adj.py)

### High level

#### What the migration does

For every WIP reciter's `detailed.json`, walks `entries[*].segments[*]` and
adds two fields to every seg:

- `qalqala_letter: str | None` — a single Arabic letter when the seg's
  matched_text's last Arabic letter is one of the qalqala letters
  (ق ط ب ج د); otherwise `null`.
- `is_boundary_adj: bool` — the raw boundary-adjustment rule output
  (structural + phoneme tail), **without** suppression. Suppression is
  layered on at validate-GET time.

Both fields are computed from the same helpers used by the runtime
classifier and the save flow (one source of truth):

- `services/qalqala.py::compute_qalqala_letter` — reused by the classifier
  fall-through, the save flow's `_stamp_persisted_classifier_fields`, and
  the backfill script.
- `services/validation/classifier.py::compute_is_boundary_adj` — same shape:
  one helper, three callers.

#### Why it's needed

The classifier was running `last_arabic_letter` (NFD + per-char Unicode
scan) and `_check_boundary_adj` (set lookups + phoneme tail comparison)
once per segment on **every** validate-GET. For ~13 k segs/reciter that
was ~3-4 s of pure-Python CPU per validate. Both rules are deterministic
functions of seg content + stable reference data — persisting the result
once and reading it back collapses the CPU loop to a dict-lookup.

Side effect: the `quranic_phonemizer` package + the local
`canonical_phonemes.pkl` are no longer needed at validate time. The pkl
ephemerality bug (lived in `/tmp/inspector-cache` in Docker, lost on every
container restart) is moot. The phonemizer is now used **only** by the
boundary_adj backfill script.

See [`validate_perf_report.md`](validate_perf_report.md) for measured
before/after timings, drift-check methodology, and the NFS-mount
simulation that confirms the deployed-Space cold floor.

#### What's affected (May 2026 scan, after WIP backfill)

Counts of segs whose new field carries a non-default value:

| Reciter | TOTAL_SEGS | qalqala_letters | is_boundary_adj=true |
|---|---:|---:|---:|
| `abdullah_ali_jabir_taraweeh_qdc` | 8 800 | 567 | (per ground truth) |
| `abdulwadood_haneef_mp3quran` | 9 076 | 511 | 4 |
| `ahmed_saud_mp3quran` | 298 | 59 | 0 |
| `ahmed_talib_bin_humaid_mp3quran` | 9 503 | 616 | 0 |
| `bandar_baleela_mp3quran` | 12 543 | 770 | 3 |
| `mohammed_alghazali_archive` | 12 140 | 728 | 5 |
| `mohammed_ayyub_mp3quran` | 9 429 | 562 | 15 |
| `raad_al_kurdi_mp3quran` | 11 557 | 693 | 27 |
| **TOTAL (WIP)** | **~83 k** | **~4.5 k** | **~54** |

Wire-cost: each seg gains ~25 B of JSON (`"qalqala_letter":null` is the
default), so detailed.json grew ~5 % per slug. Brotli compresses null
heavily — wire overhead is small (~1-2 %).

#### When to re-run

All three writers now stamp both fields, so new data lands in lockstep:

- **Save flow** stamps every edited seg
  ([`services/save.py::_stamp_persisted_classifier_fields`](../../inspector/services/save.py))
  with `canonical=None` (structural side only — the phonemic-side detection
  was captured at extraction or backfill time and the persisted value rides
  through saves).
- **Extraction** stamps every newly-produced seg
  ([`.local/extraction/segments/outputs.py::stamp_persisted_classifier_fields`](../../.local/extraction/segments/outputs.py))
  with the full canonical-loaded dict (structural + phonemic). Output is
  byte-equivalent to a fresh backfill — no follow-up backfill needed for
  new reciters. `upload_to_bucket.py`'s pre-flight aborts if any seg is
  missing the fields, which would mean a stale `outputs.py` ran on Katana.
- **Backfill scripts** are now used only for legacy / archive recovery
  paths (below).

Re-run the backfill scripts after:

- **Restoring a reciter from an old `archive/` snapshot** that predates
  this migration.
- **`quranic_phonemizer` version bump** — the phoneme tail tokenization
  could shift; `is_boundary_adj`'s phonemic side would need recomputation.
  (Save flow keeps `canonical=None`, so a phonemizer bump alone doesn't
  re-stamp anything; the backfill is the catch-up.)
- **Manual catalog import** — any path that drops a `detailed.json` into
  `wip/<slug>/` or `published/<slug>/` without going through extraction
  or the save flow.

If a seg lacks the field at read time (legacy data), the classifier falls
through to the original computation path and produces an identical
answer — so partial-state never breaks correctness, only perf.

### Low level

#### Derivation — one source of truth per field

**`qalqala_letter`** — `services/qalqala.py::compute_qalqala_letter`:

```python
def compute_qalqala_letter(seg: dict) -> str | None:
    text = seg.get("matched_text") or dk_text_for_ref(seg.get("matched_ref"))
    last = last_arabic_letter(text)
    return last if last in QALQALA_LETTERS else None
```

**`is_boundary_adj`** — `services/validation/classifier.py::compute_is_boundary_adj`:
extracted from the legacy `_check_boundary_adj` minus the
`is_suppressed_for` early-out (suppression is a runtime state that the
persisted field doesn't capture; the wrapper applies it at validate time).
Structural side checks (one-word seg outside muqattaʼat / single-word
verse / standalone-ref / standalone-word allow-list) plus the phoneme
tail comparison when canonical phonemes are available.

The save flow uses `canonical=None` (no pkl load on hot path); the
backfill script passes the real canonical so historical phonemic-side
detections land on disk and are preserved through Change 7 (phonemizer
runtime drop).

#### Drift check

The backfill is gated by an in-memory drift check before promotion:

1. Read `wip/<slug>/detailed.json`, stamp both fields on every seg.
2. Prime `services/cache.py` with the augmented entries.
3. Run `validate_reciter_segments(slug)` — uses the persisted fields.
4. Compare normalized output to `bench/ground_truth/<slug>.json` (the
   pre-change snapshot captured by `bench/snapshot.py`).
5. Only on byte-equivalent match: write to `archive/backfill/<slug>/detailed.json`
   then atomically promote to `wip/<slug>/detailed.json`.

This guarantees every backfilled slug produces validate output that's
byte-equivalent to the pre-change runtime — drift = abort.

#### Save-flow integration

[`inspector/services/save.py::_stamp_persisted_classifier_fields`](../../inspector/services/save.py)
is called from both save paths (`_apply_full_replace` and `_apply_patch`),
re-stamping both fields whenever `matched_ref` / `matched_text` change. So
post-save data stays in sync without a re-backfill.

### Apply procedure

The two backfill scripts share a CLI shape. Run them in order — qalqala
first, boundary_adj second (independent, but committing one at a time
keeps the drift trail clear):

```bash
# Per-script dry-run + apply, parallel-then-promote with drift gate

# qalqala_letter — drift-checked dry run on one slug
python inspector/scripts/backfill_qalqala_letter.py --slug bandar_baleela_mp3quran --dry-run

# qalqala_letter — apply across all WIP (each slug drift-gated independently)
python inspector/scripts/backfill_qalqala_letter.py --all-wip

# is_boundary_adj — same shape
python inspector/scripts/backfill_boundary_adj.py --all-wip

# Verify drift across the catalog
python bench/drift.py --all
```

Each backfill writes a pre-promotion copy at
`archive/backfill/<slug>/detailed.json` before overwriting `wip/<slug>/detailed.json`.
On failure the wip file is untouched.

### What it does NOT do

- **Does not delete `services/phonemizer_service.py` or the
  `quranic_phonemizer` package.** The backfill script + the extraction
  pipeline both still import them — they're the two writers that compute
  the phonemic-side `is_boundary_adj` natively. Removal from the
  Inspector runtime is already done (Step 7 of the original perf plan);
  full package removal is gated on those two writers migrating to a
  stripped-down phoneme module.
- **Does not touch `edit_history.jsonl`.** Same rationale as migration 1
  — schema-level data fix, not a user edit.
- **Does not invalidate caches across processes.** The save flow's
  `cache.invalidate_seg_caches` runs inside the backfill subprocess only.
  Restart the live Inspector (or wait for the next save) to pick up the
  new bytes.

---

## 3. `pad_migration` batch purge

One-shot data migration that strips `batch_type == "pad_migration"` audit
batches out of every reciter's `edit_history.jsonl`. Triggered by the
edit-history slim-down work in May 2026 — these batches were the bulk of
every reciter's history file (114 batches × ~1 MB of snapshot dumps per
batch ≈ 6-10 MB per slug) and no consumer reads them.

Script: [`inspector/scripts/purge_pad_migration.py`](../../inspector/scripts/purge_pad_migration.py)

Commit: [`e53cd91`](https://github.com/Wider-Community/quranic-universal-audio/commit/e53cd91) — adds the script.
Applied to dev bucket: same SHA (purge ran against `hetchyy/quranic-inspector-bucket-dev`).

### High level

#### What the migration does

For every slug under `wip/` (and optionally `published/`), walks
`edit_history.jsonl` line-by-line and partitions batch records by their
`batch_type`. All `batch_type == "pad_migration"` batches are moved to a
parallel `archive/pad_migration/<slug>/edit_history.jsonl`; the remaining
batches are written back to the live `<tier>/<slug>/edit_history.jsonl`.
A pre-purge copy of the full original file is preserved at
`archive/pad_migration/<slug>/edit_history.jsonl.<UTC-stamp>.bak`.

Atomic order per slug:
1. Write full pre-purge backup to `archive/pad_migration/<slug>/edit_history.jsonl.<ts>.bak`
2. Write purged batches to `archive/pad_migration/<slug>/edit_history.jsonl`
3. Overwrite live `<tier>/<slug>/edit_history.jsonl` with kept batches

Failure between 1-2 leaves the live file untouched. Failure between 2-3
leaves a recoverable backup. Restore is a copy-back from the `.bak`.

#### Why it's needed

`pad_migration` batches come from an older offline job (the post-extraction
pad-floor rewrite) that ran by appending one synthetic batch per chapter
to every reciter's edit_history.jsonl. Each batch carries
`targets_before`/`targets_after` snapshots for every seg in the chapter —
the full segment row, duplicated. The result: a typical WIP reciter's
edit_history.jsonl was 6-10 MB on disk and ~7-8 MB on the wire (post-orjson)
with 95 %+ of that mass being audit data nobody reads at runtime.

Specifically:
- The frontend filters `batch_type === 'pad_migration'` out at
  [`frontend/.../tabs/segments/stores/history.ts:108`](../../inspector/frontend/src/tabs/segments/stores/history.ts:108) —
  the History panel doesn't render them.
- The backend includes them in `history_query.load_edit_history` (and the
  classifier's `resolved_by_edit` index walks them), but neither uses
  their snapshot payloads — only `batch_id` + `op_id` for index keying.
- The validation classifier reads `matched_text` from snapshots, but
  pad_migration snapshots are an exact dump of the segment state at the
  time of the migration — equivalent to (and superseded by) the live
  `detailed.json` segs.

Removing them is purely a wire/disk-byte win with no functional effect on
History, Validate, Undo, or Stats. Measured impact: 90.6 % reduction
across the catalog (105.5 MB → 9.9 MB).

#### What's affected (May 2026 scan)

| Slug | Tier | Before (B) | After (B) | Saved (B) | Batches purged |
|---|---|---:|---:|---:|---:|
| `abdullah_ali_jabir_taraweeh_qdc` | wip | 6 511 551 | 475 | 6 511 076 | 114 |
| `abdulwadood_haneef_mp3quran` | wip | 6 153 195 | 60 969 | 6 092 226 | 114 |
| `ahmed_saud_mp3quran` | wip | 226 925 | 16 049 | 210 876 | 30 |
| `ahmed_talib_bin_humaid_mp3quran` | wip | 7 699 277 | 703 854 | 6 995 423 | 107 |
| `bandar_baleela_mp3quran` | wip | 9 896 967 | 759 757 | 9 137 210 | 114 |
| `mohammed_alghazali_archive` | wip | 8 209 524 | 70 927 | 8 138 597 | 114 |
| `mohammed_ayyub_mp3quran` | wip | 7 349 449 | 408 432 | 6 941 017 | 114 |
| `raad_al_kurdi_mp3quran` | wip | 8 688 333 | 159 709 | 8 528 624 | 114 |
| `maher_al_muaiqly_mp3quran` | published | 10 471 288 | 1 604 685 | 8 866 603 | 114 |
| `mishary_rashid_al_afasy_mp3quran` | published | 720 426 | 720 314 | 112 | 0 |
| `mohammed_siddiq_al_minshawi_mp3quran` | published | 8 714 652 | 830 924 | 7 883 728 | 114 |
| `nasser_al_qatami_mp3quran` | published | 11 133 227 | 1 289 657 | 9 843 570 | 113 |
| `saad_al_ghamdi_mp3quran` | published | 9 913 662 | 2 296 311 | 7 617 351 | 112 |
| `yasser_al_dosari_mp3quran` | published | 9 799 147 | 960 176 | 8 838 971 | 114 |
| **TOTAL** | | **~105.5 MB** | **~9.9 MB** | **~95.6 MB** | **1 388** |

`mishary_rashid_al_afasy_mp3quran` had zero pad_migration batches (it
pre-dates the offline pad-rewrite); the 112 B diff is JSON re-encoding
whitespace and the script treats it as `noop` (no mutation).

#### When to re-run

The script is idempotent: a slug with zero `pad_migration` batches
returns `noop` and writes nothing. Re-run after:

- **Importing a reciter that predates the pad-migration era** — if the
  offline pipeline at `.local/extraction/extract_segments.py` is later
  re-run on a reciter while the (now-deprecated) pad-rewrite job is also
  re-run, those audit batches will be appended again. Purge before review.
- **Restoring a reciter from an old `archive/` snapshot or git release zip**
  that predates this migration.
- **Before publishing a WIP reciter** — published reciters are read by
  end users; check that no pad_migration batches survived. `--apply
  --slug <slug>` handles a single reciter.

The pad_migration job itself is no longer run as part of any active
workflow; the inspector save path and the offline pipeline both stamp
pad fields directly into `detailed.json::_meta` (see
[`services/data_loader.py::resolve_pad`](../../inspector/services/data_loader.py)
for the alias-on-read), so no new pad_migration batches are produced.

### Low level

#### Detection

A single predicate: `record.get("batch_type") == "pad_migration"`. The
batch record itself is the unit of migration — individual ops within a
non-pad-migration batch are never touched.

Companion `batch_type` values that are NOT purged:
- `null` (regular user edit batch)
- `"strip_specials"` (the special-segment strip from extraction, filtered
  by the FE history renderer but kept on disk as audit data)

The script never inspects `op_type` — pad_migration ops only exist inside
pad_migration batches.

#### Companion code changes (no migration step)

The same May-2026 work that motivated this purge also changed what NEW
edit_history records look like. Legacy records keep their old shape; new
records are slimmer. No backfill, no schema break — older readers
continue to work.

Commits applying these writer-side changes:

| Commit | Scope |
|---|---|
| [`b8aa414`](https://github.com/Wider-Community/quranic-universal-audio/commit/b8aa414) | Drop `started_at_utc` / `ready_at_utc` / `applied_at_utc` from per-op records; drop `validation_summary_before` / `validation_summary_after` + `reciter` top-level from batches; drop `matched_text` from `/api/seg/data` shard response; orjson on `seg_edit_history` + `seg_data` routes |
| [`1e0d805`](https://github.com/Wider-Community/quranic-universal-audio/commit/1e0d805) | Drop `matched_text` from per-op `targets_before`/`targets_after` snapshots; new helper `services/quran_refs.py::dk_text_for_ref` derives the text server-side; classifier + `apply_inverse_patch` + `_apply_patch` + `make_seg` use it; FE save payload + `snapshotSeg` no longer carry `matched_text` |
| [`a86fa72`](https://github.com/Wider-Community/quranic-universal-audio/commit/a86fa72) | (Route-level, not schema): `Cache-Control: private, max-age=60` + sha256[:12] ETag on `/api/seg/validate`, `/api/seg/stats`, `/api/seg/edit-history` for 304 revalidation |

These commits don't require a per-reciter migration step — they only
change the shape of newly-written records and the wire shape of HTTP
responses. Existing on-disk records still parse fine via the pydantic
schema's `extra="allow"` policy and the classifier's
`seg.get("matched_text") or dk_text_for_ref(seg.get("matched_ref"))`
fall-through (both pre-rollout legacy records and pad_migration-era
snapshots still classify identically).

### Apply procedure

```bash
# 1. Dry-run, full report (default — never mutates)
python inspector/scripts/purge_pad_migration.py

# 2. Dry-run including published reciters
python inspector/scripts/purge_pad_migration.py --include-published

# 3. Apply to WIP only
python inspector/scripts/purge_pad_migration.py --apply

# 4. Apply to WIP + published (requires explicit flag)
python inspector/scripts/purge_pad_migration.py --apply --include-published

# 5. Single-slug debugging (works in dry-run or --apply mode)
python inspector/scripts/purge_pad_migration.py --apply --slug ahmed_saud_mp3quran
```

The script auto-detects each slug's tier via `data_dir.kind_for(slug)`
when `--slug` is used; otherwise the `--include-published` flag
controls scope. Each slug is processed independently — a failure
mid-loop leaves earlier slugs purged and later ones untouched (the
report at the end shows which mutated and which were skipped).

### What it does NOT do

- **Does not delete any data.** Purged batches live at
  `archive/pad_migration/<slug>/edit_history.jsonl`; pre-purge full
  backups live at `archive/pad_migration/<slug>/edit_history.jsonl.<ts>.bak`.
  Restore is a `backend.write_bytes_atomic(<tier>/<slug>/edit_history.jsonl,
  backend.read_bytes(<bak-path>))`.
- **Does not invalidate inspector caches across processes.** The live
  Flask process keeps its `_seg_edit_history` cache until either a save
  triggers `invalidate_seg_caches(slug)` or the process restarts. After
  applying the purge, restart Flask (or wait for the next save on the
  affected reciter) to see the new file.
- **Does not touch `detailed.json` or `segments.json`.** Only
  `edit_history.jsonl` is mutated.
- **Does not edit the `audit/<yyyy-mm>.jsonl` partition.** State-machine
  audit records are a separate stream; this migration is scoped to
  per-reciter edit history only.
- **Does not bump any `schema_version` in surviving records.** New
  records written by the inspector after commits `b8aa414` / `1e0d805`
  keep `HISTORY_SCHEMA_VERSION` as-is — the slim-down is a deletion of
  optional fields the schema already tolerated as absent via
  `default_factory=dict` / `extra="allow"`.

---

## 4. edit-history schema slim-down

Writer-side change to `wip/<slug>/edit_history.jsonl` (and `published/<slug>/`)
that drops fields with no live consumer from every newly-written batch /
op / snapshot. **No data backfill** — existing records on disk keep their
legacy shape forever; readers tolerate both via `extra="allow"` and
falsy-check fall-throughs. The "migration" is the code change itself.

Commits:

- [`b8aa414`](https://github.com/Wider-Community/quranic-universal-audio/commit/b8aa414) — drops the 3 op timestamps + `validation_summary_*` + top-level `reciter`; orjson on the read paths
- [`1e0d805`](https://github.com/Wider-Community/quranic-universal-audio/commit/1e0d805) — drops `matched_text` from per-op snapshots; new helper `services/quran_refs.py::dk_text_for_ref` derives it server-side at classify / undo / save time
- [`a86fa72`](https://github.com/Wider-Community/quranic-universal-audio/commit/a86fa72) — route-level: `Cache-Control` + ETag for 304 revalidation (not schema, listed for completeness)

### High level

#### What the change does

For every new batch that the save / undo paths append to `edit_history.jsonl`,
the following fields are no longer written:

| Field | Where it used to live | Why dropped |
|---|---|---|
| `started_at_utc` | per-op (top of each `operations[i]`) | No consumer in code, tests, or analytics. Captured `_baseOperation` time — overwritten relative to `applied_at_utc` so dwell-time was always near-zero |
| `applied_at_utc` | per-op | No consumer. Stamped by `finalizeEdit` a few ms after `started_at_utc` — never meaningful |
| `ready_at_utc` | per-op | No consumer. Stamped by `finalizeOp` AFTER `applied_at_utc`, so `applied - ready` was systematically negative — field names misordered relative to code flow |
| `validation_summary_before` | per-batch | Only fed by `chapter_validation_counts` and only read back into itself; no FE consumer or analytics |
| `validation_summary_after` | per-batch | Same; dropping it eliminated the redundant second `chapter_validation_counts` call per save (5-20 ms) |
| `reciter` (top-level) | per-batch | Slug already in the file path `<tier>/<slug>/edit_history.jsonl`; `history_query.load_edit_history` already stripped it from the wire shape |
| `matched_text` (inside snapshots) | each `targets_before[i]` / `targets_after[i]` | Derivable from `matched_ref` via `dk_words` (see [Migration #2](#2-qalqala_letter--is_boundary_adj-backfill)'s `dk_text_for_ref` helper). Largest single contributor — ~200-600 B per snapshot, ~2-3 snapshots per op |

#### Why it's needed

The dropped fields were collectively ~10-15 % of edit_history.jsonl wire
bytes (brotli) and 25-40 % of the decoded bytes. The 3 op timestamps were
the biggest per-op contributor (~127 B per op for the 3 ISO strings); on
heavy reciters with thousands of ops this adds up. None had consumers.

The `matched_text` strip is the largest single saving by mass but is also
the most-load-bearing change — the runtime classifier (qalqala +
boundary_adj) reads it to detect last-letter and standalone-word
patterns. Replacing the field with on-demand derivation kept the
classifier producing byte-equivalent output (drift-checked) while
shaving ~200-600 B per snapshot off the wire and making the round-trip
self-consistent (server is now authoritative on the matched-ref ↔
matched-text relationship instead of trusting whatever the FE echoed).

#### What's affected

- **New records (post-commit)**: slim shape — none of the dropped fields
  are written.
- **Legacy records (pre-commit)**: untouched. Still parse fine via
  `scripts/lib/schemas/edit_history.py` (pydantic `extra="allow"` +
  `default_factory=dict`). The runtime classifier's
  `seg.get("matched_text") or dk_text_for_ref(seg.get("matched_ref"))`
  fall-through means legacy snapshots with `matched_text` continue to
  use it; new snapshots without it derive equivalently.
- **`detailed.json`**: still carries `matched_text` per seg (documented
  schema, external dataset/release consumers depend on it). The save
  flow now derives it server-side rather than echoing from the FE — see
  [`adapters/save_payload.py::make_seg`](../../inspector/adapters/save_payload.py)
  and [`services/save.py::_apply_patch`](../../inspector/services/save.py). The
  undo path enriches snapshots before writing them back via
  [`domain/command.py::apply_inverse_patch`](../../inspector/domain/command.py).

#### When to re-run

There is nothing to run. The change is purely writer-side.

**The two scenarios where you might want a real backfill** (currently
NOT implemented — would need a new one-shot script):

1. **Storage cleanup**: rewrite legacy records to the new slim shape.
   Would save the disk bytes of legacy records but doesn't help anything
   at runtime (those records are read-once, mostly via History panel
   render). Low priority; defer until edit_history.jsonl grows large
   again or the legacy fields actively cause friction.
2. **External downstream consumer** that can't tolerate the dropped
   fields. None exists today.

If either becomes relevant, the script shape mirrors migration #3:
walk every reciter's `edit_history.jsonl`, partition records, write
to `archive/schema_slim/<slug>/edit_history.jsonl.<ts>.bak` first,
then overwrite the live file.

### Low level

#### Reader compatibility

The slim-down is safe-for-readers because:

| Reader | How it tolerates the change |
|---|---|
| `services/history_query.py::load_edit_history` | Uses `record.get(...)` everywhere; absent fields surface as `None` |
| `services/validation/classifier.py` | `seg.get("matched_text") or dk_text_for_ref(seg.get("matched_ref"))` — legacy + new both work |
| `services/undo.py::apply_reverse_op` + `domain/command.py::apply_inverse_patch::_hydrate` | Re-derives `matched_text` for restored snapshots before writing back to `detailed.json` |
| `scripts/lib/schemas/edit_history.py` (pydantic) | `extra="allow"` + `default_factory=dict` — both shapes parse |
| Frontend `frontend/src/tabs/segments/utils/history/chains.ts` | `snap.matched_text || ''` falsy-check; FE History panel re-derives Arabic text from `matched_ref + dk_words` for display regardless |

#### Writer changes (per commit)

`b8aa414`:
- FE `frontend/src/tabs/segments/stores/dirty.ts::createOp` + `finalizeOp` + `frontend/src/tabs/segments/domain/apply-command.ts::_baseOperation` + `frontend/src/tabs/segments/utils/edit/common.ts::finalizeEdit` — drop all 3 timestamp writes
- FE `frontend/src/lib/types/domain.ts::EditOp` — drop the 3 timestamp fields + `validation_summary_*` from `HistoryBatch`
- BE `services/save.py::_persist_and_record` — drop `validation_summary_before` + `validation_summary_after` from the batch dict; drop the second `chapter_validation_counts` call; drop `"reciter": reciter,`
- BE `services/undo.py::_append_revert_record` — same drops; remove `val_before` / `val_after` params + the now-unused `_merge_val_summaries` helper and `chapter_validation_counts` + `VALIDATION_CATEGORIES` imports
- BE `services/history_query.py:176` — drop `validation_summary_before` / `validation_summary_after` from the wire shape
- BE `routes/segments_data.py::seg_data` + `routes/segments_validation.py::seg_edit_history` — `jsonify` → `orjson_response`

`1e0d805`:
- BE `services/quran_refs.py::dk_text_for_ref` — new helper (~30 LOC), mirror of FE's `references.ts::dkTextForRef`
- BE `services/validation/classifier.py` — qalqala + boundary_adj checks gain `or dk_text_for_ref(seg.get("matched_ref"))` fall-through
- BE `domain/command.py::apply_inverse_patch::_hydrate` — populates `matched_text` on restored snapshots before they land in `detailed.json`
- BE `adapters/save_payload.py::make_seg` + `services/save.py::_apply_patch` — derive `matched_text` from `matched_ref` instead of trusting the FE payload
- FE `frontend/src/tabs/segments/stores/dirty.ts::snapshotSeg` — drop `matched_text` from the snapshot field set
- FE `frontend/src/tabs/segments/utils/save/{payload,execute}.ts` — drop `matched_text` from `SaveSegmentPayload{Full,Patch}` and their construction sites

#### Drift guarantee

The classifier change passes a parity check by construction:

```python
# Legacy record:           {"matched_ref": "1:1:1-1:1:4", "matched_text": "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ"}
# New record:              {"matched_ref": "1:1:1-1:1:4"}                       # no matched_text written
# Effective text both ways: dk_text_for_ref("1:1:1-1:1:4") == "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ"
```

The fall-through prefers the explicit `matched_text` when present
(handles any manual / legacy override), else derives from
`matched_ref + dk_words`. Both branches produce the same Unicode-NFD
last-letter / standalone-word lookup, so qalqala + boundary_adj
detection is byte-equivalent across the rollout boundary.

### Apply procedure

None — code change only. Verification is:

```bash
# 1. New record shape (write an edit, fetch history, confirm absent keys):
curl http://localhost:5000/api/seg/edit-history/<slug> | python3 -c "
import json, sys
batches = json.load(sys.stdin)['batches']
banned_batch = ['validation_summary_before', 'validation_summary_after', 'reciter']
banned_op = ['started_at_utc', 'ready_at_utc', 'applied_at_utc']
banned_snap = ['matched_text']
# Check most recent batch (post-commit)
b = batches[-1]
print('batch banned present:', [k for k in banned_batch if k in b])
op = (b.get('operations') or [{}])[0]
print('op banned present:', [k for k in banned_op if k in op])
snap = (op.get('targets_after') or [{}])[0]
print('snap banned present:', [k for k in banned_snap if k in snap])
"

# 2. Backward compat (legacy record still parses):
curl http://localhost:5000/api/seg/edit-history/<slug>   # any pre-commit slug — should 200 with legacy fields still present in old batches

# 3. Classifier parity (qalqala + boundary_adj):
curl http://localhost:5000/api/seg/validate/<slug>       # category_counts identical to pre-commit baseline (drift-checked via bench/drift.py if available)
```

### What it does NOT do

- **Does not rewrite legacy records.** Pre-commit batches keep all their
  fields on disk. The runtime has no way to tell them apart from new
  records and doesn't try to.
- **Does not change `HISTORY_SCHEMA_VERSION`.** The pydantic schema in
  `scripts/lib/schemas/edit_history.py` always allowed these fields to
  be absent (`default_factory=dict`); they're now consistently absent
  instead of inconsistently present.
- **Does not strip `matched_text` from `detailed.json`.** The save flow
  now writes a server-derived value instead of the FE-echoed value, but
  the on-disk schema field stays — external dataset / release consumers
  depend on it.
- **Does not run any data script.** The migration is a pure code change
  shipped in two commits.
