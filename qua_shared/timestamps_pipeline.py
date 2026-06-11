#!/usr/bin/env python3
"""Shared timestamp extraction pipeline.

Reads detailed.json from the segment extraction pipeline, downloads full
surah audio, slices segments, sends batches through a caller-provided MFA
backend, and writes per-chapter v2 timestamps shards.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import wave
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from qua_shared.timestamps_shards import build_segment_shards, gzip_shard

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
# Lowered from 8 → 4: each producer worker buffers a full ffmpeg PCM (up to
# ~400 MB for a 3h surah) via subprocess.run(capture_output=True). At 8
# parallel × big-audio reciters this peaks ≥3 GB of stdout in Python memory
# and saturates the bucket FUSE I/O, which is what stalled Husary/Mishary.
# Override per launch with DOWNLOAD_WORKERS env / settings.download_workers.
DEFAULT_DOWNLOAD_WORKERS = 4
# Canonical filenames inside an MFA runtime dir (bucket ``mfa-runtime/`` or a
# Katana-synced copy): the acoustic model zip + pronunciation dictionary.
MFA_MODEL_FILENAME = "quran_aligner_model.zip"
MFA_DICTIONARY_FILENAME = "dictionary.txt"
# Hard cap on a single chapter's ffmpeg decode. Anchored to the worst case
# observed: 191 MB CBR-128k MP3 → 382 MB PCM, ~22s local, ~100s in an 8-way
# parallel CPU-bound burst; 600s leaves ~6× headroom for the bucket FUSE
# path. Without this, a stuck ffmpeg pins a producer thread indefinitely
# (subprocess.run has no implicit timeout) and the job sits silent until HF
# kills it at its outer timeout.
LOAD_AUDIO_TIMEOUT_SEC = 600

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


def resolve_mfa_runtime(runtime_dir: str | Path | None) -> tuple[str, str]:
    """Resolve ``(model_path, dictionary_path)`` for the local MFA runtime.

    A directory yields its bundled ``quran_aligner_model.zip`` +
    ``dictionary.txt`` (both must exist). ``None`` falls back to the
    ``MFA_MODEL_PATH`` / ``MFA_DICTIONARY_PATH`` env vars.
    """
    if runtime_dir is not None:
        d = Path(runtime_dir)
        model = d / MFA_MODEL_FILENAME
        dictionary = d / MFA_DICTIONARY_FILENAME
        missing = [str(p) for p in (model, dictionary) if not p.is_file()]
        if missing:
            raise FileNotFoundError(f"MFA runtime dir {d} is missing: {', '.join(missing)}")
        return str(model), str(dictionary)
    model_env = os.environ.get("MFA_MODEL_PATH", "").strip()
    dict_env = os.environ.get("MFA_DICTIONARY_PATH", "").strip()
    if not model_env or not dict_env:
        raise RuntimeError(
            "MFA runtime unresolved: pass an --mfa-runtime-dir (containing "
            f"{MFA_MODEL_FILENAME} + {MFA_DICTIONARY_FILENAME}) or set the "
            "MFA_MODEL_PATH and MFA_DICTIONARY_PATH env vars"
        )
    return model_env, dict_env


def _paths_from_app_path(mfa_app_path: str | Path) -> tuple[str, str]:
    """DEPRECATED shim: derive ``(model, dictionary)`` from the legacy aligner
    ``app.py`` FILE path — both runtime files sit next to it in the same dir."""
    import warnings

    d = Path(mfa_app_path).resolve().parent
    warnings.warn(
        "mfa_app_path is deprecated; pass mfa_model_path + mfa_dictionary_path "
        f"(deriving {d / MFA_MODEL_FILENAME} + {d / MFA_DICTIONARY_FILENAME})",
        DeprecationWarning,
        stacklevel=3,
    )
    return str(d / MFA_MODEL_FILENAME), str(d / MFA_DICTIONARY_FILENAME)


def _sdk_align(
    aligner,
    refs: Sequence,
    audio_paths: Sequence[str],
    *,
    method: str,
    beam: int,
    shared_cmvn: bool,
    padding: str,
    word_boundary_allocation: dict | None = None,
) -> list[dict]:
    """Run one batch through a qua_sdk ``MfaLocalAligner`` → legacy row dicts.

    ``retry_beam`` is pinned to ``beam`` (no implicit retry — a wider retry
    beam is expressed as a separate value in the caller's beams list; the SDK
    default would silently widen to 35 otherwise). The wb-allocation payload
    is resolved to the full per-rule dict before the call.
    """
    from qua_sdk.components.timing.lib import resolve_word_boundary_allocation

    envelope = aligner.align_items(
        [(ref, str(p)) for ref, p in zip(refs, audio_paths, strict=True)],
        method=method,
        beam=beam,
        retry_beam=beam,
        shared_cmvn=shared_cmvn,
        padding=padding,
        wb_allocation_resolved=resolve_word_boundary_allocation(word_boundary_allocation),
    )
    if envelope.status != "ok":
        raise RuntimeError(f"Local MFA batch failed: {envelope.error}")
    return [row.model_dump() for row in envelope.results or []]


class LocalMfaBackend:
    """In-process MFA backend over qua_sdk's ``MfaLocalAligner``.

    Serial single-aligner backend — the pipeline parallelises across beams
    and batches via the process pool (``_init_worker``/``_worker_align``)
    when ``workers > 1``, so this backend covers the ``workers == 1`` path.
    qua_sdk imports stay call-local: importing this module must never pull
    the SDK (inspector services import it for pure helpers).
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        dictionary_path: str | Path | None = None,
        *,
        mfa_threads: int = 1,
    ):
        from qua_sdk.components.timing.runtimes.mfa_local import MfaLocalAligner

        self.model_path = str(model_path) if model_path else None
        self.dictionary_path = str(dictionary_path) if dictionary_path else None
        self.aligner = MfaLocalAligner(
            self.model_path, self.dictionary_path, num_threads=mfa_threads, use_pool=False
        )

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
        return _sdk_align(
            self.aligner,
            refs,
            audio_paths,
            method=method,
            beam=beam,
            shared_cmvn=shared_cmvn,
            padding=padding,
            word_boundary_allocation=word_boundary_allocation,
        )


