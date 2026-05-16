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
import os
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


@pytest.fixture
def signed_in_client(monkeypatch):
    """Factory returning a Flask test client that carries a signed identity cookie.

    Usage::

        def test_x(signed_in_client):
            client, user = signed_in_client(role="contributor")
            resp = client.post("/api/claim/foo", headers={"Origin": "http://localhost"})

    The fixture:
    - Ensures ``INSPECTOR_SESSION_SECRET`` is set (auto-seeded if absent).
    - Seeds the ``access`` store with the requested role for the user.
    - Mints a signed cookie via ``auth_service.encode_session`` and attaches
      it to the test client.
    - Returns ``(client, user_dict)`` where ``user_dict`` carries
      ``{hf_user_id, login, role}`` for assertions in the test.
    """
    import secrets

    if not os.environ.get("INSPECTOR_SESSION_SECRET"):
        monkeypatch.setenv("INSPECTOR_SESSION_SECRET", secrets.token_hex(32))

    from datetime import datetime, timezone

    from scripts.lib.schemas import Member, Role, RolesFile

    from app import app
    from services import access as access_service
    from services import auth as auth_service

    app.config["TESTING"] = True

    def _make(
        *,
        hf_user_id: str = "test-user-1",
        login: str = "test_user",
        role: str = "contributor",
    ):
        # Seed the access store. CONTRIBUTOR is the implicit default — no
        # member row needed; resolve_role returns CONTRIBUTOR for unknown ids.
        if role != "contributor":
            now = datetime.now(timezone.utc)
            roles_file = RolesFile(
                members=[
                    Member(
                        hf_user_id=hf_user_id,
                        login=login,
                        role=Role(role),
                        added_at=now,
                        added_by_hf_id="test-seed",
                    )
                ]
            )
            # Replace the in-memory store directly (bypasses the bucket).
            with access_service._store_lock:  # type: ignore[attr-defined]
                access_service._store = roles_file  # type: ignore[attr-defined]
        else:
            with access_service._store_lock:  # type: ignore[attr-defined]
                access_service._store = RolesFile()  # type: ignore[attr-defined]

        client = app.test_client()
        cookie = auth_service.encode_session(login=login, hf_user_id=hf_user_id)
        client.set_cookie(
            auth_service.SESSION_COOKIE_NAME,
            cookie,
            path="/",
        )
        return client, {"hf_user_id": hf_user_id, "login": login, "role": role}

    yield _make

    # Teardown: clear the access store so subsequent tests start clean.
    with access_service._store_lock:  # type: ignore[attr-defined]
        access_service._store = RolesFile()  # type: ignore[attr-defined]


@pytest.fixture
def state_persistence(tmp_path, monkeypatch):
    """Per-test FilesystemBackend so state mutations persist across requests.

    Replaces the legacy `_stub_persist` pattern (which mocked
    `state._persist_row` to a no-op): instead of forcing tests to manually
    `_replace_state(...)` between requests to simulate persistence, this
    fixture wires a real bucket backend rooted at a tmp dir. State
    transitions go through `_persist_row` for real — the in-memory
    `_state_file` global is updated AND the JSON is written to tmp_path.
    Subsequent GETs read the persisted state for free.

    Also re-hydrates the catalog + access stores against the empty backend
    so prior test bleed-through can't pin stale rows. Stubs `audit.append`
    so we don't write to the audit log per claim/release.

    Yields the FilesystemBackend so individual tests can inspect what
    landed on disk if needed.
    """
    from services import access as access_service
    from services import audit as audit_service
    from services import catalog as catalog_service
    from services import hf_bucket as _hf_bucket
    from services import state as state_service

    monkeypatch.setenv("INSPECTOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INSPECTOR_BACKEND", "filesystem")
    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))

    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)
    state_service.hydrate()
    catalog_service.hydrate()
    access_service.hydrate()

    monkeypatch.setattr(audit_service, "append", lambda **kw: None)

    yield backend

    _hf_bucket.reset_backend()


_SEG_CACHE_NAMES = (
    "_seg",
    "_seg_meta",
    "_seg_verses",
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

    def _install(
        reciter: str,
        fixture_name: str,
        *,
        under_review_for: str | None = None,
    ) -> Path:
        """Install a fixture under ``wip/<reciter>/`` and seed a state row.

        When ``under_review_for`` is given, the row is seeded as
        ``UNDER_REVIEW`` with that user as the active assignee — required
        for tests that POST to lock-gated routes (save/undo). Default
        ``AWAITING_REVIEW`` keeps existing tests unchanged.
        """
        # Seed a state row so data_dir.kind_for(reciter) returns "wip".
        rows = list(_state_service.snapshot().reciters)
        if not any(r.slug == reciter for r in rows):
            now = datetime.now(timezone.utc)
            if under_review_for is None:
                row = ReciterRow(
                    slug=reciter,
                    state=ReciterState.AWAITING_REVIEW,
                    state_since=now,
                )
            else:
                row = ReciterRow(
                    slug=reciter,
                    state=ReciterState.UNDER_REVIEW,
                    state_since=now,
                    assignee_hf_id=under_review_for,
                    assignee_login="test_user",
                    assignee_since=now,
                )
            rows.append(row)
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

    def _seed_under_review(reciter: str, hf_user_id: str) -> None:
        """Seed an UNDER_REVIEW state row for ``reciter`` with ``hf_user_id``
        as the assignee, without copying a fixture. Used by tests that
        hand-author their own ``detailed.json`` and just need the lock
        decorator to pass."""
        now = datetime.now(timezone.utc)
        rows = [
            r for r in _state_service.snapshot().reciters
            if r.slug != reciter
        ]
        rows.append(
            ReciterRow(
                slug=reciter,
                state=ReciterState.UNDER_REVIEW,
                state_since=now,
                assignee_hf_id=hf_user_id,
                assignee_login="test_user",
                assignee_since=now,
            )
        )
        backend.write_json_atomic(
            _storage_paths.state_path(),
            ReciterStateFile(reciters=rows).model_dump(mode="json"),
        )
        _state_service.hydrate()

    yield type("TmpReciter", (), {
        "root": tmp_path / "wip",
        "install": staticmethod(_install),
        "seed_under_review": staticmethod(_seed_under_review),
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
