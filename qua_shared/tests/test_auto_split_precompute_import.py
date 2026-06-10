"""``qua_shared.auto_split_precompute`` must import in the qua_jobs image.

The job container stages ``qua_shared`` + ``qua_jobs`` only — never the
``inspector/`` tree. cut_release imports ``word_counts_from_surah_info`` from
this module, so a module-level ``from utils.…`` import (inspector-local) would
crash the cut with ``ModuleNotFoundError: No module named 'utils'`` (regression
shipped in PR #165). The ``utils.*`` helpers are imported lazily inside
``run_precompute``'s code path, which only ever runs where ``inspector/`` exists.

This test reproduces the job env by importing the module in a subprocess whose
``sys.path`` excludes ``inspector/`` — the in-process suite can't, because the
qua_shared conftest puts ``inspector/`` on the path.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]

_CHILD = (
    "import sys;"
    "import qua_shared.auto_split_precompute as m;"
    # The simulated job env must not have the inspector tree importable.
    "assert str(m._INSPECTOR_DIR) not in sys.path, sys.path;"
    "wc = m.word_counts_from_surah_info({'1': {'verses': [{'verse': 1, 'num_words': 4}]}});"
    "assert wc == {(1, 1): 4}, wc;"
    "print('OK')"
)


def test_module_imports_and_cut_helper_works_without_inspector_tree():
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
