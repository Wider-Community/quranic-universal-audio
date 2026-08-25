"""Tests for ``services.admin.jobs.stage_sdk``.

The timestamps job imports the SDK from a copy staged on the aligner bucket,
and the deployed Space cannot refresh that copy — the SDK is a private
workspace member with no wheel. So the copy is allowed to be older than the
launcher, and the only thing standing between "older" and "writes a shard
whose native documents and stamped version disagree" is the marker this module reads
at launch. These pin that the gate opens on a match and shuts on everything
else, including a bucket that carries no marker at all.
"""

from __future__ import annotations

import json

import pytest

from services.admin.jobs import stage_sdk
from services.admin.jobs.base import JobStagingError


def _sdk_tree(root, version: str = "SHARD_SCHEMA_VERSION = 12"):
    """A minimal qua_sdk source tree: the producer, a data file, a py.typed,
    and two things staging must skip."""
    (root / "integrations").mkdir(parents=True)
    (root / "integrations" / "shards.py").write_text(f"{version}\n", encoding="utf-8")
    (root / "integrations" / "vocabulary.json").write_text("{}", encoding="utf-8")
    (root / "py.typed").write_text("", encoding="utf-8")
    (root / "notes.md").write_text("skipped", encoding="utf-8")
    (root / "_dp_core.pyd").write_bytes(b"skipped")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.py").write_text("skipped", encoding="utf-8")
    return root


def test_the_version_comes_from_the_source_the_host_holds(tmp_path):
    src = _sdk_tree(tmp_path / "qua_sdk", "SHARD_SCHEMA_VERSION = 42")
    assert stage_sdk.source_shard_version(src) == 42


def test_a_producer_that_declares_nothing_cannot_be_staged(tmp_path):
    src = _sdk_tree(tmp_path / "qua_sdk", "# no constant here")
    with pytest.raises(JobStagingError, match="SHARD_SCHEMA_VERSION"):
        stage_sdk.source_shard_version(src)


def test_staging_carries_the_code_and_the_data_and_nothing_else(tmp_path):
    src = _sdk_tree(tmp_path / "qua_sdk")
    targets = {target for _, target in stage_sdk.stage_adds(src)}
    assert targets == {
        "code/qua_sdk/integrations/shards.py",
        "code/qua_sdk/integrations/vocabulary.json",
        "code/qua_sdk/py.typed",
    }


def test_the_marker_records_what_the_staged_producer_emits(tmp_path):
    src = _sdk_tree(tmp_path / "qua_sdk")
    marker = json.loads(stage_sdk.marker_bytes(src, 3))
    assert marker == {"shard_schema_version": 12, "files": 3}


def test_a_bucket_the_source_dropped_a_path_from_loses_it(monkeypatch):
    class Entry:
        def __init__(self, path):
            self.path, self.size = path, 1

    import huggingface_hub

    monkeypatch.setattr(
        huggingface_hub,
        "list_bucket_tree",
        lambda *a, **k: [
            Entry("code/qua_sdk/kept.py"),
            Entry("code/qua_sdk/renamed_away.py"),
            # The prefix matches as a string, so the sibling marker comes back
            # under it. Sweeping it up would erase what the gate reads.
            Entry(stage_sdk.MARKER_PATH),
        ],
        raising=False,
    )
    assert stage_sdk.stale_targets({"code/qua_sdk/kept.py"}) == ["code/qua_sdk/renamed_away.py"]


@pytest.mark.parametrize(
    "marker",
    [None, {"shard_schema_version": 11}, {"files": 139}],
    ids=["never staged", "older producer", "marker without a version"],
)
def test_the_launch_is_refused_unless_the_staged_producer_agrees(monkeypatch, marker):
    monkeypatch.setattr(stage_sdk, "read_marker", lambda: marker)
    with pytest.raises(JobStagingError, match="re-stage"):
        stage_sdk.assert_staged_sdk(12)


def test_a_staged_producer_that_agrees_lets_the_launch_through(monkeypatch):
    monkeypatch.setattr(
        stage_sdk,
        "read_marker",
        lambda: {"shard_schema_version": 12, "files": 139},
    )
    stage_sdk.assert_staged_sdk(12)
