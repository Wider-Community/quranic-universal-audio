"""Automation evaluators — config cache, auto-gen gates, scheduled guards.

The job launchers + ``list_jobs`` are monkeypatched on the ``evaluators`` module
so no real HF call fires; assertions read the durable ``automation_state`` row
back rather than trusting the spy.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qua_shared.schemas import (
    AutoGenTsConfig,
    AutomationConfig,
    GhCutConfig,
    HfPublishConfig,
)
from services.admin.automation import config as automation_config
from services.admin.automation import evaluators
from services.db import repo_automation
from services.storage import cache


@pytest.fixture(autouse=True)
def _clear_automation_cache():
    """The config cache is db_seq-keyed and the seq counter resets per test —
    clear it so a prior test's cached config doesn't bleed in."""
    cache.invalidate_automation_config_cache()
    yield
    cache.invalidate_automation_config_cache()


def _now() -> datetime:
    return datetime(2026, 6, 9, 12, 0, tzinfo=UTC)


# --- config load/save + cache ------------------------------------------------


def test_load_config_defaults_then_reflects_save():
    assert automation_config.load_config().gh_cut.enabled is False
    automation_config.save_config(
        AutomationConfig(gh_cut=GhCutConfig(enabled=True)), updated_by="owner"
    )
    assert automation_config.load_config().gh_cut.enabled is True


def test_unparseable_stored_blob_degrades_to_defaults():
    from services.db import transaction

    with transaction():
        repo_automation.set_config_json("not valid json", updated_by="owner")
    cache.invalidate_automation_config_cache()
    cfg = automation_config.load_config()
    assert cfg.gh_cut.enabled is False  # defaults, no crash


def test_reads_tolerate_missing_tables():
    """A DB whose 0020 migration hasn't applied must degrade to defaults — not
    500 the Releases tab / crash the reconciler tick."""
    from services.db import transaction

    with transaction() as conn:
        conn.execute("DROP TABLE automation_config")
        conn.execute("DROP TABLE automation_state")
    cache.invalidate_automation_config_cache()

    assert repo_automation.get_config_json() is None
    assert repo_automation.all_state() == []
    assert repo_automation.get_state("gh_cut") is None
    assert automation_config.load_config().gh_cut.enabled is False  # defaults, no raise


# --- auto-gen gates ----------------------------------------------------------


def _clean_claim() -> dict:
    return {
        "mark_ready_bypass_used": 0,
        "mark_ready_comment_checks": "",
        "mark_ready_comment_issues": "",
    }


def test_auto_gen_not_gated_when_clean(monkeypatch):
    monkeypatch.setattr(evaluators, "load_detailed", lambda slug: [])
    monkeypatch.setattr(evaluators, "count_flagged", lambda entries: 0)
    c = AutoGenTsConfig(enabled=True)
    assert evaluators._auto_gen_gated(c, "slug", _clean_claim()) is False


def test_auto_gen_gated_on_checklist_bypass(monkeypatch):
    monkeypatch.setattr(evaluators, "load_detailed", lambda slug: [])
    monkeypatch.setattr(evaluators, "count_flagged", lambda entries: 0)
    claim = _clean_claim() | {"mark_ready_bypass_used": 1}
    assert evaluators._auto_gen_gated(AutoGenTsConfig(enabled=True), "slug", claim) is True


def test_auto_gen_gated_on_reviewer_comment(monkeypatch):
    monkeypatch.setattr(evaluators, "load_detailed", lambda slug: [])
    monkeypatch.setattr(evaluators, "count_flagged", lambda entries: 0)
    claim = _clean_claim() | {"mark_ready_comment_issues": "boundary looks off"}
    assert evaluators._auto_gen_gated(AutoGenTsConfig(enabled=True), "slug", claim) is True


def test_auto_gen_gated_on_flagged_segment(monkeypatch):
    monkeypatch.setattr(evaluators, "load_detailed", lambda slug: [{"segments": []}])
    monkeypatch.setattr(evaluators, "count_flagged", lambda entries: 3)
    assert evaluators._auto_gen_gated(AutoGenTsConfig(enabled=True), "slug", _clean_claim()) is True


def test_auto_gen_comment_gate_off_ignores_comment(monkeypatch):
    monkeypatch.setattr(evaluators, "load_detailed", lambda slug: [])
    monkeypatch.setattr(evaluators, "count_flagged", lambda entries: 0)
    c = AutoGenTsConfig(enabled=True, gate_by_comments=False)
    claim = _clean_claim() | {"mark_ready_comment_issues": "noted"}
    assert evaluators._auto_gen_gated(c, "slug", claim) is False


# --- scheduled guards --------------------------------------------------------


def test_gh_cut_skips_empty_cut_and_advances_cadence(monkeypatch):
    launched: list[dict] = []
    monkeypatch.setattr(evaluators, "is_due", lambda **k: True)
    monkeypatch.setattr(evaluators, "current_auto_version", lambda: (None, 0))
    monkeypatch.setattr(evaluators.jobs_base, "running_job_for", lambda **k: None)
    monkeypatch.setattr(evaluators.cut_release_jobs, "launch", lambda **k: launched.append(k))

    evaluators.eval_gh_cut(AutomationConfig(gh_cut=GhCutConfig(enabled=True)), _now())

    assert launched == []  # no cut fired for an empty release
    st = repo_automation.get_state("gh_cut")
    assert st is not None
    assert st["last_status"] == "skipped"
    assert st["last_run_at"] is not None  # cadence advanced so we don't re-check every tick


def test_gh_cut_launches_when_changes_exist(monkeypatch):
    launched: list[dict] = []
    monkeypatch.setattr(evaluators, "is_due", lambda **k: True)
    monkeypatch.setattr(evaluators, "current_auto_version", lambda: ("v1.2.0", 3))
    monkeypatch.setattr(evaluators.jobs_base, "running_job_for", lambda **k: None)
    monkeypatch.setattr(evaluators.cut_release_jobs, "launch", lambda **k: launched.append(k))

    evaluators.eval_gh_cut(AutomationConfig(gh_cut=GhCutConfig(enabled=True)), _now())

    assert len(launched) == 1
    assert repo_automation.get_state("gh_cut")["last_status"] == "launched"


def test_gh_cut_one_shot_override_is_cleared_after_launch(monkeypatch):
    launched: list[dict] = []
    monkeypatch.setattr(evaluators, "is_due", lambda **k: True)
    monkeypatch.setattr(evaluators, "current_auto_version", lambda: ("v1.2.0", 3))
    monkeypatch.setattr(evaluators.jobs_base, "running_job_for", lambda **k: None)
    monkeypatch.setattr(evaluators.cut_release_jobs, "launch", lambda **k: launched.append(k))

    cfg = AutomationConfig(gh_cut=GhCutConfig(enabled=True, next_version_override="v9.9.9"))
    evaluators.eval_gh_cut(cfg, _now())

    assert launched[0]["version"] == "v9.9.9"  # override passed to the cut
    cache.invalidate_automation_config_cache()
    assert automation_config.load_config().gh_cut.next_version_override is None  # cleared


def test_hf_publish_skips_when_no_candidates(monkeypatch):
    launched: list[list[str]] = []
    monkeypatch.setattr(evaluators, "is_due", lambda **k: True)
    monkeypatch.setattr(evaluators.jobs_base, "running_job_for", lambda **k: None)
    monkeypatch.setattr(evaluators.jobs_base, "list_in_flight_jobs", lambda kinds: [])
    monkeypatch.setattr(
        evaluators.hf_publish_batch_jobs, "launch", lambda slugs, **k: launched.append(slugs)
    )

    # No deliveries seeded → no fresh/stale candidates.
    evaluators.eval_hf_publish(AutomationConfig(hf_publish=HfPublishConfig(enabled=True)), _now())

    assert launched == []
    st = repo_automation.get_state("hf_publish")
    assert st is not None
    assert st["last_status"] == "skipped"
