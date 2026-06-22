from __future__ import annotations

import csv
import io

import pytest

from qua_shared.letter_vocab import (
    EXTERNAL_VOCAB,
    MADDAH,
    VOCAB_FILENAME,
    VOCAB_TOKENS,
    to_external_char,
    vocab_csv_bytes,
)

# The 15 bases that appear carrying a maddah in real released data. The internal
# token is the DECOMPOSED base + U+0653 (built explicitly so the fixture matches
# the real bytes, not a precomposed glyph like U+0622).
_MADDAH_BASES = ["ا", "و", "ى", "ي", "ل", "م", "ن", "س", "ص", "ع", "ق", "ك", "ٰ", "ۥ", "ۦ"]
_MADDAH_COMPOSITES = {base + MADDAH: base for base in _MADDAH_BASES}

# Tokens that must survive untouched (the silent/structural keep-list).
_PRESERVED = ["ٰ", "ۥ", "ۦ", "ۧ", "ۨ", "ٱ", "ٔ", "ء"]


def test_vocab_is_42_unique_tokens():
    assert len(EXTERNAL_VOCAB) == 42
    assert len(VOCAB_TOKENS) == 42
    tokens = [e["char"] for e in EXTERNAL_VOCAB]
    assert len(set(tokens)) == 42
    assert set(tokens) == set(VOCAB_TOKENS)
    for e in EXTERNAL_VOCAB:
        assert set(e) == {"char", "codepoint", "name"}  # no gloss/category/array noise
        assert len(e["char"]) == 1  # single-codepoint tokens only
        assert e["codepoint"] == f"U+{ord(e['char']):04X}"
        assert e["name"]


def test_maddah_composites_collapse_to_base():
    for composite, base in _MADDAH_COMPOSITES.items():
        assert to_external_char(composite) == base
        assert base in VOCAB_TOKENS
        assert MADDAH not in to_external_char(composite)


def test_silent_zero_marks_drop_to_base_letter():
    # v4 silent-letter shards fold a silent-zero mark (U+06DF rounded / U+06E0
    # rectangular) onto a written-but-unpronounced grapheme. The published
    # alphabet has no such token, so it must drop like the maddah, collapsing to
    # the base letter already in vocab.
    cases = {
        "ا۟": "ا",  # alef + small high rounded zero
        "و۟": "و",  # waw + small high rounded zero
        "ي۟": "ي",  # yeh + small high rounded zero
        "ى۟": "ى",  # alef maksura + small high rounded zero
        "ا۠": "ا",  # alef + small high rectangular zero
    }
    for marked, base in cases.items():
        assert to_external_char(marked) == base
        assert base in VOCAB_TOKENS


def test_preserved_tokens_pass_through_unchanged():
    for tok in _PRESERVED:
        assert to_external_char(tok) == tok


def test_consonants_pass_through_unchanged():
    # the 27 ordinary consonants are the first block
    for tok in "بتثجحخدذرزسشصضطظعغفقكلمنهوي":
        assert to_external_char(tok) == tok


def test_fail_loud_on_unknown_token():
    with pytest.raises(ValueError):
        to_external_char("بَ")  # beh + fatha (haraka not in alphabet)
    with pytest.raises(ValueError):
        to_external_char("ݢ")  # foreign letter
    with pytest.raises(ValueError):
        to_external_char(MADDAH)  # bare maddah collapses to empty


def test_vocab_csv_is_deterministic_and_complete():
    b1 = vocab_csv_bytes()
    b2 = vocab_csv_bytes()
    assert b1 == b2
    assert VOCAB_FILENAME == "letter_vocab_hafs_qpc.csv"
    rows = list(csv.reader(io.StringIO(b1.decode("utf-8"))))
    assert rows[0] == ["char", "codepoint", "name"]
    body = rows[1:]
    assert len(body) == 42
    chars = [r[0] for r in body]
    assert set(chars) == set(VOCAB_TOKENS)
    for char, codepoint, name in body:
        assert codepoint == f"U+{ord(char):04X}"
        assert name


def test_mapping_over_a_real_muqattaat_verse():
    # 19:1 = كٓهيعٓصٓ — maddah composites + plain letters.
    internal = ["كٓ", "ه", "ي", "عٓ", "صٓ"]
    external = [to_external_char(c) for c in internal]
    assert external == ["ك", "ه", "ي", "ع", "ص"]
    assert all(c in VOCAB_TOKENS for c in external)
    assert all(MADDAH not in c for c in external)
