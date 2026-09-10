"""``services.admin.ts_space_client`` — the signed timestamps-run request.

The Space verifies an HMAC over a JCS digest of the body, so the exact bytes of
the canonical form are the contract. These tests pin that form, and in
particular that adding multi-riwayah support did NOT change the Hafs preimage:
the field is omitted for Hafs, so every existing Hafs run signs exactly as
before and the Space-side change can ship on its own schedule.
"""

from __future__ import annotations

import pytest

from services.admin import ts_space_client


@pytest.fixture
def posted(monkeypatch):
    """Capture the body ``start_run`` posts, without touching the network."""
    monkeypatch.setenv("INSPECTOR_TS_ENGINE_SECRET", "ab" * 32)
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "get_token", lambda: None)

    captured: dict = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"run_id": "run-1"}

    import requests

    def fake_post(url, data=None, headers=None, timeout=None):
        captured["raw"] = data
        captured["headers"] = headers
        return _Resp()

    monkeypatch.setattr(requests, "post", fake_post)
    return captured


def _body(captured: dict) -> dict:
    import json

    return json.loads(captured["raw"].decode("utf-8"))


def test_a_hafs_run_carries_no_riwayah_field(posted):
    ts_space_client.start_run("some-reciter", chapters=[108], beams=[50, 5])
    assert "riwayah" not in _body(posted)


def test_the_hafs_canonical_preimage_is_unchanged(posted):
    ts_space_client.start_run("some-reciter", chapters=[108], beams=[50, 5])
    assert ts_space_client._canonical(_body(posted)) == (
        '{"beams":[50,5],"chapters":[108],'
        '"profile_id":"timing.timestamps@v1","schema_version":1,'
        '"slug":"some-reciter"}'
    )


def test_a_non_hafs_run_names_its_edition_in_sorted_position(posted):
    ts_space_client.start_run("some-reciter", chapters=[108], riwayah="warsh")
    body = _body(posted)
    assert body["riwayah"] == "warsh"
    # JCS sorts keys, so `riwayah` lands between `profile_id` and
    # `schema_version` — the Space canonicalises the same way or the HMAC fails.
    assert ts_space_client._canonical(body) == (
        '{"chapters":[108],"profile_id":"timing.timestamps@v1",'
        '"riwayah":"warsh","schema_version":1,"slug":"some-reciter"}'
    )


def test_a_float_in_the_body_fails_closed():
    """A schema drift must break the signer, not sign a wrong preimage."""
    with pytest.raises(TypeError):
        ts_space_client._canonical({"beams": [1.5]})
