"""
MFA Aligner — Gradio app for Montreal Forced Aligner on Quranic recitation audio.
Copyright 2026 Wider Community. Licensed under Apache 2.0.
See LICENSE in the repository root.
"""

import json
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import gradio as gr
import numpy as np
import soundfile as sf
import tgt

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("mfa_app")

# ---------------------------------------------------------------------------
# Paths (relative to app directory)
# ---------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
DICTIONARY_PATH = APP_DIR / "dictionary.txt"
MODEL_PATH = APP_DIR / "quran_aligner_model.zip"
SURAH_INFO_PATH = APP_DIR / "surah_info.json"

# Import phonemizer (installed via pip as quranic-phonemizer)
from quranic_phonemizer import Phonemizer
from types import SimpleNamespace

# Import flat mapping for letter-level timestamps
from quranic_phonemizer.letter_phoneme_mapping import build_letter_phoneme_mapping

# ---------------------------------------------------------------------------
# Letter splitting helpers
# ---------------------------------------------------------------------------

# Characters that start a new letter entry (splittable)
# Based on phonemizer/core/resources/base_phonemes.yaml letters + extensions
# Diacritics and other marks stay attached to the preceding letter
SPLITTABLE_CHARS = {
    # Letters from base_phonemes.yaml
    "ء",  # HAMZA (U+0621)
    "أ",  # HAMZA_ABOVE_ALEF (U+0623)
    "ؤ",  # HAMZA_WAW (U+0624)
    "إ",  # HAMZA_BELOW_ALEF (U+0625)
    "ئ",  # HAMZA_YA (U+0626)
    "ا",  # ALEF (U+0627)
    "ب",  # BA (U+0628)
    "ة",  # TAA_MARBUTA (U+0629)
    "ت",  # TA (U+062A)
    "ث",  # THA (U+062B)
    "ج",  # JEEM (U+062C)
    "ح",  # HHA (U+062D)
    "خ",  # KHA (U+062E)
    "د",  # DAL (U+062F)
    "ذ",  # THAL (U+0630)
    "ر",  # RA (U+0631)
    "ز",  # ZAIN (U+0632)
    "س",  # SEEN (U+0633)
    "ش",  # SHEEN (U+0634)
    "ص",  # SAD (U+0635)
    "ض",  # DAD (U+0636)
    "ط",  # TTA (U+0637)
    "ظ",  # DTHA (U+0638)
    "ع",  # AIN (U+0639)
    "غ",  # GHAIN (U+063A)
    "ف",  # FA (U+0641)
    "ق",  # QAF (U+0642)
    "ك",  # KAF (U+0643)
    "ل",  # LAM (U+0644)
    "م",  # MEEM (U+0645)
    "ن",  # NOON (U+0646)
    "ه",  # HA (U+0647)
    "و",  # WAW (U+0648)
    "ى",  # ALEF_MAKSURA (U+0649)
    "ي",  # YA (U+064A)
    "ٱ",  # HAMZA_WASL (U+0671)
    # Extensions (get separate entries for madd timestamps)
    "ٰ",  # DAGGER_ALEF (U+0670)
    "ۥ",  # MINI_WAW (U+06E5)
    "ۦ",  # MINI_YA_END (U+06E6)
    "ۧ",  # MINI_YA_MIDDLE (U+06E7)
}

# Tatweel should be filtered from letter timestamp output
TATWEEL = "ـ"  # U+0640


def split_into_letters(text: str) -> list[str]:
    """Split text into letters, keeping diacritics attached to their base letter.

    Only splits on SPLITTABLE_CHARS. Diacritics stay with preceding letter.
    Tatweel entries are filtered from the output.
    """
    if not text:
        return []

    letters = []
    current = ""

    for ch in text:
        if ch in SPLITTABLE_CHARS:
            if current:
                letters.append(current)
            current = ch
        else:
            current += ch

    if current:
        letters.append(current)

    # Filter out tatweel-only entries (tatweel possibly with diacritics)
    return [letter for letter in letters if letter[0] != TATWEEL]


# ---------------------------------------------------------------------------
# Special (non-verse) phoneme sequences
# ---------------------------------------------------------------------------

SPECIAL_PHONEMES = {
    "Isti'adha": [
        "ʔ", "a", "ʕ", "u:", "ð", "u", "b", "i", "ll", "a:", "h", "i",
        "m", "i", "n", "a", "ʃʃ", "a", "j", "tˤ", "aˤ:", "n", "i",
        "rˤrˤ", "aˤ", "ʒ", "i:", "m",
    ],
    "Basmala": [
        "b", "i", "s", "m", "i", "ll", "a:", "h", "i", "rˤrˤ", "aˤ",
        "ħ", "m", "a:", "n", "i", "rˤrˤ", "aˤ", "ħ", "i:", "m",
    ],
}

SPECIAL_WORDS = {
    "Isti'adha": [
        SimpleNamespace(location="0:0:1", text="أَعُوذُ",
                        phonemes=["ʔ", "a", "ʕ", "u:", "ð", "u"]),
        SimpleNamespace(location="0:0:2", text="بِٱللَّهِ",
                        phonemes=["b", "i", "ll", "a:", "h", "i"]),
        SimpleNamespace(location="0:0:3", text="مِنَ",
                        phonemes=["m", "i", "n", "a"]),
        SimpleNamespace(location="0:0:4", text="ٱلشَّيْطَـٰنِ",
                        phonemes=["ʃʃ", "a", "j", "tˤ", "aˤ:", "n", "i"]),
        SimpleNamespace(location="0:0:5", text="ٱلرَّجِيمِ",
                        phonemes=["rˤrˤ", "aˤ", "ʒ", "i:", "m"]),
    ],
    "Basmala": [
        SimpleNamespace(location="0:0:1", text="بِسْمِ",
                        phonemes=["b", "i", "s", "m", "i"]),
        SimpleNamespace(location="0:0:2", text="ٱللَّهِ",
                        phonemes=["ll", "a:", "h", "i"]),
        SimpleNamespace(location="0:0:3", text="ٱلرَّحْمَـٰنِ",
                        phonemes=["rˤrˤ", "aˤ", "ħ", "m", "a:", "n", "i"]),
        SimpleNamespace(location="0:0:4", text="ٱلرَّحِيمِ",
                        phonemes=["rˤrˤ", "aˤ", "ħ", "i:", "m"]),
    ],
}

# Case-insensitive lookup
_SPECIAL_KEYS = {k.lower(): k for k in SPECIAL_PHONEMES}

# Flat mappings for special (non-verse) segments
# Each entry is (chars, phonemes) following the rules in many-to-many-mapping-research.md
# - No empty phonemes
# - Silent letters merge into adjacent entries
# - Word boundary = space suffix on chars
SPECIAL_FLAT_MAPPINGS = {
    # Basmala: بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ
    # Derived from 1:1 (Al-Fatiha verse 1)
    "Basmala": [
        # Word 1: بِسْمِ → ["b", "i", "s", "m", "i"]
        ("ب", ["b", "i"]),
        ("س", ["s"]),
        ("م ", ["m", "i"]),
        # Word 2: ٱللَّهِ → ["ll", "a:", "h", "i"]
        # hamza wasl (silent) + first lam (idgham) → merge RIGHT into second lam
        ("ٱلل", ["ll", "a:"]),
        ("ه ", ["h", "i"]),
        # Word 3: ٱلرَّحْمَـٰنِ → ["rˤrˤ", "aˤ", "ħ", "m", "a:", "n", "i"]
        # hamza wasl (silent) + lam shamsiyah → merge RIGHT into raa
        ("ٱلر", ["rˤrˤ", "aˤ"]),
        ("ح", ["ħ"]),
        ("م", ["m"]),
        ("ـٰ", ["a:"]),  # tatweel + dagger alef carries the madd
        ("ن ", ["n", "i"]),
        # Word 4: ٱلرَّحِيمِ → ["rˤrˤ", "aˤ", "ħ", "i:", "m"]
        ("ٱلر", ["rˤrˤ", "aˤ"]),
        ("ح", ["ħ"]),
        ("ي", ["i:"]),
        ("م", ["m"]),
    ],
    # Isti'adha: أَعُوذُ بِٱللَّهِ مِنَ ٱلشَّيْطَـٰنِ ٱلرَّجِيمِ
    # Hardcoded based on many-to-many-mapping rules
    "Isti'adha": [
        # Word 1: أَعُوذُ → ["ʔ", "a", "ʕ", "u:", "ð", "u"]
        ("أ", ["ʔ", "a"]),
        ("ع", ["ʕ"]),      # damma popped for waw lengthening
        ("و", ["u:"]),     # waw carries the long vowel
        ("ذ ", ["ð", "u"]),
        # Word 2: بِٱللَّهِ → ["b", "i", "ll", "a:", "h", "i"]
        ("ب", ["b", "i"]),
        ("ٱلل", ["ll", "a:"]),  # hamza wasl (silent) + first lam (idgham) + second lam
        ("ه ", ["h", "i"]),
        # Word 3: مِنَ → ["m", "i", "n", "a"]
        # The fatha on nun produces "a" in this word
        ("م", ["m", "i"]),
        ("ن ", ["n", "a"]),
        # Word 4: ٱلشَّيْطَـٰنِ → ["ʃʃ", "a", "j", "tˤ", "aˤ:", "n", "i"]
        # hamza wasl (silent) + lam shamsiyah → merge RIGHT into sheen
        ("ٱلش", ["ʃʃ", "a"]),
        ("ي", ["j"]),
        ("ط", ["tˤ"]),        # fatha popped for alef lengthening
        ("ـٰ", ["aˤ:"]),      # tatweel + dagger alef carries the madd
        ("ن ", ["n", "i"]),
        # Word 5: ٱلرَّجِيمِ → ["rˤrˤ", "aˤ", "ʒ", "i:", "m"]
        ("ٱلر", ["rˤrˤ", "aˤ"]),  # hamza wasl (silent) + lam shamsiyah
        ("ج", ["ʒ"]),         # kasra popped for yaa lengthening
        ("ي", ["i:"]),        # yaa carries the long vowel
        ("م", ["m"]),
    ],
}

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
_phonemizer = None


def get_phonemizer():
    global _phonemizer
    if _phonemizer is None:
        logger.info("Initializing Phonemizer...")
        t0 = time.time()
        _phonemizer = Phonemizer()
        logger.info("Phonemizer ready (%.2fs)", time.time() - t0)
    return _phonemizer


# Load surah info for dropdowns
with open(SURAH_INFO_PATH, encoding="utf-8") as f:
    SURAH_INFO = json.load(f)
logger.info("Loaded surah_info.json (%d surahs)", len(SURAH_INFO))


