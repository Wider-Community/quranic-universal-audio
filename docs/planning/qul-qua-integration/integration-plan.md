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

- **Projection**: post-v12 this is `qua_shared/timestamps_native.py::project_native_shard`
  (v12 `.json.br` native shards; the pre-v12 `timestamps_dedup.project_segment_shard` path is
  gone). Add an all-occurrences projection that emits every occasion (readings/parts are
  already the occurrence grain in v12) with the canonical one flagged, reusing the existing
  earliest-completing selection (`_canonical`). Leading/trailing partials that the current
  projection trims become their own occurrence rows — emission, not new detection.
  **Note:** this plan's branch (`qul-qua`) is based on pre-v12 main — rebase before any code
  work; file references in this doc are checked against post-v12 main.
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

Deferred decision. Two audits ran 2026-08-28 (parallel sessions): the **v12 inventory below**
(the live format) and the **v11 baseline** further down (what the frozen backup and every
existing release were built from — kept for the delta and its richer silent/co-timing stats).

### Audit findings — v12 inventory (2026-08-28, prod `.json.br`, mishary full mushaf)

114 shards, 348,387 letter-timing rows; saved at
`.local/qul_compare/v12_token_inventory.json`:

- v12 letter units (`timing.l = [unit_id, word_id, text, start_ms, end_ms, silent]`) carry a
  **100-token** inventory — v11's letter row had 57. Changes vs v11: **shadda is composed into
  the token** (28 `Xّ` composites; v11 stripped it); **a dagger alif fuses onto its seat**
  (`ىٰ` 1,910 / `وٰ` 186 / `ىٰٓ` 409 / `وٰٓ` 2 — v11 emitted seat + dagger as two co-timed
  rows) while the standalone dagger token remains (6,879); **annotation marks are now units**
  (saktah `ۜ`, low-seen `ۣ`, imala `ر۪`, ishmam `ا۬`, tatweel-carried `ـٔ`/`ـۧ`/`ـۨ` — v11
  excluded them). Maddah + silent-zero fusion unchanged.
- **Null spans are effectively gone in v12**: 1 / 348,387 (the lone `ۣ` row). The historical
  "missing letter time entries" reports do not reproduce in v11 or v12 prod data.
- Silent flags: wasla 98% silent, otiose `ا۟ و۟ ي۟` 100%, alef/maksura/waw context-dependent —
  the finer per-token distribution in the v11 baseline below still holds directionally.
- Tokenization-by-purpose: the v11 matrix below carries over with two substitutions — the cell
  row becomes v12 **columns** (mark-level, 146 texts, native package, renderer/animation only)
  and the letter row becomes v12 **letter units** (written-letter grain, shadda/dagger now
  composed as above).
- The v11 "all tokens collapse cleanly to the 42 vocab" property **did not survive v12** — see
  the release break below.
- **LATENT RELEASE BREAK (fix before any v12 cut/publish):**
  `verse_layout._external_letter` (strip `{tatweel, shadda, ۜ ۣ ۪ ۫ ۬}` → 42-token
  `to_external_char`, fail-loud) **crashes on 6 v12 tokens** — the seat+dagger fusions
  `ىٰ ىٰٓ وٰ وٰٓ` (2,507 rows in Mishary alone; first `عَلَىٰ` kills the job) and the bare
  marks `ۜ`/`ۣ` (strip to empty string). `verse_layout` also raises on the one null-timed
  letter. The v12 "harden release adapters" commit did not cover these. Resolution belongs to
  this workstream's decision: extend the external vocab with the fused forms, or re-split
  seat+dagger at publish; drop (not fail) bare-mark rows.
- Open decisions: published-tier granularity (letter units as-is vs re-split), external
  alphabet contents, whether the public tier gains the `silent` flag (leaning yes — v12 has it
  per row already), and the **silent cohighlight vs no-highlight** animation policy (mergers
  always cohighlight) — pending visual review.
- Output: a versioned public addendum (the §10 promise in the revised proposal) + the letter
  tier joins B′ in a subsequent release.

### Audit findings — v11 baseline (2026-08-28, prod v11 `.json.gz`, mishary + qatami full mushaf)

Superseded as the live format by v12 above; still describes the frozen v11 backup and what the
last releases shipped. The silent-flag distribution, co-timed-pair analysis, and
tokenization-by-purpose matrix remain the reference.

**63 surface tokens**, structured as the 42 base letters plus fused riding marks:

| Class | Tokens | Convention |
|---|---|---|
| Single-codepoint letters | 42 (consonants, alef family, hamza family + seats, dagger `U+0670`, small waw/yeh `U+06E5/06E6`, small high yeh/noon `U+06E7/06E8`, hamza-above `U+0654`) | Standalone rows — incl. dagger alif and the smalls |
| `base + maddah U+0653` | 15 composites (`آ وٓ ىٓ يٓ مٓ لٓ نٓ سٓ صٓ عٓ قٓ كٓ ٰٓ ۥٓ ۦٓ`) | Maddah FUSES into its letter's token |
| `base + silent-zero` | 6 composites (`ا۟ و۟ ي۟ ى۟` rounded `U+06DF`, `ا۠` rectangular `U+06E0`) | Silent-zero marks FUSE too |

