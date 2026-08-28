# QUL integration — internal plan

Internal counterpart to [`proposal-qua-revised.html`](proposal-qua-revised.html) (the public
contract sent back to QUL; [`original-proposal.html`](original-proposal.html) is their draft,
preserved verbatim inside the revised file). **Nothing in this file is shared with QUL.** Every
section below maps one public commitment onto the internal work that delivers it.

Status: decisions locked in the 2026-08-28 review session; no implementation started.

## Decision register (locked)

| # | Decision |
|---|---|
| 1 | GH releases are the sole segment-delivery surface; no per-job segments endpoint. |
| 2 | Release format v2 ("B′"): flat ordered timeline per tier, one row per contiguous occurrence, `canonical` flag (earliest complete continuous take), compact positional rows. Partial (leading/trailing) repeats are their own rows; within-take lookbacks stay embedded and unflagged. |
| 3 | `end` = last audible; `silence_after` precomputed on verse rows only, timeline-relative; no `ends_includes_silence` toggle. |
| 4 | Letter tier **deferred** pending the tokenization audit (below). |
| 5 | Shared IDs = our slugs (reciter / recitation / riwayah); QUL ints echoed opaque; `qiraah` renamed `riwayah`. |
| 6 | No word `text` in any tier. |
| 7 | Issues flow QUA→QUL only, audio-domain catalogue: `missing_ayah_audio`, `missing_word_audio`, `mispronunciation`, `corrupted_audio`. Webhook push + GET reconciliation. |
| 8 | Issue resolution: detectable types close by re-check after re-segmentation; listener-reported types close on QUL's `issue_ids` claim. We own `status`. |
| 9 | Inbound API = resegment requests only. `scope` = list of ayah selectors or `"full"`; ranged scope declares time-preservation outside the union, we verify and fall back to full with notice. |
| 10 | Callbacks: two-phase slim (`fixed {target_release}` → `released {version, url}`). |

## Workstream A — release format v2 (B′)

The projection layer, not the shards: bucket shards already store every occurrence raw.

- **Projection**: `qua_shared/timestamps_dedup.py` — today `project_segment_shard` returns the
  canonical take only. Add an all-occurrences projection that emits every occasion (merged
  contiguous runs, same grouping as today) with the canonical one flagged, reusing the existing
  earliest-completing selection for the flag. Leading/trailing partials that the current
  projection trims become their own occurrence rows (they are occasions/segments already —
  emission, not new detection).
- **Tier builders**: `qua_jobs/cut_release.py` — verse/word tiers become flat arrays
  `[ref, start, end, canonical, silence_after (verse only), words (word tier)]` in recitation
  order. `silence_after` computed at build from the next timeline row (0 when contiguous;
  last row of a chapter: gap to chapter audio end if known, else 0 — decide at implementation).
- **Letter tier**: build keeps producing the *current* letter layout until Workstream B lands;
  the release notes mark it schema-v1-frozen. Do NOT bolt B′ onto letters prematurely.
- **HF dataset**: stays canonical-only for now (per-verse rows, embedded audio). Revisit after
  QUL adoption; not part of this integration.
- **Completeness gate**: `select_complete_verses` still gates *canonical* rows. Non-canonical
  occurrence rows are exempt by design (a partial repeat is incomplete by definition). A verse
  whose canonical take is incomplete stays fully absent (all its occurrences dropped) — matches
  the published coverage semantics.
- **Validation**: `qua_shared/dataset_validation.py` needs multi-occurrence awareness
  (per-occurrence span checks; canonical-uniqueness-per-verse as a new HARD_FAIL kind).
- **Versioning**: this is the MAJOR bump case (operator-supplied `vX.0.0` per the versioning
  table). `schema_version` in tier `_meta` bumps; changelog template
  (`docs/templates/release_body.md`) gets the new row shapes + canonical-filter one-liner.
- **Consumer helpers**: `check_updates.py` unaffected; `shard.py` + `download_audio.py`
  (`--format ayah` cuts at verse spans) must read the new verse-tier shape.

## Workstream B — letter tokenization audit (blocks the letter tier)

Deferred decision. Scope of the audit:

- Cell-like tokenization vs original-script letter rows — what granularity does the public
  letter tier promise? (Internal shards: letter row = rasm graphemes, haraka stripped, dagger
  alif its own row, seat+dagger co-timed rows; cells = mark-level with roles/status.)
- 42-token external vs 57-token internal alphabet (`qua_shared/letter_vocab.py` — maddah +
  silent-zero drop). Verified session facts: `عَلَىٰ` / `صَلَوٰة` → seat letter + dagger as two
  co-timed rows; standalone sounding dagger (`ٱلرَّحْمَٰنِ`) owns its span.
- Whether the published tier gains the shard v4 `silent` flag (`[widx, char, start, end, silent]`)
  — today's release layout drops it, which leaves co-timed seat/dagger rows ambiguous for
  highlighters. Leaning yes; decide inside the audit.
- Phonemizer tokenization review + the shard v12 question (whether a shard-format change is
  wanted at the same time), source-script revisions.
- Output: a versioned public addendum (the §10 promise in the revised proposal) + the letter
  tier joins B′ in a subsequent release.

## Workstream C — partner API (inbound)

- New blueprint (e.g. `routes/partner/`), thin per convention; service logic Flask-free.
- **Auth**: HMAC shared-secret verification util (`X-QUL-Signature` + `X-Timestamp`, 5-min skew)
  — machine partner, not a user; secrets via Space config. Not a capability gate (no user tier),
  but admin visibility surfaces below.
