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

    Cache-aware on the production path: subsequent calls in the same process
    return the cached parsed list without re-touching disk. Save appends to
    the cached list (no re-parse); undo also appends a revert batch.

    The legacy test seam (``RECITATION_SEGMENTS_PATH`` monkeypatched away
    from the default) bypasses the cache entirely so tests can rewrite the
    underlying JSONL between calls without manual cache invalidation.

    Shared by undo.py (which needs raw records for batch lookup),
    load_edit_history (which applies further filtering for the UI), and
    build_split_group_index / build_resolved_by_edit_index (derived indices).
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
    cached = cache.get_seg_history_batches(reciter)
    if cached is not None:
        return cached
    batches = list(data_dir.iter_edit_history(reciter))
    cache.set_seg_history_batches(reciter, batches)
    return batches


# ``recover_strip_specials_chapter_per_op`` (heuristic chapter recovery for
# legacy strip_specials batches without snapshot ``chapter`` stamps) was
# removed when Migration #5 made the stamp mandatory at extraction time.
# If you're hitting "chapter is null" issues, the data pre-dates Migration #5
# — fix the source by running ``.local/extraction/scripts/migrate_wip5_in_place.py``
# on the slug or by re-extracting. Don't reintroduce the heuristic.


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
        # Migration #5 contract: every snap carries ``chapter``. The
        # tier-2/3/4 legacy fallbacks (matched_ref parse, batch.chapter,
        # single-chapter batch.chapters, time-reset recovery) were
        # removed. Returning None when the stamp is missing pushes the
        # data fix back to extraction / migrate_wip5_in_place.
        return None

    for batch in batches:
        for op in batch.get("operations") or []:
            op_id = op.get("op_id") if isinstance(op.get("op_id"), str) else None
            for key in ("targets_before", "targets_after"):
                for snap in op.get(key) or []:
                    if not isinstance(snap, dict):
                        continue
                    if snap.get("audio_url"):
                        continue
                    ch = _snap_chapter(snap, batch, None, op_id)
                    if ch is None:
                        continue
                    url = by_chapter.get(ch)
                    if url:
                        snap["audio_url"] = url


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


_SPLIT_GROUP_MAX_PASSES = 32  # mirrors frontend/.../utils/constants.ts


def build_split_group_index(reciter: str) -> dict[str, list[str]]:
    """Build ``{root_uid: [descendant_uid, ...]}`` for every committed split.

    Walks every ``split_segment`` op in the cached edit-history batches and
    runs a fixpoint that transitively closes parent→children chains. For
    each uid that's been split (directly or via a descendant), the value
    lists ALL descendants reachable through committed splits.

    Backend supplies this on validation issue items as ``split_group_uids``
    so the frontend doesn't need to walk ``$historyData`` to render the
    accordion card with all split descendants. FE-side fixpoint still runs
    over the uncommitted op log.

    Cache-aware via ``cache.get_seg_split_group_index``. Pure function of
    ``parse_history_for_reciter(reciter)`` so save can extend it
    incrementally without re-parsing the JSONL.
    """
    cached = cache.get_seg_split_group_index(reciter)
    if cached is not None:
        return cached

    batches = parse_history_for_reciter(reciter)
    # Build parent → children adjacency from every split_segment op.
    children_of: dict[str, list[str]] = {}
    for batch in batches:
        for op in batch.get("operations") or []:
            if op.get("op_type") != "split_segment" and op.get("kind") != "split_segment":
                continue
            parents = op.get("targets_before") or []
            kids = op.get("targets_after") or []
            for p in parents:
                if not isinstance(p, dict):
                    continue
                p_uid = p.get("segment_uid")
                if not p_uid:
                    continue
                bucket = children_of.setdefault(p_uid, [])
                for c in kids:
                    if not isinstance(c, dict):
                        continue
                    c_uid = c.get("segment_uid")
                    if c_uid and c_uid not in bucket:
                        bucket.append(c_uid)

    # Transitive closure: for every uid that has children, walk descendants
    # to the full set with a guarded fixpoint (revert-removable cycles are
    # impossible in append-only history, but the guard is cheap).
    out: dict[str, list[str]] = {}
    for root_uid in children_of:
        group: list[str] = []
        seen: set[str] = {root_uid}
        frontier = [root_uid]
        for _ in range(_SPLIT_GROUP_MAX_PASSES):
            grew = False
            next_frontier: list[str] = []
            for uid in frontier:
                for child in children_of.get(uid, ()):
                    if child not in seen:
                        seen.add(child)
                        group.append(child)
                        next_frontier.append(child)
                        grew = True
            if not grew:
                break
            frontier = next_frontier
        if group:
            out[root_uid] = group

    cache.set_seg_split_group_index(reciter, out)
    return out


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
