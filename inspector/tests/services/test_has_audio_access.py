"""``has_audio_access`` — the looser gate for the audio surfaces.

Dashboard footer plays any catalogued delivery (CDN stream-through), so the
audio routes must not require a reviewable lifecycle state the way
``has_content_access`` does. Discarded (no catalog row) and hidden
(EveryAyah for non-owners) deliveries still 404.
"""

from types import SimpleNamespace

from services.state import catalog as catalog_mod
from services.state import state


def test_catalogued_delivery_has_audio_access(monkeypatch):
    monkeypatch.setattr(state, "is_delivery_visible", lambda slug, viewer=None: True)
    monkeypatch.setattr(catalog_mod, "find_delivery", lambda slug: SimpleNamespace(slug=slug))
    assert state.has_audio_access("some_catalogued_slug") is True


def test_unknown_delivery_has_no_audio_access(monkeypatch):
    monkeypatch.setattr(state, "is_delivery_visible", lambda slug, viewer=None: True)
    monkeypatch.setattr(catalog_mod, "find_delivery", lambda slug: None)
    assert state.has_audio_access("discarded_slug") is False


def test_hidden_delivery_has_no_audio_access(monkeypatch):
    monkeypatch.setattr(state, "is_delivery_visible", lambda slug, viewer=None: False)
    monkeypatch.setattr(catalog_mod, "find_delivery", lambda slug: SimpleNamespace(slug=slug))
    assert state.has_audio_access("everyayah_slug") is False


def test_sample_namespace_always_has_audio_access():
    assert state.has_audio_access("sample--x") is True
