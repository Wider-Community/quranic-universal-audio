from pathlib import Path

# Repo root (inspector/ is one level below)
_REPO = Path(__file__).resolve().parent.parent

# Audio files location
AUDIO_PATH = _REPO / "data"

# Cache directory
CACHE_DIR = _REPO / "inspector" / ".cache"

# MFA alignment resources
MODEL_PATH = _REPO / "mfa_aligner" / "quran_aligner_model.zip"
DICTIONARY_PATH = _REPO / "mfa_aligner" / "dictionary.txt"
SURAH_INFO_PATH = _REPO / "data" / "surah_info.json"

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
SEG_WORD_SPACING = "0.2em"                # gap between words in segment cards

# Adjust (trim) mode settings
TRIM_PAD_LEFT = 10000                     # ms padding before segment
TRIM_PAD_RIGHT = 10000                    # ms padding after segment
TRIM_DIM_ALPHA = 0.3                      # dimming opacity for padded regions

# Boundary adjustment: phoneme tail mismatch detection
BOUNDARY_TAIL_K = 3                       # number of trailing phonemes to compare
SHOW_BOUNDARY_PHONEMES = True             # show GT/ASR tail phonemes on boundary_adj cards
