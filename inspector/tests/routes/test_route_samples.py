"""HTTP boundary tests for ``/api/samples`` and the sample edit gate.

ffmpeg/ffprobe are stubbed (the upload is copied through as-is, the probe is
canned, peaks are a no-op) and the ingest thread runs inline so the row is
``ready`` when the upload returns.
"""

from __future__ import annotations

import json
from io import BytesIO

import pytest

_ORIGIN = {"Origin": "http://localhost"}
_JSON = {"Content-Type": "application/json", "Origin": "http://localhost"}


def _alignment() -> dict:
    return {
        "segments": [
            {
                "id": 0,
                "region": {"start_s": 0.5, "end_s": 2.0},
                "kind": "quran",
                "matched_ref": "2:1:1-2:2:3",
                "matched_text": "x",
                "confidence": 0.95,
                "findings": [],
            },
            {
                "id": 1,
                "region": {"start_s": 2.0, "end_s": 3.5},
                "kind": "quran",
                "matched_ref": "2:2:4-2:3:1",
                "matched_text": "y",
                "confidence": 0.4,
                "findings": [],
            },
        ],
        "chapter": None,
    }


@pytest.fixture
def stub_ingest(monkeypatch):
    """Replace ffmpeg-backed steps and run the peaks thread inline."""
    from services import samples as samples_service
    from services.samples import audio_ingest

    monkeypatch.setattr(
        audio_ingest, "normalize_to_mp3", lambda src, dst: dst.write_bytes(src.read_bytes())
    )
    monkeypatch.setattr(
        audio_ingest,
        "probe",
        lambda path: {"duration_ms": 4000, "bitrate_kbps": 128, "format": "mp3"},
    )
    monkeypatch.setattr(audio_ingest, "bake_peaks", lambda mp3, slug, ch: None)

    monkeypatch.setattr(samples_service, "_spawn", lambda target, args: target(*args))
    return samples_service


def _upload(client, name="My sample", alignment=None):
    doc = alignment if alignment is not None else _alignment()
    return client.post(
        "/api/samples",
        data={
            "name": name,
            "audio": (BytesIO(b"ID3fakeaudio"), "take1.mp3"),
            "source": (BytesIO(json.dumps(doc).encode()), "aln.json"),
        },
        content_type="multipart/form-data",
        headers=_ORIGIN,
    )


def test_anonymous_and_contributor_are_refused(flask_client, signed_in_client, tmp_reciter_dir):
    assert flask_client.get("/api/samples").status_code == 401
    client, _ = signed_in_client(role="contributor")
    assert client.get("/api/samples").status_code == 403
    assert _upload(client).status_code == 403


def test_upload_lists_and_serves_through_seg_routes(signed_in_client, tmp_reciter_dir, stub_ingest):
    client, _ = signed_in_client(role="maintainer")
    resp = _upload(client)
    assert resp.status_code == 201, resp.get_data(as_text=True)
    row = resp.get_json()
    assert row["status"] == "ready" and row["pseudo_chapter"] == 2
    assert row["slug"] == f"sample--{row['id']}"
    assert row["can_manage"] is True and row["changed_since_export"] is False

    listed = client.get("/api/samples").get_json()["samples"]
    assert [s["id"] for s in listed] == [row["id"]]

    slug = row["slug"]
    all_resp = client.get(f"/api/seg/all/{slug}")
    assert all_resp.status_code == 200
    body = all_resp.get_json()
    assert len(body["segments"]) == 2 and body["segments"][0]["chapter"] == 2
    assert body["audio_by_chapter"] == {"2": f"qua-sample://{row['id']}/2"}
    assert body["chapter_duration_ms_by_chapter"] == {"2": 4000}
    assert client.get(f"/api/seg/validate/{slug}").status_code == 200
    assert client.get(f"/api/seg/data/{slug}/2").status_code == 200

    other, _ = signed_in_client(hf_user_id="test-user-2", login="second", role="maintainer")
    other_view = other.get("/api/samples").get_json()["samples"][0]
    assert other_view["can_manage"] is False


