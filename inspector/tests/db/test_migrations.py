"""Migration runner — discovery + the duplicate-number guard.

A reused ``NNNN`` number is the bug that shipped ``0019_automation`` against live
DBs already at ``user_version=19`` (from ``0019_notifications``): version-gated
runners silently skip the second one forever. These lock the guard + assert the
shipped set is collision-free.
"""

from __future__ import annotations

import pytest

from services.db import migrate


def test_no_duplicate_migration_numbers_in_repo():
    """Every shipped migration has a unique number (else one is silently skipped
    on any DB already past that version)."""
    numbers = [n for (n, _p) in migrate._discover()]
    dupes = {n for n in numbers if numbers.count(n) > 1}
    assert not dupes, f"duplicate migration numbers: {sorted(dupes)}"


def test_discover_raises_on_duplicate_number(tmp_path, monkeypatch):
    (tmp_path / "0007_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "0007_second.sql").write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(migrate, "_MIGRATIONS_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="duplicate migration number 0007"):
        migrate._discover()
