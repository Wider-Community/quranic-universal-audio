"""Regression: the cut's boundary-validation input must respect a real
``verse_start_ms == 0``.

A canonical verse can legitimately start at 0 ms while its first word's audio
starts a few ms later (leading gap). The old builder used
``v.get("verse_start_ms") or words[0][1]``, which treats the real ``0`` as
falsy and substitutes the word start for the *field* — while computing
``duration_ms`` from the real ``0``. That asymmetry manufactured a phantom
``duration_arithmetic`` violation and aborted the cut (seen on
``abu_bakr_al_shatri_tarteel`` 5:1 etc.). ``_verse_for_validate`` resolves the
bounds once so the three fields always agree.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.jobs.cut_release import _verse_for_validate  # noqa: E402
from scripts.lib.dataset_validation import (  # noqa: E402
    check_duration_arithmetic,
)


def test_verse_start_zero_with_leading_word_gap():
    # verse_start_ms is a real 0; first word's audio starts at 60 ms.
    v = {"verse_start_ms": 0, "verse_end_ms": 24095,
         "words": [[1, 60, 2350], [23, 21995, 24095]]}
    out = _verse_for_validate(v, segments=[])
    assert out["verse_start_ms"] == 0          # NOT coerced to the word start (60)
    assert out["verse_end_ms"] == 24095
    assert out["duration_ms"] == 24095          # end - start, consistent
    assert check_duration_arithmetic("5:1", out) == []   # no phantom violation


def test_bounds_fall_back_to_words_when_absent():
    v = {"words": [[1, 100, 500], [2, 500, 900]]}   # no verse_start/end keys
    out = _verse_for_validate(v, segments=[])
    assert out["verse_start_ms"] == 100
    assert out["verse_end_ms"] == 900
    assert out["duration_ms"] == 800
    assert check_duration_arithmetic("1:1", out) == []


def test_nonzero_start_duration_consistent():
    v = {"verse_start_ms": 120, "verse_end_ms": 12814, "words": [[1, 120, 12814]]}
    out = _verse_for_validate(v, segments=[])
    assert out["duration_ms"] == 12694
    assert check_duration_arithmetic("22:1", out) == []
