# Inspector State Management Strategy

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md). Implementation-grade reference for everything reciter-state: the source-of-truth file, the catalog file, the state machine, the consolidated workflow, the identity convention with full templates, GitHub mirroring, Inspector integration, per-phase acceptance criteria, and risks.

The parent doc owns deployment architecture, file IO (which lives in [`inspector-data-storage.md`](inspector-data-storage.md)), auth/claim UX, locking, and edit-history simplifications. This doc owns *what state means, where it lives, who writes it, and how it gets reflected back to GitHub and Inspector.*

## 1. Model in one paragraph

`data/reciter_state.json` is the source of truth for pipeline state, current assignee, active issue/PR numbers, and per-reciter event history. It is repo-tracked. The only writer is `update-reciter-state.yml`, which listens for typed `repository_dispatch` events fired by every other workflow and by the Inspector backend, applies validated transitions to the file, commits with a `[state] <slug>: <event>` subject, and mirrors the new state to GitHub primitives (issue body, labels, assignees) for human UX. Static identity (display name, riwayah, audio source, `url_template`) lives separately in `data/reciter_catalog.json`, updated by manual PRs from intake. Inspector reads both files (parsed once on startup, refreshed on webhook or short poll) and bases every UI affordance on them — no live GitHub API for the read path.

## 2. Source of truth: `data/reciter_state.json`

### Schema

```jsonc
{
  "schema_version": 1,
  "updated_at": "2026-05-09T14:23:11Z",
  "updated_by_run": 1234,
  "reciters": {
    "saad_al_ghamdi": {
      "slug": "saad_al_ghamdi",
      "state": "under_review",
      "state_since": "2026-05-08T14:23:11Z",
      "issue_number": 42,
      "pr_number": 89,
      "pr_head_sha": "abc1234567...",
      "assignee": "alice",
      "assignee_since": "2026-05-08T14:23:11Z",
      "history": [
        { "at": "2026-04-15T...", "event": "catalog_synced",      "detail": "added"      },
        { "at": "2026-04-15T...", "event": "alignment_requested", "by": "bob"            },
        { "at": "2026-04-20T...", "event": "alignment_completed", "pr": 89               },
        { "at": "2026-05-08T...", "event": "claimed",             "by": "alice"          }
      ]
    }
  }
}
```

### Field semantics

| Field | Type | Nullable | Notes |
|---|---|---|---|
| `schema_version` | int | no | Bump on rename / removal / semantic change. Additive fields don't bump. |
| `updated_at` | ISO 8601 | no | Wall-clock at workflow run start |
| `updated_by_run` | int | no | GitHub Actions run ID for traceability |
| `reciters[<slug>].slug` | string | no | Redundant with key — kept for tooling that streams entries |
| `reciters[<slug>].state` | enum | no | One of the six states in §4 |
| `reciters[<slug>].state_since` | ISO 8601 | no | Latest transition into current state |
| `reciters[<slug>].issue_number` | int | yes | Null in `catalogued`; set from `awaiting_alignment` onward |
| `reciters[<slug>].pr_number` | int | yes | Null when no review PR exists; set in `awaiting_review` and `under_review`; cleared on merge |
| `reciters[<slug>].pr_head_sha` | string | yes | Snapshotted at every dispatch that touches the PR. Used by Inspector cache invalidation. |
| `reciters[<slug>].assignee` | string | yes | GitHub login. Null except in `under_review` |
| `reciters[<slug>].assignee_since` | ISO 8601 | yes | Same lifetime as `assignee` |
| `reciters[<slug>].history` | array | no | Bounded ring of last 20 entries; full history in `git log -- data/reciter_state.json` |

### History entries

```jsonc
{ "at": "<iso8601>", "event": "<event_name>", "by": "<login>", "detail": "<free-form>" }
```

`event` is from the closed vocabulary in §4. `by` is set when the event was triggered by a specific user (claim, release, manual override). `detail` is free-form and optional. Entries are append-only within a workflow run; truncation drops the oldest entry when the array exceeds 20.

### Write semantics

- **Single writer:** `update-reciter-state.yml`. Concurrency declared `singleton` so two events fired simultaneously serialize. Writes use atomic JSON serialisation (write to tempfile, `os.replace`).
- **Commit subject:** `[state] <slug>: <event>` (e.g. `[state] saad_al_ghamdi: claimed by alice`).
- **Author/committer:** `github-actions[bot]` for both.
- **Push target:** `main` directly. No PR review for state-file commits — the workflow IS the review (validation rules in §5).

### Read semantics

- **Inspector:** parses on startup, caches in memory, refreshes on a webhook (`/api/internal/state-changed`) hit by the workflow after every commit. Falls back to a 30 s poll if the webhook is missed.
- **CI scripts:** read via `scripts/lib/reciter_state.py::load()` which returns a typed `StateStore` dataclass.
- **External tools / RECITERS.md generator:** read directly off `main` via `gh api` or raw fetch.

### Validation

A CI job on every state-file commit runs `scripts/validate_reciter_state.py`:

- JSON parses cleanly.
- `schema_version` matches the expected version (or one supported version up).
- Every slug in `reciters` exists in `reciter_catalog.json`.
- `state` is in the closed enum.
- For each state, the required-fields invariants in §4 hold.
- `history` arrays are length ≤ 20.
- Timestamps are monotonic per slug (`state_since` ≤ `updated_at`).

Failure halts the workflow, reverts the commit, and pings maintainers.

## 3. Static identity: `data/reciter_catalog.json`

