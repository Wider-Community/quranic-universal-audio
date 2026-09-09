"""DigitalKhatt paint-unit projection contract."""

from __future__ import annotations

from qua_shared.digital_khatt import align_scalar_owners, project_word


def _token(offsets, *, sound_ids, start, end):
    return {
        "character_offsets": offsets,
        "paint_character_offsets": offsets,
        "sound_ids": sound_ids,
        "start_ms": start,
        "end_ms": end,
    }


def test_independently_sounded_dagger_is_its_own_paint_unit():
    word = {
        "ref": "87:1:1",
        "source_text": "ىٰ",
        "letters": [
            _token([0], sound_ids=[], start=0, end=100),
            _token([1], sound_ids=[7], start=0, end=100),
        ],
    }

    text, tokens = project_word(word, "ىٰ")

    assert text == "ىٰ"
    assert tokens == [
        {"start_ms": 0, "end_ms": 100, "owns_sound": False, "paint": [[0, 1]]},
        {"start_ms": 0, "end_ms": 100, "owns_sound": True, "paint": [[1, 2]]},
    ]


def test_inserted_combining_mark_in_digital_khatt_follows_source_owner():
    # DigitalKhatt may omit a QPC spacing scalar while retaining its mark. NFD
    # matching transfers the producer owner without treating the mark as a new
    # alphabet token.
    owners = align_scalar_owners("لـٰ", [0, 0, 0], "لٰ")
    assert owners == [0, 0]


def test_stop_mark_stays_visible_without_a_timed_paint_owner():
    word = {
        "ref": "2:5:4",
        "source_text": "ك",
        "letters": [_token([0], sound_ids=[1], start=10, end=20)],
    }

    text, tokens = project_word(word, "كۖ")

    assert text == "كۖ"
    assert tokens == [{"start_ms": 10, "end_ms": 20, "owns_sound": True, "paint": [[0, 1]]}]
