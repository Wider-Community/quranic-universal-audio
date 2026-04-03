"""Session-based API: persistence layer + endpoint wrappers.

Sessions store preprocessed audio and VAD data in /tmp so that
follow-up calls (resegment, retranscribe, realign) skip expensive
re-uploads and re-inference.
"""

import hashlib
import json
import math
import os
import pickle
import re
import shutil
import time
import uuid

import gradio as gr
import numpy as np

from config import SESSION_DIR, SESSION_EXPIRY_SECONDS, PHONEME_ASR_MODELS
from src.core.zero_gpu import QuotaExhaustedError

# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------

_last_cleanup_time = 0.0
_CLEANUP_INTERVAL = 1800  # sweep at most every 30 min

_VALID_ID = re.compile(r"^[0-9a-f]{32}$")
_VALID_MODELS = set(PHONEME_ASR_MODELS.keys())


def _validate_model_name(model_name):
    """Return an error dict if model_name is invalid, else None."""
    if model_name not in _VALID_MODELS:
        valid = ", ".join(sorted(_VALID_MODELS))
        return {"error": f"Invalid model_name '{model_name}'. Must be one of: {valid}", "segments": []}


def _session_dir(audio_id: str):
    return SESSION_DIR / audio_id


def _validate_id(audio_id: str) -> bool:
    return isinstance(audio_id, str) and bool(_VALID_ID.match(audio_id))


def _is_expired(created_at: float) -> bool:
    return (time.time() - created_at) > SESSION_EXPIRY_SECONDS


def _sweep_expired():
    """Delete expired session directories (runs at most every 30 min)."""
    global _last_cleanup_time
    now = time.time()
    if now - _last_cleanup_time < _CLEANUP_INTERVAL:
        return
    _last_cleanup_time = now
    if not SESSION_DIR.exists():
        return
    for entry in SESSION_DIR.iterdir():
        if not entry.is_dir():
            continue
        ts_file = entry / "created_at"
        if not ts_file.exists() or _is_expired(float(ts_file.read_text())):
            shutil.rmtree(entry, ignore_errors=True)


def _intervals_hash(intervals) -> str:
    return hashlib.md5(json.dumps(intervals).encode()).hexdigest()


def create_session(audio, speech_intervals, is_complete, intervals, model_name):
    """Persist session data and return audio_id (32-char hex UUID).

    Uses pickle for VAD artifacts (speech_intervals, is_complete) to
    preserve exact types (torch.Tensor etc.) expected by the segmenter.
    Uses np.save for the audio array (large, always float32 numpy).
    """
    _sweep_expired()
    audio_id = uuid.uuid4().hex
    path = _session_dir(audio_id)
    path.mkdir(parents=True, exist_ok=True)

    # Audio is always a float32 numpy array after preprocessing
    np.save(path / "audio.npy", audio)

    # VAD artifacts: preserve original types via pickle
    with open(path / "vad.pkl", "wb") as f:
        pickle.dump({"speech_intervals": speech_intervals,
                      "is_complete": is_complete}, f)

    # Lightweight metadata (JSON-safe types only)
    meta = {
        "intervals": intervals,
        "model_name": model_name,
        "intervals_hash": _intervals_hash(intervals),
        "audio_duration_s": round(len(audio) / 16000, 2),
    }
    with open(path / "metadata.json", "w") as f:
        json.dump(meta, f)

    # Timestamp file for cheap expiry checks during sweep
    (path / "created_at").write_text(str(time.time()))

    return audio_id


def load_session(audio_id):
    """Load session data. Returns dict or None if missing/expired/invalid."""
    if not _validate_id(audio_id):
        return None
    path = _session_dir(audio_id)
    if not path.exists():
        return None

    ts_file = path / "created_at"
    if not ts_file.exists() or _is_expired(float(ts_file.read_text())):
        shutil.rmtree(path, ignore_errors=True)
        return None

    audio = np.load(path / "audio.npy")

    with open(path / "vad.pkl", "rb") as f:
        vad = pickle.load(f)

    with open(path / "metadata.json") as f:
        meta = json.load(f)

    return {
        "audio": audio,
        "speech_intervals": vad["speech_intervals"],
        "is_complete": vad["is_complete"],
        "intervals": meta["intervals"],
        "model_name": meta["model_name"],
        "intervals_hash": meta.get("intervals_hash", ""),
        "audio_id": audio_id,
    }


