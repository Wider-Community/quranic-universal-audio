"""Regenerate ``inspector/tests/fixtures/segments/expected/*.classify.json``.

Run after Phase 2 lands the unified classifier:

    python -m inspector.tests.parity.snapshot_expected_outputs

Reads every fixture under ``inspector/tests/fixtures/segments/``, classifies
via the backend's unified classifier, and writes the per-segment categories
+ category counts to ``expected/<fixture>.classify.json``. Idempotent.

Pre-Phase-2 the script raises ``ImportError`` because the unified classifier
module does not yet exist; that is intentional — the snapshot is regenerated
as part of the Phase 2 commit.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "segments"
EXPECTED_DIR = FIXTURES_DIR / "expected"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.detailed.json").read_text(encoding="utf-8"))


def _classify_fixture(fixture: dict) -> dict:
    """Drive the unified classifier across every entry in a fixture.

    Imports are local so that this module can be imported pre-Phase-2 without
    raising at import-time.
    """
    from services.validation.classifier import classify_entry  # type: ignore

    by_uid: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for entry in fixture.get("entries", []):
        results = classify_entry(entry)
        for uid, info in results.items():
            by_uid[uid] = info
            for cat in info.get("categories", []):
                counts[cat] = counts.get(cat, 0) + 1

    return {"by_segment_uid": by_uid, "category_counts": counts}


def regenerate(name: str) -> Path:
    fixture = _load_fixture(name)
    out = _classify_fixture(fixture)
    out["_meta"] = {
        "fixture": name,
        "generator": "inspector.tests.parity.snapshot_expected_outputs",
        "policy": "post-Phase-2 unified classifier",
    }
    out_path = EXPECTED_DIR / f"{name}.classify.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    fixtures = argv or [
        "112-ikhlas",
        "113-falaq",
        "synthetic-structural",
        "synthetic-classifier",
    ]
    for name in fixtures:
        path = regenerate(name)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
