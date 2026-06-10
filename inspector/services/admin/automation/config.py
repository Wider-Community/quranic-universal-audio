"""Cached load + durable save of the owner ``AutomationConfig`` blob.

``load_config`` is db_seq-keyed (mirrors the capability matrix cache): any
committed config write bumps ``db_seq`` and transparently invalidates it, so a
toggle takes effect on the very next tick / request with no restart. A stored
blob that fails to parse degrades to defaults (never crashes the daemon).
"""

from __future__ import annotations

import logging
from datetime import datetime

from qua_shared.schemas import Actor, AutomationConfig
from services.db import current_db_seq, repo_automation
from services.db.sync import durable_transaction
from services.state import audit
from services.storage import cache

logger = logging.getLogger(__name__)


def load_config() -> AutomationConfig:
    """The owner's automation config (defaults when unset/unparseable). Cached."""
    seq = current_db_seq()
    cached = cache.get_automation_config_cache(seq)
    if cached is not None:
        return cached  # type: ignore[return-value]
    raw = repo_automation.get_config_json()
    if raw is None:
        cfg = AutomationConfig()
    else:
        try:
            cfg = AutomationConfig.model_validate_json(raw)
        except Exception:  # noqa: BLE001 — degrade to defaults, never crash the tick
            logger.exception("automation: stored config unparseable — using defaults")
            cfg = AutomationConfig()
    cache.set_automation_config_cache(seq, cfg)
    return cfg


def save_config(
    cfg: AutomationConfig,
    *,
    updated_by: str,
    actor: Actor | None = None,
    reason: str = "automation",
    now: datetime | None = None,
) -> None:
    """Persist the config blob durably (one bucket upload).

    Pass ``actor`` to also append an audit event in the same transaction (the
    route does; the engine's one-shot override-clear can omit it).
    """
    with durable_transaction() as _:
        repo_automation.set_config_json(cfg.model_dump_json(), updated_by=updated_by, now=now)
        if actor is not None:
            audit.append(
                "automation.config_updated",
                actor=actor,
                slug=None,
                payload={"enabled": _enabled_summary(cfg)},
                reason=reason,
            )


def _enabled_summary(cfg: AutomationConfig) -> dict[str, bool]:
    """Which automations are on — the auditable diff-friendly shape."""
    return {
        "auto_gen_ts": cfg.auto_gen_ts.enabled,
        "gh_cut": cfg.gh_cut.enabled,
        "hf_publish": cfg.hf_publish.enabled,
        "stale_ts_regen": cfg.stale_ts_regen.enabled,
        "stale_metadata": cfg.stale_metadata.enabled,
        "auto_release_inactive": cfg.auto_release_inactive.enabled,
    }
