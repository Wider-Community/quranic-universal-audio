import os
from pathlib import Path

# Repo root (inspector/ is one level below)
_REPO = Path(__file__).resolve().parent.parent

# Data root — holds only bundled reference data (surah_info, qpc_hafs,
# digital_khatt, phoneme_sub_costs, .audio_meta) in deployed mode. All
# per-reciter content lives in the bucket at INSPECTOR_BUCKET_MOUNT.
DATA_DIR = Path(os.environ.get("INSPECTOR_DATA_DIR", str(_REPO / "data"))).resolve()

SURAH_INFO_PATH = DATA_DIR / "surah_info.json"

# Legacy filesystem constant — only consulted by ``services/history_query.py``
# tests that monkeypatch a tmp_path in. Production reads edit_history through
# ``data_dir`` (bucket-resolved).
RECITATION_SEGMENTS_PATH = DATA_DIR / "recitation_segments"

# Bundled linguistic data (qpc_hafs, digital_khatt, phoneme_sub_costs) lives in
# the repo's ``data/`` dir alongside ``surah_info.json``. Override the base dir
# via INSPECTOR_QUA_DATA_PATH for standalone / Docker deployments.
_QUA_DATA_OVERRIDE = os.getenv("INSPECTOR_QUA_DATA_PATH")
_QUA_DATA = Path(_QUA_DATA_OVERRIDE) if _QUA_DATA_OVERRIDE else DATA_DIR
QPC_HAFS_PATH = _QUA_DATA / "qpc_hafs.json"
DK_SCRIPT_PATH = _QUA_DATA / "digital_khatt_v2_script.json"
PHONEME_SUB_COSTS_PATH = _QUA_DATA / "phoneme_sub_costs.json"

# Display settings
UNIFIED_DISPLAY_MAX_HEIGHT = 800  # px

# Animation settings
# Easing function for opacity transitions:
#   ease         — slow start/end, fast middle (default)
#   linear       — constant speed
#   ease-in      — slow start, fast end
#   ease-out     — fast start, slow end
#   ease-in-out  — slow both ends
#   none         — instant snap, no animation
ANIM_TRANSITION_EASING = "ease"
ANIM_HIGHLIGHT_COLOR = "#f0a500"       # gold — active word/char color (both views)
ANIM_WORD_TRANSITION_DURATION = 0.15   # seconds — word opacity transition
ANIM_CHAR_TRANSITION_DURATION = 0.02   # seconds — char opacity transition
ANIM_WORD_SPACING = "0.2em"            # gap between words in animation view
ANIM_LINE_HEIGHT = 2.0                 # line-height for animation text
ANIM_FONT_SIZE = "44px"                # Arabic text size in animation view

# Analysis view settings
ANALYSIS_WORD_FONT_SIZE = "1.5rem"     # word row text size in analysis view
ANALYSIS_LETTER_FONT_SIZE = "1.75rem"  # letter sub-row text size in analysis view

# Segments tab settings
SEG_FONT_SIZE = "1.8rem"           # Arabic text size in segment cards
LOW_CONF_DEFAULT_THRESHOLD = 80    # default % for low-confidence slider (50–99)
SEG_WORD_SPACING = "0.2em"         # gap between words in segment cards

# Auto-scroll animation mode for the segments list.
# Values: "none"   — instant (no animation)
#         "smooth" — native CSS smooth scroll on every target
#         "hybrid" — smooth only when the jump exceeds one viewport, instant otherwise
# Not a user preference — the same behavior ships for all deployments.
SEG_SCROLL_ANIM_MODE = "hybrid"

# Adjust (trim) mode settings
TRIM_PAD_LEFT = 15000                     # ms padding before segment
TRIM_PAD_RIGHT = 15000                    # ms padding after segment
TRIM_DIM_ALPHA = 0.4                      # dimming opacity for padded regions

# Accordion context: which validation categories auto-expand context cards
# Values: "shown" (default open), "hidden" (default closed), "next_only" (open on nav)
ACCORDION_CONTEXT = {
    "failed": "shown",
    "missing_words": "shown",
    "low_confidence": "hidden",
    "boundary_adj": "hidden",
    "repetitions": "hidden",
    "cross_verse": "hidden",
    "muqattaat": "hidden",
    "qalqala": "hidden",
    "audio_bleeding": "shown",
}

# HTTP / subprocess timeouts (seconds)
FFMPEG_TIMEOUT = 15
FFMPEG_FULL_TIMEOUT = 300

# Audio processing
MIN_SEG_PEAK_BUCKETS = 10
MIN_FULL_PEAK_BUCKETS = 100
PEAKS_BUCKETS_PER_SEC = 30                # target peak density for segment-level peaks