# ---------------------------------------------------------------------------
# Process-pool worker (top-level for picklability)
# ---------------------------------------------------------------------------

# Per-worker globals populated by the executor's initializer.
_WORKER = {"aligner": None}


def _init_worker(model_path: str, dictionary_path: str):
    """ProcessPoolExecutor initializer: build one MFA aligner per worker.

    Each worker gets a unique HOME under /tmp so MFA extracts its acoustic
    model into a worker-private ``~/Documents/MFA`` tree. This sidesteps the
    "Directory not empty" race that hits when N workers all target the
    same ``~/Documents/MFA/extracted_models`` path. ``MFA_ROOT_DIR`` is also
    pinned per-worker (mirrors the SDK's own pool initializer).
    """
    pid = os.getpid()
    # Worker HOMEs go under MFA_WORKER_BASE if set, else $TMPDIR (PBS
    # job-scratch — node-local SSD, plenty of space), else /tmp (last resort:
    # often a small tmpfs that fills up with N parallel model extractions).
    base = os.environ.get("MFA_WORKER_BASE") or os.environ.get("TMPDIR") or "/tmp"
    home = f"{base}/mfa_w{pid}"
    os.makedirs(home + "/Documents/MFA", exist_ok=True)
    mfa_root = f"{home}/mfa_data"
    os.makedirs(mfa_root, exist_ok=True)
    os.environ["HOME"] = home
    os.environ["MFA_ROOT_DIR"] = mfa_root
    # Single-thread the BLAS stack — workers themselves provide parallelism.
    for var in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ.setdefault(var, "1")
    from qua_sdk.components.timing.runtimes.mfa_local import MfaLocalAligner

    _WORKER["aligner"] = MfaLocalAligner(model_path, dictionary_path, num_threads=1, use_pool=False)


