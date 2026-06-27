"""Public Timestamps-tab report routes (``/api/ts/<slug>/reports``).

The categorized, cell-addressable rework of the verse-flag routes. Any visitor —
including anonymous — files a typed report (audio / timing / mapping / tajweed /
other) against a flexible target on the verse currently shown, optionally with a
comment. A report's targeted shard content is snapshotted server-side at create
time (the drift fingerprint). A new report fans a notification out to
review-alert recipients (owners by default). Owners resolve a report (single
terminal ``resolved`` outcome + optional comment), which notifies the reporter.

Gated by ``timestamps.report`` (anon-eligible, open by default). Resolve is gated
by ``timestamps.resolve_report`` (owner-default). Report-author identity in GET
responses is gated by ``timestamps.see_reporter_identity``; the stale-only filter
by ``timestamps.view_stale_reports``. Writes wrap ``sync.durable_transaction``;
mutations require a same-origin POST.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from qua_shared.schemas.wire.ts_reports import (
    TsReciterReports,
    TsReport,
    TsReportAuthor,
    TsReportCreateRequest,
    TsReportResolveRequest,
    TsReportSnapshot,
    TsReportTarget,
    TsReportVerseCount,
    TsVerseReports,
)
from services import auth as auth_service
from services.auth import capabilities as cap_service
from services.db import _serde, repo_ts_reports
from services.db import sync as _sync
from services.notifications import emit as _notify
from services.permissions import role_of
from services.ts_reports import ts_target_snapshot
from utils.decorators import require_same_origin

logger = logging.getLogger(__name__)

ts_reports_bp = Blueprint("ts_reports", __name__, url_prefix="/api/ts")


def _validation_detail(e: ValidationError) -> list[dict]:
    """JSON-safe error summary (``e.errors()`` embeds raw ValueError ``ctx``)."""
    return [{"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]} for err in e.errors()]

_REPORT_CAP = "timestamps.report"
_RESOLVE_CAP = "timestamps.resolve_report"
_IDENTITY_CAP = "timestamps.see_reporter_identity"
_VIEW_STALE_CAP = "timestamps.view_stale_reports"


def _snapshot_view(snap: dict) -> TsReportSnapshot | None:
    """Map the stored snapshot dict to the wire model, or ``None`` when empty.

    Collapses the cell ``tag`` + ``secondary_tags`` into ``rule_tags``."""
    if not snap:
        return None
    has_content = any(
        snap.get(k) for k in ("chars", "role", "status", "tag", "word_text", "verse_text")
    ) or any(snap.get(k) for k in ("secondary_tags", "phoneme_rule_tags", "phones"))
    if not has_content:
        return None
    rule_tags: list[str] = []
    if snap.get("tag"):
        rule_tags.append(snap["tag"])
    rule_tags.extend(snap.get("secondary_tags") or [])
    return TsReportSnapshot(
        chars=snap.get("chars"),
        role=snap.get("role"),
        status=snap.get("status"),
        rule_tags=rule_tags,
        phoneme_rule_tags=snap.get("phoneme_rule_tags") or [],
        phones=snap.get("phones") or [],
        share_group=snap.get("share_group"),
        word_text=snap.get("word_text"),
        verse_text=snap.get("verse_text"),
        schema_version=snap.get("schema_version"),
    )


def _report_view(row: dict, *, mine: bool, show_author: bool) -> TsReport:
    author = None
    if show_author:
        author = TsReportAuthor(
            hf_user_id=row["hf_user_id"],
            login=row["login_at_time"],
            role=row["role_at_time"],
        )
    return TsReport(
        id=row["id"],
        verse_key=row["verse_key"],
        category=row["category"],
        subtype=row["subtype"],
        target=TsReportTarget(**row["target"]),
        snapshot=_snapshot_view(row["snapshot"]),
        comment=row["comment"],
        status=row["status"],
        stale=row["stale"],
        resolver_comment=row["resolver_comment"],
        resolved_at=row["resolved_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        mine=mine,
        author=author,
    )


def _is_mine(row: dict, *, hf_user_id: str | None, anon_token: str | None) -> bool:
    if hf_user_id is not None:
        return row["hf_user_id"] == hf_user_id
    if anon_token:
        return row["anon_token"] == anon_token
    return False


@ts_reports_bp.route("/<slug>/reports", methods=["GET"])
def get_reciter_reports(slug: str):
    """Reported-verse pills + open/resolved counts for the accordion. Public read."""
    try:
        counts = repo_ts_reports.verse_counts(slug)
        resp = TsReciterReports(reports=[TsReportVerseCount(**c) for c in counts])
        return jsonify(resp.model_dump(mode="json"))
    except Exception:  # noqa: BLE001
        logger.exception("ts_reports.get_reciter_reports failed for %s", slug)
        return jsonify({"error": "failed to load reports"}), 500


@ts_reports_bp.route("/<slug>/reports/mine", methods=["GET"])
def get_my_reports(slug: str):
    """The caller's own reports (signed-in by cookie, or anon by ``?anon_token=``)."""
    try:
        user = auth_service.current_user()
        if user is not None:
            hf_user_id: str | None = user.hf_user_id
            anon_token: str | None = None
        else:
            anon_token = (request.args.get("anon_token") or "").strip() or None
            hf_user_id = None
            if anon_token is None:
                return jsonify({"reports": []})
        rows = repo_ts_reports.my_reports(slug, hf_user_id=hf_user_id, anon_token=anon_token)
        show_author = cap_service.can(user, _IDENTITY_CAP)
        reports = [_report_view(r, mine=True, show_author=show_author) for r in rows]
        return jsonify({"reports": [r.model_dump(mode="json") for r in reports]})
    except Exception:  # noqa: BLE001
        logger.exception("ts_reports.get_my_reports failed for %s", slug)
        return jsonify({"error": "failed to load reports"}), 500


