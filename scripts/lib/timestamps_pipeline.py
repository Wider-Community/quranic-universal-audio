#!/usr/bin/env python3
"""Shared timestamp extraction pipeline.

Reads detailed.json from the segment extraction pipeline, downloads full
surah audio, slices segments, sends batches through a caller-provided MFA
backend, and writes timestamps.json / timestamps_full.json.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import queue
from datetime import datetime, timezone
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from scripts.lib.timestamps_shards import split_to_shards

if TYPE_CHECKING:
    import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SPACE_URL = "https://hetchyy-quran-phoneme-mfa-dev.hf.space"
DEFAULT_ALIGNER_MODEL = "quran_aligner_model"
DEFAULT_METHOD = "kalpy"
DEFAULT_BEAMS = [50]  # canonical beam first; additional entries are probes.
DEFAULT_WORKERS = 1
DEFAULT_PADDING = "forward"  # phoneme gap-padding strategy (forward|symmetric|none)
DEFAULT_TIMEOUT = 900
DEFAULT_BATCH_SIZE = 500  # segments per MFA upload
BATCH_DELAY_SECONDS = 5  # pause between MFA batches to avoid rate-limiting
DOWNLOAD_LOG_INTERVAL = 500  # log download progress every N verses
DEFAULT_DOWNLOAD_WORKERS = 8

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


class MfaBackend(Protocol):
    """Minimal backend contract used by the shared timestamp pipeline.

    Single beam per call — multi-beam fan-out is handled by the pipeline,
    which calls align_batch once per beam value. The MFA wire protocol
    keeps a (beam, retry_beam) pair internally; here retry_beam is set
    equal to beam, since a wider retry beam is now expressed as a
    separate beam value in the caller's beams list.
    """

    def align_batch(
        self,
        refs: Sequence[str],
        audio_paths: Sequence[str],
        *,
        method: str,
        beam: int,
        shared_cmvn: bool,
        padding: str,
        word_boundary_allocation: dict | None = None,
    ) -> list[dict] | None:
        """Return MFA results aligned one-to-one with refs/audio_paths."""


class SpaceMfaBackend:
    """HF Space backend that preserves the original Gradio HTTP protocol."""

    def __init__(
        self,
        base_url: str = DEFAULT_SPACE_URL,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = 1,
        batch_delay_seconds: int = BATCH_DELAY_SECONDS,
    ):
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.batch_delay_seconds = batch_delay_seconds

    def align_batch(
        self,
        refs: Sequence[str],
        audio_paths: Sequence[str],
        *,
        method: str,
        beam: int,
        shared_cmvn: bool,
        padding: str,
        word_boundary_allocation: dict | None = None,
    ) -> list[dict] | None:
        return _submit_with_retry(
            list(refs),
            list(audio_paths),
            self.base_url,
            method=method,
            beam=beam,
            shared_cmvn=shared_cmvn,
            padding=padding,
            word_boundary_allocation=word_boundary_allocation,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

    def after_batch(self) -> None:
        if self.batch_delay_seconds > 0:
            time.sleep(self.batch_delay_seconds)


class LocalMfaBackend:
    """Direct adapter around .local/spaces/mfa_aligner/app.py.

    Used when running on Katana / locally with the MFA Space code imported
    in-process (no HTTP). Single-thread aligner — the pipeline parallelises
    across beams and batches via a process pool, so this backend stays
    serial. ``mfa_app_path`` is captured so process-pool workers can
    re-import the module independently.
    """

    def __init__(self, app_path: Path, *, mfa_threads: int = 1):
        os.environ["MFA_NUM_THREADS"] = str(mfa_threads)
        self.app_path = Path(app_path).resolve()
        self.module = self._load_app_module(self.app_path)

    @staticmethod
    def _load_app_module(app_path: Path):
        import importlib.util
        spec = importlib.util.spec_from_file_location("local_mfa_aligner",
                                                       app_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Cannot import local MFA app: {app_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def align_batch(
        self,
        refs: Sequence[str],
        audio_paths: Sequence[str],
        *,
        method: str,
        beam: int,
        shared_cmvn: bool,
        padding: str,
        word_boundary_allocation: dict | None = None,
    ) -> list[dict] | None:
        class _FileObj:
            def __init__(self, name): self.name = name
        files = [_FileObj(str(p)) for p in audio_paths]
        wb_json = (json.dumps(word_boundary_allocation)
                   if word_boundary_allocation else "")
        result = self.module._api_align_batch_impl(
            "local_batch", list(refs), files, method,
            str(beam), str(beam),  # retry_beam=beam (no implicit retry)
            str(shared_cmvn).lower(), padding, wb_json)
        if result.get("status") != "ok":
            raise RuntimeError(f"Local MFA batch failed: {result}")
        return result["results"]


# ---------------------------------------------------------------------------
# Process-pool worker (top-level for picklability)
# ---------------------------------------------------------------------------

# Per-worker globals populated by the executor's initializer.
_WORKER = {"module": None}


def _init_worker(mfa_app_path: str, mfa_threads: int = 1):
    """ProcessPoolExecutor initializer: import the MFA app once per worker.

    Each worker gets a unique HOME under /tmp so MFA extracts its acoustic
    model into a worker-private ``~/Documents/MFA`` tree. This sidesteps the
    "Directory not empty" race that hits when N workers all target the
    same ``~/Documents/MFA/extracted_models`` path.
    """
    import importlib.util
    pid = os.getpid()
    # Worker HOMEs go under MFA_WORKER_BASE if set, else $TMPDIR (PBS
    # job-scratch — node-local SSD, plenty of space), else /tmp (last resort:
    # often a small tmpfs that fills up with N parallel model extractions).
    base = (os.environ.get("MFA_WORKER_BASE")
            or os.environ.get("TMPDIR")
            or "/tmp")
    home = f"{base}/mfa_w{pid}"
    os.makedirs(home + "/Documents/MFA", exist_ok=True)
    os.environ["HOME"] = home
    os.environ["MFA_NUM_THREADS"] = str(mfa_threads)
    # Single-thread the BLAS stack — workers themselves provide parallelism.
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(var, "1")
    spec = importlib.util.spec_from_file_location("local_mfa_aligner",
                                                   mfa_app_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _WORKER["module"] = module


def _worker_align(refs, audio_paths, method, beam, shared_cmvn, padding,
                  word_boundary_allocation=None):
    """ProcessPoolExecutor task: align one batch slice for one beam."""
    module = _WORKER["module"]
    if module is None:
        raise RuntimeError("Worker not initialized; missing MFA module.")

    class _FileObj:
        def __init__(self, name): self.name = name
    files = [_FileObj(p) for p in audio_paths]
    wb_json = (json.dumps(word_boundary_allocation)
               if word_boundary_allocation else "")
    result = module._api_align_batch_impl(
        f"w{os.getpid()}", list(refs), files, method,
        str(beam), str(beam),
        str(shared_cmvn).lower(), padding, wb_json)
    if result.get("status") != "ok":
        raise RuntimeError(f"Worker MFA batch failed: {result}")
    return result["results"]


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def _is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def download_audio(url: str) -> Path:
    """Download a URL to a temp file. Caller responsible for cleanup."""
    suffix = Path(url.split("?")[0]).suffix or ".mp3"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        with open(tmp.name, "wb") as out:
            out.write(resp.read())
    tmp.close()
    return Path(tmp.name)


def load_audio_int16(path: Path) -> np.ndarray:
    """Load audio as 16kHz mono int16 via ffmpeg."""
    import numpy as np
    cmd = [
        "ffmpeg", "-i", str(path),
        "-f", "s16le", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        "-v", "quiet",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True, check=True)
    return np.frombuffer(result.stdout, dtype=np.int16)


def slice_audio(audio_int16: np.ndarray, start_ms: int, end_ms: int,
                out_path: Path, sample_rate: int = 16000):
    """Slice int16 audio array and write to WAV file."""
    start_sample = int(start_ms * sample_rate / 1000)
    end_sample = int(end_ms * sample_rate / 1000)
    segment = audio_int16[start_sample:end_sample]
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(segment.tobytes())


# ---------------------------------------------------------------------------
# MFA ref building (adapted from quranic_universal_aligner/src/mfa.py)
# ---------------------------------------------------------------------------

def build_mfa_ref(seg: dict) -> str | None:
    """Build the MFA ref string for a segment from detailed.json.

    Returns None for segments that should be skipped (empty ref, low
    confidence, or transition segments like Amin/Takbir). The ref is derived
    only from the segment key.
    """
    matched_ref = seg.get("matched_ref", "")
    confidence = seg.get("confidence", 0)

    if not matched_ref or confidence <= 0:
        return None

    # Skip transition segments (non-verse refs without colons)
    if ":" not in matched_ref:
        return None

    return matched_ref


def _matched_ref_to_output_key(matched_ref: str) -> str | None:
    """Convert a segment matched_ref to its output key.

    Single-verse '1:1:1-1:1:4' → '1:1'
    Cross-verse  '37:151:3-37:152:2' → '37:151:3-37:152:2' (kept as-is)
    """
    # Strip Basmala/Isti'adha prefix if present (shouldn't be in raw
    # matched_ref, but guard against it)
    for prefix in ("Basmala+", "Isti'adha+"):
        if matched_ref.startswith(prefix):
            matched_ref = matched_ref[len(prefix):]

    parts = matched_ref.split("-")
    if len(parts) != 2:
        return None
    start_parts = parts[0].split(":")
    end_parts = parts[1].split(":")
    if len(start_parts) != 3 or len(end_parts) != 3:
        return None

    start_sura, start_ayah = start_parts[0], start_parts[1]
    end_ayah = end_parts[1]

    if start_ayah == end_ayah:
        return f"{start_sura}:{start_ayah}"
    else:
        return matched_ref  # compound key for cross-verse


def _seg_covered_ayahs(matched_ref: str) -> set[tuple[int, int]]:
    """Extract the set of (surah, ayah) pairs a segment's matched_ref covers.

    '1:1:1-1:1:4' → {(1,1)}
    '37:151:3-37:152:2' → {(37,151), (37,152)}
    """
    for prefix in ("Basmala+", "Isti'adha+"):
        if matched_ref.startswith(prefix):
            matched_ref = matched_ref[len(prefix):]
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return set()
    sp = parts[0].split(":")
    ep = parts[1].split(":")
    if len(sp) < 2 or len(ep) < 2:
        return set()
    try:
        s_surah, s_ayah = int(sp[0]), int(sp[1])
        e_surah, e_ayah = int(ep[0]), int(ep[1])
    except ValueError:
        return set()
    if s_surah == e_surah:
        return {(s_surah, a) for a in range(s_ayah, e_ayah + 1)}
    # Cross-surah (rare): just include the endpoints
    return {(s_surah, s_ayah), (e_surah, e_ayah)}


def _seg_is_home_for_key(matched_ref: str, output_key: str) -> bool:
    """Check if a segment's matched_ref is 'home' for an output verse key.

    A segment is home when its derived output key matches *output_key*.
    For example, segment ``"5:69:1-5:69:12"`` is home for ``"5:69"``
    but a cross-verse segment ``"5:69:8-5:70:2"`` is NOT home for ``"5:69"``
    (its derived key is the compound ``"5:69:8-5:70:2"``).
    """
    return _matched_ref_to_output_key(matched_ref) == output_key


def _repeat_pass_skip_indices(segments: list[dict]) -> set[int]:
    """Identify home segs that belong to a re-pass and should be skipped.

    Reciters sometimes re-recite a verse (or short run of verses) after
    moving on. The segmenter emits home segs for every pass, and keeping
    them all produces two disjoint copies of the same verse — the verse's
    `start`/`end` then spans both, manifesting downstream as a "verse
    overlap" against neighbours.

    The picker works at the *run* level rather than the seg level. A run
    for verse V is a maximal contiguous sequence of V's home segs in
    seg-order, allowed to be punctuated by cross-verse segs (which are
    transition audio, not a new home). A different home verse breaks the
    run.

    For each verse with multiple runs, the run that covers the widest set
    of widxs wins; on a tie the earliest run wins (so a clean first
    take is preferred over a clean re-pass of the same range). All segs
    in losing runs are skipped from timestamp extraction. Within the
    winning run, multi-seg coverage and within-verse stutter still flow
    through `_merge_seg_words`'s primary-append path unchanged.

    Picking by widx coverage handles the partial-then-complete shape
    (e.g. seg ``19:30:1-4`` then later ``19:30:1-8``): the fuller run
    wins, so the verse ends up complete instead of stuck at the early
    partial pass. Reciters don't jump forward and back-fill mid-pass, so
    we don't worry about merging widxs across runs.
    """
    runs_by_verse: dict[str, list[dict]] = {}
    cur_verse: str | None = None
    cur_run: dict | None = None

    def _finalize() -> None:
        nonlocal cur_verse, cur_run
        if cur_verse is not None and cur_run is not None:
            runs_by_verse.setdefault(cur_verse, []).append(cur_run)
        cur_verse = None
        cur_run = None

    for idx, seg in enumerate(segments):
        matched_ref = seg.get("matched_ref", "")
        if not matched_ref:
            continue
        out_key = _matched_ref_to_output_key(matched_ref)
        if out_key is None:
            continue
        # Cross-verse: out_key is the compound matched_ref itself —
        # transition audio, doesn't break the active home's run.
        is_single_home = ":" in out_key and "-" not in out_key
        if not is_single_home:
            continue

        widx_range = _declared_widx_range(matched_ref)
        if widx_range is None:
            continue
        seg_widxs = set(range(widx_range[0], widx_range[1] + 1))

        if cur_verse != out_key:
            _finalize()
            cur_verse = out_key
            cur_run = {"seg_idxs": [], "widxs": set()}
        cur_run["seg_idxs"].append(idx)
        cur_run["widxs"] |= seg_widxs

    _finalize()

    skip: set[int] = set()
    for runs in runs_by_verse.values():
        if len(runs) <= 1:
            continue
        # Wider coverage wins; earliest first-seg breaks ties.
        best = max(runs, key=lambda r: (len(r["widxs"]),
                                        -min(r["seg_idxs"])))
        for r in runs:
            if r is not best:
                skip.update(r["seg_idxs"])
    return skip


def _declared_widx_range(matched_ref: str) -> tuple[int, int] | None:
    """Return (W1, W2) widx range declared by a single-verse matched_ref.

    '27:37:1-27:37:11' → (1, 11). Cross-verse or malformed refs → None.
    Used to distinguish primary (widx within declared range) from bleed
    (MFA emitted a widx outside what the seg was supposed to align).
    """
    for prefix in ("Basmala+", "Isti'adha+"):
        if matched_ref.startswith(prefix):
            matched_ref = matched_ref[len(prefix):]
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return None
    sp = parts[0].split(":")
    ep = parts[1].split(":")
    if len(sp) != 3 or len(ep) != 3:
        return None
    if sp[:2] != ep[:2]:
        return None
    try:
        return int(sp[2]), int(ep[2])
    except ValueError:
        return None


def _merge_seg_words(entry: dict, matched_ref: str, verse_key: str,
                     verse_words: list) -> None:
    """Merge one seg's words for a verse_key into the accumulator entry.

    `entry` has shape {"words": list[list], "_provenance": list[bool]}
    (provenance aligned with words: True=primary, False=bleed).

    Contributions are classified primary when the seg is home for
    verse_key AND widx lies within the declared matched_ref range.
    Primaries append (multiple primaries at the same widx = legitimate
    within-verse repetition — both kept). Primaries supersede any prior
    bleed at the same widx. Bleeds dedupe: first-seen wins.
    """
    is_home = _seg_is_home_for_key(matched_ref, verse_key)
    declared = _declared_widx_range(matched_ref) if is_home else None
    for w in verse_words:
        widx = w[0]
        is_primary = (declared is not None
                      and declared[0] <= widx <= declared[1])
        has_primary = any(
            ew[0] == widx and ep
            for ew, ep in zip(entry["words"], entry["_provenance"]))
        has_bleed = any(
            ew[0] == widx and not ep
            for ew, ep in zip(entry["words"], entry["_provenance"]))
        if is_primary:
            if has_bleed:
                kept_w, kept_p = [], []
                for ew, ep in zip(entry["words"], entry["_provenance"]):
                    if ew[0] == widx and not ep:
                        continue
                    kept_w.append(ew)
                    kept_p.append(ep)
                entry["words"] = kept_w
                entry["_provenance"] = kept_p
            entry["words"].append(w)
            entry["_provenance"].append(True)
        else:
            if has_primary or has_bleed:
                continue
            entry["words"].append(w)
            entry["_provenance"].append(False)


def _ref_sort_key(ref_str: str):
    """Sort key for verse refs ('1:1') and compound refs ('37:151:3-37:152:2')."""
    parts = ref_str.split("-")
    nums = []
    for part in parts:
        nums.extend(int(x) for x in part.split(":"))
    # Pad for consistent comparison
    while len(nums) < 6:
        nums.append(0)
    return tuple(nums)


# ---------------------------------------------------------------------------
# Result conversion (MFA seconds → ms, compact format)
# ---------------------------------------------------------------------------

def _s_to_ms(val, offset_ms: int = 0):
    """Convert seconds (float or None) to integer milliseconds + offset."""
    if val is None:
        return None
    return round(val * 1000) + offset_ms


def _convert_word(w: dict, seg_offset_ms: int) -> list:
    """Convert a single MFA word to compact array format.

    Returns [word_idx, start_ms, end_ms, [[char,s,e],...], [[phone,s,e],...]].
    """
    word_idx = int(w["location"].rsplit(":", 1)[-1])
    letters = [
        [lt["char"],
         _s_to_ms(lt.get("start"), seg_offset_ms),
         _s_to_ms(lt.get("end"), seg_offset_ms)]
        for lt in w.get("letters", [])
    ]
    phones = [
        [p["phone"],
         _s_to_ms(p["start"], seg_offset_ms),
         _s_to_ms(p["end"], seg_offset_ms)]
        for p in w.get("phones", [])
    ]
    return [word_idx,
            _s_to_ms(w["start"], seg_offset_ms),
            _s_to_ms(w["end"], seg_offset_ms),
            letters, phones]


def _convert_result(result: dict, seg_offset_ms: int) -> list:
    """Convert MFA result to compact array format with absolute ms timestamps.

    seg_offset_ms is added to all MFA-relative timestamps to get absolute
    offsets within the source audio file.

    Returns words where each word is:
      [word_idx, start_ms, end_ms, [[char, start_ms, end_ms], ...], [[phone, start_ms, end_ms], ...]]

    Phones are nested per word from MFA's per-word 'phones' field (linguistically
    correct, derived from the phonemizer's per-word phoneme lists).
    """
    return [_convert_word(w, seg_offset_ms)
            for w in result.get("words", [])]


# ---------------------------------------------------------------------------
# MFA Space HTTP client (inline — no imports from quranic_universal_aligner)
# ---------------------------------------------------------------------------

def mfa_upload_and_submit(refs, audio_paths, base_url, *,
                          method=DEFAULT_METHOD, beam=DEFAULT_BEAMS[0],
                          shared_cmvn=False, padding=DEFAULT_PADDING,
                          word_boundary_allocation=None,
                          timeout=DEFAULT_TIMEOUT):
    """Upload audio files and submit alignment batch to the MFA Space.

    Returns (event_id, headers, base_url).
    """
    import requests

    hf_token = os.environ.get("HF_TOKEN", "")
    headers = {}
    if hf_token:
        headers["Authorization"] = f"Bearer {hf_token}"

    # Read all audio files into memory to avoid file descriptor limits
    files_payload = []
    for path in audio_paths:
        with open(path, "rb") as f:
            content = f.read()
        files_payload.append(("files", (os.path.basename(path), io.BytesIO(content), "audio/wav")))

    resp = requests.post(
        f"{base_url}/gradio_api/upload",
        headers=headers,
        files=files_payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    uploaded_paths = resp.json()

    # Build FileData objects
    file_data_list = [
        {"path": p, "meta": {"_type": "gradio.FileData"}}
        for p in uploaded_paths
    ]

    # Submit batch alignment
    wb_json = (json.dumps(word_boundary_allocation)
               if word_boundary_allocation else "")
    submit_resp = requests.post(
        f"{base_url}/gradio_api/call/align_batch",
        headers={**headers, "Content-Type": "application/json"},
        json={"data": [refs, file_data_list, method, str(beam), str(beam),
                        str(shared_cmvn).lower(), padding, wb_json]},
        timeout=timeout,
    )
    submit_resp.raise_for_status()
    event_id = submit_resp.json()["event_id"]
    return event_id, headers, base_url


def mfa_wait_result(event_id, headers, base_url, timeout=DEFAULT_TIMEOUT):
    """Wait for the MFA SSE stream and return parsed results list."""
    import requests

    sse_resp = requests.get(
        f"{base_url}/gradio_api/call/align_batch/{event_id}",
        headers=headers,
        stream=True,
        timeout=timeout,
    )
    sse_resp.raise_for_status()

    result_data = None
    current_event = None
    for line in sse_resp.iter_lines(decode_unicode=True):
        if line and line.startswith("event: "):
            current_event = line[7:]
        elif line and line.startswith("data: "):
            data_str = line[6:]
            if current_event == "complete":
                result_data = data_str
            elif current_event == "error":
                if data_str.strip() in ("null", ""):
                    raise RuntimeError(
                        "MFA align_batch failed: Space returned null error. "
                        "Check parameter count and Gradio input validation."
                    )
                raise RuntimeError(f"MFA align_batch SSE error: {data_str}")

    if result_data is None:
        raise RuntimeError("No data received from MFA align_batch SSE stream")

    parsed = json.loads(result_data)
    if isinstance(parsed, list) and len(parsed) == 1:
        parsed = parsed[0]

    if parsed is None:
        raise RuntimeError("MFA align_batch returned null result")

    if not isinstance(parsed, dict) or parsed.get("status") != "ok":
        raise RuntimeError(f"MFA align_batch failed: {parsed}")

    return parsed["results"]


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def _normalize_from_results(chapters, results_by_ch, audio_category):
    """Convert raw MFA results to per-chapter ordered occurrences + failures.

    The conversion + per-verse word routing half of the former
    ``_build_outputs`` closure, factored out so the deduped projection
    (``_dedup_core``) is shared between the live pipeline and the
    read-path ``canonical_occurrence`` (single implementation, no drift).

    Returns ``(norm, failures)`` where ``norm[ch_idx]`` is a list of
    occurrences in result order::

        {"ch_ref", "seg_index", "matched_ref", "time_start", "time_end",
         "words_by_verse": {verse_key: [converted_word, ...]}, "segment_uid"}

    No repeat-pass skip and no word merge — every accepted segment is one
    occurrence. Failed segments go to ``failures`` (carrying ``seg`` + ref
    so run contiguity can be reconstructed downstream).
    """
    by_surah = str(audio_category).startswith("by_surah")
    norm: dict[int, list] = {}
    failures: list[dict] = []
    for ch_idx, chapter in enumerate(chapters):
        ch_ref = str(chapter.get("ref", ""))
        segs = chapter.get("segments", [])
        verse_prefix = (f"{ch_ref}:" if (not by_surah and ":" in ch_ref) else None)
        ch_occ = []
        for seg_idx, result in results_by_ch.get(ch_idx, []):
            if seg_idx >= len(segs):
                continue
            seg = segs[seg_idx]
            matched_ref = seg.get("matched_ref", "")
            if result.get("status") != "ok":
                failures.append({
                    "verse": ch_ref, "seg": seg_idx,
                    "ref": matched_ref,
                    "error": result.get("error", "unknown"),
                })
                continue
            seg_offset_ms = seg.get("time_start", 0)
            seg_end_ms = seg.get("time_end", seg_offset_ms)
            raw_words = result.get("words", [])
            if verse_prefix is not None:
                raw_words = [w for w in raw_words
                             if w.get("location", "").startswith(verse_prefix)]
            words_by_verse: dict[str, list] = {}
            for w in raw_words:
                verse_key = w["location"].rsplit(":", 1)[0]
                words_by_verse.setdefault(verse_key, []).append(
                    _convert_word(w, seg_offset_ms))
            ch_occ.append({
                "ch_ref": ch_ref,
                "seg_index": seg_idx,
                "matched_ref": matched_ref,
                "time_start": seg_offset_ms,
                "time_end": seg_end_ms,
                "words_by_verse": words_by_verse,
                "segment_uid": seg.get("segment_uid"),
            })
        if ch_occ:
            norm[ch_idx] = ch_occ
    return norm, failures


def _dedup_core(chapters_norm, seed_existing, *, completed_surahs,
                completed_refs, refresh_surahs, audio_category):
    """Repeat-pass skip + word merge + verse bounds over normalized occurrences.

    The deduped half of the former ``_build_outputs`` closure. Operates on
    the normalized form (already-converted, verse-routed words) so the live
    pipeline (fresh results) and the read-path (stored v2) produce identical
    output. ``chapters_norm`` entries are
    ``{"ch_ref", "matched_refs": [positional matched_ref], "occurrences": [...]}``.

    Returns ``(full_data, words_data)``.
    """
    full_data: dict = dict(seed_existing) if seed_existing else {}
    words_data: dict = {}
    seg_bounds: dict[str, list[int]] = {}
    if seed_existing:
        for ref, val in seed_existing.items():
            words_data[ref] = [[w[0], w[1], w[2]] for w in val["words"]]
            vs = val.get("verse_start_ms")
            ve = val.get("verse_end_ms")
            if vs is not None and ve is not None:
                seg_bounds[ref] = [vs, ve]

    by_surah = str(audio_category).startswith("by_surah")
    for ch in chapters_norm:
        ch_ref = ch["ch_ref"]
        if seed_existing is not None:
            if by_surah:
                if ch_ref in completed_surahs and ch_ref not in (refresh_surahs or set()):
                    continue
            else:
                if ch_ref in completed_refs:
                    continue
        occurrences = ch["occurrences"]
        if not occurrences:
            continue

        if by_surah:
            repeat_skip = _repeat_pass_skip_indices(
                [{"matched_ref": m} for m in ch["matched_refs"]])
            if repeat_skip:
                log.info("Surah %s: dropping %d re-pass home seg(s): %s",
                         ch_ref, len(repeat_skip), sorted(repeat_skip))
            for occ in occurrences:
                if occ["seg_index"] in repeat_skip:
                    continue
                matched_ref = occ["matched_ref"]
                seg_offset_ms = occ["time_start"]
                seg_end_ms = occ["time_end"]
                seg_home_key = _matched_ref_to_output_key(matched_ref)
                seg_is_single_home = (seg_home_key is not None
                                      and ":" in seg_home_key
                                      and "-" not in seg_home_key)
                if seg_is_single_home:
                    cur = seg_bounds.get(seg_home_key)
                    if cur is None:
                        seg_bounds[seg_home_key] = [seg_offset_ms, seg_end_ms]
                    else:
                        cur[0] = min(cur[0], seg_offset_ms)
                        cur[1] = max(cur[1], seg_end_ms)
                if not occ["words_by_verse"]:
                    continue
                for verse_key, verse_words in occ["words_by_verse"].items():
                    entry = full_data.setdefault(
                        verse_key, {"words": [], "_provenance": []})
                    if "_provenance" not in entry:
                        entry["_provenance"] = [True] * len(entry["words"])
                    _merge_seg_words(entry, matched_ref, verse_key, verse_words)
        else:
            all_words = []
            for occ in occurrences:
                for verse_words in occ["words_by_verse"].values():
                    all_words.extend(verse_words)
            if all_words:
                full_data[ch_ref] = {"words": all_words}

    for ref in list(full_data.keys()):
        if ref.startswith("0:"):
            del full_data[ref]

    for ref, val in full_data.items():
        val.pop("_home_indices", None)
        val.pop("_provenance", None)
        words = val["words"]
        words.sort(key=lambda w: w[1])
        bound = seg_bounds.get(ref)
        word_start = words[0][1] if words else None
        word_end = max((w[2] for w in words), default=None)
        if bound is not None and words:
            val["verse_start_ms"] = min(bound[0], word_start)
            val["verse_end_ms"] = max(bound[1], word_end)
        elif bound is not None:
            val["verse_start_ms"] = bound[0]
            val["verse_end_ms"] = bound[1]
        elif words:
            val["verse_start_ms"] = word_start
            val["verse_end_ms"] = word_end

    for ref, val in full_data.items():
        if ref not in words_data:
            words_data[ref] = [[w[0], w[1], w[2]] for w in val["words"]]

    return full_data, words_data


def build_outputs(results_by_ch, seed_existing, *, chapters,
                  completed_surahs, completed_refs, refresh_surahs,
                  audio_category):
    """Module-level form of the former ``_build_outputs`` closure.

    ``_normalize_from_results`` (convert + verse-route) → ``_dedup_core``
    (skip + merge + bounds). ``canonical_occurrence`` reuses the SAME
    ``_dedup_core`` over stored v2, so the deduped projection cannot drift
    from what the pipeline wrote. Returns ``(full_data, words_data, mfa_failures)``.
    """
    norm, failures = _normalize_from_results(chapters, results_by_ch, audio_category)
    chapters_norm = []
    for ch_idx, chapter in enumerate(chapters):
        chapters_norm.append({
            "ch_ref": str(chapter.get("ref", "")),
            "matched_refs": [s.get("matched_ref", "")
                             for s in chapter.get("segments", [])],
            "occurrences": norm.get(ch_idx, []),
        })
    full_data, words_data = _dedup_core(
        chapters_norm, seed_existing,
        completed_surahs=completed_surahs, completed_refs=completed_refs,
        refresh_surahs=refresh_surahs, audio_category=audio_category)
    return full_data, words_data, failures


def process(input_dir: Path,
            backend: MfaBackend | None,
            method: str,
            beams: list[int],
            shared_cmvn: bool,
            resume: bool,
            batch_size: int = DEFAULT_BATCH_SIZE,
            output_dir: Path | None = None,
            padding: str = "forward",
            refresh_verses: set[str] | None = None,
            download_workers: int = DEFAULT_DOWNLOAD_WORKERS,
            workers: int = DEFAULT_WORKERS,
            mfa_app_path: str | Path | None = None,
            word_boundary_allocation: dict | None = None) -> Path | None:
    """Process all chapters from detailed.json through MFA alignment.

    Each value in ``beams`` runs as an independent alignment pass over
    the same audio. The widest beam (``max(beams)``) is the canonical
    pass — it always drives ``timestamps[_full].json`` regardless of the
    order ``beams`` was supplied in. Every other beam writes
    ``timestamps[_full].beam_<N>.json`` and its failures feed the
    cascade in ``beam_diff_report.txt``.

    When ``mfa_app_path`` is set and ``workers > 1``, the alignment
    fan-out runs across a ProcessPoolExecutor (true parallelism, GIL
    bypassed) — this is the local Katana / Kalpy path. Otherwise the
    single supplied ``backend`` is called serially per (batch, beam),
    which is what the HF Space wrapper uses.

    Returns the resolved output directory on success. Returns None when
    nothing was written.
    """
    if not beams:
        raise ValueError("beams must contain at least one value")
    # Canonical = widest beam, regardless of input order.
    canonical_beam = max(beams)
    probe_beams = sorted((b for b in beams if b != canonical_beam),
                         reverse=True)
    use_pool = mfa_app_path is not None and workers > 1
    if not use_pool and backend is None:
        raise ValueError("backend is required when not using the process pool")

    detailed_path = input_dir / "detailed.json"
    if not detailed_path.exists():
        log.error("detailed.json not found in %s", input_dir)
        sys.exit(1)

    reciter = input_dir.name

    # Read detailed.json
    with open(detailed_path, "r", encoding="utf-8") as f:
        detailed_doc = json.load(f)
    meta = detailed_doc.get("_meta")
    chapters = detailed_doc.get("entries", [])

    # Fallback: read _meta from segments.json if detailed.json has none
    if meta is None:
        segments_path = input_dir / "segments.json"
        if segments_path.exists():
            with open(segments_path, "r", encoding="utf-8") as f:
                seg_doc = json.load(f)
                meta = seg_doc.get("_meta")

    if not chapters:
        log.error("No chapter entries found in %s", detailed_path)
        sys.exit(1)

    log.info("Read %d chapters from %s", len(chapters), detailed_path)

    # Output path: user-specified or auto-derived
    audio_source = meta.get("audio_source", "") if meta else ""
    if audio_source.startswith("by_ayah"):
        audio_category = "by_ayah_audio"
    else:
        audio_category = "by_surah_audio"
    if output_dir is None:
        output_dir = input_dir.parent.parent / "timestamps" / audio_category / reciter
    output_dir.mkdir(parents=True, exist_ok=True)
    resume_path = output_dir / "timestamps_full.json"

    # Resume / refresh: load already-completed chapters from the full file
    completed_refs = set()
    existing_data = {}
    load_existing = resume or refresh_verses
    if load_existing and resume_path.exists():
        with open(resume_path, "r", encoding="utf-8") as f:
            resume_doc = json.load(f)
        for ref, val in resume_doc.items():
            if ref == "_meta":
                continue
            completed_refs.add(ref)
            existing_data[ref] = val
        if completed_refs:
            log.info("Loaded existing timestamps: %d verses", len(completed_refs))

    # Refresh mode: parse target verses into (surah, ayah) tuples for
    # segment matching, and derive the set of affected surahs for chapter
    # filtering.  Clear existing data for affected verses (will be rebuilt).
    refresh_ayahs: set[tuple[int, int]] | None = None
    refresh_surahs: set[str] | None = None
    if refresh_verses and existing_data:
        refresh_ayahs = set()
        for v in refresh_verses:
            parts = v.split(":")
            if len(parts) >= 2:
                try:
                    refresh_ayahs.add((int(parts[0]), int(parts[1])))
                except ValueError:
                    pass
        refresh_surahs = {str(s) for s, _ in refresh_ayahs}
        cleared = 0
        for ref in list(existing_data.keys()):
            parts = ref.split(":")
            if len(parts) >= 2:
                try:
                    if (int(parts[0]), int(parts[1])) in refresh_ayahs:
                        del existing_data[ref]
                        completed_refs.discard(ref)
                        cleared += 1
                except ValueError:
                    pass
        log.info("Refresh: cleared %d verses, keeping %d",
                 cleared, len(existing_data))

    # For by-surah resume: derive completed surah numbers from verse keys
    completed_surahs = set()
    if audio_category == "by_surah_audio" and completed_refs:
        for ref in completed_refs:
            sura = ref.split(":")[0].split("-")[0]
            completed_surahs.add(sura)
        if resume:
            log.info("Resume: %d surahs already completed", len(completed_surahs))

    tmp_dir = Path(tempfile.mkdtemp(prefix="mfa_timestamps_"))
    skipped_chapters = []

    # Build list of chapters to process
    if refresh_verses:
        # Refresh: process only surahs containing target verses
        chapters_to_process = [
            (ch_idx, chapter) for ch_idx, chapter in enumerate(chapters)
            if str(chapter.get("ref", "")).split(":")[0] in refresh_surahs
        ]
    elif audio_category == "by_surah_audio":
        # For by-surah: skip entire surahs that have any output
        chapters_to_process = [
            (ch_idx, chapter) for ch_idx, chapter in enumerate(chapters)
            if str(chapter.get("ref", "")) not in completed_surahs
        ]
    else:
        chapters_to_process = [
            (ch_idx, chapter) for ch_idx, chapter in enumerate(chapters)
            if str(chapter.get("ref", "")) not in completed_refs
        ]

    if not chapters_to_process:
        log.info("No segments to process (all complete or skipped)")
        if existing_data:
            for ref, val in existing_data.items():
                words = val.get("words", [])
                if words and "verse_start_ms" not in val:
                    val["verse_start_ms"] = words[0][1]
                    val["verse_end_ms"] = words[-1][2]
            _write_output(output_dir / "timestamps_full.json", meta,
                          method, canonical_beam, shared_cmvn,
                          existing_data, padding=padding)
            words_data = {}
            for ref, val in existing_data.items():
                words_only = [[w[0], w[1], w[2]] for w in val["words"]]
                words_data[ref] = words_only
            _write_output(output_dir / "timestamps.json", meta,
                          method, canonical_beam, shared_cmvn, words_data,
                          padding=padding)
        return output_dir

    # --- Producer-consumer pipeline ---
    # Bounded queue prevents unbounded WAV accumulation on disk.
    seg_queue = queue.Queue(maxsize=batch_size * 2)
    error_event = threading.Event()
    # results_by_beam[beam][ch_idx] = list of (seg_idx, result_dict).
    results_by_beam: dict[int, dict[int, list]] = {b: {} for b in beams}
    submitted_batch_count = [0]  # mutable counter for logging

    def _process_chapter(ch_idx, chapter):
        """Download, convert, slice one chapter and push segments to queue."""
        ch_ref = str(chapter.get("ref", ""))
        audio_src = chapter.get("audio", "")
        if not audio_src:
            log.warning("Surah %s: no audio source, skipping", ch_ref)
            return ch_idx, ch_ref, 0

        try:
            if _is_url(audio_src):
                audio_file = download_audio(audio_src)
            else:
                audio_file = Path(audio_src)
            audio_int16 = load_audio_int16(audio_file)
            if _is_url(audio_src):
                audio_file.unlink()
        except Exception as e:
            log.warning("Surah %s: audio download/convert failed: %s",
                        ch_ref, e)
            return ch_idx, ch_ref, 0

        count = 0
        for seg_idx, seg in enumerate(chapter.get("segments", [])):
            if error_event.is_set():
                break
            mfa_ref = build_mfa_ref(seg)
            if mfa_ref is None:
                continue
            # Refresh mode: skip segments not covering any target verse
            if refresh_ayahs is not None:
                covered = _seg_covered_ayahs(seg.get("matched_ref", ""))
                if not (covered & refresh_ayahs):
                    continue

            wav_path = tmp_dir / f"ch{ch_ref}_seg{seg_idx:04d}.wav"
            try:
                slice_audio(audio_int16, seg["time_start"], seg["time_end"],
                            wav_path)
            except Exception as e:
                log.warning("Surah %s seg %d: slice failed: %s",
                            ch_ref, seg_idx, e)
                continue

            # Bounded put — blocks if queue is full (backpressure)
            seg_queue.put((mfa_ref, str(wav_path), ch_idx, seg_idx))
            count += 1

        return ch_idx, ch_ref, count

    n_to_process = len(chapters_to_process)
    log.info("Pipeline: %d chapters, %d download workers, batch_size=%d, "
             "beams=%s, %s",
             n_to_process, download_workers, batch_size, beams,
             f"pool workers={workers}" if use_pool else "single backend (serial)")

    def _store_results(beam: int, batch_map, results, error_msg=None):
        """Push a batch's per-seg results into results_by_beam[beam]."""
        for i, (ch_idx, seg_idx) in enumerate(batch_map):
            if error_msg is not None:
                rec = {"status": "error", "error": error_msg}
            elif i < len(results):
                rec = results[i]
            else:
                rec = {"status": "error", "error": "missing result"}
            results_by_beam[beam].setdefault(ch_idx, []).append(
                (seg_idx, rec))

    # Producer thread: drain download/slice futures, push WAVs onto seg_queue.
    def _producer_loop():
        try:
            with ThreadPoolExecutor(max_workers=download_workers) as ex:
                futures = {ex.submit(_process_chapter, ci, ch): ci
                           for ci, ch in chapters_to_process}
                total = 0
                done = 0
                last = 0
                for f in as_completed(futures):
                    _, ch_ref, count = f.result()
                    done += 1
                    if count == 0:
                        skipped_chapters.append(ch_ref)
                    else:
                        total += count
                    if (total - last >= DOWNLOAD_LOG_INTERVAL
                            or done == n_to_process):
                        log.info("Downloads: %d/%d verses (%d segments queued)",
                                 done, n_to_process, total)
                        last = total
        finally:
            seg_queue.put(None)  # sentinel for the dispatcher

    if use_pool:
        # ProcessPoolExecutor path: B beams × N batches as separate tasks.
        # Each worker has its own HOME under /tmp so MFA model extraction is
        # private per worker — no need to pre-init in main.

        # Per-batch state for WAV cleanup once all beams complete.
        batch_state: dict[int, dict] = {}
        future_meta: dict = {}

        def _submit_batch(pool, refs, paths, mp):
            submitted_batch_count[0] += 1
            bid = submitted_batch_count[0]
            batch_state[bid] = {
                "remaining": len(beams),
                "paths": list(paths),
                "map": list(mp),
            }
            log.info("Batch %d: submit %d segs × %d beams",
                     bid, len(refs), len(beams))
            for b in beams:
                fut = pool.submit(_worker_align,
                                  list(refs), list(paths),
                                  method, b, shared_cmvn, padding,
                                  word_boundary_allocation)
                future_meta[fut] = (bid, b)

        producer = threading.Thread(target=_producer_loop, daemon=True)
        producer.start()

        with ProcessPoolExecutor(
                max_workers=workers,
                initializer=_init_worker,
                initargs=(str(mfa_app_path), 1)) as pool:
            buf_refs, buf_paths, buf_map = [], [], []
            while True:
                try:
                    item = seg_queue.get(timeout=1.0)
                except queue.Empty:
                    if error_event.is_set():
                        break
                    continue
                if item is None:
                    if buf_refs:
                        _submit_batch(pool, buf_refs, buf_paths, buf_map)
                        buf_refs, buf_paths, buf_map = [], [], []
                    break
                mfa_ref, wav_path, ch_idx, seg_idx = item
                buf_refs.append(mfa_ref)
                buf_paths.append(wav_path)
                buf_map.append((ch_idx, seg_idx))
                if len(buf_refs) >= batch_size:
                    _submit_batch(pool, buf_refs, buf_paths, buf_map)
                    buf_refs, buf_paths, buf_map = [], [], []
            producer.join()

            n_total = len(future_meta)
            n_done = 0
            for fut in as_completed(list(future_meta.keys())):
                bid, b = future_meta[fut]
                state = batch_state[bid]
                try:
                    results = fut.result()
                    _store_results(b, state["map"], results)
                except Exception as e:
                    log.error("Batch %d beam=%d failed: %s", bid, b, e)
                    _store_results(b, state["map"], [], error_msg=str(e))
                state["remaining"] -= 1
                n_done += 1
                if n_done % max(1, len(beams)) == 0:
                    log.info("Aligned: %d/%d tasks", n_done, n_total)
                if state["remaining"] == 0:
                    for p in state["paths"]:
                        try:
                            os.unlink(p)
                        except OSError:
                            pass
                    del batch_state[bid]
    else:
        # Serial path (HF Space backend). Loop over beams sequentially per
        # batch — the Space already ThreadPools internally per call.
        producer = threading.Thread(target=_producer_loop, daemon=True)
        producer.start()

        buf_refs, buf_paths, buf_map = [], [], []

        def _flush(refs, paths, mp):
            if not refs:
                return True
            submitted_batch_count[0] += 1
            bid = submitted_batch_count[0]
            log.info("Batch %d: %d segs × %d beams (serial)",
                     bid, len(refs), len(beams))
            ok = True
            for b in beams:
                try:
                    results = backend.align_batch(
                        refs, paths,
                        method=method, beam=b,
                        shared_cmvn=shared_cmvn, padding=padding,
                        word_boundary_allocation=word_boundary_allocation)
                except Exception as e:
                    log.error("Batch %d beam=%d raised %s", bid, b, e)
                    _store_results(b, mp, [], error_msg=str(e))
                    continue
                if results is None:
                    log.error("Batch %d beam=%d returned None", bid, b)
                    _store_results(b, mp, [], error_msg="batch_failed")
                    ok = False
                    continue
                _store_results(b, mp, results)
            for p in paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass
            after_batch = getattr(backend, "after_batch", None)
            if after_batch is not None:
                after_batch()
            return ok

        while True:
            try:
                item = seg_queue.get(timeout=1.0)
            except queue.Empty:
                if error_event.is_set():
                    break
                continue
            if item is None:
                _flush(buf_refs, buf_paths, buf_map)
                break
            mfa_ref, wav_path, ch_idx, seg_idx = item
            buf_refs.append(mfa_ref)
            buf_paths.append(wav_path)
            buf_map.append((ch_idx, seg_idx))
            if len(buf_refs) >= batch_size:
                if not _flush(buf_refs, buf_paths, buf_map):
                    error_event.set()
                    break
                buf_refs, buf_paths, buf_map = [], [], []
        producer.join()

    if error_event.is_set():
        while True:
            try:
                item = seg_queue.get_nowait()
            except queue.Empty:
                break
            if item is not None:
                _, wav_path, _, _ = item
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass

    canonical_results = results_by_beam[canonical_beam]
    if not canonical_results and not existing_data:
        log.info("No segments processed (all skipped or failed)")
        _cleanup([], tmp_dir)
        return None

    def _build_outputs(results_by_ch, seed_existing):
        """Build (full_data, words_data, mfa_failures) from a chapter_results dict.

        seed_existing: pre-loaded verse data to merge into (resume/refresh
        path). Pass None for a fresh build (e.g. low-beam sidecar).
        """
        full_data = dict(seed_existing) if seed_existing else {}
        words_data = {}
        mfa_failures = []
        # Per-verse min(time_start) / max(time_end) of accepted home segs.
        # Drives `verse_start_ms` / `verse_end_ms` in `full_data` so dataset
        # consumers cut audio along seg boundaries (which include natural
        # leading/trailing silence) rather than MFA's tight phone-level
        # boundaries. Cross-verse segs don't contribute (their audio is
        # shared across two verses; the home segs alone bracket each verse).
        seg_bounds: dict[str, list[int]] = {}
        if seed_existing:
            for ref, val in seed_existing.items():
                words_only = [[w[0], w[1], w[2]] for w in val["words"]]
                words_data[ref] = words_only
                vs = val.get("verse_start_ms")
                ve = val.get("verse_end_ms")
                if vs is not None and ve is not None:
                    seg_bounds[ref] = [vs, ve]

        for ch_idx, chapter in enumerate(chapters):
            ch_ref = str(chapter.get("ref", ""))
            if seed_existing is not None:
                if audio_category == "by_surah_audio":
                    if ch_ref in completed_surahs and ch_ref not in (refresh_surahs or set()):
                        continue
                else:
                    if ch_ref in completed_refs:
                        continue
            if ch_idx not in results_by_ch:
                continue

            if audio_category == "by_surah_audio":
                repeat_skip = _repeat_pass_skip_indices(chapter["segments"])
                if repeat_skip:
                    log.info(
                        "Surah %s: dropping %d re-pass home seg(s): %s",
                        ch_ref, len(repeat_skip), sorted(repeat_skip))
                for seg_idx, result in results_by_ch[ch_idx]:
                    if seg_idx in repeat_skip:
                        continue
                    seg = chapter["segments"][seg_idx]
                    matched_ref = seg.get("matched_ref", "")

                    if result.get("status") != "ok":
                        error_msg = result.get("error", "unknown")
                        log.warning("Surah %s seg %d: MFA failed: %s",
                                    ch_ref, seg_idx, error_msg)
                        mfa_failures.append({
                            "verse": ch_ref,
                            "seg": seg_idx,
                            "ref": matched_ref,
                            "error": error_msg,
                        })
                        continue

                    seg_offset_ms = seg["time_start"]
                    seg_end_ms = seg.get("time_end", seg_offset_ms)
                    seg_home_key = _matched_ref_to_output_key(matched_ref)
                    seg_is_single_home = (seg_home_key is not None
                                          and ":" in seg_home_key
                                          and "-" not in seg_home_key)
                    if seg_is_single_home:
                        cur = seg_bounds.get(seg_home_key)
                        if cur is None:
                            seg_bounds[seg_home_key] = [seg_offset_ms, seg_end_ms]
                        else:
                            cur[0] = min(cur[0], seg_offset_ms)
                            cur[1] = max(cur[1], seg_end_ms)

                    words_by_verse: dict[str, list] = {}
                    for w in result.get("words", []):
                        location = w["location"]
                        verse_key = location.rsplit(":", 1)[0]
                        word_data = _convert_word(w, seg_offset_ms)
                        words_by_verse.setdefault(verse_key, []).append(word_data)

                    if not words_by_verse:
                        continue

                    for verse_key, verse_words in words_by_verse.items():
                        entry = full_data.setdefault(
                            verse_key, {"words": [], "_provenance": []})
                        if "_provenance" not in entry:
                            entry["_provenance"] = [True] * len(entry["words"])
                        _merge_seg_words(entry, matched_ref, verse_key,
                                         verse_words)
            else:
                all_words = []
                verse_prefix = f"{ch_ref}:" if ":" in ch_ref else None
                for seg_idx, result in results_by_ch[ch_idx]:
                    if result.get("status") != "ok":
                        seg = chapter["segments"][seg_idx]
                        error_msg = result.get("error", "unknown")
                        matched_ref = seg.get("matched_ref", "")
                        log.warning("Verse %s seg %d: MFA failed: %s",
                                    ch_ref, seg_idx, error_msg)
                        mfa_failures.append({
                            "verse": ch_ref,
                            "seg": seg_idx,
                            "ref": matched_ref,
                            "error": error_msg,
                        })
                        continue

                    seg = chapter["segments"][seg_idx]
                    if verse_prefix:
                        raw_words = result.get("words", [])
                        result["words"] = [
                            w for w in raw_words
                            if w.get("location", "").startswith(verse_prefix)
                        ]
                    words = _convert_result(result, seg["time_start"])
                    all_words.extend(words)

                if all_words:
                    full_data[ch_ref] = {"words": all_words}

        for ref in list(full_data.keys()):
            if ref.startswith("0:"):
                del full_data[ref]

        for ref, val in full_data.items():
            val.pop("_home_indices", None)
            val.pop("_provenance", None)
            words = val["words"]
            words.sort(key=lambda w: w[1])
            bound = seg_bounds.get(ref)
            # Verse boundaries take the union of accepted home segs (carries
            # the segmenter's natural leading/trailing silence — preferred
            # for dataset clip cuts) and the actual MFA word bounds (so a
            # cross-verse bleed contributing widxs outside the home segs'
            # range still falls inside the clip).
            word_start = words[0][1] if words else None
            word_end = max((w[2] for w in words), default=None)
            if bound is not None and words:
                val["verse_start_ms"] = min(bound[0], word_start)
                val["verse_end_ms"] = max(bound[1], word_end)
            elif bound is not None:
                val["verse_start_ms"] = bound[0]
                val["verse_end_ms"] = bound[1]
            elif words:
                val["verse_start_ms"] = word_start
                val["verse_end_ms"] = word_end

        for ref, val in full_data.items():
            if ref not in words_data:
                words_only = [[w[0], w[1], w[2]] for w in val["words"]]
                words_data[ref] = words_only

        return full_data, words_data, mfa_failures

    # v2 is the ONLY persisted timestamps format: per-chapter occurrence-
    # preserving shards at ``<output_dir>/timestamps/<chapter>.json``.
    # ``canonical_results`` carries every aligned segment (pre-dedup) so
    # build_raw_v2 keeps all occurrences; the inspector read-path dedups on
    # serve and downstream consumers derive whatever projection they need.
    # The historical timestamps_full.json / timestamps.json (single-file +
    # word-only) are intentionally NOT written (decision: one canonical v2).
    from scripts.lib.timestamps_dedup import build_raw_v2  # lazy: avoid import cycle
    ts_dir = output_dir / "timestamps"
    ts_dir.mkdir(parents=True, exist_ok=True)

    def _emit_v2(results_by_ch, suffix=""):
        v2_doc = build_raw_v2(chapters, results_by_ch, audio_category)
        shards = split_to_shards(
            v2_doc, reciter=reciter, audio_category=audio_category, url_template="")
        for ch_num, shard_doc in shards.items():
            (ts_dir / f"{ch_num}{suffix}.json").write_text(
                json.dumps(shard_doc, ensure_ascii=False), encoding="utf-8")
        fails = len((v2_doc.get("_meta") or {}).get("mfa_failures", []))
        return len(shards), fails

    n_shards, n_fail = _emit_v2(canonical_results)
    if n_fail:
        log.warning("Canonical beam %d: %d MFA failures", canonical_beam, n_fail)
    log.info("Wrote %d v2 timestamps shard(s) (beam=%d) -> %s",
             n_shards, canonical_beam, ts_dir)

    # Probe beams → v2 sidecar shards ``<chapter>.beam_<N>.json`` (same format,
    # for beam comparison) — no legacy single-file.
    for b in probe_beams:
        nb, fb = _emit_v2(results_by_beam[b], suffix=f".beam_{b}")
        log.info("Wrote %d v2 probe shard(s) (beam=%d, %d failures)", nb, b, fb)

    _cleanup([], tmp_dir)
    return output_dir


