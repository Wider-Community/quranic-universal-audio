"""Ensure shared tests can import the Inspector service package."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_INSPECTOR = _ROOT / "inspector"
for _p in (_ROOT, _INSPECTOR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
