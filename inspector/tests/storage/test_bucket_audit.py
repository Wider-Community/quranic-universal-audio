"""Unit tests for the bucket-artefact audit engine.

Exercises ``services.storage.bucket_audit.audit`` against a bucket-shaped
``reciters/<slug>/`` directory built under ``tmp_path`` and read through a
real ``FilesystemBackend``. No network — the committed segments fixtures
(``inspector/tests/fixtures/segments/``) supply the artefact bodies.

Two scenarios:
  - a *clean* reciter folder parses with zero legacy strips / zero warnings;
  - a *legacy* reciter folder (the fixture ``edit_history.jsonl`` carries
    pre-migration ``EditHistoryBatch`` / ``EditOperation`` keys) parses ``ok``
    but surfaces the INFO-level legacy-field strips from the schema extras
    pre-validator, on both the ``FileResult.n_info`` count and ``caplog``.
"""

from __future__ import annotations

import base64
import gzip
import json
import logging

import pytest

from services.storage.bucket_audit import (
    _sample_slugs,
    audit,
    sample_validation,
)
from services.storage.hf_bucket import FilesystemBackend
from tests.conftest import FIXTURES_DIR

SLUG = "fixture_reciter"

# Seg-level keys that the DetailedSegment schema treats as legacy (DEAD_FIELDS)
# and strips at INFO. The fixture carries some of these; the clean variant
# drops them so it parses with zero strips.
_SEG_DEAD = {
    "matched_text",
    "phonemes_asr",
    "has_repeated_words",
    "audio_url",
    "chapter",
    "entry_ref",
    "index_at_save",
    "display_text",
}


def _clean_detailed(fixture: dict) -> dict:
    """Strip the fixture-only + legacy keys so the doc parses cleanly."""
    doc = json.loads(json.dumps(fixture))  # deep copy
    doc.pop("_fixture_meta", None)
    for entry in doc.get("entries", []):
        entry.pop("audio", None)  # _ENTRY_DEAD_FIELDS
        for seg in entry.get("segments", []):
            for k in _SEG_DEAD:
                seg.pop(k, None)
    return doc


def _v3_peaks_gz() -> bytes:
    """A minimal valid v3 slim peaks blob (gzip(JSON))."""
    doc = {
        "schema_version": 3,
        "duration_ms": 5000,
        "q": "int8",
        "bps": 8,
        "n": 2,
        "peaks_b64": base64.b64encode(bytes([0, 10, 251, 7])).decode("ascii"),
    }
    return gzip.compress(json.dumps(doc).encode("utf-8"))


def _legacy_edit_history_bytes() -> bytes:
    """Read the committed fixture edit_history.jsonl as raw bytes.

    The fixture carries pre-migration ``EditHistoryBatch`` / ``EditOperation``
    keys that the schema strips at INFO — a natural legacy artefact.
    """
    return (FIXTURES_DIR / "112-ikhlas.edit_history.jsonl").read_bytes()


def _build_reciter_dir(backend: FilesystemBackend, detailed: dict, *, edit_history: bytes) -> None:
    """Populate ``reciters/<SLUG>/`` with a full, parity-balanced artefact set."""
    base = f"reciters/{SLUG}"
    backend.write_bytes_atomic(f"{base}/detailed.json", json.dumps(detailed).encode("utf-8"))

    # segments.json — structural shape: verse-keyed lists of int rows.
    segments = {
        "_meta": {"audio_source": "by_surah/fixture"},
        "112:1": [[0, 3, 0, 1500], [3, 6, 1500, 3000]],
    }
    backend.write_bytes_atomic(f"{base}/segments.json", json.dumps(segments).encode("utf-8"))

    backend.write_bytes_atomic(f"{base}/edit_history.jsonl", edit_history)

    pipeline_meta = {
        "schema_version": 1,
        "generated_at": "2026-01-01T00:00:00Z",
        "deleted_basmala_chapters": [],
    }
    backend.write_bytes_atomic(
        f"{base}/pipeline_meta.json", json.dumps(pipeline_meta).encode("utf-8")
    )

    # One chapter of audio + peaks, kept in parity (1 mp3, 1 json.gz).
    backend.write_bytes_atomic(f"{base}/audio/112.mp3", b"\xff\xfb" + b"\x00" * 4096)
    backend.write_bytes_atomic(f"{base}/peaks/112.json.gz", _v3_peaks_gz())


@pytest.fixture
def backend(tmp_path):
    """A FilesystemBackend rooted at a fresh tmp dir (bucket-shaped layout)."""
    return FilesystemBackend(tmp_path)


def test_missing_reciter_reports_not_found(backend):
    result = audit(backend, "test-bucket", "does_not_exist")

    assert result.found is False
    assert result.n_errors == 0
    assert result.files[0].status == "missing"


