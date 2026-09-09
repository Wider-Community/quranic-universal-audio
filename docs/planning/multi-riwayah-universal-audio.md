# Multi-riwayah in Universal Audio — surface audit and plan

Status: **audit / not started**. Upstream contract landed in
[QUA PR #99](https://github.com/Hetchy/qua/pull/99) (merged to `qua@main` as `c334291`)
and [aligner app PR #55](https://github.com/Hetchy/qua-aligner-app/pull/55). Both explicitly say
"Universal Audio and its offline extraction pipeline have not been wired yet".

Upstream references (read these first, they are the contract this plan consumes):

| Doc | In `qua` |
|---|---|
| Edition identity, scripts, fonts, projection | `docs/reference/editions.md` |
| Proxy timing contract + exception boundaries | `docs/plans/multi-riwayah-timing.md` |
| Deployment evidence, behaviour, prod checklist | `docs/plans/multi-riwayah-deployment.md` |
| Source/coordinate audit | `docs/plans/multi-riwayah-source-audit.md` |

---

## 0. The upstream contract in one page

Four editions: `hafs`, `warsh`, `qalun`, `shuba` (SDK slugs). `qua_domain` owns edition
identity, exact target script, coordinate index, paired font, stop-sign profile, special
texts, counting profile, and the Hafs→target word projection. `qua_sdk` owns
`project_alignment()` / `refresh_target_coverage()`.

Three facts drive everything below:

1. **Recognition and DP matching stay Hafs.** A non-Hafs recording is recognised against the
   Hafs acoustic reference, matched against the Hafs reference index, then *projected* to the
   selected edition. `matched_ref` / `matched_text` / `wrap_word_ranges` remain **source (Hafs)
   evidence**; `projected_ref` / `projected_text` / `projection_groups` are the **target
   coordinates the user sees and edits**.
2. **MFA is Hafs proxy phones.** No native non-Hafs acoustic model or dictionary. Ordinary 1:1
   target words inherit Hafs proxy intervals; four audited relations
   (`1:1:1-4` opener, `40:26:13-14`, `57:24:10`, `72:16:1`) have explicit phone ownership.
3. **Non-Hafs timing responses are word-only.** No letters, no nested phones, no raw phone
   intervals, no cross-word merge detail, no character geometry — those shapes belong to the
   Hafs reference script. `words=[]` is a valid aligned omission; `words=None` is still failure.

Verse and word **counting differs per edition** (Warsh/Qalun renumber; the Fatiha opener is
unnumbered). This is not a global offset — it comes from the full word map.

---

## 1. "Do we adjust code, or is it a shared image and just a deploy?"

**Both, but the code side is unavoidable — and it is call-site wiring, not new algorithms.**

The riwayah-aware machinery (domain assets, projection, coverage, proxy timing, exception
handling) is already in the shared `qua_domain` / `qua_sdk` packages that every engine image
installs. What PR #99 wired was the *interactive* path only.

| Path | Who runs it | Riwayah-aware today? |
|---|---|---|
| Interactive align (aligner Space) | `engines/alignment` → `qua_sdk.pipelines.align` | **Yes** (PR #99) |
| Interactive timing (timing Space, Gradio/typed batch) | `engines/timing/{adapters,batch,runtime,legacy_gradio_v1}.py` | **Yes** (PR #99) |
| **Offline extraction (Katana)** | `engines/alignment-batch` → `qua_alignment_batch.job` | **No — zero `riwayah` hits** |
| **MFA sidecars** | `engines/timing-batch` (`low_confidence`, `auto_split`) | **No — zero hits** |
| **Whole-verse timestamps producer** | `engines/timing/timestamps/*` + `timestamps_runner.py`, route `/internal/v1/timestamps` | **No — zero hits** |

So:

- **Deploy-only wins:** the MFA acoustic model and dictionary do not change. No new model, no
  new GPU artefact, no new Space. Bumping the batch timing Space + Katana image to a post-#99
  SDK pin gets you the *capability* but changes nothing on its own.
- **Code required:** three unwired call sites.
  - `qua_alignment_batch`: carry `riwayah` on the input manifest → `BatchJob` → `align(..., riwayah=...)`,
    and persist the projected refs/text the SDK returns (`AlignProfile` itself needs no new field;
    riwayah is an `align()` keyword, and the matcher takes it via `matching_params.recitation_riwayah`).
  - `qua_timing_batch`: pass `recitation_riwayah` + `target_refs` on the remote MFA call
    (`MfaParams(recitation_riwayah=...)`, remote batch adds one parallel `target_refs` list per item).
  - `qua_timing_engine.timestamps`: accept `riwayah` on the `/internal/v1/timestamps` body, take the
    word-only branch, and emit the new word-profile shard (see §3).
- **QUA (this repo) code required:** the request body in
  [`inspector/services/admin/ts_space_client.py`](../../inspector/services/admin/ts_space_client.py)
  is a fixed, HMAC-signed shape (`schema_version`, `profile_id`, `slug`, `chapters`, `beams`).
  Adding `riwayah` changes the signed preimage — coordinate the field addition with the Space and
  the signing parity test in the same release.

---

## 2. Coordinate model — the one decision everything else hangs off

The aligner app **displays and edits in target coordinates** and keeps Hafs source evidence
alongside. Universal Audio should do the same, otherwise the Segments tab shows Hafs verse
numbers under a Warsh script.

**Recommendation.** `matched_ref` keeps its name and becomes *the delivery's own edition
coordinate* (identity for Hafs, so nothing moves for the 37 existing reciters). Add to
`DetailedSegment`:

| Field | Type | Why |
|---|---|---|
| `source_ref` | `str \| None` | Hafs acoustic/DP evidence. Only the timestamps producer and any re-alignment read it. `None` ⇒ identity. |
| `projection_support` | `"full" \| "partial" \| None` | The SDK's `support` for the group; `partial` means the segment cuts an N:M relation. |

and to `DetailedMeta`: **`riwayah: str \| None`** — so a reader knows which coordinate system a
`detailed.json` is in without a catalog round-trip.

> Bug found while auditing: [`qua_jobs/publish_hf.py:633`](../../qua_jobs/publish_hf.py) already reads
> `detailed["_meta"]["riwayah"]` as a fallback, but `DetailedMeta` is `extra="forbid"` with no such
> field — that fallback is unreachable dead code today. Adding the field fixes it.

Rejected alternative: store Hafs coords in `matched_ref` and project at read time. It makes every
edit a reverse-projection (lossy at partial N:M groups), and makes the Segments editor unable to
address Warsh/Qalun `72:16:2`, which has no Hafs word of its own.

---

## 3. Shard format — v13 is Hafs-only by construction

[`qua_shared/schemas/bucket/ts_shard.py`](../../qua_shared/schemas/bucket/ts_shard.py) requires
`phonemizer_version`, `native_schema_version: 2`, `renderer_codec_version: 1`, per-sound timing
(`timing.s` count == `render.p` count), per-column/cell rows, rule-occurrence IDs, and letter
recutting. None of that exists for a proxy-timed non-Hafs word row. A degenerate v13 with empty
`p`/`r`/columns would pass the pydantic closure check but fail `audit_v13_document` and produce an
empty cell graph in `@quranic-phonemizer/cells`.

**Recommendation: a discriminated profile, not a v13 fork and not a v13 restamp.**

```jsonc
{
  "_meta": {
    "schema_version": 14,
    "profile": "word",            // "native" | "word"
    "riwayah": "warsh",
    "script": "warsh-madani",
    "script_sha256": "...",
    "chapter": 40,
    "audio_category": "by_surah",
    "timing_provider": "hafs_proxy_mfa",   // provenance: these are proxy timings
    "projection_id": "...", "projection_sha256": "..."
  },
  "readings": [{
    "id": "r1",
    "parts": [["40:26", 1200, 5400, 0, 2]],
    "words": [["40:26:13", "<exact target text>", 1200, 3100]],
    "boundaries": [[state_code, verse_end]]
  }]
}
```

Rules:

- Existing Hafs shards stay **`schema_version: 13`, untouched** — no second restamp of 37 reciters
  × 114 chapters. A reader treats absent `profile` as `"native"`.
- The word profile has **no** `phonemizer_version`, `native_schema_version`, `renderer_codec_version`,
  `render`, `timing.s/a/c`. Boundary timing keeps the v13 derivation rule (preceding word end →
  following word start, next reading's *first word start* across a gap) — that rule is
  phoneme-free and should be shared, not reimplemented.
- New audit `qua_shared/timestamps_word_audit.py`; new decoder branch in
  [`qua_shared/timestamps_codec.py`](../../qua_shared/timestamps_codec.py) and in
  [`compact-shards.ts`](../../inspector/frontend/src/lib/recitation-data/compact-shards.ts)
  (which currently hard-throws `schema_version !== 13`).
- `write_validated_shard` dispatches on profile.

Open decision: whether `schema_version: 14 / profile: "word"` or a separate top-level document kind
(`"word/1"`). The discriminator keeps one path, one LRU cache, one route, one release loader — that
is the argument for it.

---

## 4. Reference assets — the Inspector has no `qua_domain`

[`inspector/requirements.txt`](../../inspector/requirements.txt) deliberately excludes `qua_sdk` /
`qua_domain` (the Inspector is a pure consumer; the image stays light). Today the whole app renders
from two Hafs artefacts:

- `data/qpc_hafs.json[.gz]` (+ bucket fallback `reference/qpc_hafs.json.gz`) —
  [`services/storage/static_refs.py`](../../inspector/services/storage/static_refs.py)
- `data/digital_khatt_v2_script.json` + `data/surah_info.json` → the immutable
  `dk_words + verse_word_counts` bundle in
  [`services/reference/quran_refs.py`](../../inspector/services/reference/quran_refs.py)
- one inlined `DigitalKhattV2.otf` data URI in `src/styles/base.css` (~680 KB of base64)

**Plan.** Add a codegen script `scripts/codegen/export_edition_refs.py` that runs *offline* against
`qua_domain` (never a runtime dep) and writes, per edition, to the bucket:

```
reference/editions/<riwayah>/index.json.gz     # exact script text, per-word, target coords
reference/editions/<riwayah>/counts.json.gz    # verse list + per-verse word counts (counting profile)
reference/editions/<riwayah>/font.otf          # the paired font, digest-verified
reference/editions/<riwayah>/meta.json         # edition id, digests, stop-sign profile, special texts
```

Then generalise:

- `static_refs.load_qpc_bytes()` → `load_edition_index_bytes(riwayah)` (same local → local-gz →
  bucket ladder; Hafs keeps its current fast path).
- `quran_refs.py` bundle becomes per-riwayah with a per-edition hash; the static route gains a
  riwayah parameter.
- `data_loader.get_word_counts()` / `surah_words.word_counts_from_surah_info()` become
  edition-scoped. **This is the highest fan-out change in the repo** — `get_word_counts()` feeds
  `normalize_ref`, missing-words, missing-verses, coverage, save, release and HF validation.

**Do not inline three more fonts into `base.css`.** That is ~2 MB of base64 on every page load, and
the reason DK is inlined at all is the HF-Space LFS-smudge trap
(see [`config-deploy.md`](../reference/config-deploy.md)). Serve non-Hafs fonts from the bucket
through a long-cache Flask route — bucket objects are Xet-backed and have no LFS pointer problem
(same reasoning as `reference/qpc_hafs.json.gz`).

---

## 5. Riwayah slug mapping

The Inspector vocabulary and the SDK do not agree:

| Inspector `riwayahs.slug` | `short` | SDK slug |
|---|---|---|
| `hafs_an_asim` | `hafs` | `hafs` |
| `warsh_an_nafi` | `warsh` | `warsh` |
| `qalon_an_nafi` | `qalon` | **`qalun`** |
| `shubah_an_asim` | `shubah` | **`shuba`** |

Twenty riwayat exist in the vocabulary; four are supported. Add a single source of truth —
`qua_shared/riwayat.py` with `SUPPORTED_RIWAYAT`, `to_sdk_slug()`, `from_sdk_slug()` — and codegen
it to the FE alongside the schema types. Never compare `short != 'hafs'` again (two FE sites do
that today, see §10).

---

## 6. Offline extraction and the bucket

### 6.1 Extraction run

- `scripts/inputs_from_manifest.py` (in `qua`) writes `inputs.json` from the catalog sidecar — add
  the delivery's riwayah, resolved through §5.
- `qua_alignment_batch.job` passes it to `align()`; `detailed.json` is written with target
  `matched_ref` + `source_ref` + `_meta.riwayah`.
- The specials strip must use the **edition's** special texts (`special_text("Basmala", riwayah)`),
  and for Warsh/Qalun the Fatiha opener is an unnumbered `opening_basmala` group, not `1:1:1-4`.
- **Guard:** refuse a run whose delivery riwayah is not in `SUPPORTED_RIWAYAT`, rather than
  silently aligning it as Hafs.

### 6.2 Sidecars — what survives

| Sidecar | Non-Hafs | Reasoning |
|---|---|---|
| `low_confidence_v2.json` | **Do not produce** | It is a *tight-beam MFA* probe. Non-Hafs MFA runs Hafs proxy phones, so genuine riwayah pronunciation (madd lengths, imala/taqlil, naql, badal, differing assimilation) fails the tight beam everywhere. The signal degenerates to "this is not Hafs". |
| `ts_validation.json` | **Do not produce** | The verse-level twin of the above — same multi-beam probe, same argument. The Timestamps ts-validation accordion must hide when the sidecar is absent (it already tolerates absence). |
| `auto_split_v1.json` | Produce, lower trust | Beam-30 MFA is wide enough to place a section cut, but it is still proxy phones. Auto Split already falls back to plain Split when `refs` is null. Decide whether to gate it off for a first release. |
| `hidden_pause_v1.json` | Produce | Acoustic re-segmentation (boundary head / VAD arms). Riwayah-agnostic. |
| `false_split_v1.json` | Produce | Same. |
| `unmarked_wasl_v1.json` | Produce | Same — but its "verse-to-verse join" test needs *target* ayah numbering. |
| `peaks/*.json.gz`, `audio/*.mp3` | Unchanged | Pure audio. |
| `pipeline_meta.json` | Add `riwayah` | Provenance; also the TS-gen eligibility gate reads it. |

### 6.3 Files whose shape changes

| Bucket path | Change |
|---|---|
| `reciters/<slug>/detailed.json` | `_meta.riwayah`; segs gain `source_ref`, `projection_support` |
| `reciters/<slug>/timestamps/<ch>.json.br` | word-profile shard (§3) for non-Hafs |
| `reciters/<slug>/edit_history.jsonl` | No schema change; snapshots carry target refs. Non-Hafs reciters are new, so no migration |
| `reciters/<slug>/segments.json` | Verse-aggregated view — regenerates from `detailed.json`, needs per-edition verse list |
| `catalog/audio_manifest/<slug>.json` | Already carries `_meta.riwayah` (canonical per `publish_hf._riwayah_for`) |
| `reference/editions/<riwayah>/*` | New (§4) |

---

## 7. Validation categories — per-category verdict

Registry: [`services/validation/registry.py`](../../inspector/services/validation/registry.py) ↔
[`tabs/segments/domain/registry.ts`](../../inspector/frontend/src/tabs/segments/domain/registry.ts).
Hardcoded coordinate tables: [`inspector/constants.py`](../../inspector/constants.py).

| # | Category | Verdict | What has to change |
|---|---|---|---|
| 1 | `failed` | keep | none (empty `matched_ref`) |
| 2 | `missing_verses` | keep | per-edition verse list — Warsh/Qalun have different verse counts, so a Hafs `surah_info` gives false gaps |
| 3 | `missing_words` | keep | per-edition `verse_word_counts` |
| 4 | `structural_errors` | keep | none (pure time/index) |
| 5 | `low_confidence` | keep, **re-tune** | Score comes from Hafs DP against a non-Hafs recitation, so the whole distribution shifts down. `LOW_CONFIDENCE_THRESHOLD` / `LOW_CONFIDENCE_DETAIL_THRESHOLD` need a per-edition value or the accordion drowns |
| 6 | `low_confidence_v2` | **disable** | sidecar not produced (§6.2). Registry row stays; `category_counts` emits 0 and the accordion hides |
| 7 | `audio_bleeding` | keep | `seg_belongs_to_entry` containment must use target coords |
| 8 | `boundary_adj` | keep, **remap** | `STANDALONE_REFS` is 10 hardcoded Hafs `(surah, ayah, word)` triples; `MUQATTAAT_VERSES` is 30 hardcoded `(surah, ayah)` pairs; `single_word_verses` derives from Hafs word counts. All three must be projected per edition (or the allow-lists gated to Hafs, accepting more false positives). `STANDALONE_WORDS` is bare-skeleton text and mostly survives, but Warsh rasm differs on some words — verify against the edition index |
| 9 | `repetitions` | keep | pure `wrap_word_ranges` geometry |
| 10 | `cross_verse` | keep | needs target ayah numbering |
| 11 | `qalqala` | keep | `compute_qalqala_letter` reads `dk_text_for_ref` → must read the **edition** script. Qalqala letters themselves are edition-invariant |
| 12 | `muqattaat` | keep, **remap** | `MUQATTAAT_VERSES` per edition |
| 13 | `basmala_amin` | **rework** | [`detail.py:535`](../../inspector/services/validation/detail.py) hardcodes `surah == 1 and (1 in span or 7 in span)`. In Warsh/Qalun the Fatiha Basmala is an **unnumbered opener**, so `1:1` is a different verse and the last verse is not `1:7`. The rule must resolve the edition's opener special + last Fatiha verse ref |
| 14 | `hidden_pause` | keep | none |
| 15 | `false_split` | keep | none |
| 16 | `unmarked_wasl` | keep | target ayah numbering |

Also touched: `bench/ground_truth/<slug>.json` drift snapshots are per-reciter, so existing Hafs
snapshots are unaffected — but the drift gate must be extended with at least one non-Hafs reciter
before the coordinate tables are edited, or the change is unguarded.

---

## 8. Timestamps tab — word-only mode

Gate on the shard's own `_meta.profile === 'word'` (authoritative), not on the manifest riwayah —
the manifest already carries `riwayah` per reciter
([`wire/timestamps.py:129,195`](../../qua_shared/schemas/wire/timestamps.py)) and is fine as a
pre-fetch hint, but the shard is the truth about what timing exists.

| Surface | File | Action |
|---|---|---|
| Letters toggle | `components/TimestampsFooterAnalysis.svelte`, `stores/display.ts::showLetters` | force `false`, render `disabled` with a "not available for this riwayah" title |
| Phonemes toggle | same, `showPhonemes` | same |
| Continuous highlight (karaoke wipe) | same, `highlightWipe` | disable — the wipe interpolates *within* a cell from sound timing that does not exist |
| Tajweed settings | `components/TajweedSettingsPanel.svelte`, `stores/tajweed-settings.ts`, `timestamps/data/rules.json`, `tajweed-rules.ts` | disable the drop-up button. The 45-rule catalogue is generated from the Hafs phonemizer and has no non-Hafs meaning |
| Analysis rows | `components/TimedAnalysisRow.svelte` | word cells only — no letter row, no phoneme row, no bridges, no stacked underlines, no group spotlight |
| Hover bus | `stores/display.ts::TsHoveredElement` | `kind` restricted to `'word'` |
| Animation granularity | `stores/display.ts::TS_GRANULARITIES`, `lib/recitation-animation/config.ts`, `lib/components/player/NowReciting.svelte` | lock to `words`; hide/disable the char toggle in the teleprompter and the dashboard now-reciting player |
| Teleprompter shaped glyphs | `lib/recitation-animation/shaped-glyphs.ts` → `/generated/shaped-glyphs-v13/*` | Hafs DigitalKhatt geometry only. Either generate an equivalent per edition, or take the existing "shaped geometry is an enhancement" fallback and render unshaped edition text |
| Word-by-word translations | `stores/display.ts::verseTranslations`, `services/quran_foundation/` | glosses are keyed `surah:ayah:word` in **Hafs/Uthmani** coordinates. A target word must reverse-project to its source word(s) before lookup, or translations silently mis-align on Warsh/Qalun |
| ts-validation accordion | `components/TsValidationPanel.svelte` | hides when `ts_validation.json` is absent (§6.2) — verify it degrades rather than errors |

### 8.1 Reports (`ts_reports`)

[`docs/reference/ts-reports.md`](../reference/ts-reports.md) target kinds
`column` / `sound` / `group` / `bridge` do not exist in a word shard.

| Report category | Word profile |
|---|---|
| `audio` (verse, word) | keep |
| `timing` (word, column, sound, group, boundary, bridge) | restrict to `word` + `boundary` |
| `tajweed` | **disable** |
| `phonemes` | **disable** |
| `silence` (boundary) | keep — boundaries exist; but `pause_wasl` / `pause_missed` subtypes should be reviewed, since they were tuned against Hafs sakt/wasl semantics |
| `other` | keep, restricted to available kinds |

`report-mode.ts` (`ReportMode` union, `seedOwnFlags`), `TimestampsFooterReport.svelte`, and
`wire/ts_reports.py::shard_schema_version: Literal[12, 13]` all need the word profile added.
`services/ts_reports/ts_target_snapshot.py` hard-checks `schema_version != 13` in two places.

---

## 9. Segments tab

- Reference text, ref picker, and word counts come from the `dk_words + verse_word_counts` bundle —
  make it edition-scoped (§4) and key the browser cache by edition so one riwayah's payload can
  never be reused for another.
- Font: `.seg-text` and friends hardcode `font-family: 'DigitalKhatt', ...` in
  `src/styles/segments.css`. Introduce a `--font-quran` token set per edition and switch it from
  the loaded reciter's riwayah (theming rule: no raw values in components).
- Ayah markers / ornaments: the aligner app keeps the Digital Khatt ornament font for markers while
  Quran words use the edition font. Mirror that rather than swapping everything.
- Cross-chapter / cross-verse traversal must use the edition's verse lengths — Warsh/Qalun
  `72:16:8` is editable and visible even though Hafs has seven words there.
- RTL: the Segments editor already pins time-axis surfaces to `dir=ltr` islands
  ([`theming.md`](../reference/theming.md), i18n work) — no change, but re-verify with a wider
  Warsh script.

---

## 10. Requests / intake

Today: `nonHafsRiwayah = !!selectedRiwayahShort && selectedRiwayahShort !== 'hafs'` in
[`RequestForm.svelte:208`](../../inspector/frontend/src/tabs/dashboard/components/RequestForm.svelte)
and
[`StepDetails.svelte:46`](../../inspector/frontend/src/tabs/dashboard/components/submit/StepDetails.svelte),
rendering `m.dashboard_request_non_hafs_callout()`.

Change to `!SUPPORTED_RIWAYAT.has(short)` (§5) and replace the message with an
"unsupported riwayah" variant: we support Hafs, Warsh, Qalun and Shu'bah; other riwayat are planned;
the request can still be submitted. Requires:

- new key in `src/tabs/dashboard/messages/{en,ar}.json`, Paraglide recompile
- retire `dashboard_request_non_hafs_callout` (both message files + generated output)
- no backend gate exists today (`services/admin/intake_validation.py` has no Hafs check) — nothing
  to remove server-side

---

## 11. Releases and publishing

### 11.1 GitHub release

- `qua_jobs/cut_release.py` builds three tiers per reciter. A word-profile reciter emits
  **verse + word only** — no `letter_timestamps.json.gz`.
- `content_hash = SHA-256(letter_tier.gz || catalog.json)` has no letter tier to hash. Redefine as
  the deepest emitted tier and record `tiers: ["verse","word"]` per recitation in the release
  `manifest.json`. That is a **format semantics change** ⇒ raise `RELEASE_FORMAT_MAJOR` (v4.0.0)
  rather than sneaking it into a v3 patch.
- `static_refs` in the dataset manifest must carry the per-edition script JSON + font (and the
  release must ship them), not just `digital_khatt_v2_script.json` + `DigitalKhattV2.otf`.
- `_load_canonical_verses` → `select_complete_verses` uses reference word indices → per-edition
  word counts.
- [`qua_shared/timestamps_native.py`](../../qua_shared/timestamps_native.py) reads
  `reading["analysis"]["result"]["words"]` and `timing["animation_tokens"]` — needs a word-profile
  branch that projects words with no `letters` array.
- `qua_shared/release_changelog.py` + `docs/templates/release_body.md` should name the riwayah and
  state plainly that non-Hafs timings are Hafs-proxy word timings.
- `qua_jobs/shard.py` (the consumer helper) already tolerates a missing letter tier — verify.

### 11.2 HF dataset

- Already partitioned config-per-riwayah
  ([`qua_shared/hf_dataset_catalog.py`](../../qua_shared/hf_dataset_catalog.py), `_push_to_hf(slug, riwayah, ...)`),
  so a differing feature schema per config is legal. Mind the 30-splits-per-config cap.
- `_reshape_timestamps_for_rows(canonical, digital_khatt_words)` must take the edition script; letter
  columns are absent (not null-filled) for word-profile configs.
- `qua_shared/dataset_validation.py` + `qua_shared/coverage.py` need per-edition verse/word counts.
- Config names: the dataset uses Inspector slugs (`warsh_an_nafi`) — keep that, and record the SDK
  slug + projection digest in the config card so a consumer can tell proxy timing from native.

### 11.3 Eligibility / automation

No change to the gate itself (`gh_release_eligible` + a current `ts` row). But
`services/admin/automation/evaluators.py` "stale TS regen" and "stale metadata refresh" rules will
now fan out over reciters whose regeneration is a word-profile run — verify the job kind is carried
through and that a word-profile regen does not trip the native audit.

---

## 12. Anything else the audit turned up

1. **`ts_space_client` signed body.** Adding `riwayah` changes the HMAC preimage; the inlined JCS
   canonicaliser rejects floats but happily signs a new string field. Ship the QUA change and the
   Space change together, and update the signer parity test.
2. **`inspector/services/reference/timestamps.py:183`** defaults an unknown delivery to
   `"hafs_an_asim"`. With four editions live that default silently mislabels; make it fail or emit
   `None`.
3. **`_RESOURCE_KEYS = ("qpc_hafs", "digital_khatt")`** in the same module is the FE's resource
   bundle contract — it becomes edition-keyed.
4. **Anon capability snapshots.** Any new capability (e.g. a per-edition asset route) breaks the
   hardcoded anon lists in `tests/test_capabilities`, `test_route_auth`, `test_dev_mode`. Grep first.
5. **Response snapshots** (`tests/routes/snapshots/*.json`) pin `riwayah: hafs_an_asim` — they will
   need non-Hafs fixtures once the wire shape grows.
6. **`docs/reference/shards.md` is stale** — it documents schema v12 throughout while the code is on
   v13 (`ts_shard.py`, `timestamps-job.md`, `compact-shards.ts`). Fix in the same change.
7. **Drift gate.** `bench/` ground-truth snapshots must gain a non-Hafs reciter before any
   coordinate-table edit lands, otherwise the only guarantee that save / extraction / backfill
   writers agree is gone for the new path.
8. **Dashboard "now reciting" player** (`lib/components/player/NowReciting.svelte`) shares the
   animation config with the Timestamps teleprompter — it needs the same word-lock, and it is a
   cross-tab surface that is easy to miss.
9. **Search / browse filters** already expose riwayah (`lib/catalog/schema-descriptor`,
   `components/picker/`), driven by catalog vocabulary — no change beyond making sure a
   word-profile reciter's Timestamps entry point does not advertise analysis features it lacks.
10. **Proxy-timing honesty.** The upstream doc is explicit that these are "useful proxy timings, not
    a measured native-riwayah phonetic accuracy guarantee". Surface that once in the UI (a badge on
    the Timestamps header for word-profile reciters) and once in the release changelog, rather than
    letting consumers infer parity with Hafs.

---

## 13. Suggested sequencing

1. `qua_shared/riwayat.py` + `DetailedMeta.riwayah` + `DetailedSegment.source_ref` (schema-only, no
   behaviour) → regen FE types.
2. `scripts/codegen/export_edition_refs.py` + bucket `reference/editions/*` + edition-scoped
   `static_refs` / `quran_refs` / `get_word_counts`. Hafs path byte-identical (drift gate proves it).
3. Word-profile shard schema + audit + Python/TS decoders (§3), no producer yet.
4. Upstream: `qua_alignment_batch` riwayah wiring; `qua_timing_engine.timestamps` word branch;
   `qua_timing_batch` sidecar policy. Deploy batch timing Space + Katana image on the new pin.
5. Inspector read paths: Segments (script/font/counts), Timestamps word-only gating, reports
   restriction.
6. Validation coordinate tables + `basmala_amin` rework + threshold re-tune, guarded by a non-Hafs
   drift snapshot.
7. Releases: `RELEASE_FORMAT_MAJOR` bump, tier/`content_hash` change, HF row builder.
8. Requests copy + supported-riwayah list.
9. Reference docs updated in the same changes (`shards.md`, `timestamps-job.md`, `validation.md`,
   `catalog.md`, `dataset-and-releases.md`, `segments-editor.md`, `frontend.md`, plus a new
   `editions.md` in `docs/reference/`).

---

## 14. Open questions for the owner

1. Shard discriminator: `schema_version: 14 + profile: "word"` (recommended) or a separate document
   kind? Either way, Hafs v13 is not restamped.
2. `matched_ref` = target coordinates with `source_ref` alongside (recommended), or Hafs coordinates
   with read-time projection?
3. `auto_split_v1` for non-Hafs — produce with lower trust, or omit for the first release alongside
   `low_confidence_v2` / `ts_validation`?
4. Teleprompter shaped geometry for non-Hafs — generate per-edition fixtures, or accept unshaped
   text rendering for those three editions?
5. Release format: bump to v4.0.0 for the tier/`content_hash` change (recommended), or keep v3 and
   special-case word-profile reciters?
