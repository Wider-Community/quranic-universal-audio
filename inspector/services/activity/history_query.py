"""Query helpers for Segments-tab edit-history endpoint.

No Flask imports -- functions accept parameters and return plain dicts/lists.
Undo logic for reverse-applying history entries lives in ``services/undo.py``;
this module is read-only.
"""

from collections import Counter
import logging
import threading

from config import RECITATION_SEGMENTS_PATH as _DEFAULT_RECITATION_SEGMENTS_PATH
from services.storage import cache, data_dir
from utils.references import chapter_from_ref

logger = logging.getLogger(__name__)


# Categories that disappear from the validation accordion once the user
# has edited a segment from that card. The classifier consults the
# resolved-by-edit index instead of mutating ``ignored_categories``.
# ``cross_verse`` is excluded -- it's a hard structural rule. Self-resolving
# categories (``low_confidence``, ``failed``) are excluded because the
# classifier already drops them when ``confidence`` flips to 1.0.
RESOLVES_BY_EDIT_CATEGORIES: frozenset[str] = frozenset({
    "boundary_adj",
    "audio_bleeding",
    "repetitions",
})

# Legacy test seam: older unit tests monkeypatch this path directly. Production
# reads through data_dir; parse_history_for_reciter only consults this when the
# value has been monkeypatched away from the configured default.
RECITATION_SEGMENTS_PATH = _DEFAULT_RECITATION_SEGMENTS_PATH

_history_locks: dict[str, threading.Lock] = {}
_history_locks_guard = threading.Lock()


def _history_lock(reciter: str) -> threading.Lock:
    with _history_locks_guard:
        lock = _history_locks.get(reciter)
        if lock is None:
            lock = threading.Lock()
            _history_locks[reciter] = lock
        return lock


def parse_history_for_reciter(reciter: str) -> list[dict]:
    """Read every batch record from a reciter's edit_history.jsonl.

    Shared by undo.py (which needs raw records for batch lookup) and
    load_edit_history (which applies further filtering for the UI).
    Returns an empty list when the file is absent.
    """
    if RECITATION_SEGMENTS_PATH != _DEFAULT_RECITATION_SEGMENTS_PATH:
        import orjson

        path = RECITATION_SEGMENTS_PATH / reciter / "edit_history.jsonl"
        if not path.exists():
            return []
        out: list[dict] = []
        with path.open("rb") as fh:
            for raw in fh:
                line = raw.strip()
                if line:
                    out.append(orjson.loads(line))
        return out
    return list(data_dir.iter_edit_history(reciter))


_CHAPTER_TIME_RESET_TOLERANCE_MS = 500


