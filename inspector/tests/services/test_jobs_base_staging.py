"""Tests for ``services.admin.jobs.base.stage_job_code``.

Pins the "every required entrypoint and static ref is COPYed into the runtime
image" contract: when a path is missing on disk, ``stage_job_code`` must raise
``JobStagingError`` with a clear hint BEFORE calling ``run_job``. The
HF-Job-side ``No such file or directory`` failure surfaced from a Dockerfile
COPY drop is exactly what this guards against.
"""
from __future__ import annotations

import sys
import types

import pytest

from services.admin.jobs import base


@pytest.fixture
def stub_batch(monkeypatch):
    """Stub ``batch_bucket_files`` so we can assert on the upload arg without
    touching HF infra."""
    calls: list[dict] = []
    mod = sys.modules.get("huggingface_hub")
    if mod is None:
        mod = types.ModuleType("huggingface_hub")
        monkeypatch.setitem(sys.modules, "huggingface_hub", mod)

    def fake(bucket, *, add):
        calls.append({"bucket": bucket, "add": list(add)})

    monkeypatch.setattr(mod, "batch_bucket_files", fake, raising=False)
    return calls


def test_stage_job_code_uploads_every_required_path(stub_batch):
    base.stage_job_code()
    assert len(stub_batch) == 1
    targets = {target for _src, target in stub_batch[0]["add"]}
    for rel in base.REQUIRED_ENTRYPOINTS:
        assert f"code/{rel}" in targets, f"missing entrypoint upload: {rel}"
    for rel in base.REQUIRED_STATIC_FILES:
        assert f"code/{rel}" in targets, f"missing static upload: {rel}"


def test_stage_job_code_raises_when_entrypoint_missing(stub_batch, monkeypatch, tmp_path):
    """Point REPO_ROOT at a tree missing scripts/jobs/publish_hf.py; expect
    ``JobStagingError`` with the missing path in the message."""
    (tmp_path / "scripts" / "lib").mkdir(parents=True)
    (tmp_path / "scripts" / "jobs").mkdir(parents=True)
    # Only generate_timestamps.py exists — publish_hf/cut_release/shard absent.
    (tmp_path / "scripts" / "jobs" / "generate_timestamps.py").write_text("# stub")
    (tmp_path / "scripts" / "lib" / "__init__.py").write_text("")
    monkeypatch.setattr(base, "REPO_ROOT", tmp_path)

    with pytest.raises(base.JobStagingError) as exc:
        base.stage_job_code()
    msg = str(exc.value)
    assert "scripts/jobs/publish_hf.py" in msg
    assert "Dockerfile" in msg
    assert stub_batch == [], "must not upload when contract is broken"
