"""Thin HF API proxy for ``login -> hf_user_id`` resolution.

Used by ``/api/admin/users/lookup`` + the reassign route to canonicalize
free-text login input before persisting an assignee. Anonymous GET — HF's
``/api/users/<login>/overview`` is public.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import requests


_BASE_URL: Final[str] = "https://huggingface.co/api/users"
_TIMEOUT_SECONDS: Final[float] = 5.0


class HfUserLookupError(RuntimeError):
    """Raised on transport-level failure (timeout, DNS, 5xx)."""


@dataclass(frozen=True)
class HfUser:
    hf_user_id: str
    login: str
    fullname: str | None
    avatar_url: str | None


def lookup(login: str) -> HfUser | None:
    """Return parsed user or ``None`` if HF returns 404. Raises
    ``HfUserLookupError`` on transport failure.
    """
    login = (login or "").strip()
    if not login:
        return None
    url = f"{_BASE_URL}/{login}/overview"
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise HfUserLookupError(f"HF user lookup failed: {e}") from e
    if resp.status_code == 404:
        return None
    if resp.status_code >= 500:
        raise HfUserLookupError(f"HF user lookup 5xx: {resp.status_code}")
    if not resp.ok:
        raise HfUserLookupError(
            f"HF user lookup unexpected status {resp.status_code}"
        )
    body = resp.json()
    hf_user_id = body.get("id") or body.get("_id")
    canonical_login = body.get("user") or body.get("name") or login
    if not hf_user_id:
        raise HfUserLookupError("HF user lookup response missing id")
    return HfUser(
        hf_user_id=str(hf_user_id),
        login=str(canonical_login),
        fullname=body.get("fullname"),
        avatar_url=body.get("avatarUrl"),
    )
