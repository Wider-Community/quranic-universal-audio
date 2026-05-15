# Validation engine benchmark harness

Phase-0 scaffolding for the `validate ≤ 1s` optimization (see plan at
`~/.claude/plans/matched-text-qalqala-should-frolicking-forest.md`).

## Scripts

| Script | Purpose |
|---|---|
| `snapshot.py` | Capture canonical (pre-change) `validate_reciter_segments` output per WIP slug + per-category counts CSV |
| `drift.py`    | Compare a current run against the canonical snapshot; print per-category diff on mismatch; exit non-zero on any drift |
| `measure.py`  | Time `validate_reciter_segments` in `inspector-cold` / `warm` / `process-cold` modes; append CSV row to `results/timings.csv` |

## Workflow

```bash
# 0.3 — capture canonical snapshots (once, before any code change)
./.venv/bin/python3 bench/snapshot.py

# 0.4 — baseline timings (once, before any code change)
./.venv/bin/python3 bench/measure.py --all --mode inspector-cold --tag baseline
./.venv/bin/python3 bench/measure.py --all --mode warm           --tag baseline
./.venv/bin/python3 bench/measure.py --all --mode process-cold   --tag baseline

# after every code change in Phase 1:
./.venv/bin/python3 bench/drift.py --slugs abdulwadood_haneef_mp3quran,mohammed_ayyub_mp3quran
./.venv/bin/python3 bench/measure.py --slugs abdulwadood_haneef_mp3quran,mohammed_ayyub_mp3quran --mode inspector-cold --tag change1
```

## Outputs

| Path | Status |
|---|---|
| `bench/ground_truth/<slug>.json` | committed |
| `bench/results/baseline_counts.csv` | committed |
| `bench/results/timings.csv` | gitignored (per-machine ms variance) |
| `bench/results/final_report.md` | committed at end of Phase 3 |

## Invariants

- `drift.py` MUST pass before any commit. Drift = silent semantic regression.
- All measurements run from the same worktree, same Python process model
  (single-worker Flask), against the same dev bucket.
- `inspector-cold` is the `<1s` target gate. `process-cold` is reported but
  not gated.
