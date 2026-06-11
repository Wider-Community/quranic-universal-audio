"""resolve_mfa_runtime / the deprecated mfa_app_path shim / import isolation.

qua_sdk-free on purpose: path resolution and the legacy-shim derivation never
touch the SDK, and importing ``qua_shared.timestamps_pipeline`` itself must
not pull qua_sdk (inspector services import the module for pure helpers — the
SDK is a job-container dependency only).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from qua_shared.timestamps_pipeline import (
    MFA_DICTIONARY_FILENAME,
    MFA_MODEL_FILENAME,
    _paths_from_app_path,
    resolve_mfa_runtime,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_runtime_dir(tmp_path: Path) -> Path:
    (tmp_path / MFA_MODEL_FILENAME).write_bytes(b"zip")
    (tmp_path / MFA_DICTIONARY_FILENAME).write_text("dict", encoding="utf-8")
    return tmp_path


def test_resolve_runtime_dir_returns_both_bundled_files(tmp_path):
    d = _make_runtime_dir(tmp_path)
    model, dictionary = resolve_mfa_runtime(d)
    assert model == str(d / MFA_MODEL_FILENAME)
    assert dictionary == str(d / MFA_DICTIONARY_FILENAME)


def test_resolve_runtime_dir_missing_dictionary_raises(tmp_path):
    (tmp_path / MFA_MODEL_FILENAME).write_bytes(b"zip")
    with pytest.raises(FileNotFoundError, match=MFA_DICTIONARY_FILENAME):
        resolve_mfa_runtime(tmp_path)


def test_resolve_none_falls_back_to_env_pair(monkeypatch):
    monkeypatch.setenv("MFA_MODEL_PATH", "/aux/mfa-runtime/quran_aligner_model.zip")
    monkeypatch.setenv("MFA_DICTIONARY_PATH", "/aux/mfa-runtime/dictionary.txt")
    model, dictionary = resolve_mfa_runtime(None)
    assert model == "/aux/mfa-runtime/quran_aligner_model.zip"
    assert dictionary == "/aux/mfa-runtime/dictionary.txt"


def test_resolve_none_without_env_raises_clear_error(monkeypatch):
    monkeypatch.delenv("MFA_MODEL_PATH", raising=False)
    monkeypatch.delenv("MFA_DICTIONARY_PATH", raising=False)
    with pytest.raises(RuntimeError, match="MFA_MODEL_PATH"):
        resolve_mfa_runtime(None)


def test_app_path_shim_derives_siblings_and_warns(tmp_path):
    app_py = tmp_path / "app.py"
    app_py.write_text("", encoding="utf-8")
    with pytest.warns(DeprecationWarning, match="mfa_app_path is deprecated"):
        model, dictionary = _paths_from_app_path(app_py)
    assert model == str(tmp_path / MFA_MODEL_FILENAME)
    assert dictionary == str(tmp_path / MFA_DICTIONARY_FILENAME)


# Importing the pipeline module must not pull qua_sdk (call-local imports
# only). Subprocess so the in-process suite's own qua_sdk imports can't mask
# a regression.
_CHILD = (
    "import sys;"
    "import qua_shared.timestamps_pipeline;"
    "leaked = [m for m in sys.modules if m == 'qua_sdk' or m.startswith('qua_sdk.')];"
    "assert not leaked, leaked;"
    "print('OK')"
)


def test_importing_pipeline_module_does_not_import_qua_sdk():
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