def recover_strip_specials_chapter_per_op(batch: dict) -> dict[str, int]:
    """Per-op chapter recovery for a legacy ``strip_specials`` batch.

    Use case: snapshots written by the extraction pipeline prior to the
    chapter-stamping fix have ``chapter: null`` on every op, but the batch
    still carries ``chapters: [...]`` (the union of every chapter the
    post-pass touched). We can recover per-op chapter by exploiting two
    pipeline invariants:

    1. ``strip_special_segments`` iterates entries in detailed.json order
       (which is surah order for by-surah reciters), then iterates each
       entry's segs in time order. So within one chapter's contributions
       the op timestamps are monotonically increasing, and between
       chapters time resets toward zero (each chapter's audio is a
       separate per-chapter MP3, time-local).
    2. ``batch.chapters`` is sorted by the writer.

    Algorithm: walk ops; whenever ``op.time_start`` drops well below the
    previous op's ``time_end``, that's a chapter boundary. Group ops by
    those boundaries; pair group N with ``sorted(chapters)[N]``.

    Returns ``{op_id: chapter}`` for every resolvable op. Returns ``{}``
    when:
      - batch isn't ``strip_specials`` (waqf_sakt is single-chapter via
        ``batch.chapter``);
      - the batch has no ``chapters`` list;
      - group count ≠ chapter count (heuristic disagrees — refuse to
        guess; the caller falls back to its own resolution path).

    Validated on legacy Husary data: 117 ops + 112 batch.chapters yields
    112 groups → exact 1:1 mapping.
    """
    if batch.get("batch_type") != "strip_specials":
        return {}
    chapters = sorted(
        c for c in (batch.get("chapters") or []) if isinstance(c, int) and c > 0
    )
    if not chapters:
        return {}

    ops = batch.get("operations") or []
    groups: list[list[dict]] = []
    current: list[dict] = []
    prev_end = -1
    for op in ops:
        snap = (op.get("targets_before") or [{}])[0]
        if not isinstance(snap, dict):
            continue
        t0 = snap.get("time_start")
        t1 = snap.get("time_end")
        if not isinstance(t0, (int, float)) or not isinstance(t1, (int, float)):
            continue
        if current and t0 < prev_end - _CHAPTER_TIME_RESET_TOLERANCE_MS:
            groups.append(current)
            current = []
        current.append(op)
        prev_end = t1
    if current:
        groups.append(current)

    if len(groups) != len(chapters):
        logger.warning(
            "recover_strip_specials_chapter_per_op: heuristic group count "
            "%d ≠ batch.chapters count %d for batch %s; aborting recovery",
            len(groups), len(chapters), batch.get("batch_id"),
        )
        return {}

    out: dict[str, int] = {}
    for group, ch in zip(groups, chapters):
        for op in group:
            op_id = op.get("op_id")
            if isinstance(op_id, str):
                out[op_id] = ch
    return out


def _merge_batches_sharing_batch_id(batches: list[dict]) -> list[dict]:
    """Merge consecutive-like batches that share the same ``batch_id`` (multi-chapter saves).

    Preserves chronological order: the first occurrence of a ``batch_id`` anchors
    the merged row; later lines with the same id extend its ``operations``.
    """
    out: list[dict] = []
    anchor_index_by_id: dict[str, int] = {}

    for batch in batches:
        bid = batch.get("batch_id")
        if not isinstance(bid, str):
            out.append(batch)
            continue
        if bid not in anchor_index_by_id:
            anchor_index_by_id[bid] = len(out)
            merged = dict(batch)
            merged["operations"] = list(batch.get("operations") or [])
            out.append(merged)
            continue

        acc = out[anchor_index_by_id[bid]]
        acc["operations"].extend(batch.get("operations") or [])
        chs: set[int] = set()
        if isinstance(acc.get("chapter"), int):
            chs.add(acc["chapter"])
        if isinstance(batch.get("chapter"), int):
            chs.add(batch["chapter"])
        for c in acc.get("chapters") or []:
            if isinstance(c, int):
                chs.add(c)
        for c in batch.get("chapters") or []:
            if isinstance(c, int):
                chs.add(c)
        if chs:
            acc["chapters"] = sorted(chs)
            acc["chapter"] = None if len(chs) > 1 else next(iter(chs))
        acc["saved_at_utc"] = batch.get("saved_at_utc") or acc.get("saved_at_utc")

    return out


def load_edit_history(reciter: str) -> dict:
    """Return ``{batches, summary}`` for a reciter's edit_history.jsonl.

    Filters fully-reverted batches, strips per-op reverts, and aggregates
    summary statistics. Returns ``{"batches": [], "summary": None}`` when the
    reciter has no edit history file yet.
    """
    use_cache = RECITATION_SEGMENTS_PATH == _DEFAULT_RECITATION_SEGMENTS_PATH
    cached = cache.get_seg_edit_history(reciter) if use_cache else None
    if cached is not None:
        return cached

    with _history_lock(reciter):
        cached = cache.get_seg_edit_history(reciter) if use_cache else None
        if cached is not None:
            return cached

        raw_records = parse_history_for_reciter(reciter)
        return _load_edit_history_from_records(
            reciter, raw_records, cache_result=use_cache,
        )


