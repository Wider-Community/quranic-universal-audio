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


# Category lists derive from ``services.validation.registry.IssueRegistry``
# in registry-declared accordion order (Appendix A). The fallback literals
# match the registry verbatim so the module remains importable even before
# the validation package is available on ``sys.path``.
try:
    from services.validation.registry import (  # type: ignore
        ALL_CATEGORIES as _REG_ALL,
        PER_SEGMENT_CATEGORIES as _REG_SEG,
        PER_VERSE_CATEGORIES as _REG_VERSE,
        PER_CHAPTER_CATEGORIES as _REG_CHAPTER,
        CAN_IGNORE_CATEGORIES as _REG_CAN,
        PERSISTS_IGNORE_CATEGORIES as _REG_PERSIST,
        AUTO_SUPPRESS_CATEGORIES as _REG_AUTO,
    )
    ALL_CATEGORIES = list(_REG_ALL)
    PER_SEGMENT_CATEGORIES = list(_REG_SEG)
    PER_VERSE_CATEGORIES = list(_REG_VERSE)
    PER_CHAPTER_CATEGORIES = list(_REG_CHAPTER)
    CAN_IGNORE_CATEGORIES = list(_REG_CAN)
    PERSISTS_IGNORE_CATEGORIES = list(_REG_PERSIST)
    AUTO_SUPPRESS_CATEGORIES = list(_REG_AUTO)
except Exception:
    ALL_CATEGORIES = [
        "failed", "missing_verses", "missing_words", "structural_errors",
        "low_confidence", "repetitions", "audio_bleeding", "boundary_adj",
        "cross_verse", "qalqala", "muqattaat",
    ]
    PER_SEGMENT_CATEGORIES = [
        "failed", "low_confidence", "repetitions", "audio_bleeding",
        "boundary_adj", "cross_verse", "qalqala", "muqattaat",
    ]
    PER_VERSE_CATEGORIES = ["missing_verses", "missing_words"]
    PER_CHAPTER_CATEGORIES = ["structural_errors"]
    CAN_IGNORE_CATEGORIES = [
        "low_confidence", "repetitions", "audio_bleeding", "boundary_adj",
        "cross_verse",
    ]
    PERSISTS_IGNORE_CATEGORIES = list(CAN_IGNORE_CATEGORIES)
    AUTO_SUPPRESS_CATEGORIES = [
        "failed", "missing_verses", "structural_errors", "low_confidence",
        "repetitions", "audio_bleeding", "boundary_adj", "cross_verse",
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
    """Per-test writable bucket-shape directory rooted under ``tmp_path``.

    Installs a ``FilesystemBackend`` against ``tmp_path`` (v2 backend
    abstraction), so routes/services/loaders read + write under the temp
    dir instead of the real bucket. The on-disk layout matches the bucket
    layout (``wip/<slug>/segments.json``, etc.); the ``install`` helper
    drops fixtures there and seeds the state file so ``data_dir.kind_for``
    returns ``"wip"`` for installed reciters.
    """
    from datetime import datetime, timezone

    from scripts.lib.schemas import ReciterRow, ReciterState, ReciterStateFile

    from services import hf_bucket as _hf_bucket
    from services import state as _state_service
    from services import access as _access_service
    from services import catalog as _catalog_service
    from services import storage_paths as _storage_paths

    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path))
    # Local-write gate stays open in tests — fixtures need to exercise the
    # save flow without touching INSPECTOR_LOCAL_WRITES.
    monkeypatch.setenv("INSPECTOR_BACKEND", "filesystem")
    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))

    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)

    # Rehydrate the in-memory services against the fresh empty backend so
    # the previous test's state doesn't leak across.
    _state_service.hydrate()
    _catalog_service.hydrate()
    _access_service.hydrate()

    _invalidate_seg_caches()

    def _install(reciter: str, fixture_name: str) -> Path:
        # Seed a state row so data_dir.kind_for(reciter) returns "wip".
        rows = list(_state_service.snapshot().reciters)
        if not any(r.slug == reciter for r in rows):
            rows.append(
                ReciterRow(
                    slug=reciter,
                    state=ReciterState.AWAITING_REVIEW,
                    state_since=datetime.now(timezone.utc),
                )
            )
            backend.write_json_atomic(
                _storage_paths.state_path(),
                ReciterStateFile(reciters=rows).model_dump(mode="json"),
            )
            _state_service.hydrate()

        # Install fixture file at wip/<reciter>/detailed.json
        src = FIXTURES_DIR / f"{fixture_name}.detailed.json"
        detailed_rel = _storage_paths.detailed_path(reciter, "wip")
        with open(src, "rb") as f:
            backend.write_bytes_atomic(detailed_rel, f.read())
        dst_path = (tmp_path / detailed_rel).resolve()

        history_src = FIXTURES_DIR / f"{fixture_name}.edit_history.jsonl"
        if history_src.exists():
            with open(history_src, "rb") as f:
                backend.write_bytes_atomic(
                    _storage_paths.edit_history_path(reciter, "wip"),
                    f.read(),
                )

        # Build a matching segments.json so consumers that read both files
        # see a consistent on-disk state for the fixture.
        try:
            from services.save import rebuild_segments_json  # type: ignore
        except ImportError:
            rebuild_segments_json = None  # type: ignore[assignment]
        if rebuild_segments_json is not None:
            doc = json.loads((tmp_path / detailed_rel).read_bytes())
            entries = doc.get("entries", [])
            meta = doc.get("_meta", {})
            seg_rel = _storage_paths.segments_path(reciter, "wip")
            if not backend.exists(seg_rel):
                backend.write_json_atomic(seg_rel, {"_meta": meta})
            rebuild_segments_json(reciter, entries)
            # Re-stamp meta if rebuild dropped it.
            seg_doc = backend.read_json(seg_rel)
            if not seg_doc.get("_meta"):
                seg_doc["_meta"] = meta
                backend.write_json_atomic(seg_rel, seg_doc)

        _invalidate_seg_caches()
        return dst_path

    yield type("TmpReciter", (), {
        "root": tmp_path / "wip",
        "install": staticmethod(_install),
        "data_dir": tmp_path,
        "backend": backend,
    })

    # Drop the backend singleton at teardown so the next test re-installs fresh.
    _hf_bucket.reset_backend()


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
