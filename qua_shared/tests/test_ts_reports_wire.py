"""ts_reports wire validators: per-category comment / subtype / target rules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qua_shared.schemas.wire.ts_reports import TsReportCreateRequest


def _req(**kw) -> dict:
    base = {"verse_key": "2:45", "category": "other", "target": {"kind": "verse"}, "comment": "x"}
    base.update(kw)
    return base


def test_audio_requires_comment():
    TsReportCreateRequest.model_validate(_req(category="audio", comment="bad audio"))
    with pytest.raises(ValidationError):
        TsReportCreateRequest.model_validate(_req(category="audio", comment=None))


def test_mapping_requires_comment_and_column_target():
    TsReportCreateRequest.model_validate(
        _req(
            category="mapping",
            comment="wrong map",
            target={"kind": "column", "word_index": 0, "source_letter_index": 1},
        )
    )
    with pytest.raises(ValidationError):  # missing comment
        TsReportCreateRequest.model_validate(
            _req(
                category="mapping",
                comment=None,
                target={"kind": "column", "word_index": 0, "source_letter_index": 1},
            )
        )
    with pytest.raises(ValidationError):  # non-column target
        TsReportCreateRequest.model_validate(
            _req(category="mapping", comment="x", target={"kind": "verse"})
        )


def test_other_requires_comment():
    with pytest.raises(ValidationError):
        TsReportCreateRequest.model_validate(_req(category="other", comment="   "))


def test_timing_subtype_and_conditional_comment():
    # too_long is fine without a comment
    TsReportCreateRequest.model_validate(
        _req(category="timing", subtype="too_long", comment=None, target={"kind": "word", "word_index": 0})
    )
    # other requires a comment
    with pytest.raises(ValidationError):
        TsReportCreateRequest.model_validate(
            _req(category="timing", subtype="other", comment=None, target={"kind": "word", "word_index": 0})
        )
    # missing subtype
    with pytest.raises(ValidationError):
        TsReportCreateRequest.model_validate(
            _req(category="timing", subtype=None, comment="x", target={"kind": "word", "word_index": 0})
        )


def test_tajweed_subtype_and_target():
    TsReportCreateRequest.model_validate(
        _req(
            category="tajweed",
            subtype="wrong_rule",
            comment=None,
            target={"kind": "cell", "word_index": 0, "cell_index": 2},
        )
    )
    with pytest.raises(ValidationError):  # bad subtype
        TsReportCreateRequest.model_validate(
            _req(
                category="tajweed",
                subtype="too_long",
                comment=None,
                target={"kind": "cell", "word_index": 0, "cell_index": 2},
            )
        )
    with pytest.raises(ValidationError):  # tajweed cannot target a whole verse
        TsReportCreateRequest.model_validate(
            _req(category="tajweed", subtype="wrong_rule", comment=None, target={"kind": "verse"})
        )


def test_subtype_rejected_for_audio_and_other():
    with pytest.raises(ValidationError):
        TsReportCreateRequest.model_validate(_req(category="audio", comment="x", subtype="too_long"))


def test_bad_verse_key_rejected():
    with pytest.raises(ValidationError):
        TsReportCreateRequest.model_validate(_req(verse_key="nope"))


def test_target_field_requirements():
    with pytest.raises(ValidationError):  # cell needs an index
        TsReportCreateRequest.model_validate(
            _req(category="other", target={"kind": "cell", "word_index": 0})
        )
    with pytest.raises(ValidationError):  # column needs source_letter_index
        TsReportCreateRequest.model_validate(
            _req(category="mapping", comment="x", target={"kind": "column", "word_index": 0})
        )
    with pytest.raises(ValidationError):  # phoneme needs phoneme_flat_index
        TsReportCreateRequest.model_validate(
            _req(
                category="tajweed",
                subtype="wrong_rule",
                comment=None,
                target={"kind": "phoneme", "word_index": 0},
            )
        )
