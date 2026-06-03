"""Bearer-token OWNER authorization for server-to-server endpoints.

The offline extraction/ingest client authenticates with its HF token (the same
``HF_TOKEN`` it already uses for bucket access) rather than a browser session
cookie. This module resolves that bearer token to an ``hf_user_id`` via
``huggingface_hub.whoami`` and gates on :data:`Role.OWNER`.

Identity mapping (verified): OAuth stores ``hf_user_id = userinfo["sub"]``
(``routes/auth/auth.py``), and the HF user API returns that same id as
``body["id"]`` / ``body["_id"]`` (``services/auth/hf_users.py``). So
``whoami(token)["id"]`` (fallback ``["_id"]``) is the canonical
``hf_user_id`` we can hand straight to :func:`access.resolve_role`.

**Fail closed.** Any transport / parse / auth error resolving the token raises
:class:`TokenAuthError` — the caller maps it to 401 and NEVER falls through to
an authenticated identity. A successful resolution that isn't OWNER raises
:class:`NotOwner` → 403.

The token→id lookup is short-TTL cached (whoami is a network round-trip and a
batch ingest hits the endpoint once per chapter-upload step) — the cache holds
the *id only*, never the role (roles are resolved fresh from the DB on every
call, mirroring the cookie path's live-role contract).
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time

from qua_shared.schemas import Actor, Role

from . import access

logger = logging.getLogger(__name__)


# whoami is a cheap-but-not-free network call; a batch ingest authorizes once
# per HTTP request. A 5-minute id cache absorbs the repeat lookups within a run
# without ever caching the (mutable) role. Keyed on a SHA-256 of the token (never
# the raw secret in memory); expired entries are purged on insert and the dict is
# hard-capped as a backstop so it can't grow unbounded.
_TOKEN_TTL_SECONDS: float = 300.0
_TOKEN_CACHE_MAX: int = 256
_token_cache: dict[str, tuple[float, tuple[str, str]]] = {}
_token_cache_lock = threading.Lock()


def _token_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenAuthError(Exception):
    """The bearer token could not be resolved to an HF identity (→ 401).

    Covers a missing/blank token, any ``whoami`` transport error, and a
    response missing an id. Fail-closed: the caller must reject, never bypass.
    """


class NotOwner(Exception):
    """The token resolved to a real HF user who is not an OWNER (→ 403)."""


def _whoami_identity(token: str) -> tuple[str, str]:
    """Resolve a bearer token to ``(hf_user_id, login)`` via HF ``whoami``.

    Cached for :data:`_TOKEN_TTL_SECONDS`. Raises :class:`TokenAuthError` on any
    failure (fail closed)."""
    now = time.time()
    key = _token_key(token)
    with _token_cache_lock:
        hit = _token_cache.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]

    try:
        from huggingface_hub import whoami as _whoami
    except Exception as e:  # noqa: BLE001 — import error must not bypass auth
        raise TokenAuthError(f"huggingface_hub unavailable: {e}") from e

    try:
        info = _whoami(token=token)
    except Exception as e:  # noqa: BLE001 — any transport/auth error → reject
        raise TokenAuthError(f"whoami failed: {type(e).__name__}") from e

    if not isinstance(info, dict):
        raise TokenAuthError("whoami returned a non-dict response")
    hf_user_id = info.get("id") or info.get("_id")
    if not hf_user_id:
        raise TokenAuthError("whoami response missing id")
    login = info.get("name") or info.get("user") or info.get("fullname") or str(hf_user_id)
    identity = (str(hf_user_id), str(login))

    with _token_cache_lock:
        if len(_token_cache) >= _TOKEN_CACHE_MAX:
            for k in [k for k, (exp, _) in _token_cache.items() if exp <= now]:
                _token_cache.pop(k, None)
            if len(_token_cache) >= _TOKEN_CACHE_MAX:
                _token_cache.clear()  # backstop — unreachable at real token counts
        _token_cache[key] = (now + _TOKEN_TTL_SECONDS, identity)
    return identity


def resolve_owner_from_token(token: str | None) -> Actor:
    """Resolve a bearer token to an OWNER :class:`Actor`, or raise.

    - Blank/missing token → :class:`TokenAuthError` (401).
    - ``whoami`` failure / missing id → :class:`TokenAuthError` (401).
    - Resolved user is not OWNER → :class:`NotOwner` (403).

    Role is resolved fresh from the DB on every call (the cache holds the id
    only) — a demoted owner loses access on the next request without a re-login,
    matching the cookie path's live-role contract.
    """
    tok = (token or "").strip()
    if not tok:
        raise TokenAuthError("missing bearer token")
    hf_user_id, login = _whoami_identity(tok)
    # ``resolve_role`` returns a ``Role`` (CONTRIBUTOR for non-members); the
    # ``Role(...)`` wrap is defensive normalization, idempotent on a Role.
    role = Role(access.resolve_role(hf_user_id))
    if role != Role.OWNER:
        raise NotOwner(
            f"hf_user_id {hf_user_id!r} resolved role {role.value!r}; OWNER required"
        )
    return Actor(hf_user_id=hf_user_id, login_at_time=login, role=Role.OWNER)


def bearer_token_from_header(authorization: str | None) -> str | None:
    """Extract the token from an ``Authorization: Bearer <token>`` header value.

    Returns ``None`` when the header is absent or not a Bearer scheme."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _clear_cache_for_test() -> None:
    with _token_cache_lock:
        _token_cache.clear()


__all__ = [
    "NotOwner",
    "TokenAuthError",
    "bearer_token_from_header",
    "resolve_owner_from_token",
]
