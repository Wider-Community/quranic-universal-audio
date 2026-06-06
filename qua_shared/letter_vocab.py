"""Canonical letter-tier tokenization for published timestamps.

The internal per-letter ``char`` (in ``reciters/<slug>/timestamps/<ch>.json.gz``)
is a grapheme token produced upstream by the aligner: the Uthmani word text with
short vowels (haraka: fatha/damma/kasra/sukun/shadda/tanween/waqf marks) already
stripped, but with *madd-class* marks retained. That internal alphabet is **57
tokens** — it keeps the maddah mark ``U+0653`` fused onto base letters
(``آ وٓ كٓ مٓ نٓ …``) alongside the bare bases, which is redundant for consumers
(the maddah is a prolongation mark, not a distinct letter).

This module defines the smaller, stable **external** alphabet we publish, and the
build-time mapping the release/dataset jobs apply. The rule is intentionally tiny:

    external = internal with the maddah mark (U+0653) removed.

That collapses the 15 ``base+maddah`` composites into their already-present bases
(a non-lossy, prolongation-only merge — no two distinct letters ever combine),
leaving **42** tokens. Everything orthographically load-bearing is preserved as its
own token: the dagger/superscript alef (``U+0670``, which also stands alone), the
small waw/yeh and small-high yeh/noon, alef-wasla, and every hamza seat.

Internal shards are NOT touched — they stay full-fidelity (57). The Inspector
animation reads internal shards and is unaffected; only the published letter tier
(GH release ``letter_timestamps.json.gz`` + HF dataset ``letter_timestamps.char``)
goes through :func:`to_external_char`.

``to_external_char`` is **fail-loud**: any token it produces that is not in
:data:`VOCAB_TOKENS` raises, so a future riwayah / orthography change surfaces at
cut time instead of silently shipping an undocumented token. The companion asset
:func:`vocab_json_bytes` (published as ``letter_vocab.json`` next to the release's
``qpc_hafs.json``) documents the alphabet for downstream consumers.

Extensibility: the vocab document is ``schema_version``-stamped and scoped by
``script`` + ``riwayah``. Today only Hafs ``an Asim`` in the QPC Uthmani script is
populated; additional riwayat/orthographies extend this (a riwayah-keyed registry)
rather than mutating the Hafs alphabet.
"""

from __future__ import annotations

import json
import unicodedata

# The maddah (prolongation) mark. Dropped from every token at publish time.
MADDAH = "ٓ"  # ARABIC MADDAH ABOVE

# Vocab document provenance.
SCHEMA_VERSION = 1
SCRIPT = "uthmani_hafs_qpc"
RIWAYAH = "hafs_an_asim"

# === The 42-token external alphabet ===
# Defined by codepoint (single code point each — the maddah composites collapse to
# their base) to remove any glyph-transcription risk. Each entry is
# ``(codepoint, category, gloss)``; the token, U+ string, and Unicode name are
# derived below. Order is meaningful (grouped + roughly frequency-sorted within
# group) and is preserved in the published asset.
_VOCAB_SPEC: tuple[tuple[int, str, str], ...] = (
    # --- 27 ordinary consonants ---
    (0x0628, "consonant", "beh"),
    (0x062A, "consonant", "teh"),
    (0x062B, "consonant", "theh"),
    (0x062C, "consonant", "jeem"),
    (0x062D, "consonant", "hah"),
    (0x062E, "consonant", "khah"),
    (0x062F, "consonant", "dal"),
    (0x0630, "consonant", "thal"),
    (0x0631, "consonant", "reh"),
    (0x0632, "consonant", "zain"),
    (0x0633, "consonant", "seen"),
    (0x0634, "consonant", "sheen"),
    (0x0635, "consonant", "sad"),
    (0x0636, "consonant", "dad"),
    (0x0637, "consonant", "tah"),
    (0x0638, "consonant", "zah"),
    (0x0639, "consonant", "ain"),
    (0x063A, "consonant", "ghain"),
    (0x0641, "consonant", "feh"),
    (0x0642, "consonant", "qaf"),
    (0x0643, "consonant", "kaf"),
    (0x0644, "consonant", "lam"),
    (0x0645, "consonant", "meem"),
    (0x0646, "consonant", "noon"),
    (0x0647, "consonant", "heh"),
    (0x0648, "consonant", "waw"),
    (0x064A, "consonant", "yeh"),
    # --- 4 alef / ta-marbuta (distinct written letters, never folded) ---
    (0x0627, "alef", "alef"),
    (0x0671, "alef", "alef wasla (silent connecting alef)"),
    (0x0649, "alef", "alef maksura"),
    (0x0629, "alef", "teh marbuta"),
    # --- 6 hamza family (seat is part of letter identity) ---
    (0x0621, "hamza", "hamza"),
    (0x0623, "hamza", "alef with hamza above"),
    (0x0625, "hamza", "alef with hamza below"),
    (0x0624, "hamza", "waw with hamza above"),
    (0x0626, "hamza", "yeh with hamza above"),
    (0x0654, "hamza", "bare hamza above (seatless hamza mark)"),
    # --- 5 special / silent / superscript letters ---
    (0x0670, "special", "superscript (dagger) alef — long aa written above; also stands alone"),
    (0x06E5, "special", "small waw (silent/assimilated glide)"),
    (0x06E6, "special", "small yeh (silent/assimilated glide)"),
    (0x06E7, "special", "small high yeh"),
    (0x06E8, "special", "small high noon"),
)