def test_rejects_bad_json_and_bad_audio_extension(signed_in_client, tmp_reciter_dir, stub_ingest):
    client, _ = signed_in_client(role="maintainer")
    assert _upload(client, alignment={"nope": 1}).status_code == 400
    resp = client.post(
        "/api/samples",
        data={
            "name": "x",
            "audio": (BytesIO(b"x"), "take1.txt"),
            "source": (BytesIO(b"{}"), "a.json"),
        },
        content_type="multipart/form-data",
        headers=_ORIGIN,
    )
    assert resp.status_code == 400


def test_rename_and_delete_are_owner_scoped(signed_in_client, tmp_reciter_dir, stub_ingest):
    client, _ = signed_in_client(role="maintainer")
    sid = _upload(client).get_json()["id"]

    other, _ = signed_in_client(hf_user_id="test-user-2", login="second", role="maintainer")
    assert (
        other.patch(f"/api/samples/{sid}", json={"name": "nope"}, headers=_JSON).status_code == 403
    )
    assert other.delete(f"/api/samples/{sid}", headers=_ORIGIN).status_code == 403

    boss, _ = signed_in_client(hf_user_id="test-owner", login="boss", role="owner")
    renamed = boss.patch(f"/api/samples/{sid}", json={"name": "Renamed"}, headers=_JSON)
    assert renamed.status_code == 200 and renamed.get_json()["name"] == "Renamed"

    assert client.delete(f"/api/samples/{sid}", headers=_ORIGIN).status_code == 204
    assert client.get(f"/api/seg/all/sample--{sid}").status_code == 404
    assert client.get(f"/api/samples/{sid}/export").status_code == 404


def test_save_via_seg_route_flags_export_then_export_clears(
    signed_in_client, tmp_reciter_dir, stub_ingest
):
    client, _ = signed_in_client(role="maintainer")
    row = _upload(client).get_json()
    slug, sid = row["slug"], row["id"]

    segs = client.get(f"/api/seg/all/{slug}").get_json()["segments"]
    payload = {
        "segments": [{"index": 1, "matched_ref": "2:2:4-2:3:1", "confidence": 0.7}],
        "operations": [],
    }
    saved = client.post(f"/api/seg/save/{slug}/2", json=payload, headers=_JSON)
    assert saved.status_code == 200, saved.get_data(as_text=True)

    listed = client.get("/api/samples").get_json()["samples"][0]
    assert listed["changed_since_export"] is True and listed["last_save_at"]

    exported = client.get(f"/api/samples/{sid}/export")
    assert exported.status_code == 200
    assert exported.headers["Content-Disposition"].endswith('.alignment.json"')
    doc = exported.get_json()
    assert doc["chapter"] == 2
    by_id = {s["id"]: s for s in doc["segments"]}
    assert by_id[1]["confidence"] == pytest.approx(0.7)
    assert by_id[0]["region"] == {"start_s": 0.5, "end_s": 2.0}
    assert segs[0]["segment_uid"]

    assert client.get("/api/samples").get_json()["samples"][0]["changed_since_export"] is False

    contrib, _ = signed_in_client(hf_user_id="c1", login="c", role="contributor")
    assert contrib.post(f"/api/seg/save/{slug}/2", json=payload, headers=_JSON).status_code == 403


def test_word_timings_surface_on_all_and_survive_a_structural_save(
    signed_in_client, tmp_reciter_dir, stub_ingest
):
    client, _ = signed_in_client(role="maintainer")
    doc = _alignment()
    doc["segments"][0]["words"] = [{"word": "w", "location": "2:1:1", "start": 0.1, "end": 0.6}]
    row = _upload(client, alignment=doc).get_json()
    slug = row["slug"]
    seg = client.get(f"/api/seg/all/{slug}").get_json()["segments"][0]
    timings = [{"word": "w", "location": "2:1:1", "start_ms": 600, "end_ms": 1100}]
    assert seg["word_timings"] == timings

    # Structural save with the key present is authoritative; without it the
    # existing timings are inherited.
    payload = {
        "full_replace": True,
        "segments": [{
            "segment_uid": seg["segment_uid"],
            "time_start": seg["time_start"],
            "time_end": seg["time_end"],
            "matched_ref": seg["matched_ref"],
            "confidence": 1.0,
            "audio_url": "",
            "ignored_categories": [],
        }],
        "operations": [],
    }
    assert client.post(f"/api/seg/save/{slug}/2", json=payload, headers=_ORIGIN).status_code == 200
    assert client.get(f"/api/seg/all/{slug}").get_json()["segments"][0]["word_timings"] == timings
    payload["segments"][0]["word_timings"] = None
    assert client.post(f"/api/seg/save/{slug}/2", json=payload, headers=_ORIGIN).status_code == 200
    assert "word_timings" not in client.get(f"/api/seg/all/{slug}").get_json()["segments"][0]


