"""OAuth2 authorization_code + PKCE helpers for Quran.Foundation (pre-prod).

Flask-free. The token endpoint requires ``client_secret_basic`` (HTTP Basic);
``client_secret_post`` is rejected by the client (verified live).
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlencode

import requests

from . import config

_TIMEOUT_SECONDS: Final[float] = 10.0


class QfOAuthError(RuntimeError):
    """Raised on token-exchange transport or protocol failure."""


@dataclass(frozen=True)
class PkcePair:
    verifier: str
    challenge: str


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def new_pkce() -> PkcePair:
    verifier = _b64url(os.urandom(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return PkcePair(verifier=verifier, challenge=challenge)


def new_state() -> str:
    return secrets.token_urlsafe(24)


def build_authorize_url(*, state: str, nonce: str, code_challenge: str) -> str:
    params = {
        "client_id": config.preprod_client_id(),
        "response_type": "code",
        "redirect_uri": config.redirect_uri(),
        "scope": config.USER_API_SCOPE,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{config.PREPROD_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code(*, code: str, code_verifier: str) -> dict:
    """Exchange an authorization code for tokens. Returns the token dict
    (``access_token``, ``refresh_token``, ``expires_in``, ...)."""
    return _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_uri(),
            "code_verifier": code_verifier,
        }
    )


def refresh(refresh_token: str) -> dict:
    return _token_request(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}
    )


def _token_request(body: dict) -> dict:
    cid, secret = config.preprod_client_id(), config.preprod_client_secret()
    if not cid or not secret:
        raise QfOAuthError("QF pre-prod client credentials are not configured")
    try:
        resp = requests.post(
            config.PREPROD_TOKEN_URL,
            data=body,
            auth=(cid, secret),  # client_secret_basic
            headers={"Accept": "application/json"},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise QfOAuthError(f"QF token request failed: {e}") from e
    if not resp.ok:
        raise QfOAuthError(
            f"QF token request {resp.status_code}: {resp.text[:200]}"
        )
    return resp.json()
