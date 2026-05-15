"""Measure validate timing in multiple modes.

Modes:
  inspector-cold  Flask warm, inspector caches invalidated. Reflects post-save path.
  warm            Cache-hit path. Reflects subsequent validates with no save.
  process-cold    Fresh Python subprocess per trial. Reflects container-restart path.

Usage:
    python bench/measure.py --slug <slug> [--mode inspector-cold] [--trials N]
    python bench/measure.py --all [--mode inspector-cold] [--trials N]
    python bench/measure.py --slugs a,b,c
    python bench/measure.py --tag baseline                 # writes CSV row with tag

Output: pretty-printed JSON per slug + appends a row to bench/results/timings.csv
        with columns: timestamp, tag, slug, mode, trials, median_ms, min_ms,
        max_ms, git_sha, loadavg_1min.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSPECTOR = REPO_ROOT / "inspector"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(INSPECTOR))

from services import data_dir  # noqa: E402
from services.cache import invalidate_seg_caches  # noqa: E402
from services.validation import validate_reciter_segments  # noqa: E402

RESULTS = REPO_ROOT / "bench" / "results"
TIMINGS_CSV = RESULTS / "timings.csv"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT),
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def _loadavg() -> float:
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return -1.0


def measure_inspector_cold(slug: str, trials: int) -> dict:
    """Clear caches before each call; Flask process stays warm."""
    times_ms: list[float] = []
    for i in range(trials):
        invalidate_seg_caches(slug)
        t0 = time.perf_counter()
        validate_reciter_segments(slug)
        ms = (time.perf_counter() - t0) * 1000
        times_ms.append(ms)
        print(f"    trial {i + 1}/{trials}: {ms:>8.1f} ms", flush=True)
    return _summarize(times_ms)


def measure_warm(slug: str, trials: int) -> dict:
    """One inspector-cold prime, then time pure cache-hit trips."""
    invalidate_seg_caches(slug)
    validate_reciter_segments(slug)  # prime
    times_ms: list[float] = []
    for i in range(trials):
        t0 = time.perf_counter()
        validate_reciter_segments(slug)
        ms = (time.perf_counter() - t0) * 1000
        times_ms.append(ms)
        print(f"    trial {i + 1}/{trials}: {ms:>8.3f} ms", flush=True)
    return _summarize(times_ms)


def measure_process_cold(slug: str, trials: int) -> dict:
    """Fork a fresh Python process per trial — no module-level state retained."""
    times_ms: list[float] = []
    python = sys.executable
    code = (
        "import sys, time; "
        f"sys.path.insert(0, {str(REPO_ROOT)!r}); "
        f"sys.path.insert(0, {str(INSPECTOR)!r}); "
        "from services.validation import validate_reciter_segments; "
        f"t0 = time.perf_counter(); validate_reciter_segments({slug!r}); "
        "print(f'{(time.perf_counter() - t0) * 1000:.1f}')"
    )
    for i in range(trials):
        out = subprocess.check_output(
            [python, "-c", code],
            cwd=str(INSPECTOR),
            text=True,
        ).strip()
        ms = float(out)
        times_ms.append(ms)
        print(f"    trial {i + 1}/{trials}: {ms:>8.1f} ms", flush=True)
    return _summarize(times_ms)


def _summarize(times_ms: list[float]) -> dict:
    return {
        "trials": times_ms,
        "median_ms": statistics.median(times_ms),
        "min_ms": min(times_ms),
        "max_ms": max(times_ms),
        "mean_ms": statistics.mean(times_ms),
        "stdev_ms": statistics.stdev(times_ms) if len(times_ms) > 1 else 0.0,
    }


def _append_csv_row(tag: str, slug: str, mode: str, summary: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    header = [
        "timestamp", "tag", "slug", "mode", "trials",
        "median_ms", "min_ms", "max_ms", "mean_ms", "stdev_ms",
        "git_sha", "loadavg_1min",
    ]
    row = {
        "timestamp": _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "tag": tag,
        "slug": slug,
        "mode": mode,
        "trials": len(summary["trials"]),
        "median_ms": round(summary["median_ms"], 1),
        "min_ms": round(summary["min_ms"], 1),
        "max_ms": round(summary["max_ms"], 1),
        "mean_ms": round(summary["mean_ms"], 1),
        "stdev_ms": round(summary["stdev_ms"], 1),
        "git_sha": _git_sha(),
        "loadavg_1min": _loadavg(),
    }
    write_header = not TIMINGS_CSV.exists()
    with TIMINGS_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--slug", help="single slug to measure")
    group.add_argument("--all", action="store_true", help="every WIP slug")
    group.add_argument("--slugs", help="comma-separated list")
    ap.add_argument("--mode", choices=["inspector-cold", "warm", "process-cold"],
                    default="inspector-cold")
    ap.add_argument("--trials", type=int)
    ap.add_argument("--tag", default="", help="label for this run in the CSV log")
    args = ap.parse_args()

    if args.all:
        slugs = sorted(data_dir.list_slugs("wip"))
    elif args.slugs:
        slugs = [s.strip() for s in args.slugs.split(",") if s.strip()]
    else:
        slugs = [args.slug]

    default_trials = {"inspector-cold": 5, "warm": 5, "process-cold": 3}
    trials = args.trials or default_trials[args.mode]

    print(f"loadavg_1min={_loadavg():.2f}  git_sha={_git_sha()}  mode={args.mode}  trials={trials}\n")

    fn = {
        "inspector-cold": measure_inspector_cold,
        "warm": measure_warm,
        "process-cold": measure_process_cold,
    }[args.mode]

    for slug in slugs:
        print(f"  {slug:<45s}")
        summary = fn(slug, trials)
        print(f"    median={summary['median_ms']:.1f}ms  min={summary['min_ms']:.1f}  "
              f"max={summary['max_ms']:.1f}  stdev={summary['stdev_ms']:.1f}")
        _append_csv_row(args.tag, slug, args.mode, summary)

    print(f"\nAppended results to {TIMINGS_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
