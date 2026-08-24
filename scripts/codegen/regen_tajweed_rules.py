#!/usr/bin/env python3
"""Regenerate the Inspector's native tajweed-rule catalogue.

The shard schema intentionally excludes presentation metadata.  This committed
asset carries only the producer-owned names and summaries; the Inspector's
grouping, colours, defaults, and underline policy remain in TypeScript.
"""

from __future__ import annotations

import json
from importlib.metadata import version
from pathlib import Path

from packaging.version import Version
from quranic_phonemizer import tajweed_rules

REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "inspector" / "frontend" / "src" / "tabs" / "timestamps" / "data" / "rules.json"
EXPECTED_PHONEMIZER = Version("2.15.0")
EXPECTED_RULE_COUNT = 45


def main() -> int:
    installed = Version(version("quranic-phonemizer"))
    if installed != EXPECTED_PHONEMIZER:
        raise SystemExit(f"quranic-phonemizer {EXPECTED_PHONEMIZER} required; found {installed}")

    rows = [
        {
            "id": rule_id,
            "name": name,
            "arabic_name": arabic_name,
            "summary": summary,
        }
        for rule_id, name, arabic_name, summary in tajweed_rules("hafs")
    ]
    ids = [row["id"] for row in rows]
    if len(rows) != EXPECTED_RULE_COUNT or len(set(ids)) != EXPECTED_RULE_COUNT:
        raise SystemExit(
            f"expected {EXPECTED_RULE_COUNT} unique producer rules; got {len(rows)} rows"
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {OUTPUT.relative_to(REPO)} ({len(rows)} rules)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