def update_session(audio_id, *, intervals=None, model_name=None):
    """Update mutable session fields (intervals, model_name)."""
    path = _session_dir(audio_id)
    meta_path = path / "metadata.json"
    if not meta_path.exists():
        return
    with open(meta_path) as f:
        meta = json.load(f)
    if intervals is not None:
        meta["intervals"] = intervals
        meta["intervals_hash"] = _intervals_hash(intervals)
    if model_name is not None:
        meta["model_name"] = model_name
    tmp = path / "metadata.tmp"
    with open(tmp, "w") as f:
        json.dump(meta, f)
    os.replace(tmp, meta_path)


def _save_segments(audio_id, segments):
    """Persist alignment segments for later MFA use."""
    path = _session_dir(audio_id)
    if not path.exists():
        return
    seg_path = path / "segments.json"
    tmp = path / "segments.tmp"
    with open(tmp, "w") as f:
        json.dump(segments, f)
    os.replace(tmp, seg_path)


def _load_segments(audio_id):
    """Load stored segments. Returns list or None."""
    if not _validate_id(audio_id):
        return None
    path = _session_dir(audio_id)
    seg_path = path / "segments.json"
    if not seg_path.exists():
        return None
    with open(seg_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------

_SESSION_ERROR = {"error": "Session not found or expired", "segments": []}


# ---------------------------------------------------------------------------
# Duration estimation
# ---------------------------------------------------------------------------

_ESTIMABLE_ENDPOINTS = {
    "process_audio_session",
    "process_url_session",
    "resegment",
    "retranscribe",
    "realign_from_timestamps",
    "timestamps",
    "timestamps_direct",
}

_MFA_ENDPOINTS = {"timestamps", "timestamps_direct"}
_VAD_ENDPOINTS = {"process_audio_session", "process_url_session"}


def _load_session_metadata(audio_id):
    """Load only metadata.json (no audio/VAD). Returns dict or None."""
    if not _validate_id(audio_id):
        return None
    path = _session_dir(audio_id)
    meta_path = path / "metadata.json"
    if not meta_path.exists():
        return None
    ts_file = path / "created_at"
    if not ts_file.exists() or _is_expired(float(ts_file.read_text())):
        return None
    with open(meta_path) as f:
        return json.load(f)


def estimate_duration(endpoint, audio_duration_s=None, audio_id=None,
                      model_name="Base", device="GPU"):
    """Estimate processing duration for a given endpoint.

    Uses direct wall-time regression (not sum of lease components) fitted on
    257 runs from hetchyy/quran-aligner-logs v1 dataset.
    """
    from config import (
        ESTIMATE_GPU_BASE_SLOPE, ESTIMATE_GPU_BASE_INTERCEPT,
        ESTIMATE_GPU_LARGE_SLOPE, ESTIMATE_GPU_LARGE_INTERCEPT,
        ESTIMATE_CPU_BASE_SLOPE, ESTIMATE_CPU_BASE_INTERCEPT,
        ESTIMATE_CPU_LARGE_SLOPE, ESTIMATE_CPU_LARGE_INTERCEPT,
        ESTIMATE_WALL_BUFFER,
        MFA_PROGRESS_SEGMENT_RATE,
    )

    _error = {"estimated_duration_s": None}

    if endpoint not in _ESTIMABLE_ENDPOINTS:
        _error["error"] = (
            f"Unknown endpoint '{endpoint}'. "
            f"Valid: {', '.join(sorted(_ESTIMABLE_ENDPOINTS))}"
        )
        return _error

    # --- Resolve audio duration ---
    meta = None
    if audio_id:
        meta = _load_session_metadata(audio_id)

    if audio_duration_s is not None and audio_duration_s > 0:
        duration_s = float(audio_duration_s)
    elif meta and meta.get("audio_duration_s"):
        duration_s = meta["audio_duration_s"]
    else:
        _error["error"] = (
            "audio_duration_s is required (or provide audio_id with an existing session)"
        )
        return _error

    minutes = duration_s / 60.0

    # --- MFA endpoints require session with stored segments ---
    if endpoint in _MFA_ENDPOINTS:
        if not audio_id:
            _error["error"] = "MFA estimation requires audio_id with existing segments"
            return _error
        segments = _load_segments(audio_id)
        if not segments:
            _error["error"] = "No segments found in session — run an alignment endpoint first"
            return _error
        num_segments = len(segments)
        estimate = MFA_PROGRESS_SEGMENT_RATE * num_segments
    else:
        # --- Pipeline endpoints: direct wall-time regression ---
        device_upper = (device or "GPU").upper()
        is_large = model_name == "Large"

        if device_upper == "CPU":
            if is_large:
                estimate = ESTIMATE_CPU_LARGE_SLOPE * minutes + ESTIMATE_CPU_LARGE_INTERCEPT
            else:
                estimate = ESTIMATE_CPU_BASE_SLOPE * minutes + ESTIMATE_CPU_BASE_INTERCEPT
        else:
            if is_large:
                estimate = ESTIMATE_GPU_LARGE_SLOPE * minutes + ESTIMATE_GPU_LARGE_INTERCEPT
            else:
                estimate = ESTIMATE_GPU_BASE_SLOPE * minutes + ESTIMATE_GPU_BASE_INTERCEPT

        # Retranscribe/realign skip VAD — scale down by ~50% (ASR+DP only)
        if endpoint not in _VAD_ENDPOINTS:
            estimate *= 0.5

        estimate *= ESTIMATE_WALL_BUFFER

    rounded = max(5, math.ceil(estimate / 5) * 5)

    return {
        "endpoint": endpoint,
        "estimated_duration_s": rounded,
        "device": device,
        "model_name": model_name,
    }


def _format_response(audio_id, json_output, warning=None):
    """Convert pipeline json_output to the documented API response schema."""
    segments = []
    for seg in json_output.get("segments", []):
        entry = {
            "segment": seg["segment"],
            "time_from": seg["time_from"],
            "time_to": seg["time_to"],
            "ref_from": seg["ref_from"],
            "ref_to": seg["ref_to"],
            "matched_text": seg["matched_text"],
            "confidence": seg["confidence"],
            "has_missing_words": seg.get("has_missing_words", False),
            "has_repeated_words": seg.get("has_repeated_words", False),
            "error": seg["error"],
        }
        if seg.get("special_type"):
            entry["special_type"] = seg["special_type"]
        if seg.get("repeated_ranges"):
            entry["repeated_ranges"] = seg["repeated_ranges"]
            entry["repeated_text"] = seg["repeated_text"]
        segments.append(entry)
    _save_segments(audio_id, segments)
    resp = {"audio_id": audio_id, "segments": segments}
    if warning:
        resp["warning"] = warning
    return resp


# ---------------------------------------------------------------------------
# Endpoint wrappers
# ---------------------------------------------------------------------------

def process_audio_session(audio_data, min_silence_ms, min_speech_ms, pad_ms,
                          model_name="Base", device="GPU",
                          request: gr.Request = None):
    """Full pipeline: preprocess -> VAD -> ASR -> alignment. Creates session."""
    err = _validate_model_name(model_name)
    if err:
        return err
    from src.pipeline import process_audio

    quota_warning = None
    try:
        result = process_audio(
            audio_data, int(min_silence_ms), int(min_speech_ms), int(pad_ms),
            model_name, device, request=request, endpoint="process",
        )
    except QuotaExhaustedError as e:
        reset_msg = f" Resets in {e.reset_time}." if e.reset_time else ""
        quota_warning = f"GPU quota reached — processed on CPU (slower).{reset_msg}"
        result = process_audio(
            audio_data, int(min_silence_ms), int(min_speech_ms), int(pad_ms),
            model_name, "CPU", request=request, endpoint="process",
        )
    # result is a 9-tuple:
    # (html, json_output, speech_intervals, is_complete, audio, sr, intervals, seg_dir, log_row)
    json_output = result[1]
    if json_output is None:
        return {"error": "No speech detected in audio", "segments": []}

    speech_intervals = result[2]
    is_complete = result[3]
    audio_ref = result[4]
    intervals = result[6]

    # Resolve audio from pipeline cache (result[4] is now a cache key, not array)
    from src.pipeline import _load_audio
    audio, _ = _load_audio(audio_ref)

    audio_id = create_session(
        audio, speech_intervals, is_complete, intervals, model_name,
    )
    return _format_response(audio_id, json_output, warning=quota_warning)


def process_url_session(url, min_silence_ms, min_speech_ms, pad_ms,
                        model_name="Base", device="GPU",
                        request: gr.Request = None):
    """Full pipeline from URL: download -> preprocess -> VAD -> ASR -> alignment.

    Downloads audio via yt-dlp, then runs the same pipeline as
    process_audio_session. Returns the same response format with an
    additional url_metadata field.
    """
    err = _validate_model_name(model_name)
    if err:
        return err

    if not url or not isinstance(url, str) or not url.strip():
        return {"error": "URL is required", "segments": []}

    url = url.strip()

    # Download audio
    try:
        from src.ui.handlers import _download_url_core
        wav_path, url_meta = _download_url_core(url)
    except Exception as e:
        return {"error": f"Download failed: {e}", "segments": []}

    # Run the standard pipeline with the downloaded WAV path
    from src.pipeline import process_audio

    quota_warning = None
    try:
        result = process_audio(
            wav_path, int(min_silence_ms), int(min_speech_ms), int(pad_ms),
            model_name, device, request=request, endpoint="process_url",
        )
    except QuotaExhaustedError as e:
        reset_msg = f" Resets in {e.reset_time}." if e.reset_time else ""
        quota_warning = f"GPU quota reached — processed on CPU (slower).{reset_msg}"
        result = process_audio(
            wav_path, int(min_silence_ms), int(min_speech_ms), int(pad_ms),
            model_name, "CPU", request=request, endpoint="process_url",
        )

    json_output = result[1]
    if json_output is None:
        return {"error": "No speech detected in audio", "segments": []}

    speech_intervals = result[2]
    is_complete = result[3]
    audio_ref = result[4]
    intervals = result[6]

    from src.pipeline import _load_audio
    audio, _ = _load_audio(audio_ref)

    audio_id = create_session(
        audio, speech_intervals, is_complete, intervals, model_name,
    )

    response = _format_response(audio_id, json_output, warning=quota_warning)
    response["url_metadata"] = {
        "title": url_meta.get("title"),
        "duration": url_meta.get("duration"),
        "source_url": url_meta.get("source_url"),
    }

    # Clean up downloaded WAV (audio is now cached in session)
    try:
        os.remove(wav_path)
    except OSError:
        pass

    return response


def resegment(audio_id, min_silence_ms, min_speech_ms, pad_ms,
                       model_name="Base", device="GPU",
                       request: gr.Request = None):
    """Re-clean VAD boundaries with new params and re-run ASR + alignment."""
    err = _validate_model_name(model_name)
    if err:
        err["audio_id"] = audio_id
        return err
    session = load_session(audio_id)
    if session is None:
        return _SESSION_ERROR

    from src.pipeline import resegment_audio

    quota_warning = None
    try:
        result = resegment_audio(
            session["speech_intervals"], session["is_complete"],
            session["audio"], 16000,
            int(min_silence_ms), int(min_speech_ms), int(pad_ms),
            model_name, device, request=request, endpoint="resegment",
        )
    except QuotaExhaustedError as e:
        reset_msg = f" Resets in {e.reset_time}." if e.reset_time else ""
        quota_warning = f"GPU quota reached — processed on CPU (slower).{reset_msg}"
        result = resegment_audio(
            session["speech_intervals"], session["is_complete"],
            session["audio"], 16000,
            int(min_silence_ms), int(min_speech_ms), int(pad_ms),
            model_name, "CPU", request=request, endpoint="resegment",
        )
    json_output = result[1]
    if json_output is None:
        return {"audio_id": audio_id, "error": "No segments with these settings", "segments": []}

    new_intervals = result[6]
    update_session(audio_id, intervals=new_intervals, model_name=model_name)
    return _format_response(audio_id, json_output, warning=quota_warning)


def retranscribe(audio_id, model_name="Base", device="GPU",
                          request: gr.Request = None):
    """Re-run ASR with a different model on current segment boundaries."""
    err = _validate_model_name(model_name)
    if err:
        err["audio_id"] = audio_id
        return err
    session = load_session(audio_id)
    if session is None:
        return _SESSION_ERROR

    # Guard: reject if model and boundaries unchanged
    if (model_name == session["model_name"]
            and _intervals_hash(session["intervals"]) == session["intervals_hash"]):
        return {
            "audio_id": audio_id,
            "error": "Model and boundaries unchanged. Change model_name or call /resegment first.",
            "segments": [],
        }

    from src.pipeline import retranscribe_audio

    quota_warning = None
    try:
        result = retranscribe_audio(
            session["intervals"],
            session["audio"], 16000,
            session["speech_intervals"], session["is_complete"],
            model_name, device, request=request, endpoint="retranscribe",
        )
    except QuotaExhaustedError as e:
        reset_msg = f" Resets in {e.reset_time}." if e.reset_time else ""
        quota_warning = f"GPU quota reached — processed on CPU (slower).{reset_msg}"
        result = retranscribe_audio(
            session["intervals"],
            session["audio"], 16000,
            session["speech_intervals"], session["is_complete"],
            model_name, "CPU", request=request, endpoint="retranscribe",
        )
    json_output = result[1]
    if json_output is None:
        return {"audio_id": audio_id, "error": "Retranscription failed", "segments": []}

    update_session(audio_id, model_name=model_name)
    return _format_response(audio_id, json_output, warning=quota_warning)


def realign_from_timestamps(audio_id, timestamps, model_name="Base", device="GPU",
                             request: gr.Request = None):
    """Run ASR + alignment on caller-provided timestamp intervals."""
    err = _validate_model_name(model_name)
    if err:
        err["audio_id"] = audio_id
        return err
    session = load_session(audio_id)
    if session is None:
        return _SESSION_ERROR

    # Parse timestamps: accept list of {"start": f, "end": f} dicts
    if isinstance(timestamps, str):
        timestamps = json.loads(timestamps)

    intervals = [(ts["start"], ts["end"]) for ts in timestamps]

    from src.pipeline import realign_audio

    quota_warning = None
    try:
        result = realign_audio(
            intervals,
            session["audio"], 16000,
            session["speech_intervals"], session["is_complete"],
            model_name, device, request=request, endpoint="realign",
        )
    except QuotaExhaustedError as e:
        reset_msg = f" Resets in {e.reset_time}." if e.reset_time else ""
        quota_warning = f"GPU quota reached — processed on CPU (slower).{reset_msg}"
        result = realign_audio(
            intervals,
            session["audio"], 16000,
            session["speech_intervals"], session["is_complete"],
            model_name, "CPU", request=request, endpoint="realign",
        )
    json_output = result[1]
    if json_output is None:
        return {"audio_id": audio_id, "error": "Alignment failed", "segments": []}

    new_intervals = result[6]
    update_session(audio_id, intervals=new_intervals, model_name=model_name)
    return _format_response(audio_id, json_output, warning=quota_warning)


# ---------------------------------------------------------------------------
# MFA timestamp helpers
# ---------------------------------------------------------------------------

def _preprocess_api_audio(audio_data):
    """Convert audio input to 16kHz mono float32 numpy array.

    Handles file path (str) and Gradio numpy tuple (sample_rate, array).
    Returns (audio_np, sample_rate).
    """
    import librosa
    from config import RESAMPLE_TYPE

    if isinstance(audio_data, str):
        audio, sr = librosa.load(audio_data, sr=16000, mono=True, res_type=RESAMPLE_TYPE)
        return audio, 16000

    sample_rate, audio = audio_data
    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32768.0
    elif audio.dtype == np.int32:
        audio = audio.astype(np.float32) / 2147483648.0
    if len(audio.shape) > 1:
        audio = audio.mean(axis=1)
    if sample_rate != 16000:
        audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000, res_type=RESAMPLE_TYPE)
        sample_rate = 16000
    return audio, sample_rate


