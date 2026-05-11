"""Smoke test for storage primitives (FilesystemBackend round-trip + paths).

Run with ``python -m inspector.services._storage_smoke``. The bucket backend
is exercised by integration tests against a real dev bucket separately —
this smoke is local-only.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import storage_paths
from .hf_bucket import FilesystemBackend, StorageNotFound


def smoke() -> int:
    try:
        # Path helpers
        assert storage_paths.state_path() == "state/reciter_state.json"
        assert storage_paths.catalog_path() == "catalog/reciter_catalog.json"
        assert storage_paths.roles_path() == "access/inspector_roles.json"
        assert (
            storage_paths.audit_partition_path(
                datetime(2026, 5, 12, tzinfo=timezone.utc)
            )
            == "audit/2026-05.jsonl"
        )
        assert (
            storage_paths.segments_path("saad_al_ghamdi", "wip")
            == "wip/saad_al_ghamdi/segments.json"
        )
        assert (
            storage_paths.segments_path("saad_al_ghamdi", "published")
            == "published/saad_al_ghamdi/segments.json"
        )
        assert (
            storage_paths.published_timestamps_path("saad_al_ghamdi", 1)
            == "published/saad_al_ghamdi/timestamps/1.json"
        )
        assert (
            storage_paths.audio_manifest_path("saad_al_ghamdi_mp3quran")
            == "catalog/audio_manifest/saad_al_ghamdi_mp3quran.json"
        )
        print("ok  storage_paths helpers")

        with tempfile.TemporaryDirectory() as tmp:
            backend = FilesystemBackend(tmp)

            # round-trip JSON
            backend.write_json_atomic("state/reciter_state.json", {"hello": "world"})
            assert backend.exists("state/reciter_state.json")
            obj = backend.read_json("state/reciter_state.json")
            assert obj == {"hello": "world"}
            print("ok  FilesystemBackend.write_json_atomic round-trip")

            # missing read
            try:
                backend.read_json("state/missing.json")
            except StorageNotFound:
                print("ok  FilesystemBackend.read_json raises StorageNotFound")
            else:
                raise AssertionError("expected StorageNotFound")

            # JSONL append + iterate
            for i in range(3):
                backend.append_jsonl(
                    "audit/2026-05.jsonl",
                    {"event": "test", "i": i},
                )
            records = list(backend.iter_jsonl("audit/2026-05.jsonl"))
            assert len(records) == 3
            assert records[0]["i"] == 0 and records[2]["i"] == 2
            print("ok  FilesystemBackend.append_jsonl + iter_jsonl")

            # list_dir
            backend.write_json_atomic("wip/saad_al_ghamdi/segments.json", {})
            backend.write_json_atomic("wip/saad_al_ghamdi/detailed.json", {})
            backend.write_json_atomic("wip/mishary_alafasi/segments.json", {})
            slugs = backend.list_dir("wip")
            assert slugs == ["mishary_alafasi", "saad_al_ghamdi"]
            print("ok  FilesystemBackend.list_dir")

            # copy + move + delete
            backend.copy(
                "wip/saad_al_ghamdi/segments.json",
                "published/saad_al_ghamdi/segments.json",
            )
            assert backend.exists("published/saad_al_ghamdi/segments.json")
            backend.move(
                "wip/mishary_alafasi/segments.json",
                "published/mishary_alafasi/segments.json",
            )
            assert backend.exists("published/mishary_alafasi/segments.json")
            assert not backend.exists("wip/mishary_alafasi/segments.json")
            backend.delete("published/saad_al_ghamdi/segments.json")
            assert not backend.exists("published/saad_al_ghamdi/segments.json")
            print("ok  FilesystemBackend.copy + move + delete")

            # atomic — no .tmp file left behind
            stragglers = list(Path(tmp).rglob("*.tmp.*"))
            assert not stragglers, f"tmp files left behind: {stragglers}"
            print("ok  FilesystemBackend leaves no tmp stragglers")

            # path validation
            try:
                backend.read_bytes("/absolute/path")
            except ValueError:
                print("ok  FilesystemBackend rejects absolute paths")
            else:
                raise AssertionError("expected ValueError on absolute path")

        print("storage smoke: all checks passed")
        return 0
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(smoke())
