# `wip/<slug>/detailed.json` migrations

Playbook for one-shot data migrations against the bucket's `wip/` (and where
noted, `published/`) per-reciter `detailed.json`. Each migration here shares
the same shape: a backfill script writes new data into a parallel
`archive/<migration>/<slug>/...` path, drift- or sanity-checks the result, then
atomically promotes to the live `wip/<slug>/detailed.json`.

| # | Migration | Scope at time of writing | Script | Status |
|---|---|---|---|---|
| 1 | [`wrap_word_ranges` purge (stale wraps)](#1-stale-wrap_word_ranges-purge) | 7 reciters / 34 segs | `inspector/scripts/purge_stale_wraps.py` | shipped May 2026 |
| 2 | [`qalqala_letter` + `is_boundary_adj` backfill (validate-perf)](#2-qalqala_letter--is_boundary_adj-backfill) | 8 WIP reciters / ~80 k segs | `inspector/scripts/backfill_qalqala_letter.py`, `inspector/scripts/backfill_boundary_adj.py` | WIP only — published pending |

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

The save flow stamps both fields on every edited seg
([`services/save.py::_stamp_persisted_classifier_fields`](../../inspector/services/save.py)),
so interactive editing keeps the data in lockstep. Re-run after:

- **Published-reciter migration** — current backfill is WIP only. Apply
  to `published/<slug>/detailed.json` when extending to the rest of the
  catalog.
- **New reciter from extraction** — until the offline pipeline at
  `.local/extraction/extract_segments.py` is updated to stamp these
  fields at extraction time, run the backfill once per fresh reciter.
- **Restoring a reciter from an old `archive/` snapshot** that predates
  this migration.
- **`quranic_phonemizer` version bump** — the phoneme tail tokenization
  could shift; `is_boundary_adj`'s phonemic side would need recomputation.

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

- **Does not touch published reciters yet.** Re-running with
  `--all-wip` is safe but doesn't extend to `published/`. Use a
  follow-up script invocation (planned addition: `--all-published`)
  before flipping the runtime to require the persisted fields on
  published reads.
- **Does not delete `services/phonemizer_service.py` or the
  `quranic_phonemizer` package.** The backfill script still imports
  them — they're the ONE remaining consumer. Removal happens after
  every reciter (WIP + published + extraction-pipeline output) is
  pre-stamped.
- **Does not touch `edit_history.jsonl`.** Same rationale as migration 1
  — schema-level data fix, not a user edit.
- **Does not invalidate caches across processes.** The save flow's
  `cache.invalidate_seg_caches` runs inside the backfill subprocess only.
  Restart the live Inspector (or wait for the next save) to pick up the
  new bytes.