def _create_segment_wavs(audio_np, sample_rate, segments):
    """Slice audio by segment boundaries and write WAV files.

    Returns the temp directory path containing seg_0.wav, seg_1.wav, etc.
    """
    import tempfile
    import soundfile as sf

    seg_dir = tempfile.mkdtemp(prefix="mfa_api_")
    for seg in segments:
        seg_idx = seg.get("segment", 0) - 1
        time_from = seg.get("time_from", 0)
        time_to = seg.get("time_to", 0)
        start_sample = int(time_from * sample_rate)
        end_sample = int(time_to * sample_rate)
        segment_audio = audio_np[start_sample:end_sample]
        wav_path = os.path.join(seg_dir, f"seg_{seg_idx}.wav")
        sf.write(wav_path, segment_audio, sample_rate)
    return seg_dir


# ---------------------------------------------------------------------------
# MFA timestamp helpers
# ---------------------------------------------------------------------------

_SPECIAL_TEXT = {
    "Basmala": "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيم",
    "Isti'adha": "أَعُوذُ بِٱللَّهِ مِنَ الشَّيْطَانِ الرَّجِيم",
    "Amin": "آمِين",
    "Takbir": "اللَّهُ أَكْبَر",
    "Tahmeed": "سَمِعَ اللَّهُ لِمَنْ حَمِدَه",
    "Tasleem": "ٱلسَّلَامُ عَلَيْكُمْ وَرَحْمَةُ ٱللَّه",
    "Sadaqa": "صَدَقَ ٱللَّهُ ٱلْعَظِيم",
}


