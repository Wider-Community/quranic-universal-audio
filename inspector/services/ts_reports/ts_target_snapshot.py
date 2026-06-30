"""Resolve a report target against a shard → content snapshot + staleness diff.

A Timestamps report points at a flexible target (verse / word / cell / phoneme /
cell-group). There is no per-cell hash anywhere, so the denormalized
*snapshot* of the targeted shard content captured at create time IS the drift
fingerprint: when a reciter's shards are regenerated, each open report's target
is re-resolved against the new shard and the report is flagged ``stale`` iff its
**category-relevant** fields changed.

What "changed" means per category (the report stays valid otherwise — e.g. a
regen that only shifts timing ms does NOT stale a timing report):
- ``tajweed`` — rule tags / silence (role/status) / cell chars changed.
- ``phonemes`` — the targeted phone's identity (chars / role / rule) changed.
  A bridge (cross-word merger) phoneme targets ``phoneme_flat_index = -1`` and is
  resolved by walking the words for the merger phone rendered before the target
  word (see ``_bridge_phone_for_target``).
- ``timing`` — the reported cell's identity (chars/role) changed or vanished, OR
  a boundary the report flagged (onset/offset) moved past
  ``config.TS_REPORT_BOUNDARY_STALE_MS`` (a pure ms shift on an unflagged boundary
  does NOT stale).
- ``silence`` — gap reports don't just stale, they **auto-resolve** when the data
  confirms them: a ``pause_missed`` resolves once a gap appears at its boundary, a
  ``pause_wasl`` (and a ``pause_boundary`` whose gap vanished) once the gap is gone.
  A ``pause_boundary`` whose gap remains stales on a flagged-boundary shift (like
  timing). Auto-resolve notifies BOTH owners and the reporter. See
  ``_silence_action`` + ``recheck_reports_staleness``.
- ``audio``  — never auto-staled (not bound to shard cells).
- ``other`` / verse-level — the verse vanished or its text changed.

Flask-free. Reads shards via ``services/storage/data_dir`` and parses cells via
``qua_shared/ts_shard_cells`` (the same primitives the offline pipeline uses).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from config import TS_REPORT_BOUNDARY_STALE_MS
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


def _indexable_phone_rows(word: Any) -> list[Any]:
    """Word phone ROWS (``[phone, start_ms, end_ms, ...]``) in the word-local
    indexable coordinate space (render-only markers like ``Q`` excluded)."""
    try:
        phones = word[4] or []
    except (IndexError, TypeError):
        return []
    out: list[Any] = []
    for row in phones:
        try:
            p = str(row[0])
        except (IndexError, TypeError):
            continue
        if p in _RENDER_ONLY_PHONES:
            continue
        out.append(row)
    return out


def _row_bounds(rows: Any, idx: int) -> tuple[int | None, int | None]:
    """``(start_ms, end_ms)`` from a letter/phone row at ``idx``; ``(None, None)``
    on a miss or null timing."""
    try:
        r = rows[idx]
        return r[1], r[2]
    except (IndexError, TypeError):
        return None, None


def _word_bounds(word: Any) -> tuple[int | None, int | None]:
    try:
        return word[1], word[2]
    except (IndexError, TypeError):
        return None, None


def _letter_bounds(word: Any, source_letter_index: Any) -> tuple[int | None, int | None]:
    """Boundary ms of a cell's anchoring letter (``None`` for an implicit cell)."""
    if not isinstance(source_letter_index, int) or source_letter_index < 0:
        return None, None
    try:
        letters = word[3] or []
    except (IndexError, TypeError):
        return None, None
    return _row_bounds(letters, source_letter_index)


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


