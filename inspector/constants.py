"""Domain constants for the inspector: validation categories, Quranic reference sets."""

# Canonical validation categories -- single source of truth.
# Every counting, summary, and delta function derives from this tuple.
VALIDATION_CATEGORIES = (
    "failed", "low_confidence", "boundary_adj", "cross_verse",
    "missing_words", "audio_bleeding", "repetitions",
    "muqattaat", "qalqala",
)

# Quranic stop/pause signs (sili, qili, small meem, jeem)
STOP_SIGNS = set('\u06D6\u06D7\u06D8\u06DA')

# Huruf muqattaat opening verses (surah, ayah) tuples
MUQATTAAT_VERSES = {
    (2, 1), (3, 1), (7, 1), (10, 1), (11, 1), (12, 1), (13, 1), (14, 1), (15, 1),
    (19, 1), (20, 1), (26, 1), (27, 1), (28, 1), (29, 1), (30, 1), (31, 1), (32, 1),
    (36, 1), (38, 1), (40, 1), (41, 1), (42, 1), (42, 2), (43, 1), (44, 1), (45, 1),
    (46, 1), (50, 1), (68, 1),
}

# Qalqala letters
QALQALA_LETTERS = {'\u0642', '\u0637', '\u0628', '\u062C', '\u062F'}

# Known standalone single-word segment references (surah, ayah, word) tuples
STANDALONE_REFS = {
    (9, 13, 13), (16, 16, 1), (43, 35, 1), (70, 11, 1), (79, 27, 6),
    (37, 9, 1), (37, 24, 1), (44, 37, 9), (46, 35, 22), (44, 28, 1),
}

# Known standalone single-word segment texts (bare-skeleton form)
STANDALONE_WORDS = {"\u0643\u0644\u0627", "\u0630\u0644\u0643", "\u0643\u0630\u0644\u0643", "\u0633\u0628\u062D\u0646\u0647\u06E5"}

# Phonemes that indicate a long vowel at word boundary
BOUNDARY_VOWELS = {'a:', 'a\u02E4:', 'u:', 'i:'}
