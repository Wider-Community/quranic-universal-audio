"""Release-automation reconciler.

A single opt-in daemon (gated by ``INSPECTOR_AUTOMATIONS=1``) that watches live
release state every ~60 s and fires the existing release jobs on the owner's
behalf, per the owner's ``AutomationConfig``. Five independent automations:
auto-generate timestamps, scheduled GH cut, scheduled HF batch-publish,
stale-TS regen, stale-metadata refresh.

The engine reacts to *state* (not events), so it is idempotent + restart-safe;
it respects job single-flight and skips the failed bucket (no auto-retry). See
``docs/reference/automation.md``.
"""

from __future__ import annotations

from .config import load_config, save_config
from .engine import start_background_loop, tick

__all__ = ["load_config", "save_config", "start_background_loop", "tick"]
