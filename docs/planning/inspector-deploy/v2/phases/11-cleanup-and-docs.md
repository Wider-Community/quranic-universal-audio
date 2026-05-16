# Phase 11 — Cleanup and docs

> Decommission the legacy repo `data/` layout now that every consumer reads from the bucket. Drop dead workflows + scripts. Refresh contributor docs to point at the new flows.

**Status:** not started
**Depends on:** Phase 5 (publish pipeline + workflow rewrite) complete
**Blocks:** —

## Goal

The repo no longer carries per-reciter data files, vocab JSON sidecars, or audio manifests — the bucket is the sole source of truth for that content, and every CI workflow + maintainer script that previously read `data/` has been migrated to `huggingface_hub` reads against the bucket. Dead workflows (v1 PR-flow + earlier-v2-draft forwards) are removed. Contributor-facing docs point at the website as the primary contribution surface; local-mode docs stay for maintainer offline use.

## Deliverables

- [ ] Repo `data/` cleanup (carried over from Phase 1 — see [`01-foundation.md`](01-foundation.md) Outcomes / Deferred):
  - [ ] `data/recitation_segments/` (entire tree)
  - [ ] `data/audio/` (entire tree, 381 per-reciter manifests)
  - [ ] `data/reciters_index.json`
  - [ ] `data/riwayat.json`, `data/sources.json`, `data/styles.json`
  - [ ] `data/.audio_meta.json`, `data/.audio_durations.json`
  - [ ] `data/timestamps/` (carried from Phase 2 — see [`02-deployable-image.md`](02-deployable-image.md))
- [ ] Grep audit passes: `grep -rE "reciters_index|riwayat\.json|sources\.json|styles\.json|\.audio_meta|\.audio_durations|recitation_segments" .github/ scripts/ inspector/ validators/` returns no matches outside `inspector_v2_seed/` (which intentionally reads on-disk vocab to seed the bucket)
- [ ] Pre-deletion safety snapshot: tag `pre-v2-cutover` at the commit before the data deletion so the git history of segments edits stays reachable for forensic queries
- [ ] Dead workflows deleted (also referenced in Phase 5): `bot-create-pr.yml`, `bot-comment.yml`, `issue-commands.yml`, `pr-assignee-sync.yml`, `validate-segments-pr.yml`, `segments-pr-merged.yml`, `forward-to-inspector.yml`
- [ ] `.github/scripts/find_segments_pr.py` deleted
- [ ] Legacy bucket layout decommission (D20 Option B): drop `<bucket>/manifest.json.gz`, `<bucket>/segments/<slug>/`, `<bucket>/timestamps/<slug>/`. Gated on D20 Track A (aligner Preload migrated) AND Track B (Inspector TS-tab frontend migrated). Delete the shard builders: `scripts/lib/segments_shards.py`, `scripts/lib/timestamps_shards.py`. Delete `inspector/services/ts_local.py` (local-mode manifest builder; replaced by v2 path reads). Drop `INSPECTOR_TS_HF_DATASET_BASE_URL` env from `inspector/config.py`.
- [ ] `inspector/CLAUDE.md`, `CONTRIBUTING.md`, top-level `CLAUDE.md` updated: website is the primary contribution surface; local Docker is the maintainer offline / debug fallback
- [ ] `data/README.md` rewritten or removed — describes the bucket layout link instead of the gone `data/recitation_segments/`

## Out of scope

- Schema-doc generation pipeline (deferred — separate `schema-docs.md` track).
- D-item resolutions that need their own design rounds (D2 reciter-requests-space decommission, D14 native request flow).
- Local-mode complete removal — kept for offline maintainer review.

## Acceptance criteria

- [ ] `git status` after the deletion commit shows no remaining tracked files under the listed paths
- [ ] `git tag pre-v2-cutover` resolves to a commit that still has the deleted files (forensic reach)
- [ ] All v1 PR-flow workflows produced zero runs in the 7 days preceding deletion (verified via `gh run list`)
- [ ] Contributor docs no longer reference `data/recitation_segments/<slug>/` paths as the "where to find this" answer
- [ ] CI green on the cleanup commit's PR

## Verification

```bash
# Pre-deletion snapshot
git tag pre-v2-cutover

# Deletion commit
git rm -r data/recitation_segments/ data/audio/ data/timestamps/
git rm data/reciters_index.json data/riwayat.json data/sources.json data/styles.json
git rm data/.audio_meta.json data/.audio_durations.json
git rm .github/scripts/find_segments_pr.py
git rm .github/workflows/{bot-create-pr,bot-comment,issue-commands,pr-assignee-sync,validate-segments-pr,segments-pr-merged,forward-to-inspector}.yml

# Audit
test ! -d data/recitation_segments
test ! -d data/audio
test ! -d data/timestamps
test ! -f data/reciters_index.json
! grep -rE "reciters_index|riwayat\.json|sources\.json|styles\.json|\.audio_meta|\.audio_durations|recitation_segments" \
    .github/ scripts/ inspector/ validators/ 2>/dev/null

# CI smoke (after merge)
gh workflow run update-reciters.yml --ref main
gh workflow run sync-dataset.yml --ref main
gh workflow run release.yml --ref main
# all three should complete green reading from the bucket
```

## Risks

- **Loss of git blame on segment edits.** Mitigated by the `pre-v2-cutover` tag and by the audit log + edit_history.jsonl on the bucket (which carry the actor + batch_id per save in the v2 schema).
- **Stale references in docs.** Mitigated by the grep audit + a manual sweep of `README.md` files.
- **Forgotten workflow still scheduled.** Mitigated by the 7-day observation window before deletion.

## Reference

- [`inspector-cleanup-registry.md`](../inspector-cleanup-registry.md) — running ledger of deletions / modifications / new code across v2
- [`inspector-deferred.md`](../inspector-deferred.md) D20 — legacy bucket layout decision
- [`01-foundation.md`](01-foundation.md) Outcomes log — what got carried forward from Phase 1
- [`02-deployable-image.md`](02-deployable-image.md) — `data/timestamps/` removal scoping
- [`05-publish-pipeline.md`](05-publish-pipeline.md) — workflow rewrite that unblocks `data/` deletion
