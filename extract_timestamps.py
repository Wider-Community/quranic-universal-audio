#!/usr/bin/env python3
"""Extract word-level, letter-level, and phoneme-level timestamps via MFA.

Reads detailed.json from the segment extraction pipeline, downloads full
surah audio, slices segments, and submits them in one batch to the MFA
forced alignment HF Space.

Usage:
    python extract_timestamps.py --input data/recitation_segments/<reciter>/
    python extract_timestamps.py --input data/recitation_segments/<reciter>/ --resume
    python extract_timestamps.py --input data/recitation_segments/<reciter>/ --shared-cmvn
"""

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Load HF_TOKEN from quranic_universal_aligner/.env (overrides shell env to
# avoid stale tokens from prior activations)
# ---------------------------------------------------------------------------
_env_file = Path(__file__).parent / "quranic_universal_aligner" / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        if line.startswith("HF_TOKEN="):
            os.environ["HF_TOKEN"] = line.split("=", 1)[1].strip()
            break

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASMALA_TEXT = "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيم"
_ISTIATHA_TEXT = "أَعُوذُ بِٱللَّهِ مِنَ الشَّيْطَانِ الرَّجِيم"

DEFAULT_SPACE_URL = "https://hetchyy-quran-phoneme-mfa.hf.space"
DEFAULT_ALIGNER_MODEL = "quran_aligner_model"
DEFAULT_METHOD = "kalpy"
DEFAULT_BEAM = 20
DEFAULT_RETRY_BEAM = 50
DEFAULT_TIMEOUT = 600  # 10 minutes for large batches
DEFAULT_BATCH_SIZE = 500  # segments per MFA upload
BATCH_DELAY_SECONDS = 5  # pause between MFA batches to avoid rate-limiting
DOWNLOAD_LOG_INTERVAL = 500  # log download progress every N verses

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


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
    confidence, or transition segments like Amin/Takbir).
    """
    matched_ref = seg.get("matched_ref", "")
    confidence = seg.get("confidence", 0)

    if not matched_ref or confidence <= 0:
        return None

    # Skip transition segments (non-verse refs without colons)
    if ":" not in matched_ref:
        return None

    mfa_ref = matched_ref

    # Check for Basmala/Isti'adha prefix in matched_text (fused segments)
    matched_text = seg.get("matched_text", "")
    if matched_text.startswith(_ISTIATHA_TEXT):
        mfa_ref = f"Isti'adha+{mfa_ref}"
    elif matched_text.startswith(_BASMALA_TEXT):
        mfa_ref = f"Basmala+{mfa_ref}"

    return mfa_ref


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
                          method="kalpy", beam=10, retry_beam=40,
                          shared_cmvn=False, padding="forward",
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
    submit_resp = requests.post(
        f"{base_url}/gradio_api/call/align_batch",
        headers={**headers, "Content-Type": "application/json"},
        json={"data": [refs, file_data_list, method, str(beam), str(retry_beam),
                        str(shared_cmvn).lower(), padding]},
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

def process(input_dir: Path, space_url: str, method: str, beam: int,
            retry_beam: int, shared_cmvn: bool, resume: bool,
            batch_size: int = DEFAULT_BATCH_SIZE,
            output_dir: Path | None = None, padding: str = "forward",
            refresh_verses: set[str] | None = None):
    """Process all chapters from detailed.json through MFA alignment."""

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
            # Ensure verse boundaries exist on resumed data
            for ref, val in existing_data.items():
                words = val.get("words", [])
                if words and "verse_start_ms" not in val:
                    val["verse_start_ms"] = words[0][1]
                    val["verse_end_ms"] = words[-1][2]
            _write_output(output_dir / "timestamps_full.json", meta,
                          method, beam, retry_beam, shared_cmvn,
                          existing_data, padding=padding)
            words_data = {}
            for ref, val in existing_data.items():
                words_only = [[w[0], w[1], w[2]] for w in val["words"]]
                words_data[ref] = words_only
            _write_output(output_dir / "timestamps.json", meta,
                          method, beam, retry_beam, shared_cmvn, words_data,
                          padding=padding)
        return

    # --- Producer-consumer pipeline ---
    # Bounded queue prevents unbounded WAV accumulation on disk
    seg_queue = queue.Queue(maxsize=batch_size)
    error_event = threading.Event()
    # chapter_idx → [(seg_idx, result), ...] — written by consumer thread
    chapter_results: dict[int, list] = {}
    consumer_batch_count = [0]  # mutable counter for logging

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

    def _mfa_consumer():
        """Consume segments from queue, batch, and submit to MFA."""
        buf_refs = []
        buf_paths = []
        buf_map = []  # (ch_idx, seg_idx)

        def _flush_batch():
            if not buf_refs:
                return True
            consumer_batch_count[0] += 1
            batch_num = consumer_batch_count[0]
            log.info("Batch %d: submitting %d segments",
                     batch_num, len(buf_refs))
            results = _submit_with_retry(
                buf_refs, buf_paths, space_url,
                method=method, beam=beam,
                retry_beam=retry_beam, shared_cmvn=shared_cmvn,
                padding=padding)
            if results is None:
                log.error("Batch %d failed. Use --resume to continue.",
                          batch_num)
                return False
            log.info("Batch %d: received %d results",
                     batch_num, len(results))
            for i, (ch_idx, seg_idx) in enumerate(buf_map):
                if i < len(results):
                    chapter_results.setdefault(ch_idx, []).append(
                        (seg_idx, results[i]))
            # Cleanup WAV files for this batch
            for p in buf_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass
            buf_refs.clear()
            buf_paths.clear()
            buf_map.clear()
            # Throttle between batches to avoid HF rate-limiting
            if BATCH_DELAY_SECONDS > 0:
                time.sleep(BATCH_DELAY_SECONDS)
            return True

        while True:
            try:
                item = seg_queue.get(timeout=1.0)
            except queue.Empty:
                if error_event.is_set():
                    break
                continue

            if item is None:
                # Sentinel: flush remaining buffer and exit
                _flush_batch()
                break

            mfa_ref, wav_path, ch_idx, seg_idx = item
            buf_refs.append(mfa_ref)
            buf_paths.append(wav_path)
            buf_map.append((ch_idx, seg_idx))

            if len(buf_refs) >= batch_size:
                if not _flush_batch():
                    error_event.set()
                    break

    # Start consumer thread
    consumer = threading.Thread(target=_mfa_consumer, daemon=True)
    consumer.start()

    # Producer: download and slice in parallel
    download_workers = 8
    n_to_process = len(chapters_to_process)
    log.info("Pipeline: %d chapters, %d download workers, batch_size=%d",
             n_to_process, download_workers, batch_size)
    total_segments = 0
    verses_done = 0
    last_logged = 0
    with ThreadPoolExecutor(max_workers=download_workers) as executor:
        futures = {
            executor.submit(_process_chapter, ch_idx, chapter): ch_idx
            for ch_idx, chapter in chapters_to_process
        }
        for future in as_completed(futures):
            ch_idx, ch_ref, count = future.result()
            verses_done += 1
            if count == 0:
                skipped_chapters.append(ch_ref)
            else:
                total_segments += count
            if (total_segments - last_logged >= DOWNLOAD_LOG_INTERVAL
                    or verses_done == n_to_process):
                log.info("Downloads: %d/%d verses (%d segments queued)",
                         verses_done, n_to_process, total_segments)
                last_logged = total_segments

    # Signal consumer that all producers are done
    seg_queue.put(None)
    consumer.join()

    # If consumer errored, drain queue to unblock any stuck producers
    # and clean up orphan WAV files
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

    if not chapter_results and not existing_data:
        log.info("No segments processed (all skipped or failed)")
        _cleanup([], tmp_dir)
        return

    # Phase 3: Build verse-keyed output dicts (full + words-only)
    full_data = dict(existing_data) if load_existing else {}
    words_data = {}
    mfa_failures = []  # track failed MFA alignments
    if load_existing:
        for ref, val in existing_data.items():
            words_only = [[w[0], w[1], w[2]] for w in val["words"]]
            words_data[ref] = words_only

    for ch_idx, chapter in enumerate(chapters):
        ch_ref = str(chapter.get("ref", ""))
        if audio_category == "by_surah_audio":
            if ch_ref in completed_surahs and ch_ref not in (refresh_surahs or set()):
                continue
        else:
            if ch_ref in completed_refs:
                continue
        if ch_idx not in chapter_results:
            continue

        if audio_category == "by_surah_audio":
            # by-surah: each chapter = full surah, distribute words to
            # individual verse keys derived from each word's MFA location.
            for seg_idx, result in chapter_results[ch_idx]:
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

                # Group words by verse key from MFA location field.
                # For cross-verse segments (e.g. "37:151:3-37:152:2"),
                # each word's location ("37:151:3", "37:152:1") tells
                # us which verse it belongs to.
                words_by_verse: dict[str, list] = {}
                for w in result.get("words", []):
                    location = w["location"]  # "surah:ayah:word"
                    verse_key = location.rsplit(":", 1)[0]  # "surah:ayah"
                    word_data = _convert_word(w, seg_offset_ms)
                    words_by_verse.setdefault(verse_key, []).append(word_data)

                if not words_by_verse:
                    continue

                # Provenance-aware merge: see `_merge_seg_words` docstring.
                for verse_key, verse_words in words_by_verse.items():
                    entry = full_data.setdefault(
                        verse_key, {"words": [], "_provenance": []})
                    if "_provenance" not in entry:
                        # Pre-existing entry loaded from a prior run: treat
                        # existing words as primary so repetitions don't
                        # evict them.
                        entry["_provenance"] = [True] * len(entry["words"])
                    _merge_seg_words(entry, matched_ref, verse_key, verse_words)
        else:
            # by-ayah: each chapter entry = one verse, ref is the key
            all_words = []
            # Prefix for filtering bleeding words from cross-verse segments:
            # e.g. ch_ref="5:70" → verse_prefix="5:70:"
            verse_prefix = f"{ch_ref}:" if ":" in ch_ref else None
            for seg_idx, result in chapter_results[ch_idx]:
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
                # Filter out bleeding words from adjacent verses.
                # MFA location is "surah:ayah:word"; only keep words
                # whose surah:ayah matches this entry's verse.
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

    # Drop non-verse keys (e.g. "0:0" from Basmala/Isti'adha prefixes)
    for ref in list(full_data.keys()):
        if ref.startswith("0:"):
            del full_data[ref]

    # Post-process: sort words, compute verse boundaries, clean up tracking
    for ref, val in full_data.items():
        val.pop("_home_indices", None)
        val.pop("_provenance", None)
        words = val["words"]
        # Sort by start time — sorting by word index breaks cross-verse
        # segments where indices reset at verse boundaries (e.g. 3,4,5,1,2)
        words.sort(key=lambda w: w[1])
        if words:
            val["verse_start_ms"] = words[0][1]
            val["verse_end_ms"] = words[-1][2]

    # Build words-only data from full_data (covers both paths)
    for ref, val in full_data.items():
        if ref not in words_data:
            words_only = [[w[0], w[1], w[2]] for w in val["words"]]
            words_data[ref] = words_only

    if mfa_failures:
        log.warning("%d MFA alignment failures recorded", len(mfa_failures))

    full_path = output_dir / "timestamps_full.json"
    words_path = output_dir / "timestamps.json"
    _write_output(full_path, meta, method, beam, retry_beam,
                  shared_cmvn, full_data, mfa_failures, padding=padding)
    _write_output(words_path, meta, method, beam, retry_beam,
                  shared_cmvn, words_data, mfa_failures, padding=padding)
    log.info("Wrote %s (%d verses) and %s",
             full_path, len(full_data), words_path)

    # Clean up any remaining temp files
    _cleanup([], tmp_dir)


def _submit_with_retry(refs, audio_paths, space_url, *, method, beam,
                       retry_beam, shared_cmvn, padding="forward",
                       max_retries=1):
    """Submit batch to MFA Space with one retry on failure."""
    for attempt in range(max_retries + 1):
        try:
            event_id, headers, base = mfa_upload_and_submit(
                refs, audio_paths, space_url,
                method=method, beam=beam, retry_beam=retry_beam,
                shared_cmvn=shared_cmvn, padding=padding)
            log.info("Submitted batch (event_id=%s), waiting for results...", event_id)
            return mfa_wait_result(event_id, headers, base)
        except Exception as e:
            if attempt < max_retries:
                log.warning("MFA batch failed (%s), retrying in 30s...", e)
                time.sleep(30)
            else:
                log.error("MFA batch failed after %d retries: %s", max_retries, e)
    return None


def _write_output(output_path, meta, method, beam, retry_beam,
                  shared_cmvn, output_data, mfa_failures=None,
                  padding="forward"):
    """Write the output JSON file."""
    out_meta = {
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "audio_source": meta.get("audio_source", "") if meta else "",
        "aligner_model": DEFAULT_ALIGNER_MODEL,
        "method": method,
        "beam": beam,
        "retry_beam": retry_beam,
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
    parser.add_argument("-o", "--output", default=None,
                        help="Output directory (default: auto-derived from input path)")

    args = parser.parse_args()
    input_dir = Path(args.input).resolve()
    output_dir = Path(args.output).resolve() if args.output else None
    refresh = set(args.refresh_verses.split(",")) if args.refresh_verses else None

    process(
        input_dir=input_dir,
        space_url=args.space_url,
        method=args.method,
        beam=args.beam,
        retry_beam=args.retry_beam,
        shared_cmvn=args.shared_cmvn,
        resume=args.resume,
        batch_size=args.batch_size,
        output_dir=output_dir,
        padding=args.padding,
        refresh_verses=refresh,
    )


if __name__ == "__main__":
    main()