def test_realign_returns_space_words_as_absolute_ms(
    signed_in_client, tmp_reciter_dir, stub_ingest, monkeypatch
):
    from services.admin import ts_space_client

    client, _ = signed_in_client(role="maintainer")
    row = _upload(client).get_json()
    calls = []

    def fake_align(**kw):
        calls.append(kw)
        return {"ref": kw["ref"], "status": "ok",
                "words": [{"location": "2:1:1", "text": "x", "start": 0.25, "end": 0.9}]}

    monkeypatch.setattr(ts_space_client, "align_item", fake_align)
    body = {"segment_uid": "u", "matched_ref": "2:1:1-2:1:2", "time_start": 500, "time_end": 2000}
    resp = client.post(f"/api/samples/{row['id']}/realign", json=body, headers=_ORIGIN)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()["word_timings"] == [
        {"word": "x", "location": "2:1:1", "start_ms": 750, "end_ms": 1400}
    ]
    assert calls[0]["path"].endswith(f"samples/{row['id']}/audio/2.mp3")
    assert (calls[0]["ref"], calls[0]["start_ms"], calls[0]["end_ms"]) == ("2:1:1-2:1:2", 500, 2000)
    assert client.post(
        f"/api/samples/{row['id']}/realign", json={**body, "matched_ref": "Basmala"}, headers=_ORIGIN
    ).status_code == 409
    assert client.post(
        "/api/samples/nope/realign", json=body, headers=_ORIGIN
    ).status_code == 404


def test_wbw_tag_tracks_coverage_and_review_clears_on_save(
    signed_in_client, tmp_reciter_dir, stub_ingest
):
    client, _ = signed_in_client(role="maintainer")
    doc = _alignment()
    doc["segments"][0]["matched_ref"] = "2:1:1-2:1:2"
    doc["segments"][0]["words"] = [
        {"word": "a", "location": "2:1:1", "start": 0.1, "end": 0.4},
    ]
    row = _upload(client, alignment=doc).get_json()
    assert row["wbw_complete"] is False

    # Complete the coverage through the ordinary save path.
    slug = row["slug"]
    seg = client.get(f"/api/seg/all/{slug}").get_json()["segments"][0]
    payload = {
        "full_replace": True,
        "segments": [{
            "segment_uid": seg["segment_uid"],
            "time_start": seg["time_start"],
            "time_end": seg["time_end"],
            "matched_ref": seg["matched_ref"],
            "confidence": 1.0,
            "audio_url": "",
            "ignored_categories": [],
            "word_timings": [
                {"word": "a", "location": "2:1:1", "start_ms": 600, "end_ms": 900},
                {"word": "b", "location": "2:1:2", "start_ms": 900, "end_ms": 1400},
            ],
        }],
        "operations": [],
    }
    assert client.post(f"/api/seg/save/{slug}/2", json=payload, headers=_ORIGIN).status_code == 200

    reviewed = client.post(
        f"/api/samples/{row['id']}/review", json={"reviewed": True}, headers=_ORIGIN
    ).get_json()
    assert reviewed["wbw_complete"] is True
    assert reviewed["reviewed_at"] and reviewed["reviewed_by_login"]

    # Any later save drops the sign-off.
    assert client.post(f"/api/seg/save/{slug}/2", json=payload, headers=_ORIGIN).status_code == 200
    after = client.get("/api/samples").get_json()["samples"][0]
    assert after["reviewed_at"] is None and after["wbw_complete"] is True

    assert client.post(
        "/api/samples/nope/review", json={"reviewed": True}, headers=_ORIGIN
    ).status_code == 404
