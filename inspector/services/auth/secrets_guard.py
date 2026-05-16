"""Typed accessors for secrets seeded by ``setup_space.py``.

Routes the secret through a guard that raises ``MissingSecret`` when the
slot is unset, holds a placeholder, or is below the entropy floor — so a
caller never quietly ships ``Bearer PLACEHOLDER_…`` to a third party or
signs cookies with an empty key.
"""

from __future__ import annotations

import os

DISPATCH_PLACEHOLDER_PREFIX = "PLACEHOLDER_"


class MissingSecret(RuntimeError):
    """Raised when a secret is absent or still the seed placeholder."""


def get_dispatch_token() -> str:
    """Return ``INSPECTOR_GITHUB_DISPATCH_TOKEN`` after checking it's real."""
    raw = os.environ.get("INSPECTOR_GITHUB_DISPATCH_TOKEN", "").strip()
    if not raw:
        raise MissingSecret(
            "INSPECTOR_GITHUB_DISPATCH_TOKEN is unset; mint a fine-grained PAT "
            "(actions:write on the project repo) and update the Space secret."
        )
    if raw.startswith(DISPATCH_PLACEHOLDER_PREFIX):
        raise MissingSecret(
            "INSPECTOR_GITHUB_DISPATCH_TOKEN still holds the seed placeholder "
            f"({raw[:24]}...). Replace it with a real token."
        )
    return raw


def get_session_secret() -> str:
    """Return ``INSPECTOR_SESSION_SECRET``; reject unset / under-length values."""
    raw = os.environ.get("INSPECTOR_SESSION_SECRET", "").strip()
    if not raw:
        raise MissingSecret(
            "INSPECTOR_SESSION_SECRET is unset; auto-seed via "
            "`python -m scripts.inspector_v2_seed.setup_space dev --apply` or "
            "set it manually in Space secrets."
        )
    if len(raw) < 32:
        raise MissingSecret(
            f"INSPECTOR_SESSION_SECRET is too short (len={len(raw)}); expected "
            "≥32 hex chars (16+ bytes of entropy)."
        )
    return raw