### Design principle: slug is opaque, catalog is structured

The slug is just a unique ID string. **No parser ever extracts semantic meaning from it.** All dimensions that matter — name, riwayah, style, source, year, variant grouping — are catalog fields. This decouples slug format from data dimensions: adding a new style or recording-year or any future axis is a schema-additive change to the catalog, never a slug reshape. Existing slugs and URLs and branch names stay valid forever.

### Schema (v2)

```jsonc
{
  "schema_version": 2,
  "reciters": {
    "alafasy_mujawwad": {
      "slug": "alafasy_mujawwad",
      "reciter_id": "alafasy",
      "name_en": "Mishary Rashid Alafasy",
      "name_ar": "مشاري راشد العفاسي",
      "country": "kw",
      "riwayah": "hafs_an_asim",
      "style": "mujawwad",
      "audio_source": "mp3quran",
      "audio_category": "by_surah",
      "url_template": "...",
      "recording_year": null,
      "variant_label": "Mujawwad",
      "is_canonical": false,
      "added_at": "2026-04-15T...",
      "added_by": "bob"
    }
  }
}
```

### Field semantics

| Field | Type | Required | Notes |
|---|---|---|---|
| `slug` | string | yes | Primary key. Matches the regex below. Immutable. |
| `reciter_id` | string | yes | Same shape as slug. Groups variants of the same human reciter. Defaults to slug for single-variant reciters. Immutable. |
| `name_en`, `name_ar` | string | yes | Display |
| `country` | ISO-2 code | yes | `unknown` if undisclosed |
| `riwayah`, `style`, `audio_source` | string | yes | Controlled vocab in `data/{riwayat,sources,styles}.json` |
| `audio_category` | enum | yes | `by_surah` or `by_ayah` |
| `url_template` | string | yes | Per [`timestamps-tab-deployment-plan.md`](timestamps-tab-deployment-plan.md) §3; empty allowed (forces per-verse map fallback) |
| `recording_year` | int | no | When same reciter+style+riwayah+source has multiple recordings |
| `variant_label` | string | no | Human-readable distinguisher in UI when ≥2 entries share `reciter_id` |
| `is_canonical` | bool | no | Exactly one `true` per `reciter_id`. Default landing variant when only `reciter_id` is requested |
| `added_at`, `added_by` | metadata | yes | Audit |

### Slug naming rules

Slug format is enforced only for safety, not for parsing:

- Regex: `^[a-z][a-z0-9_]{1,39}$`
- ASCII lowercase, single underscores between tokens, no double-underscore, no trailing underscore
- 2–40 characters
- Branch-name-safe and URL-safe by construction
- Immutable after first publish

Same rules for `reciter_id`. CI fails any catalog PR that violates them.

### Naming convention (advisory)

Maintainer judgment when picking a new slug. The convention exists to keep the catalog readable; nothing parses it.

```
<reciter_short_id>                            canonical/default rendition
<reciter_short_id>_<qualifier>                variant
<reciter_short_id>_<q1>_<q2>                  multi-dimensional variant
```

Examples:

```
ghamdi                  canonical Saad Al-Ghamdi (Hafs, Murattal, everyayah)
ghamdi_mujawwad         mujawwad variant
ghamdi_warsh            Warsh riwayah variant
ghamdi_2010             earlier recording
ghamdi_mujawwad_2010    combined
```

Most-distinguishing qualifier first. A maintainer breaking the convention is fine — the slug is still a valid unique ID, the catalog row still says what fields it has.

### Adding a new dimension later

The whole point of "slug opaque, catalog structured" is that future dimensions cost nothing. Adding `recording_year` (or any other field) is purely additive:

- The schema gains an optional field
- Existing rows have it `null` or absent
- New rows fill it in
- **Existing slugs are never reshaped.** `ghamdi` doesn't become `ghamdi_2005` retroactively when `ghamdi_2018` is later added — `ghamdi` keeps meaning whatever it meant when first published. The two coexist as distinct slugs sharing one `reciter_id`.
- No URL, branch, commit subject, or marker ever needs rewriting

The same holds for editorial flags, recording-venue tags, deprecation markers, alternate transliterations — anything we discover we need.

### Validation rules

CI runs `scripts/validate_reciter_catalog.py` on every PR touching the file:

- JSON parses; `schema_version` is 2
- Every `slug` and `reciter_id` matches the regex
- `riwayah`, `style`, `audio_source` exist in their respective controlled-vocab files
- `audio_category ∈ {by_surah, by_ayah}`
- `url_template` matches one of the two supported patterns or is empty
- At most one `is_canonical: true` per `reciter_id`
- No duplicate slugs

### Update path

- **Adds** come from the Reciter Requests intake — the Space submits a PR (or fires a workflow that opens one) that adds the entry. PR-reviewed by maintainer, merged.
- **Edits** (typo fixes, source corrections, adding optional fields) are also PRs, manually authored.
- **Adding a variant** of an existing reciter is just adding a new row with the same `reciter_id` as the existing canonical entry. The intake form prompts for "what's different about this recording?" mapping to style/riwayah/source/year so duplicate-slug-for-same-recording is avoided.
- On merge to main, a `push` event triggers `update-reciter-state.yml` with a synthetic `catalog_synced` event. The workflow adds new slugs to `reciter_state.json` with `state: catalogued`, re-renders any existing issue body referencing a changed field, and logs catalog-removal as a no-op (`discarded` flow deferred).

### Constraints

