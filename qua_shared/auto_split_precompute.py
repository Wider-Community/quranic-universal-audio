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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from qua_shared.mfa_runtime import MfaRuntime
from qua_shared.timestamps_pipeline import (
    DEFAULT_ALIGNER_MODEL,
    _worker_align,
    download_audio,
    load_audio_int16,
    slice_audio,
)
from qua_shared.timestamps_pipeline import (
    is_compound_cross_verse as _is_compound_cross_verse,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_INSPECTOR_DIR = _REPO_ROOT / "inspector"


def _ensure_inspector_helpers() -> None:
    """Put ``inspector/`` on ``sys.path`` so the pure parsing helpers under
    ``utils.*`` resolve.

    Done lazily (inside the functions that use them), NOT at module import:
    ``qua_shared`` ships in the qua_jobs image WITHOUT the ``inspector/`` tree,
    and jobs that only need a pure helper here (cut_release imports
    ``word_counts_from_surah_info``) must be able to import this module there.
    ``run_precompute`` — the only caller of the ``utils.*`` helpers — runs solely
    in the extraction context, where ``inspector/`` is present.
    """
    if str(_INSPECTOR_DIR) not in sys.path:
        sys.path.insert(0, str(_INSPECTOR_DIR))


log = logging.getLogger(__name__)

DEFAULT_BEAM = 50  # canonical pipeline beam (vs probe_mfa's 2)
DEFAULT_METHOD = "kalpy"
DEFAULT_PADDING = "none"  # match runtime auto_split._run_mfa
DEFAULT_BATCH_SIZE = 200  # fewer than probe_mfa (each seg = a sequence)
DEFAULT_WORKERS = 12
DEFAULT_DOWNLOAD_WORKERS = 8

# Frozen UUID5 namespace mirrored from inspector/domain/identity.py — must
# match exactly so derived UIDs equal the ones Inspector backfills at load
# time. Changing this invalidates every Inspector-issued UID.
_NAMESPACE_INSPECTOR = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _QueueItem(NamedTuple):
    refs: list[str]  # N per-section refs (sequence mode)
    wav_path: str
    segment_uid: str
    kind: str  # "cross_verse" | "repetition"
    section_word_counts: list[int]
    time_start_ms: int


def _derive_uid(chapter: int, original_index: int, start_ms: int) -> str:
    """Deterministic UUID5 — must match ``inspector/domain/identity.derive_uid``."""
    key = f"{chapter}:{original_index}:{start_ms}"
    return str(uuid.uuid5(_NAMESPACE_INSPECTOR, key))


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


# ---------------------------------------------------------------------------
# Word-count loading
# ---------------------------------------------------------------------------


def word_counts_from_surah_info(surah_info: dict) -> dict[tuple[int, int], int]:
    """Build the ``(surah, ayah) -> word_count`` map from a loaded surah_info dict.

    ``surah_info`` is ``{surah_str: {"verses": [{"verse": int, "num_words": int},
    ...]}}`` — the in-memory shape both publish/release jobs already hold.
    """
    counts: dict[tuple[int, int], int] = {}
    for surah_str, info in surah_info.items():
        surah = int(surah_str)
        for v in info.get("verses", []):
            counts[(surah, int(v["verse"]))] = int(v["num_words"])
    return counts


def load_verse_word_counts(repo_root: Path) -> dict[tuple[int, int], int]:
    """Build the ``(surah, ayah) -> word_count`` map from ``data/surah_info.json``.

    Mirrors what ``inspector.services.data_loader.get_word_counts`` returns,
    but reads from disk directly so the offline script doesn't have to wire
    up the inspector cache/bucket layer.
    """
    path = repo_root / "data" / "surah_info.json"
    with open(path, encoding="utf-8") as f:
        return word_counts_from_surah_info(json.load(f))


def load_chapter_urls(manifest_path: Path) -> dict[int, str]:
    """Build the ``chapter -> url`` map from a catalog ``audio_manifest`` sidecar.

    Inspector's catalog moved per-chapter URLs out of ``detailed.json`` into
    ``catalog/audio_manifest/<slug>.json`` (commit fdeaae0d). When neither
    ``entry.audio`` nor a staged ``audio/<ch>.mp3`` is available, the precompute
    falls back to URLs from this sidecar so it can still download chapter audio
    on demand.
    """
    with open(manifest_path, encoding="utf-8") as f:
        doc = json.load(f)
    chapters = doc.get("chapters") or {}
    urls: dict[int, str] = {}
    for ch_str, info in chapters.items():
        url = (info or {}).get("url") or ""
        if url:
            try:
                urls[int(ch_str)] = url
            except (TypeError, ValueError):
                continue
    return urls


# ---------------------------------------------------------------------------
# Cursor extraction (pure)
# ---------------------------------------------------------------------------


def _section_boundary_cuts(words: list[dict], section_word_counts: list[int]) -> list[int] | None:
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
# (cross-verse test reused from timestamps_pipeline so the offline precompute
#  and the timestamps-job guard agree).
# ---------------------------------------------------------------------------


def _build_seg_candidate(
    seg: dict,
    chapter: int,
    idx: int,
    verse_word_counts: dict[tuple[int, int], int],
) -> tuple[list[list[str]], list[str], list[int], str, str] | None:
    """Return ``(sections, refs, section_word_counts, kind, uid)`` or None.

    Skips segs that don't qualify for Auto Split (single-verse, no wrap) or
    that fail the offline preconditions (missing word counts, malformed ref).
    Decision tree matches ``compute_auto_split`` in inspector exactly:
    wrap → repetition; else compound multi-verse → cross-verse.
    """
    _ensure_inspector_helpers()
    from utils.references import cross_verse_sections
    from utils.repetitions import (
        compute_reading_sequence,
        count_words_in_section,
        section_refs_canonical,
    )

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
    section_word_counts = [count_words_in_section(s[0], s[1], verse_word_counts) for s in sections]
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
    audio_dir: Path | None = None,
    audio_manifest: Path | None = None,
    repo_root: Path | None = None,
    beam: int = DEFAULT_BEAM,
    method: str = DEFAULT_METHOD,
    padding: str = DEFAULT_PADDING,
    batch_size: int = DEFAULT_BATCH_SIZE,
    workers: int = DEFAULT_WORKERS,
    download_workers: int = DEFAULT_DOWNLOAD_WORKERS,
    runtime: MfaRuntime | None = None,
) -> Path | None:
    """Run the offline pre-compute and write the v1 sidecar.

    Reads ``<reciter_dir>/detailed.json``, enumerates every cross-verse /
    repetition candidate, slices its audio, batched-aligns through a local
    Kalpy MFA process pool, and writes ``<reciter_dir>/auto_split_v1.json``.

    Audio resolution order, per chapter:

    1. ``<audio_dir>/<chapter>.mp3`` if ``audio_dir`` is provided and the file
       exists — Katana fast-path, since extraction's audio_persist post-pass
       writes per-chapter MP3s right there.
    2. ``entry.audio`` URL/path from ``detailed.json`` (legacy pre-#fdeaae0d
       reciters).
    3. ``audio_manifest`` catalog sidecar URL — required for post-#fdeaae0d
       reciters whose ``detailed.json`` no longer carries ``entry.audio``.
       Defaults to ``<reciter_dir>/audio_manifest.json`` when not specified;
       skip silently if neither the explicit path nor the auto-detected one
       exists.

    Returns the sidecar path on success, or ``None`` when ``detailed.json``
    is missing.
    """
    reciter_dir = Path(reciter_dir).resolve()
    detailed_path = reciter_dir / "detailed.json"
    if not detailed_path.exists():
        log.error("detailed.json not found in %s", reciter_dir)
        return None

    audio_dir = Path(audio_dir).resolve() if audio_dir else None
    if audio_dir is not None and not audio_dir.is_dir():
        log.error("audio_dir does not exist or is not a directory: %s", audio_dir)
        return None

    chapter_urls: dict[int, str] = {}
    manifest_path = (
        Path(audio_manifest).resolve() if audio_manifest else (reciter_dir / "audio_manifest.json")
    )
    if manifest_path.is_file():
        try:
            chapter_urls = load_chapter_urls(manifest_path)
            log.info("Loaded %d chapter URLs from %s", len(chapter_urls), manifest_path)
        except Exception as e:  # noqa: BLE001
            log.warning("Failed to load audio_manifest %s: %s", manifest_path, e)
    elif audio_manifest is not None:
        log.warning("audio_manifest %s not found; URL fallback disabled", manifest_path)

    repo_root = repo_root or _REPO_ROOT
    verse_word_counts = load_verse_word_counts(repo_root)

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

    _ensure_inspector_helpers()
    from utils.references import chapter_from_ref

    def _process_chapter(entry: dict) -> int:
        ref = entry.get("ref", "")
        chapter = chapter_from_ref(ref) if ref else None
        audio_src = entry.get("audio", "")
        if chapter is None:
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

        local_mp3 = audio_dir / f"{chapter}.mp3" if audio_dir else None
        manifest_url = chapter_urls.get(chapter, "") if chapter_urls else ""
        if (
            not audio_src
            and not (local_mp3 is not None and local_mp3.is_file())
            and not manifest_url
        ):
            return 0
        try:
            if local_mp3 is not None and local_mp3.is_file():
                audio_int16 = load_audio_int16(local_mp3)
            elif _is_url(audio_src):
                if local_mp3 is not None:
                    log.warning("Chapter %s: local %s missing; falling back to URL", ref, local_mp3)
                audio_file = download_audio(audio_src)
                audio_int16 = load_audio_int16(audio_file)
                audio_file.unlink(missing_ok=True)
            elif audio_src:
                audio_int16 = load_audio_int16(Path(audio_src))
            else:
                audio_file = download_audio(manifest_url)
                audio_int16 = load_audio_int16(audio_file)
                audio_file.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            log.warning(
                "Chapter %s: audio load failed (%s); skipping %d candidates",
                ref,
                e,
                len(cand_descriptors),
            )
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
            seg_queue.put(
                _QueueItem(
                    refs=list(refs),
                    wav_path=str(wav_path),
                    segment_uid=uid,
                    kind=kind,
                    section_word_counts=list(section_word_counts),
                    time_start_ms=t_start,
                )
            )
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

    # Pool ownership: reuse caller-provided runtime if given, else open
    # a self-contained pool. See qua_shared/mfa_runtime.py.
    owned_runtime: MfaRuntime | None = None
    if runtime is None:
        owned_runtime = MfaRuntime(mfa_app_path, workers)
        owned_runtime.__enter__()
    pool = (runtime or owned_runtime).pool
    try:
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
            fut = pool.submit(
                _worker_align, list(buf_refs), list(buf_paths), method, beam, False, padding
            )
            futures[fut] = bid
            buf_refs.clear()
            buf_paths.clear()
            buf_uids.clear()
            buf_kinds.clear()
            buf_swc.clear()
            buf_tstart.clear()

        while True:
            try:
                item = seg_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                _flush()
                break
            buf_refs.append(item.refs)  # list[str] per seg (sequence mode)
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
                log.warning(
                    "Batch %d crashed (%s); dropping all %d candidates", bid, e, len(state["uids"])
                )
                for p in state["paths"]:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
                del batch_state[bid]
                n_done += 1
                continue

            for uid, kind, swc, t_start, refs, item in zip(
                state["uids"],
                state["kinds"],
                state["swc"],
                state["tstart"],
                state["refs"],
                results,
                strict=False,
            ):
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
                try:
                    os.unlink(p)
                except OSError:
                    pass
            del batch_state[bid]
            n_done += 1
            if n_done % 5 == 0 or n_done == n_total:
                log.info("Aligned: %d/%d batches", n_done, n_total)
    finally:
        if owned_runtime is not None:
            owned_runtime.__exit__(None, None, None)

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
    log.info("Wrote %s (%d hits / %d candidates)", sidecar_path, len(by_uid), candidate_count)
    return sidecar_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(
        description="Pre-compute the Auto Split cursor sidecar for a reciter."
    )
    p.add_argument(
        "--reciter-dir", required=True, type=Path, help="Directory containing detailed.json."
    )
    p.add_argument(
        "--mfa-app-path", required=True, type=Path, help="Path to the local MFA aligner module."
    )
    p.add_argument(
        "--audio-dir",
        type=Path,
        default=None,
        help="Optional dir holding per-chapter MP3s named <chapter>.mp3 "
        "(extraction's audio_persist output). Read from local file "
        "instead of the URL in detailed.json; falls back to URL on miss.",
    )
    p.add_argument("--beam", type=int, default=DEFAULT_BEAM)
    p.add_argument("--method", default=DEFAULT_METHOD)
    p.add_argument("--padding", default=DEFAULT_PADDING)
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--download-workers", type=int, default=DEFAULT_DOWNLOAD_WORKERS)
    p.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repo root (used to find data/surah_info.json). Defaults to two levels above this script.",
    )
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
        audio_dir=args.audio_dir,
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
