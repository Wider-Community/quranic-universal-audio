-- Inspector SQLite substrate — migration 0013.
--
-- Add ``delivery_states.last_job_finished_at`` (ISO-8601 UTC, nullable). Stamped
-- whenever a timestamps job for the slug reaches a terminal state — on SUCCESS
-- (alongside the publish → released transition) and on FAILURE (no state change;
-- the reciter stays under_review marked_ready). It drives the Reviews-tab
-- notification dot for job completions, the same way ``claims.marked_ready_at``
-- drives the mark-ready dot: a row is "unread" when
-- ``max(marked_ready_at, last_job_finished_at) > review_views.viewed_at``.
--
-- NULL for every pre-existing row (no backfill) so historically-released
-- reciters don't light up the dot — only completions going forward do.
--
-- Conventions match prior migrations: no transaction control (the runner wraps
-- in BEGIN/COMMIT + user_version).

ALTER TABLE delivery_states ADD COLUMN last_job_finished_at TEXT;