- Slugs and `reciter_id`s are immutable for now. A rename event would require coordinated PR-branch rename, history rewrite, dataset republish — deferred until a real need appears.
- Removing a row is not supported (use `discarded` flow when implemented).

### Migration (one-shot)

`scripts/migrate_catalog_v2.py` runs once during Phase 0:

1. Read existing identity sources (`data/reciters_index.json` + per-reciter audio manifests' `_meta`).
2. For each known reciter: emit a v2 row with `reciter_id = slug`, `is_canonical = true`, all other new optional fields null.
3. Bump `schema_version` to 2.
4. Run `validate_reciter_catalog.py`; commit.

No state-file changes. No PR-branch impact. Inspector reads new fields gracefully (`reciter_id` defaults to slug if missing; UI ignores absent variant fields).

## 4. State machine

### States

| State | Definition | Required state-file fields | Forbidden fields |
|---|---|---|---|
| `catalogued` | In catalog. No alignment work has started. | none beyond identity | `issue_number`, `pr_number`, `assignee` must be null |
| `awaiting_alignment` | Alignment pipeline pending or running. | `issue_number` | `pr_number`, `assignee` null |
| `awaiting_review` | Alignment done. PR exists. No reviewer claimed. | `issue_number`, `pr_number`, `pr_head_sha` | `assignee` null |
| `under_review` | A reviewer has claimed the PR. | `issue_number`, `pr_number`, `pr_head_sha`, `assignee`, `assignee_since` | none |
| `awaiting_timestamps` | Segments PR merged to main. TS data not yet on main. | `issue_number` | `pr_number`, `assignee` null |
| `completed` | Segments + TS both on main, in sync. | `issue_number` | `pr_number`, `assignee` null |

`assignee_since` is the only multi-field linkage with a temporal invariant — equal to `state_since` when state is `under_review`.

### Events

```
# Lifecycle
reciter.catalog_synced            # catalog file changed; add new slugs / propagate metadata changes
reciter.alignment_requested       # from Reciter Requests Space
reciter.alignment_completed       # pipeline finished, PR opened

# Review cycle
reciter.claimed                   # someone took the PR
reciter.released                  # claimant gave it back
reciter.review_merged             # segments PR merged to main

# Timestamps cycle
reciter.timestamps_completed      # TS data on main

# Admin
reciter.admin_override            # direct state edit via workflow_dispatch
```

Deferred (recognised but not implemented; schema will accommodate when needed):

```
reciter.alignment_failed
reciter.timestamps_failed
reciter.timestamps_stale
reciter.revision_opened
reciter.revision_merged
reciter.audio_source_changed
reciter.realignment_requested
reciter.discarded
```

### Transition matrix

| Event | From state(s) | To state | Side effects |
|---|---|---|---|
| `catalog_synced` (new slug) | (no row) | `catalogued` | Append history `added` |
| `catalog_synced` (existing) | any | (same) | Diff catalog; re-render issue body if field referenced there |
| `alignment_requested` | `catalogued` | `awaiting_alignment` | Open issue; set `issue_number`; mirror label |
| `alignment_completed` | `awaiting_alignment` | `awaiting_review` | Set `pr_number`, `pr_head_sha`; mirror label; comment on issue |
| `claimed` | `awaiting_review` | `under_review` | Set `assignee`, `assignee_since`; mirror to issue + PR |
| `released` | `under_review` | `awaiting_review` | Clear `assignee`; mirror |
| `review_merged` | `under_review` | `awaiting_timestamps` | Clear `pr_number`, `pr_head_sha`, `assignee`; mirror; trigger TS pipeline downstream |
| `timestamps_completed` | `awaiting_timestamps` | `completed` | Mirror; close issue |
| `admin_override` | any | (specified) | History entry includes `detail` with reason |

Invalid transitions (e.g. `claimed` while state is `completed`) are rejected by the workflow with a comment back on the originating event source (issue comment, PR comment, or workflow run log).

### Why re-edits don't get their own state

Once a reciter is `completed`, the reviewing surface for a fix-up PR is identical to first-time review — same branch name pattern, same Inspector entry point, same gate. Implementation: when a new PR is opened touching `data/recitation_segments/<slug>/` for an already-`completed` slug, fire `alignment_completed` (yes — same event). The workflow validates that no `pr_number` is currently set, then transitions back to `awaiting_review`. No new state needed. The existing CI that detects merged segment changes and regenerates timestamps already handles the TS staleness without an explicit `timestamps_stale` event.

## 5. The state workflow (`update-reciter-state.yml`)

### Triggers

```yaml
on:
  repository_dispatch:
    types:
      - reciter.catalog_synced
      - reciter.alignment_requested
      - reciter.alignment_completed
      - reciter.claimed
      - reciter.released
      - reciter.review_merged
      - reciter.timestamps_completed
      - reciter.admin_override
  push:
    branches: [main]
    paths:
      - 'data/reciter_catalog.json'        # synthetic catalog_synced
      - 'data/recitation_segments/**'       # detect direct merges
      - 'data/timestamps/**'                # detect direct ts pushes
  workflow_dispatch:
    inputs:
      slug:
      action:    # one of: claim, release, override, ...
      payload:   # JSON string

concurrency:
  group: reciter-state
  cancel-in-progress: false
```

### Job structure

One Python entry point, `scripts/update_state.py event_type [args...]`:

```
1. Load data/reciter_state.json into a StateStore.
2. Load data/reciter_catalog.json.
3. Resolve event payload → typed Event.
4. Validate Event against StateStore (state machine in §4, plus business rules below).
5. Apply transition → new StateStore.
6. Append history entry, truncate to 20.
7. Write data/reciter_state.json (atomic).
8. Commit with [state] <slug>: <event> subject. Push to main.
9. Mirror to GitHub:
   - Re-render issue body if any of (state, pr_number, assignee, catalog metadata) changed.
   - Set/unset labels.
   - Set/unset issue assignee, mirror to PR assignee in same call.
   - Post issue comment for events listed in §7 ("Automated comments").
10. POST /api/internal/state-changed on the deployed Inspector (best-effort, fire-and-forget).
```

### Business rules (workflow rejects events that violate)

- `claimed` is rejected if `state != awaiting_review` or `assignee` already set.
- `released` is rejected if `state != under_review` or `assignee != event.by`.
- `review_merged` is rejected if `state != under_review`.
- `alignment_completed` is rejected if there is already an `active_pr` on the same slug (prevents duplicate alignment runs).
- `admin_override` is the only way to set `state` to a value the matrix doesn't permit; requires a `detail` reason.

Rejection posts a comment on the source artifact (the issue or PR or workflow_dispatch run log) explaining the rejection, and exits non-zero. State file is unchanged.

### Concurrency and queue

`concurrency: { group: reciter-state, cancel-in-progress: false }` ensures one run at a time across the whole repo. Burst capacity = GitHub Actions queue depth (effectively unbounded for our scale). Each run is fast (parse → validate → write → push → mirror) — empirically <30 s. Realistic write rate <50/day, so queueing is non-issue.

### Webhook reliability

GitHub repository_dispatch is delivered with at-least-once semantics, but webhook delivery (for the `push` triggers) is best-effort. To mitigate missed events:

- The `push` trigger on `data/recitation_segments/**` re-runs `catalog_synced` style reconciliation — if a reciter's `pr_number` is set but the PR is closed-not-merged, sweep it.
- A separate scheduled workflow (`reciter-state-reconcile.yml`, cron daily) does a full sweep: walks the catalog, checks each slug's expected GitHub primitives (issue, PR, labels), logs any drift. Drift fixes are applied via `admin_override` events, not silently corrected.

## 6. Identity convention — full registry

### Branch

```
reciter/<slug>
```

The single review branch for any review work on that reciter. No `kind` suffix — TS pushes go direct to main.

### Issue title

```
[request] <slug>: <Display Name>
```

Example: `[request] saad_al_ghamdi: Saad Al-Ghamdi`

### PR title

```
[<slug>] <description>
```

Bot-created initial PR: `[saad_al_ghamdi] alignment for Saad Al-Ghamdi`

### Squash-merge subject (the one that lands on main)

Configure GitHub squash-merge to override the default with:

```
[<slug>] segments review (#<pr_number>)
```

Generic phrasing; per-edit detail lives in the squashed-out commits, accessible via `git log --grep` if needed.

### Commit subjects

| Source | Subject pattern | Example |
|---|---|---|
| Inspector contributor edit (debounce) | `[<slug>] [wip] <op summary>` | `[saad_al_ghamdi] [wip] trim 2:34:1 left edge` |
| Inspector multi-op debounce | `[<slug>] [wip] segments edit (<n> ops)` | `[saad_al_ghamdi] [wip] segments edit (4 ops)` |
| Inspector explicit push | `[<slug>] <message>` | `[saad_al_ghamdi] segments edit` |
| Pipeline (alignment) | `[<slug>] [pipeline] alignment` | `[saad_al_ghamdi] [pipeline] alignment` |
| Pipeline (timestamps) | `[<slug>] [pipeline] timestamps refresh` | `[saad_al_ghamdi] [pipeline] timestamps refresh` |
| State workflow | `[state] <slug>: <event>` | `[state] saad_al_ghamdi: claimed by alice` |
| Catalog change (manual PR) | conventional commit | `feat(catalog): add saad_al_ghamdi` |

### Author attribution

| Source | Author | Committer |
|---|---|---|
| Inspector edit | Contributor (`<id>+<login>@users.noreply.github.com`) | Same as author |
| Pipeline push | `github-actions[bot]` | `github-actions[bot]` |
| State workflow | `github-actions[bot]` | `github-actions[bot]` |
| Catalog PR merge | PR author | PR author |

The Inspector edit case uses the GitHub App installation token to push but sets `author` and `committer` to the contributor's no-reply email. Contribution graph credits the contributor; the bot just delivered the bytes. This is the documented exception to the "all bot artifacts as `github-actions[bot]`" rule.

### Marker registry

All markers are HTML comments — invisible in rendered Markdown. `scripts/lib/markers.py` owns parse/render for every entry below; no ad-hoc string manipulation in workflows.

| Marker | Where | Purpose |
|---|---|---|
| `<!-- reciter-task: slug=<slug> schema=1 -->` | Issue body | Identity (permanent) |
| `<!-- reciter-task: slug=<slug> issue=<n> schema=1 -->` | PR body | Identity + issue link (permanent) |
| `<!-- reciter-state-snapshot: state=<state> at=<iso8601> -->` | Issue/PR body | Latest snapshot, rewritten on every transition |
| `<!-- reciter-state-comment: event=<event> slug=<slug> run=<run_id> -->` | Issue comment | Workflow-generated state comment (one per event with a `run` id for dedup) |

`run=<run_id>` allows the workflow to detect a duplicate event firing twice (at-least-once delivery semantics) and skip the second comment.

### Labels (optional, mirrored from file)

If maintainers use GitHub label filters: maintain exactly one `state:*` label on each issue and on the active PR, mirrored from the file. Plus one fixed classifier label.

```
state:catalogued
state:awaiting_alignment
state:awaiting_review
state:under_review
state:awaiting_timestamps
state:completed

reciter-request          # fixed classifier on every reciter issue
```

The state workflow ensures exactly one `state:*` label on every issue and PR. Manual edits get reverted on the next workflow run. If maintainers don't use GitHub label filters, drop labels entirely — body markers are the parser surface.

## 7. Body templates and automated comments

### Issue body (re-rendered by the state workflow on every transition)

```markdown
<!-- reciter-task: slug=saad_al_ghamdi schema=1 -->
<!-- reciter-state-snapshot: state=under_review at=2026-05-08T14:23:11Z -->

**[Open in Inspector](https://<inspector_url>/r/saad_al_ghamdi)**

| | |
|---|---|
| Slug | `saad_al_ghamdi` |
| Display | Saad Al-Ghamdi |
| Riwayah | Hafs an Asim |
| Style | Murattal |
| Audio source | everyayah |
| State | `under_review` (snapshot 2026-05-08T14:23:11Z) |
| PR | #89 |

---
*Live state in [`data/reciter_state.json`](https://github.com/.../blob/main/data/reciter_state.json). Claim/release in the [Inspector](https://<inspector_url>/r/saad_al_ghamdi) — labels and assignees here are mirrors.*
```

The PR row is omitted when `pr_number` is null. Catalog rows pull from `reciter_catalog.json` at render time so a typo fix propagates automatically on the next state event.

### PR body (set once at PR creation; not re-rendered)

```markdown
<!-- reciter-task: slug=saad_al_ghamdi issue=42 schema=1 -->

**[Open in Inspector to review](https://<inspector_url>/r/saad_al_ghamdi)**

Closes #42

| | |
|---|---|
| Slug | `saad_al_ghamdi` |
| Display | Saad Al-Ghamdi |
| Issue | #42 |
| Pipeline | `extract_segments.py` (commit `<sha>`) |

---
*Reviews happen in the [Inspector](https://<inspector_url>/r/saad_al_ghamdi). Edits commit to this branch as `[<slug>] [wip] ...` and squash-merge into main. Don't review file diffs here — too much noise.*
```

`Closes #42` keeps GitHub's auto-link active.

### Automated issue comments

Sparse — most transitions are body updates only. Comments fire only on:

| Event | Comment template |
|---|---|
| `alignment_completed` | "Alignment ready for review. [Open in Inspector](...)." |
| `timestamps_completed` | "Timestamps complete. Reciter is live in the dataset." (and close issue) |
| `admin_override` | "State set to `<state>` by @maintainer. Reason: …" |

Each comment carries `<!-- reciter-state-comment: event=<event> slug=<slug> run=<run_id> -->` for dedup.

### No automated PR comments

PR validation results go to the GitHub Checks API (status badge), not comments. Inspector shows the rich validation panel. PR timeline stays clean. Merge conflicts and exceptional admin overrides also go silent on the PR — the events still produce issue comments and state-file history, which is enough.

### Inspector URL convention

| Path | Page |
|---|---|
| `/` | Tab listings (Available / Under review / Completed) |
| `/r/<slug>` | Reciter view, last-active tab |
| `/r/<slug>/segments` | Segments tab |
| `/r/<slug>/timestamps` | Timestamps tab |
| `/r/<slug>/audio` | Audio tab |
| `/r/<slug>?validation=<sha>` | Segments tab with validation panel scrolled to the run |

Slug is URL identity. Stable as long as slugs are immutable (which they are; rename deferred).

## 8. Inspector integration

### API endpoints

```
# Identity
GET  /api/me                       → { login, id, noreply_email, is_collaborator }
GET  /api/me/collaborator-status   → { is_collaborator }   (polled after invite)

# State reads (all sourced from parsed reciter_state.json + reciter_catalog.json)
GET  /api/reciters                 → [{ slug, display, state, riwayah, style }]
                                     served from in-memory cache; refreshed on state-changed webhook or 30 s poll
GET  /api/reciter-task/<slug>      → full ReciterTask + can_edit_for_current_user

# Claim flow (mutating — fire dispatch, return 202)
POST /api/claim/<slug>             → fires reciter.claimed; returns 202 with optimistic state
DELETE /api/claim/<slug>           → fires reciter.released; flushes pending edits before dispatch

# Internal (workflow → backend)
POST /api/internal/state-changed   → wakes the in-memory cache (auth via shared secret)
POST /api/internal/cache-invalidate → drops github-fetch entries (existing per data-storage doc)
```

### State refresh strategy

- **On startup:** fetch `reciter_state.json` + `reciter_catalog.json` via `services/github_fetch.py` at `main` ref; parse into in-memory `StateStore`.
- **On webhook:** `POST /api/internal/state-changed` from the workflow → re-fetch + re-parse.
- **As fallback:** 30 s poll. Webhook miss results in at most 30 s of staleness.
- **Per-request lookup:** dict access on the parsed store. O(1).

### Optimistic UI

`POST /api/claim/<slug>` returns 202 immediately after firing dispatch. Frontend optimistically flips lock-banner / claim-button state. On the next state-refresh tick (~10 s typical), the file change propagates and the optimistic state either reconciles silently or — if the workflow rejected the event — flips back with a toast explaining why.

### `can_edit_for_current_user`

Computed server-side in the `/api/reciter-task/<slug>` response:

```python
def can_edit(entry: ReciterStateEntry, user: User | None) -> bool:
    if user is None:
        return False
    return entry.state == 'under_review' and entry.assignee == user.login
```

The same predicate gates `@require_edit_lock` on every mutating endpoint. Frontend hiding is cleanliness; backend rejection is security.

## 9. GitHub App permissions

The Inspector App needs:

| Resource | Permission | Why |
|---|---|---|
| Contents | Read & write | github-fetch (read) and Git Data API commits (write) |
| Pull requests | Read & write | Open PRs from `bot-create-pr.yml`; sync assignees |
| Issues | Read & write | Create issues, post comments, mirror labels/assignees |
| Metadata | Read | Required for any API call |
| Members | Read | Collaborator status check |
| Administration | Write | `PUT /collaborators/{login}` (invite) |

The App's installation token is what github-fetch and the commit pathway use. The contributor's OAuth token (issued by the App's user-token flow) is only used for identity establishment — never for repo writes.

## 10. Downstream consumers and producers

The new files (`reciter_catalog.json`, `reciter_state.json`) are upstream of several producers that today derive their output from on-disk data + the legacy `reciters_index.json`. After Phase 0 lands, these producers must be reworked to read from the new files — otherwise they silently go stale.

### Files derived from catalog + state

| Output | Producer | Pre-migration source | Post-migration source |
|---|---|---|---|
| `data/reciters_index.json` | `.github/scripts/list_reciters.py` | walks data tree + ad-hoc inferences | catalog (identity) + state (status) + data tree (only for `coverage` / `has_timing`) |
| `data/RECITERS.md` | same | same | same |
| README badge counts | same | same | same |
| HF dataset `manifest.json.gz` | `.github/scripts/build_reciter.py --build-manifest` | per-reciter audio manifests + ts data | catalog (identity) + state (`completed` filter) + ts data (shard hashes) |
| GitHub release `manifest.json` | `.github/scripts/package_release.py` | `reciter_eligibility.py` (file-presence check) | (optional) `state == "completed"` lookup; file-presence check is still correct so long as state workflow is bug-free |
| Publish-email summary | `.github/scripts/send_publish_email.py` | `reciters_index.json` | catalog directly, or via the regenerated `reciters_index.json` |

### Keeping `reciters_index.json` alive (transitional)

External consumers — the Reciter Requests Space chiefly — read `reciters_index.json` for the catalog of known reciters. Two paths:

A. **Keep regenerating** as a derived snapshot. `update-reciters.yml` rebuilds it from `reciter_catalog.json` + `reciter_state.json` + on-disk data on every relevant change. External consumers see no change.
B. **Drop entirely** and update external consumers to read both new files directly.

**Decision:** start with (A) (low-risk migration), schedule (B) as later cleanup once the Reciter Requests Space and any other external readers are migrated.

### `sync-dataset.yml` triggers

Today triggers on `data/audio/**`, `data/timestamps/**`. Add:

- `data/reciter_catalog.json` — identity changes (typo fixes, source corrections, new variants) propagate to the HF manifest's per-reciter block.
- `data/reciter_state.json` — transitions to `completed` should pull a reciter into the next HF publish window. Today this is implicit via segments/timestamps file presence; making it explicit removes ambiguity when the state workflow lands a transition before the actual data files are written by their respective pipelines.

`update-reciters.yml` listens on the same paths so `reciters_index.json` and `RECITERS.md` stay current.

### Staleness scenarios if migration is partial

| Scenario | Symptom | Mitigation |
|---|---|---|
| `list_reciters.py` not updated | `reciters_index.json` regenerated from old logic; new catalog fields (variant_label, recording_year, etc.) invisible to external consumers | Rewrite is in scope of Phase 0 |
| `--build-manifest` not updated | HF manifest carries stale name/riwayah/url after a catalog typo fix | Rewrite is in scope of Phase 0 |
| `package_release.py` left on file-presence check | Two truth sources for "is reciter completed"; can diverge if the state workflow has a bug | Optional cleanup in Phase 6; works correctly so long as the state workflow is bug-free |
| Reciter Requests Space points at old `reciters_index.json` shape | Space's reciter dropdown stale on new fields | Keep regenerating until the Space is updated |
| `sync-dataset.yml` triggers not extended | Catalog edits don't republish the HF manifest | Add catalog/state paths to the workflow's `paths:` filter |

### `data/.release_history.json` (clarification)

Earlier internal docs and CLAUDE.md reference `data/.release_history.json` for release versioning. The actual implementation in `package_release.py::compute_version` reads version history from the previous GitHub release's `manifest.json`, not a local file. There's nothing to migrate here — the reference in CLAUDE.md should be corrected.

## 11. Phased rollout

This doc's scope lands primarily in **Phase 0** (foundational state work) and bleeds slightly into Phases 1, 3, 5a, and 6.

### Phase 0 — Foundation

**In scope of this doc:**
- Land `scripts/lib/reciter_task.py` (resolver) and `scripts/lib/reciter_state.py` (file parser, state machine, mirror helpers).
- Land `scripts/lib/markers.py` for parse/render of every HTML-comment marker.
- Create `data/reciter_catalog.json` — v2 schema, split static identity out of existing `reciters_index.json`. One-shot migration script.
- Create `data/reciter_state.json` — seeded from current GitHub state via a one-shot script that walks open issues, open PRs, and the on-main data tree.
- Land `scripts/update_state.py` with the validate-apply-mirror pipeline.
- Land `update-reciter-state.yml` workflow with all dispatch triggers.
- Migrate existing workflows to fire `repository_dispatch` events instead of writing labels/assignees.
- Decommission `pr-assignee-sync.yml`, `find_segments_pr.py`.
- Land `scripts/validate_reciter_state.py` + `scripts/validate_reciter_catalog.py` + CI gates.
- **Rewrite `list_reciters.py`** to read from catalog + state + data tree (per §10).
- **Rewrite `build_reciter.py --build-manifest`** to read identity from catalog (per §10).
- **Extend `sync-dataset.yml` and `update-reciters.yml` triggers** to include catalog and state file paths (per §10).

**Acceptance:**
- `data/reciter_state.json` parses, validates, and matches observable GitHub state for every existing reciter.
- `data/reciter_catalog.json` v2 parses, validates, every existing reciter has a row with `reciter_id = slug` and `is_canonical = true`.
- Regenerated `reciters_index.json` is byte-identical (or differ only in newly added fields with documented null values) compared to the pre-migration version, so external consumers see no breakage.
- HF `manifest.json.gz` rebuilt against catalog produces the same per-reciter metadata as the pre-migration build, plus any catalog corrections.
- A test event (`workflow_dispatch` with `claim`) successfully transitions a test reciter, mirrors to the issue, and re-renders the body — within 30 s end-to-end.
- The reconciler workflow finds zero drift on a clean post-migration state.
- All retired workflows produce no runs over a 7-day observation window.

### Phase 1 — Read-only deploy

**In scope of this doc:**
- Inspector backend reads `reciter_state.json` + `reciter_catalog.json` via github-fetch on startup; in-memory `StateStore`.
- `/api/reciter-task/<slug>`, `/api/reciters` endpoints serve from the parsed store.
- 30 s poll fallback for webhook miss.

**Acceptance:**
- Anonymous viewer sees correct state pills and tab partitioning for all reciters within 30 s of any state event.

### Phase 3 — Claim flow

**In scope:**
- `/api/claim/<slug>` and `/api/release/<slug>` fire dispatch events.
- Optimistic UI flip + reconciliation on poll.
- `/api/internal/state-changed` webhook receives invalidation hits from the workflow.

**Acceptance:**
- Logged-in collaborator clicks Claim, sees lock banner flip within ~3 s (optimistic) and reconciles to authoritative within 30 s.
- Two simultaneous claim attempts on the same reciter: one succeeds, one is rejected with a clear toast (workflow business rule).

### Phase 5a — Writes

**Out of scope of this doc** beyond reusing the `assignee` lookup for `@require_edit_lock`.

### Phase 6 — Cleanup

**In scope:**
- Switch `update-reciters.yml` to read from the state file (it now generates `RECITERS.md` and badges only).
- Slow `update-reciters.yml` cadence to every 30 min (reduce CI minutes).
- Add the daily `reciter-state-reconcile.yml` cron sweep.

## 12. Risks and open questions (beyond what the parent doc covers)

### State file corruption from a workflow bug

A bug in `scripts/update_state.py` could write structurally-valid but semantically-wrong state (e.g. assignee set on `awaiting_review`). The CI validator (§2) catches schema violations but not semantic ones. **Mitigation:** the workflow's commit subject `[state] <slug>: <event>` makes `git revert` a one-liner. The reconciler workflow catches drift on the next daily sweep. Acceptable as long as the validator covers the field-presence invariants in §4.

### Webhook delivery loss

GitHub webhook delivery is best-effort. A dropped `push` event on the catalog file means a new reciter never enters the state file. **Mitigation:** the reconciler cron sweep (§5) backfills. Worst-case latency to detection: 24 hours. If we need tighter, run hourly.

### Catalog ↔ state drift

A catalog PR adds slug `X` to `reciter_catalog.json`. The push event fires `catalog_synced`, but the workflow run fails for any reason (rate limit, App token expired). Slug `X` exists in catalog but not in state. **Symptom:** Inspector lists slug `X` in the dropdown with no state pill. **Mitigation:** the reconciler workflow detects "catalog has slugs the state file doesn't" and adds them. **Acceptance:** Inspector frontend treats missing-from-state as `state: catalogued` (graceful degradation).

### Stalled `awaiting_alignment`

Pipeline runs the alignment job, then the runner crashes before firing `alignment_completed`. State file stays in `awaiting_alignment` forever. **Mitigation:** detect via reconciler — if `awaiting_alignment` for more than N hours and no in-flight pipeline run found, flag for maintainer. No automatic recovery (don't re-run alignment automatically; pipeline is expensive).

### Stalled `awaiting_timestamps`

TS pipeline fails. State stays `awaiting_timestamps`. **Mitigation:** reconciler flags after N hours; maintainer triggers `timestamps-refresh.yml` manually with the slug, which on success fires `timestamps_completed`.

### Manual GitHub UI edits

A maintainer manually toggles the `state:under_review` label on an issue. The next state workflow run reverts it. Without explanation, that's confusing. **Mitigation:** the workflow's mirror step detects "incoming label state doesn't match file state" and posts a one-time comment on the issue: `"Label set to X manually but file state is Y. Reverted to match file. To override, fire admin_override via workflow_dispatch."` Comment carries a marker so it's only posted once per drift event.

### History array cap

History is bounded to 20 entries per reciter. The 21st event drops the oldest. Full history is in `git log -- data/reciter_state.json`, but `git log` won't show *why* a transition happened — only the commit subject. **Mitigation:** the commit message body for `[state]` commits embeds the event payload as JSON. So `git show <sha>` recovers full event detail; the in-file array is the recent-history view for tooling.

### Optimistic UI on workflow rejection

User clicks Claim. Frontend optimistically flips. Workflow rejects (e.g. someone else claimed in the same second). Frontend reconciles back. **UX:** the user sees lock-banner flip-then-flip-back over ~10 s. **Mitigation:** the 202 response includes a poll endpoint URL the frontend can hit at higher cadence (1 s) for the first 10 s after a claim, falling back to 30 s. If the reconciliation finds the workflow rejected the event, surface a toast: `"Claim failed — @<other_user> claimed it first."`.

### Concurrent dispatch storm

Pathological case: many reciters complete alignment in a burst, firing N `alignment_completed` events. The singleton workflow serializes; queue grows. Each run is <30 s, so 100 events = ~50 min worst case. Tolerable for our scale. **Mitigation if pain:** batch handler — workflow drains the queue in a single run by accepting up to M dispatch events. Defer until measured.

### App token expiry mid-mirror

The state workflow runs <30 s end-to-end, well within the 1-hour App token TTL. Not a real risk for the workflow, but the *Inspector backend's* in-memory App token can expire while idle. Already handled in [`inspector-data-storage.md`](inspector-data-storage.md) §10.

### Slug rename

Currently impossible — slugs are immutable. If we ever need it: a `slug_renamed` event would have to coordinate (a) catalog edit, (b) state file edit with old-slug tombstone or alias, (c) PR-branch rename, (d) issue edit, (e) historical commits with old slug in subject preserved as-is, (f) HF dataset republish under new slug. **Decision: defer until a real rename request appears.**

### PR closed without merging

Currently no event for this. If a maintainer closes a review PR without merging, `pr_number` stays in the state file pointing at a closed PR. **Symptom:** Inspector shows `under_review` or `awaiting_review`, but the PR is dead. **Decision (deferred):** treat closed-not-merged as `discarded` once we implement that flow. Until then, reconciler flags the drift.

### Force-push on `reciter/*` branches

A force-push could destroy Inspector edits in flight. **Mitigation:** branch protection rule — block force-push on `reciter/*` for everyone except the App. The App itself uses `force = false` on ref updates (per [`inspector-data-storage.md`](inspector-data-storage.md) §5), so there's no legitimate force-push.

### Test fixtures

E2E tests of the state machine need test slugs. Convention: any slug starting with `_test_` lives in `reciter_catalog.json` under a separate `_test_reciters` block (gitignored from `RECITERS.md` generation). State workflow accepts events on test slugs but skips the GitHub mirror step. Lets us run integration tests without polluting real issues.

### Production vs staging state file

If staging and production deploys point at the same repo's state file, a staging test claim would fire a real workflow run and update real state. **Decision:** staging deploys use a separate `INSPECTOR_GITHUB_REPO` pointing at a fork of the repo, with its own state file. Documented in deployment config; defer concrete fork setup until staging is needed.

### Inspector cold-start state-file fetch

On every backend boot, fetch state file + catalog file. Two github-fetch calls. If GitHub is unreachable, backend boot fails. **Mitigation:** ship a stale snapshot of both files in the Docker image as a fallback. Boot succeeds with stale data; first webhook or poll refreshes.

### Partial producer migration

Phase 0 lands the catalog + state files but doesn't atomically rewrite every consumer in the same commit. During the migration window, `reciters_index.json` may be regenerated from the old logic by a stale `list_reciters.py` while the catalog has new fields. **Symptom:** external consumers (Reciter Requests Space) see partial data. **Mitigation:** land all of (catalog v2, state file, list_reciters rewrite, build-manifest rewrite, sync-dataset trigger extension) in one merge group, gated by a CI integration test that diffs the regenerated `reciters_index.json` against the pre-migration version.

### `reciter_id` collision with future variants

A reciter is added today as the canonical entry with `reciter_id = slug = ghamdi`. Years later, a maintainer wants to add a Mujawwad variant: `slug = ghamdi_mujawwad`, `reciter_id = ghamdi`. This works, but the original entry's `reciter_id = ghamdi` is now ambiguous in dropdown grouping if the canonical bit isn't set right. **Mitigation:** the catalog validator enforces "exactly one `is_canonical: true` per `reciter_id`", and the migration script sets `is_canonical = true` on every row by default. So when a variant is added later, the maintainer must explicitly mark the original as canonical (already true) and the new one as non-canonical, or flip canonicity if the variant should be the new default. CI catches both-true and both-false cases.

### `variant_label` drift

UI groups by `reciter_id` and shows `variant_label` when count > 1. If a maintainer leaves `variant_label` null on a non-canonical entry, the UI falls back to slug. Acceptable but ugly. **Mitigation:** lint warning (not error) when `is_canonical = false` and `variant_label` is null.

### Reciter Requests intake doesn't know about variants

The current Reciter Requests Space form asks for "reciter name + audio source." A contributor submitting a request for the Mujawwad variant of an existing reciter has no way to express that — the form would just create a duplicate-slug-for-same-recording or reject with "reciter exists." **Mitigation:** Phase 0 extends the intake form with optional fields (style override, riwayah override, recording year, "what's different about this recording") that map to catalog fields. The Space gates new-slug creation on those fields being distinguishing — if every distinguishing field matches an existing entry, reject with "this recording is already catalogued."
