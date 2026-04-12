import os
from pathlib import Path

# Repo root (inspector/ is one level below)
_REPO = Path(__file__).resolve().parent.parent

# Audio files location
AUDIO_PATH = _REPO / "data"

# Cache directory
CACHE_DIR = _REPO / "inspector" / ".cache"

SURAH_INFO_PATH = _REPO / "data" / "surah_info.json"

# Optional sibling-project linguistic data (qpc_hafs, digital_khatt, phoneme_sub_costs).
# Each consumer in services/ gracefully degrades to an empty set/dict if the file is
# missing, so these paths are advisory rather than required. Override the base dir via
# INSPECTOR_QUA_DATA_PATH for standalone / Docker deployments.
_QUA_DATA_OVERRIDE = os.getenv("INSPECTOR_QUA_DATA_PATH")
_QUA_DATA = Path(_QUA_DATA_OVERRIDE) if _QUA_DATA_OVERRIDE else _REPO / "quranic_universal_aligner" / "data"
QPC_HAFS_PATH = _QUA_DATA / "qpc_hafs.json"
DK_SCRIPT_PATH = _QUA_DATA / "digital_khatt_v2_script.json"
PHONEME_SUB_COSTS_PATH = _QUA_DATA / "phoneme_sub_costs.json"

# Recitation segments from extract_segments.py
RECITATION_SEGMENTS_PATH = _REPO / "data" / "recitation_segments"

# Audio metadata (JSON files with surah URLs per reciter)
AUDIO_METADATA_PATH = _REPO / "data" / "audio"

# Timestamps from MFA forced alignment (JSONL per reciter)
TIMESTAMPS_PATH = _REPO / "data" / "timestamps"

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
ANIM_HIGHLIGHT_COLOR = "#f0a500"          # gold — active word/char color (both views)
ANIM_WORD_TRANSITION_DURATION = 0.15      # seconds — word opacity transition
ANIM_CHAR_TRANSITION_DURATION = 0.02      # seconds — char opacity transition
ANIM_WORD_SPACING = "0.2em"               # gap between words in animation view
ANIM_LINE_HEIGHT = 2.0                    # line-height for animation text
ANIM_FONT_SIZE = "44px"                   # Arabic text size in animation view

# Analysis view settings
ANALYSIS_WORD_FONT_SIZE = "1.5rem"         # word row text size in analysis view
ANALYSIS_LETTER_FONT_SIZE = "1.75rem"      # letter sub-row text size in analysis view

# Segments tab settings
SEG_FONT_SIZE = "1.8rem"                  # Arabic text size in segment cards
LOW_CONF_DEFAULT_THRESHOLD = 80           # default % for low-confidence slider (50–99)
SEG_WORD_SPACING = "0.2em"                # gap between words in segment cards

# Adjust (trim) mode settings
TRIM_PAD_LEFT = 10000                     # ms padding before segment
TRIM_PAD_RIGHT = 10000                    # ms padding after segment
TRIM_DIM_ALPHA = 0.4                      # dimming opacity for padded regions

# Boundary adjustment: phoneme tail mismatch detection
BOUNDARY_TAIL_K = 3                       # number of trailing phonemes to compare
SHOW_BOUNDARY_PHONEMES = False             # show GT/ASR tail phonemes on boundary_adj cards

# Accordion context: which validation categories auto-expand context cards
# Values: "shown" (default open), "hidden" (default closed), "next_only" (open on nav)
ACCORDION_CONTEXT = {
    "failed": "shown",
    "low_confidence": "shown",
    "boundary_adj": "hidden",
    "repetitions": "hidden",
    "cross_verse": "shown",
    "muqattaat": "hidden",
    "qalqala": "hidden",
    "audio_bleeding": "shown",
}

# HTTP / subprocess timeouts (seconds)
FFPROBE_TIMEOUT = 5
FFMPEG_TIMEOUT = 10
FFMPEG_FULL_TIMEOUT = 300
ID3_PROBE_TIMEOUT = 5

# Audio processing
DEFAULT_BYTES_PER_SEC = 16_000
RANGE_DECODE_PAD_SEC = 5
ID3_PROBE_BYTES = 50_000
MIN_SEG_PEAK_BUCKETS = 10
MIN_FULL_PEAK_BUCKETS = 100
PEAKS_BUCKETS_PER_SEC = 50                # target peak density for segment-level peaks
PEAKS_NEIGHBOR_COUNT = 0                  # neighbors to pre-fetch (0 = disabled, observer-only)

# Validation thresholds
LOW_CONFIDENCE_THRESHOLD = 0.80
MAX_AYAH_BOUNDARY_CHECK = 300
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

# Audio MIME types (shared between app.py and audio_proxy)
AUDIO_MIME_TYPES = {
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
}