def _normalize_segments(segments):
    """Fill defaults so callers can pass minimal segment dicts (timestamps + refs).

    Auto-assigns ``segment`` numbers, defaults ``confidence`` to 1.0, and
    derives ``matched_text`` from ``special_type`` for special segments.
    """
    normalized = []
    for i, seg in enumerate(segments):
        entry = dict(seg)
        if "segment" not in entry:
            entry["segment"] = i + 1
        if "confidence" not in entry:
            entry["confidence"] = 1.0
        if "matched_text" not in entry:
            special = entry.get("special_type", "")
            entry["matched_text"] = _SPECIAL_TEXT.get(special, "")
        normalized.append(entry)
    return normalized


# ---------------------------------------------------------------------------
# MFA timestamp endpoints
# ---------------------------------------------------------------------------

def timestamps(audio_id, segments_json=None, granularity="words"):
    """Compute MFA word/letter timestamps using session audio."""
    if granularity == "words+chars":
        return {"audio_id": audio_id, "error": "chars granularity is currently disabled via API", "segments": []}

    session = load_session(audio_id)
    if session is None:
        return _SESSION_ERROR

    # Parse segments: use provided or load stored
    if isinstance(segments_json, str):
        segments_json = json.loads(segments_json)

    if segments_json:
        segments = _normalize_segments(segments_json)
    else:
        segments = _load_segments(audio_id)
        if not segments:
            return {"audio_id": audio_id, "error": "No segments found in session", "segments": []}

    # Create segment WAVs from session audio
    try:
        seg_dir = _create_segment_wavs(session["audio"], 16000, segments)
    except Exception as e:
        return {"audio_id": audio_id, "error": f"Failed to create segment audio: {e}", "segments": []}

    from src.mfa import compute_mfa_timestamps_api
    try:
        result = compute_mfa_timestamps_api(segments, seg_dir, granularity or "words")
    except Exception as e:
        return {"audio_id": audio_id, "error": f"MFA alignment failed: {e}", "segments": []}

    result["audio_id"] = audio_id
    return result


