"""The optional-dependency installer must never break a credential-less setup.

``scripts/devenv/setup.sh`` calls it unconditionally, so a fork clone with no
access to the private monorepo has to come out the other side with a working
Hafs-only checkout — not a failed setup.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "devenv" / "install_qua_domain.py"


@pytest.fixture
def installer():
    spec = importlib.util.spec_from_file_location("_install_qua_domain", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exits_zero_without_installing_when_no_credential_reaches_the_monorepo(
    installer, monkeypatch, capsys
):
    monkeypatch.delenv(installer.DEPLOY_KEY_ENV, raising=False)
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 128, b"", b"")
    )
    monkeypatch.setattr("sys.argv", ["install_qua_domain.py"])

    assert installer.main() == 0
    out = capsys.readouterr().out
    assert "skipped" in out
    assert "Hafs-only" in out


def test_a_fetch_failure_is_loud_when_a_credential_did_exist(installer, monkeypatch):
    # The silent path is only for "no credential". A key that IS present but
    # cannot fetch the pin means a bad pin or a revoked key — that must fail.
    monkeypatch.setenv(installer.DEPLOY_KEY_ENV, "-----BEGIN KEY-----\nx\n-----END KEY-----")
    monkeypatch.setattr("sys.argv", ["install_qua_domain.py"])

    def boom(cmd, **kwargs):
        raise subprocess.CalledProcessError(128, cmd)

    monkeypatch.setattr(installer, "_run", boom)
    with pytest.raises(subprocess.CalledProcessError):
        installer.main()


def test_the_deploy_key_is_written_lf_terminated_at_owner_only_mode(installer, tmp_path):
    # OpenSSH rejects both a CRLF key and a key with no trailing newline with a
    # bare "invalid format", and refuses a group/world-readable one outright.
    key = installer._write_key("-----BEGIN KEY-----\r\nbody\r\n-----END KEY-----", tmp_path)
    raw = key.read_bytes()

    assert b"\r" not in raw
    assert raw.endswith(b"-----END KEY-----\n")
    if os.name == "posix":
        # Windows has no POSIX mode bits; every platform that actually runs ssh
        # here (CI, the image build, the Space) is POSIX.
        assert not stat.S_IMODE(key.stat().st_mode) & (stat.S_IRGRP | stat.S_IROTH)


def test_git_runs_without_an_interactive_prompt(installer, tmp_path):
    # GIT_TERMINAL_PROMPT=0 turns a missing credential into an immediate
    # non-zero exit; without it a CI runner blocks until the job times out.
    env = installer._git_env(tmp_path / "key")
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert str(installer.QUA_COMMIT) not in env["GIT_SSH_COMMAND"]
    assert "-i " in env["GIT_SSH_COMMAND"]


def test_check_mode_reports_without_touching_the_network(installer, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["install_qua_domain.py", "--check"])
    monkeypatch.setenv(installer.DEPLOY_KEY_ENV, "key-material")

    def fail(*a, **kw):  # noqa: ANN002, ANN003
        pytest.fail("--check must not shell out")

    monkeypatch.setattr(installer, "_run", fail)
    assert installer.main() == 0
    assert installer.QUA_COMMIT in capsys.readouterr().out
