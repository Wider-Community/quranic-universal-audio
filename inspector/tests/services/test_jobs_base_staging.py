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
    trees on disk or on whether ``qpc_hafs.json`` exists in this checkout.
    """
    (tmp_path / "qua_shared").mkdir(parents=True)
    (tmp_path / "qua_shared" / "__init__.py").write_text("")
    (tmp_path / "qua_jobs").mkdir(parents=True)
    for ep in base.REQUIRED_ENTRYPOINTS:
        (tmp_path / ep).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / ep).write_text("# stub")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "surah_info.json").write_text("{}")
    (tmp_path / "data" / "qpc_hafs.json").write_text("{}")
    (tmp_path / ".github" / "config").mkdir(parents=True)
    (tmp_path / ".github" / "config" / "repo.yml").write_text("hf_dataset: foo/bar")
    (tmp_path / "docs" / "templates").mkdir(parents=True)
    (tmp_path / "docs" / "templates" / "release_body.md").write_text("{{ release_title }}")
    (tmp_path / "docs" / "templates" / "hf_dataset_card.md").write_text("{{ dataset_title }}")
    (tmp_path / "LICENSE").write_text("MIT")
    monkeypatch.setattr(base, "REPO_ROOT", tmp_path)

    base.stage_job_code()
    assert len(stub_batch) == 1
    targets = {target for _src, target in stub_batch[0]["add"]}
    for rel in base.REQUIRED_ENTRYPOINTS:
        assert f"code/{rel}" in targets, f"missing entrypoint upload: {rel}"
    for rel in base.REQUIRED_STATIC_FILES:
        assert f"code/{rel}" in targets, f"missing static upload: {rel}"


def test_stage_job_code_decompresses_qpc_when_only_gzip_present(stub_batch, monkeypatch, tmp_path):
    """When only ``data/qpc_hafs.json.gz`` exists, stage plain JSON."""
    (tmp_path / "qua_shared").mkdir(parents=True)
    (tmp_path / "qua_jobs").mkdir(parents=True)
    for ep in base.REQUIRED_ENTRYPOINTS:
        (tmp_path / ep).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / ep).write_text("# stub")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "surah_info.json").write_text("{}")
    import gzip as _gzip

    (tmp_path / "data" / "qpc_hafs.json.gz").write_bytes(
        _gzip.compress(b'{"1:1:1": {"text": "x"}}')
    )
    (tmp_path / ".github" / "config").mkdir(parents=True)
    (tmp_path / ".github" / "config" / "repo.yml").write_text("hf_dataset: foo/bar")
    (tmp_path / "docs" / "templates").mkdir(parents=True)
    (tmp_path / "docs" / "templates" / "release_body.md").write_text("{{ release_title }}")
    (tmp_path / "docs" / "templates" / "hf_dataset_card.md").write_text("{{ dataset_title }}")
    (tmp_path / "LICENSE").write_text("MIT")
    monkeypatch.setattr(base, "REPO_ROOT", tmp_path)

    base.stage_job_code()

    assert len(stub_batch) == 1
    by_target = {target: blob for _src, target, blob in stub_batch[0]["snapshot"]}
    assert by_target["code/data/qpc_hafs.json"] == b'{"1:1:1": {"text": "x"}}'


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


# --- poll-handler registration (the auto-regen completion path) --------------


def test_register_poll_handlers_includes_timestamps(monkeypatch):
    """Every poll-completable kind — crucially the TS handler — must be
    registered under the kind the HF job is labelled with (``timestamps``).

    The TS handler being absent (or, historically, registered under the wrong
    key "ts" while the job is labelled "timestamps") left automated TS regens
    with no completion path (no webhook, no open drawer, poll skips a label it
    has no handler for), freezing ``produced_at`` and looping the auto-regen
    automation. The handler set is asserted against the single source of truth
    so any future omission fails here instead of in prod."""
    saved = dict(base._HANDLERS)
    base._HANDLERS.clear()
    try:
        base.register_poll_handlers()
        assert set(base._HANDLERS) == set(base.POLL_COMPLETABLE_KINDS)
        assert "timestamps" in base._HANDLERS
        # cut_release is webhook-only — it must NOT be on the poll path.
        assert "cut_release" not in base._HANDLERS
    finally:
        base._HANDLERS.clear()
        base._HANDLERS.update(saved)


def test_poll_dispatches_timestamps_labelled_job_to_handler(monkeypatch):
    """A completed HF job labelled ``task='timestamps'`` must reach the TS
    handler. The dispatcher keys handlers by the raw HF label, so a handler
    registered under any other string (the historical "ts") is silently skipped
    and the reciter never releases — this drives the real label→handler path
    that ``test_register_poll_handlers_includes_timestamps`` alone can't prove."""
    hub = sys.modules.get("huggingface_hub")
    if hub is None:
        hub = types.ModuleType("huggingface_hub")
        monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    fake_job = types.SimpleNamespace(
        id="jid-ts-1",
        labels={"task": "timestamps", "reciter": "foo_slug"},
        status=types.SimpleNamespace(stage="COMPLETED"),
    )
    monkeypatch.setattr(hub, "list_jobs", lambda: [fake_job], raising=False)

    dispatched: list[tuple[str | None, str]] = []
    saved = dict(base._HANDLERS)
    base._HANDLERS.clear()
    try:
        base.register_handler("timestamps", lambda slug, jid: dispatched.append((slug, jid)))
        base._poll_terminal_jobs()
        assert dispatched == [("foo_slug", "jid-ts-1")]
    finally:
        base._HANDLERS.clear()
        base._HANDLERS.update(saved)