def timestamps_direct(audio_data, segments_json, granularity="words"):
    """Compute MFA word/letter timestamps with provided audio and segments."""
    if granularity == "words+chars":
        return {"error": "chars granularity is currently disabled via API", "segments": []}

    # Parse segments
    if isinstance(segments_json, str):
        segments_json = json.loads(segments_json)

    if not segments_json:
        return {"error": "No segments provided", "segments": []}

    segments = _normalize_segments(segments_json)

    # Preprocess audio
    try:
        audio_np, sr = _preprocess_api_audio(audio_data)
    except Exception as e:
        return {"error": f"Failed to preprocess audio: {e}", "segments": []}

    # Create segment WAVs
    try:
        seg_dir = _create_segment_wavs(audio_np, sr, segments)
    except Exception as e:
        return {"error": f"Failed to create segment audio: {e}", "segments": []}

    from src.mfa import compute_mfa_timestamps_api
    try:
        result = compute_mfa_timestamps_api(segments, seg_dir, granularity or "words")
    except Exception as e:
        return {"error": f"MFA alignment failed: {e}", "segments": []}

    return result


# ---------------------------------------------------------------------------
# Hidden debug endpoint
# ---------------------------------------------------------------------------

import dataclasses
import threading
from datetime import datetime, timezone