def _worker_align(
    refs, audio_paths, method, beam, shared_cmvn, padding, word_boundary_allocation=None
):
    """ProcessPoolExecutor task: align one batch slice for one beam."""
    aligner = _WORKER["aligner"]
    if aligner is None:
        raise RuntimeError("Worker not initialized; missing MFA aligner.")
    return _sdk_align(
        aligner,
        refs,
        audio_paths,
        method=method,
        beam=beam,
        shared_cmvn=shared_cmvn,
        padding=padding,
        word_boundary_allocation=word_boundary_allocation,
    )


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
    """Load audio as 16kHz mono int16 via ffmpeg.

    Bounded by ``LOAD_AUDIO_TIMEOUT_SEC`` — without it a stuck ffmpeg
    (bucket FUSE read stall, kernel paging under memory pressure, malformed
    stream) pins the calling producer thread indefinitely.
    """
    import numpy as np

    cmd = [
        "ffmpeg",
        "-i",
        str(path),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-v",
        "quiet",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True, check=True, timeout=LOAD_AUDIO_TIMEOUT_SEC)
    return np.frombuffer(result.stdout, dtype=np.int16)


def slice_audio(
    audio_int16: np.ndarray, start_ms: int, end_ms: int, out_path: Path, sample_rate: int = 16000
):
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
            matched_ref = matched_ref[len(prefix) :]

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


def is_compound_cross_verse(matched_ref: str) -> bool:
    """True if ``matched_ref`` spans two distinct verses (``s:a:w-s:b:w``, a≠b).

    Single source for the cross-verse test shared by the Auto-Split precompute
    and the timestamps job's segment-array guard. Within-verse word ranges
    (``2:1:1-2:1:4``) and non-dash refs are not compound.
    """
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return False
    s, e = parts[0].split(":"), parts[1].split(":")
    return len(s) >= 2 and len(e) >= 2 and s[1] != e[1]


def build_ts_validation(
    chapters,
    results_by_beam,
    beams,
    *,
    reciter: str,
    method: str,
    aligner_model: str = DEFAULT_ALIGNER_MODEL,
) -> dict:
    """Verse-level beam-agreement summary across every aligned beam.

    Each beam in ``beams`` is an independent alignment pass; the widest
    (``max(beams)``) is canonical. A verse *passes* under beam ``b`` when every
    segment mapping to that verse aligned (``status == "ok"``) under ``b``. A
    verse is *flagged* when it fails under at least one beam it was tested
    under — tighter beams disagreeing with the canonical pass is the
    low-confidence signal. This is the verse-level analogue of the segment-level
    ``low_confidence_v2.json`` probe and feeds the Timestamps-tab "ts-validation"
    accordion (owner preview).

    Returns a plain dict (no pydantic dep — runs inside the HF job container):
    ``{"_meta": {...}, "verses": {verse_key: {"failed_beams": [...],
    "min_passing_beam": int|None}}}``. With a single beam (no probes) ``verses``
    is empty — there is nothing to compare against.
    """
    canonical_beam = max(beams) if beams else 0
    # verse_key -> {beam: all_segments_ok_under_beam}
    pass_by_beam: dict[str, dict[int, bool]] = {}
    for b in beams:
        for ch_idx, seg_list in (results_by_beam.get(b) or {}).items():
            segments = chapters[ch_idx].get("segments", []) if 0 <= ch_idx < len(chapters) else []
            for seg_idx, rec in seg_list:
                if not (0 <= seg_idx < len(segments)):
                    continue
                vkey = _matched_ref_to_output_key(segments[seg_idx].get("matched_ref", "") or "")
                if not vkey:
                    continue
                ok = (rec or {}).get("status") == "ok"
                by_beam = pass_by_beam.setdefault(vkey, {})
                by_beam[b] = by_beam.get(b, True) and ok

    verses: dict[str, dict] = {}
    for vkey, by_beam in pass_by_beam.items():
        tested = [b for b in beams if b in by_beam]
        failed = sorted((b for b in tested if not by_beam[b]), reverse=True)
        if not failed:
            continue  # aligned under every beam it was tested → confident
        passing = [b for b in tested if by_beam[b]]
        verses[vkey] = {
            "failed_beams": failed,
            "min_passing_beam": min(passing) if passing else None,
        }

    return {
        "_meta": {
            "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reciter": reciter,
            "aligner_model": aligner_model,
            "method": method,
            "beams": sorted(set(beams), reverse=True),
            "canonical_beam": canonical_beam,
        },
        "verses": verses,
    }