def _bridge_phone_for_target(seg: dict[str, Any], target_word: int) -> dict[str, Any] | None:
    """Resolve a cross-word merger (bridge) phoneme rendered before ``target_word``.

    A merger phone carries a bridge rule in its phone row's 6th slot (``row[5]``);
    it renders before its own block when it is the word's first phone (``k == 0``)
    and before the NEXT block otherwise (cross-word idgham), mirroring the FE
    ``rendered-blocks`` lift. The iltiqaa-kasra connector is a bridge with no rule
    slot — found via its cell tag on the preceding word. Returns
    ``{chars, tag, onset_ms, offset_ms}`` or ``None``."""
    words = seg.get("words") or []
    for wi, word in enumerate(words):
        try:
            phones = word[4] or []
        except (IndexError, TypeError):
            continue
        for k, row in enumerate(phones):
            try:
                rule = row[5] if len(row) > 5 else None
            except (IndexError, TypeError):
                rule = None
            if not rule:
                continue
            if (wi if k == 0 else wi + 1) != target_word:
                continue
            start, end = _row_bounds(phones, k)
            return {"chars": str(row[0]), "tag": str(rule), "onset_ms": start, "offset_ms": end}
    src = _word_at(seg, target_word - 1)
    if src is not None:
        rows = _indexable_phone_rows(src)
        for c in word_cells(src):
            if c.tag == "iltiqaa_kasra" and c.phoneme_indices:
                pidx = c.phoneme_indices[0]
                if 0 <= pidx < len(rows):
                    start, end = _row_bounds(rows, pidx)
                    return {
                        "chars": str(rows[pidx][0]),
                        "tag": "iltiqaa_kasra",
                        "onset_ms": start,
                        "offset_ms": end,
                    }
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
    ``phones``/``share_group``/``word_text``/``verse_text``/``schema_version`` plus
    ``onset_ms``/``offset_ms``, the target's boundary ms for timing staleness).
    """
    seg = _first_segment(doc, verse_key)
    if seg is None:
        return None
    schema_version = (doc.get("_meta") or {}).get("schema_version")
    verse_text = _verse_text(seg)
    snap: dict[str, Any] = {"verse_text": verse_text, "schema_version": schema_version}

    kind = target.get("kind")
    if kind == "verse":
        t = seg.get("t") or []
        snap["onset_ms"], snap["offset_ms"] = (t[0], t[1]) if len(t) >= 2 else (None, None)
        return snap

    wi = target.get("word_index")
    word = _word_at(seg, wi) if isinstance(wi, int) else None
    if word is None:
        return None
    snap["word_text"] = _letters_text(word)
    if kind == "word":
        snap["onset_ms"], snap["offset_ms"] = _word_bounds(word)
        return snap

    if kind == "gap":
        # A silence report's word-boundary gap: onset = this word's end, offset =
        # the next word's start. Gap-present iff offset > onset (a positive
        # inter-word silence). A missing next word means the structure changed.
        nxt = _word_at(seg, wi + 1) if isinstance(wi, int) else None
        if nxt is None:
            return None
        snap["onset_ms"] = _word_bounds(word)[1]
        snap["offset_ms"] = _word_bounds(nxt)[0]
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
        snap["onset_ms"], snap["offset_ms"] = _letter_bounds(word, c.source_letter_index)
        return snap

    if kind == "phoneme":
        pi = target.get("phoneme_flat_index")
        if isinstance(pi, int) and pi < 0 and isinstance(wi, int):
            # A bridge (cross-word merger) phoneme: ``word_index`` is the rendered
            # target word; the merger phone lives in the source word.
            bridge = _bridge_phone_for_target(seg, wi)
            if bridge is None:
                return None
            snap.update(bridge)
            return snap
        rows = _indexable_phone_rows(word)
        if not isinstance(pi, int) or not (0 <= pi < len(rows)):
            return None
        snap["chars"] = str(rows[pi][0])
        snap["onset_ms"], snap["offset_ms"] = _row_bounds(rows, pi)
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
        bounds = [_letter_bounds(word, c.source_letter_index) for c in group]
        starts = [s for s, _ in bounds if s is not None]
        ends = [e for _, e in bounds if e is not None]
        snap["onset_ms"] = min(starts) if starts else None
        snap["offset_ms"] = max(ends) if ends else None
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


def _shifted(a: Any, b: Any, threshold_ms: int) -> bool:
    """Did a boundary move beyond the threshold? Needs both ms known."""
    return isinstance(a, int) and isinstance(b, int) and abs(a - b) > threshold_ms


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
        # Identity change (the cell vanished / became a different letter) always
        # stales. Otherwise, only a move of a boundary THIS report flagged past
        # the threshold stales it — a shift on an unflagged boundary is ignored.
        if differs("chars", "role"):
            return True
        thr = TS_REPORT_BOUNDARY_STALE_MS
        if report.get("onset") and _shifted(old.get("onset_ms"), new.get("onset_ms"), thr):
            return True
        if report.get("offset") and _shifted(old.get("offset_ms"), new.get("offset_ms"), thr):
            return True
        return False
    if category == "tajweed":
        return differs("chars", "role", "status", "tag", "secondary_tags", "phoneme_rule_tags")
    if category == "phonemes":
        return differs("chars", "role", "tag")
    # other / verse-level
    kind = (report.get("target") or {}).get("kind")
    if kind == "word":
        return differs("word_text")
    return differs("verse_text")


def _gap_present(snap: dict[str, Any] | None) -> bool:
    """Is there a positive inter-word silence in this gap snapshot?"""
    if not snap:
        return False
    onset, offset = snap.get("onset_ms"), snap.get("offset_ms")
    return isinstance(onset, int) and isinstance(offset, int) and offset > onset


def _silence_action(report: dict[str, Any], doc: dict[str, Any]) -> tuple[str, str | None]:
    """Decide a silence report's fate against the regenerated shard ``doc``.

    Returns ``("resolve", reason)`` to auto-resolve (the data now agrees with the
    report), ``("stale", None)`` for owner re-check, or ``("none", None)`` to leave
    it open. A vanished target (word structure changed) stales for re-check."""
    new = resolve_target(doc, report["verse_key"], report.get("target") or {})
    if new is None:
        return "stale", None
    subtype = report.get("subtype")
    now_gap = _gap_present(new)
    if subtype == "pause_missed":
        return ("resolve", "A pause now appears here on the latest timestamps.") if now_gap else ("none", None)
    if subtype == "pause_wasl":
        return ("none", None) if now_gap else ("resolve", "This pause is gone on the latest timestamps.")
    if subtype == "pause_boundary":
        if not now_gap:
            return "resolve", "This pause is gone on the latest timestamps."
        old = report.get("snapshot") or {}
        thr = TS_REPORT_BOUNDARY_STALE_MS
        if report.get("onset") and _shifted(old.get("onset_ms"), new.get("onset_ms"), thr):
            return "stale", None
        if report.get("offset") and _shifted(old.get("offset_ms"), new.get("offset_ms"), thr):
            return "stale", None
        return "none", None
    return "none", None


def recheck_reports_staleness(slug: str, affected_chapters: list[int] | None) -> int:
    """After a regeneration, flag/resolve open reports whose targeted content changed.

    Scoped to ``affected_chapters`` (or all open reports when ``None`` —
    full/unknown-scope regen). Reads each chapter's new shard once. Non-silence
    reports stale via ``is_stale_after_restamp``; silence reports route through
    ``_silence_action`` and may **auto-resolve** (notifying both owners and the
    reporter) when a gap appeared/disappeared. Returns the number of reports newly
    flagged stale. Caller owns the transaction (the repo writes + the notification
    fan all assume an active ``durable_transaction``, which is nesting-safe)."""
    from services.db import repo_ts_reports

    open_reports = repo_ts_reports.list_open_for_recheck(slug, chapters=affected_chapters)
    if not open_reports:
        return 0
    shard_cache: dict[int, dict[str, Any] | None] = {}
    stale_ids: list[int] = []
    auto_resolve: list[tuple[dict[str, Any], str]] = []
    for report in open_reports:
        chapter = report["chapter"]
        if chapter not in shard_cache:
            shard_cache[chapter] = _load_shard(slug, chapter)
        doc = shard_cache[chapter]
        if doc is None:
            continue
        try:
            if report.get("category") == "silence":
                action, reason = _silence_action(report, doc)
                if action == "stale":
                    stale_ids.append(report["id"])
                elif action == "resolve" and reason is not None:
                    auto_resolve.append((report, reason))
            elif is_stale_after_restamp(report, doc):
                stale_ids.append(report["id"])
        except Exception:  # noqa: BLE001 — one bad report must not abort the recheck
            logger.exception("staleness recheck failed for report %s", report.get("id"))
    _auto_resolve_silence(slug, auto_resolve)
    return repo_ts_reports.mark_stale(stale_ids)


def _auto_resolve_silence(slug: str, auto_resolve: list[tuple[dict[str, Any], str]]) -> None:
    """Resolve each agreed silence report + notify both owners and the reporter."""
    if not auto_resolve:
        return
    from services.db import repo_ts_reports
    from services.notifications import emit as _notify

    for report, reason in auto_resolve:
        try:
            row = repo_ts_reports.resolve_auto(report_id=report["id"], reason=reason)
            if row is None:
                continue
            _notify.notify_ts_report_auto_resolved(
                slug=slug,
                verse_key=row["verse_key"],
                category=row["category"],
                reporter_id=row["hf_user_id"],
                author_login=row["login_at_time"],
                report_id=row["id"],
                reason=reason,
            )
        except Exception:  # noqa: BLE001 — best-effort; one failure must not abort the rest
            logger.exception("auto-resolve silence report %s failed", report.get("id"))
