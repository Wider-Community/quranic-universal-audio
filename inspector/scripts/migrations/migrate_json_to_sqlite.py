"""One-shot migration: 7 bucket JSON stores + audit JSONL → SQLite.

Reads the legacy stores via the configured storage backend, decomposes them
into the SQLite tables, runs a parity readback, and (optionally) uploads the
DB to ``db/inspector.db``. Refuses to overwrite an existing bucket DB without
``--force``.

Decomposition:
  access  → users + role_assignments (active + revoked)
  catalog → vocab + reciters + deliveries + aliases + persisted derived/generated_at
  state   → delivery_states + a synthesized OPEN claim for under_review rows
  pending + 3 archives → requests (status pending|accepted|returned|discarded)
  audit JSONL → transitions (ts/id/content_hash preserved verbatim; slug NULLed
                if the delivery no longer exists, to satisfy the FK)
  activity → activity_tombstones (keyed on content_hash; the legacy per-user
             dismissals list is dropped — the admin notifications rail it
             backed has been retired)

Parity is SEMANTIC (list order normalized — repos read slug-sorted), not byte.

Usage:
  python inspector/scripts/migrations/migrate_json_to_sqlite.py --bucket dev [--force]
                                                      [--allow-orphans] [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger("migrate_json_to_sqlite")

# Backfill SQL is owned by the schema migration so there's one source of truth;
# build() applies it after its inserts (schema migrations run before build()
# populates, so a fresh build needs first_seen recomputed post-insert).
_FIRST_SEEN_BACKFILL_SQL = (
    # migrations/ -> scripts/ -> inspector/
    Path(__file__).resolve().parent.parent.parent
    / "services" / "db" / "migrations" / "0003_backfill_first_seen.sql"
)

_STATUS_FOR_ARCHIVE = {"completed": "accepted", "returned": "returned", "discarded": "discarded"}
_BUCKET_REPOS = {
    "dev": "hetchyy/quranic-inspector-bucket-dev",
    "prod": "hetchyy/quranic-inspector-bucket",
}


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def read_sources() -> dict:
    from services.storage import storage_paths as sp
    from services.storage.hf_bucket import StorageNotFound, get_backend
    from qua_shared.schemas import (
        ActivityState, ArchivedRequestsFile, PendingRequestsFile, ReciterCatalog,
        ReciterStateFile, RolesFile,
    )

    backend = get_backend()

    def _json(path, model, default):
        try:
            return model.model_validate(backend.read_json(path))
        except StorageNotFound:
            return default

    archives = {
        "completed": _json(sp.completed_requests_path(), ArchivedRequestsFile, ArchivedRequestsFile()),
        "returned": _json(sp.returned_requests_path(), ArchivedRequestsFile, ArchivedRequestsFile()),
        "discarded": _json(sp.discarded_requests_path(), ArchivedRequestsFile, ArchivedRequestsFile()),
    }

    audit: list[dict] = []
    try:
        names = sorted(backend.list_dir("audit"))
    except Exception:
        names = []
    part_re = re.compile(r"^\d{4}-\d{2}\.jsonl$")
    for name in names:
        if part_re.match(name):
            audit.extend(backend.iter_jsonl(f"audit/{name}"))

    return {
        "state": _json(sp.state_path(), ReciterStateFile, ReciterStateFile()),
        "catalog": _json(sp.catalog_path(), ReciterCatalog, ReciterCatalog()),
        "roles": _json(sp.roles_path(), RolesFile, RolesFile()),
        "pending": _json(sp.pending_requests_path(), PendingRequestsFile, PendingRequestsFile()),
        "archives": archives,
        "activity": _json(sp.activity_state_path(), ActivityState, ActivityState()),
        "audit": audit,
    }


# ---------------------------------------------------------------------------
# orphan check
# ---------------------------------------------------------------------------


def orphan_check(src: dict) -> list[tuple[str, str]]:
    """(kind, slug) for every state/request slug missing from catalog deliveries."""
    delivery_slugs = {d.slug for d in src["catalog"].deliveries}
    orphans: list[tuple[str, str]] = []
    for row in src["state"].reciters:
        if row.slug not in delivery_slugs:
            orphans.append(("state", row.slug))
    for slug in src["pending"].by_slug:
        if slug not in delivery_slugs:
            orphans.append(("pending", slug))
    for kind, af in src["archives"].items():
        for slug in af.by_slug:
            if slug not in delivery_slugs:
                orphans.append((f"archive:{kind}", slug))
    return orphans


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def _actor_dict(actor) -> dict:
    role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
    return {"hf_user_id": actor.hf_user_id, "login_at_time": actor.login_at_time, "role": role}


def build(src: dict, *, allow_orphans: bool = False) -> dict:
    """Populate the (migrated, empty) DB from the sources, in one transaction."""
    import uuid

    from services import db
    from services.db import _serde, repo_access, repo_catalog, repo_claims, repo_state

    catalog = src["catalog"]
    delivery_slugs = {d.slug for d in catalog.deliveries}
    stats = {k: 0 for k in (
        "users", "roles", "reciters", "deliveries", "states", "claims",
        "requests", "transitions", "tombstones", "orphans_skipped",
    )}

    # idempotency guard: build() only runs against a freshly-migrated empty DB.
    _conn0 = db.get_conn()
    for _t in ("role_assignments", "reciters", "deliveries", "delivery_states",
               "claims", "requests", "transitions"):
        if _conn0.execute(f"SELECT 1 FROM {_t} LIMIT 1").fetchone():  # fixed table list
            raise SystemExit(f"ABORT: target table {_t} is not empty — run against a fresh DB")

    with db.transaction() as conn:
        # --- access: users + role_assignments ---
        for m in src["roles"].members:
            repo_access.ensure_user(m.hf_user_id, login=m.login)
            repo_access.ensure_user(m.added_by_hf_id)
            if m.removed_by_hf_id:
                repo_access.ensure_user(m.removed_by_hf_id)
            role = m.role.value if hasattr(m.role, "value") else str(m.role)
            conn.execute(
                "INSERT INTO role_assignments(hf_user_id, role, granted_at, granted_by, "
                "revoked_at, revoked_by) VALUES (?,?,?,?,?,?)",
                (m.hf_user_id, role, _serde.to_iso(m.added_at), m.added_by_hf_id,
                 _serde.to_iso(m.removed_at), m.removed_by_hf_id),
            )
            stats["roles"] += 1

        # --- catalog ---
        repo_catalog.load_vocab(catalog.vocab)
        for r in catalog.reciters:
            repo_catalog.insert_reciter(r); stats["reciters"] += 1
        for d in catalog.deliveries:
            repo_catalog.insert_delivery(d); stats["deliveries"] += 1
        for a in catalog.aliases:
            repo_catalog.insert_alias(a)
        repo_catalog.set_meta(generated_at=catalog.generated_at, derived=catalog.derived)

        # --- state + synthesized open claims ---
        for row in src["state"].reciters:
            if row.slug not in delivery_slugs:
                if not allow_orphans:
                    raise RuntimeError(f"orphan state slug {row.slug!r} (use --allow-orphans)")
                stats["orphans_skipped"] += 1
                continue
            repo_state.upsert_state(
                row.slug, state=row.state, state_since=row.state_since,
                visibility=row.visibility, visibility_reason=row.visibility_reason,
                last_save_at=row.last_save_at, timestamps_job_ids=row.timestamps_job_ids,
                revision_in_progress=row.revision_in_progress,
            )
            stats["states"] += 1
            if row.assignee_hf_id:
                repo_access.ensure_user(row.assignee_hf_id, login=row.assignee_login)
                repo_claims.open_claim(
                    slug=row.slug, assignee_id=row.assignee_hf_id,
                    assignee_login=row.assignee_login, claimed_at=row.assignee_since,
                )
                if row.marked_ready:
                    repo_claims.set_marked_ready(row.slug, ready=True, at=row.assignee_since)
                stats["claims"] += 1

        # --- requests: pending + archives ---
        def _insert_request(*, slug, requester, submitted_at, status, proposed_edits,
                            comments, auto_claim, resolved_at=None, transitioned_by=None,
                            reason=None):
            if slug is not None and slug not in delivery_slugs:
                if not allow_orphans:
                    raise RuntimeError(f"orphan request slug {slug!r} (use --allow-orphans)")
                stats["orphans_skipped"] += 1
                return
            repo_access.ensure_user(requester.hf_user_id, login=requester.login_at_time)
            payload = {
                "requester": _actor_dict(requester),
                "proposed_edits": proposed_edits.model_dump(mode="json"),
            }
            resolved_by = None
            if transitioned_by is not None:
                repo_access.ensure_user(transitioned_by.hf_user_id,
                                        login=transitioned_by.login_at_time)
                payload["transitioned_by"] = _actor_dict(transitioned_by)
                resolved_by = transitioned_by.hf_user_id
            conn.execute(
                "INSERT INTO requests(id, kind, slug, requester_id, submitted_at, status, "
                "resolved_at, resolved_by_id, resolution_reason, auto_claim, comments, payload) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"rq_{uuid.uuid4().hex[:12]}", "existing_combo_edit", slug,
                 requester.hf_user_id, _serde.to_iso(submitted_at), status,
                 _serde.to_iso(resolved_at), resolved_by, reason,
                 1 if auto_claim else 0, comments, _serde.json_dumps(payload)),
            )
            stats["requests"] += 1

        for slug, pr in src["pending"].by_slug.items():
            _insert_request(slug=slug, requester=pr.requester, submitted_at=pr.submitted_at,
                            status="pending", proposed_edits=pr.proposed_edits,
                            comments=pr.comments, auto_claim=pr.auto_claim)
        for kind, af in src["archives"].items():
            status = _STATUS_FOR_ARCHIVE[kind]
            for slug, lst in af.by_slug.items():
                for ar in lst:
                    _insert_request(slug=slug, requester=ar.requester,
                                    submitted_at=ar.submitted_at, status=status,
                                    proposed_edits=ar.proposed_edits, comments=ar.comments,
                                    auto_claim=ar.auto_claim, resolved_at=ar.archived_at,
                                    transitioned_by=ar.transitioned_by, reason=ar.reason)

        # --- transitions (audit) ---
        seen_ids: set[str] = set()
        for rec in src["audit"]:
            actor = rec.get("actor") or {}
            actor_hf = actor.get("hf_user_id")
            if actor_hf:
                repo_access.ensure_user(actor_hf, login=actor.get("login_at_time"))
            tid = rec.get("request_id") or f"req_{uuid.uuid4().hex[:12]}"
            while tid in seen_ids:
                tid = f"req_{uuid.uuid4().hex[:12]}"
            seen_ids.add(tid)
            slug = rec.get("slug")
            if slug is not None and slug not in delivery_slugs:
                slug = None  # preserve the event; drop the dangling FK link
            conn.execute(
                "INSERT INTO transitions(id, ts, slug, event, from_state, to_state, "
                "actor_id, actor_login_snapshot, actor_role_snapshot, reason, result, "
                "payload, content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, rec.get("ts"), slug, rec.get("event"), rec.get("from_state"),
                 rec.get("to_state"), actor_hf, actor.get("login_at_time"),
                 actor.get("role"), rec.get("reason"), rec.get("result") or "ok",
                 _serde.json_dumps(rec.get("payload") or {}),
                 _serde.content_hash_for_record(rec)),
            )
            stats["transitions"] += 1

        # --- activity sidecars ---
        # Per-user dismissals were dropped with the admin notifications rail;
        # only the global tombstone list is migrated.
        now_iso = _serde.to_iso(_serde.now())
        for ch in src["activity"].deleted:
            conn.execute(
                "INSERT OR IGNORE INTO activity_tombstones(audit_content_hash, ts) VALUES (?,?)",
                (ch, now_iso),
            )
            stats["tombstones"] += 1

        # Correct first_seen to the earliest historical evidence now that all
        # users + their role/claim/request/transition rows are inserted (within
        # this same txn, so the recompute sees them). Same statement that ships
        # as migration 0003 for already-populated DBs.
        conn.execute(_FIRST_SEEN_BACKFILL_SQL.read_text(encoding="utf-8"))

        stats["users"] = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    return stats


# ---------------------------------------------------------------------------
# parity
# ---------------------------------------------------------------------------


def _norm_catalog(dump: dict) -> dict:
    d = dict(dump)
    v = dict(d.get("vocab") or {})
    for key in ("riwayat", "styles", "sources", "channels", "recording_contexts"):
        v[key] = sorted(v.get(key) or [], key=lambda x: x["slug"])
    d["vocab"] = v
    d["reciters"] = sorted(d.get("reciters") or [], key=lambda x: x["reciter_id"])
    d["deliveries"] = sorted(d.get("deliveries") or [], key=lambda x: x["slug"])
    return d


def parity_check(src: dict, *, allow_orphans: bool) -> list[str]:
    from services import db
    from services.db import repo_access, repo_activity, repo_catalog, repo_requests, repo_state

    delivery_slugs = {d.slug for d in src["catalog"].deliveries}
    issues: list[str] = []

    got = repo_catalog.snapshot().model_dump(mode="json", by_alias=True)
    want = src["catalog"].model_dump(mode="json", by_alias=True)
    if _norm_catalog(got) != _norm_catalog(want):
        issues.append("catalog snapshot mismatch")

    got_active = {(m.hf_user_id, m.role) for m in repo_access.active_members()}
    want_active = {(m.hf_user_id, m.role) for m in src["roles"].active_members()}
    if got_active != want_active:
        issues.append(f"active roles mismatch: {got_active} != {want_active}")

    for row in src["state"].reciters:
        if row.slug not in delivery_slugs:
            continue
        got_row = repo_state.get_row(row.slug)
        if got_row is None or got_row.model_dump(mode="json") != row.model_dump(mode="json"):
            issues.append(f"state row mismatch: {row.slug}")

    want_pending = {s for s in src["pending"].by_slug if s in delivery_slugs}
    got_pending = {pr.slug for pr in repo_requests.all_pending()}
    if got_pending != want_pending:
        issues.append(f"pending mismatch: {got_pending} != {want_pending}")

    conn = db.get_conn()

    # archives: per-status row counts (slugs out of catalog are skipped on build)
    for kind, af in src["archives"].items():
        status = _STATUS_FOR_ARCHIVE[kind]
        want = sum(len(lst) for s, lst in af.by_slug.items() if s in delivery_slugs)
        got = conn.execute("SELECT COUNT(*) FROM requests WHERE status=?", (status,)).fetchone()[0]
        if got != want:
            issues.append(f"archive {kind} count {got} != {want}")

    # open claims ↔ under_review state rows with an assignee
    want_claims = {
        (r.slug, r.assignee_hf_id) for r in src["state"].reciters
        if r.slug in delivery_slugs and r.assignee_hf_id
    }
    got_claims = {
        (row["slug"], row["assignee_id"])
        for row in conn.execute("SELECT slug, assignee_id FROM claims WHERE released_at IS NULL")
    }
    if got_claims != want_claims:
        issues.append(f"open claims mismatch: {got_claims} != {want_claims}")

    # role_assignments: full count (active + revoked) + active set already checked
    n_roles = conn.execute("SELECT COUNT(*) FROM role_assignments").fetchone()[0]
    if n_roles != len(src["roles"].members):
        issues.append(f"role_assignments count {n_roles} != {len(src['roles'].members)}")

    # activity sidecars (keyed on content_hash)
    if repo_activity.deleted_set() != set(src["activity"].deleted):
        issues.append("tombstones mismatch")

    n_tx = conn.execute("SELECT COUNT(*) FROM transitions").fetchone()[0]
    if n_tx != len(src["audit"]):
        issues.append(f"transitions count {n_tx} != audit {len(src['audit'])}")

    return issues


# ---------------------------------------------------------------------------
# run / CLI
# ---------------------------------------------------------------------------


def run(*, allow_orphans: bool = False, dry_run: bool = False) -> dict:
    src = read_sources()
    orphans = orphan_check(src)
    if orphans and not allow_orphans:
        raise SystemExit(
            f"ABORT: {len(orphans)} orphan slug(s) not in catalog deliveries: "
            f"{orphans[:10]}{'...' if len(orphans) > 10 else ''} — pass --allow-orphans to skip."
        )
    stats = build(src, allow_orphans=allow_orphans)
    issues = parity_check(src, allow_orphans=allow_orphans)
    if issues:
        raise SystemExit(f"ABORT: parity check failed: {issues}")
    logger.info("migration parity OK: %s", stats)
    return stats


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="migrate_json_to_sqlite")
    p.add_argument("--bucket", choices=["dev", "prod"], default="dev")
    p.add_argument("--force", action="store_true", help="overwrite an existing bucket DB")
    p.add_argument("--allow-orphans", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="build + parity, no upload")
    args = p.parse_args(argv)

    os.environ.setdefault("INSPECTOR_BACKEND", "bucket")
    os.environ["INSPECTOR_BUCKET_REPO"] = _BUCKET_REPOS[args.bucket]

    from services import db
    from services.db import sync
    from services.storage.hf_bucket import StorageNotFound

    # refuse to clobber an existing bucket DB
    if not args.force:
        try:
            sync._read_direct(sync.DB_BUCKET_PATH)
            print(f"ABORT: {sync.DB_BUCKET_PATH} already exists in bucket; pass --force.")
            return 2
        except StorageNotFound:
            pass

    db.init_db()
    stats = run(allow_orphans=args.allow_orphans, dry_run=args.dry_run)
    print(f"built DB: {stats}")
    if args.dry_run:
        print("dry-run: skipping upload")
        return 0
    seq = sync.upload()
    print(f"uploaded db/inspector.db at seq={seq}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
