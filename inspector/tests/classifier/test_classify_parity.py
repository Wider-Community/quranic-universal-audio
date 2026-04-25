"""Backend ↔ CLI classifier parity tests (MUST-6, SC-1).

These tests assert that for the same fixture, the backend route and the CLI
``validators/validate_segments.py`` produce identical category counts and
sets after Phase 2 lands the unified classifier.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip(
    "services.validation.classifier",
    reason="phase-2 — unified classifier not yet introduced",
)


REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_SCRIPT = REPO_ROOT / "validators" / "validate_segments.py"


PARITY_FIXTURES = ["112-ikhlas", "113-falaq", "synthetic-classifier"]


@pytest.mark.parametrize("fixture_name", PARITY_FIXTURES, ids=PARITY_FIXTURES)
@pytest.mark.xfail(reason="phase-2", strict=False)
def test_backend_and_cli_classify_identically_per_fixture(
    fixture_name, load_fixture, tmp_reciter_dir
):
    reciter_slug = "fixture_reciter"
    tmp_reciter_dir.install(reciter_slug, fixture_name)

    from services.validation import validate_reciter_segments  # type: ignore

    backend_result = validate_reciter_segments(reciter_slug)
    assert backend_result is not None, "backend validation returned None"

    proc = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), reciter_slug],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env={"INSPECTOR_DATA_DIR": str(tmp_reciter_dir.data_dir)},
    )
    assert proc.returncode == 0, f"CLI failed: stdout={proc.stdout!r} stderr={proc.stderr!r}"

    backend_counts = backend_result.get("category_counts") or backend_result.get("counts") or {}
    cli_counts: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        for category in backend_counts:
            if category in line:
                token = line.split(category)[-1].strip().split()[0]
                if token.isdigit():
                    cli_counts[category] = int(token)

    for category, expected in backend_counts.items():
        actual = cli_counts.get(category, 0)
        assert actual == expected, (
            f"{fixture_name}::{category}: backend={expected} cli={actual}"
        )


@pytest.mark.xfail(reason="phase-2", strict=False)
def test_no_duplicate_helpers_in_cli():
    """Phase 2 deletes duplicated helpers from validators/validate_segments.py."""
    cli_text = CLI_SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "def _strip_diacritics",
        "def _last_arabic_letter",
        "def _is_ignored_for",
        "_MUQATTAAT_VERSES",
        "_QALQALA_LETTERS",
        "_STANDALONE_REFS",
        "_STANDALONE_WORDS",
    ]
    leaks = [name for name in forbidden if name in cli_text]
    assert not leaks, (
        f"validators/validate_segments.py still defines duplicated helpers: {leaks}. "
        "Phase 2 must replace these with imports from inspector.services.validation."
    )
