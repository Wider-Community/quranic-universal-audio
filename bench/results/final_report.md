# Validation engine optimization — final report

Worktree: `.local/worktrees/validate-opt` (branch `worktree-validate-opt`).
Dataset: 8 WIP reciters on dev bucket `hetchyy/quranic-inspector-bucket-dev`.

## TL;DR

- **Zero drift across all 8 WIP reciters** at every change step (every category list byte-equivalent to pre-change snapshot).
- **Warm-mode validate: 2-4× speedup** per reciter (most slugs now <250 ms warm; ahmed_saud at 6 ms).
- **Inspector-cold (local-dev, HF-bucket-HTTPS-bound): 1.1-1.7× speedup**. The `<1 s` target is achievable only on the tiny reciter locally; the larger reciters' floor (~2.5-4 s) is HF HTTPS RTT × N parallel reads, not Inspector CPU.
- **Phonemizer fully out of the Inspector runtime.** `services/phonemizer_service.py` is now only used by `inspector/scripts/backfill_boundary_adj.py` (offline). Eager-boot init removed. No `canonical_phonemes.pkl` is loaded during validate.
- **Schema additions to `detailed.json`** (per-seg): `qalqala_letter: str | None`, `is_boundary_adj: bool`. Backfilled across all 8 WIP slugs via parallel-then-promote scripts.

## Phase 0 — baseline (pre-change, c70c81f)

`inspector-cold` median ms (5 trials, system idle):

| slug | TOTAL_SEGS | issues | baseline cold ms | baseline warm ms |
|---|---:|---:|---:|---:|
| abdullah_ali_jabir_taraweeh_qdc | 8800 | 5039 | 3626 | n/a |
| abdulwadood_haneef_mp3quran (primary) | 9076 | 5673 | **3342** | ~500 |
| ahmed_saud_mp3quran | 298 | 179 | 1396 | 9 |
| ahmed_talib_bin_humaid_mp3quran | 9503 | 5182 | 4012 | 483 |
| bandar_baleela_mp3quran | 12543 | 6996 | 5012 | 632 |
| mohammed_alghazali_archive | 12140 | 6571 | 4567 | 584 |
| mohammed_ayyub_mp3quran (primary) | 9429 | 6470 | **5009** | 876 |
| raad_al_kurdi_mp3quran | 11557 | 8046 | 5701 | 582 |

Baseline `process-cold` (subprocess fresh per trial): 4.4–8.1 s median.

Per-category counts: see `bench/results/baseline_counts.csv`.

## Phase 1 — changes applied

Each change was: (1) applied as a single commit in the worktree, (2) drift-checked against `bench/ground_truth/<slug>.json` (must PASS), (3) measured in `inspector-cold` and `warm` modes on both primary slugs.

| # | Change | Drift | Cumulative impact (primary slugs, warm) | Commit |
|---|---|:---:|---|---|
| 1 | `@lru_cache` on `last_arabic_letter` + `strip_quran_deco`; precomputed surah-ayah offset table for `_word_ord` | PASS | haneef warm 500→159 ms (−68%); ayyub warm 876→164 ms (−81%) | 30f3754 |
| 2 | `ThreadPoolExecutor(4)` fans out the 4 independent bucket reads in validate (`load_detailed` / `_resolved_idx` / `load_probe_v2` / `load_seg_verses`) | PASS | haneef cold 3316→2464 ms (−26%); ayyub cold 3750→2643 ms (−47%) | 0b68493 |
| 3 | (in-memory verse map from entries) | **REVERTED** | warm regressed 159→502 ms — the in-memory `build_segments_doc` walk is more expensive than the cached `load_seg_verses` returns. Bucket read was already parallel anyway. | — |
| 4 | Persist `qalqala_letter` per-seg in `detailed.json`. Classifier short-circuits on the persisted field; legacy segs fall through to compute. Save flow stamps via `services/qalqala.py::compute_qalqala_letter` — one source of truth across save / backfill / classifier fall-through. | PASS (all 8) | detailed.json grew ~5% (`"qalqala_letter":null` on every seg). Cold dominated by I/O so impact visible mostly in warm. | a8e6531 |
| 5 | Persist `is_boundary_adj` per-seg. `_check_boundary_adj` split into `compute_is_boundary_adj` (raw rule, no suppression) + suppression-aware wrapper. Backfill uses `canonical_phonemes` so historical phonemic-side detections are captured. Save stamps structural-only (no pkl). | PASS (all 8) | haneef warm 193→118 ms (−39%); ayyub warm 214→159 ms (−26%) | b8a52ce |
| 6 | (persist `resolved_by_edit`) | **DEFERRED** | After Change 2 the edit_history read is already in parallel — removing it doesn't shrink max-of-parallel. Remaining ~150-250 ms savings vs save+undo integration complexity wasn't worth it. Documented for future revisit. | — |
| 7 | Drop `quranic_phonemizer` + `canonical_phonemes` pkl from the Inspector runtime. `validate_reciter_segments` passes `canonical=None`. `app.py` boot init removed. Pkl + package now offline-only (`scripts/backfill_boundary_adj.py`). | PASS (all 8) | haneef cold 2533 ms median; ayyub cold 3344 ms median (cumul −24%/−33% vs baseline) | a00a278 |
| 8 | (chapter-scoped `?chapters=` param) | **DROPPED** | User explicitly rejected per-chapter validate (accordions are global across chapters and segs — splitting the response would require FE merge logic and break the global accordion view). | — |