def _seg_covered_ayahs(matched_ref: str) -> set[tuple[int, int]]:
    """Extract the set of (surah, ayah) pairs a segment's matched_ref covers.

    '1:1:1-1:1:4' → {(1,1)}
    '37:151:3-37:152:2' → {(37,151), (37,152)}
    """
    for prefix in ("Basmala+", "Isti'adha+"):
        if matched_ref.startswith(prefix):
            matched_ref = matched_ref[len(prefix) :]
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
        [
            lt["char"],
            _s_to_ms(lt.get("start"), seg_offset_ms),
            _s_to_ms(lt.get("end"), seg_offset_ms),
        ]
        for lt in w.get("letters", [])
    ]
    phones = [
        [p["phone"], _s_to_ms(p["start"], seg_offset_ms), _s_to_ms(p["end"], seg_offset_ms)]
        for p in w.get("phones", [])
    ]
    return [
        word_idx,
        _s_to_ms(w["start"], seg_offset_ms),
        _s_to_ms(w["end"], seg_offset_ms),
        letters,
        phones,
    ]


# ---------------------------------------------------------------------------
# MFA Space HTTP client (inline — no imports from quranic_universal_aligner)
# ---------------------------------------------------------------------------


def mfa_upload_and_submit(
    refs,
    audio_paths,
    base_url,
    *,
    method=DEFAULT_METHOD,
    beam=DEFAULT_BEAMS[0],
    shared_cmvn=False,
    padding=DEFAULT_PADDING,
    word_boundary_allocation=None,
    timeout=DEFAULT_TIMEOUT,
):
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
    file_data_list = [{"path": p, "meta": {"_type": "gradio.FileData"}} for p in uploaded_paths]

    # Submit batch alignment
    wb_json = json.dumps(word_boundary_allocation) if word_boundary_allocation else ""
    submit_resp = requests.post(
        f"{base_url}/gradio_api/call/align_batch",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "data": [
                refs,
                file_data_list,
                method,
                str(beam),
                str(beam),
                str(shared_cmvn).lower(),
                padding,
                wb_json,
            ]
        },
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

    The conversion + per-verse word routing core; ``build_raw_v2`` (in
    ``timestamps_dedup``) consumes its output to build the raw v2 document the
    segment-array writer emits.

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
        verse_prefix = f"{ch_ref}:" if (not by_surah and ":" in ch_ref) else None
        ch_occ = []
        for seg_idx, result in results_by_ch.get(ch_idx, []):
            if seg_idx >= len(segs):
                continue
            seg = segs[seg_idx]
            matched_ref = seg.get("matched_ref", "")
            if result.get("status") != "ok":
                failures.append(
                    {
                        "verse": ch_ref,
                        "seg": seg_idx,
                        "ref": matched_ref,
                        "error": result.get("error", "unknown"),
                    }
                )
                continue
            seg_offset_ms = seg.get("time_start", 0)
            seg_end_ms = seg.get("time_end", seg_offset_ms)
            raw_words = result.get("words", [])
            if verse_prefix is not None:
                raw_words = [w for w in raw_words if w.get("location", "").startswith(verse_prefix)]
            words_by_verse: dict[str, list] = {}
            for w in raw_words:
                verse_key = w["location"].rsplit(":", 1)[0]
                words_by_verse.setdefault(verse_key, []).append(_convert_word(w, seg_offset_ms))
            ch_occ.append(
                {
                    "ch_ref": ch_ref,
                    "seg_index": seg_idx,
                    "matched_ref": matched_ref,
                    "time_start": seg_offset_ms,
                    "time_end": seg_end_ms,
                    "words_by_verse": words_by_verse,
                    "segment_uid": seg.get("segment_uid"),
                }
            )
        if ch_occ:
            norm[ch_idx] = ch_occ
    return norm, failures


def _merge_ts_validation(path: Path, fresh: dict, refresh_chapters: set[int]) -> dict:
    """Merge a partial run's ``ts_validation`` into the existing whole-reciter
    sidecar at ``path``. Keeps the prior file's flagged verses for chapters NOT
    in ``refresh_chapters`` and takes ``fresh``'s verses for the refreshed ones.
    Returns ``fresh`` unchanged when there's no readable prior file."""
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fresh

    def _surah_of(verse_key: str) -> int | None:
        try:
            return int(str(verse_key).split(":")[0])
        except (ValueError, IndexError):
            return None

    merged = {
        k: v
        for k, v in (existing.get("verses") or {}).items()
        if _surah_of(k) not in refresh_chapters
    }
    merged.update(fresh.get("verses") or {})
    fresh["verses"] = dict(sorted(merged.items(), key=lambda kv: kv[0]))
    return fresh