All 63 collapse cleanly to the 42-token external vocab (strip `U+0653`/`U+06DF`/`U+06E0`) — no
gaps, mapping verified against live data. Zero null-timed letters anywhere.

**Silent-flag distribution validates the semantics**: `ٱ` 98.0% silent (the 2% = utterance-initial
wasl), `ا۟` 99.9% / `و۟ ي۟ ى۟` 100% (otiose), `ل` 14.0% (sun-letter lam), `ى` 22.4% (silent seat
under a dagger), `ا` 13.6%, silah smalls `ۥ`/`ۦ` 14–27% (waqf-shortened); dagger `ٰ` silent only
2/18,498 — it virtually always sounds.

**Co-timed adjacent rows** (identical `[start,end]`) are systematic, not noise — they are the
alignment's shared units: `ٱ`+`ل` ×24.8k (definite article), `و`+`ا۟` ×8.1k (plural waw + otiose
alef), `ل`+`ل` ×5.4k (Allah), `ى`+`ٰ` ×4.8k (seat + dagger), sun-letter `ل`+consonant,
`ه`+`ۥ`/`ۦ` (silah). A consumer without the silent flag cannot disambiguate these pairs —
**strong case for shipping the silent flag in the public letter tier**.

**Tokenization-by-purpose matrix** (the "different tokenization for different purposes" answer):

| Surface | Granularity | Consumer |
|---|---|---|
| Shard letter row | Rasm graphemes: haraka stripped, maddah/silent-zero fused, dagger + smalls standalone, `silent` flag | Timing index; animation; the public letter tier's base |
| Shard cell row (v11 slot 5) | Mark-level: every written mark a cell (haraka/tanween/madd separate, shadda composed), roles/status/phoneme indices/rules | Tajweed analysis + reporting — internal + Inspector UI only; NOT for QUL/consumers |
| FE animation | Letter row + cell-driven folding (riding marks fold onto hosts, share-groups co-highlight, silent letters currently co-highlight via shared spans) | Inspector Timestamps tab |
| Published external | Letter row mapped through the 42-token vocab (maddah + silent-zero dropped) | Releases (GH/HF) |

**Pending decision (visual review):** silent letters in the animation — co-highlight with the
sounding neighbour (current behaviour via shared spans) vs no highlight at all; mergers always
co-highlight. Whichever wins, the public tier ships timings as-is + the silent flag so consumers
make their own choice.

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
- **Reconciliation / no double counting.** The same verse commonly earns the same finding from
  several sources at once (publish-gate auto-promotion + a manual TS-tab or seg-flag report).
  Issues therefore have a **canonical identity key independent of source**:
  `(recitation, type, ayah)` (+ merged word detail for `missing_word_audio`). All promotion
  paths **upsert on that key**: an existing open issue absorbs the new source — `source`
  becomes a list, comments append, word ranges union — never a second row. The stable issue
  `id` survives merges, so the webhook delivers an *update* of the same id and QUL's upsert
  can't double count either. Re-runs of the publish gate are no-ops against an existing open
  issue; a *resolved* issue whose condition is found again **reopens the same id** (it was
  never actually fixed) rather than minting a new one. Distinct types on one verse (e.g.
  `missing_word_audio` + `mispronunciation`) stay distinct issues — semantically different
  findings, not duplicates.
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

## Workstream H — migration (public §14)

Three cohorts, phased; each internal implication:

1. **Shared recitations on Tarteel/QUL CDN** (channels `tarteel` / `quranicaudio` serving the
   `qul` source): the pilot cohort — timings already keyed to their CDN files, zero audio work.
   Internal: enumerate the cohort from the catalog (`source='qul'` / channel match), confirm
   release coverage, support their importer pilot. QUL side: new data behind a separate
   page/filter; their old-format segments untouched until sign-off.
2. **QUA-only recitations** (YouTube-sourced / non-Tarteel CDN): blocked on the audio-indexing
   decision (owner's audio-integration plan) — original provenance vs mirror vs Tarteel hosting.
   No internal work until that lands.
3. **QUL-only recitations into QUA**: normal intake → extraction → review pipeline, capacity-
   bound. Plus **overlap assessment tooling**: match QUL's list against the catalog by reciter +
   riwayah + style; for hits with different audio provenance, per-case decision — realign
   against QUL's audio (new delivery row) vs QUL adopts our audio + timings. Conditional on
   overlap actually found.

## Sequencing

1. **Send the revised proposal** (no code dependency).
2. Workstream B audit (blocks letter tier; independent of everything else).
3. Workstream A (release v2) — can cut before the API exists; QUL can adopt the format early.
4. Workstreams C + D stores/endpoints + F outbox (one delivery substrate).
5. Workstream E pipeline (heaviest; ranged path can trail the full path).
6. D promotion sources (TS-tab pills, seg-flag formalization, publish-gate promotion) —
   incremental, each independently shippable.
7. Migration phase 1 pilot (H.1) rides on A; H.2 waits on the audio plan; H.3 is ongoing
   intake capacity + the overlap assessment.

## Leak boundary (reminder)

Public = the revised proposal's content only: endpoint shapes, row schemas, catalogue, slugs,
lifecycle semantics, shared-understanding facts (§0). Internal-only: every store/table name,
ts_reports/flag_segment machinery, promotion gates, review process details, pipeline/HPC
mechanics, bucket layout, staleness/ledger internals, this file.