# Validation thresholds
LOW_CONFIDENCE_THRESHOLD = 0.80
# Minimum number of pipeline-stripped basmalas required before we flag the
# remaining (non-stripped) chapters as "missed Basmala" candidates. Below this
# count the reciter is treated as one who doesn't recite inter-chapter
# basmalas, and the augmentation is suppressed to avoid accordion noise.
MISSED_BASMALA_FLAG_MIN_DELETED = int(os.getenv("MISSED_BASMALA_FLAG_MIN_DELETED", "10"))
# "Show everything below perfect" tier — used to populate detail lists (not count badges).
# Distinct from LOW_CONFIDENCE_THRESHOLD (count badge cutoff) and LOW_CONFIDENCE_RED (red highlight).
LOW_CONFIDENCE_DETAIL_THRESHOLD = 1.0
METADATA_PEEK_BYTES = 512

# Statistics histogram defaults
PAUSE_HIST_BIN_MS = 50
PAUSE_HIST_MAX_MS = 3000
SEG_DUR_HIST_BIN_MS = 500
SEG_DUR_HIST_MAX_MS = 15000

# Cache headers
AUDIO_CACHE_MAX_AGE = 31_536_000

# Confidence thresholds
LOW_CONFIDENCE_RED = 0.60           # below this = red highlight ("below_60" stat)

# Peaks (ffmpeg) — waveform peak extraction defaults (services/peaks.py)
PEAKS_FFMPEG_SAMPLE_RATE = 8000          # Hz — ffmpeg resample target for peak computation
PEAKS_PCM_NORMALIZER = 32768.0           # divisor that maps int16 PCM → [-1, 1] float
PEAKS_WORKER_COUNT = 8                   # ThreadPoolExecutor workers for parallel peak compute
# v1 used integer block size (`num_samples // num_buckets`) and dropped the
# trailing samples that didn't fit, leaving the peaks array advertising
# `duration_ms` larger than what it actually covered — a 0.25% multiplicative
# time→peak drift visible as misregistered silences on long chapters
# (~2 s offset 15 min in, ~17 s offset at end-of-file for a ~115 min surah).
# v2 uses a float stride so every sample is bucketed; the read path treats
# missing/old version as a cache miss so existing peaks lazily recompute.
#
# v3 introduces the slim packed shape (int8-quantized, decimated, gzipped) at
# ``wip/<slug>/peaks/<chapter>.json.gz``. See ``services/audio/peaks_slim.py``
# for the format. Pre-v3 ``.json`` files are migrated by
# ``scripts/backfill_peaks_slim.py`` and preserved as ``.json.bak`` for
# rollback. Reader (``audio_fetch.read_prefetched_peaks``) inflates v3 blobs
# into a ``peaks: list[list[float]]`` dict so the existing slicers
# (``_slice_chapter_peaks``) work unchanged.
PEAKS_SCHEMA_VERSION = 3

# Audio-cache background download (routes/audio_proxy.py)
AUDIO_DL_WORKER_COUNT = 8                # concurrent audio-file download workers for by_surah cache warmup

# Server defaults (app.py)
DEFAULT_PORT = 5000                      # Flask --port default
FLASK_ENV_VAR = "FLASK_ENV"              # environment variable name for Flask env
FLASK_DEV_VALUE = "development"          # value that triggers debug/reloader mode
# Bind host — override with INSPECTOR_HOST for non-local deployments.
SERVER_HOST = os.environ.get("INSPECTOR_HOST", "0.0.0.0")

# Timestamps validation (routes/timestamps.py)
TS_RANDOM_MAX_RETRIES = 10             # max attempts to find a non-empty verse in /ts/random
TS_BOUNDARY_TOLERANCE_MS = 500         # default boundary tolerance when not in result metadata
# Sort-order weight for missing-word issues: one missing word adds this many ms to diff_ms.
# This is NOT a unit conversion — it is purely a sort-order heuristic.
MISSING_WORD_DIFF_MS_WEIGHT = 1000

# Statistics histogram shape constants (services/stats.py)
WORDS_PER_SEG_HIST_MAX = 15            # upper bound for words-per-segment histogram
SEGS_PER_VERSE_HIST_MAX = 8            # upper bound for segs-per-verse histogram
CONF_HIST_BIN_SIZE = 5                 # bin width (percentage points) for confidence histogram

# Auto-split (services/auto_split.py): MFA Space + timeout. Cross-verse
# accordion's "Auto Split" routes here to compute the verse-boundary split
# time. Always the dev Space — interactive call volume is low. Override
# via INSPECTOR_MFA_SPACE_URL. On any failure or timeout the FE silently
# falls back to a midpoint cursor.
MFA_SPACE_URL = os.environ.get(
    "INSPECTOR_MFA_SPACE_URL", "https://hetchyy-quran-phoneme-mfa-dev.hf.space"
)
AUTO_SPLIT_MFA_TIMEOUT = 15

# Audio MIME types (shared between app.py and audio_proxy)
AUDIO_MIME_TYPES = {
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
}
