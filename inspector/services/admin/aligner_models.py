"""Aligner model catalog for the inspector UI.

Reads the ``catalog.json`` manifest from the private model store repo
(``MFA_MODEL_REPO``, default ``hetchyy/qua-aligner-models``) so the timestamps
launch form + automation config can offer a model dropdown. Only the manifest
(tiny) is fetched — never the weights. Cached in-process; a stale/unreachable
repo degrades to a single ``default`` entry so the form still renders.
"""

from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

_MODEL_REPO = os.environ.get("MFA_MODEL_REPO", "hetchyy/qua-aligner-models")
_TTL_S = 300
_cache: dict[str, object] = {"at": 0.0, "models": None}


def _fetch() -> list[dict]:
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(_MODEL_REPO, "catalog.json", repo_type="model",
                           token=os.environ.get("HF_TOKEN") or None)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    default = data.get("default")
    out = []
    for m in data.get("models", []):
        out.append({"id": m["id"], "label": m.get("label", m["id"]),
                    "default": m["id"] == default})
    if out and not any(m["default"] for m in out):
        out[0]["default"] = True
    return out


def list_models() -> list[dict]:
    """[{id, label, default}], default-first. Cached; never raises."""
    now = time.time()
    if _cache["models"] is not None and now - float(_cache["at"]) < _TTL_S:
        return _cache["models"]  # type: ignore[return-value]
    try:
        models = _fetch()
    except Exception as exc:  # noqa: BLE001 — degrade, don't break the form
        logger.warning("aligner catalog fetch failed (%s); using default-only", exc)
        models = _cache["models"] or [{"id": None, "label": "Default", "default": True}]
    models = sorted(models, key=lambda m: (not m["default"], str(m["label"])))
    _cache.update(at=now, models=models)
    return models
