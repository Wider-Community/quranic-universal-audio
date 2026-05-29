"""Dev-only accordion-guide example flagging store.

Local scratch queue of edit-history ops the maintainer flags while browsing
the History panel, for later conversion into accordion-guide examples (see
``docs/reference/accordion-guides.md``). Persisted as JSONL at
``config.GUIDE_FLAGS_PATH`` (under the gitignored ``.local/``) — never the
bucket, never git.

Paired surfaces:
  - Routes: dev-only ``POST/GET/DELETE /api/dev/guide-flag(s)`` in
    ``routes/auth/dev.py`` (404 when dev mode is off → zero prod surface).
  - Builder: ``inspector/scripts/build_guide_examples_from_flags.py`` (offline)
    resolves each flag against the bucket — pulls the op from
    ``edit_history.jsonl``, the waveform from ``edit_history_peaks.jsonl``, and
    cuts a standalone audio clip — then emits a draft ``GuideExample`` record.

This is authoring infrastructure between the maintainer and the agent; it is
deliberately schema-light (a flat dict, not a shared ``scripts/lib/schemas``
model) because nothing round-trips it through the pipeline.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import config

logger = logging.getLogger(__name__)

_REQUIRED = ("reciter", "batch_id", "op_ids", "category")
_VALID_RENDER = ("history_op", "edit_chain")


class GuideFlagError(ValueError):
    """Raised when a flag payload is missing or malforms a required field."""


def _validate(payload: dict[str, Any]) -> None:
    missing = [k for k in _REQUIRED if not payload.get(k)]
    if missing:
        raise GuideFlagError(f"missing required field(s): {', '.join(missing)}")
    op_ids = payload.get("op_ids")
    if not isinstance(op_ids, list) or not op_ids or not all(
        isinstance(x, str) and x for x in op_ids
    ):
        raise GuideFlagError("op_ids must be a non-empty list of strings")


def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
    """Whitelist + coerce the persisted fields; drop everything else."""
    chapter = payload.get("chapter")
    render = str(payload.get("render") or "history_op")
    if render not in _VALID_RENDER:
        render = "history_op"
    note = str(payload.get("note") or "").strip()
    example_id = str(payload.get("example_id") or "").strip()
    return {
        "reciter": str(payload["reciter"]),
        "chapter": int(chapter) if chapter is not None else None,
        "batch_id": str(payload["batch_id"]),
        "op_ids": [str(x) for x in payload["op_ids"]],
        "op_type": str(payload["op_type"]) if payload.get("op_type") else None,
        "matched_ref": str(payload["matched_ref"]) if payload.get("matched_ref") else None,
        "category": str(payload["category"]),
        "render": render,
        "note": note or None,
        "example_id": example_id or None,
        "flagged_by": str(payload["flagged_by"]) if payload.get("flagged_by") else None,
    }


def load_flags() -> list[dict[str, Any]]:
    """Return all flags, oldest-first. Tolerates a missing/empty file and skips
    malformed lines (logged, never fatal)."""
    path = config.GUIDE_FLAGS_PATH
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("guide_flags: skipping malformed line %d in %s", i + 1, path)
    return out


def append_flag(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate, stamp (``flag_id`` + ``flagged_at_utc``), append one flag.

    Returns the stored record. Raises ``GuideFlagError`` on a bad payload.
    """
    _validate(payload)
    record = _normalize(payload)
    record["flag_id"] = uuid.uuid4().hex
    record["flagged_at_utc"] = datetime.now(timezone.utc).isoformat()

    path = config.GUIDE_FLAGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info(
        "guide_flags: flagged %s ch%s batch=%s ops=%d category=%s",
        record["reciter"], record["chapter"], record["batch_id"],
        len(record["op_ids"]), record["category"],
    )
    return record


def delete_flag(flag_id: str) -> bool:
    """Remove the flag with ``flag_id``; rewrite the file. Returns True if one
    was removed (small dev-scratch dataset — full rewrite, no tombstones)."""
    flags = load_flags()
    kept = [f for f in flags if f.get("flag_id") != flag_id]
    if len(kept) == len(flags):
        return False
    path = config.GUIDE_FLAGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in kept),
        encoding="utf-8",
    )
    return True
