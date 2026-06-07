-- Tag release staleness with a reason so remediation can differ per cause.
-- ts_regen  → per-verse timestamps changed → needs a full HF republish / GH cut.
-- catalog_edit → catalog metadata changed → cheap HF "refresh catalog" / next GH cut.
-- Backfill existing stamps to ts_regen (the only historical stamper).

ALTER TABLE per_recitation_releases ADD COLUMN stale_reason TEXT;
ALTER TABLE gh_release_recitations  ADD COLUMN stale_reason TEXT;

UPDATE per_recitation_releases SET stale_reason = 'ts_regen' WHERE stale_since IS NOT NULL;
UPDATE gh_release_recitations  SET stale_reason = 'ts_regen' WHERE stale_since IS NOT NULL;
