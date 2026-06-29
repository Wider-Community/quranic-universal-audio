-- Inspector SQLite substrate — migration 0026.
--
-- Soft-delete for `ts_reports`. A reporter removing their own report should
-- drop it from every user-facing view (counts, verse lists, "mine") while the
-- row is retained internally for audit/analysis. `hidden_at` (ISO-8601 UTC)
-- records when it was hidden; NULL = visible. All reads filter on
-- `hidden_at IS NULL`; re-filing the same category+target un-hides the row.
--
-- The per-identity unique indexes (ux_tsreport_user / ux_tsreport_anon) stay as
-- they are: a hidden row still occupies its (identity, category, target) slot,
-- so a re-file collides and updates-in-place (clearing hidden_at) rather than
-- inserting a duplicate.

ALTER TABLE ts_reports ADD COLUMN hidden_at TEXT;  -- NULL = visible

-- Reads scope to visible rows by slug/verse/status; index the common filter.
CREATE INDEX ix_tsreport_visible ON ts_reports(slug, verse_key) WHERE hidden_at IS NULL;
