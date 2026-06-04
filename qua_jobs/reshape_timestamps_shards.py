#!/usr/bin/env python3
"""Reshape v2 occurrence-list timestamps shards → temporal segment-array shards.

Thin CLI around the pure transform in ``qua_shared/timestamps_reshape.py``. The
transform reuses the offline writer's segment-array builder, so a reshaped shard
is byte-shape identical to a freshly-generated one. See
``docs/planning/ts-segment-array-migration.md``.

Scope of THIS tool (one-off migration, local only):

  - **DRY-RUN against a LOCAL directory of shards** — no bucket reads, no bucket
    writes. Point ``--src-dir`` at a directory of ``<chapter>.json.gz`` (and/or
    ``.json``) shards (e.g. a synced mirror or the audit cache
    ``.local/ts_migration_audit/raw/reciters/<slug>/timestamps``). Reports, per
    shard: shape classification, segment count before/after, byte-size delta, and
    any reshape error.
  - **delete-list the stale shadowed uncompressed ``.json``** — for any
    ``<chapter>.json`` that sits next to a live ``<chapter>.json.gz`` it is dead
    (the read path serves only the ``.gz``). The list is REPORTED, not executed —
    bucket deletion is a deferred, coordinated step (a separate workstream).
  - ``--out-dir`` optionally writes the reshaped ``.gz`` shards to a LOCAL
    directory for inspection / verification. It is never the source dir and never
    a bucket.

The actual bucket reshape/write/delete is a deferred coordinated cutover and is
deliberately NOT implemented here.
"""

from __future__ import annotations

import argparse
import gzip
import sys
from dataclasses import dataclass, field
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import orjson  # noqa: E402

from qua_shared.timestamps_reshape import (  # noqa: E402
    classify_shard,
    reshape_shard,
)
from qua_shared.timestamps_shards import gzip_shard  # noqa: E402


@dataclass
class ShardOutcome:
    """Per-shard reshape outcome for the dry-run report."""

    path: Path
    chapter: str
    kind: str
    in_segs: int = 0
    out_segs: int = 0
    in_bytes: int = 0
    out_bytes: int = 0
    error: str | None = None
    skipped: bool = False


@dataclass
class RunReport:
    """Aggregate report for one ``--src-dir`` run."""

    outcomes: list[ShardOutcome] = field(default_factory=list)
    stale_json: list[Path] = field(default_factory=list)


def _load_shard(path: Path) -> dict:
    """Load a shard document from a ``.json.gz`` or ``.json`` file."""
    raw = path.read_bytes()
    if path.suffix == ".gz" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return orjson.loads(raw)


