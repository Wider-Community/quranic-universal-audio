"""Persisted ``qalqala_letter`` derivation — one source of truth.

The classifier's qalqala check used to call ``last_arabic_letter`` per
segment at every validate (~1.8s self-time across ~13k segs). To eliminate
that runtime cost we persist the result onto each segment's dict in
``detailed.json``. Three writers stamp this field:

- ``services/save.py`` on every saved segment (live edits)
- ``services/validation/classifier.py`` fall-through (legacy segs lacking
  the persisted field — preserves identity for non-backfilled data)
- ``inspector/scripts/backfill_qalqala_letter.py`` (one-off backfill)

All three call ``compute_qalqala_letter`` here so the value is byte-
equivalent across writers, which keeps drift checks honest.
"""

from __future__ import annotations

from constants import QALQALA_LETTERS
from services.reference.quran_refs import dk_text_for_ref
from utils.arabic_text import last_arabic_letter


def compute_qalqala_letter(seg: dict) -> str | None:
    """Return the persisted ``qalqala_letter`` value for *seg*.

    Either a single Arabic letter (one of ``QALQALA_LETTERS``) or ``None``
    when no qalqala letter exists at the segment's right boundary. The
    seg's text is derived from ``matched_ref`` via ``dk_text_for_ref``
    (Migration #5 dropped per-seg ``matched_text``).
    """
    text = dk_text_for_ref(seg.get("matched_ref"))
    last = last_arabic_letter(text)
    return last if last in QALQALA_LETTERS else None