def _enrich_snapshot_audio_urls(reciter: str, batches: list[dict]) -> None:
    """Fill ``audio_url`` on snapshots that have it empty/null.

    Only walks if any snapshot is missing an audio_url. Resolves per chapter
    from ``detailed.json`` (mirrors ``segments_query.get_chapter_data``). The
    chapter for each snapshot is taken from (in order): ``snapshot.chapter``
    (post-fix extraction), ``snapshot.matched_ref`` parse for real Quran refs,
    ``batch.chapter``, then the single value in ``batch.chapters`` if any.
    Snapshots whose chapter still can't be resolved are left untouched.
    """
    def _needs_enrichment() -> bool:
        for batch in batches:
            for op in batch.get("operations") or []:
                for snap in (op.get("targets_before") or []) + (op.get("targets_after") or []):
                    if not isinstance(snap, dict):
                        continue
                    if not snap.get("audio_url"):
                        return True
                    if not isinstance(snap.get("chapter"), int):
                        return True
        return False

    if not _needs_enrichment():
        return

    # Migration #5: source per-chapter audio URLs from the bucket
    # audio_manifest sidecar instead of detailed.json's ``entry.audio``
    # (which the extractor no longer writes). ``chapter_urls(reciter)``
    # returns ``{str_key: url}`` for both by_surah and by_ayah deliveries;
    # we int-cast the by_surah keys here since pipeline snapshots
    # enrich at chapter granularity.
    from services.audio.audio_meta import chapter_urls

    by_chapter: dict[int, str] = {}
    try:
        for key, url in chapter_urls(reciter).items():
            if ":" in str(key):
                continue  # by_ayah key — chapter enrichment only
            try:
                by_chapter[int(key)] = url
            except (TypeError, ValueError):
                continue
    except Exception:  # noqa: BLE001
        logger.exception(
            "history_query: chapter_urls failed during audio_url enrichment "
            "(reciter=%s)", reciter,
        )
        return

    if not by_chapter:
        return

    def _snap_chapter(snap: dict, batch: dict, recovered: dict[str, int],
                      op_id: str | None) -> int | None:
        ch = snap.get("chapter")
        if isinstance(ch, int) and ch > 0:
            return ch
        ref = snap.get("matched_ref", "")
        if isinstance(ref, str) and ref and ":" in ref:
            ch = chapter_from_ref(ref)
            if ch:
                return ch
        bch = batch.get("chapter")
        if isinstance(bch, int) and bch > 0:
            return bch
        bchs = batch.get("chapters") or []
        if len(bchs) == 1 and isinstance(bchs[0], int):
            return bchs[0]
        # Last resort: strip_specials per-op chapter recovery via the
        # time-reset heuristic. Caller passes the recovered map so we
        # compute it once per batch, not per snapshot.
        if op_id and op_id in recovered:
            return recovered[op_id]
        return None

    for batch in batches:
        # Compute strip-specials per-op chapter recovery once per batch.
        recovered = recover_strip_specials_chapter_per_op(batch)
        for op in batch.get("operations") or []:
            op_id = op.get("op_id") if isinstance(op.get("op_id"), str) else None
            for key in ("targets_before", "targets_after"):
                for snap in op.get(key) or []:
                    if not isinstance(snap, dict):
                        continue
                    if snap.get("audio_url"):
                        continue
                    ch = _snap_chapter(snap, batch, recovered, op_id)
                    if ch is None:
                        continue
                    url = by_chapter.get(ch)
                    if url:
                        snap["audio_url"] = url
                    # Also stamp the chapter on the snapshot so downstream
                    # consumers (frontend, peaks backfill) don't need to
                    # re-derive it.
                    if not isinstance(snap.get("chapter"), int):
                        snap["chapter"] = ch


