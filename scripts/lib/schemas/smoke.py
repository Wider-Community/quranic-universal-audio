"""Schema round-trip smoke test.

Run with ``python -m scripts.lib.schemas.smoke``. Exits 0 on success, 1 on
the first validation failure. Constructs one realistic instance of each
top-level schema, round-trips through JSON, and re-validates.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from .access import Member, Role, RolesFile
from .audit import Actor, AuditRecord
from .catalog import (
    AudioCategory,
    BitrateMode,
    Channel,
    Delivery,
    ReciterCatalog,
    ReciterEntry,
    RecordingContext,
    Riwayah,
    Source,
    Style,
    Vocab,
)
from .edit_history import EditHistoryBatch, EditOperation, parse_edit_history_line
from .state import (
    ReciterRow,
    ReciterState,
    ReciterStateFile,
    Visibility,
)


def _now() -> datetime:
    return datetime(2026, 5, 12, 14, 23, 11, tzinfo=timezone.utc)


def _round_trip(label: str, model) -> None:
    cls = type(model)
    payload = model.model_dump(mode="json")
    serialized = json.dumps(payload)
    reparsed = cls.model_validate_json(serialized)
    if reparsed != model:
        raise AssertionError(f"{label}: round-trip mismatch")
    print(f"ok  {label}")


def smoke() -> int:
    try:
        # 1. RolesFile
        owner = Member(
            hf_user_id="12345",
            login="alice",
            role=Role.OWNER,
            added_at=_now(),
            added_by_hf_id="bootstrap",
        )
        roles = RolesFile(members=[owner])
        assert roles.resolve_role("12345") == Role.OWNER
        assert roles.resolve_role("nobody") == Role.CONTRIBUTOR
        _round_trip("RolesFile", roles)

        # 2. ReciterStateFile — claim cycle
        catalogued = ReciterRow(
            slug="bandar_balilah",
            state=ReciterState.CATALOGUED,
            state_since=_now(),
        )
        awaiting = ReciterRow(
            slug="saad_al_ghamdi",
            state=ReciterState.AWAITING_REVIEW,
            state_since=_now(),
        )
        under = ReciterRow(
            slug="mishary_alafasi",
            state=ReciterState.UNDER_REVIEW,
            state_since=_now(),
            assignee_hf_id="12345",
            assignee_login="alice",
            assignee_since=_now(),
        )
        ready = ReciterRow(
            slug="maher_al_meaqli",
            state=ReciterState.UNDER_REVIEW,
            state_since=_now(),
            assignee_hf_id="12345",
            assignee_login="alice",
            assignee_since=_now(),
            marked_ready=True,
        )
        completed = ReciterRow(
            slug="yasser_al_dosari",
            state=ReciterState.COMPLETED,
            state_since=_now(),
            visibility=Visibility.PUBLIC,
        )
        state_file = ReciterStateFile(
            reciters=[catalogued, awaiting, under, ready, completed]
        )
        assert state_file.find("mishary_alafasi") is under
        _round_trip("ReciterStateFile", state_file)

        # State invariant: assignee on a non-under_review row is rejected.
        try:
            ReciterRow(
                slug="bad_slug",
                state=ReciterState.AWAITING_REVIEW,
                state_since=_now(),
                assignee_hf_id="12345",
            )
        except Exception:
            print("ok  ReciterRow rejects assignee on non-under_review")
        else:
            raise AssertionError("expected ValidationError on stray assignee")

        # State invariant: marked_ready without under_review is rejected.
        try:
            ReciterRow(
                slug="bad_slug_2",
                state=ReciterState.AWAITING_REVIEW,
                state_since=_now(),
                marked_ready=True,
            )
        except Exception:
            print("ok  ReciterRow rejects marked_ready outside under_review")
        else:
            raise AssertionError("expected ValidationError on stray marked_ready")

        # Slug regex: invalid slug rejected.
        try:
            ReciterRow(
                slug="Bad-Slug",  # uppercase + hyphen
                state=ReciterState.CATALOGUED,
                state_since=_now(),
            )
        except Exception:
            print("ok  ReciterRow rejects invalid slug")
        else:
            raise AssertionError("expected ValidationError on invalid slug")

        # 3. ReciterCatalog — vocab-only stub (Phase 1 shape).
        vocab = Vocab(
            riwayat=[Riwayah(slug="hafs_an_asim", short="hafs", name="Hafs A'n Assem")],
            styles=[
                Style(slug="murattal", short="murattal", name="Murattal"),
                Style(slug="mujawwad", short="mujawwad", name="Mujawwad"),
            ],
            sources=[
                Source(
                    slug="mp3quran",
                    name="mp3quran.net",
                    url="https://mp3quran.net",
                    audio_categories=[AudioCategory.BY_SURAH],
                )
            ],
            channels=[
                Channel(slug="mp3quran", short="mp3quran", name="mp3quran CDN"),
            ],
            recording_contexts=[
                RecordingContext(slug="studio", name="Studio recording"),
            ],
        )
        stub = ReciterCatalog(vocab=vocab)
        _round_trip("ReciterCatalog (vocab-only stub)", stub)

        # 4. ReciterCatalog — with one reciter + one delivery, FKs valid.
        full = ReciterCatalog(
            vocab=vocab,
            reciters=[
                ReciterEntry(
                    reciter_id="saad_al_ghamdi",
                    name_en="Saad Al-Ghamdi",
                    name_ar="سعد الغامدي",
                    country="SA",
                )
            ],
            deliveries=[
                Delivery(
                    slug="saad_al_ghamdi_mp3quran",
                    reciter_id="saad_al_ghamdi",
                    riwayah="hafs_an_asim",
                    style="murattal",
                    recording_context="studio",
                    source="mp3quran",
                    channel="mp3quran",
                    audio_category=AudioCategory.BY_SURAH,
                    chapter_count=114,
                    bitrate_mode=BitrateMode.CBR,
                    bitrate_kbps_nominal=128,
                    added_at=_now(),
                    added_by_hf_id="12345",
                )
            ],
        )
        _round_trip("ReciterCatalog (with delivery, FKs)", full)

        # Catalog FK: unknown reciter_id rejected.
        try:
            ReciterCatalog(
                vocab=vocab,
                deliveries=[
                    Delivery(
                        slug="orphan_mp3quran",
                        reciter_id="ghost",
                        riwayah="hafs_an_asim",
                        style="murattal",
                        source="mp3quran",
                        channel="mp3quran",
                        audio_category=AudioCategory.BY_SURAH,
                        chapter_count=0,
                        added_at=_now(),
                        added_by_hf_id="12345",
                    )
                ],
            )
        except Exception:
            print("ok  ReciterCatalog rejects orphan delivery FK")
        else:
            raise AssertionError("expected ValidationError on orphan delivery")

        # 5. AuditRecord
        rec = AuditRecord(
            ts=_now(),
            event="reciter.claimed",
            slug="saad_al_ghamdi",
            from_state="awaiting_review",
            to_state="under_review",
            actor=Actor(hf_user_id="12345", login_at_time="alice", role=Role.CONTRIBUTOR),
            request_id="req_abc123",
        )
        _round_trip("AuditRecord", rec)

        # 6. EditHistoryBatch + v1 tolerance
        batch = EditHistoryBatch(
            batch_id="batch_001",
            ts=_now(),
            actor=Actor(
                hf_user_id="12345", login_at_time="alice", role=Role.CONTRIBUTOR
            ),
            operations=[EditOperation(op_id="op_001", kind="trim", new_end=1.234)],
        )
        _round_trip("EditHistoryBatch", batch)

        v1_genesis = '{"type": "genesis", "file_hash_after": "deadbeef"}'
        assert parse_edit_history_line(v1_genesis) is None
        print("ok  parse_edit_history_line skips v1 genesis")

        v1_batch_with_chain = json.dumps(
            {
                "batch_id": "batch_legacy",
                "ts": "2025-01-01T00:00:00Z",
                "actor": {
                    "hf_user_id": "1",
                    "login_at_time": "old",
                    "role": "contributor",
                },
                "operations": [],
                "file_hash_after": "deadbeef",  # should be silently dropped
            }
        )
        parsed = parse_edit_history_line(v1_batch_with_chain)
        assert parsed is not None and parsed.batch_id == "batch_legacy"
        print("ok  parse_edit_history_line drops legacy file_hash_after")

        print("smoke: all checks passed")
        return 0
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(smoke())
