"""segment_uid stability and backfill tests (MUST-4, IS-8)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}


def _segments(detailed: dict) -> list[dict]:
    out: list[dict] = []
    for entry in detailed.get("entries", []):
        out.extend(entry.get("segments", []))
    return out


def test_uid_matches_typescript_implementation():
    """Cross-platform parity vector. If this changes, frontend identity.ts must too.

    The frontend test in
    ``frontend/src/tabs/segments/__tests__/normalized-state/uid-backfill.test.ts``
    asserts the same value for the same input. Both implementations must agree.
    """
    from domain.identity import derive_uid

    assert derive_uid(1, 0, 0) == "418dc3a4-5e80-5d8e-9a3f-209a6403206e"


def test_save_round_trips_through_adapters(tmp_reciter_dir, signed_in_client, load_fixture):
    """Adapter round-trip: a normal save preserves segment_uid + matched_ref
    through the adapter path, and ``segments.json`` is regenerated with the
    verse-aggregated tuple format.
    """
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    chapter = 112
    fixture = load_fixture("112-ikhlas")
    pre_uids = [s["segment_uid"] for s in fixture["entries"][0]["segments"]]

    seg_payload = [
        {
            "time_start": s["time_start"],
            "time_end": s["time_end"],
            "matched_ref": s["matched_ref"],
            "confidence": s["confidence"],
            "segment_uid": s["segment_uid"],
        }
        for s in fixture["entries"][0]["segments"]
    ]

    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps({"full_replace": True, "segments": seg_payload, "operations": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 200

    saved_detailed = json.loads(
        (tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8")
    )
    post_uids = [s["segment_uid"] for s in saved_detailed["entries"][0]["segments"]]
    assert pre_uids == post_uids, "adapter make_seg dropped or remapped segment_uid"

    # segments.json should still contain the verse-aggregated tuple format
    saved_segments = json.loads(
        (tmp_reciter_dir.root / reciter / "segments.json").read_text(encoding="utf-8")
    )
    keys = [k for k in saved_segments.keys() if k != "_meta"]
    assert keys, "adapter rebuild_segments_json produced no verse blocks"
    for key in keys:
        for entry in saved_segments[key]:
            assert isinstance(entry, list) and len(entry) == 4, (
                f"adapter wrote wrong tuple shape under {key}: {entry!r}"
            )


def test_uid_present_in_modern_fixture_unchanged(load_fixture):
    """A modern fixture's UIDs are present and well-formed."""
    fixture = load_fixture("112-ikhlas")
    for seg in _segments(fixture):
        uid = seg.get("segment_uid")
        assert uid, f"modern fixture segment missing segment_uid: {seg}"
        assert isinstance(uid, str)
        assert len(uid) >= 16


def test_uid_backfilled_for_legacy_fixture(tmp_reciter_dir):
    """A legacy fixture (no UIDs) gets deterministic UIDs on load."""
    reciter = "legacy_reciter"
    legacy_path = tmp_reciter_dir.root / reciter / "detailed.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_doc = {
        "_meta": {"audio_source": "by_surah/fixture"},
        "entries": [
            {
                "ref": "112",
                "segments": [
                    {
                        "time_start": 1000,
                        "time_end": 2000,
                        "matched_ref": "112:1:1-112:1:1",
                        "confidence": 1.0,
                    },
                    {
                        "time_start": 3000,
                        "time_end": 4000,
                        "matched_ref": "112:1:2-112:1:2",
                        "confidence": 1.0,
                    },
                ],
            }
        ],
    }
    legacy_path.write_text(json.dumps(legacy_doc), encoding="utf-8")

    from services.data_loader import load_detailed

    entries = load_detailed(reciter)
    for seg in entries[0]["segments"]:
        uid = seg.get("segment_uid")
        assert uid, "loader must backfill segment_uid for legacy fixtures"


def test_uid_backfill_unique_across_split_chapter(tmp_reciter_dir):
    """A chapter delivered as several uid-less entries derives one uid per segment.

    The first entry's uids equal the single-entry derivation; later entries
    continue the chapter index instead of restarting it, so segments that
    share a ``time_start`` across entries never collide.
    """
    from domain.identity import derive_uid
    from services.data_loader import load_detailed

    reciter = "split_reciter"
    path = tmp_reciter_dir.root / reciter / "detailed.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    def seg(start: int, verse: int) -> dict:
        return {
            "time_start": start,
            "time_end": start + 1000,
            "matched_ref": f"1:{verse}:1-1:{verse}:1",
            "confidence": 1.0,
        }

    doc = {
        "_meta": {"audio_source": "intake_ingest"},
        "entries": [
            {"ref": "1", "segments": [seg(300, 1), seg(2000, 2)]},
            {"ref": "112", "segments": [seg(300, 1)]},
            {"ref": "1", "segments": [seg(300, 3), seg(4000, 4)]},
        ],
    }
    path.write_text(json.dumps(doc), encoding="utf-8")

    entries = load_detailed(reciter)
    uids = [s["segment_uid"] for e in entries for s in e["segments"]]
    assert all(uids)
    assert len(set(uids)) == len(uids)
    assert entries[0]["segments"][0]["segment_uid"] == derive_uid(1, 0, 300)
    assert entries[2]["segments"][0]["segment_uid"] == derive_uid(1, 2, 300)
    assert entries[1]["segments"][0]["segment_uid"] == derive_uid(112, 0, 300)