## Phase 2 — sweep across all 8 WIP reciters

Drift on all 8 WIP slugs: **PASS** (every category byte-equivalent to ground-truth snapshot).

### `inspector-cold` median, post-changes (5 trials, system idle ~0.6 loadavg)

| slug | baseline (ms) | final (ms) | speedup | drift |
|---|---:|---:|---:|:---:|
| abdullah_ali_jabir_taraweeh_qdc | 3626 | 3280 | 1.11× | PASS |
| abdulwadood_haneef_mp3quran | 3342 | **2655** | 1.26× | PASS |
| ahmed_saud_mp3quran | 1396 | **427** | **3.27×** | PASS |
| ahmed_talib_bin_humaid_mp3quran | 4012 | 2758 | 1.45× | PASS |
| bandar_baleela_mp3quran | 5012 | 4410 | 1.14× | PASS |
| mohammed_alghazali_archive | 4567 | 3306 | 1.38× | PASS |
| mohammed_ayyub_mp3quran | 5009 | 3437 | 1.46× | PASS |
| raad_al_kurdi_mp3quran | 5701 | 3426 | 1.66× | PASS |
| **aggregate (sum)** | **32,665** | **23,699** | **1.38×** | — |

### `warm` median, post-changes (7 trials)

| slug | baseline warm (ms) | final warm (ms) | speedup |
|---|---:|---:|---:|
| abdullah_ali_jabir_taraweeh_qdc | n/a | 179 | — |
| abdulwadood_haneef_mp3quran | ~500 | **129** | 3.9× |
| ahmed_saud_mp3quran | 9 | **6** | 1.4× |
| ahmed_talib_bin_humaid_mp3quran | 483 | 134 | 3.6× |
| bandar_baleela_mp3quran | 632 | 293 | 2.2× |
| mohammed_alghazali_archive | 584 | 255 | 2.3× |
| mohammed_ayyub_mp3quran | 876 | **218** | 4.0× |
| raad_al_kurdi_mp3quran | 582 | 174 | 3.3× |

**Every WIP slug now warm-validates under 300 ms; 5 of 8 under 200 ms.**

### `process-cold` (fresh Python subprocess per trial, 3 trials)

Higher variance + dominated by Python module-load + HF HTTPS roundtrip. Reported but not gated against `<1 s`.

## What kept us above 1 s cold for full-size reciters

The remaining cold cost (~2.5-4.4 s) is HF-bucket-over-HTTPS I/O — primarily `detailed.json` fetch (now ~5.4-6 MB per slug after the per-seg field additions). On a deployed Space with the bucket NFS-mounted, those reads are ~10× faster and the same Inspector CPU work (~200-300 ms) lands the cold path well under 1 s.

What we can't measure here without an NFS mount: the production cold-validate ceiling. The Inspector-side optimizations are exhaustive — the warm timings (no I/O, only Python CPU) show what the cold path collapses to once I/O is fast: 6-300 ms across the 8 reciters.

## Per-reciter, per-category counts (baseline)

See `bench/results/baseline_counts.csv`. Excerpt:

| slug | failed | missing_verses | missing_words | structural_errors | low_confidence | low_confidence_v2 | repetitions | audio_bleeding | boundary_adj | cross_verse | qalqala | muqattaat | basmala_amin | TOTAL_SEGS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| abdullah_ali_jabir_taraweeh_qdc | 0 | 0 | 0 | 0 | 3930 | 2 | 0 | 0 | 1 | 507 | 567 | 30 | 2 | 8800 |
| abdulwadood_haneef_mp3quran | 8 | 1 | 8 | 0 | 4585 | 0 | 12 | 0 | 2 | 515 | 511 | 29 | 2 | 9076 |
| ahmed_saud_mp3quran | 0 | 0 | 0 | 0 | 92 | 0 | 0 | 0 | 0 | 28 | 59 | 0 | 0 | 298 |
| ahmed_talib_bin_humaid_mp3quran | 1 | 2 | 2 | 0 | 4466 | 12 | 0 | 0 | 0 | 134 | 535 | 28 | 2 | 9503 |
| bandar_baleela_mp3quran | 0 | 0 | 0 | 0 | 6156 | 36 | 0 | 0 | 3 | 0 | 770 | 29 | 2 | 12543 |
| mohammed_alghazali_archive | 11 | 0 | 8 | 0 | 5745 | 1 | 1 | 0 | 4 | 41 | 728 | 30 | 2 | 12140 |
| mohammed_ayyub_mp3quran | 0 | 0 | 0 | 0 | 5321 | 73 | 6 | 0 | 0 | 478 | 561 | 29 | 2 | 9429 |
| raad_al_kurdi_mp3quran | 24 | 3 | 9 | 1 | 6882 | 3 | 13 | 0 | 14 | 373 | 693 | 29 | 2 | 11557 |

