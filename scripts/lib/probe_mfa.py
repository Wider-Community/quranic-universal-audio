"""Tight-beam MFA probe → ``low_confidence_v2.json`` sidecar.

Surfaces extraction-time segments whose audio fails to align under a narrow
MFA beam — an acoustic second-opinion to the DP/ASR ``confidence`` already
emitted by the segments stage. Inspector consumes the sidecar as the
*Low Confidence v2* accordion.

Outputs `<reciter_dir>/low_confidence_v2.json`:

    {
      "_meta": {
        "created_at": ISO-8601 UTC,
        "aligner_model": str, "method": str, "beam": int,
        "reciter": str,
        "source_file_hash": "sha256:...",   # detailed.json hash at probe time
      },
      "failures": [segment_uid, segment_uid, ...]
    }

UIDs match what the Inspector's ``backfill_entries_uids`` derives from
``(chapter, original_index, start_ms)`` so the sidecar joins cleanly to
the live segment dicts without any other anchor.

Parallelism mirrors ``timestamps_pipeline.process``: a thread pool fans
out audio download/slice while a process pool runs MFA alignment, both
sharing ``_init_worker`` / ``_worker_align`` from the timestamps module.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import tempfile
import threading
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from scripts.lib.mfa_runtime import MfaRuntime
from scripts.lib.timestamps_pipeline import (
    DEFAULT_ALIGNER_MODEL,
    _init_worker,
    _worker_align,
    build_mfa_ref,
    download_audio,
    load_audio_int16,
    slice_audio,
)

log = logging.getLogger(__name__)

DEFAULT_PROBE_BEAM = 2
DEFAULT_METHOD = "kalpy"
DEFAULT_PADDING = "forward"
DEFAULT_BATCH_SIZE = 500
DEFAULT_WORKERS = 24
DEFAULT_DOWNLOAD_WORKERS = 8

# Frozen UUID5 namespace mirrored from inspector/domain/identity.py — must
# match exactly so probed UIDs equal the ones Inspector backfills at load
# time. Changing this invalidates every Inspector-issued UID.
_NAMESPACE_INSPECTOR = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _QueueItem(NamedTuple):
    mfa_ref: str
    wav_path: str
    segment_uid: str


def _derive_uid(chapter: int, original_index: int, start_ms: int) -> str:
    """Deterministic UUID5 — must match ``inspector/domain/identity.derive_uid``."""
    key = f"{chapter}:{original_index}:{start_ms}"
    return str(uuid.uuid5(_NAMESPACE_INSPECTOR, key))


def _chapter_from_ref(ref: str) -> int | None:
    head = str(ref).split(":", 1)[0]
    try:
        return int(head)
    except ValueError:
        return None


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def run_probe(
    reciter_dir: Path,
    *,
    mfa_app_path: Path,
    audio_dir: Path | None = None,
    beam: int = DEFAULT_PROBE_BEAM,
    method: str = DEFAULT_METHOD,
    padding: str = DEFAULT_PADDING,
    batch_size: int = DEFAULT_BATCH_SIZE,
    workers: int = DEFAULT_WORKERS,
    download_workers: int = DEFAULT_DOWNLOAD_WORKERS,
    runtime: "MfaRuntime | None" = None,
) -> Path | None:
    """Run a tight-beam MFA probe and write the v2 sidecar.

    Reads ``<reciter_dir>/detailed.json``, derives Inspector-compatible
    UIDs for every probable segment, and runs alignment in parallel via a
    download ThreadPool feeding a process pool of MFA workers.

    When ``audio_dir`` is provided, chapter audio is read from
    ``<audio_dir>/<chapter>.mp3`` instead of the URL/path in ``detailed.json``
    — this is the Katana fast-path, since extraction's audio_persist post-pass
    has already written the per-chapter MP3s right there. Falls back to the
    ``detailed.json`` source per-chapter when a file is missing.

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

    with open(detailed_path, encoding="utf-8") as f:
        doc = json.load(f)
    entries = doc.get("entries", [])
    if not entries:
        log.warning("detailed.json has no entries; nothing to probe")
        return None

    file_hash = _file_sha256(detailed_path)
    tmp_dir = Path(tempfile.mkdtemp(prefix="mfa_probe_"))

    seg_queue: queue.Queue[_QueueItem | None] = queue.Queue(maxsize=batch_size * 2)
    failures: set[str] = set()

    def _process_chapter(entry: dict) -> int:
        ref = entry.get("ref", "")
        chapter = _chapter_from_ref(ref)
        audio_src = entry.get("audio", "")
        if chapter is None or not audio_src:
            log.warning("Chapter %s: missing chapter/audio; skipping", ref)
            return 0
        local_mp3 = audio_dir / f"{chapter}.mp3" if audio_dir else None
        try:
            if local_mp3 is not None and local_mp3.is_file():
                audio_int16 = load_audio_int16(local_mp3)
            elif _is_url(audio_src):
                if local_mp3 is not None:
                    log.warning("Chapter %s: local %s missing; falling back to URL",
                                ref, local_mp3)
                audio_file = download_audio(audio_src)
                audio_int16 = load_audio_int16(audio_file)
                audio_file.unlink(missing_ok=True)
            else:
                audio_int16 = load_audio_int16(Path(audio_src))
        except Exception as e:
            log.warning("Chapter %s: audio load failed (%s); skipping", ref, e)
            return 0

        count = 0
        for idx, seg in enumerate(entry.get("segments", [])):
            mfa_ref = build_mfa_ref(seg)
            if mfa_ref is None:
                continue
            t_start = int(seg.get("time_start", 0))
            t_end = int(seg.get("time_end", 0))
            if t_end <= t_start:
                continue
            uid = seg.get("segment_uid") or _derive_uid(chapter, idx, t_start)
            wav_path = tmp_dir / f"ch{chapter}_seg{idx:04d}.wav"
            try:
                slice_audio(audio_int16, t_start, t_end, wav_path)
            except Exception as e:
                log.warning("Chapter %s seg %d: slice failed: %s", ref, idx, e)
                continue
            seg_queue.put(_QueueItem(mfa_ref, str(wav_path), uid))
            count += 1
        log.info("Chapter %s: queued %d segments", ref, count)
        return count

    def _producer() -> None:
        try:
            with ThreadPoolExecutor(max_workers=download_workers) as ex:
                futs = [ex.submit(_process_chapter, e) for e in entries]
                done = 0
                for f in as_completed(futs):
                    try:
                        f.result()
                    except Exception as e:
                        log.warning("Chapter download failed: %s", e)
                    done += 1
                    if done % 10 == 0 or done == len(entries):
                        log.info("Downloads: %d/%d chapters", done, len(entries))
        finally:
            seg_queue.put(None)

    batch_state: dict[int, dict] = {}
    bid_counter = 0
    futures: dict = {}

    log.info("Probe: %d chapters, %d download workers, %d MFA workers, "
             "batch_size=%d, beam=%d",
             len(entries), download_workers, workers, batch_size, beam)

    producer = threading.Thread(target=_producer, daemon=True)
    producer.start()

    # Pool ownership: reuse caller-provided runtime if given, else open
    # a self-contained pool. Both paths drain through the same body.
    owned_runtime: MfaRuntime | None = None
    if runtime is None:
        owned_runtime = MfaRuntime(mfa_app_path, workers)
        owned_runtime.__enter__()
    pool = (runtime or owned_runtime).pool
    try:
        buf_refs: list[str] = []
        buf_paths: list[str] = []
        buf_uids: list[str] = []

        def _flush() -> None:
            nonlocal bid_counter
            if not buf_refs:
                return
            bid_counter += 1
            bid = bid_counter
            batch_state[bid] = {"paths": list(buf_paths), "uids": list(buf_uids)}
            log.info("Batch %d: submit %d segs at beam=%d",
                     bid, len(buf_refs), beam)
            fut = pool.submit(_worker_align,
                              list(buf_refs), list(buf_paths),
                              method, beam, False, padding)
            futures[fut] = bid
            buf_refs.clear(); buf_paths.clear(); buf_uids.clear()

        while True:
            try:
                item = seg_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                _flush()
                break
            buf_refs.append(item.mfa_ref)
            buf_paths.append(item.wav_path)
            buf_uids.append(item.segment_uid)
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
                for uid, item in zip(state["uids"], results):
                    if (item or {}).get("status") != "ok":
                        failures.add(uid)
            except Exception as e:
                log.warning("Batch %d crashed (%s); flagging all %d uids",
                            bid, e, len(state["uids"]))
                failures.update(state["uids"])
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

    sidecar_path = reciter_dir / "low_confidence_v2.json"
    payload = {
        "_meta": {
            "created_at": _utc_now(),
            "aligner_model": DEFAULT_ALIGNER_MODEL,
            "method": method,
            "beam": beam,
            "reciter": reciter_dir.name,
            "source_file_hash": file_hash,
        },
        "failures": sorted(failures),
    }
    with open(sidecar_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log.info("Wrote %s (%d failures)", sidecar_path, len(payload["failures"]))
    return sidecar_path
