from __future__ import annotations

import runpy
from pathlib import Path

_MODULE = Path(__file__).resolve().parents[3] / "qua_jobs" / "run_generate_timestamps.py"


def _load() -> dict:
    return runpy.run_path(str(_MODULE), run_name="timestamp_runner_test")


def test_current_phonemizer_needs_no_install(monkeypatch):
    module = _load()
    monkeypatch.setitem(
        module["installed_phonemizer_version"].__globals__,
        "installed_phonemizer_version",
        lambda: module["PHONEMIZER_VERSION"],
    )
    calls = []
    monkeypatch.setattr(module["subprocess"], "check_call", lambda command: calls.append(command))

    module["ensure_phonemizer"]()

    assert calls == []


def test_stale_image_is_repaired_with_the_exact_pin(monkeypatch):
    module = _load()
    monkeypatch.setitem(
        module["installed_phonemizer_version"].__globals__,
        "installed_phonemizer_version",
        lambda: "2.13",
    )
    calls = []
    monkeypatch.setattr(module["subprocess"], "check_call", lambda command: calls.append(command))

    module["ensure_phonemizer"]()

    assert len(calls) == 1
    assert calls[0][-1] == f"quranic-phonemizer=={module['PHONEMIZER_VERSION']}"
