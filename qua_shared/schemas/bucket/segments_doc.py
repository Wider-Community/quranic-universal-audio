"""Per-reciter ``segments.json`` schema — verse-aggregated bucket artefact.

The verse-keyed companion to ``detailed.json``: a flat map of
``"<surah>:<ayah>" -> [row, ...]`` plus a ``_meta`` block, rebuilt by the
Inspector save flow (``services/segments/save.py``) and structurally audited
by ``inspector/services/storage/bucket_audit.py::_audit_segments``.

This is a BACKEND-ONLY artefact (the FE never fetches it), so it is modelled
for VALIDATION only — it is NOT re-exported via ``fe_types.py`` and never
codegen'd to TypeScript.

Document shape::

    {
      "_meta": {...arbitrary provenance...},
      "1:1": [[w_start, w_end, ms_start, ms_end], ...],
      "1:2": [[w_start, w_end, ms_start, ms_end, {"repeated": [...]}], ...],
      ...
    }

Each row is ``[w_start, w_end, ms_start, ms_end]`` (four ints in word/ms
order, ``ms_end >= ms_start``) with an optional trailing dict carrying
per-row annotations (e.g. ``{"repeated": [...]}``). The dynamic verse keys
preclude a plain field model, so the document is a ``RootModel`` over the
raw dict with an ``after`` validator that range-checks every row.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import RootModel, model_validator

_VERSE_KEY_RE = re.compile(r"^[1-9]\d{0,2}:[1-9]\d{0,2}$")


def _is_int(v: Any) -> bool:
    """True for a real int (bools are ints in Python — exclude them)."""
    return isinstance(v, int) and not isinstance(v, bool)


class SegmentsDoc(RootModel[dict[str, Any]]):
    """Whole ``segments.json`` document, keyed by verse ref + ``_meta``.

    Validation mirrors ``_audit_segments``: ``_meta`` must be a dict when
    present; every other key is a ``"<surah>:<ayah>"`` verse ref whose value
    is a list of rows, and each row is at least four ints
    (``[w_start, w_end, ms_start, ms_end]``) with ``ms_end >= ms_start`` and an
    optional trailing dict.
    """

    @model_validator(mode="after")
    def _validate_shape(self) -> SegmentsDoc:
        doc = self.root
        meta = doc.get("_meta")
        if meta is not None and not isinstance(meta, dict):
            raise ValueError("_meta must be a dict")

        for key, rows in doc.items():
            if key == "_meta":
                continue
            if not _VERSE_KEY_RE.match(key):
                raise ValueError(f"invalid verse key: {key!r}")
            if not isinstance(rows, list):
                raise ValueError(f"{key}: rows must be a list")
            for i, row in enumerate(rows):
                if not isinstance(row, list) or len(row) < 4:
                    raise ValueError(
                        f"{key}[{i}]: row must be [w_start, w_end, ms_start, ms_end, ...]"
                    )
                w_start, w_end, ms_start, ms_end = row[:4]
                if not (_is_int(w_start) and _is_int(w_end)):
                    raise ValueError(f"{key}[{i}]: word range not ints")
                if not (_is_int(ms_start) and _is_int(ms_end)):
                    raise ValueError(f"{key}[{i}]: ms range not ints")
                if ms_end < ms_start:
                    raise ValueError(f"{key}[{i}]: ms_end < ms_start")
                if len(row) > 4 and not isinstance(row[4], dict):
                    raise ValueError(f"{key}[{i}]: row tail must be a dict annotation")
        return self
