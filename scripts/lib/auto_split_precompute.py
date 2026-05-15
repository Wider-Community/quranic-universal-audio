"""Pre-compute the Auto Split cursor sidecar (``auto_split_v1.json``).

Runtime auto-split used to call the MFA Space on every button click in the
Inspector (5–15 s per click — see ``inspector/services/auto_split.py``). This
script does the same alignment work offline, keyed by segment_uid, and writes
a sidecar that Inspector reads at boot. Sidecar hits answer in <10 ms.

Pattern mirrors ``probe_mfa.py``:
  - download chapter MP3 once per chapter (in-RAM int16 array)
  - slice each candidate seg
  - batch-submit to a local Kalpy MFA process pool
  - persist ``{by_uid: {segment_uid: {cursors, refs, kind}}}``

Candidate segs are exactly the two kinds Auto Split handles today:
  - **repetition** — any seg with ``wrap_word_ranges``; sections via
    ``compute_reading_sequence``.
  - **cross-verse** — any seg whose ``matched_ref`` is compound across at
    least two distinct verses; sections via ``cross_verse_sections``.

When MFA fails for a particular seg (alignment error, word-count mismatch,
audio missing) no entry is written — Inspector's FE flips that row back to
a plain Split button so the user can place the cursor manually.

Outputs ``<reciter_dir>/auto_split_v1.json``::

    {
      "_meta": {
        "created_at": ISO-8601 UTC,
        "aligner_model": str, "method": str, "beam": int,
        "reciter": str,
        "source_file_hash": "sha256:...",
        "candidate_count": int,
        "mfa_hit_count":   int
      },
      "by_uid": {
        "<segment_uid>": {
          "cursors": [int, ...],   # absolute ms, N-1 entries
          "refs":    [str, ...],   # N per-section refs
          "kind":    "cross_verse" | "repetition"
        },
        ...
      }
    }
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import sys
import tempfile
import threading
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Optional

from scripts.lib.timestamps_pipeline import (
    DEFAULT_ALIGNER_MODEL,
    _init_worker,
    _worker_align,
    download_audio,
    load_audio_int16,
    slice_audio,
)

# Reuse the inspector's pure parsing helpers — same code path so the offline
# pre-compute and the (now sidecar-only) runtime fallback agree byte-for-byte
# on sections/refs shape.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_INSPECTOR_DIR = _REPO_ROOT / "inspector"
if str(_INSPECTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_INSPECTOR_DIR))

# The order matters: `utils.references` is imported before `services.*` so
# inspector's runtime-only deps (Flask, audio_source, etc.) don't leak in.
from utils.references import chapter_from_ref, cross_verse_sections  # noqa: E402
from utils.repetitions import (  # noqa: E402
    compute_reading_sequence,
    count_words_in_section,
    section_refs_canonical,
)

log = logging.getLogger(__name__)

DEFAULT_BEAM = 50          # canonical pipeline beam (vs probe_mfa's 2)
DEFAULT_METHOD = "kalpy"
DEFAULT_PADDING = "none"   # match runtime auto_split._run_mfa
DEFAULT_BATCH_SIZE = 200   # fewer than probe_mfa (each seg = a sequence)
DEFAULT_WORKERS = 12
DEFAULT_DOWNLOAD_WORKERS = 8

# Frozen UUID5 namespace mirrored from inspector/domain/identity.py — must
# match exactly so derived UIDs equal the ones Inspector backfills at load
# time. Changing this invalidates every Inspector-issued UID.
_NAMESPACE_INSPECTOR = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _QueueItem(NamedTuple):
    refs: list[str]                # N per-section refs (sequence mode)
    wav_path: str
    segment_uid: str
    kind: str                      # "cross_verse" | "repetition"
    section_word_counts: list[int]
    time_start_ms: int


def _derive_uid(chapter: int, original_index: int, start_ms: int) -> str:
    """Deterministic UUID5 — must match ``inspector/domain/identity.derive_uid``."""
    key = f"{chapter}:{original_index}:{start_ms}"
    return str(uuid.uuid5(_NAMESPACE_INSPECTOR, key))


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


# ---------------------------------------------------------------------------
# Word-count loading
# ---------------------------------------------------------------------------

def _load_verse_word_counts(repo_root: Path) -> dict[tuple[int, int], int]:
    """Build the ``(surah, ayah) -> word_count`` map from ``data/surah_info.json``.

    Mirrors what ``inspector.services.data_loader.get_word_counts`` returns,
    but reads from disk directly so the offline script doesn't have to wire
    up the inspector cache/bucket layer.
    """
    path = repo_root / "data" / "surah_info.json"
    with open(path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    counts: dict[tuple[int, int], int] = {}
    for surah_str, info in doc.items():
        surah = int(surah_str)
        for v in info.get("verses", []):
            counts[(surah, int(v["verse"]))] = int(v["num_words"])
    return counts


# ---------------------------------------------------------------------------
# Cursor extraction (pure)
# ---------------------------------------------------------------------------

def _section_boundary_cuts(words: list[dict],
                           section_word_counts: list[int]) -> Optional[list[int]]:
    """Return ``N-1`` segment-relative ms cuts between consecutive sections.

    Identical to ``inspector.services.auto_split._repetition_cuts`` —
    duplicated rather than imported to keep the offline script free of any
    inspector runtime dependency.
    """
    if not section_word_counts or not words:
        return None
    cuts: list[int] = []
    cursor = 0
    for count in section_word_counts[:-1]:
        cursor += count
        if cursor <= 0 or cursor >= len(words):
            return None
        prev_end = words[cursor - 1].get("end")
        next_start = words[cursor].get("start")
        if prev_end is None or next_start is None:
            return None
        cuts.append(round(((prev_end + next_start) / 2.0) * 1000))
    return cuts


# ---------------------------------------------------------------------------
# Candidate detection — exactly mirrors inspector's compute_auto_split dispatch
# ---------------------------------------------------------------------------

def _is_compound_cross_verse(matched_ref: str) -> bool:
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return False
    s, e = parts[0].split(":"), parts[1].split(":")
    return len(s) >= 2 and len(e) >= 2 and s[1] != e[1]


def _build_seg_candidate(seg: dict, chapter: int, idx: int,
                         verse_word_counts: dict[tuple[int, int], int],
                         ) -> Optional[tuple[list[list[str]], list[str], list[int], str, str]]:
    """Return ``(sections, refs, section_word_counts, kind, uid)`` or None.

    Skips segs that don't qualify for Auto Split (single-verse, no wrap) or
    that fail the offline preconditions (missing word counts, malformed ref).
    Decision tree matches ``compute_auto_split`` in inspector exactly:
    wrap → repetition; else compound multi-verse → cross-verse.
    """
    matched_ref = seg.get("matched_ref", "")
    if not matched_ref:
        return None
    t_start = int(seg.get("time_start", 0))
    t_end = int(seg.get("time_end", 0))
    if t_end <= t_start:
        return None

    wrap = seg.get("wrap_word_ranges") or None
    if wrap:
        parts = matched_ref.split("-")
        if len(parts) != 2:
            return None
        sections = compute_reading_sequence(parts[0], parts[1], wrap)
        if not sections or len(sections) < 2:
            return None
        kind = "repetition"
    elif _is_compound_cross_verse(matched_ref):
        sections = cross_verse_sections(matched_ref, verse_word_counts)
        if not sections or len(sections) < 2:
            return None
        kind = "cross_verse"
    else:
        return None

    refs = section_refs_canonical(sections)
    section_word_counts = [
        count_words_in_section(s[0], s[1], verse_word_counts) for s in sections
    ]
    if not all(c > 0 for c in section_word_counts):
        return None

    uid = seg.get("segment_uid") or _derive_uid(chapter, idx, t_start)
    return sections, refs, section_word_counts, kind, uid


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run_precompute(
    reciter_dir: Path,
    *,
    mfa_app_path: Path,
    repo_root: Path | None = None,
    beam: int = DEFAULT_BEAM,
    method: str = DEFAULT_METHOD,
    padding: str = DEFAULT_PADDING,
    batch_size: int = DEFAULT_BATCH_SIZE,
    workers: int = DEFAULT_WORKERS,
    download_workers: int = DEFAULT_DOWNLOAD_WORKERS,
) -> Path | None:
    """Run the offline pre-compute and write the v1 sidecar.

    Reads ``<reciter_dir>/detailed.json``, enumerates every cross-verse /
    repetition candidate, slices its audio, batched-aligns through a local
    Kalpy MFA process pool, and writes ``<reciter_dir>/auto_split_v1.json``.

    Returns the sidecar path on success, or ``None`` when ``detailed.json``
    is missing.
    """
    reciter_dir = Path(reciter_dir).resolve()
    detailed_path = reciter_dir / "detailed.json"
    if not detailed_path.exists():
        log.error("detailed.json not found in %s", reciter_dir)
        return None

    repo_root = repo_root or _REPO_ROOT
    verse_word_counts = _load_verse_word_counts(repo_root)

    with open(detailed_path, encoding="utf-8") as f:
        doc = json.load(f)
    entries = doc.get("entries", [])
    if not entries:
        log.warning("detailed.json has no entries; nothing to precompute")
        return None

    file_hash = _file_sha256(detailed_path)
    tmp_dir = Path(tempfile.mkdtemp(prefix="auto_split_pre_"))

    seg_queue: queue.Queue[_QueueItem | None] = queue.Queue(maxsize=batch_size * 2)
    by_uid: dict[str, dict] = {}
    candidate_count = 0

    def _process_chapter(entry: dict) -> int:
        ref = entry.get("ref", "")
        chapter = chapter_from_ref(ref) if ref else None
        audio_src = entry.get("audio", "")
        if chapter is None or not audio_src:
            return 0

        # Pre-scan: any candidates? If not skip the audio download entirely.
        cand_descriptors = []
        for idx, seg in enumerate(entry.get("segments", [])):
            built = _build_seg_candidate(seg, chapter, idx, verse_word_counts)
            if built is None:
                continue
            cand_descriptors.append((idx, seg, built))
        if not cand_descriptors:
            return 0

        try:
            if _is_url(audio_src):
                audio_file = download_audio(audio_src)
                audio_int16 = load_audio_int16(audio_file)
                audio_file.unlink(missing_ok=True)
            else:
                audio_int16 = load_audio_int16(Path(audio_src))
        except Exception as e:  # noqa: BLE001
            log.warning("Chapter %s: audio load failed (%s); skipping %d candidates",
                        ref, e, len(cand_descriptors))
            return 0

        count = 0
        for idx, seg, (_sections, refs, section_word_counts, kind, uid) in cand_descriptors:
            t_start = int(seg.get("time_start", 0))
            t_end = int(seg.get("time_end", 0))
            wav_path = tmp_dir / f"ch{chapter}_seg{idx:04d}.wav"
            try:
                slice_audio(audio_int16, t_start, t_end, wav_path)
            except Exception as e:  # noqa: BLE001
                log.warning("Chapter %s seg %d: slice failed: %s", ref, idx, e)
                continue
            seg_queue.put(_QueueItem(
                refs=list(refs),
                wav_path=str(wav_path),
                segment_uid=uid,
                kind=kind,
                section_word_counts=list(section_word_counts),
                time_start_ms=t_start,
            ))
            count += 1
        log.info("Chapter %s: queued %d candidates", ref, count)
        return count

    def _producer() -> None:
        try:
            with ThreadPoolExecutor(max_workers=download_workers) as ex:
                futs = [ex.submit(_process_chapter, e) for e in entries]
                done = 0
                for f in as_completed(futs):
                    try:
                        f.result()
                    except Exception as e:  # noqa: BLE001
                        log.warning("Chapter pre-scan/download failed: %s", e)
                    done += 1
                    if done % 10 == 0 or done == len(entries):
                        log.info("Pre-scan/download: %d/%d chapters", done, len(entries))
        finally:
            seg_queue.put(None)

    batch_state: dict[int, dict] = {}
    bid_counter = 0
    futures: dict = {}

    producer = threading.Thread(target=_producer, daemon=True)
    producer.start()

    with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
            initargs=(str(mfa_app_path), 1)) as pool:
        buf_refs: list[list[str]] = []
        buf_paths: list[str] = []
        buf_uids: list[str] = []
        buf_kinds: list[str] = []
        buf_swc: list[list[int]] = []
        buf_tstart: list[int] = []

        def _flush() -> None:
            nonlocal bid_counter
            if not buf_refs:
                return
            bid_counter += 1
            bid = bid_counter
            batch_state[bid] = {
                "paths": list(buf_paths),
                "uids": list(buf_uids),
                "kinds": list(buf_kinds),
                "swc": list(buf_swc),
                "tstart": list(buf_tstart),
                "refs": list(buf_refs),
            }
            log.info("Batch %d: submit %d candidates at beam=%d", bid, len(buf_refs), beam)
            fut = pool.submit(_worker_align,
                              list(buf_refs), list(buf_paths),
                              method, beam, False, padding)
            futures[fut] = bid
            buf_refs.clear(); buf_paths.clear(); buf_uids.clear()
            buf_kinds.clear(); buf_swc.clear(); buf_tstart.clear()

        while True:
            try:
                item = seg_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                _flush()
                break
            buf_refs.append(item.refs)         # list[str] per seg (sequence mode)
            buf_paths.append(item.wav_path)
            buf_uids.append(item.segment_uid)
            buf_kinds.append(item.kind)
            buf_swc.append(item.section_word_counts)
            buf_tstart.append(item.time_start_ms)
            candidate_count += 1
            if len(buf_refs) >= batch_size:
                _flush()
        producer.join()

        n_total = len(futures)
        n_done = 0
        for fut in as_completed(list(futures.keys())):
            bid = futures[fut]
            state = batch_state[bid]
            try:
                results = fut.result()
            except Exception as e:  # noqa: BLE001
                log.warning("Batch %d crashed (%s); dropping all %d candidates",
                            bid, e, len(state["uids"]))
                for p in state["paths"]:
                    try: os.unlink(p)
                    except OSError: pass
                del batch_state[bid]
                n_done += 1
                continue

            for uid, kind, swc, t_start, refs, item in zip(
                    state["uids"], state["kinds"], state["swc"], state["tstart"],
                    state["refs"], results):
                if not item or item.get("status") != "ok":
                    continue
                words = item.get("words") or []
                if not words or len(words) != sum(swc):
                    continue
                rel_cuts = _section_boundary_cuts(words, swc)
                if rel_cuts is None:
                    continue
                by_uid[uid] = {
                    "cursors": [t_start + c for c in rel_cuts],
                    "refs": refs,
                    "kind": kind,
                }

            for p in state["paths"]:
                try: os.unlink(p)
                except OSError: pass
            del batch_state[bid]
            n_done += 1
            if n_done % 5 == 0 or n_done == n_total:
                log.info("Aligned: %d/%d batches", n_done, n_total)

    try:
        tmp_dir.rmdir()
    except OSError:
        pass

    sidecar_path = reciter_dir / "auto_split_v1.json"
    payload = {
        "_meta": {
            "created_at": _utc_now(),
            "aligner_model": DEFAULT_ALIGNER_MODEL,
            "method": method,
            "beam": beam,
            "padding": padding,
            "reciter": reciter_dir.name,
            "source_file_hash": file_hash,
            "candidate_count": candidate_count,
            "mfa_hit_count": len(by_uid),
        },
        "by_uid": by_uid,
    }
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("Wrote %s (%d hits / %d candidates)",
             sidecar_path, len(by_uid), candidate_count)
    return sidecar_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        description="Pre-compute the Auto Split cursor sidecar for a reciter.")
    p.add_argument("--reciter-dir", required=True, type=Path,
                   help="Directory containing detailed.json.")
    p.add_argument("--mfa-app-path", required=True, type=Path,
                   help="Path to the local MFA aligner module.")
    p.add_argument("--beam", type=int, default=DEFAULT_BEAM)
    p.add_argument("--method", default=DEFAULT_METHOD)
    p.add_argument("--padding", default=DEFAULT_PADDING)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--download-workers", type=int, default=DEFAULT_DOWNLOAD_WORKERS)
    p.add_argument("--repo-root", type=Path, default=None,
                   help="Repo root (used to find data/surah_info.json). Defaults to two levels above this script.")
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose >= 2 else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    sidecar = run_precompute(
        args.reciter_dir,
        mfa_app_path=args.mfa_app_path,
        repo_root=args.repo_root,
        beam=args.beam,
        method=args.method,
        padding=args.padding,
        batch_size=args.batch_size,
        workers=args.workers,
        download_workers=args.download_workers,
    )
    return 0 if sidecar is not None else 1


if __name__ == "__main__":
    raise SystemExit(_main())
