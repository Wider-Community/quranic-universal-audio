"""Fixtures for the bucket-script tests.

The scripts are flat modules run as ``python scripts/bucket/<name>.py``, so a
test importing one needs ``scripts/bucket/`` on the path; each script puts the
repo root and ``inspector/`` there itself at import time.

``clean_env`` restores ``os.environ`` around every test: a script's bootstrap
pins ``INSPECTOR_*`` directly and would otherwise leak into the next one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


@pytest.fixture(autouse=True)
def clean_env():
    before = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(before)
