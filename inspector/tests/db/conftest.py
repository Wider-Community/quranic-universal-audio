"""Shared fixtures for the SQLite-substrate test package."""

from __future__ import annotations

import pytest

from services import db


@pytest.fixture
def fresh_db(tmp_path):
    """A migrated, empty SQLite DB on a temp file. Reset after the test."""
    db.set_db_path_for_test(tmp_path / "test.db")
    db.init_db()
    yield
    db.reset()