# ---------------------------------------------------------------------------
# KalpyEngine — persistent aligner using kalpy API directly
# ---------------------------------------------------------------------------

def strip_position_tag(phone: str) -> str:
    """Remove Kaldi position tags (_B, _E, _I, _S) from phone labels."""
    if phone and len(phone) > 2 and phone[-2] == "_" and phone[-1] in "BEIS":
        return phone[:-2]
    return phone


class KalpyEngine:
    """Persistent MFA alignment engine using kalpy directly.
    Eliminates the ~9s PretrainedAligner.setup() overhead."""

    def __init__(self, acoustic_model_path, dictionary_path):
        from kalpy.aligner import KalpyAligner
        from kalpy.feat.cmvn import CmvnComputer
        from kalpy.fstext.lexicon import LexiconCompiler
        from montreal_forced_aligner.dictionary.mixins import (
            DEFAULT_BRACKETS,
            DEFAULT_CLITIC_MARKERS,
            DEFAULT_COMPOUND_MARKERS,
            DEFAULT_PUNCTUATION,
            DEFAULT_WORD_BREAK_MARKERS,
        )
        from montreal_forced_aligner.models import AcousticModel
        from montreal_forced_aligner.tokenization.simple import SimpleTokenizer

        # 1. Load acoustic model (has .mfcc_computer, .parameters)
        self.acoustic_model = AcousticModel(str(acoustic_model_path))
        p = self.acoustic_model.parameters

        # 2. Build lexicon compiler with model params
        self.lexicon_compiler = LexiconCompiler(
            disambiguation=False,
            silence_probability=p["silence_probability"],
            initial_silence_probability=p["initial_silence_probability"],
            final_silence_correction=p["final_silence_correction"],
            final_non_silence_correction=p["final_non_silence_correction"],
            silence_phone=p["optional_silence_phone"],
            oov_phone=p["oov_phone"],
            position_dependent_phones=p["position_dependent_phones"],
            phones=p["non_silence_phones"],
            ignore_case=True,
        )
        self.lexicon_compiler.load_pronunciations(str(dictionary_path))

        # 3. Build tokenizer (matches align_one.py defaults)
        self.tokenizer = SimpleTokenizer(
            word_table=self.lexicon_compiler.word_table,
            word_break_markers=DEFAULT_WORD_BREAK_MARKERS,
            punctuation=DEFAULT_PUNCTUATION,
            clitic_markers=DEFAULT_CLITIC_MARKERS,
            compound_markers=DEFAULT_COMPOUND_MARKERS,
            brackets=DEFAULT_BRACKETS,
            ignore_case=True,
        )

        # 4. Create reusable aligner (cached by beam params)
        self._default_beam = 10
        self._default_retry_beam = 40
        self._aligner_cache = {}
        self.kalpy_aligner = self._get_aligner(self._default_beam, self._default_retry_beam)

        # 5. CMVN computer (stateless)
        self.cmvn_computer = CmvnComputer()

    def _get_aligner(self, beam: int, retry_beam: int):
        """Get or create a KalpyAligner for given beam parameters."""
        from kalpy.aligner import KalpyAligner
        key = (beam, retry_beam)
        if key not in self._aligner_cache:
            self._aligner_cache[key] = KalpyAligner(
                self.acoustic_model, self.lexicon_compiler,
                beam=beam, retry_beam=retry_beam,
            )
        return self._aligner_cache[key]

    def align(self, wav_path, lab_content, beam=None, retry_beam=None):
        """Align a single WAV file with its phoneme string.
        Returns list[dict] of phone intervals [{start, end, phone}]."""
        from kalpy.utterance import Segment, Utterance as KalpyUtterance
        from montreal_forced_aligner.corpus.classes import FileData
        from montreal_forced_aligner.online.alignment import tokenize_utterance_text

        _beam = beam if beam is not None else self._default_beam
        _retry_beam = retry_beam if retry_beam is not None else self._default_retry_beam
        aligner = self._get_aligner(_beam, _retry_beam)

        file = FileData.parse_file(
            Path(wav_path).stem, str(wav_path), None, "", 0
        )
        duration = file.wav_info.duration

        seg = Segment(str(wav_path), 0, duration, 0)

        normalized = tokenize_utterance_text(
            lab_content, self.lexicon_compiler, self.tokenizer,
            language=self.acoustic_model.language,
        )
        utt = KalpyUtterance(seg, normalized)
        utt.generate_mfccs(self.acoustic_model.mfcc_computer)

        cmvn = self.cmvn_computer.compute_cmvn_from_features([utt.mfccs])
        utt.apply_cmvn(cmvn)

        ctm = aligner.align_utterance(utt)
        return self._ctm_to_intervals(ctm)

    def _resolve_phone(self, symbol_id):
        """Resolve phone integer ID to string name via phone_table, then strip position tag."""
        phone_table = self.lexicon_compiler.phone_table
        if phone_table is not None and isinstance(symbol_id, int):
            name = phone_table.find(symbol_id)
            if name:
                return strip_position_tag(name)
        return strip_position_tag(str(symbol_id))

    def _ctm_to_intervals(self, ctm):
        """Convert HierarchicalCtm to list of phone interval dicts."""
        intervals = []
        for word_iv in ctm.word_intervals:
            for phone in word_iv.phones:
                intervals.append({
                    "start": round(float(phone.begin), 4),
                    "end": round(float(phone.end), 4),
                    "phone": self._resolve_phone(phone.symbol),
                })
        return intervals

    def align_batch(self, segments, beam=None, retry_beam=None, shared_cmvn=False):
        """Align N (wav_path, lab_content) pairs.

        Args:
            segments: List of (wav_path, lab_content) tuples.
            beam: Viterbi beam width (default: engine default).
            retry_beam: Retry beam width (default: engine default).
            shared_cmvn: If True, compute CMVN across all segments.
                If False (default), compute per-utterance CMVN.
        """
        from kalpy.utterance import Segment, Utterance as KalpyUtterance
        from montreal_forced_aligner.corpus.classes import FileData
        from montreal_forced_aligner.online.alignment import tokenize_utterance_text

        _beam = beam if beam is not None else self._default_beam
        _retry_beam = retry_beam if retry_beam is not None else self._default_retry_beam
        aligner = self._get_aligner(_beam, _retry_beam)

        utterances = []
        for wav_path, lab_content in segments:
            file = FileData.parse_file(
                Path(wav_path).stem, str(wav_path), None, "", 0
            )
            seg = Segment(str(wav_path), 0, file.wav_info.duration, 0)
            normalized = tokenize_utterance_text(
                lab_content, self.lexicon_compiler, self.tokenizer,
                language=self.acoustic_model.language,
            )
            utt = KalpyUtterance(seg, normalized)
            utt.generate_mfccs(self.acoustic_model.mfcc_computer)
            utterances.append(utt)

        if shared_cmvn:
            valid_feats = [u.mfccs for u in utterances if u.mfccs.NumRows() > 0]
            cmvn = self.cmvn_computer.compute_cmvn_from_features(
                valid_feats if valid_feats else [u.mfccs for u in utterances]
            )
            all_results = []
            for utt in utterances:
                if utt.mfccs.NumRows() == 0:
                    all_results.append([])
                    continue
                utt.apply_cmvn(cmvn)
                try:
                    ctm = aligner.align_utterance(utt)
                    all_results.append(self._ctm_to_intervals(ctm))
                except Exception as e:
                    logger.warning("align_batch: utterance alignment failed: %s", e)
                    all_results.append([])
        else:
            all_results = []
            for utt in utterances:
                if utt.mfccs.NumRows() == 0:
                    all_results.append([])
                    continue
                cmvn = self.cmvn_computer.compute_cmvn_from_features([utt.mfccs])
                utt.apply_cmvn(cmvn)
                try:
                    ctm = aligner.align_utterance(utt)
                    all_results.append(self._ctm_to_intervals(ctm))
                except Exception as e:
                    logger.warning("align_batch: utterance alignment failed: %s", e)
                    all_results.append([])

        return all_results


# Initialize KalpyEngine at startup (fallback gracefully if it fails)
_kalpy_engine = None
try:
    logger.info("Initializing KalpyEngine...")
    t0 = time.time()
    _kalpy_engine = KalpyEngine(MODEL_PATH, DICTIONARY_PATH)
    logger.info("KalpyEngine ready (%.2fs)", time.time() - t0)
except Exception as e:
    logger.warning("KalpyEngine init failed (falling back to other methods): %s", e)


# ---------------------------------------------------------------------------
# Phoneme transforms (from inspector/server.py → prepare_labs.py)
# ---------------------------------------------------------------------------

def normalize_phonemes(text: str) -> str:
    return text.replace(":", "\u02d0")