def test_clean_reciter_audits_ok_with_no_strips(backend, load_fixture):
    clean = _clean_detailed(load_fixture("112-ikhlas"))
    # A clean edit_history.jsonl: an empty file is valid (0/0 batches, ok).
    _build_reciter_dir(backend, clean, edit_history=b"")

    result = audit(backend, "test-bucket", SLUG)

    assert result.found is True
    assert result.n_errors == 0, [f"{f.path}: {f.detail}" for f in result.files if f.status == "error"]
    assert result.n_legacy == 0
    assert result.n_warnings == 0

    by_path = {f.path: f for f in result.files}
    detailed = by_path[f"reciters/{SLUG}/detailed.json"]
    assert detailed.status == "ok"
    assert detailed.n_info == 0
    assert detailed.n_warn == 0
    assert detailed.items_total == 4  # the fixture has 4 segments

    # audio/peaks parity row present and ok.
    parity = by_path[f"reciters/{SLUG}/(audio|peaks)/"]
    assert parity.status == "ok"
    assert parity.items_ok == 1


def test_legacy_edit_history_strips_surface_as_info(backend, load_fixture, caplog):
    clean = _clean_detailed(load_fixture("112-ikhlas"))
    # The fixture edit_history carries pre-migration EditHistoryBatch /
    # EditOperation keys (file_hash_after, save_mode, type, patch, ...) that
    # the schema strips at INFO.
    _build_reciter_dir(backend, clean, edit_history=_legacy_edit_history_bytes())

    with caplog.at_level(logging.INFO, logger="qua_shared.schemas._extras"):
        result = audit(backend, "test-bucket", SLUG)

    assert result.found is True
    assert result.n_errors == 0, [f"{f.path}: {f.detail}" for f in result.files if f.status == "error"]

    by_path = {f.path: f for f in result.files}
    eh = by_path[f"reciters/{SLUG}/edit_history.jsonl"]
    assert eh.status == "ok"
    assert eh.items_ok == 1  # one batch parsed
    assert eh.n_info > 0  # legacy strips counted on the FileResult
    assert eh.n_warn == 0  # nothing unrecognized — only known-legacy keys

    # The INFO strip also reaches the standard logging surface.
    info_msgs = [
        r.getMessage()
        for r in caplog.records
        if r.name == "qua_shared.schemas._extras" and r.levelno == logging.INFO
    ]
    assert any("stripped legacy field" in m for m in info_msgs)


# ---------------------------------------------------------------------------
# sample_validation — the cheap /healthz?deep=1 drift probe
# ---------------------------------------------------------------------------


def test_sample_slugs_spreads_across_sorted_list():
    # 3-of-10 must hit first + last, not just the first three alphabetically.
    slugs = [f"r{i:02d}" for i in range(10)]
    assert _sample_slugs(slugs, 3) == ["r00", "r04", "r09"]
    # Fewer slugs than the cap returns them all (sorted).
    assert _sample_slugs(["b", "a"], 3) == ["a", "b"]
    # A zero cap walks nothing.
    assert _sample_slugs(slugs, 0) == []


def test_sample_validation_clean_reciter_is_ok(backend, load_fixture):
    clean = _clean_detailed(load_fixture("112-ikhlas"))
    _build_reciter_dir(backend, clean, edit_history=b"")

    out = sample_validation(backend=backend, bucket_id="test-bucket", slugs=[SLUG])

    assert out["ok"] is True
    assert out["catalog_ok"] is True  # autouse DB has a clean reciter-less catalog
    assert out["sampled"] == [SLUG]
    assert out["n_reciters"] == 1
    assert out["errors"] == []


def test_sample_validation_surfaces_drifted_reciter(backend, load_fixture):
    clean = _clean_detailed(load_fixture("112-ikhlas"))
    _build_reciter_dir(backend, clean, edit_history=b"")
    # Corrupt detailed.json so the schema audit fails → the probe must report it.
    backend.write_bytes_atomic(f"reciters/{SLUG}/detailed.json", b"{not json")

    out = sample_validation(backend=backend, bucket_id="test-bucket", slugs=[SLUG])

    assert out["ok"] is False
    assert out["sampled"] == [SLUG]
    assert any("detailed.json" in e for e in out["errors"])


def test_sample_validation_caps_the_walk(backend, load_fixture):
    clean = _clean_detailed(load_fixture("112-ikhlas"))
    # Build five reciter folders; the default cap walks only three of them.
    slugs = [f"r{i}" for i in range(5)]
    for slug in slugs:
        base = f"reciters/{slug}"
        backend.write_bytes_atomic(f"{base}/detailed.json", json.dumps(clean).encode("utf-8"))

    out = sample_validation(backend=backend, bucket_id="test-bucket", slugs=slugs, limit=3)

    assert out["n_reciters"] == 5
    assert len(out["sampled"]) == 3
    assert out["sampled"] == ["r0", "r2", "r4"]
