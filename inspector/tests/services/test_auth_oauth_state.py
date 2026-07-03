"""OAuth state is held server-side, never in the Flask session cookie.

On HF Spaces the app runs inside a cross-site huggingface.co iframe where the
Flask session cookie is third-party and Safari's ITP drops it. Authlib's stock
integration keeps an ``exp`` marker in the session even when a cache is wired
up, so the callback raised ``MismatchingStateError`` whenever that cookie
failed to round-trip. These tests pin the cookie-free state store and the
return-path helpers that replaced the session.
"""

from __future__ import annotations


def test_state_round_trip_needs_no_session():
    """set/get/clear work with ``session=None`` — proving the session is never
    touched. The stock integration would raise on ``None.get(...)``."""
    from services.auth.auth import _CacheStateIntegration, _TTLCache

    integ = _CacheStateIntegration("huggingface", _TTLCache())
    data = {"redirect_uri": "https://space.hf.space/api/auth/callback", "nonce": "n-1"}

    integ.set_state_data(None, "state-xyz", data)
    assert integ.get_state_data(None, "state-xyz") == data

    integ.clear_state_data(None, "state-xyz")
    assert integ.get_state_data(None, "state-xyz") is None


def test_get_state_data_with_empty_state_is_none():
    from services.auth.auth import _CacheStateIntegration, _TTLCache

    integ = _CacheStateIntegration("huggingface", _TTLCache())
    assert integ.get_state_data(None, None) is None
    assert integ.get_state_data(None, "") is None


def test_return_path_round_trip_is_single_use():
    from services.auth import auth as auth_service

    auth_service.remember_return_path("state-ret-1", "/segments/foo")
    assert auth_service.pop_return_path("state-ret-1") == "/segments/foo"
    # Consumed on first read so a replayed callback can't reuse it.
    assert auth_service.pop_return_path("state-ret-1") is None


def test_pop_return_path_handles_missing_and_none():
    from services.auth import auth as auth_service

    assert auth_service.pop_return_path(None) is None
    assert auth_service.pop_return_path("never-set") is None


def test_popup_flag_round_trip_is_single_use():
    """The popup marker (embedded-iframe sign-in) round-trips and is consumed on
    first read so a replayed callback can't re-trigger the close-window path."""
    from services.auth import auth as auth_service

    auth_service.remember_popup("state-popup-1")
    assert auth_service.pop_popup("state-popup-1") is True
    assert auth_service.pop_popup("state-popup-1") is False


def test_pop_popup_defaults_false_for_missing_and_none():
    """An ordinary (non-popup) sign-in never set the flag → callback redirects."""
    from services.auth import auth as auth_service

    assert auth_service.pop_popup(None) is False
    assert auth_service.pop_popup("never-set-popup") is False