def _load_edit_history_from_records(
    reciter: str,
    raw_records: list[dict],
    *,
    cache_result: bool = True,
) -> dict:
    if not raw_records:
        result = {"batches": [], "summary": None}
        if cache_result:
            cache.set_seg_edit_history(reciter, result)
        return result
    all_records = []
    fully_reverted_ids: set[str] = set()
    per_op_reverted: dict[str, set[str]] = {}
    for record in raw_records:
        if record.get("record_type") == "genesis":
            continue
        all_records.append(record)
        rbid = record.get("reverts_batch_id")
        if rbid:
            rop_ids = record.get("reverts_op_ids")
            if rop_ids:
                if rbid not in per_op_reverted:
                    per_op_reverted[rbid] = set()
                per_op_reverted[rbid].update(rop_ids)
            else:
                fully_reverted_ids.add(rbid)

    batches = []
    for record in all_records:
        if record.get("reverts_batch_id"):
            continue
        batch_id = record.get("batch_id")
        if batch_id in fully_reverted_ids:
            continue

        ops = record.get("operations", [])
        reverted_ops_for_batch = per_op_reverted.get(batch_id, set())
        if reverted_ops_for_batch:
            ops = [op for op in ops if op.get("op_id") not in reverted_ops_for_batch]
        if not ops and reverted_ops_for_batch:
            continue

        batch = {
            "batch_id": batch_id,
            "batch_type": record.get("batch_type"),
            "saved_at_utc": record.get("saved_at_utc"),
            "chapter": record.get("chapter"),
            "chapters": record.get("chapters"),
            "save_mode": record.get("save_mode"),
            "is_revert": False,
            "operations": ops,
        }
        if reverted_ops_for_batch:
            batch["reverted_op_ids"] = list(reverted_ops_for_batch)
        batches.append(batch)

    batches = _merge_batches_sharing_batch_id(batches)

    # Enrich pipeline-edit snapshots that lack ``audio_url``. Older
    # ``edit_history.jsonl`` records (written before the extraction fix that
    # stamps ``audio_url`` from the parent entry) carry ``audio_url: null`` on
    # every pipeline snapshot, which breaks History-row playback. Look up the
    # canonical audio URL per chapter from detailed.json once, then patch the
    # snapshots in place. Cache-friendly because ``load_edit_history`` caches
    # the post-enrichment result.
    _enrich_snapshot_audio_urls(reciter, batches)

    op_counts = Counter()
    fix_kind_counts = Counter()
    chapters_edited: set[int] = set()
    total_batches = 0

    for batch in batches:
        ops = batch.get("operations") or []
        if not ops:
            continue
        total_batches += 1
        ch = batch.get("chapter")
        if ch is not None:
            chapters_edited.add(ch)
        for mch in batch.get("chapters") or []:
            chapters_edited.add(mch)
        for op in ops:
            op_counts[op.get("op_type", "unknown")] += 1
            fix_kind_counts[op.get("fix_kind", "unknown")] += 1

    total_operations = sum(op_counts.values())
    summary = {
        "total_operations": total_operations,
        "total_batches": total_batches,
        "chapters_edited": len(chapters_edited),
        "op_counts": dict(op_counts),
        "fix_kind_counts": dict(fix_kind_counts),
    } if total_operations > 0 else None

    result = {"batches": batches, "summary": summary}
    if cache_result:
        cache.set_seg_edit_history(reciter, result)
    return result


def build_resolved_by_edit_index(reciter: str) -> dict[str, set[str]]:
    """Build ``{segment_uid: {category, ...}}`` from edit_history.jsonl.

    For every effective op (post revert/per-op-revert filtering) carrying an
    ``op_context_category`` in ``RESOLVES_BY_EDIT_CATEGORIES``, every uid in
    ``targets_after`` accumulates that category. The classifier consults this
    index and skips re-flagging those segments for those categories — which
    is what makes a card disappear once the user has edited from it, without
    writing to ``ignored_categories``.

    Returns an empty dict when the reciter has no edit history file.
    """
    history = load_edit_history(reciter)
    if not history.get("batches"):
        return {}
    out: dict[str, set[str]] = {}
    for batch in history.get("batches", []):
        for op in batch.get("operations", []):
            cat = op.get("op_context_category")
            if not isinstance(cat, str):
                continue
            if cat not in RESOLVES_BY_EDIT_CATEGORIES:
                continue
            for snap in op.get("targets_after") or []:
                uid = snap.get("segment_uid") if isinstance(snap, dict) else None
                if not uid:
                    continue
                out.setdefault(uid, set()).add(cat)
    return out