def _submit_with_retry(refs, audio_paths, space_url, *, method, beam,
                       shared_cmvn, padding=DEFAULT_PADDING,
                       word_boundary_allocation=None,
                       timeout=DEFAULT_TIMEOUT, max_retries=1):
    """Submit batch to MFA Space with one retry on failure."""
    for attempt in range(max_retries + 1):
        try:
            event_id, headers, base = mfa_upload_and_submit(
                refs, audio_paths, space_url,
                method=method, beam=beam,
                shared_cmvn=shared_cmvn, padding=padding,
                word_boundary_allocation=word_boundary_allocation,
                timeout=timeout)
            log.info("Submitted batch (event_id=%s), waiting for results...", event_id)
            return mfa_wait_result(event_id, headers, base, timeout=timeout)
        except Exception as e:
            if attempt < max_retries:
                log.warning("MFA batch failed (%s), retrying in 30s...", e)
                time.sleep(30)
            else:
                log.error("MFA batch failed after %d retries: %s", max_retries, e)
    return None


def _write_output(output_path, meta, method, beam, shared_cmvn,
                  output_data, mfa_failures=None,
                  padding=DEFAULT_PADDING):
    """Write a timestamps JSON file (canonical or per-beam variant)."""
    out_meta = {
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audio_source": meta.get("audio_source", "") if meta else "",
        "aligner_model": DEFAULT_ALIGNER_MODEL,
        "method": method,
        "beam": beam,
        "shared_cmvn": shared_cmvn,
        "padding": padding,
    }
    if mfa_failures:
        out_meta["mfa_failures"] = mfa_failures

    doc = {"_meta": out_meta}
    for ref in sorted(output_data.keys(), key=_ref_sort_key):
        doc[ref] = output_data[ref]

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)


