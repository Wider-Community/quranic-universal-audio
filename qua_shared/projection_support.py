"""How completely a Hafs span reached the delivery edition's words.

Recognition and MFA always run against Hafs, so a projected segment records the
Hafs span the matcher matched (``source_ref``) beside the delivery edition's own
``matched_ref``. ``projection_support`` says whether every Hafs word in that span
made it across.

The question has to be asked of the SOURCE words. ``relation_for_target`` answers
``"full"`` for every word of every edition — a target word is covered by
definition — so a target-side check reports ``"full"`` everywhere and the
``partial`` branch never fires.

Kept here rather than in the Inspector tree because ``qua_jobs`` and the devenv
scripts need the same answer, and two spellings of it would disagree.
"""

from __future__ import annotations

from typing import Any

FULL = "full"
PARTIAL = "partial"


def source_refs(first_ref: str, last_ref: str) -> list[str]:
    """Every Hafs word ref from ``first_ref`` to ``last_ref`` inclusive.

    Walks whole ayahs rather than assuming one: a segment can span a verse
    boundary, and a target verse can draw on two Hafs verses (Qalun 1:1 merges
    Hafs 1:1 and 1:2).
    """
    from qua_domain import get_ayah_word_count

    surah, first_ayah, first_word = (int(part) for part in first_ref.split(":"))
    end_surah, last_ayah, last_word = (int(part) for part in last_ref.split(":"))
    if end_surah != surah:
        raise ValueError(f"{first_ref}..{last_ref} spans two surahs")
    refs: list[str] = []
    for ayah in range(first_ayah, last_ayah + 1):
        start = first_word if ayah == first_ayah else 1
        end = last_word if ayah == last_ayah else get_ayah_word_count(surah, ayah, "hafs")
        refs.extend(f"{surah}:{ayah}:{word}" for word in range(start, end + 1))
    return refs


def degrades(group: Any) -> bool:
    """True when one projection group did not carry its source words across whole.

    ``target_absent`` is the plain case: the edition does not write this word.
    ``opening_basmala`` is the same loss wearing a different kind — Warsh and
    Qalun render the Fatiha opener unnumbered, so its four words reach nothing.
    Anything not fully supported counts too, which is a segment cutting an N:M
    relation in half.
    """
    return group.kind != "mapped" or group.support != FULL


def _group_sources(group: Any) -> set[str]:
    return {f"{word.surah}:{word.ayah}:{word.word}" for word in group.source_words}


def support_for(projection: Any, source_span: str) -> str:
    """``"full"`` or ``"partial"`` for a segment's whole Hafs span.

    Two ways to be partial: a word in the span reached nothing, or the span
    holds only PART of a relation. Warsh writes Hafs 40:26:13+14 as one word, so
    a segment ending at 13 carries half of what that target word is made of —
    the aligner will time it from half its phones.
    """
    first, _, last = source_span.partition("-")
    refs = source_refs(first, last or first)
    covered = set(refs)
    for ref in refs:
        try:
            group = projection.relation_for_source(ref)
        except KeyError:
            raise ValueError(f"{source_span!r} names {ref}, which is not a Hafs word") from None
        if degrades(group) or not covered.issuperset(_group_sources(group)):
            return PARTIAL
    return FULL


__all__ = ["FULL", "PARTIAL", "degrades", "source_refs", "support_for"]