- **Store**: new `partner_requests` table (migration): `request_id` (unique, idempotency),
  recitation slug, surah, audio {url, checksum, duration_ms, qul_audio_file_id}, scope JSON,
  issue_ids JSON, notes, status `queued|processing|fixed|released|failed`, `target_release`,
  `released_version`, timestamps. Written inside `durable_transaction`, audited.
- **Endpoints**: `POST /api/v1/resegment-requests` (202 + idempotent replay),
  `GET /api/v1/resegment-requests/<id>`.
- **Admin surface**: requests appear in the admin Jobs/Requests view for owner triage — intake
  does NOT auto-launch pipelines. Owner accepts → runs the resegment flow (Workstream E).

## Workstream D — issues subsystem (outbound)

- **Store**: new `partner_issues` table: stable issue id, type, slug, surah, ayah, word_number?,
  span ms?, comment?, source (`ts_report|seg_flag|publish_gate`), status `open|resolved`,
  detected_at, resolved_at, resolution (`recheck|claimed`).
- **Delivery**: outbox pattern (single-worker safe): issue writes enqueue a webhook delivery row;
  a lightweight retrier (reuse the automation reconciler cadence) POSTs to QUL with backoff;
  `GET /api/v1/recitations/<slug>/issues` + global GET read the table directly.
- **Sources / promotion gates** (all internal, none leaked):
  1. **TS-tab audio reports auto-forward** (decision: no owner confirmation). Prereq: formalize
     the `audio` category in `ts_reports` with typed subtypes (pills) matching the public
     catalogue + keep the free comment; forward includes verse ref, verse timestamps, comments.
     FE: ReportComposer pill row; wire model + `ts_reports.subtype` values.
  2. **Segments-tab flag formalization**: `flag_segment` gains first-class audio-issue types;
     flagging a segment with one promotes an issue (reviewer trusted) carrying slug, surah,
     verse, verse timestamps.
  3. **Publish-time auto-promotion**: at HF/GH publish, remaining coverage gaps promote —
     `missing_ayah_audio` when the verse has no recited words in the shard, `missing_word_audio`
     with the specific widx range when partially recited (the gate drops the verse either way;
     the shard distinguishes). Source of truth = the same `select_complete_verses` +
     `missing_coverage` pass the cut already runs — no new detection.
- **Resolution**:
  - Detectable: after a resegment request's re-ingest + re-align completes, re-run the
    detection over the affected scope; close issues whose condition cleared, keep the rest open.
    (Same philosophy as ts_reports silence auto-resolve-on-regen.)
  - Listener-reported: close when a request lists them in `issue_ids` **and** the request
    reaches `fixed`; audio-diff spot-check flagged for owner review.
- **Basmala guard**: promotion respects the Fatiha `1:1` exception; other basmalat never
  promote (they are outside timed spans by policy).

## Workstream E — resegment pipeline

- **Intake validation**: fetch replacement audio, verify checksum + duration; probe encode.
- **Time-preservation verification** (ranged scope): duration delta vs current source + spot
  audio-diff outside the scope union; on failure → escalate to full with a notice callback.
- **Ranged path**: re-align the union spans with ±1-verse context buffer, splice into the
  per-reciter artefacts surgically — precedent: the single-chapter realign + reconcile flow
  (6-file splice, format-guarded). New audio replaces the affected chapter audio (or offsets
  update), metadata reprobed.
- **Full path**: standard re-extraction + full chapter re-alignment; existing timings for the
  file superseded.
- **Post**: TS regen for affected chapters → existing staleness cascade (`ts_regen` → HF/GH
  stale) → rides the next cut. `fixed` callback fires when the corrected timestamps land
  internally (regen complete), carrying `target_release: "next"`.
- **Open internal decision**: whether `target_release` can carry a concrete predicted version
  (auto-version is only computed at cut preview) — start with the literal `"next"` +
  release-preview version when cheaply available.

## Workstream F — callbacks

- Outbox + retrier shared with Workstream D deliveries; signed `X-QUA-Signature`.
- `fixed` fires from the regen-complete path for the request's scope; `failed` from any
  terminal pipeline error; `released` fans out from the GH cut completion hook
  (`services.admin.jobs.cut_release.complete()`) to every `partner_requests` row in `fixed`
  whose recitation is in the cut membership — set `released_version`, deliver callback,
  trigger issue re-check closure sweep.

## Workstream G — docs for QUL (public)

- ID adoption note: slug stability guarantees (immutable, never repurposed), riwayah vocab
  export, where slugs appear in release artifacts.
- Release-consumption runbook already exists in the release body; extend with the canonical
  filter + B′ row shapes when v2 cuts.
- The audio-integration plan (original-source vs mirrored encode indexing) — separate doc,
  owner-authored, referenced as an open question in the proposal.

## Sequencing

1. **Send the revised proposal** (no code dependency).
2. Workstream B audit (blocks letter tier; independent of everything else).
3. Workstream A (release v2) — can cut before the API exists; QUL can adopt the format early.
4. Workstreams C + D stores/endpoints + F outbox (one delivery substrate).
5. Workstream E pipeline (heaviest; ranged path can trail the full path).
6. D promotion sources (TS-tab pills, seg-flag formalization, publish-gate promotion) —
   incremental, each independently shippable.

## Leak boundary (reminder)

Public = the revised proposal's content only: endpoint shapes, row schemas, catalogue, slugs,
lifecycle semantics, shared-understanding facts (§0). Internal-only: every store/table name,
ts_reports/flag_segment machinery, promotion gates, review process details, pipeline/HPC
mechanics, bucket layout, staleness/ledger internals, this file.
