"""Smoke test for the stateful services (state, catalog, audit, access).

Uses a ``FilesystemBackend`` against a tempdir — no HF deps. Run with
``python -m inspector.services._services_smoke``.

Exercises the slug-bound state machine end-to-end (claim → mark-ready →
unmark → release → claim → publish → timestamps → unlocked_for_revision
→ unpublished), plus the role bootstrap + grant + revoke + update flows,
plus catalog vocab-only stub round-trip.
"""

from __future__ import annotations

import os
import sys
import tempfile

# Smoke output uses non-ASCII glyphs (arrows, ↔). Force UTF-8 on stdout for
# Windows hosts where the default cp1252 console can't render them.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

from qua_shared.schemas import (
    Actor,
    AudioCategory,
    Channel,
    ReciterEntry,
    Riwayah,
    Role,
    Source,
    Style,
    Vocab,
)

# Force filesystem backend before any service imports trigger get_backend().
os.environ["INSPECTOR_BACKEND"] = "filesystem"


def _setup(root: str):
    """Configure backend + freshly hydrate stores against ``root``."""
    os.environ["INSPECTOR_FILESYSTEM_ROOT"] = root

    from . import access, audit, catalog, state
    from .hf_bucket import FilesystemBackend, set_backend

    set_backend(FilesystemBackend(root))
    access.hydrate()
    state.hydrate()
    catalog.hydrate()
    audit.ensure_meta_initialized()
    return access, audit, catalog, state