_debug_lock = threading.Lock()


def debug_process(audio_data, min_silence_ms, min_speech_ms, pad_ms,
                  model_name="Base", device="GPU", hf_token="",
                  request: gr.Request = None):
    """Hidden debug endpoint: full pipeline with comprehensive debug output.

    Authenticated via HF token comparison against the Space secret.
    Returns structured debug data from every pipeline stage.
    """
    # --- Auth ---
    space_token = os.environ.get("HF_TOKEN", "")
    if not hf_token or (space_token and hf_token != space_token):
        return {"error": "Unauthorized"}

    err = _validate_model_name(model_name)
    if err:
        return err

    from src.core.debug_collector import start_debug_collection, stop_debug_collection
    from src.pipeline import process_audio

    with _debug_lock:
        try:
            start_debug_collection()

            result = process_audio(
                audio_data, int(min_silence_ms), int(min_speech_ms), int(pad_ms),
                model_name, device, request=request, endpoint="process",
            )

            collector = stop_debug_collection()
        except Exception as e:
            stop_debug_collection()
            return {"error": f"Pipeline failed: {e}"}

    # --- Assemble response ---
    json_output = result[1]
    if json_output is None:
        return {"error": "No speech detected in audio", "segments": []}

    # Extract profiling from collector (stored by _run_post_vad_pipeline)
    profiling_dict = {}
    if collector and collector._profiling is not None:
        p = collector._profiling
        profiling_dict = dataclasses.asdict(p)
        # Add computed fields
        profiling_dict["phoneme_dp_avg_time"] = p.phoneme_dp_avg_time
        profiling_dict["summary_text"] = p.summary()

    # Format segments (same as _format_response but without session)
    segments = []
    for seg in json_output.get("segments", []):
        entry = {
            "segment": seg["segment"],
            "time_from": seg["time_from"],
            "time_to": seg["time_to"],
            "ref_from": seg["ref_from"],
            "ref_to": seg["ref_to"],
            "matched_text": seg["matched_text"],
            "confidence": seg["confidence"],
            "has_missing_words": seg.get("has_missing_words", False),
            "has_repeated_words": seg.get("has_repeated_words", False),
            "error": seg["error"],
        }
        if seg.get("special_type"):
            entry["special_type"] = seg["special_type"]
        if seg.get("repeated_ranges"):
            entry["repeated_ranges"] = seg["repeated_ranges"]
            entry["repeated_text"] = seg["repeated_text"]
        segments.append(entry)

    # Build final response
    response = {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profiling": profiling_dict,
        "segments": segments,
    }

    # Merge collector sections
    if collector:
        debug_data = collector.to_dict()
        response["vad"] = debug_data["vad"]
        response["asr"] = debug_data["asr"]
        response["anchor"] = debug_data["anchor"]
        response["specials"] = debug_data["specials"]
        response["alignment_detail"] = debug_data["alignment_detail"]
        response["events"] = debug_data["events"]

    return response
