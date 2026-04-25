"""Shared pytest fixtures for the inspector test suite.

The Flask app in ``inspector/app.py`` is constructed at module import time
(module-level ``app = Flask(...)``), not via a factory. Tests that need a
client spin one up via ``app.test_client()``.

This module also provides the helpers used by the segments-tab refactor
test suite:

- ``load_fixture`` reads a JSON fixture from
  ``inspector/tests/fixtures/segments/<name>.detailed.json``.
- ``load_expected`` reads a baseline from
  ``inspector/tests/fixtures/segments/expected/<name>.<kind>.json``.
- ``flask_client`` exposes the Flask test client.
- ``tmp_reciter_dir`` redirects the data path to a writable per-test
  directory and exposes an ``install`` helper to drop a fixture into
  ``<reciter>/detailed.json``.
- ``ALL_CATEGORIES`` enumerates the 11 validation categories. After
  Phase 1 lands the registry, this constant flips to read from
  ``inspector.services.validation.registry.IssueRegistry.keys()``.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "segments"
EXPECTED_DIR = FIXTURES_DIR / "expected"


# Placeholder until Phase 1 introduces the registry. Listed in registry-
# declared accordion order (Appendix A: failed, missing_verses, missing_words,
# structural_errors, low_confidence, repetitions, audio_bleeding, boundary_adj,
# cross_verse, qalqala, muqattaat).
ALL_CATEGORIES = [
    "failed",
    "missing_verses",
    "missing_words",
    "structural_errors",
    "low_confidence",
    "repetitions",
    "audio_bleeding",
    "boundary_adj",
    "cross_verse",
    "qalqala",
    "muqattaat",
]


PER_SEGMENT_CATEGORIES = [
    "failed",
    "low_confidence",
    "repetitions",
    "audio_bleeding",
    "boundary_adj",
    "cross_verse",
    "qalqala",
    "muqattaat",
]


PER_VERSE_CATEGORIES = ["missing_verses", "missing_words"]
PER_CHAPTER_CATEGORIES = ["structural_errors"]


CAN_IGNORE_CATEGORIES = [
    "low_confidence",
    "repetitions",
    "audio_bleeding",
    "boundary_adj",
    "cross_verse",
    "qalqala",
]


PERSISTS_IGNORE_CATEGORIES = list(CAN_IGNORE_CATEGORIES)


AUTO_SUPPRESS_CATEGORIES = [
    "failed",
    "missing_verses",
    "structural_errors",
    "low_confidence",
    "repetitions",
    "audio_bleeding",
    "boundary_adj",
    "cross_verse",
    "qalqala",
]


def _read_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def load_fixture():
    """Return a function that loads ``<name>.detailed.json`` from the fixtures dir."""
    def _loader(name: str) -> dict:
        path = FIXTURES_DIR / f"{name}.detailed.json"
        return _read_json(path)
    return _loader


@pytest.fixture
def load_expected():
    """Return a function that loads ``expected/<name>.<kind>.json``."""
    def _loader(name: str, kind: str) -> dict:
        path = EXPECTED_DIR / f"{name}.{kind}.json"
        return _read_json(path)
    return _loader


@pytest.fixture
def flask_client():
    """Flask test client over the module-level app in ``inspector/app.py``."""
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


def _modules_holding_seg_path() -> list[str]:
    """Modules that import ``RECITATION_SEGMENTS_PATH`` and need re-pointing."""
    return [
        "config",
        "routes.segments_data",
        "routes.segments_edit",
        "routes.segments_validation",
        "services.data_loader",
        "services.history_query",
        "services.save",
        "services.undo",
    ]


_SEG_CACHE_NAMES = (
    "_seg",
    "_seg_meta",
    "_seg_verses",
    "_seg_reciters",
)


def _invalidate_seg_caches(reciter: str | None = None):
    """Invalidate the segment-related caches that may pin pre-redirect data."""
    try:
        from services import cache as _cache
    except Exception:
        return
    for name in _SEG_CACHE_NAMES:
        obj = getattr(_cache, name, None)
        if obj is None:
            continue
        if hasattr(obj, "clear"):
            obj.clear()


@pytest.fixture
def tmp_reciter_dir(tmp_path, monkeypatch):
    """Per-test writable reciter directory rooted under ``tmp_path``.

    Repoints the captured ``RECITATION_SEGMENTS_PATH`` constant in every
    importing module so that routes, services, and data loaders read/write
    under ``tmp_path`` instead of the real data directory.
    """
    reciter_root = tmp_path / "recitation_segments"
    reciter_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path))

    # Force-refresh module-level path bindings.
    for name in _modules_holding_seg_path():
        if name in sys.modules:
            mod = sys.modules[name]
            if hasattr(mod, "RECITATION_SEGMENTS_PATH"):
                monkeypatch.setattr(mod, "RECITATION_SEGMENTS_PATH", reciter_root, raising=False)
            if hasattr(mod, "DATA_DIR"):
                monkeypatch.setattr(mod, "DATA_DIR", tmp_path, raising=False)

    _invalidate_seg_caches()

    def _install(reciter: str, fixture_name: str) -> Path:
        src = FIXTURES_DIR / f"{fixture_name}.detailed.json"
        dst_dir = reciter_root / reciter
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst_path = dst_dir / "detailed.json"
        shutil.copy(str(src), str(dst_path))
        _invalidate_seg_caches()
        return dst_path

    return type("TmpReciter", (), {
        "root": reciter_root,
        "install": staticmethod(_install),
        "data_dir": tmp_path,
    })


def assert_keys_superset(
    baseline_keys: list[str],
    response_keys: list[str],
    route_name: str,
) -> None:
    """Assert that *response_keys* is a superset of *baseline_keys* (MUST-1).

    Any key present in the baseline must remain present in the live response.
    New keys are allowed (additive-only contract); missing keys are failures.
    """
    missing = set(baseline_keys) - set(response_keys)
    assert not missing, (
        f"MUST-1 violation on {route_name!r}: "
        f"baseline keys no longer in response: {sorted(missing)!r}. "
        f"Baseline had {sorted(baseline_keys)!r}; "
        f"live response has {sorted(response_keys)!r}."
    )


@pytest.fixture
def fresh_registry():
    """Yield a snapshot of the issue registry, or ``None`` pre-Phase-1.

    Tests that parametrize over the registry use ``ALL_CATEGORIES`` until
    Phase 1 lands ``inspector.services.validation.registry``.
    """
    try:
        from services.validation.registry import IssueRegistry  # type: ignore
        return IssueRegistry
    except Exception:
        return None