def _entry(cp: int, category: str, gloss: str) -> dict:
    token = chr(cp)
    return {
        "token": token,
        "codepoints": [f"U+{cp:04X}"],
        "names": [unicodedata.name(token, "?")],
        "category": category,
        "gloss": gloss,
    }


# Ordered, fully-annotated alphabet — the body of the published asset.
EXTERNAL_VOCAB: list[dict] = [_entry(cp, cat, gloss) for cp, cat, gloss in _VOCAB_SPEC]

# Fast membership set + the drift guard's source of truth.
VOCAB_TOKENS: frozenset[str] = frozenset(chr(cp) for cp, _cat, _gloss in _VOCAB_SPEC)

assert len(EXTERNAL_VOCAB) == len(VOCAB_TOKENS) == 42, "external letter vocab must be 42 unique tokens"


def to_external_char(ch: str) -> str:
    """Map one internal letter token to its external (published) form.

    Drops the maddah mark (``U+0653``). Fail-loud: raises ``ValueError`` if the
    result is not a known token, so an unexpected upstream token (new riwayah /
    orthography) is caught at cut time rather than shipped silently.
    """
    ext = ch.replace(MADDAH, "")
    if ext not in VOCAB_TOKENS:
        raise ValueError(
            f"letter token {ch!r} (-> {ext!r}, codepoints "
            f"{' '.join(f'U+{ord(c):04X}' for c in ext)}) is not in the external "
            f"letter vocab; the 42-token alphabet may need extending — see "
            f"qua_shared/letter_vocab.py"
        )
    return ext


def vocab_document() -> dict:
    """The full ``letter_vocab.json`` document (alphabet + provenance + rules)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "script": SCRIPT,
        "riwayah": RIWAYAH,
        "description": (
            "Character vocabulary for the letter tier (letter_timestamps.json.gz / the "
            "dataset's letter_timestamps.char). Each letter's `char` is one of these tokens."
        ),
        "tokenization": {
            "rule": (
                "Grapheme tokens from the Uthmani word text. Short vowels (haraka: "
                "fatha/damma/kasra/sukun/shadda/tanween and waqf marks) are stripped; "
                "the maddah prolongation mark (U+0653) is also dropped. Madd/silent "
                "skeleton letters are kept as distinct tokens: the superscript (dagger) "
                "alef U+0670, the small waw/yeh U+06E5/U+06E6, the small-high yeh/noon "
                "U+06E7/U+06E8, alef-wasla U+0671, and every hamza seat."
            ),
            "render_hint": (
                "A few tokens are standalone combining marks (U+0670, U+0654, U+06E7, "
                "U+06E8). To render one in isolation, prefix it with a base such as ZWSP "
                "(U+200B) so it does not attach to surrounding text."
            ),
            "token_count": len(EXTERNAL_VOCAB),
        },
        "tokens": EXTERNAL_VOCAB,
    }


def vocab_json_bytes() -> bytes:
    """Deterministic UTF-8 bytes for the ``letter_vocab.json`` release/dataset asset."""
    return (
        json.dumps(vocab_document(), ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    )
