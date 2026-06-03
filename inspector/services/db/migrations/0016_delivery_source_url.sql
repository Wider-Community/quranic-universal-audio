-- Inspector SQLite substrate — migration 0016.
--
-- Add deliveries.source_url: the originating playlist/set/collection URL for
-- download-only sources (YouTube playlists, SoundCloud sets, archive items).
-- Surfaced on PublicDelivery so the reciter-detail channel cell can hyperlink
-- to the source. NULL for CDN deliveries — their per-chapter URLs live in the
-- audio_manifest sidecar. See docs/reference/catalog.md.
--
-- The runner wraps this file in BEGIN/…/PRAGMA user_version=16/COMMIT — do NOT
-- add transaction control or a user_version pragma here.

ALTER TABLE deliveries ADD COLUMN source_url TEXT;
