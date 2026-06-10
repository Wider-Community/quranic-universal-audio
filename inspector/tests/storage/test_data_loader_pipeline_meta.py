"""``load_pipeline_meta`` degradation guard.

The sidecar is read on the hot ``/api/seg/validate`` path. Under pure
``extra="forbid"`` a single un-migrated or forward-compat field would make
``PipelineMeta.model_validate`` raise → HTTP 500 for the reciter's entire
validation view. ``load_pipeline_meta`` must instead degrade to the raw doc
and let the nightly bucket validator surface the drift.
"""

from __future__ import annotations

from services.storage import cache, data_loader


def test_pipeline_meta_with_forward_field_degrades_to_raw_doc(monkeypatch):
    """A sidecar carrying an unknown/forward field is served raw, not 500'd."""
    slug = "degrade_reciter"
    # Valid except for the one forward field — so the ONLY reason validation
    # raises is the unknown key (not a missing required field).
    doc = {
        "schema_version": 1,
        "generated_at": "2026-06-10T00:00:00Z",
        "deleted_basmala_chapters": [1, 9],
        "some_future_field": {"added_by": "a newer extractor"},
    }
    monkeypatch.setattr(data_loader.data_dir, "read_pipeline_meta_doc", lambda r: doc)
    cache.pop_seg_pipeline_meta(slug)

    result = data_loader.load_pipeline_meta(slug)

    # Degraded to the raw doc — the forward field (which a validated model_dump
    # would have rejected) survives, proving the guard fired instead of 500ing.
    assert result is not None
    assert result["deleted_basmala_chapters"] == [1, 9]
    assert result["some_future_field"] == {"added_by": "a newer extractor"}


def test_pipeline_meta_clean_doc_validates_normally(monkeypatch):
    """A clean sidecar still round-trips through ``PipelineMeta`` (no regression
    to the happy path)."""
    slug = "clean_reciter"
    doc = {
        "schema_version": 1,
        "generated_at": "2026-06-10T00:00:00Z",
        "deleted_basmala_chapters": [9],
    }
    monkeypatch.setattr(data_loader.data_dir, "read_pipeline_meta_doc", lambda r: doc)
    cache.pop_seg_pipeline_meta(slug)

    result = data_loader.load_pipeline_meta(slug)

    # Went through PipelineMeta.model_validate → model_dump: exactly the
    # declared fields, no extras.
    assert result == {
        "schema_version": 1,
        "generated_at": "2026-06-10T00:00:00Z",
        "deleted_basmala_chapters": [9],
    }