def _cleanup(audio_paths, tmp_dir):
    """Remove temporary audio files and directory."""
    for p in audio_paths:
        try:
            os.unlink(p)
        except OSError:
            pass
    try:
        tmp_dir.rmdir()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract word/letter/phoneme timestamps via MFA forced alignment."
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to reciter directory containing detailed.json",
    )
    parser.add_argument(
        "--space-url", default=DEFAULT_SPACE_URL,
        help=f"MFA HF Space URL (default: {DEFAULT_SPACE_URL})",
    )
    parser.add_argument("--method", default=DEFAULT_METHOD,
                        help="Alignment method (default: kalpy)")
    parser.add_argument("--beam", type=int, default=DEFAULT_BEAM,
                        help="Beam width (default: 10)")
    parser.add_argument("--retry-beam", type=int, default=DEFAULT_RETRY_BEAM,
                        help="Retry beam width (default: 40)")
    parser.add_argument("--shared-cmvn", action="store_true",
                        help="Compute shared CMVN across batch (kalpy only)")
    parser.add_argument("--padding", choices=["forward", "symmetric", "none"],
                        default="forward",
                        help="Phoneme gap-padding strategy (default: forward)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip already-completed chapters")
    parser.add_argument("--refresh-verses",
                        help="Comma-separated verse keys to re-extract (e.g. 1:1,37:151,37:152)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"Segments per MFA upload batch (default: {DEFAULT_BATCH_SIZE})")
    parser.add_argument("--download-workers", type=int, default=DEFAULT_DOWNLOAD_WORKERS,
                        help=f"Parallel audio download/decode workers (default: {DEFAULT_DOWNLOAD_WORKERS})")
    parser.add_argument("-o", "--output", default=None,
                        help="Output directory (default: auto-derived from input path)")

    args = parser.parse_args()
    input_dir = Path(args.input).resolve()
    output_dir = Path(args.output).resolve() if args.output else None
    refresh = set(args.refresh_verses.split(",")) if args.refresh_verses else None

    process(
        input_dir=input_dir,
        backend=SpaceMfaBackend(args.space_url),
        method=args.method,
        beam=args.beam,
        retry_beam=args.retry_beam,
        shared_cmvn=args.shared_cmvn,
        resume=args.resume,
        batch_size=args.batch_size,
        output_dir=output_dir,
        padding=args.padding,
        refresh_verses=refresh,
        download_workers=args.download_workers,
    )


if __name__ == "__main__":
    main()
