-- Inspector SQLite substrate — migration 0011.
--
-- Drop the vestigial ``delivery_states.prefetch_purge_at`` column. It scheduled
-- the post-release wip-audio sweeper (TTL GC of bucket audio/peaks), a feature
-- that has now been removed entirely — nothing writes or reads the column. No
-- index or constraint references it, so a plain DROP COLUMN suffices
-- (SQLite >= 3.35).
--
-- Conventions match prior migrations: no transaction control (the runner wraps
-- in BEGIN/COMMIT + user_version).

ALTER TABLE delivery_states DROP COLUMN prefetch_purge_at;
