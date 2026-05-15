# Migration: stale `wrap_word_ranges` purge

One-shot data migration to strip leaked `wrap_word_ranges` (and the
matching `has_repeated_words` flag) from segments where the wrap geometry
no longer fits the segment's `matched_ref`. Triggered by the auto-split
bug investigation in May 2026; the underlying code paths are now closed
(see *Code fixes* below).

Script: [`inspector/scripts/purge_stale_wraps.py`](../../inspector/scripts/purge_stale_wraps.py)

## High level

### What the migration does

Walks every reciter's `detailed.json` (both `wip/` and `published/` tiers)
and removes `wrap_word_ranges` + `has_repeated_words` from any segment
whose wrap doesn't fit the segment's word range or whose wrap geometry is
internally invalid. Per-file backup is written before mutation.

### Why it's needed

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

### What's affected (May 2026 scan)

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

### When to re-run

The code fixes prevent new stale wraps from being written. Re-run after:

- Bulk-importing detailed.json from an external source (the offline
  pipeline in `.local/spaces/quranic_universal_aligner/`).
- Restoring a reciter from an old `archive/` snapshot.
- A future bug suspected of re-introducing stale wraps.

The BE save-time guard (see *Code fixes*) catches new bad wraps at write
time, so under normal interactive editing the count should stay at zero.

## Low level

### Detection — `is_wrap_consistent`

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

### The bug pattern (now closed)

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

### Code fixes

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