def process(
    input_dir: Path,
    backend: MfaBackend | None,
    method: str,
    beams: list[int],
    shared_cmvn: bool,
    resume: bool,
    batch_size: int = DEFAULT_BATCH_SIZE,
    output_dir: Path | None = None,
    padding: str = "forward",
    refresh_verses: set[str] | None = None,
    refresh_chapters: set[int] | None = None,
    download_workers: int = DEFAULT_DOWNLOAD_WORKERS,
    workers: int = DEFAULT_WORKERS,
    mfa_model_path: str | Path | None = None,
    mfa_dictionary_path: str | Path | None = None,
    mfa_app_path: str | Path | None = None,
    word_boundary_allocation: dict | None = None,
) -> Path | None:
    """Process all chapters from detailed.json through MFA alignment.

    Each value in ``beams`` runs as an independent alignment pass over
    the same audio. The widest beam (``max(beams)``) is the canonical
    pass — it always drives the ``timestamps/<ch>.json.gz`` segment-array
    shards regardless of the order ``beams`` was supplied in. The remaining
    (narrower) beams are folded into a single verse-level
    ``ts_validation.json`` sidecar — verses that align under the canonical
    beam but fail under a tighter beam are flagged as low-confidence.

    When ``mfa_model_path`` + ``mfa_dictionary_path`` are set and
    ``workers > 1``, the alignment fan-out runs across a
    ProcessPoolExecutor (true parallelism, GIL bypassed) — this is the
    local Katana / Kalpy path. Otherwise the single supplied ``backend``
    is called serially per (batch, beam), which is what the HF Space
    wrapper uses. ``mfa_app_path`` is a deprecated alias: the model +
    dictionary are derived from the app.py file's directory.

    ``refresh_chapters`` (surah numbers) scopes the run to those chapters only —
    untouched chapters keep their existing shards, and the whole-reciter
    ``ts_validation.json`` is merged rather than clobbered.

    Returns the resolved output directory on success. Returns None when
    nothing was written.
    """
    if not beams:
        raise ValueError("beams must contain at least one value")
    # Canonical = widest beam, regardless of input order. The narrower beams
    # feed the verse-level ts_validation.json sidecar (built after alignment).
    canonical_beam = max(beams)
    if mfa_app_path is not None and not (mfa_model_path and mfa_dictionary_path):
        mfa_model_path, mfa_dictionary_path = _paths_from_app_path(mfa_app_path)
    use_pool = bool(mfa_model_path and mfa_dictionary_path) and workers > 1
    if not use_pool and backend is None:
        raise ValueError("backend is required when not using the process pool")

    detailed_path = input_dir / "detailed.json"
    if not detailed_path.exists():
        log.error("detailed.json not found in %s", input_dir)
        sys.exit(1)

    reciter = input_dir.name

    # Read detailed.json
    with open(detailed_path, encoding="utf-8") as f:
        detailed_doc = json.load(f)
    meta = detailed_doc.get("_meta")
    chapters = detailed_doc.get("entries", [])

    # Fallback: read _meta from segments.json if detailed.json has none
    if meta is None:
        segments_path = input_dir / "segments.json"
        if segments_path.exists():
            with open(segments_path, encoding="utf-8") as f:
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
        with open(resume_path, encoding="utf-8") as f:
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
        log.info("Refresh: cleared %d verses, keeping %d", cleared, len(existing_data))

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
    if refresh_chapters:
        # Affected-only regen: process only the named chapters (surah numbers).
        # Untouched shards stay on the bucket; ts_validation.json is merged below.
        refresh_chapter_strs = {str(c) for c in refresh_chapters}
        chapters_to_process = [
            (ch_idx, chapter)
            for ch_idx, chapter in enumerate(chapters)
            if str(chapter.get("ref", "")).split(":")[0] in refresh_chapter_strs
        ]
    elif refresh_verses:
        # Refresh: process only surahs containing target verses
        chapters_to_process = [
            (ch_idx, chapter)
            for ch_idx, chapter in enumerate(chapters)
            if str(chapter.get("ref", "")).split(":")[0] in refresh_surahs
        ]
    elif audio_category == "by_surah_audio":
        # For by-surah: skip entire surahs that have any output
        chapters_to_process = [
            (ch_idx, chapter)
            for ch_idx, chapter in enumerate(chapters)
            if str(chapter.get("ref", "")) not in completed_surahs
        ]
    else:
        chapters_to_process = [
            (ch_idx, chapter)
            for ch_idx, chapter in enumerate(chapters)
            if str(chapter.get("ref", "")) not in completed_refs
        ]

    if not chapters_to_process:
        # Nothing new to align — the segment-array shards from the prior run
        # already stand. No legacy timestamps_full.json / timestamps.json is
        # written (single canonical format).
        log.info("No segments to process (all complete or skipped)")
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

        # Per-chapter start log. Without this, a producer-side stall (slow
        # ffmpeg decode, blocked seg_queue.put) is invisible until the first
        # 500-segment milestone — too coarse for diagnosing hangs on
        # big-audio reciters. Keep it short; one line per chapter @ 114
        # chapters is fine.
        try:
            src_label = audio_src if _is_url(audio_src) else f"bucket:{ch_ref}.mp3"
            src_size_mb = (
                Path(audio_src).stat().st_size / 1e6
                if not _is_url(audio_src) and Path(audio_src).exists()
                else None
            )
        except OSError:
            src_label, src_size_mb = audio_src, None
        if src_size_mb is not None:
            log.info("ch%s: start (src=%s, %.0fMB)", ch_ref, src_label, src_size_mb)
        else:
            log.info("ch%s: start (src=%s)", ch_ref, src_label)
        t_start = time.time()

        try:
            if _is_url(audio_src):
                audio_file = download_audio(audio_src)
            else:
                audio_file = Path(audio_src)
            t_dl = time.time()
            audio_int16 = load_audio_int16(audio_file)
            t_decode = time.time()
            if _is_url(audio_src):
                audio_file.unlink()
        except subprocess.TimeoutExpired:
            log.warning(
                "ch%s: ffmpeg decode TIMED OUT after %ds — skipping chapter",
                ch_ref,
                LOAD_AUDIO_TIMEOUT_SEC,
            )
            return ch_idx, ch_ref, 0
        except Exception as e:
            log.warning("ch%s: audio download/convert failed: %s", ch_ref, e)
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
                slice_audio(audio_int16, seg["time_start"], seg["time_end"], wav_path)
            except Exception as e:
                log.warning("Surah %s seg %d: slice failed: %s", ch_ref, seg_idx, e)
                continue

            # Bounded put — blocks if queue is full (backpressure)
            seg_queue.put((mfa_ref, str(wav_path), ch_idx, seg_idx))
            count += 1

        # Done log mirrors the start log: download / decode / total split so a
        # slow chapter can be isolated (FUSE-bound dl vs CPU-bound decode vs
        # MFA-bound queue back-pressure on the put loop).
        t_end = time.time()
        log.info(
            "ch%s: done in %.1fs (dl=%.1fs decode=%.1fs slice+queue=%.1fs, segs=%d)",
            ch_ref,
            t_end - t_start,
            t_dl - t_start,
            t_decode - t_dl,
            t_end - t_decode,
            count,
        )
        return ch_idx, ch_ref, count

    n_to_process = len(chapters_to_process)
    log.info(
        "Pipeline: %d chapters, %d download workers, batch_size=%d, beams=%s, %s",
        n_to_process,
        download_workers,
        batch_size,
        beams,
        f"pool workers={workers}" if use_pool else "single backend (serial)",
    )

    def _store_results(beam: int, batch_map, results, error_msg=None):
        """Push a batch's per-seg results into results_by_beam[beam]."""
        for i, (ch_idx, seg_idx) in enumerate(batch_map):
            if error_msg is not None:
                rec = {"status": "error", "error": error_msg}
            elif i < len(results):
                rec = results[i]
            else:
                rec = {"status": "error", "error": "missing result"}
            results_by_beam[beam].setdefault(ch_idx, []).append((seg_idx, rec))

    # Producer thread: drain download/slice futures, push WAVs onto seg_queue.
    def _producer_loop():
        try:
            with ThreadPoolExecutor(max_workers=download_workers) as ex:
                futures = {
                    ex.submit(_process_chapter, ci, ch): ci for ci, ch in chapters_to_process
                }
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
                    if total - last >= DOWNLOAD_LOG_INTERVAL or done == n_to_process:
                        log.info(
                            "Downloads: %d/%d verses (%d segments queued)",
                            done,
                            n_to_process,
                            total,
                        )
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
            log.info("Batch %d: submit %d segs × %d beams", bid, len(refs), len(beams))
            for b in beams:
                fut = pool.submit(
                    _worker_align,
                    list(refs),
                    list(paths),
                    method,
                    b,
                    shared_cmvn,
                    padding,
                    word_boundary_allocation,
                )
                future_meta[fut] = (bid, b)

        producer = threading.Thread(target=_producer_loop, daemon=True)
        producer.start()

        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
            initargs=(str(mfa_model_path), str(mfa_dictionary_path)),
        ) as pool:
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
            log.info("Batch %d: %d segs × %d beams (serial)", bid, len(refs), len(beams))
            ok = True
            for b in beams:
                try:
                    results = backend.align_batch(
                        refs,
                        paths,
                        method=method,
                        beam=b,
                        shared_cmvn=shared_cmvn,
                        padding=padding,
                        word_boundary_allocation=word_boundary_allocation,
                    )
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

    # Per-chapter temporal segment-array shards at
    # ``<output_dir>/timestamps/<chapter>.json.gz``. ``canonical_results``
    # carries every aligned segment, so build_raw_v2 keeps all occurrences and
    # build_segment_shards emits each one RAW as a recitation-ordered segment
    # entry ({ref, t, words}) — no dedup at write. Consumers derive whatever
    # projection they need; the inspector read-path is a byte pass-through.
    from quranic_phonemizer import Phonemizer

    from qua_shared.timestamps_bridges import (
        tag_v2_doc,  # lazy: keep phonemizer off the inspector import path
    )
    from qua_shared.timestamps_dedup import build_raw_v2  # lazy: avoid import cycle

    ts_dir = output_dir / "timestamps"
    ts_dir.mkdir(parents=True, exist_ok=True)

    # One phonemizer for cross-word bridge tagging across all chapters.
    bridge_pm = Phonemizer()

    # Slim aligner provenance stamped into each shard's ``_meta`` (reciter,
    # url_template and audio_urls are excluded — slug is the path, manifest is
    # the audio ground truth).
    shard_provenance = {
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audio_source": audio_source,
        "aligner_model": DEFAULT_ALIGNER_MODEL,
        "method": method,
        "beam": canonical_beam,
        "shared_cmvn": shared_cmvn,
        "padding": padding,
    }

    def _emit_segment_shards(results_by_ch, suffix=""):
        v2_doc = build_raw_v2(chapters, results_by_ch, audio_category)
        # Stamp cross-word tajweed bridge rules onto merger phones (schema v3).
        n_bridges = tag_v2_doc(bridge_pm, v2_doc)
        log.info("Tagged %d cross-word bridge phone(s)", n_bridges)
        shards = build_segment_shards(
            v2_doc, audio_category=audio_category, src_meta=shard_provenance
        )
        for ch_num, shard_doc in shards.items():
            (ts_dir / f"{ch_num}{suffix}.json.gz").write_bytes(gzip_shard(shard_doc))
        fails = len((v2_doc.get("_meta") or {}).get("mfa_failures", []))
        return len(shards), fails

    n_shards, n_fail = _emit_segment_shards(canonical_results)
    if n_fail:
        log.warning("Canonical beam %d: %d MFA failures", canonical_beam, n_fail)
    log.info(
        "Wrote %d segment-array timestamps shard(s) (beam=%d) -> %s",
        n_shards,
        canonical_beam,
        ts_dir,
    )

    # Probe beams → ONE verse-level ``ts_validation.json`` sidecar (the
    # verse-level analogue of low_confidence_v2.json) instead of per-beam
    # shard files. Flags verses whose alignment disagrees under tighter beams;
    # served owner-gated to the Timestamps-tab "ts-validation" accordion.
    ts_validation = build_ts_validation(
        chapters, results_by_beam, beams, reciter=reciter, method=method
    )
    # ts_validation.json is a WHOLE-RECITER sidecar but a partial run only
    # produced flags for the processed chapters. Merge: drop the existing flags
    # for the refreshed chapters (they're rebuilt) and keep every other chapter's,
    # so an affected-only regen never clobbers untouched chapters' flags.
    if refresh_chapters:
        ts_validation = _merge_ts_validation(
            output_dir / "ts_validation.json", ts_validation, refresh_chapters
        )
    (output_dir / "ts_validation.json").write_text(
        json.dumps(ts_validation, ensure_ascii=False), encoding="utf-8"
    )
    log.info(
        "Wrote ts_validation.json: %d flagged verse(s) across beams %s",
        len(ts_validation["verses"]),
        ts_validation["_meta"]["beams"],
    )

    _cleanup([], tmp_dir)
    return output_dir