def smoke() -> int:
    try:
        with tempfile.TemporaryDirectory() as root:
            access, audit, catalog, state = _setup(root)
            from qua_shared.schemas import ReciterState, Visibility

            # ---- access bootstrap ----
            owner = access.bootstrap(hf_user_id="100", login="owner_alice")
            assert owner.role == Role.OWNER
            assert access.resolve_role("100") == Role.OWNER
            assert access.resolve_role("999") == Role.CONTRIBUTOR
            print("ok  access.bootstrap + resolve_role")

            owner_actor = Actor(hf_user_id="100", login_at_time="owner_alice", role=Role.OWNER)

            # grant a maintainer + a contributor self (via grant maintainer)
            maintainer = access.grant(
                hf_user_id="200",
                login="maint_bob",
                role=Role.MAINTAINER,
                actor=owner_actor,
            )
            assert maintainer.role == Role.MAINTAINER
            assert access.resolve_role("200") == Role.MAINTAINER
            print("ok  access.grant MAINTAINER")

            maintainer_actor = Actor(
                hf_user_id="200", login_at_time="maint_bob", role=Role.MAINTAINER
            )
            # contributor doesn't get a role row (CONTRIBUTOR is implicit).
            contributor_actor = Actor(
                hf_user_id="300", login_at_time="contrib_carol", role=Role.CONTRIBUTOR
            )

            # Re-grant same maintainer should fail.
            try:
                access.grant(
                    hf_user_id="200",
                    login="maint_bob",
                    role=Role.MAINTAINER,
                    actor=owner_actor,
                )
            except access.MemberAlreadyActive:
                print("ok  access.grant rejects duplicate active member")
            else:
                raise AssertionError("expected MemberAlreadyActive")

            # Maintainer cannot grant OWNER.
            try:
                access.grant(
                    hf_user_id="900",
                    login="impostor",
                    role=Role.OWNER,
                    actor=maintainer_actor,
                )
            except access.NotAuthorized:
                print("ok  access.grant denies maintainer granting OWNER")
            else:
                raise AssertionError("expected NotAuthorized")

            # ---- catalog: stub vocab + add reciter + add delivery ----
            stub = catalog.snapshot()
            stub.vocab = Vocab(
                riwayat=[Riwayah(slug="hafs_an_asim", short="hafs", name="Hafs A'n Assem")],
                styles=[Style(slug="murattal", short="murattal", name="Murattal")],
                sources=[
                    Source(
                        slug="mp3quran",
                        name="mp3quran.net",
                        url="https://mp3quran.net",
                        audio_categories=[AudioCategory.BY_SURAH],
                    )
                ],
                channels=[Channel(slug="mp3quran", short="mp3quran", name="mp3quran CDN")],
                recording_contexts=[],
            )
            # Persist vocab directly (bypasses the mutation API which is for
            # the runtime; tests need to seed the vocab first.)
            from . import storage_paths
            from .hf_bucket import get_backend

            get_backend().write_json_atomic(
                storage_paths.catalog_path(),
                stub.model_dump(mode="json"),
            )
            catalog.hydrate()

            reciter = catalog.add_reciter(
                actor=maintainer_actor,
                reciter_id="saad_al_ghamdi",
                name_en="Saad Al-Ghamdi",
                name_ar="سعد الغامدي",
                country="SA",
            )
            assert reciter.reciter_id == "saad_al_ghamdi"
            print("ok  catalog.add_reciter")

            # Contributor cannot mutate catalog.
            try:
                catalog.add_reciter(
                    actor=contributor_actor,
                    reciter_id="rogue",
                    name_en="Rogue",
                )
            except catalog.NotAuthorizedForCatalog:
                print("ok  catalog.add_reciter denies contributor")
            else:
                raise AssertionError("expected NotAuthorizedForCatalog")

            # ---- state: full lifecycle on a single slug ----
            # Seed a row directly into the state file (this is what
            # seed_state.py does at cutover). Use catalog.added to create.
            row = state.transition(
                "saad_al_ghamdi",
                "catalog.added",
                actor=maintainer_actor,
            )
            assert row.state == ReciterState.CATALOGUED
            print("ok  state catalog.added → CATALOGUED")

            # reciter.requested → AWAITING_ALIGNMENT (the canonical flow now
            # that admin.force_set_state has been removed).
            row = state.transition(
                "saad_al_ghamdi",
                "reciter.requested",
                actor=contributor_actor,
            )
            assert row.state == ReciterState.AWAITING_ALIGNMENT
            row = state.transition(
                "saad_al_ghamdi",
                "reciter.alignment_completed",
                actor=maintainer_actor,
            )
            assert row.state == ReciterState.AWAITING_REVIEW
            print("ok  state alignment_completed → AWAITING_REVIEW")

            # claim → under_review
            row = state.transition(
                "saad_al_ghamdi",
                "reciter.claimed",
                actor=contributor_actor,
            )
            assert row.state == ReciterState.UNDER_REVIEW
            assert row.assignee_hf_id == "300"
            print("ok  state reciter.claimed → UNDER_REVIEW")

            # second claim from different user → InvalidTransition (already
            # under_review).
            try:
                state.transition(
                    "saad_al_ghamdi",
                    "reciter.claimed",
                    actor=owner_actor,
                )
            except state.InvalidTransition:
                print("ok  state second claim rejected")
            else:
                raise AssertionError("expected InvalidTransition")

            # one-claim-per-user predicate
            assert state.has_other_active_claim("300")
            assert not state.has_other_active_claim("300", except_slug="saad_al_ghamdi")
            print("ok  state.has_other_active_claim")

            # mark_ready → unmark_ready
            row = state.transition(
                "saad_al_ghamdi",
                "reciter.marked_ready",
                actor=contributor_actor,
            )
            assert row.marked_ready is True
            print("ok  state reciter.marked_ready")

            row = state.transition(
                "saad_al_ghamdi",
                "reciter.unmarked_ready",
                actor=contributor_actor,
            )
            assert row.marked_ready is False
            print("ok  state reciter.unmarked_ready")

            # non-assignee can't unmark
            row = state.transition(
                "saad_al_ghamdi",
                "reciter.marked_ready",
                actor=contributor_actor,
            )
            try:
                state.transition(
                    "saad_al_ghamdi",
                    "reciter.unmarked_ready",
                    actor=owner_actor,
                )
            except state.NotAuthorizedForTransition:
                print("ok  state unmark by non-assignee rejected")
            else:
                raise AssertionError("expected NotAuthorizedForTransition")

            # send-back via merge_rejected (maintainer-driven, flips flag)
            row = state.transition(
                "saad_al_ghamdi",
                "reciter.merge_rejected",
                actor=maintainer_actor,
                reason="please fix verse 152 timing alignment",
            )
            assert row.marked_ready is False
            assert row.assignee_hf_id == "300"  # assignee retained
            print("ok  state reciter.merge_rejected (assignee retained)")

            # mark again, then publish (maintainer). Publish now goes straight
            # under_review (marked_ready) → released — no awaiting_timestamps
            # hop — and carries the succeeded job id for the audit.
            state.transition(
                "saad_al_ghamdi",
                "reciter.marked_ready",
                actor=contributor_actor,
            )
            row = state.transition(
                "saad_al_ghamdi",
                "reciter.published",
                actor=maintainer_actor,
                payload={"job_id": "job_abc"},
            )
            assert row.state == ReciterState.RELEASED
            assert row.assignee_hf_id is None
            assert row.timestamps_job_ids == ["job_abc"]
            print("ok  state reciter.published → RELEASED (job linked)")

            # unlocked_for_revision — sets RevisionContext (exits RELEASED)
            row = state.transition(
                "saad_al_ghamdi",
                "admin.unlocked_for_revision",
                actor=owner_actor,
            )
            assert row.state == ReciterState.AWAITING_REVIEW
            assert row.revision_in_progress is not None
            assert row.revision_in_progress.unlocked_from_state == "released"
            print("ok  state admin.unlocked_for_revision sets RevisionContext")

            # discard / undiscard
            row = state.transition(
                "saad_al_ghamdi",
                "reciter.discarded",
                actor=maintainer_actor,
                reason="audio source taken down by upstream copyright claim",
            )
            assert row.visibility == Visibility.DISCARDED
            row = state.transition(
                "saad_al_ghamdi",
                "reciter.undiscarded",
                actor=maintainer_actor,
            )
            assert row.visibility == Visibility.PUBLIC
            print("ok  state reciter.discarded ↔ undiscarded")

            # claim on a fresh slug — exercises reassign on a different slug
            # so the one-claim-per-user check is unrelated.
            state.transition(
                "test_other",
                "catalog.added",
                actor=maintainer_actor,
            )
            state.transition(
                "test_other",
                "reciter.requested",
                actor=contributor_actor,
            )
            state.transition(
                "test_other",
                "reciter.alignment_completed",
                actor=maintainer_actor,
            )
            state.transition(
                "test_other",
                "reciter.claimed",
                actor=contributor_actor,
            )
            row = state.transition(
                "test_other",
                "claim.reassigned",
                actor=owner_actor,
                payload={"new_assignee_hf_id": "200", "new_assignee_login": "maint_bob"},
                reason="original claim holder went on leave for two weeks",
            )
            assert row.assignee_hf_id == "200"
            print("ok  state claim.reassigned swaps assignee")

            # force_released
            row = state.transition(
                "test_other",
                "claim.force_released",
                actor=owner_actor,
                reason="locked claim freed after one-month inactivity check",
            )
            assert row.state == ReciterState.AWAITING_REVIEW
            assert row.assignee_hf_id is None
            print("ok  state claim.force_released")

            # ---- access revoke + update ----
            access.update(
                hf_user_id="200",
                actor=owner_actor,
                login="maint_bob_renamed",
            )
            updated = access.find_member("200")
            assert updated is not None and updated.login == "maint_bob_renamed"
            print("ok  access.update refreshes login cache")

            access.revoke(
                hf_user_id="200",
                actor=owner_actor,
                reason="left the project after migration cutover",
            )
            assert access.resolve_role("200") == Role.CONTRIBUTOR  # soft-deleted
            print("ok  access.revoke soft-deletes")

            # ---- audit partition has all our entries ----
            from . import storage_paths

            partition = storage_paths.audit_partition_path(
                __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            )
            records = list(get_backend().iter_jsonl(partition))
            assert len(records) >= 15, f"expected >=15 audit entries, got {len(records)}"
            print(f"ok  audit has {len(records)} entries")

        print("services smoke: all checks passed")
        return 0
    except Exception as e:
        import traceback

        traceback.print_exc()
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(smoke())
