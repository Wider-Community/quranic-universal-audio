"""Resolve a report target against a shard → content snapshot + staleness diff.

A Timestamps report points at a flexible target (verse / word / cell / phoneme /
column / cell-group). There is no per-cell hash anywhere, so the denormalized
*snapshot* of the targeted shard content captured at create time IS the drift
fingerprint: when a reciter's shards are regenerated, each open report's target
is re-resolved against the new shard and the report is flagged ``stale`` iff its
**category-relevant** fields changed.

What "changed" means per category (the report stays valid otherwise — e.g. a
regen that only shifts timing ms does NOT stale a timing report):
- ``tajweed`` — rule tags / silence (role/status) / cell chars changed.
- ``mapping`` — the column binding (grapheme chars ↔ mapped phones) changed.
- ``timing`` — the reported cell's identity (chars/role) changed or it vanished.
- ``audio``  — never auto-staled (not bound to shard cells).
- ``other`` / verse-level — the verse vanished or its text changed.

Flask-free. Reads shards via ``services/storage/data_dir`` and parses cells via
``qua_shared/ts_shard_cells`` (the same primitives the offline pipeline uses).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from qua_shared.ts_shard_cells import CellRow, word_cells
from services.storage import data_dir

logger = logging.getLogger(__name__)

#: Render-only phone markers excluded from the word-local indexable-phone space
#: (mirrors the cells coordinate space — qalqala ``Q`` is render-only).
_RENDER_ONLY_PHONES = frozenset({"Q"})


def _load_shard(slug: str, chapter: int) -> dict[str, Any] | None:
    try:
        raw = data_dir.read_timestamps_chapter(slug, chapter)
    except Exception:  # noqa: BLE001 — best-effort; a bucket hiccup means no fingerprint
        logger.warning("ts_target_snapshot: shard read failed %s ch%s", slug, chapter)
        return None
    if raw is None:
        return None
    try:
        doc = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("ts_target_snapshot: unparseable shard %s ch%s", slug, chapter)
        return None
    return doc if isinstance(doc, dict) else None


def _first_segment(doc: dict[str, Any], verse_key: str) -> dict[str, Any] | None:
    for seg in doc.get("segments") or []:
        if isinstance(seg, dict) and seg.get("ref") == verse_key:
            return seg
    return None


def _letters_text(word: Any) -> str:
    try:
        return "".join(str(r[0]) for r in (word[3] or []))
    except (IndexError, TypeError):
        return ""


def _verse_text(seg: dict[str, Any]) -> str:
    return " ".join(_letters_text(w) for w in (seg.get("words") or []))


def _indexable_phones(word: Any) -> list[str]:
    """Word phone strings in the word-local indexable coordinate space."""
    try:
        phones = word[4] or []
    except (IndexError, TypeError):
        return []
    out: list[str] = []
    for row in phones:
        try:
            p = str(row[0])
        except (IndexError, TypeError):
            continue
        if p in _RENDER_ONLY_PHONES:
            continue
        out.append(p)
    return out


def _word_at(seg: dict[str, Any], word_index: int) -> Any | None:
    words = seg.get("words") or []
    if 0 <= word_index < len(words):
        return words[word_index]
    return None


def _cell_for_letter(cells: list[CellRow], source_letter_index: int) -> CellRow | None:
    for c in cells:
        if c.source_letter_index == source_letter_index:
            return c
    return None


def _cell_snapshot(c: CellRow) -> dict[str, Any]:
    return {
        "chars": c.chars,
        "role": c.role,
        "status": c.status,
        "tag": c.tag,
        "secondary_tags": list(c.secondary_tags) if c.secondary_tags else [],
        "phoneme_rule_tags": list(c.phoneme_rule_tags) if c.phoneme_rule_tags else [],
        "share_group": c.share_group,
    }


def resolve_target(
    doc: dict[str, Any], verse_key: str, target: dict[str, Any]
) -> dict[str, Any] | None:
    """Resolve ``target`` against shard ``doc`` → a snapshot dict, or ``None``.

    ``None`` means the target no longer resolves (verse/word vanished) — a strong
    staleness signal. Snapshot keys mirror what ``repo_ts_reports`` persists
    (``chars``/``role``/``status``/``tag``/``secondary_tags``/``phoneme_rule_tags``/
    ``phones``/``share_group``/``word_text``/``verse_text``/``schema_version``).
    """
    seg = _first_segment(doc, verse_key)
    if seg is None:
        return None
    schema_version = (doc.get("_meta") or {}).get("schema_version")
    verse_text = _verse_text(seg)
    snap: dict[str, Any] = {"verse_text": verse_text, "schema_version": schema_version}

    kind = target.get("kind")
    if kind == "verse":
        return snap

    wi = target.get("word_index")
    word = _word_at(seg, wi) if isinstance(wi, int) else None
    if word is None:
        return None
    snap["word_text"] = _letters_text(word)
    if kind == "word":
        return snap

    cells = word_cells(word)
    if kind == "cell":
        ci = target.get("cell_index")
        c: CellRow | None = None
        if isinstance(ci, int) and 0 <= ci < len(cells):
            c = cells[ci]
        elif isinstance(target.get("source_letter_index"), int):
            c = _cell_for_letter(cells, target["source_letter_index"])
        if c is None:
            return None
        snap.update(_cell_snapshot(c))
        return snap

    if kind == "column":
        sli = target.get("source_letter_index")
        c = _cell_for_letter(cells, sli) if isinstance(sli, int) else None
        if c is None:
            return None
        snap.update(_cell_snapshot(c))
        idx = _indexable_phones(word)
        snap["phones"] = [idx[i] for i in c.phoneme_indices if 0 <= i < len(idx)]
        return snap

    if kind == "phoneme":
        pi = target.get("phoneme_flat_index")
        idx = _indexable_phones(word)
        if not isinstance(pi, int) or not (0 <= pi < len(idx)):
            return None
        snap["chars"] = idx[pi]
        owner = next((c for c in cells if pi in c.phoneme_indices), None)
        if owner is not None:
            snap["role"] = owner.role
            pos = owner.phoneme_indices.index(pi)
            rule = None
            if owner.phoneme_rule_tags and pos < len(owner.phoneme_rule_tags):
                rule = owner.phoneme_rule_tags[pos]
            snap["tag"] = rule if rule is not None else owner.tag
        return snap

    if kind == "cell_group":
        sg = target.get("share_group")
        group = [c for c in cells if c.share_group == sg] if sg is not None else []
        if not group:
            return None
        snap["chars"] = "".join(c.chars for c in group)
        snap["share_group"] = sg
        tags = sorted({c.tag for c in group if c.tag})
        snap["secondary_tags"] = tags
        return snap

    return None


def build_snapshot(slug: str, verse_key: str, target: dict[str, Any]) -> dict[str, Any] | None:
    """Snapshot the targeted shard content at report-create time. Best-effort:
    returns ``None`` when the shard is missing/unparseable (the report is still
    accepted, just without a drift fingerprint)."""
    try:
        chapter = int(verse_key.split(":", 1)[0])
    except (ValueError, IndexError):
        return None
    doc = _load_shard(slug, chapter)
    if doc is None:
        return None
    try:
        return resolve_target(doc, verse_key, target)
    except Exception:  # noqa: BLE001 — snapshot is best-effort, never block a report
        logger.exception("build_snapshot failed %s %s %r", slug, verse_key, target)
        return None


def _norm(v: Any) -> Any:
    """Normalize a snapshot field for comparison (lists → tuples, sets stable)."""
    if isinstance(v, list):
        return tuple(v)
    return v


def is_stale_after_restamp(report: dict[str, Any], doc: dict[str, Any]) -> bool:
    """Did the regenerated shard ``doc`` invalidate this open report?

    Compares only the category-relevant snapshot fields. ``audio`` is never
    auto-staled. A vanished target is always stale. Best-effort: if the original
    snapshot was never captured (no fingerprint), returns False to avoid false
    positives."""
    category = report.get("category")
    if category == "audio":
        return False

    old = report.get("snapshot") or {}
    new = resolve_target(doc, report["verse_key"], report.get("target") or {})
    if new is None:
        return True

    def differs(*fields: str) -> bool:
        return any(_norm(old.get(f)) != _norm(new.get(f)) for f in fields)

    if category == "timing":
        return differs("chars", "role")
    if category == "tajweed":
        return differs("chars", "role", "status", "tag", "secondary_tags", "phoneme_rule_tags")
    if category == "mapping":
        return differs("chars", "phones")
    # other / verse-level
    kind = (report.get("target") or {}).get("kind")
    if kind == "word":
        return differs("word_text")
    return differs("verse_text")


def recheck_reports_staleness(slug: str, affected_chapters: list[int] | None) -> int:
    """After a regeneration, flag open reports whose targeted content changed.

    Scoped to ``affected_chapters`` (or all open reports when ``None`` —
    full/unknown-scope regen). Reads each chapter's new shard once. Returns the
    number of reports newly flagged stale. Caller owns the transaction (the repo
    write assumes an active ``durable_transaction``)."""
    from services.db import repo_ts_reports

    open_reports = repo_ts_reports.list_open_for_recheck(slug, chapters=affected_chapters)
    if not open_reports:
        return 0
    shard_cache: dict[int, dict[str, Any] | None] = {}
    stale_ids: list[int] = []
    for report in open_reports:
        chapter = report["chapter"]
        if chapter not in shard_cache:
            shard_cache[chapter] = _load_shard(slug, chapter)
        doc = shard_cache[chapter]
        if doc is None:
            continue
        try:
            if is_stale_after_restamp(report, doc):
                stale_ids.append(report["id"])
        except Exception:  # noqa: BLE001 — one bad report must not abort the recheck
            logger.exception("staleness recheck failed for report %s", report.get("id"))
    return repo_ts_reports.mark_stale(stale_ids)
