from __future__ import annotations

import json

import pytest

from qua_shared.letter_vocab import (
    EXTERNAL_VOCAB,
    MADDAH,
    VOCAB_TOKENS,
    to_external_char,
    vocab_document,
    vocab_json_bytes,
)

# Every internal base+maddah composite seen in real released data, and the base
# it must collapse to (codepoint pairs for clarity).
_MADDAH_COMPOSITES = {
    "آ": "ا",  # alef -> alef (آ)
    "وٓ": "و",  # waw
    "ىٓ": "ى",  # alef maksura
    "يٓ": "ي",  # yeh
    "لٓ": "ل",  # lam (muqattaat)
    "مٓ": "م",  # meem
    "نٓ": "ن",  # noon
    "سٓ": "س",  # seen
    "صٓ": "ص",  # sad
    "عٓ": "ع",  # ain
    "قٓ": "ق",  # qaf
    "كٓ": "ك",  # kaf
    "ٰٓ": "ٰ",  # dagger alef -> dagger alef
    "ۥٓ": "ۥ",  # small waw
    "ۦٓ": "ۦ",  # small yeh
}

# Tokens that must survive untouched (the silent/structural keep-list).
_PRESERVED = ["ٰ", "ۥ", "ۦ", "ۧ", "ۨ", "ٱ", "ٔ", "ء"]


def test_vocab_is_42_unique_annotated_tokens():
    assert len(EXTERNAL_VOCAB) == 42
    assert len(VOCAB_TOKENS) == 42
    tokens = [e["token"] for e in EXTERNAL_VOCAB]
    assert len(set(tokens)) == 42
    assert set(tokens) == set(VOCAB_TOKENS)
    for e in EXTERNAL_VOCAB:
        assert e["codepoints"] and e["names"] and e["category"] and e["gloss"]
        assert e["category"] in {"consonant", "alef", "hamza", "special"}
        # single-codepoint tokens only (maddah composites collapsed)
        assert len(e["token"]) == 1


def test_maddah_composites_collapse_to_base():
    for composite, base in _MADDAH_COMPOSITES.items():
        assert to_external_char(composite) == base
        assert base in VOCAB_TOKENS
        assert MADDAH not in to_external_char(composite)


def test_preserved_tokens_pass_through_unchanged():
    for tok in _PRESERVED:
        assert to_external_char(tok) == tok


def test_consonants_pass_through_unchanged():
    for e in EXTERNAL_VOCAB:
        if e["category"] == "consonant":
            assert to_external_char(e["token"]) == e["token"]


def test_fail_loud_on_unknown_token():
    # haraka-bearing token (fatha) is not in the external alphabet
    with pytest.raises(ValueError):
        to_external_char("بَ")  # beh + fatha
    # a foreign letter
    with pytest.raises(ValueError):
        to_external_char("ݢ")  # arabic letter keheh with dot above
    # a bare maddah on its own collapses to empty -> not a token
    with pytest.raises(ValueError):
        to_external_char(MADDAH)


def test_vocab_json_is_deterministic_and_complete():
    b1 = vocab_json_bytes()
    b2 = vocab_json_bytes()
    assert b1 == b2
    doc = json.loads(b1)
    assert doc["schema_version"] == 1
    assert doc["riwayah"] == "hafs_an_asim"
    assert doc["tokenization"]["token_count"] == 42
    assert len(doc["tokens"]) == 42
    # document() and the serialized form agree
    assert json.loads(b1) == vocab_document()


def test_mapping_over_a_real_muqattaat_verse():
    # 19:1 = كٓهيعٓصٓ — three maddah composites + plain letters; result must be
    # within the alphabet, maddah-free, and length-preserving.
    internal = ["كٓ", "ه", "ي", "عٓ", "صٓ"]
    external = [to_external_char(c) for c in internal]
    assert external == ["ك", "ه", "ي", "ع", "ص"]
    assert all(c in VOCAB_TOKENS for c in external)
    assert all(MADDAH not in c for c in external)