@ts_reports_bp.route("/<slug>/reports/<verse_key>", methods=["GET"])
def get_verse_reports(slug: str, verse_key: str):
    """All reports on a verse. Public read; author shown only to identity-capable
    callers. ``?stale=1`` filters to stale reports (owner-gated)."""
    try:
        user = auth_service.current_user()
        show_author = cap_service.can(user, _IDENTITY_CAP)
        hf_user_id = user.hf_user_id if user is not None else None
        anon_token = request.args.get("anon_token") if user is None else None
        rows = repo_ts_reports.list_for_verse(slug, verse_key)
        if request.args.get("stale") == "1":
            if not cap_service.can(user, _VIEW_STALE_CAP):
                return jsonify({"error": "not available"}), 403
            rows = [r for r in rows if r["stale"]]
        reports = [
            _report_view(
                r,
                mine=_is_mine(r, hf_user_id=hf_user_id, anon_token=anon_token),
                show_author=show_author,
            )
            for r in rows
        ]
        return jsonify(
            TsVerseReports(verse_key=verse_key, reports=reports).model_dump(mode="json")
        )
    except Exception:  # noqa: BLE001
        logger.exception("ts_reports.get_verse_reports failed for %s %s", slug, verse_key)
        return jsonify({"error": "failed to load reports"}), 500


