"""Tests for the local prod-bucket safety guard in ``services/storage/hf_bucket``.

The SQLite substrate syncs full-file, so a single stray write from a
local/non-deployed process clobbers production state. ``resolve_bucket_repo``
defaults every non-deployed process to the dev bucket and refuses the prod
bucket unless explicitly acknowledged. Deployed Spaces (behind the proxy) are
exempt.
"""

from __future__ import annotations

import pytest

from services.storage.hf_bucket import (
    DEV_BUCKET_REPO,
    PROD_BUCKET_REPO,
    ProdBucketRefused,
    resolve_bucket_repo,
)


def _clear(monkeypatch):
    for var in (
        "INSPECTOR_BUCKET_REPO",
        "INSPECTOR_BEHIND_PROXY",
        "INSPECTOR_ALLOW_PROD_BUCKET",
    ):
        monkeypatch.delenv(var, raising=False)


def test_defaults_to_dev_when_unset(monkeypatch):
    _clear(monkeypatch)
    assert resolve_bucket_repo() == DEV_BUCKET_REPO


def test_blank_env_falls_back_to_dev(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("INSPECTOR_BUCKET_REPO", "   ")
    assert resolve_bucket_repo() == DEV_BUCKET_REPO


def test_explicit_dev_passes_through(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("INSPECTOR_BUCKET_REPO", DEV_BUCKET_REPO)
    assert resolve_bucket_repo() == DEV_BUCKET_REPO


def test_arbitrary_personal_bucket_passes_through(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("INSPECTOR_BUCKET_REPO", "alice/quranic-inspector-alice")
    assert resolve_bucket_repo() == "alice/quranic-inspector-alice"


def test_prod_refused_locally(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("INSPECTOR_BUCKET_REPO", PROD_BUCKET_REPO)
    with pytest.raises(ProdBucketRefused):
        resolve_bucket_repo()


def test_prod_allowed_with_optin(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("INSPECTOR_BUCKET_REPO", PROD_BUCKET_REPO)
    monkeypatch.setenv("INSPECTOR_ALLOW_PROD_BUCKET", "1")
    assert resolve_bucket_repo() == PROD_BUCKET_REPO


def test_prod_allowed_when_deployed(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("INSPECTOR_BUCKET_REPO", PROD_BUCKET_REPO)
    monkeypatch.setenv("INSPECTOR_BEHIND_PROXY", "1")
    assert resolve_bucket_repo() == PROD_BUCKET_REPO
