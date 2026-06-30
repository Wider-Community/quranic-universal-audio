"""Tests for ``qua_shared.inspector_notify.notify_ts_refreshed``.

The shared best-effort callback fired by backfills / jobs after a bucket-direct
TS shard upload. Verifies it skips when URL/secret are absent, POSTs the right
body + secret header to the right endpoint, and swallows transport errors.
"""

from __future__ import annotations

from qua_shared.inspector_notify import notify_ts_refreshed


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def test_skips_without_url(monkeypatch):
    monkeypatch.delenv("INSPECTOR_URL", raising=False)
    assert notify_ts_refreshed(None, "rec_a", secret="s") is False


def test_skips_without_secret(monkeypatch):
    monkeypatch.delenv("INSPECTOR_WEBHOOK_SECRET", raising=False)
    assert notify_ts_refreshed("https://x.test", "rec_a", secret=None) is False


def test_posts_body_and_secret_header(monkeypatch):
    import requests

    captured: dict = {}

    def _fake_post(url, *, json, headers, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _Resp(200)

    monkeypatch.setattr(requests, "post", _fake_post)
    ok = notify_ts_refreshed(
        "https://x.test/", "rec_a", chapters=[5, 2], reason="backfill_cells", secret="sek"
    )
    assert ok is True
    assert captured["url"] == "https://x.test/api/admin/internal/ts-refreshed"
    assert captured["json"] == {"slug": "rec_a", "reason": "backfill_cells", "chapters": [2, 5]}
    assert captured["headers"]["X-Inspector-Job-Secret"] == "sek"


def test_non_2xx_returns_false(monkeypatch):
    import requests

    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(503))
    assert notify_ts_refreshed("https://x.test", "rec_a", secret="s") is False


def test_swallows_transport_error(monkeypatch):
    import requests

    def _boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "post", _boom)
    # Must never raise into the caller — a failed callback can't fail a backfill.
    assert notify_ts_refreshed("https://x.test", "rec_a", secret="s") is False
