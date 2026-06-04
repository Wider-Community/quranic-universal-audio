"""Shared ``model_validator(mode='before')`` helpers for warn-on-extras.

Replaces silent ``extra="allow"`` with a two-tier warning surface:

1. ``DEAD_FIELDS`` — known-legacy keys that pre-date a migration. Stripped
   on read with an INFO-level message ("legacy field stripped"). Writers
   MUST NOT emit them; readers tolerate them so legacy on-disk data still
   parses while the migration backfill runs.

2. Anything else not in the model's declared field set — WARNING-level
   ("unrecognized field stripped"). Surfaces drift between writer and
   schema, which is the whole point of the migration #5 single-source-of-
   truth refactor.

After the pre-validator strips both classes, the model itself can run with
``extra="forbid"`` so subsequent code paths see a clean shape (no surprise
attributes from absorbed extras).

Tests live alongside the schemas (``qua_shared/schemas/smoke.py``).
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)


def strip_and_warn(
    data: Any,
    *,
    declared: set[str],
    dead: set[str],
    model_name: str,
) -> Any:
    """Strip dead + unknown keys with appropriate log severity.

    Idempotent: re-running on already-cleaned data is a no-op.

    Returns a new dict with only declared keys (or the input unchanged when
    ``data`` isn't a dict — pydantic handles the error in that case).
    """
    if not isinstance(data, dict):
        return data

    cleaned: dict[str, Any] = {}
    extras_dead: list[str] = []
    extras_unknown: list[str] = []

    for k, v in data.items():
        if k in declared:
            cleaned[k] = v
        elif k in dead:
            extras_dead.append(k)
        else:
            extras_unknown.append(k)

    if extras_dead:
        _log.info(
            "%s: stripped legacy field(s) %s — writers must not emit these",
            model_name,
            sorted(extras_dead),
        )
    if extras_unknown:
        _log.warning(
            "%s: stripped UNRECOGNIZED field(s) %s — schema is out of date "
            "or writer is emitting bloat",
            model_name,
            sorted(extras_unknown),
        )

    return cleaned
