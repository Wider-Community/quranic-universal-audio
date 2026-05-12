"""Tiny helpers around environment-resident secrets.

Exists so any future Phase-3+ code path that consumes the secrets seeded by
``scripts/inspector_v2_seed/setup_space.py`` can fail loud rather than
ship the literal placeholder string to a third party.

Phase 2 doesn't read these at runtime (they're staged for Phase 3 and 5),
but the guard ships now so the contract is one import away when Phase 5
wires up `repository_dispatch reciter.completed`.
"""

from __future__ import annotations

import os

DISPATCH_PLACEHOLDER_PREFIX = "PLACEHOLDER_"


class MissingSecret(RuntimeError):
    """Raised when a Phase-3+ secret is absent or still the seed placeholder."""


def get_dispatch_token() -> str:
    """Return ``INSPECTOR_GITHUB_DISPATCH_TOKEN`` after checking it's real.

    ``setup_space.py`` seeds the slot with ``PLACEHOLDER_REPLACE_BEFORE_PHASE_5``
    so the env var exists. Any Phase 5+ caller using this helper avoids
    accidentally posting that literal value as a Bearer token to GitHub.
    """
    raw = os.environ.get("INSPECTOR_GITHUB_DISPATCH_TOKEN", "").strip()
    if not raw:
        raise MissingSecret(
            "INSPECTOR_GITHUB_DISPATCH_TOKEN is unset; mint a fine-grained PAT "
            "(actions:write on the project repo) and update the Space secret."
        )
    if raw.startswith(DISPATCH_PLACEHOLDER_PREFIX):
        raise MissingSecret(
            "INSPECTOR_GITHUB_DISPATCH_TOKEN still holds the Phase 2 placeholder "
            f"({raw[:24]}...). Replace before Phase 5 publish flow ships."
        )
    return raw


def get_session_secret() -> str:
    """Return ``INSPECTOR_SESSION_SECRET`` (Phase 3 cookie signing key).

    Same shape as ``get_dispatch_token`` — Phase 3 imports this when wiring
    Authlib + itsdangerous; raising loud here is better than producing
    cookies signed with an empty key.
    """
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
