-- Inspector SQLite substrate — migration 0030.
--
-- Review state for maintainer samples: a maintainer marks a sample reviewed
-- once its segments and word timings look right, which surfaces the "Ready"
-- tag on the samples list. Any later segment save clears it (the save path
-- nulls both columns), so the tag always describes the current content.

ALTER TABLE samples ADD COLUMN reviewed_at TEXT;
ALTER TABLE samples ADD COLUMN reviewed_by TEXT REFERENCES users(hf_user_id);