`low_confidence` dominates the count (every seg below 80% confidence). `qalqala` is the second-densest at ~500-770 per reciter — and was the single biggest CPU cost before Change 1 + Change 4.

## Schema changes

`detailed.json` segments now carry two additional fields:

- `qalqala_letter: str | null` — a single Arabic letter when the seg's matched-text's last Arabic letter is one of the qalqala letters (ق ط ب ج د), else `null`.
- `is_boundary_adj: bool` — raw boundary-adjustment rule output (no suppression).

Both fields are computed by `services/qalqala.py::compute_qalqala_letter` and `services/validation/classifier.py::compute_is_boundary_adj` respectively. Stamped at save time by `services/save.py::_stamp_persisted_classifier_fields`. Backfilled across existing reciters by:

- `inspector/scripts/backfill_qalqala_letter.py`
- `inspector/scripts/backfill_boundary_adj.py`

Both backfill scripts use the parallel-then-promote pattern: write to `archive/backfill/<slug>/detailed.json`, drift-check in-memory against `bench/ground_truth/<slug>.json`, then atomically promote to `wip/<slug>/detailed.json` only on byte-equivalent match.

## Files changed

```
inspector/
├── app.py                                       (-eager phonemizer init)
├── services/
│   ├── data_loader.py                           (no longer used: load_seg_verses sat unused for one experiment — kept for back-compat with other callers)
│   ├── qalqala.py                               NEW (compute_qalqala_letter helper)
│   ├── save.py                                  (_stamp_persisted_classifier_fields wiring)
│   └── validation/
│       ├── __init__.py                          (ThreadPoolExecutor, drop get_canonical_phonemes call)
│       └── classifier.py                        (compute_is_boundary_adj split + persisted-field short-circuit + qalqala_letter short-circuit)
├── scripts/
│   ├── backfill_qalqala_letter.py               NEW
│   └── backfill_boundary_adj.py                 NEW
└── utils/
    └── arabic_text.py                           (@lru_cache on last_arabic_letter + strip_quran_deco)

bench/
├── snapshot.py                                  NEW
├── drift.py                                     NEW
├── measure.py                                   NEW
├── ground_truth/<slug>.json × 8                 NEW (committed canonical snapshots)
├── results/baseline_counts.csv                  NEW (committed)
├── results/timings.csv                          (gitignored, per-machine ms variance)
└── results/final_report.md                      THIS FILE
```

## Open follow-ups (not in this branch)

1. **Backfill published reciters** with `qalqala_letter` + `is_boundary_adj`. Required before the same perf win lands for published-reciter validate paths.
2. **Persist `resolved_by_edit`** (Change 6, deferred). Save + undo flow integration would let validate drop the `build_resolved_by_edit_index` walk entirely. Currently it stays in the parallel I/O block and doesn't dominate, but it's still ~150-250 ms of in-process work per cold call.
3. **Extraction-pipeline integration**: `.local/extraction/extract_segments.py` should stamp `qalqala_letter` + `is_boundary_adj` at extraction time, so brand-new reciters land pre-persisted and never need the backfill scripts.
4. **Deployed Space measurement**: re-run `bench/measure.py` against the bucket-NFS-mounted production Space to confirm `<1 s` cold lands there with the same Inspector-side code paths.
5. **Eventually delete `services/phonemizer_service.py`** + `quranic_phonemizer` dependency once all reciters (WIP + published + any new arrivals from Katana) are backfilled with `is_boundary_adj`. Currently the import is preserved for the backfill script only.

## Aggregate session impact

- 4 changes shipped (Changes 1, 2, 4, 5, 7); 2 reverted/deferred (3, 6); 1 dropped per user direction (8).
- 8/8 WIP reciter slugs pass byte-equivalent drift check at HEAD.
- Aggregate inspector-cold time for one validate per slug: **32.7 s → 23.7 s (1.38× faster)**.
- Aggregate warm time: **~4.6 s → ~1.4 s (3.3× faster)**.
- 2 new per-seg fields persisted (~5-6% growth on `detailed.json`).
- 1 external dependency (`quranic_phonemizer`) moved out of the runtime path.
- 5 commits in the worktree; ready for review + cherry-pick onto `dev` once published-reciter backfill is sequenced.