def transform_phonemes(text: str) -> str:
    tokens = text.split()
    result = []
    for tok in tokens:
        if tok == "Q":
            continue
        tok = tok.replace("r\u02e4", "r").replace("a\u02e4", "a").replace("l\u02e4", "l")
        n = len(tok)
        if n >= 2 and n % 2 == 0 and tok[: n // 2] == tok[n // 2 :]:
            result.append(tok[: n // 2])
            result.append(tok[n // 2 :])
        else:
            result.append(tok)
    return " ".join(result)


# ---------------------------------------------------------------------------
# Audio conversion
# ---------------------------------------------------------------------------

def save_as_wav(src_path: str, wav_path: Path):
    try:
        data, sr = sf.read(src_path)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sr != 16000:
            ratio = 16000 / sr
            n_samples = int(len(data) * ratio)
            indices = np.linspace(0, len(data) - 1, n_samples)
            data = np.interp(indices, np.arange(len(data)), data)
            sr = 16000
        sf.write(str(wav_path), data, sr, subtype="PCM_16")
    except Exception:
        subprocess.run(
            ["ffmpeg", "-y", "-i", src_path, "-ar", "16000", "-ac", "1", str(wav_path)],
            capture_output=True,
            timeout=30,
        )
        if not wav_path.exists():
            raise RuntimeError("Failed to convert audio to WAV")


# ---------------------------------------------------------------------------
# TextGrid parsing
# ---------------------------------------------------------------------------

def parse_textgrid(tg_path: Path) -> list[dict]:
    tg = tgt.read_textgrid(str(tg_path))
    phones_tier = None
    for tier_name in ["phones", "phone", "phonemes", "phoneme"]:
        try:
            phones_tier = tg.get_tier_by_name(tier_name)
            break
        except ValueError:
            continue
    if phones_tier is None:
        for tier in tg.tiers:
            if hasattr(tier, "intervals"):
                phones_tier = tier
                break
    if phones_tier is None:
        return []
    intervals = []
    for interval in phones_tier.intervals:
        intervals.append({
            "start": round(float(interval.start_time), 4),
            "end": round(float(interval.end_time), 4),
            "phone": interval.text,
        })
    return intervals


# ---------------------------------------------------------------------------
# Word timestamp recovery
# ---------------------------------------------------------------------------

def build_words_from_mapping(intervals: list[dict], word_maps: list) -> list[dict]:
    tg_phones = []
    for idx, iv in enumerate(intervals):
        phone = iv["phone"]
        if phone and phone not in ("", "sil", "sp", "spn"):
            tg_phones.append((idx, phone))

    words_out = []
    cursor = 0
    for wm in word_maps:
        original_phonemes = list(wm.phonemes)
        raw = " ".join(original_phonemes)
        transformed = transform_phonemes(normalize_phonemes(raw))
        expected = transformed.split()
        if not expected:
            continue
        n = len(expected)
        if cursor + n > len(tg_phones):
            n = len(tg_phones) - cursor
            if n <= 0:
                break
        first_idx = tg_phones[cursor][0]
        last_idx = tg_phones[cursor + n - 1][0]
        phone_indices = [tg_phones[cursor + i][0] for i in range(n)]
        words_out.append({
            "location": wm.location,
            "text": wm.text,
            "start": intervals[first_idx]["start"],
            "end": intervals[last_idx]["end"],
            "phone_indices": phone_indices,
            "phonemes": original_phonemes,
        })
        cursor += n
    return words_out


def build_reverse_mapped_intervals(intervals: list[dict], words: list[dict]) -> list[dict]:
    result = [dict(iv) for iv in intervals]
    for word in words:
        original_phonemes = word["phonemes"]
        phone_indices = word["phone_indices"]
        cursor = 0
        for orig_ph in original_phonemes:
            transformed = transform_phonemes(normalize_phonemes(orig_ph))
            mfa_phones = transformed.split()
            if not mfa_phones:
                continue
            n = len(mfa_phones)
            if cursor + n > len(phone_indices):
                break
            if n == 1:
                idx = phone_indices[cursor]
                result[idx]["phone"] = orig_ph
                cursor += 1
            elif n == 2:
                idx1 = phone_indices[cursor]
                idx2 = phone_indices[cursor + 1]
                result[idx1]["phone"] = orig_ph
                result[idx1]["geminate_start"] = True
                result[idx2]["phone"] = ""
                result[idx2]["geminate_end"] = True
                cursor += 2
    return result


def _pad_intervals(mapped_intervals, strategy="forward"):
    """Pad gaps between consecutive non-silence phones in mapped_intervals IN PLACE.

    strategy: "forward" | "symmetric" | "none"
    - forward: extend each phone's end to next phone's start
    - symmetric: split gap at midpoint
    - none: no padding
    """
    if strategy == "none":
        return mapped_intervals

    # Collect indices of non-silence, non-empty-phone entries
    active_indices = [
        i for i, iv in enumerate(mapped_intervals)
        if iv.get("phone") and iv["phone"] not in ("sil", "sp", "spn")
    ]

    for j in range(len(active_indices) - 1):
        idx_a = active_indices[j]
        idx_b = active_indices[j + 1]
        gap = mapped_intervals[idx_b]["start"] - mapped_intervals[idx_a]["end"]
        if gap <= 0:
            continue
        if strategy == "forward":
            mapped_intervals[idx_a]["end"] = mapped_intervals[idx_b]["start"]
        elif strategy == "symmetric":
            mid = mapped_intervals[idx_a]["end"] + gap / 2
            mapped_intervals[idx_a]["end"] = mid
            mapped_intervals[idx_b]["start"] = mid

    return mapped_intervals


def _nest_phones_in_words(words, mapped_intervals):
    """Add per-word 'phones' list using phone_indices into mapped_intervals.

    Each word gets a 'phones' field containing its non-silence phones from
    the reverse-mapped intervals (with original phoneme names restored).
    """
    for w in words:
        word_phones = []
        for pi in w.get("phone_indices", []):
            if pi < len(mapped_intervals):
                iv = mapped_intervals[pi]
                ph = iv.get("phone", "")
                if ph and ph not in ("sil", "sp", "spn"):
                    word_phones.append({
                        "phone": ph,
                        "start": round(iv["start"], 4),
                        "end": round(iv["end"], 4),
                    })
        w["phones"] = word_phones
    return words


# ---------------------------------------------------------------------------
# Letter-level timestamp mapping (from flat many-to-many mappings)
# ---------------------------------------------------------------------------

def build_letter_timestamps(
    intervals: list[dict],
    flat_entries: list[tuple[str, list[str]]],
    phoneme_sequence: list[str],
) -> list[dict]:
    """Build letter-level timestamps from flat mapping entries.

    For each flat entry [chars, phonemes]:
    1. Find the MFA intervals corresponding to those phonemes
    2. Aggregate: start = first interval start, end = last interval end
    3. Each letter in chars gets the same timestamps

    Then extend timestamps to fill gaps (each group's end = next group's start).

    Args:
        intervals: Mapped phone intervals (geminates merged, padded) [{start, end, phone, geminate_start?, geminate_end?}, ...]
        flat_entries: From get_flat_mapping().entries [(chars, phonemes), ...]
        phoneme_sequence: Original phoneme sequence (pre-transform)

    Returns:
        List of letter groups: [{chars, start, end, is_word_end}, ...]
        where chars may contain multiple letters that share the same timestamps.
    """
    # Step 1+2: Build mapping from original phoneme index to interval index.
    # mapped_intervals already has original phoneme names restored and geminates
    # merged, so it's 1-to-1 with phoneme_sequence. Just filter to active phones
    # (skip silence and geminate_end empties) and walk them together.
    active_phones = []  # (interval_index, phone_name)
    for idx, iv in enumerate(intervals):
        phone = iv.get("phone", "")
        if phone and phone not in ("sil", "sp", "spn"):
            active_phones.append(idx)

    orig_to_mfa: list[list[int]] = []
    cursor = 0
    for orig_ph in phoneme_sequence:
        if orig_ph == "Q":
            # Q has no interval in mapped_intervals — skip without consuming
            orig_to_mfa.append([])
        elif cursor < len(active_phones):
            orig_to_mfa.append([active_phones[cursor]])
            cursor += 1
        else:
            orig_to_mfa.append([])

    # Step 3: For each flat entry, compute timestamps
    letter_groups = []  # [(chars, start, end, is_word_end), ...]
    orig_cursor = 0
    for chars, phonemes in flat_entries:
        # Determine if this entry ends a word (space suffix or space inside)
        is_word_end = chars.endswith(" ") or (" " in chars and not chars.endswith(" "))
        chars_clean = chars.rstrip(" ")  # Remove trailing space for output

        if not phonemes:
            # Empty phonemes (shouldn't happen in valid flat mapping)
            letter_groups.append({
                "chars": chars_clean,
                "start": None,
                "end": None,
                "is_word_end": is_word_end,
            })
            continue

        # Gather MFA interval indices for this entry's phonemes
        mfa_indices = []
        for _ in phonemes:
            if orig_cursor < len(orig_to_mfa):
                mfa_indices.extend(orig_to_mfa[orig_cursor])
            orig_cursor += 1

        if mfa_indices:
            start = intervals[min(mfa_indices)]["start"]
            end = intervals[max(mfa_indices)]["end"]
        else:
            # No MFA intervals (all phonemes skipped like Q)
            start, end = None, None

        letter_groups.append({
            "chars": chars_clean,
            "start": start,
            "end": end,
            "is_word_end": is_word_end,
        })

    # Step 4: Inherit timestamps for groups with no MFA intervals (e.g. Q phoneme)
    # Gap-padding between real intervals is already handled by _pad_intervals
    for i in range(len(letter_groups) - 1):
        curr = letter_groups[i]
        next_g = letter_groups[i + 1]
        if curr["end"] is None and next_g["start"] is not None:
            curr["start"] = next_g["start"]
            curr["end"] = next_g["start"]

    return letter_groups


def group_letters_by_word(
    letter_groups: list[dict],
    words: list[dict],
) -> list[dict]:
    """Group letter timestamps by word, matching word locations.

    Args:
        letter_groups: [{chars, start, end, is_word_end}, ...]
        words: [{location, text, start, end}, ...] from build_words_from_mapping

    Returns:
        Words with added 'letters' field: [{location, text, start, end, letters}, ...]
    """
    result = []
    group_idx = 0
    pending_chars = None  # Track leftover from cross-word merge
    pending_timestamps = (None, None)  # (start, end) for pending chars

    for word in words:
        word_letters = []

        # First, add any pending chars from previous cross-word merge
        if pending_chars:
            for letter in split_into_letters(pending_chars):
                start, end = pending_timestamps
                if start is not None and end is not None:
                    word_letters.append({
                        "char": letter,
                        "start": round(start, 2),
                        "end": round(end, 2),
                    })
                else:
                    word_letters.append({"char": letter, "start": None, "end": None})
            pending_chars = None
            pending_timestamps = (None, None)

        # Collect letter groups until we hit a word boundary
        while group_idx < len(letter_groups):
            group = letter_groups[group_idx]
            chars = group["chars"]
            start = group["start"]
            end = group["end"]
            is_word_end = group["is_word_end"]

            # Handle cross-word merges: chars like "ن ر" span two words
            if " " in chars:
                parts = chars.split(" ", 1)
                first_part = parts[0]
                # Add letters from first part to current word
                for letter in split_into_letters(first_part):
                    if start is not None and end is not None:
                        word_letters.append({
                            "char": letter,
                            "start": round(start, 2),
                            "end": round(end, 2),
                        })
                    else:
                        word_letters.append({"char": letter, "start": None, "end": None})

                # Save second part for next word
                if len(parts) > 1 and parts[1]:
                    pending_chars = parts[1]
                    pending_timestamps = (start, end)

                group_idx += 1
                break
            else:
                # Normal entry: add all letters to current word
                for letter in split_into_letters(chars):
                    if start is not None and end is not None:
                        word_letters.append({
                            "char": letter,
                            "start": round(start, 2),
                            "end": round(end, 2),
                        })
                    else:
                        word_letters.append({"char": letter, "start": None, "end": None})

                group_idx += 1

                if is_word_end:
                    break

        result.append({
            "location": word["location"],
            "text": word["text"],
            "start": round(word["start"], 2),
            "end": round(word["end"], 2),
            "phone_indices": word.get("phone_indices", []),
            "letters": word_letters,
        })

    return result


# ---------------------------------------------------------------------------
# Core MFA runner (shared by UI and API)
# ---------------------------------------------------------------------------

def _prepare_files(audio_path: str, lab_content: str, work_dir: Path):
    """Convert audio + write lab into work_dir. Returns (wav_path, lab_path)."""
    corpus_dir = work_dir / "corpus" / "speaker"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    wav_path = corpus_dir / "custom.wav"
    t0 = time.time()
    save_as_wav(audio_path, wav_path)
    logger.info("Audio converted to WAV (%.2fs)", time.time() - t0)

    lab_path = corpus_dir / "custom.lab"
    lab_path.write_text(lab_content, encoding="utf-8")
    logger.info("Lab content (%d chars): %s", len(lab_content), lab_content[:200])
    return wav_path, lab_path


def _find_textgrid(output_dir: Path) -> Path:
    """Search for TextGrid file in output directory."""
    for candidate in [
        output_dir / "speaker" / "custom.TextGrid",
        output_dir / "custom.TextGrid",
    ]:
        if candidate.exists():
            return candidate
    tg_files = list(output_dir.rglob("*.TextGrid"))
    if tg_files:
        logger.info("Found TextGrid at: %s", tg_files[0])
        return tg_files[0]
    raise FileNotFoundError(f"TextGrid not found in {output_dir}")


# ---------------------------------------------------------------------------
# Method 1: mfa align_one (single-file, no DB overhead)
# ---------------------------------------------------------------------------

def run_mfa_align_one(audio_path: str, lab_content: str,
                      beam: int = 10, retry_beam: int = 40) -> list[dict]:
    """Use 'mfa align_one' — skips database/corpus setup entirely."""
    work_dir = Path(tempfile.mkdtemp(prefix="mfa_one_"))
    wav_path, lab_path = _prepare_files(audio_path, lab_content, work_dir)
    output_tg = work_dir / "custom.TextGrid"

    cmd = [
        "mfa", "align_one",
        str(wav_path),
        str(lab_path),
        str(DICTIONARY_PATH),
        str(MODEL_PATH),
        str(output_tg),
        "--beam", str(beam),
        "--retry_beam", str(retry_beam),
    ]
    logger.info("Running mfa align_one: %s", " ".join(cmd))
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    logger.info("mfa align_one finished in %.2fs (code %d)", time.time() - t0, proc.returncode)
    if proc.stderr:
        for line in proc.stderr.splitlines():
            line = line.strip()
            if line:
                logger.info("MFA| %s", line)
    if proc.returncode != 0:
        stderr = proc.stderr[-500:] if proc.stderr else ""
        raise RuntimeError(f"mfa align_one failed (code {proc.returncode}): {stderr}")

    intervals = parse_textgrid(output_tg)
    logger.info("Parsed TextGrid: %d intervals", len(intervals))
    return intervals


# ---------------------------------------------------------------------------
# Method 2: Python API with cached aligner
# ---------------------------------------------------------------------------
_cached_aligner = None
_cached_work_dir = None
_cached_beam_params = None


def run_mfa_python_cached(audio_path: str, lab_content: str,
                          beam: int = 10, retry_beam: int = 40) -> list[dict]:
    """Use PretrainedAligner Python API. Caches aligner across requests."""
    global _cached_aligner, _cached_work_dir, _cached_beam_params
    from montreal_forced_aligner.alignment.pretrained import PretrainedAligner

    beam_params = (beam, retry_beam)

    # Use persistent directory so DB/model can be reused
    if _cached_work_dir is None:
        _cached_work_dir = Path(tempfile.mkdtemp(prefix="mfa_cached_"))
    work_dir = _cached_work_dir
    output_dir = work_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    wav_path, lab_path = _prepare_files(audio_path, lab_content, work_dir)

    if _cached_aligner is None or _cached_beam_params != beam_params:
        logger.info("Aligner init + setup (beam=%d, retry_beam=%d)...", beam, retry_beam)
        t0 = time.time()
        _cached_aligner = PretrainedAligner(
            acoustic_model_path=str(MODEL_PATH),
            corpus_directory=str(work_dir / "corpus"),
            dictionary_path=str(DICTIONARY_PATH),
            output_directory=str(output_dir),
            clean=True,
            single_speaker=True,
            beam=beam,
            retry_beam=retry_beam,
        )
        _cached_beam_params = beam_params
        logger.info("PretrainedAligner init (%.2fs)", time.time() - t0)

        t0 = time.time()
        _cached_aligner.setup()
        logger.info("Aligner setup (%.2fs)", time.time() - t0)
    else:
        logger.info("Reusing cached aligner — reloading corpus...")
        t0 = time.time()
        # Re-initialize corpus with new files but keep model loaded
        _cached_aligner.initialized = False
        _cached_aligner.setup()
        logger.info("Aligner re-setup (%.2fs)", time.time() - t0)

    t0 = time.time()
    _cached_aligner.align()
    logger.info("Aligner align (%.2fs)", time.time() - t0)

    t0 = time.time()
    _cached_aligner.export_files(str(output_dir))
    logger.info("Aligner export (%.2fs)", time.time() - t0)

    tg_path = _find_textgrid(output_dir)
    intervals = parse_textgrid(tg_path)
    logger.info("Parsed TextGrid: %d intervals", len(intervals))
    return intervals


# ---------------------------------------------------------------------------
# Method 3: mfa align CLI fallback (verbose)
# ---------------------------------------------------------------------------

def run_mfa_cli(audio_path: str, lab_content: str,
                beam: int = 10, retry_beam: int = 40) -> list[dict]:
    """Fallback: full 'mfa align' corpus-based CLI."""
    work_dir = Path(tempfile.mkdtemp(prefix="mfa_align_"))
    output_dir = work_dir / "output"
    output_dir.mkdir(parents=True)
    _prepare_files(audio_path, lab_content, work_dir)

    cmd = [
        "mfa", "align",
        str(work_dir / "corpus"),
        str(DICTIONARY_PATH),
        str(MODEL_PATH),
        str(output_dir),
        "--clean",
        "--single_speaker",
        "-v",
        "--beam", str(beam),
        "--retry_beam", str(retry_beam),
    ]
    logger.info("Running mfa align (fallback): %s", " ".join(cmd))
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    logger.info("mfa align finished in %.2fs (code %d)", time.time() - t0, proc.returncode)
    if proc.stderr:
        for line in proc.stderr.splitlines():
            line = line.strip()
            if line:
                logger.info("MFA| %s", line)
    if proc.returncode != 0:
        stderr = proc.stderr[-500:] if proc.stderr else ""
        raise RuntimeError(f"MFA align failed (code {proc.returncode}): {stderr}")

    tg_path = _find_textgrid(output_dir)
    intervals = parse_textgrid(tg_path)
    logger.info("Parsed TextGrid: %d intervals", len(intervals))
    return intervals


# ---------------------------------------------------------------------------
# Method 4: Direct kalpy API (no DB, no corpus, no subprocess)
# ---------------------------------------------------------------------------

def run_mfa_kalpy(audio_path: str, lab_content: str,
                  beam: int = 10, retry_beam: int = 40) -> list[dict]:
    """Use direct kalpy API — no DB, no corpus, no subprocess."""
    if _kalpy_engine is None:
        raise RuntimeError("KalpyEngine not initialized")
    work_dir = Path(tempfile.mkdtemp(prefix="mfa_kalpy_"))
    wav_path = work_dir / "audio.wav"
    save_as_wav(audio_path, wav_path)
    return _kalpy_engine.align(str(wav_path), lab_content,
                               beam=beam, retry_beam=retry_beam)


# ---------------------------------------------------------------------------
# Main dispatcher: tries methods in order
# ---------------------------------------------------------------------------

VALID_METHODS = ("kalpy", "align_one", "python_api", "cli")


def run_mfa(audio_path: str, lab_content: str, *,
            method: str = "kalpy", beam: int = 10, retry_beam: int = 40) -> list[dict]:
    """Run MFA alignment using specified method.

    Args:
        method: "kalpy", "align_one", "python_api", or "cli". Default "kalpy".
            If kalpy is requested but unavailable, falls back to align_one.
        beam: Viterbi beam width (default 10).
        retry_beam: Retry beam width (default 40).
    """
    if method not in VALID_METHODS:
        raise ValueError(f"Unknown method {method!r}. Must be one of {VALID_METHODS}")

    kwargs = dict(beam=beam, retry_beam=retry_beam)

    if method == "kalpy":
        if _kalpy_engine is not None:
            return run_mfa_kalpy(audio_path, lab_content, **kwargs)
        else:
            logger.warning("kalpy requested but unavailable, falling back to align_one")
            return run_mfa_align_one(audio_path, lab_content, **kwargs)
    elif method == "align_one":
        return run_mfa_align_one(audio_path, lab_content, **kwargs)
    elif method == "python_api":
        return run_mfa_python_cached(audio_path, lab_content, **kwargs)
    elif method == "cli":
        return run_mfa_cli(audio_path, lab_content, **kwargs)


# ---------------------------------------------------------------------------
# Reference parser + word-level alignment helper
# ---------------------------------------------------------------------------

def parse_ref(ref: str):
    """Parse a verse/word reference into phonemizer ref and word filter params.

    Supported formats:
      "7:2"           → phon_ref="7:2",     surah=7, ayah_from=2, ayah_to=2, word_from=1, word_to=None
      "7:2-7:5"       → phon_ref="7:2-7:5", surah=7, ayah_from=2, ayah_to=5, word_from=1, word_to=None
      "7:2:3"         → phon_ref="7:2",     surah=7, ayah_from=2, ayah_to=2, word_from=3, word_to=3
      "7:2:3-7:2:5"   → phon_ref="7:2",     surah=7, ayah_from=2, ayah_to=2, word_from=3, word_to=5
      "7:2:3-7:4:1"   → phon_ref="7:2-7:4", surah=7, ayah_from=2, ayah_to=4, word_from=3, word_to=1

    Returns: (phon_ref, surah, ayah_from, ayah_to, word_from, word_to)
    """
    ref = ref.strip()
    if "-" in ref:
        left, right = ref.split("-", 1)
        lp = left.split(":")
        rp = right.split(":")
    else:
        lp = ref.split(":")
        rp = lp  # same start and end

    surah = int(lp[0])
    ayah_from = int(lp[1])
    ayah_to = int(rp[1]) if len(rp) >= 2 else ayah_from

    if len(lp) >= 3:
        word_from = int(lp[2])
        word_to = int(rp[2]) if len(rp) >= 3 else word_from
    else:
        word_from = 1
        word_to = None

    if ayah_from == ayah_to:
        phon_ref = f"{surah}:{ayah_from}"
    else:
        phon_ref = f"{surah}:{ayah_from}-{surah}:{ayah_to}"

    return phon_ref, surah, ayah_from, ayah_to, word_from, word_to


def _filter_words(mapping, surah, ayah_from, ayah_to, word_from, word_to):
    """Filter phonemizer word mappings by surah/ayah/word range."""
    filtered = []
    for w in mapping.words:
        parts = w.location.split(":")
        w_surah, w_ayah, w_idx = int(parts[0]), int(parts[1]), int(parts[2])
        if w_surah != surah:
            continue
        if w_ayah < ayah_from or w_ayah > ayah_to:
            continue
        if w_ayah == ayah_from and w_idx < word_from:
            continue
        if word_to and w_ayah == ayah_to and w_idx > word_to:
            continue
        filtered.append(w)
    return filtered


def _get_verse_words(ref: str):
    """Parse a verse ref and return the phonemizer word list."""
    pm = get_phonemizer()
    phon_result = pm.phonemize(ref=ref)
    mapping = phon_result.get_mapping()
    return mapping.words


def _phonemize_ref(ref: str):
    """Phonemize a reference and return (words, mapping).

    Passes the full ref (including word ranges) to the phonemizer so that the
    last word is correctly marked as stopping, which affects tanween phonemization.

    Args:
        ref: Verse reference (e.g., "7:2", "7:2:3-7:2:5", "1:1-1:4")

    Returns:
        (words, mapping) tuple where words is a list of WordMapping objects
        and mapping is the PhonemizationMapping.
    """
    pm = get_phonemizer()
    phon_result = pm.phonemize(ref=ref)
    mapping = phon_result.get_mapping()
    return mapping.words, mapping


def _prepare_ref(ref: str):
    """Phase 1: phonemize a ref and build lab content for MFA.

    Returns a SimpleNamespace with:
        ref, all_words, lab_content, verse_mapping, verse_words,
        special_prefixes, is_special_only
    """
    special_prefixes = []
    remaining_ref = ref.strip()
    while True:
        found = False
        for name in SPECIAL_WORDS:
            if remaining_ref.lower().startswith(name.lower() + "+"):
                special_prefixes.append(name)
                remaining_ref = remaining_ref[len(name) + 1:]
                found = True
                break
        if not found:
            break

    is_special_only = False
    verse_mapping = None
    verse_words = []

    if special_prefixes:
        remaining_special = _SPECIAL_KEYS.get(remaining_ref.strip().lower())
        if remaining_special:
            special_prefixes.append(remaining_special)
            remaining_ref = ""

        all_words = []
        word_counter = 1
        for sp_name in special_prefixes:
            for w in SPECIAL_WORDS[sp_name]:
                all_words.append(SimpleNamespace(
                    location=f"0:0:{word_counter}",
                    text=w.text,
                    phonemes=list(w.phonemes),
                ))
                word_counter += 1
        if remaining_ref:
            verse_words, verse_mapping = _phonemize_ref(remaining_ref)
            all_words.extend(verse_words)
        else:
            is_special_only = True
    else:
        special_key = _SPECIAL_KEYS.get(ref.strip().lower())
        if special_key:
            all_words = SPECIAL_WORDS[special_key]
            is_special_only = True
        else:
            all_words, verse_mapping = _phonemize_ref(ref)

    if not all_words:
        raise ValueError(f"No words found for reference {ref}")

    lab_phonemes = []
    for w in all_words:
        raw = " ".join(w.phonemes)
        transformed = transform_phonemes(normalize_phonemes(raw))
        if transformed:
            lab_phonemes.append(transformed)
    lab_content = " ".join(lab_phonemes)

    return SimpleNamespace(
        ref=ref, all_words=all_words, lab_content=lab_content,
        verse_mapping=verse_mapping, verse_words=verse_words,
        special_prefixes=special_prefixes, is_special_only=is_special_only,
    )


def _recover_words(intervals, prep, include_letters: bool = False,
                    padding: str = "forward"):
    """Phase 3: map MFA phone intervals back to words (and optionally letters).

    Returns (words_list, timing_dict, mapped_intervals).
    mapped_intervals has geminates merged and original phoneme names restored.

    padding: "forward" | "symmetric" | "none" — gap-padding strategy for phonemes.
    """
    timing = {"flat_map": 0.0, "words": 0.0, "letters": 0.0}

    t0 = time.time()
    words_out = build_words_from_mapping(intervals, prep.all_words)
    timing["words"] = time.time() - t0

    # Reverse-map: merge split geminates, restore original phoneme names
    mapped_intervals = build_reverse_mapped_intervals(intervals, words_out) if words_out else intervals

    # Pad gaps at the phoneme level — letters and per-word phones inherit this
    _pad_intervals(mapped_intervals, strategy=padding)

    # Update word boundaries to match padded phone ranges
    if padding != "none":
        for w in words_out:
            active = [
                mapped_intervals[pi] for pi in w.get("phone_indices", [])
                if pi < len(mapped_intervals)
                and mapped_intervals[pi].get("phone")
                and mapped_intervals[pi]["phone"] not in ("sil", "sp", "spn")
            ]
            if active:
                w["start"] = active[0]["start"]
                w["end"] = active[-1]["end"]

    if include_letters:
        try:
            t0 = time.time()

            if prep.is_special_only and not prep.special_prefixes:
                special_key = _SPECIAL_KEYS.get(prep.ref.strip().lower())
                flat_entries = SPECIAL_FLAT_MAPPINGS[special_key]
                phoneme_sequence = SPECIAL_PHONEMES[special_key]
            elif prep.is_special_only and prep.special_prefixes:
                flat_entries = []
                phoneme_sequence = []
                for sp_name in prep.special_prefixes:
                    entries = list(SPECIAL_FLAT_MAPPINGS[sp_name])
                    if entries:
                        last_chars, last_phonemes = entries[-1]
                        entries[-1] = (last_chars + " ", last_phonemes)
                    flat_entries.extend(entries)
                    phoneme_sequence.extend(SPECIAL_PHONEMES[sp_name])
            elif prep.special_prefixes:
                flat_entries = []
                phoneme_sequence = []
                for sp_name in prep.special_prefixes:
                    entries = list(SPECIAL_FLAT_MAPPINGS[sp_name])
                    if entries:
                        last_chars, last_phonemes = entries[-1]
                        entries[-1] = (last_chars + " ", last_phonemes)
                    flat_entries.extend(entries)
                    phoneme_sequence.extend(SPECIAL_PHONEMES[sp_name])
                flat_entries.extend(build_letter_phoneme_mapping(prep.verse_mapping, words=prep.verse_words))
                for w in prep.verse_words:
                    phoneme_sequence.extend(w.phonemes)
            else:
                flat_entries = build_letter_phoneme_mapping(prep.verse_mapping, words=prep.all_words)
                phoneme_sequence = []
                for w in prep.all_words:
                    phoneme_sequence.extend(w.phonemes)
            timing["flat_map"] = time.time() - t0

            t0 = time.time()
            letter_groups = build_letter_timestamps(mapped_intervals, flat_entries, phoneme_sequence)
            words_with_letters = group_letters_by_word(letter_groups, words_out)
            timing["letters"] = time.time() - t0

            return words_with_letters, timing, mapped_intervals

        except Exception as e:
            logger.warning("Failed to build letter timestamps for %s: %s", prep.ref, e)

    result = [
        {
            "location": w["location"],
            "text": w["text"],
            "start": round(w["start"], 2),
            "end": round(w["end"], 2),
            "phone_indices": w.get("phone_indices", []),
        }
        for w in words_out
    ]
    return result, timing, mapped_intervals


def align_ref(audio_path: str, ref: str, include_letters: bool = False,
              return_timing: bool = False, return_intervals: bool = False, *,
              method: str = "kalpy", beam: int = 10, retry_beam: int = 40,
              padding: str = "forward",
              ) -> list[dict] | tuple[list[dict], dict] | tuple[list[dict], dict, list[dict]]:
    """Align audio against a verse reference. Returns word timestamps (with optional letters).

    Accepts verse refs ("7:2", "1:1-1:4", "7:2:3-7:2:5"), special refs
    ("Basmala", "Isti'adha", case-insensitive), and compound refs
    ("Basmala+2:1:1-2:1:4", "Isti'adha+Basmala+2:1:1-2:1:4").

    Args:
        audio_path: Path to audio file
        ref: Verse reference string
        include_letters: If True, include letter-level timestamps in output
        return_timing: If True, return (words, timing_dict) instead of just words
        return_intervals: If True (requires return_timing), also return raw MFA phone intervals
        method: Alignment method ("kalpy", "align_one", "python_api", "cli")
        beam: Viterbi beam width (default 10)
        retry_beam: Retry beam width (default 40)
        padding: Gap-padding strategy ("forward", "symmetric", "none")

    Returns: [{"location": "s:v:w", "text": "...", "start": float, "end": float, "letters": [...]}, ...]
             (letters field only present when include_letters=True and ref is a verse)
             If return_timing=True, returns (words, timing) where timing has keys:
             phonemize, flat_map, mfa, words, letters (all in seconds)
             If return_timing=True and return_intervals=True, returns (words, timing, intervals)
    """
    timing = {"phonemize": 0.0, "flat_map": 0.0, "mfa": 0.0, "words": 0.0, "letters": 0.0}

    t0 = time.time()
    prep = _prepare_ref(ref)
    timing["phonemize"] = time.time() - t0

    t0 = time.time()
    intervals = run_mfa(audio_path, prep.lab_content, method=method, beam=beam, retry_beam=retry_beam)
    timing["mfa"] = time.time() - t0

    words, recovery_timing, mapped_intervals = _recover_words(
        intervals, prep, include_letters=include_letters, padding=padding)
    timing.update(recovery_timing)

    if return_timing and return_intervals:
        return (words, timing, mapped_intervals)
    return (words, timing) if return_timing else words


# ---------------------------------------------------------------------------
# Main alignment pipeline (UI)
# ---------------------------------------------------------------------------

def run_alignment(audio_path: str, ref: str, surah: int, ayah_from: int,
                  ayah_to: int, word_from: int, word_to: int | None, *,
                  method: str = "kalpy", beam: int = 10, retry_beam: int = 40):
    logger.info("run_alignment: ref=%s surah=%d ayah=%d-%d word=%d-%s",
                ref, surah, ayah_from, ayah_to, word_from, word_to)
    t_total = time.time()

    # 1. Phonemize
    t0 = time.time()
    pm = get_phonemizer()
    phon_result = pm.phonemize(ref=ref)
    mapping = phon_result.get_mapping()
    logger.info("Phonemized in %.2fs: %d words", time.time() - t0, len(mapping.words))

    # Filter words by range
    all_words = []
    for w in mapping.words:
        parts = w.location.split(":")
        w_surah, w_ayah, w_idx = int(parts[0]), int(parts[1]), int(parts[2])
        if w_surah != surah:
            continue
        if w_ayah < ayah_from or w_ayah > ayah_to:
            continue
        if w_ayah == ayah_from and w_idx < word_from:
            continue
        if word_to and w_ayah == ayah_to and w_idx > word_to:
            continue
        all_words.append(w)

    if not all_words:
        raise ValueError(f"No words found for reference {ref}")
    logger.info("Filtered to %d words", len(all_words))

    # 2. Build .lab
    lab_phonemes = []
    for w in all_words:
        raw = " ".join(w.phonemes)
        transformed = transform_phonemes(normalize_phonemes(raw))
        if transformed:
            lab_phonemes.append(transformed)
    lab_content = " ".join(lab_phonemes)

    # 3. Run MFA
    intervals = run_mfa(audio_path, lab_content, method=method, beam=beam, retry_beam=retry_beam)

    # 4. Build word timestamps
    t0 = time.time()
    words_out = build_words_from_mapping(intervals, all_words)
    logger.info("Word recovery: %d words matched (%.2fs)", len(words_out), time.time() - t0)

    # 5. Reverse-map phonemes
    if words_out:
        intervals = build_reverse_mapped_intervals(intervals, words_out)

    logger.info("Total alignment time: %.2fs", time.time() - t_total)
    return intervals, words_out


# ---------------------------------------------------------------------------
# API endpoint: batch alignment (references + audios → word timestamps)
# ---------------------------------------------------------------------------

def api_align_batch(references_json, files,
                    method_str="kalpy", beam_str="10", retry_beam_str="40",
                    shared_cmvn_str="false", padding_str="forward"):
    """Batch alignment: list of (reference, audio) pairs → word timestamps.

    references_json: JSON array of reference strings, e.g. ["7:2", "1:1-1:4"]
    files: list of uploaded audio files (Gradio File objects with .name attribute)
    method_str: alignment method ("kalpy", "align_one", "python_api", "cli")
    """
    import sys, traceback as _tb
    print(f"[DEBUG] api_align_batch called: refs={references_json!r}, files={files!r}, method={method_str!r}", flush=True)
    try:
        return _api_align_batch_impl(references_json, files, method_str, beam_str, retry_beam_str, shared_cmvn_str, padding_str)
    except Exception as e:
        print(f"[DEBUG] api_align_batch EXCEPTION: {type(e).__name__}: {e}", flush=True)
        _tb.print_exc()
        sys.stdout.flush()
        return {"status": "error", "error": f"{type(e).__name__}: {e}", "results": []}

def _api_align_batch_impl(references_json, files,
                    method_str="kalpy", beam_str="10", retry_beam_str="40",
                    shared_cmvn_str="false", padding_str="forward"):
    """Batch alignment: list of (reference, audio) pairs → word timestamps.

    references_json: JSON array of reference strings, e.g. ["7:2", "1:1-1:4"]
    files: list of uploaded audio files (Gradio File objects with .name attribute)
    method_str: alignment method ("kalpy", "align_one", "python_api", "cli")
    beam_str: Viterbi beam width (default "10")
    retry_beam_str: retry beam width (default "40")
    shared_cmvn_str: "true"/"false" — compute shared CMVN across batch (kalpy only)
    padding_str: gap-padding strategy ("forward", "symmetric", "none")
    """
    if not references_json or not files:
        return {"status": "error", "error": "Both references and audio files are required"}

    method = method_str.strip() if method_str else "kalpy"
    beam = int(beam_str) if beam_str else 10
    retry_beam = int(retry_beam_str) if retry_beam_str else 40
    use_shared_cmvn = shared_cmvn_str.strip().lower() in ("true", "1", "yes") if shared_cmvn_str else False
    padding = padding_str.strip() if padding_str else "forward"
    if padding not in ("forward", "symmetric", "none"):
        padding = "forward"

    refs = references_json if isinstance(references_json, list) else [references_json]
    file_list = files if isinstance(files, list) else [files]

    if len(refs) != len(file_list):
        return {
            "status": "error",
            "error": f"Mismatch: {len(refs)} references but {len(file_list)} audio files",
        }

    logger.info("align_batch: %d items method=%s beam=%d retry_beam=%d shared_cmvn=%s",
                len(refs), method, beam, retry_beam, use_shared_cmvn)
    t_total = time.time()

    # Timing aggregation
    total_timing = {"phonemize": 0.0, "flat_map": 0.0, "mfa": 0.0, "words": 0.0, "letters": 0.0}

    # Shared CMVN batch path: phonemize all → batch align → recover all
    if use_shared_cmvn and method == "kalpy" and _kalpy_engine is not None:
        # Phase 1: phonemize all refs
        t0 = time.time()
        preps = []
        failed = {}  # index → error string
        for i, ref in enumerate(refs):
            try:
                preps.append(_prepare_ref(ref))
            except Exception as e:
                logger.warning("align_batch [%d] ref=%s phonemize failed: %s", i, ref, e)
                preps.append(None)
                failed[i] = str(e)
        total_timing["phonemize"] = time.time() - t0

        # Phase 2: convert audio + batch align with shared CMVN
        t0 = time.time()
        work_dir = Path(tempfile.mkdtemp(prefix="mfa_batch_"))
        segments = []
        valid_indices = []
        for i, (audio_file, prep) in enumerate(zip(file_list, preps)):
            if prep is None:
                continue
            audio_path = audio_file.name if hasattr(audio_file, "name") else str(audio_file)
            wav_path = work_dir / f"seg_{i:04d}.wav"
            save_as_wav(audio_path, wav_path)
            segments.append((str(wav_path), prep.lab_content))
            valid_indices.append(i)

        all_intervals = _kalpy_engine.align_batch(
            segments, beam=beam, retry_beam=retry_beam, shared_cmvn=True)
        total_timing["mfa"] = time.time() - t0

        # Phase 3: word/letter recovery per item
        intervals_iter = iter(all_intervals)
        results = []
        for i, ref in enumerate(refs):
            if i in failed:
                results.append({"ref": ref, "status": "error", "error": failed[i]})
                continue
            try:
                intervals = next(intervals_iter)
                words, recovery_timing, mapped_intervals = _recover_words(
                    intervals, preps[i], include_letters=True, padding=padding)
                _nest_phones_in_words(words, mapped_intervals)
                results.append({"ref": ref, "status": "ok", "words": words})
                for k in ("flat_map", "words", "letters"):
                    total_timing[k] += recovery_timing.get(k, 0.0)
            except Exception as e:
                logger.warning("align_batch [%d] ref=%s recovery failed: %s", i, ref, e)
                results.append({"ref": ref, "status": "error", "error": str(e)})
    else:
        # Per-item loop (existing path)
        results = []
        for i, (ref, audio_file) in enumerate(zip(refs, file_list)):
            audio_path = audio_file.name if hasattr(audio_file, "name") else str(audio_file)
            try:
                words, item_timing, mapped_intervals = align_ref(
                    audio_path, ref, include_letters=True,
                    return_timing=True, return_intervals=True,
                    method=method, beam=beam, retry_beam=retry_beam,
                    padding=padding)
                _nest_phones_in_words(words, mapped_intervals)
                results.append({"ref": ref, "status": "ok", "words": words})
                for k in total_timing:
                    total_timing[k] += item_timing.get(k, 0.0)
            except Exception as e:
                logger.warning("align_batch [%d] ref=%s failed: %s", i, ref, e)
                results.append({"ref": ref, "status": "error", "error": str(e)})

    elapsed = round(time.time() - t_total, 2)
    timing_str = " | ".join(f"{k} {v:.2f}s" for k, v in total_timing.items())
    logger.info("align_batch done: %d items in %.2fs | %s", len(results), elapsed, timing_str)
    return {
        "status": "ok",
        "count": len(results),
        "elapsed_seconds": elapsed,
        "shared_cmvn": use_shared_cmvn,
        "results": results,
    }


# ---------------------------------------------------------------------------
# API endpoint: phonemes + audio → intervals
# ---------------------------------------------------------------------------

def api_align(audio_path, lab_phonemes_str,
              method_str="kalpy", beam_str="10", retry_beam_str="40"):
    """API endpoint: takes audio + pre-transformed phoneme string, returns intervals JSON."""
    if audio_path is None:
        return {"error": "No audio provided", "intervals": [], "status": "error"}
    if not lab_phonemes_str or not lab_phonemes_str.strip():
        return {"error": "No phonemes provided", "intervals": [], "status": "error"}

    method = method_str.strip() if method_str else "kalpy"
    beam = int(beam_str) if beam_str else 10
    retry_beam = int(retry_beam_str) if retry_beam_str else 40

    logger.info("api_align called: phonemes=%s method=%s beam=%d retry_beam=%d",
                lab_phonemes_str[:200], method, beam, retry_beam)
    try:
        t0 = time.time()
        intervals = run_mfa(audio_path, lab_phonemes_str.strip(),
                            method=method, beam=beam, retry_beam=retry_beam)
        elapsed = time.time() - t0
        logger.info("api_align done: %d intervals in %.2fs", len(intervals), elapsed)
        return {
            "intervals": intervals,
            "status": "ok",
            "num_intervals": len(intervals),
            "elapsed_seconds": round(elapsed, 2),
        }
    except Exception as e:
        logger.exception("api_align failed")
        return {"error": str(e), "intervals": [], "status": "error"}


def api_compare_methods(audio_path, lab_phonemes_str,
                        beam_str="10", retry_beam_str="40"):
    """Run kalpy and align_one on the same input. Return both interval lists for comparison."""
    if audio_path is None:
        return {"error": "No audio provided"}
    lab = lab_phonemes_str.strip() if lab_phonemes_str else ""
    if not lab:
        return {"error": "No phonemes provided"}

    beam = int(beam_str) if beam_str else 10
    retry_beam = int(retry_beam_str) if retry_beam_str else 40

    results = {}
    for name, fn in [("kalpy", run_mfa_kalpy), ("align_one", run_mfa_align_one)]:
        try:
            t0 = time.time()
            intervals = fn(audio_path, lab, beam=beam, retry_beam=retry_beam)
            elapsed = time.time() - t0
            results[name] = {
                "intervals": intervals,
                "num_intervals": len(intervals),
                "elapsed_seconds": round(elapsed, 2),
                "status": "ok",
            }
        except Exception as e:
            logger.exception("compare: %s failed", name)
            results[name] = {"status": "error", "error": str(e)}

    # Compute diff summary if both succeeded
    if results.get("kalpy", {}).get("status") == "ok" and results.get("align_one", {}).get("status") == "ok":
        k_ivs = results["kalpy"]["intervals"]
        a_ivs = results["align_one"]["intervals"]
        max_start_diff = 0.0
        max_end_diff = 0.0
        phone_mismatches = []
        n = min(len(k_ivs), len(a_ivs))
        for i in range(n):
            sd = abs(k_ivs[i]["start"] - a_ivs[i]["start"])
            ed = abs(k_ivs[i]["end"] - a_ivs[i]["end"])
            max_start_diff = max(max_start_diff, sd)
            max_end_diff = max(max_end_diff, ed)
            if k_ivs[i]["phone"] != a_ivs[i]["phone"]:
                phone_mismatches.append({
                    "index": i,
                    "kalpy": k_ivs[i]["phone"],
                    "align_one": a_ivs[i]["phone"],
                })
        results["diff"] = {
            "kalpy_count": len(k_ivs),
            "align_one_count": len(a_ivs),
            "compared": n,
            "max_start_diff": round(max_start_diff, 4),
            "max_end_diff": round(max_end_diff, 4),
            "phone_mismatches": phone_mismatches,
        }
    return results


# ---------------------------------------------------------------------------
# Batch benchmark: compare alignment methods on N duplicated segments
# ---------------------------------------------------------------------------

def _make_batch_corpus(audio_path: str, lab_content: str, n: int, work_dir: Path):
    """Create corpus with N copies of the same audio+lab."""
    corpus_dir = work_dir / "corpus" / "speaker"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    # Convert source audio once
    src_wav = work_dir / "_src.wav"
    save_as_wav(audio_path, src_wav)

    for i in range(n):
        name = f"utt_{i:03d}"
        shutil.copy2(src_wav, corpus_dir / f"{name}.wav")
        (corpus_dir / f"{name}.lab").write_text(lab_content, encoding="utf-8")

    return corpus_dir


def batch_method_align_one(audio_path: str, lab_content: str, n: int,
                           beam: int = 10, retry_beam: int = 40) -> dict:
    """Method A: mfa align_one in a loop."""
    logger.info("[batch] Method A: align_one loop × %d", n)
    work_dir = Path(tempfile.mkdtemp(prefix="mfa_batch_one_"))
    src_wav = work_dir / "src.wav"
    save_as_wav(audio_path, src_wav)

    total_intervals = 0
    t_total = time.time()
    for i in range(n):
        wav_i = work_dir / f"utt_{i:03d}.wav"
        lab_i = work_dir / f"utt_{i:03d}.lab"
        tg_i = work_dir / f"utt_{i:03d}.TextGrid"
        shutil.copy2(src_wav, wav_i)
        lab_i.write_text(lab_content, encoding="utf-8")

        cmd = [
            "mfa", "align_one",
            str(wav_i), str(lab_i),
            str(DICTIONARY_PATH), str(MODEL_PATH),
            str(tg_i),
            "--beam", str(beam),
            "--retry_beam", str(retry_beam),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            logger.warning("[batch] align_one failed for utt_%03d: %s", i, proc.stderr[-200:])
            continue
        intervals = parse_textgrid(tg_i)
        total_intervals += len(intervals)
        if i == 0 or (i + 1) % 5 == 0:
            logger.info("[batch] align_one %d/%d done (%.1fs so far)",
                        i + 1, n, time.time() - t_total)

    elapsed = time.time() - t_total
    logger.info("[batch] Method A done: %.2fs total, %.2fs/segment", elapsed, elapsed / n)
    return {"total_seconds": round(elapsed, 2), "per_segment": round(elapsed / n, 2),
            "total_intervals": total_intervals, "status": "ok"}


def batch_method_corpus_cli(audio_path: str, lab_content: str, n: int,
                            beam: int = 10, retry_beam: int = 40) -> dict:
    """Method B: single mfa align on full corpus."""
    logger.info("[batch] Method B: corpus CLI × %d", n)
    work_dir = Path(tempfile.mkdtemp(prefix="mfa_batch_corpus_"))
    output_dir = work_dir / "output"
    output_dir.mkdir()

    t0 = time.time()
    _make_batch_corpus(audio_path, lab_content, n, work_dir)
    logger.info("[batch] Corpus prepared in %.2fs", time.time() - t0)

    cmd = [
        "mfa", "align",
        str(work_dir / "corpus"),
        str(DICTIONARY_PATH), str(MODEL_PATH),
        str(output_dir),
        "--clean", "--single_speaker",
        "--beam", str(beam),
        "--retry_beam", str(retry_beam),
    ]
    logger.info("[batch] Running mfa align...")
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    mfa_time = time.time() - t0
    logger.info("[batch] mfa align finished in %.2fs (code %d)", mfa_time, proc.returncode)
    if proc.stderr:
        for line in proc.stderr.splitlines():
            line = line.strip()
            if line and ("INFO" in line or "WARNING" in line):
                logger.info("MFA| %s", line)
    if proc.returncode != 0:
        return {"total_seconds": round(mfa_time, 2), "status": "error",
                "error": proc.stderr[-300:] if proc.stderr else "unknown"}

    # Count intervals across all TextGrids
    total_intervals = 0
    for tg_file in output_dir.rglob("*.TextGrid"):
        total_intervals += len(parse_textgrid(tg_file))

    elapsed = time.time() - t0 + (time.time() - t0 - mfa_time)  # include corpus prep
    # Use wall clock from start
    elapsed = mfa_time  # just MFA time (corpus prep is negligible)
    logger.info("[batch] Method B done: %.2fs total, %.2fs/segment", elapsed, elapsed / n)
    return {"total_seconds": round(elapsed, 2), "per_segment": round(elapsed / n, 2),
            "total_intervals": total_intervals, "status": "ok"}


def batch_method_python_api(audio_path: str, lab_content: str, n: int,
                            beam: int = 10, retry_beam: int = 40) -> dict:
    """Method C: Python API PretrainedAligner on full corpus."""
    logger.info("[batch] Method C: Python API × %d", n)
    from montreal_forced_aligner.alignment.pretrained import PretrainedAligner

    work_dir = Path(tempfile.mkdtemp(prefix="mfa_batch_py_"))
    output_dir = work_dir / "output"
    output_dir.mkdir()

    t0 = time.time()
    _make_batch_corpus(audio_path, lab_content, n, work_dir)
    prep_time = time.time() - t0
    logger.info("[batch] Corpus prepared in %.2fs", prep_time)

    t0 = time.time()
    aligner = PretrainedAligner(
        acoustic_model_path=str(MODEL_PATH),
        corpus_directory=str(work_dir / "corpus"),
        dictionary_path=str(DICTIONARY_PATH),
        output_directory=str(output_dir),
        clean=True,
        single_speaker=True,
        beam=beam,
        retry_beam=retry_beam,
    )
    init_time = time.time() - t0
    logger.info("[batch] PretrainedAligner init (%.2fs)", init_time)

    t0 = time.time()
    aligner.setup()
    setup_time = time.time() - t0
    logger.info("[batch] Aligner setup (%.2fs)", setup_time)

    t0 = time.time()
    aligner.align()
    align_time = time.time() - t0
    logger.info("[batch] Aligner align (%.2fs)", align_time)

    t0 = time.time()
    aligner.export_files(str(output_dir))
    export_time = time.time() - t0
    logger.info("[batch] Aligner export (%.2fs)", export_time)

    try:
        aligner.cleanup()
    except Exception:
        pass

    total_intervals = 0
    for tg_file in output_dir.rglob("*.TextGrid"):
        total_intervals += len(parse_textgrid(tg_file))

    total = prep_time + init_time + setup_time + align_time + export_time
    logger.info("[batch] Method C done: %.2fs total, %.2fs/segment", total, total / n)
    return {
        "total_seconds": round(total, 2),
        "per_segment": round(total / n, 2),
        "total_intervals": total_intervals,
        "breakdown": {
            "prep": round(prep_time, 2),
            "init": round(init_time, 2),
            "setup": round(setup_time, 2),
            "align": round(align_time, 2),
            "export": round(export_time, 2),
        },
        "status": "ok",
    }


def batch_method_kalpy(audio_path: str, lab_content: str, n: int,
                       beam: int = 10, retry_beam: int = 40,
                       shared_cmvn: bool = False) -> dict:
    """Method D: direct kalpy API — no setup overhead."""
    if _kalpy_engine is None:
        raise RuntimeError("KalpyEngine not initialized")
    logger.info("[batch] Method D: kalpy direct × %d", n)
    work_dir = Path(tempfile.mkdtemp(prefix="mfa_batch_kalpy_"))
    src_wav = work_dir / "src.wav"
    save_as_wav(audio_path, src_wav)

    # Prepare N copies
    segments = []
    for i in range(n):
        wav_i = work_dir / f"utt_{i:03d}.wav"
        shutil.copy2(src_wav, wav_i)
        segments.append((str(wav_i), lab_content))

    t0 = time.time()
    all_results = _kalpy_engine.align_batch(segments, beam=beam, retry_beam=retry_beam,
                                            shared_cmvn=shared_cmvn)
    elapsed = time.time() - t0

    total_intervals = sum(len(r) for r in all_results)
    logger.info("[batch] Method D done: %.2fs total, %.2fs/segment", elapsed, elapsed / n)
    return {
        "total_seconds": round(elapsed, 2),
        "per_segment": round(elapsed / n, 2),
        "total_intervals": total_intervals,
        "status": "ok",
    }


def api_batch_benchmark(audio_path, lab_phonemes_str, num_copies_str, methods_str="",
                        beam_str="10", retry_beam_str="40", shared_cmvn_str="false"):
    """Benchmark endpoint: compare MFA methods on N duplicated segments.

    methods_str: comma-separated list of methods to run.
                 Options: align_one, corpus_cli, python_api, kalpy.
                 Empty string or blank runs all.
    beam_str: Viterbi beam width (default "10").
    retry_beam_str: retry beam width (default "40").
    shared_cmvn_str: "true"/"false" — shared CMVN for kalpy batch (default "false").
    """
    if audio_path is None:
        return {"error": "No audio provided"}
    if not lab_phonemes_str or not lab_phonemes_str.strip():
        return {"error": "No phonemes provided"}

    n = int(num_copies_str) if num_copies_str else 20
    n = max(1, min(n, 200))
    lab = lab_phonemes_str.strip()
    beam = int(beam_str) if beam_str else 10
    retry_beam = int(retry_beam_str) if retry_beam_str else 40
    shared_cmvn = shared_cmvn_str.strip().lower() == "true" if shared_cmvn_str else False

    # Parse methods filter
    all_methods = ["align_one_loop", "corpus_cli", "python_api", "kalpy"]
    if methods_str and methods_str.strip():
        # Accept short names like "corpus_cli,python_api" or "cli,python"
        requested = [m.strip().lower() for m in methods_str.split(",") if m.strip()]
        methods = []
        for r in requested:
            for m in all_methods:
                if r in m and m not in methods:
                    methods.append(m)
        if not methods:
            methods = all_methods
    else:
        methods = all_methods

    logger.info("=== BATCH BENCHMARK: %d segments, methods=%s beam=%d retry_beam=%d ===",
                n, methods, beam, retry_beam)

    beam_kwargs = dict(beam=beam, retry_beam=retry_beam)
    results = {}

    if "align_one_loop" in methods:
        try:
            results["align_one_loop"] = batch_method_align_one(audio_path, lab, n, **beam_kwargs)
        except Exception as e:
            logger.exception("[batch] Method A failed")
            results["align_one_loop"] = {"status": "error", "error": str(e)}

    if "corpus_cli" in methods:
        try:
            results["corpus_cli"] = batch_method_corpus_cli(audio_path, lab, n, **beam_kwargs)
        except Exception as e:
            logger.exception("[batch] Method B failed")
            results["corpus_cli"] = {"status": "error", "error": str(e)}

    if "python_api" in methods:
        try:
            results["python_api"] = batch_method_python_api(audio_path, lab, n, **beam_kwargs)
        except Exception as e:
            logger.exception("[batch] Method C failed")
            results["python_api"] = {"status": "error", "error": str(e)}

    if "kalpy" in methods:
        try:
            results["kalpy"] = batch_method_kalpy(audio_path, lab, n,
                                                  **beam_kwargs, shared_cmvn=shared_cmvn)
        except Exception as e:
            logger.exception("[batch] Method D failed")
            results["kalpy"] = {"status": "error", "error": str(e)}

    logger.info("=== BATCH BENCHMARK COMPLETE ===")
    for name, r in results.items():
        logger.info("  %s: %.2fs total, %.2fs/seg, status=%s",
                     name, r.get("total_seconds", -1), r.get("per_segment", -1), r.get("status"))

    return {"num_segments": n, "results": results}


# ---------------------------------------------------------------------------
# Gradio UI helpers
# ---------------------------------------------------------------------------

def get_surah_choices():
    choices = []
    for num in sorted(SURAH_INFO.keys(), key=lambda x: int(x)):
        info = SURAH_INFO[num]
        name = info.get("name_en", "") or info.get("name", "")
        choices.append((f"{num} - {name}", num))
    return choices


def get_ayah_choices(surah_num):
    if not surah_num:
        return gr.update(choices=[], value=None), gr.update(choices=[], value=None)
    info = SURAH_INFO.get(str(surah_num), {})
    verses = info.get("verses", [])
    if verses:
        choices = [(str(v["verse"]), v["verse"]) for v in verses]
    else:
        num_verses = info.get("num_verses", 1)
        choices = [(str(i), i) for i in range(1, num_verses + 1)]
    return (
        gr.update(choices=choices, value=choices[0][1] if choices else None),
        gr.update(choices=choices, value=choices[-1][1] if choices else None),
    )


def align(audio, surah_num, ayah_from, ayah_to, word_from, word_to):
    import sys, traceback as _tb
    print(f"[DEBUG] align called: audio={audio!r}, surah={surah_num!r}, ayah={ayah_from!r}-{ayah_to!r}", flush=True)
    try:
        return _align_impl(audio, surah_num, ayah_from, ayah_to, word_from, word_to)
    except Exception as e:
        print(f"[DEBUG] align EXCEPTION: {type(e).__name__}: {e}", flush=True)
        _tb.print_exc()
        sys.stdout.flush()
        return None, None, f"Error: {type(e).__name__}: {e}"

def _align_impl(audio, surah_num, ayah_from, ayah_to, word_from, word_to):
    if audio is None:
        return None, None, "No audio provided."
    if not surah_num:
        return None, None, "Select a surah."
    if not ayah_from or not ayah_to:
        return None, None, "Select ayah range."

    surah = int(surah_num)
    af = int(ayah_from)
    at = int(ayah_to)
    wf = int(word_from) if word_from else 1
    wt = int(word_to) if word_to else None

    if af == at:
        ref = f"{surah}:{af}"
    else:
        ref = f"{surah}:{af}-{surah}:{at}"

    try:
        intervals, words = run_alignment(audio, ref, surah, af, at, wf, wt)
    except Exception as e:
        logger.exception("Alignment failed")
        return None, None, f"Alignment failed: {e}"

    # Build words table (list of lists for Gradio Dataframe)
    words_rows = [
        [w["location"], w["text"], f"{w['start']:.3f}", f"{w['end']:.3f}", " ".join(w["phonemes"])]
        for w in words
    ]

    # Build phoneme intervals table (list of lists)
    phone_rows = []
    for iv in intervals:
        phone = iv["phone"]
        if not phone or phone in ("sil", "sp", "spn"):
            phone = f"({phone or 'sil'})"
        phone_rows.append([phone, f"{iv['start']:.4f}", f"{iv['end']:.4f}"])

    status = f"Aligned {len(words)} words, {len(intervals)} phones."
    logger.info(status)
    return words_rows, phone_rows, status


# ---------------------------------------------------------------------------
# Build Gradio app
# ---------------------------------------------------------------------------

logger.info("Building Gradio app...")
surah_choices = get_surah_choices()

with gr.Blocks(title="MFA Aligner") as demo:
    gr.Markdown("# MFA Aligner")
    gr.Markdown("Upload Quran recitation audio and select the reference to align.")

    with gr.Row():
        with gr.Column(scale=1):
            audio_input = gr.Audio(type="filepath", label="Audio")
            surah_dd = gr.Dropdown(
                choices=surah_choices,
                label="Surah",
                interactive=True,
            )
            with gr.Row():
                ayah_from_dd = gr.Dropdown(choices=[], label="Ayah From", interactive=True)
                ayah_to_dd = gr.Dropdown(choices=[], label="Ayah To", interactive=True)
            with gr.Row():
                word_from_input = gr.Number(label="Word From", value=1, precision=0)
                word_to_input = gr.Number(label="Word To (empty=all)", precision=0)
            align_btn = gr.Button("Align", variant="primary")
            status_box = gr.Textbox(label="Status", interactive=False)

        with gr.Column(scale=2):
            words_table = gr.Dataframe(
                label="Words",
                headers=["Location", "Word", "Start (s)", "End (s)", "Phonemes"],
                interactive=False,
            )
            phones_table = gr.Dataframe(
                label="Phoneme Intervals",
                headers=["Phone", "Start (s)", "End (s)"],
                interactive=False,
            )

    # Hidden API-only components
    api_audio_input = gr.Audio(type="filepath", visible=False)
    api_phonemes_input = gr.Textbox(visible=False)
    api_method_input = gr.Textbox(visible=False, value="kalpy")
    api_beam_input = gr.Textbox(visible=False, value="10")
    api_retry_beam_input = gr.Textbox(visible=False, value="40")
    api_json_output = gr.JSON(visible=False)
    api_btn = gr.Button(visible=False)

    # Cascade ayah dropdowns on surah change
    surah_dd.change(
        fn=get_ayah_choices,
        inputs=[surah_dd],
        outputs=[ayah_from_dd, ayah_to_dd],
    )

    # Align button (UI)
    align_btn.click(
        fn=align,
        inputs=[audio_input, surah_dd, ayah_from_dd, ayah_to_dd, word_from_input, word_to_input],
        outputs=[words_table, phones_table, status_box],
        api_name="align",
    )

    # API endpoint: phonemes + audio → intervals JSON
    api_btn.click(
        fn=api_align,
        inputs=[api_audio_input, api_phonemes_input,
                api_method_input, api_beam_input, api_retry_beam_input],
        outputs=[api_json_output],
        api_name="align_phonemes",
    )

    # Batch benchmark API
    api_batch_audio = gr.Audio(type="filepath", visible=False)
    api_batch_phonemes = gr.Textbox(visible=False)
    api_batch_n = gr.Textbox(visible=False)
    api_batch_methods = gr.Textbox(visible=False)
    api_batch_beam = gr.Textbox(visible=False, value="10")
    api_batch_retry_beam = gr.Textbox(visible=False, value="40")
    api_batch_shared_cmvn = gr.Textbox(visible=False, value="false")
    api_batch_output = gr.JSON(visible=False)
    api_batch_btn = gr.Button(visible=False)
    api_batch_btn.click(
        fn=api_batch_benchmark,
        inputs=[api_batch_audio, api_batch_phonemes, api_batch_n, api_batch_methods,
                api_batch_beam, api_batch_retry_beam, api_batch_shared_cmvn],
        outputs=[api_batch_output],
        api_name="batch_benchmark",
    )

    # Batch alignment API (references + audios → word timestamps)
    api_ab_refs = gr.JSON(visible=False)
    api_ab_files = gr.File(file_count="multiple", visible=False)
    api_ab_method = gr.Textbox(visible=False, value="kalpy")
    api_ab_beam = gr.Textbox(visible=False, value="10")
    api_ab_retry_beam = gr.Textbox(visible=False, value="40")
    api_ab_shared_cmvn = gr.Textbox(visible=False, value="false")
    api_ab_padding = gr.Textbox(visible=False, value="forward")
    api_ab_output = gr.JSON(visible=False)
    api_ab_btn = gr.Button(visible=False)
    api_ab_btn.click(
        fn=api_align_batch,
        inputs=[api_ab_refs, api_ab_files,
                api_ab_method, api_ab_beam, api_ab_retry_beam, api_ab_shared_cmvn,
                api_ab_padding],
        outputs=[api_ab_output],
        api_name="align_batch",
    )

    # Compare methods API (kalpy vs align_one on same input)
    api_cmp_audio = gr.Audio(type="filepath", visible=False)
    api_cmp_phonemes = gr.Textbox(visible=False)
    api_cmp_beam = gr.Textbox(visible=False, value="10")
    api_cmp_retry_beam = gr.Textbox(visible=False, value="40")
    api_cmp_output = gr.JSON(visible=False)
    api_cmp_btn = gr.Button(visible=False)
    api_cmp_btn.click(
        fn=api_compare_methods,
        inputs=[api_cmp_audio, api_cmp_phonemes,
                api_cmp_beam, api_cmp_retry_beam],
        outputs=[api_cmp_output],
        api_name="compare_methods",
    )

logger.info("Launching Gradio app on 0.0.0.0:7860")
demo.launch(server_name="0.0.0.0", server_port=7860)
