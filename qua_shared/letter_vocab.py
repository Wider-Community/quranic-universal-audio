"""Canonical letter-tier tokenization for published timestamps.

The internal per-letter ``char`` (in ``reciters/<slug>/timestamps/<ch>.json.br``)
is a grapheme token produced upstream by the aligner: the Uthmani word text with
short vowels (haraka: fatha/damma/kasra/sukun/shadda/tanween/waqf marks) already
stripped, but with *madd-class* marks retained. That internal alphabet is **57
tokens** — it keeps the maddah mark ``U+0653`` fused onto base letters
(``آ وٓ كٓ مٓ نٓ …``) alongside the bare bases, which is redundant for consumers
(the maddah is a prolongation mark, not a distinct letter).

This module defines the smaller, stable **external** alphabet we publish, and the
build-time mapping the release/dataset jobs apply. The rule is intentionally tiny:

    external = internal with the maddah (U+0653) and silent-zero (U+06DF, U+06E0)
    marks removed.

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
cut time instead of silently shipping an undocumented token.

The companion asset :func:`vocab_csv_bytes` documents the alphabet for downstream
consumers (``char,codepoint,name`` CSV). It ships as :data:`VOCAB_FILENAME` — the
riwayah + script are encoded in the *filename* (``letter_vocab_hafs_qpc.csv``) so a
future riwayah/orthography adds its own file (``letter_vocab_warsh_qpc.csv``, …)
rather than mutating this one. The tokenization rule itself lives in the release
notes + dataset card, not inside the asset.
"""

from __future__ import annotations

import csv
import io
import unicodedata

# The maddah (prolongation) mark. Dropped from every token at publish time.
MADDAH = "ٓ"  # ARABIC MADDAH ABOVE

# Silent-zero marks (Quranic "small high zero") the v4 silent-letter shard format
# folds onto a written-but-unpronounced grapheme. Dropped at publish time like
# the maddah — they flag silence, not a distinct letter, and the base they sit on
# is already a vocab token (silence isn't carried in the published letter tier).
SILENT_ZERO_MARKS = ("۟", "۠")  # SMALL HIGH ROUNDED / RECTANGULAR ZERO

# Every mark stripped from an internal token to derive its external form.
_DROP_MARKS = (MADDAH, *SILENT_ZERO_MARKS)

# Provenance — encoded in the published asset's filename for extensibility.
RIWAYAH = "hafs_an_asim"
SCRIPT = "uthmani_hafs_qpc"
VOCAB_FILENAME = "letter_vocab_hafs_qpc.csv"

# === The 42-token external alphabet ===
# Ordered codepoints (single code point each — the maddah composites collapse to
# their base). Token + U+ string + Unicode name are derived below. Order is
# grouped (consonants, alef family, hamza family, special/silent) and preserved
# in the published CSV.
_CODEPOINTS: tuple[int, ...] = (
    # 27 ordinary consonants
    0x0628,
    0x062A,
    0x062B,
    0x062C,
    0x062D,
    0x062E,
    0x062F,
    0x0630,
    0x0631,
    0x0632,
    0x0633,
    0x0634,
    0x0635,
    0x0636,
    0x0637,
    0x0638,
    0x0639,
    0x063A,
    0x0641,
    0x0642,
    0x0643,
    0x0644,
    0x0645,
    0x0646,
    0x0647,
    0x0648,
    0x064A,
    # 4 alef / ta-marbuta (distinct written letters, never folded)
    0x0627,
    0x0671,
    0x0649,
    0x0629,
    # 6 hamza family (seat is part of letter identity)
    0x0621,
    0x0623,
    0x0625,
    0x0624,
    0x0626,
    0x0654,
    # 5 special / silent / superscript letters
    0x0670,
    0x06E5,
    0x06E6,
    0x06E7,
    0x06E8,
)

# Ordered, flat rows — the body of the published CSV.
EXTERNAL_VOCAB: list[dict] = [
    {"char": chr(cp), "codepoint": f"U+{cp:04X}", "name": unicodedata.name(chr(cp), "?")}
    for cp in _CODEPOINTS
]

# Fast membership set + the drift guard's source of truth.
VOCAB_TOKENS: frozenset[str] = frozenset(chr(cp) for cp in _CODEPOINTS)

assert len(EXTERNAL_VOCAB) == len(VOCAB_TOKENS) == 42, (
    "external letter vocab must be 42 unique tokens"
)


def to_external_char(ch: str) -> str:
    """Map one internal letter token to its external (published) form.

    Drops the maddah (``U+0653``) and silent-zero (``U+06DF`` / ``U+06E0``) marks.
    Fail-loud: raises ``ValueError`` if the result is not a known token, so an
    unexpected upstream token (new riwayah / orthography) is caught at cut time
    rather than shipped silently.
    """
    ext = ch
    for _mark in _DROP_MARKS:
        ext = ext.replace(_mark, "")
    if ext not in VOCAB_TOKENS:
        raise ValueError(
            f"letter token {ch!r} (-> {ext!r}, codepoints "
            f"{' '.join(f'U+{ord(c):04X}' for c in ext)}) is not in the external "
            f"letter vocab; the 42-token alphabet may need extending — see "
            f"qua_shared/letter_vocab.py"
        )
    return ext


def vocab_csv_bytes() -> bytes:
    """Deterministic UTF-8 CSV (``char,codepoint,name``) for the published asset."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["char", "codepoint", "name"])
    for entry in EXTERNAL_VOCAB:
        writer.writerow([entry["char"], entry["codepoint"], entry["name"]])
    return buf.getvalue().encode("utf-8")
