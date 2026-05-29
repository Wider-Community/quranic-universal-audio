-- Inspector SQLite substrate — mark-ready attestation submission (migration 0007).
--
-- Adds the persisted mark-ready form columns to ``claims``. A reviewer who
-- hits "Mark ready" submits a six-box checklist + two optional comment fields;
-- those land here on the open claim and are surfaced back to maintainers in the
-- admin Reviews drawer. Cleared together with ``marked_ready_at`` on
-- unmark / release / reassign so a sent-back row presents fresh; preserved on
-- closed history rows so past cycles' attestations stay auditable.
--
-- WHY a separate migration (not part of 0001): these columns were originally
-- inlined into 0001_init.sql, but every deployed/dev/local DB is already past
-- user_version 1, so 0001 never re-runs and the columns never reached live
-- data — the Reviews General drawer detail query (which SELECTs them) 500'd
-- with "no such column". Additive ALTERs are the only path that reaches an
-- existing DB; 0001 now creates the claims table WITHOUT these columns and
-- this migration adds them, so fresh and existing DBs converge on the same shape.
--
-- The runner wraps this file in BEGIN/…/PRAGMA user_version=7/COMMIT — do NOT
-- add transaction control or a user_version pragma here.

ALTER TABLE claims ADD COLUMN mark_ready_checklist      TEXT;   -- JSON: MarkReadyChecklist (scripts/lib/schemas/mark_ready.py)
ALTER TABLE claims ADD COLUMN mark_ready_comment_checks TEXT;   -- optional free text (additional checks performed)
ALTER TABLE claims ADD COLUMN mark_ready_comment_issues TEXT;   -- optional free text (notes / suspected false positives)
