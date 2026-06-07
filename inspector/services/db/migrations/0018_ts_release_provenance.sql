-- Record regeneration provenance on the per-recitation ts row so a future
-- granular per-reciter changelog can say "v_n regenerated chapters [5,12],
-- superseding v_{n-1}".
-- affected_chapters → JSON int list of chapters the regen folded in (the edits
--                     since the prior generation; null for a first publish).
-- prior_ts_version  → the version of the ts row this one superseded (null first).

ALTER TABLE per_recitation_releases ADD COLUMN affected_chapters TEXT;
ALTER TABLE per_recitation_releases ADD COLUMN prior_ts_version TEXT;
