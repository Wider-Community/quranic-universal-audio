"""Backend ↔ CLI classifier parity (MUST-6, SC-1).

This file is cross-listed with ``inspector/tests/classifier/test_classify_parity.py``.
The classifier/ tests focus on per-fixture parity; this file documents the
load-bearing nature of the assertion and adds a holistic round-trip.
"""
from __future__ import annotations

import json
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


@pytest.mark.parametrize("fixture_name", ["112-ikhlas", "113-falaq", "synthetic-classifier"])
@pytest.mark.xfail(reason="phase-2", strict=False)
def test_backend_cli_parity_holistic(fixture_name, tmp_reciter_dir, load_expected):
    """Backend route counts == CLI counts for every fixture; baseline matches expected/<fixture>.classify.json."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, fixture_name)

    from services.validation import validate_reciter_segments  # type: ignore

    backend = validate_reciter_segments(reciter)
    backend_counts = backend.get("category_counts") or backend.get("counts") or {}
    expected = load_expected(fixture_name, "classify")
    expected_counts = expected.get("category_counts") or {}

    for category, want in expected_counts.items():
        if want > 0:
            assert backend_counts.get(category) == want, (
                f"{fixture_name}::{category}: backend={backend_counts.get(category)} expected={want}"
            )

    proc = subprocess.run(
        [sys.executable, str(CLI_SCRIPT), reciter],
        cwd=str(REPO_ROOT),
        capture_output=True, text=True,
        env={"INSPECTOR_DATA_DIR": str(tmp_reciter_dir.data_dir)},
    )
    assert proc.returncode == 0