def test_uid_stable_across_load_save_load(tmp_reciter_dir, signed_in_client, load_fixture):
    """Load → save (without UIDs in payload) → load: UIDs persist (MUST-4).

    When a save payload omits ``segment_uid`` on segments, the backend
    must look up the existing UID by ``(chapter, original_index, start_ms)``
    — backfilling deterministically — and write it back to disk.  The
    on-disk UID must equal the pre-save UID after every round-trip.
    """
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")

    fixture = load_fixture("112-ikhlas")
    chapter = 112

    pre_uids = [s["segment_uid"] for s in fixture["entries"][0]["segments"]]

    seg_payload_no_uids = [
        {
            "time_start": s["time_start"],
            "time_end": s["time_end"],
            "matched_ref": s["matched_ref"],
            "confidence": s["confidence"],
            # NOTE: no segment_uid — backend must backfill from existing entry by (chapter, index, start_ms)
        }
        for s in fixture["entries"][0]["segments"]
    ]

    res = client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps({"full_replace": True, "segments": seg_payload_no_uids, "operations": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 200

    saved = json.loads(
        (tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8")
    )
    post_uids = [s.get("segment_uid", "") for s in saved["entries"][0]["segments"]]
    assert pre_uids == post_uids, (
        f"UIDs drifted across save/reload (MUST-4) — pre={pre_uids!r} post={post_uids!r}"
    )


def test_uid_persisted_on_next_save(tmp_reciter_dir, signed_in_client):
    """Load legacy fixture → save → reload from disk: UIDs are now present in the disk file."""
    reciter = "legacy_reciter"
    legacy_path = tmp_reciter_dir.root / reciter / "detailed.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_doc = {
        "_meta": {"audio_source": "by_surah/fixture"},
        "entries": [
            {
                "ref": "112",
                "segments": [
                    {
                        "time_start": 1000,
                        "time_end": 2000,
                        "matched_ref": "112:1:1-112:1:1",
                        "confidence": 1.0,
                    },
                ],
            }
        ],
    }
    legacy_path.write_text(json.dumps(legacy_doc), encoding="utf-8")
    tmp_reciter_dir.seed_under_review(reciter, "test-user-1")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")

    res = client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps(
            {
                "full_replace": True,
                "segments": [
                    {
                        "time_start": 1000,
                        "time_end": 2000,
                        "matched_ref": "112:1:1-112:1:1",
                        "confidence": 1.0,
                    },
                ],
                "operations": [],
            }
        ),
        headers=_HEADERS,
    )
    assert res.status_code == 200

    on_disk = json.loads(legacy_path.read_text(encoding="utf-8"))
    for seg in on_disk["entries"][0]["segments"]:
        assert seg.get("segment_uid"), "save did not persist backfilled segment_uid"


def test_uid_deterministic_across_processes(tmp_path):
    """Backfill the same legacy fixture in two cold processes; UIDs must match."""
    legacy_dir = tmp_path / "reciters" / "legacy_reciter"
    legacy_dir.mkdir(parents=True)
    legacy_path = legacy_dir / "detailed.json"
    legacy_doc = {
        "_meta": {"audio_source": "by_surah/fixture"},
        "entries": [
            {
                "ref": "112",
                "segments": [
                    {
                        "time_start": 1000,
                        "time_end": 2000,
                        "matched_ref": "112:1:1-112:1:1",
                        "confidence": 1.0,
                    },
                ],
            }
        ],
    }
    legacy_path.write_text(json.dumps(legacy_doc), encoding="utf-8")

    script = textwrap.dedent(
        """
        import json, os, sys
        sys.path.insert(0, os.environ['INSPECTOR_DIR'])
        sys.path.insert(0, os.environ['REPO_ROOT'])
        os.environ['INSPECTOR_BACKEND'] = 'filesystem'
        os.environ['INSPECTOR_FILESYSTEM_ROOT'] = os.environ['DATA_DIR']
        # Cold process: initialise the SQLite substrate like app boot does
        # (load_detailed → repo_state needs the schema present).
        os.environ['INSPECTOR_DB_PATH'] = os.path.join(os.environ['DATA_DIR'], 'inspector.db')
        from services import db
        db.init_db()
        from services.data_loader import load_detailed
        entries = load_detailed('legacy_reciter')
        print(json.dumps([s['segment_uid'] for e in entries for s in e['segments']]))
        """
    )

    import os as _os
    from pathlib import Path as _Path

    repo_inspector = str(_Path(__file__).parent.parent.parent)

    proc1 = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={
            **_os.environ,
            "DATA_DIR": str(tmp_path),
            "INSPECTOR_DIR": repo_inspector,
            "REPO_ROOT": str(_Path(repo_inspector).parent),
        },
    )
    proc2 = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={
            **_os.environ,
            "DATA_DIR": str(tmp_path),
            "INSPECTOR_DIR": repo_inspector,
            "REPO_ROOT": str(_Path(repo_inspector).parent),
        },
    )
    assert proc1.returncode == 0, proc1.stderr
    assert proc2.returncode == 0, proc2.stderr
    assert proc1.stdout.strip() == proc2.stdout.strip(), (
        f"UIDs not deterministic across processes: {proc1.stdout!r} vs {proc2.stdout!r}"
    )