def _chapter_of(path: Path) -> str:
    """``2.json.gz`` / ``2.json`` → ``"2"``. Stem strips one suffix only."""
    name = path.name
    for suffix in (".json.gz", ".json"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


def _count_segments(shard: dict) -> int:
    """Segment count for a TARGET shard, else 0."""
    segs = shard.get("segments")
    return len(segs) if isinstance(segs, list) else 0


def plan_directory(src_dir: Path, *, out_dir: Path | None = None) -> RunReport:
    """Dry-run the reshape over every ``.json.gz`` shard in ``src_dir``.

    For each ``<chapter>.json.gz`` shard: classify it, and if it is a v2
    occurrence-list, reshape it and record the segment count + byte deltas. When
    ``out_dir`` is given the reshaped ``.gz`` is written there (LOCAL only).

    Also collects the delete-list: any ``<chapter>.json`` shadowed by a sibling
    ``<chapter>.json.gz`` (dead — never read). Reported, never executed here.
    """
    report = RunReport()

    gz_shards = sorted(src_dir.glob("*.json.gz"), key=lambda p: _natural(p))
    gz_chapters = {_chapter_of(p) for p in gz_shards}

    for path in gz_shards:
        chapter = _chapter_of(path)
        outcome = ShardOutcome(path=path, chapter=chapter, kind="?", in_bytes=path.stat().st_size)
        try:
            shard = _load_shard(path)
        except Exception as exc:  # noqa: BLE001 — report, don't crash the batch
            outcome.error = f"load failed: {exc}"
            report.outcomes.append(outcome)
            continue

        outcome.kind = classify_shard(shard)
        if outcome.kind == "target":
            outcome.skipped = True
            outcome.out_segs = _count_segments(shard)
            report.outcomes.append(outcome)
            continue
        if outcome.kind in ("v1", "empty"):
            outcome.skipped = True
            outcome.error = f"unhandled shape ({outcome.kind}); left untouched"
            report.outcomes.append(outcome)
            continue

        outcome.in_segs = sum(
            len(v) for k, v in shard.items() if k != "_meta" and isinstance(v, list)
        )
        try:
            reshaped = reshape_shard(shard)
        except Exception as exc:  # noqa: BLE001 — surface per-shard, keep going
            outcome.error = f"reshape failed: {exc}"
            report.outcomes.append(outcome)
            continue

        outcome.out_segs = _count_segments(reshaped)
        payload = gzip_shard(reshaped)
        outcome.out_bytes = len(payload)
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{chapter}.json.gz").write_bytes(payload)
        report.outcomes.append(outcome)

    # Stale shadowed uncompressed shards: <chapter>.json next to <chapter>.json.gz.
    for path in sorted(src_dir.glob("*.json"), key=lambda p: _natural(p)):
        if path.name.endswith(".json.gz"):
            continue
        if _chapter_of(path) in gz_chapters:
            report.stale_json.append(path)

    return report


def _natural(path: Path) -> tuple[int, str]:
    """Sort ``<n>.json[.gz]`` numerically (``2`` before ``10``)."""
    chapter = _chapter_of(path)
    return (int(chapter), "") if chapter.isdigit() else (1 << 30, chapter)


def _print_report(report: RunReport, src_dir: Path, *, wrote: bool) -> None:
    """Human-readable dry-run summary to stdout."""
    print(f"src: {src_dir}")
    print(
        f"{'chapter':>8}  {'shape':<8}  {'in_seg':>7}  {'out_seg':>7}  "
        f"{'in_kb':>8}  {'out_kb':>8}  {'Δ%':>6}  note"
    )
    n_reshape = n_skip = n_err = 0
    for o in report.outcomes:
        if o.error and not o.skipped:
            n_err += 1
        elif o.skipped:
            n_skip += 1
        else:
            n_reshape += 1
        delta = ""
        if o.in_bytes and o.out_bytes:
            delta = f"{(o.out_bytes - o.in_bytes) / o.in_bytes * 100:+.1f}"
        note = o.error or ("already target" if o.kind == "target" else "")
        print(
            f"{o.chapter:>8}  {o.kind:<8}  {o.in_segs:>7}  {o.out_segs:>7}  "
            f"{o.in_bytes / 1024:>8.1f}  {o.out_bytes / 1024:>8.1f}  "
            f"{delta:>6}  {note}"
        )

    print()
    print(
        f"shards: {len(report.outcomes)}  reshaped: {n_reshape}  skipped: {n_skip}  errors: {n_err}"
    )
    if report.stale_json:
        print()
        print(
            f"DELETE-LIST — {len(report.stale_json)} stale shadowed .json "
            "(report only; bucket deletion is a deferred coordinated step):"
        )
        for p in report.stale_json:
            print(f"  rm  {p.name}")
    if wrote:
        print("\n(wrote reshaped .gz shards to --out-dir; bucket untouched)")
    else:
        print("\n(dry-run: no files written; bucket untouched)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run reshape v2 occurrence-list timestamps shards into "
        "the segment-array shape (LOCAL only; never writes the bucket)."
    )
    parser.add_argument(
        "--src-dir",
        type=Path,
        required=True,
        help="Local directory of <chapter>.json.gz shards (e.g. a synced mirror "
        "or .local/ts_migration_audit/raw/reciters/<slug>/timestamps).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Optional LOCAL directory to write reshaped .gz shards for "
        "inspection. Omit for a pure dry-run (no writes).",
    )
    args = parser.parse_args(argv)

    if not args.src_dir.is_dir():
        print(f"error: --src-dir {args.src_dir} is not a directory", file=sys.stderr)
        return 2
    if args.out_dir is not None and args.out_dir.resolve() == args.src_dir.resolve():
        print("error: --out-dir must differ from --src-dir (no in-place writes)", file=sys.stderr)
        return 2

    report = plan_directory(args.src_dir, out_dir=args.out_dir)
    if not report.outcomes:
        print(f"no .json.gz shards found in {args.src_dir}", file=sys.stderr)
        return 1

    _print_report(report, args.src_dir, wrote=args.out_dir is not None)
    has_errors = any(o.error and not o.skipped for o in report.outcomes)
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
