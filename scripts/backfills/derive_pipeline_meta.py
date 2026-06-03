"""Derive ``pipeline_meta.json`` for a slug's local folder.

Two derivation paths:

1. **New pipeline (Migration #5+):** every ``strip_specials`` op snapshot
   carries a ``chapter`` stamp. Walk the snapshots, collect chapters
   where ``matched_ref`` is in the Basmala-class set. Same as
   ``qua_shared.pipeline_meta.collect_deleted_basmalas``.

2. **Legacy fallback:** if every op snapshot is missing ``chapter`` (the
   pre-#5 writer didn't stamp it), walk ops in order pairing each
   Basmala-class op with the next chapter from ``batch.chapters[]``.
   Works because the strip_specials post-pass emits ops in chapter +
   time order, and within each chapter the Basmala-class strip is the
   chapter's last op (Isti'adha precedes Basmala in audio).

Usage::

    python3 scripts/backfills/derive_pipeline_meta.py --dir /tmp/<slug>/

Writes ``<dir>/pipeline_meta.json``. Idempotent — re-running on the same
data emits a byte-equal sidecar modulo ``generated_at``.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("derive_pipeline_meta")

_BASMALA_REFS = {"Basmala", "Isti'adha+Basmala"}


def _setup_paths() -> None:
    here = Path(__file__).resolve()
    repo = here.parents[2]
    sys.path.insert(0, str(repo))


def _has_chapter_stamps(batch: dict) -> bool:
    """True iff every strip-op snapshot has a non-null chapter stamp."""
    if batch.get("batch_type") != "strip_specials":
        return True  # not relevant
    for op in batch.get("operations") or []:
        snap = (op.get("targets_before") or [{}])[0]
        if snap.get("chapter") is None:
            return False
    return True


def _collect_new_pipeline(batches: list[dict]) -> set[int]:
    """Snapshot-stamp path — same logic as
    ``qua_shared.pipeline_meta.collect_deleted_basmalas``."""
    from qua_shared.pipeline_meta import collect_deleted_basmalas
    return collect_deleted_basmalas(batches)


def _collect_legacy(batches: list[dict]) -> set[int]:
    """Op-order recovery for legacy data (chapter=null on snapshots)."""
    out: set[int] = set()
    for b in batches:
        if b.get("batch_type") != "strip_specials":
            continue
        chs = list(b.get("chapters") or [])
        if not chs:
            continue
        chap_iter = iter(chs)
        current = next(chap_iter, None)
        for op in b.get("operations") or []:
            snap = (op.get("targets_before") or [{}])[0]
            ref = snap.get("matched_ref")
            if ref in _BASMALA_REFS:
                if current is not None:
                    out.add(current)
                current = next(chap_iter, None)
    return out


def derive(slug_dir: Path) -> dict:
    from qua_shared.schemas import PipelineMeta, parse_edit_history_line

    history_path = slug_dir / "edit_history.jsonl"
    if not history_path.is_file():
        raise SystemExit(f"missing: {history_path}")

    batches: list[dict] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        b = parse_edit_history_line(line)
        if b is not None:
            batches.append(b.model_dump())

    # Pick the path: new pipeline if any strip_specials batch has chapter
    # stamps, else fall back to legacy op-order walk.
    strip_batches = [b for b in batches if b.get("batch_type") == "strip_specials"]
    use_new = bool(strip_batches) and all(_has_chapter_stamps(b) for b in strip_batches)
    if use_new:
        deleted = _collect_new_pipeline(batches)
        log.info("Path: NEW pipeline (snapshots stamped); %d chapters", len(deleted))
    else:
        deleted = _collect_legacy(batches)
        log.info("Path: LEGACY op-order recovery; %d chapters", len(deleted))

    payload = PipelineMeta(
        schema_version=1,
        generated_at=datetime.now(timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"),
        deleted_basmala_chapters=sorted(deleted),
    ).model_dump(mode="json")
    out_path = slug_dir / "pipeline_meta.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    log.info("Wrote %s (%d chapters)", out_path, len(deleted))
    return {"path": "new" if use_new else "legacy",
            "deleted_basmala_chapters": sorted(deleted)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dir", type=Path, required=True,
                    help="Slug folder (must contain edit_history.jsonl).")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _setup_paths()
    if not args.dir.is_dir():
        raise SystemExit(f"not a directory: {args.dir}")
    result = derive(args.dir)
    log.info("DONE: %s", {k: (v[:8] if isinstance(v, list) and len(v) > 8 else v)
                          for k, v in result.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