def _submit_with_retry(
    refs,
    audio_paths,
    space_url,
    *,
    method,
    beam,
    shared_cmvn,
    padding=DEFAULT_PADDING,
    word_boundary_allocation=None,
    timeout=DEFAULT_TIMEOUT,
    max_retries=1,
):
    """Submit batch to MFA Space with one retry on failure."""
    for attempt in range(max_retries + 1):
        try:
            event_id, headers, base = mfa_upload_and_submit(
                refs,
                audio_paths,
                space_url,
                method=method,
                beam=beam,
                shared_cmvn=shared_cmvn,
                padding=padding,
                word_boundary_allocation=word_boundary_allocation,
                timeout=timeout,
            )
            log.info("Submitted batch (event_id=%s), waiting for results...", event_id)
            return mfa_wait_result(event_id, headers, base, timeout=timeout)
        except Exception as e:
            if attempt < max_retries:
                log.warning("MFA batch failed (%s), retrying in 30s...", e)
                time.sleep(30)
            else:
                log.error("MFA batch failed after %d retries: %s", max_retries, e)
    return None


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
        "--input",
        required=True,
        help="Path to reciter directory containing detailed.json",
    )
    parser.add_argument(
        "--space-url",
        default=DEFAULT_SPACE_URL,
        help=f"MFA HF Space URL (default: {DEFAULT_SPACE_URL})",
    )
    parser.add_argument(
        "--method", default=DEFAULT_METHOD, help="Alignment method (default: kalpy)"
    )
    parser.add_argument(
        "--beams",
        default=",".join(str(b) for b in DEFAULT_BEAMS),
        help="Comma-separated beam widths; the widest is canonical, the rest "
        f"are validation probes (default: {DEFAULT_BEAMS[0]})",
    )
    parser.add_argument(
        "--shared-cmvn", action="store_true", help="Compute shared CMVN across batch (kalpy only)"
    )
    parser.add_argument(
        "--padding",
        choices=["forward", "symmetric", "none"],
        default="forward",
        help="Phoneme gap-padding strategy (default: forward)",
    )
    parser.add_argument("--resume", action="store_true", help="Skip already-completed chapters")
    parser.add_argument(
        "--refresh-verses", help="Comma-separated verse keys to re-extract (e.g. 1:1,37:151,37:152)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Segments per MFA upload batch (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--download-workers",
        type=int,
        default=DEFAULT_DOWNLOAD_WORKERS,
        help=f"Parallel audio download/decode workers (default: {DEFAULT_DOWNLOAD_WORKERS})",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output directory (default: auto-derived from input path)",
    )

    args = parser.parse_args()
    input_dir = Path(args.input).resolve()
    output_dir = Path(args.output).resolve() if args.output else None
    refresh = set(args.refresh_verses.split(",")) if args.refresh_verses else None
    beams = [int(t) for t in args.beams.replace(" ", "").split(",") if t]

    process(
        input_dir=input_dir,
        backend=SpaceMfaBackend(args.space_url),
        method=args.method,
        beams=beams,
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
