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
    touching HF infra. Snapshots the bytes of every source file at call time
    (auto-gzipped temp sources are deleted in stage_job_code's finally block,
    so reading them post-call would race the cleanup)."""
    calls: list[dict] = []
    mod = sys.modules.get("huggingface_hub")
    if mod is None:
        mod = types.ModuleType("huggingface_hub")
        monkeypatch.setitem(sys.modules, "huggingface_hub", mod)

    def fake(bucket, *, add):
        snapshot = []
        for src, target in add:
            try:
                blob = open(src, "rb").read()
            except OSError:
                blob = None
            snapshot.append((src, target, blob))
        calls.append({"bucket": bucket, "add": list(add), "snapshot": snapshot})

    monkeypatch.setattr(mod, "batch_bucket_files", fake, raising=False)
    return calls


def test_stage_job_code_uploads_every_required_path(stub_batch, monkeypatch, tmp_path):
    """Happy path against a synthetic, hermetic repo tree — every required
    entrypoint AND every required static file must be in the upload manifest.

    Mirrors the other tests' tmp_path + REPO_ROOT monkeypatch isolation so
    the assertion no longer depends on the real ``qua_shared`` / ``qua_jobs``
    trees on disk or on whether ``qpc_hafs.json.gz`` exists in this checkout.
    """
    (tmp_path / "qua_shared").mkdir(parents=True)
    (tmp_path / "qua_shared" / "__init__.py").write_text("")
    (tmp_path / "qua_jobs").mkdir(parents=True)
    for ep in base.REQUIRED_ENTRYPOINTS:
        (tmp_path / ep).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / ep).write_text("# stub")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "surah_info.json").write_text("{}")
    (tmp_path / "data" / "qpc_hafs.json.gz").write_bytes(b"\x1f\x8bstub-gz")
    (tmp_path / ".github" / "config").mkdir(parents=True)
    (tmp_path / ".github" / "config" / "repo.yml").write_text("hf_dataset: foo/bar")
    (tmp_path / ".github" / "templates").mkdir(parents=True)
    (tmp_path / ".github" / "templates" / "release_body.md").write_text("{{ release_title }}")
    (tmp_path / "LICENSE").write_text("MIT")
    monkeypatch.setattr(base, "REPO_ROOT", tmp_path)

    base.stage_job_code()
    assert len(stub_batch) == 1
    targets = {target for _src, target in stub_batch[0]["add"]}
    for rel in base.REQUIRED_ENTRYPOINTS:
        assert f"code/{rel}" in targets, f"missing entrypoint upload: {rel}"
    for rel in base.REQUIRED_STATIC_FILES:
        assert f"code/{rel}" in targets, f"missing static upload: {rel}"


def test_stage_job_code_auto_gzips_qpc_when_only_uncompressed_present(
    stub_batch, monkeypatch, tmp_path
):
    """In a dev tree with ``data/qpc_hafs.json`` but no ``.gz``, the resolver
    gzip-compresses on the fly and uploads under the ``.gz`` target path."""
    (tmp_path / "qua_shared").mkdir(parents=True)
    (tmp_path / "qua_jobs").mkdir(parents=True)
    for ep in base.REQUIRED_ENTRYPOINTS:
        (tmp_path / ep).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / ep).write_text("# stub")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "surah_info.json").write_text("{}")
    (tmp_path / "data" / "qpc_hafs.json").write_text('{"1:1:1": {"text": "x"}}')
    (tmp_path / ".github" / "config").mkdir(parents=True)
    (tmp_path / ".github" / "config" / "repo.yml").write_text("hf_dataset: foo/bar")
    (tmp_path / ".github" / "templates").mkdir(parents=True)
    (tmp_path / ".github" / "templates" / "release_body.md").write_text("{{ release_title }}")
    (tmp_path / "LICENSE").write_text("MIT")
    monkeypatch.setattr(base, "REPO_ROOT", tmp_path)

    base.stage_job_code()

    assert len(stub_batch) == 1
    by_target = {target: blob for _src, target, blob in stub_batch[0]["snapshot"]}
    assert "code/data/qpc_hafs.json.gz" in by_target
    import gzip as _gzip

    assert _gzip.decompress(by_target["code/data/qpc_hafs.json.gz"]) == b'{"1:1:1": {"text": "x"}}'


def test_stage_job_code_raises_when_entrypoint_missing(stub_batch, monkeypatch, tmp_path):
    """Point REPO_ROOT at a tree missing qua_jobs/publish_hf.py; expect
    ``JobStagingError`` with the missing path in the message."""
    (tmp_path / "qua_shared").mkdir(parents=True)
    (tmp_path / "qua_jobs").mkdir(parents=True)
    # Only generate_timestamps.py exists — publish_hf/cut_release/shard absent.
    (tmp_path / "qua_jobs" / "generate_timestamps.py").write_text("# stub")
    (tmp_path / "qua_shared" / "__init__.py").write_text("")
    monkeypatch.setattr(base, "REPO_ROOT", tmp_path)

    with pytest.raises(base.JobStagingError) as exc:
        base.stage_job_code()
    msg = str(exc.value)
    assert "qua_jobs/publish_hf.py" in msg
    assert "Dockerfile" in msg
    assert stub_batch == [], "must not upload when contract is broken"
