"""segment_uid stability and backfill tests (MUST-4, IS-8)."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest


def _segments(detailed: dict) -> list[dict]:
    out: list[dict] = []
    for entry in detailed.get("entries", []):
        out.extend(entry.get("segments", []))
    return out


def test_uid_present_in_modern_fixture_unchanged(load_fixture):
    """A modern fixture's UIDs are present and well-formed."""
    fixture = load_fixture("112-ikhlas")
    for seg in _segments(fixture):
        uid = seg.get("segment_uid")
        assert uid, f"modern fixture segment missing segment_uid: {seg}"
        assert isinstance(uid, str)
        assert len(uid) >= 16


@pytest.mark.xfail(reason="phase-4", strict=False)
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
                "audio": "https://fixture.local/audio/112.mp3",
                "segments": [
                    {"time_start": 1000, "time_end": 2000, "matched_ref": "112:1:1-112:1:1", "matched_text": "x", "confidence": 1.0},
                    {"time_start": 3000, "time_end": 4000, "matched_ref": "112:1:2-112:1:2", "matched_text": "y", "confidence": 1.0},
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


@pytest.mark.xfail(reason="phase-4", strict=False)
def test_uid_stable_across_load_save_load(tmp_reciter_dir, flask_client, load_fixture):
    """Load → save (without UIDs in payload) → load: UIDs persist (MUST-4 + IS-8).

    Phase 4 contract: when a save payload lacks `segment_uid` on segments
    (e.g. an older client), the backend looks up the existing UID by
    (chapter, original_index, start_ms) — backfilling deterministically —
    and writes it back to disk. Pre-Phase-4 the save handler trusts the
    payload only, so an empty `segment_uid` zeroes out the on-disk UID.
    """
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    fixture = load_fixture("112-ikhlas")
    chapter = 112

    pre_uids = [s["segment_uid"] for s in fixture["entries"][0]["segments"]]

    seg_payload_no_uids = [
        {
            "time_start": s["time_start"],
            "time_end": s["time_end"],
            "matched_ref": s["matched_ref"],
            "matched_text": s["matched_text"],
            "confidence": s["confidence"],
            "phonemes_asr": s.get("phonemes_asr", ""),
            # NOTE: no segment_uid — Phase 4 backend must backfill from existing
        }
        for s in fixture["entries"][0]["segments"]
    ]

    res = flask_client.post(
        f"/api/seg/save/{reciter}/{chapter}",
        data=json.dumps({"full_replace": True, "segments": seg_payload_no_uids, "operations": []}),
        content_type="application/json",
    )
    assert res.status_code == 200

    saved = json.loads((tmp_reciter_dir.root / reciter / "detailed.json").read_text(encoding="utf-8"))
    post_uids = [s.get("segment_uid", "") for s in saved["entries"][0]["segments"]]
    assert pre_uids == post_uids, (
        f"UIDs drifted across save/reload (MUST-4) — pre={pre_uids!r} post={post_uids!r}"
    )


@pytest.mark.xfail(reason="phase-4", strict=False)
def test_uid_persisted_on_next_save(tmp_reciter_dir, flask_client):
    """Load legacy fixture → save → reload from disk: UIDs are now present in the disk file."""
    reciter = "legacy_reciter"
    legacy_path = tmp_reciter_dir.root / reciter / "detailed.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_doc = {
        "_meta": {"audio_source": "by_surah/fixture"},
        "entries": [
            {
                "ref": "112",
                "audio": "https://fixture.local/audio/112.mp3",
                "segments": [
                    {"time_start": 1000, "time_end": 2000, "matched_ref": "112:1:1-112:1:1", "matched_text": "x", "confidence": 1.0},
                ],
            }
        ],
    }
    legacy_path.write_text(json.dumps(legacy_doc), encoding="utf-8")

    res = flask_client.post(
        f"/api/seg/save/{reciter}/112",
        data=json.dumps({"full_replace": True, "segments": [
            {"time_start": 1000, "time_end": 2000, "matched_ref": "112:1:1-112:1:1", "matched_text": "x", "confidence": 1.0, "phonemes_asr": ""},
        ], "operations": []}),
        content_type="application/json",
    )
    assert res.status_code == 200

    on_disk = json.loads(legacy_path.read_text(encoding="utf-8"))
    for seg in on_disk["entries"][0]["segments"]:
        assert seg.get("segment_uid"), "save did not persist backfilled segment_uid"


@pytest.mark.xfail(reason="phase-4", strict=False)
def test_uid_deterministic_across_processes(tmp_path):
    """Backfill the same legacy fixture in two cold processes; UIDs must match."""
    legacy_dir = tmp_path / "recitation_segments" / "legacy_reciter"
    legacy_dir.mkdir(parents=True)
    legacy_path = legacy_dir / "detailed.json"
    legacy_doc = {
        "_meta": {"audio_source": "by_surah/fixture"},
        "entries": [
            {
                "ref": "112",
                "audio": "https://fixture.local/audio/112.mp3",
                "segments": [
                    {"time_start": 1000, "time_end": 2000, "matched_ref": "112:1:1-112:1:1", "matched_text": "x", "confidence": 1.0},
                ],
            }
        ],
    }
    legacy_path.write_text(json.dumps(legacy_doc), encoding="utf-8")

    script = textwrap.dedent(
        """
        import json, os, sys
        sys.path.insert(0, os.environ['INSPECTOR_DIR'])
        os.environ['INSPECTOR_DATA_DIR'] = os.environ['DATA_DIR']
        from services.data_loader import load_detailed
        entries = load_detailed('legacy_reciter')
        print(json.dumps([s['segment_uid'] for e in entries for s in e['segments']]))
        """
    )

    import os as _os
    inspector_dir = str((tmp_path.parent / "inspector").parent)
    inspector_dir = str((tmp_path / "..").resolve().parent / "inspector")
    real_inspector = str((tmp_path.parent / "inspector").parent / "inspector")
    real_inspector = str((__file__ + "/../../../").replace("\\", "/"))

    repo_inspector = str((tmp_path.parent / "inspector").parent / "inspector")
    repo_inspector = str(__file__).replace("/tests/persistence/test_uid_backfill.py", "")

    proc1 = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True,
        env={**_os.environ, "DATA_DIR": str(tmp_path), "INSPECTOR_DIR": repo_inspector},
    )
    proc2 = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True,
        env={**_os.environ, "DATA_DIR": str(tmp_path), "INSPECTOR_DIR": repo_inspector},
    )
    assert proc1.returncode == 0, proc1.stderr
    assert proc2.returncode == 0, proc2.stderr
    assert proc1.stdout.strip() == proc2.stdout.strip(), (
        f"UIDs not deterministic across processes: {proc1.stdout!r} vs {proc2.stdout!r}"
    )