@ts_reports_bp.route("/<slug>/reports", methods=["POST"])
@require_same_origin
def create_report(slug: str):
    """Create the caller's report on a verse. Anonymous allowed."""
    user = auth_service.current_user()
    if not cap_service.can(user, _REPORT_CAP):
        return jsonify({"error": "not available"}), 403
    try:
        req = TsReportCreateRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"error": "invalid report", "detail": _validation_detail(e)}), 400

    if user is not None:
        hf_user_id: str | None = user.hf_user_id
        anon_token: str | None = None
        login_at_time: str | None = user.login
        role_at_time: str | None = role_of(user).value
    else:
        anon = (req.anon_token or "").strip()
        if not anon:
            return jsonify({"error": "anon_token required for anonymous reports"}), 400
        hf_user_id, anon_token = None, anon
        login_at_time = role_at_time = None

    target = req.target.model_dump()
    snapshot = ts_target_snapshot.build_snapshot(slug, req.verse_key, target)

    try:
        with _sync.durable_transaction():
            row, created = repo_ts_reports.create(
                slug=slug,
                verse_key=req.verse_key,
                category=req.category,
                subtype=req.subtype,
                target=target,
                snapshot=snapshot,
                comment=req.comment,
                hf_user_id=hf_user_id,
                anon_token=anon_token,
                login_at_time=login_at_time,
                role_at_time=role_at_time,
            )
    except Exception:  # noqa: BLE001
        logger.exception("ts_reports.create_report failed for %s %s", slug, req.verse_key)
        return jsonify({"error": "failed to save report"}), 500

    if created:
        at_utc = _serde.to_iso(row["created_at"])
        if at_utc is not None:
            _notify.notify_owners_ts_report(
                slug=slug,
                verse_key=req.verse_key,
                category=req.category,
                author_id=hf_user_id,
                author_login=login_at_time,
                report_id=row["id"],
                at_utc=at_utc,
            )

    show_author = cap_service.can(user, _IDENTITY_CAP)
    return jsonify(
        _report_view(row, mine=True, show_author=show_author).model_dump(mode="json")
    ), (201 if created else 200)


@ts_reports_bp.route("/<slug>/reports/<int:report_id>/resolve", methods=["POST"])
@require_same_origin
def resolve_report(slug: str, report_id: int):
    """Mark a report resolved (owner-gated) and notify the reporter."""
    user = auth_service.current_user()
    if not cap_service.can(user, _RESOLVE_CAP):
        return jsonify({"error": "not available"}), 403
    try:
        req = TsReportResolveRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"error": "invalid resolve", "detail": _validation_detail(e)}), 400

    try:
        with _sync.durable_transaction():
            row = repo_ts_reports.resolve(
                report_id=report_id,
                resolver_hf_user_id=user.hf_user_id if user is not None else None,
                resolver_login=user.login if user is not None else None,
                resolver_comment=req.comment,
            )
    except Exception:  # noqa: BLE001
        logger.exception("ts_reports.resolve_report failed for %s #%s", slug, report_id)
        return jsonify({"error": "failed to resolve report"}), 500

    if row is None:
        return jsonify({"error": "report not found or already resolved"}), 404

    reporter_id = row["hf_user_id"]
    if reporter_id is not None:
        at_utc = _serde.to_iso(row["resolved_at"])
        if at_utc is not None:
            _notify.notify_reporter_ts_report_resolved(
                reporter_id=reporter_id,
                slug=slug,
                verse_key=row["verse_key"],
                resolver_comment=req.comment,
                report_id=report_id,
                at_utc=at_utc,
            )

    show_author = cap_service.can(user, _IDENTITY_CAP)
    return jsonify(_report_view(row, mine=False, show_author=show_author).model_dump(mode="json"))


@ts_reports_bp.route("/<slug>/reports/<int:report_id>", methods=["DELETE"])
@require_same_origin
def delete_report(slug: str, report_id: int):
    """Delete the caller's own report."""
    user = auth_service.current_user()
    if not cap_service.can(user, _REPORT_CAP):
        return jsonify({"error": "not available"}), 403
    if user is not None:
        hf_user_id: str | None = user.hf_user_id
        anon_token: str | None = None
    else:
        anon_token = (request.args.get("anon_token") or "").strip()
        if not anon_token:
            return jsonify({"error": "anon_token required"}), 400
        hf_user_id = None
    try:
        with _sync.durable_transaction():
            removed = repo_ts_reports.delete(
                report_id=report_id, hf_user_id=hf_user_id, anon_token=anon_token
            )
    except Exception:  # noqa: BLE001
        logger.exception("ts_reports.delete_report failed for %s #%s", slug, report_id)
        return jsonify({"error": "failed to delete report"}), 500
    return jsonify({"ok": removed})
