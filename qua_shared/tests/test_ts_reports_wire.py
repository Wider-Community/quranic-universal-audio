"""ts_reports wire validators: per-category comment / subtype / target rules."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qua_shared.schemas.wire.ts_reports import (
    TsReportBatchCreateRequest,
    TsReportBatchItem,
    TsReportCreateRequest,
    timing_label,
)


def _req(**kw) -> dict:
    base = {"verse_key": "2:45", "category": "other", "target": {"kind": "verse"}, "comment": "x"}
    base.update(kw)
    return base


def test_audio_requires_comment():
    TsReportCreateRequest.model_validate(_req(category="audio", comment="bad audio"))
    with pytest.raises(ValidationError):
        TsReportCreateRequest.model_validate(_req(category="audio", comment=None))


def test_other_requires_comment():
    with pytest.raises(ValidationError):
        TsReportCreateRequest.model_validate(_req(category="other", comment="   "))


def test_timing_axes_required_no_subtype():
    word = {"kind": "word", "word_index": 0}
    # one axis is enough; comment optional
    TsReportCreateRequest.model_validate(
        _req(category="timing", comment=None, onset="early", target=word)
    )
    TsReportCreateRequest.model_validate(
        _req(category="timing", comment=None, offset="late", target=word)
    )
    # both axes set is fine
    TsReportCreateRequest.model_validate(
        _req(category="timing", comment=None, onset="late", offset="early", target=word)
    )
    # neither axis → rejected
    with pytest.raises(ValidationError):
        TsReportCreateRequest.model_validate(_req(category="timing", comment="x", target=word))
    # subtype is timing-illegal
    with pytest.raises(ValidationError):
        TsReportCreateRequest.model_validate(
            _req(category="timing", subtype="wrong_rule", onset="early", target=word)
        )


def test_timing_label_matrix():
    assert timing_label("early", "late") == "Too long"
    assert timing_label("late", "early") == "Too short"
    assert timing_label("early", "early") == "Shifted earlier"
    assert timing_label("late", "late") == "Shifted later"
    assert timing_label("early", None) == "Starts early"
    assert timing_label("late", None) == "Starts late"
    assert timing_label(None, "early") == "Finishes early"
    assert timing_label(None, "late") == "Finishes late"


def test_tajweed_subtype_and_target():
    cell = {"kind": "cell", "word_index": 0, "cell_index": 2}
    TsReportCreateRequest.model_validate(
        _req(category="tajweed", subtype="wrong_rule", comment="wrong tafkhīm", target=cell)
    )
    with pytest.raises(ValidationError):  # comment is mandatory for tajweed
        TsReportCreateRequest.model_validate(
            _req(category="tajweed", subtype="wrong_rule", comment=None, target=cell)
        )
    with pytest.raises(ValidationError):  # bad subtype
        TsReportCreateRequest.model_validate(
            _req(category="tajweed", subtype="not_a_real_subtype", comment="x", target=cell)
        )
    with pytest.raises(ValidationError):  # tajweed cannot target a whole verse
        TsReportCreateRequest.model_validate(
            _req(category="tajweed", subtype="wrong_rule", comment="x", target={"kind": "verse"})
        )


def test_phonemes_target_phoneme_no_subtype_axes_or_comment():
    ph = {"kind": "phoneme", "word_index": 0, "phoneme_flat_index": 2}
    # a phoneme target, no comment, no subtype/axes — valid
    TsReportCreateRequest.model_validate(_req(category="phonemes", comment=None, target=ph))
    # a bridge phoneme (phoneme_flat_index = -1) is a valid target
    bridge = {"kind": "phoneme", "word_index": 1, "phoneme_flat_index": -1}
    TsReportCreateRequest.model_validate(_req(category="phonemes", comment=None, target=bridge))
    with pytest.raises(ValidationError):  # phonemes can't carry a subtype
        TsReportCreateRequest.model_validate(
            _req(category="phonemes", comment=None, subtype="wrong_rule", target=ph)
        )
    with pytest.raises(ValidationError):  # phonemes can't carry timing axes
        TsReportCreateRequest.model_validate(
            _req(category="phonemes", comment=None, onset="early", target=ph)
        )
    with pytest.raises(ValidationError):  # phonemes can only target a phoneme
        TsReportCreateRequest.model_validate(
            _req(
                category="phonemes",
                comment=None,
                target={"kind": "cell", "word_index": 0, "cell_index": 1},
            )
        )
    with pytest.raises(ValidationError):  # selected_rule_tags is tajweed-only
        TsReportCreateRequest.model_validate(
            _req(category="phonemes", comment=None, target=ph, selected_rule_tags=["qalqala"])
        )


def test_silence_subtypes_target_gap():
    gap = {"kind": "gap", "word_index": 1}
    # binary subtypes: a gap target, no comment, no axes — valid
    TsReportCreateRequest.model_validate(
        _req(category="silence", subtype="pause_wasl", comment=None, target=gap)
    )
    TsReportCreateRequest.model_validate(
        _req(category="silence", subtype="pause_missed", comment=None, target=gap)
    )
    # pause_boundary carries the onset/offset axes (≥1)
    TsReportCreateRequest.model_validate(
        _req(category="silence", subtype="pause_boundary", comment=None, onset="early", target=gap)
    )
    with pytest.raises(ValidationError):  # boundary with no axis
        TsReportCreateRequest.model_validate(
            _req(category="silence", subtype="pause_boundary", comment=None, target=gap)
        )
    with pytest.raises(ValidationError):  # axes only on pause_boundary
        TsReportCreateRequest.model_validate(
            _req(
                category="silence", subtype="pause_missed", comment=None, onset="early", target=gap
            )
        )
    with pytest.raises(ValidationError):  # silence requires a subtype
        TsReportCreateRequest.model_validate(_req(category="silence", comment=None, target=gap))
    with pytest.raises(ValidationError):  # a tajweed subtype is not a silence subtype
        TsReportCreateRequest.model_validate(
            _req(category="silence", subtype="wrong_rule", comment=None, target=gap)
        )
    with pytest.raises(ValidationError):  # silence can only target a gap
        TsReportCreateRequest.model_validate(
            _req(category="silence", subtype="pause_missed", comment=None, target={"kind": "verse"})
        )
    with pytest.raises(ValidationError):  # a gap target needs word_index
        TsReportCreateRequest.model_validate(
            _req(category="silence", subtype="pause_missed", comment=None, target={"kind": "gap"})
        )


def test_subtype_and_axes_rejected_for_non_timing():
    with pytest.raises(ValidationError):  # audio takes no subtype
        TsReportCreateRequest.model_validate(
            _req(category="audio", comment="x", subtype="wrong_rule")
        )
    with pytest.raises(ValidationError):  # onset/offset are timing-only
        TsReportCreateRequest.model_validate(_req(category="audio", comment="x", onset="early"))
    with pytest.raises(ValidationError):  # tajweed cannot carry axes
        TsReportCreateRequest.model_validate(
            _req(
                category="tajweed",
                subtype="wrong_rule",
                comment=None,
                onset="early",
                target={"kind": "cell", "word_index": 0, "cell_index": 2},
            )
        )


def test_bad_verse_key_rejected():
    with pytest.raises(ValidationError):
        TsReportCreateRequest.model_validate(_req(verse_key="nope"))


def test_target_field_requirements():
    with pytest.raises(ValidationError):  # cell needs an index
        TsReportCreateRequest.model_validate(
            _req(category="other", target={"kind": "cell", "word_index": 0})
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


def test_selected_rule_tags_only_on_tajweed_wrong_rule():
    TsReportCreateRequest.model_validate(
        _req(
            category="tajweed",
            subtype="wrong_rule",
            comment="should be qalqala",
            target={"kind": "cell", "word_index": 0, "cell_index": 2},
            selected_rule_tags=["qalqala"],
        )
    )
    with pytest.raises(ValidationError):  # missing_rule can't carry selected tags
        TsReportCreateRequest.model_validate(
            _req(
                category="tajweed",
                subtype="missing_rule",
                comment="x",
                target={"kind": "cell", "word_index": 0, "cell_index": 2},
                selected_rule_tags=["qalqala"],
            )
        )
    with pytest.raises(ValidationError):  # audio can't carry selected tags
        TsReportCreateRequest.model_validate(
            _req(category="audio", comment="x", selected_rule_tags=["qalqala"])
        )


def _item(**kw) -> dict:
    base = {"category": "timing", "onset": "early", "target": {"kind": "word", "word_index": 0}}
    base.update(kw)
    return base


def test_batch_item_shares_validation_with_single_create():
    # A bad input (timing with neither boundary axis) is rejected identically by both.
    bad = _item(onset=None)
    with pytest.raises(ValidationError):
        TsReportBatchItem.model_validate(bad)
    with pytest.raises(ValidationError):
        TsReportCreateRequest.model_validate(_req(**bad))


def test_batch_item_requires_comment_when_mandatory():
    with pytest.raises(ValidationError):
        TsReportBatchItem.model_validate(
            _item(
                category="tajweed",
                onset=None,
                subtype="wrong_rule",
                comment=None,
                target={"kind": "cell", "word_index": 0, "cell_index": 1},
            )
        )


def test_batch_request_rejects_empty_items():
    with pytest.raises(ValidationError):
        TsReportBatchCreateRequest.model_validate({"verse_key": "2:45", "items": []})


def test_batch_request_rejects_bad_verse_key():
    with pytest.raises(ValidationError):
        TsReportBatchCreateRequest.model_validate({"verse_key": "2", "items": [_item()]})


def test_batch_request_accepts_mixed_items():
    req = TsReportBatchCreateRequest.model_validate(
        {
            "verse_key": "2:45",
            "items": [
                _item(),
                _item(
                    category="tajweed",
                    onset=None,
                    subtype="wrong_rule",
                    comment="x",
                    target={"kind": "cell", "word_index": 0, "cell_index": 1},
                    selected_rule_tags=["qalqala"],
                ),
            ],
        }
    )
    assert len(req.items) == 2
