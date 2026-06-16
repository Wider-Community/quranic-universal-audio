"""``qua_shared.surah_words`` must import in the qua_jobs image.

The job container stages ``qua_shared`` + ``qua_jobs`` only — never the
``inspector/`` tree. cut_release / publish_hf import
``word_counts_from_surah_info`` from this module, so it must carry zero
inspector-local (``utils.*``) or MFA deps. This reproduces the job env by
importing in a subprocess whose ``sys.path`` excludes ``inspector/`` (the
in-process suite can't — the qua_shared conftest puts ``inspector/`` on path).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from qua_shared.surah_words import word_counts_from_surah_info

_REPO_ROOT = Path(__file__).resolve().parents[2]

_CHILD = (
    "import qua_shared.surah_words as m;"
    "wc = m.word_counts_from_surah_info({'1': {'verses': [{'verse': 1, 'num_words': 4}]}});"
    "assert wc == {(1, 1): 4}, wc;"
    "print('OK')"
)


def test_word_counts_basic():
    assert word_counts_from_surah_info(
        {"2": {"verses": [{"verse": 1, "num_words": 3}, {"verse": 2, "num_words": 5}]}}
    ) == {(2, 1): 3, (2, 2): 5}


def test_module_imports_without_inspector_tree():
    # PYTHONPATH = repo root only → `import qua_shared` resolves, `utils` does not.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD],
        cwd=str(_REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    assert proc.stdout.strip().endswith("OK"), proc.stdout
