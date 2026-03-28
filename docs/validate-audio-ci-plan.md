# CI: Validate audio manifests on PR + related automation

## Context
When contributors add new audio manifests or update `_meta` fields via PRs, there's no automated validation or audit trail. Need: PR validation with URL checks, clean single/multi report format, GitHub issue updates on meta changes, and release automation review.

## 1. NEW: `.github/workflows/validate-audio-pr.yml`

**Trigger:** `pull_request` on `data/audio/**/*.json`

**Steps:**
1. Detect changed/added manifests via `git diff --name-only` against PR base
2. Run `validators/validate_audio_ci.py` with `--check-sources` (do check URLs — acceptable CI time for 1-5 files)
3. Post concise markdown report as PR comment

**Report format — single file (clean, no table):**
```markdown
## Audio Manifest Validation

**`mp3quran/new_reciter.json`** — Ali Jaber (علي جابر)
- Coverage: 114 / 114 surahs
- Riwayah: hafs_an_asim | Style: murattal | Country: unknown
- Sources: 114 reachable, 0 errors
- Meta: ✓ all fields valid
```

**Report format — multiple files:**
```markdown
## Audio Manifest Validation

| File | Reciter | Coverage | Sources | Meta |
|------|---------|----------|---------|------|
| `mp3quran/new_reciter.json` | Ali Jaber | 114/114 | ✓ | ✓ |
| `everyayah/partial.json` | Ayman Sowaid | 89/114 | 2 errors | ⚠ missing name_ar |

<details><summary>Details</summary>
...per-file breakdown...
</details>
```

**Permissions:** `contents: read`, `pull-requests: write`

## 2. GitHub issue updates on meta changes

When a PR modifies `_meta` fields of an existing manifest that has a linked request issue:

**In `validate_audio_ci.py`:**
- For modified files (not new), diff the `_meta` against base branch version
- If any fields changed, include a "Meta Changes" section in the report showing old → new
- Output a structured JSON summary of changes for the workflow to consume

**In the workflow:**
- If meta changes detected AND the slug has an open/closed request issue, update the issue body:
  - Find the relevant `**Field:**` line
  - Strikethrough old value, append new: `**Style:** ~~murattal~~ mujawwad`
  - Add a comment: "Meta updated via PR #N: style changed from murattal to mujawwad"
- Same pattern for min_silence changes on re-align PRs

**Implementation:** The workflow step uses `gh` CLI to:
1. Search issues for slug: `gh issue list --label request --search "Slug: {slug}"`
2. If found, edit issue body with `gh api` PATCH to strikethrough changed values
3. Add comment documenting the change

## 3. Release automation gaps

**Current state (`scripts/package_release.py`):**
- `info.json` per reciter includes: reciter, reciter_display, riwayah, audio_source, coverage, version, created
- **Missing from info.json:** name_en, name_ar, style, country — these are in the audio manifest but not copied to the release zip
- Release triggers after `sync-dataset.yml` succeeds (which triggers on segment/timestamp changes)
- Audio manifest `_meta` changes do NOT trigger a release (only segment/timestamp changes do)

**Needed updates to `scripts/package_release.py`:**
- `build_info_json()` (~line 111-130): Add name_en, name_ar, style, country from audio_meta
- Include `audio.json` in zip with the full manifest URLs (already done — `find_audio_manifest()` copies it)

**Release trigger for meta changes:**
- Option A: Add `data/audio/**/*.json` to `sync-dataset.yml` triggers → cascades to release
- Option B: Add a separate `workflow_dispatch` trigger condition in `release.yml` for audio meta changes
- **Recommendation:** Option A is simpler. Meta changes should trigger a dataset re-sync (the HF dataset card references riwayah/style), which cascades to release.

But wait — `sync-dataset.yml` only syncs reciters that have segments+timestamps. A meta-only change to a manifest that has no segments won't trigger anything. That's correct behavior — we only release aligned reciters. For aligned reciters, meta changes SHOULD trigger a re-sync because the dataset includes metadata.

**Action:** Add `data/audio/**/*.json` to `sync-dataset.yml` path triggers (alongside existing segment/timestamp paths). Then `build_reciter.py` will re-upload with updated metadata, and release will auto-trigger.

## Files to create/modify

| File | Action |
|------|--------|
| `.github/workflows/validate-audio-pr.yml` | **NEW** — PR validation + comment |
| `validators/validate_audio_ci.py` | **NEW** — validation script with URL checks, meta diff, markdown output |
| `scripts/package_release.py` | **MODIFY** — add name_en, name_ar, style, country to info.json |
| `.github/workflows/sync-dataset.yml` | **MODIFY** — add `data/audio/**/*.json` to path triggers |

## 4. `_meta.fetched` date field

All manifests now include `fetched` — an ISO date string recording when the manifest was created or last refreshed.

**Backfill:** All 382 existing manifests backfilled with `"2026-03-28"`.

**CI automation (future):** When `validate-audio-pr.yml` processes a new manifest that's missing `fetched`, the CI adds it automatically using the PR merge date. For modified manifests where `_meta` fields changed, CI updates `fetched` to the current date. This is done in a follow-up commit by the workflow (requires `contents: write` permission on the PR branch).

**Schema:** `fetched` is optional in `_meta`. Valid format: `"YYYY-MM-DD"`. Validated by `validate_audio_ci.py` as a warning if missing (not an error).

## `validators/validate_audio_ci.py` logic

1. Accept manifest paths as CLI args + `--base-sha` for meta diffing
2. For each manifest:
   - Load JSON, extract `_meta`
   - **Coverage:** count data keys vs expected (114 surahs or 6236 ayahs)
   - **URL check:** parallel HEAD requests on audio URLs (same as validate_audio.py but reports counts)
   - **Meta schema:** reciter non-empty, name_en non-empty and not "unknown", riwayah in riwayat.json, style in styles.json, no empty strings, country can be "unknown", fetched is valid ISO date if present
   - **Meta diff (modified files):** compare _meta against base-sha version, report changed fields
3. Adaptive report: single-file → clean prose format; multi-file → table
4. Output `changes.json` with slug→field→{old, new} for issue update step
5. Exit 1 on errors, 0 on clean/warnings

## Verification
1. PR adding new manifest → validation runs, URL checks pass, comment posted (single format)
2. PR adding multiple manifests → table format comment
3. PR modifying existing manifest _meta → meta diff shown, linked issue updated with strikethrough
4. Meta change to aligned reciter pushed to main → sync-dataset triggers → release triggers
5. `python3 scripts/package_release.py --dry-run` → info.json includes name_en, name_ar, style, country, fetched
