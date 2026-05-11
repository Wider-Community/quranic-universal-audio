# Reciter Catalog Reference

The canonical reference for the reciter catalog: layers, slug convention, schema, audio metadata split, and the workflows for adding/probing/maintaining reciters. Companion to the v2 deployment plan ([`../planning/inspector-deploy/v2/inspector-deployment-plan.md`](../planning/inspector-deploy/v2/inspector-deployment-plan.md)).

Assumes shared context with the v2 deploy work. For *why* a given decision was made beyond this doc, check the planning docs and `.local/dedup/` artifacts.

## 1. Overview

The catalog is two on-bucket artifacts plus a 1:1 set of sidecars:

```
<bucket>/
└── catalog/
    ├── reciter_catalog.json              # vocab + reciters[] + deliveries[] + aliases[]
    └── audio_manifest/
        └── <slug>.json                   # one per delivery (864 today): URL map + per-chapter metadata
```

`reciter_catalog.json` is small (~250 KB). Sidecars are 5–20 KB each for `by_surah` (114 chapters), larger for `by_ayah` (6236 ayahs). Inspector backend is the sole writer of both.

## 2. The three layers

| Layer | Identity question | Where it lives |
|---|---|---|
| **Reciter** | Who is the human? | `reciters[]` row, keyed by `reciter_id` |
| **Recording** | Which artistic act? *(implicit — see below)* | Computed via group-by on `deliveries[]` |
| **Delivery** | Which file did we actually fetch? | `deliveries[]` row, keyed by `slug` |

A "recording" — same reciter performing the same style+riwayah+year — is **not** a stored entity. It's a group-by:

```
recording = (reciter_id, riwayah, style, recording_year, variant_label)
```

Sibling deliveries of the same recording (e.g., mp3quran + qul both serving Mishary's 2008 Hafs Murattal) are discovered with a `GROUP BY` over `deliveries[]`. We considered a `recording_id` middle layer, dropped it: denormalizing year/variant across CDN-rows is cheap and removes a foreign key.

### Source × Channel are orthogonal

- **`source`** = the website we found the audio on (mp3quran.net, everyayah.com, qul.tarteel.ai, surahquran.com, quranicaudio.com, tvquran.com).
- **`channel`** = the host actually serving the bytes (`server*.mp3quran.net`, `download.quranicaudio.com`, `audio-cdn.tarteel.ai`, `download.tvquran.com`, `everyayah.com`, `*.archive.org`).

Relationship is M:N. One source can route through multiple channels (qul uses both `tarteel` and `quranicaudio`); one channel can serve multiple sources (`quranicaudio` channel serves both `quranicaudio` and `qul`; `archive_org` serves `surah-quran`).

The (source, channel) pair on each delivery row is **authoritative** — vocab does not store either direction of the mapping. Use `GROUP BY` if you need it.

**CDN is the primary dedup axis.** Same `(reciter, riwayah, style, channel)` is kept (separate deliveries) when bitrate, sample rate, channels, or duration differ — they're different masters. Within-tuple disambiguators on the slug: `_<bitrate>k` when bitrates differ, `_v2` otherwise. See §3.

## 3. Slug convention

```
<reciter_id>[_<riwayah_short>][_<style_short>][_<year>]_<channel_short>[_<disambiguator>]
```

Fixed ordering (left to right): reciter, riwayah, style, year, channel, disambiguator.

**Regex:** `^[a-z][a-z0-9_]{1,79}$`. ASCII lowercase, single underscores between tokens. No code parses the slug — it's a human-readable opaque ID.

**Suffix rules:**

| Component | Omit when | Source |
|---|---|---|
| `riwayah_short` | `hafs` (Hafs an Asim, the default) | `vocab.riwayat[].short` |
| `style_short` | `murattal` (the default) | `vocab.styles[].short` |
| `year` | not known — never invent | row's `recording_year` |
| `channel_short` | **never** — channel suffix is mandatory | `vocab.channels[].short` |
| `disambiguator` | only when same `(reciter, riwayah, style, year, channel)` has >1 delivery | derived during seeding |

**Disambiguator forms** (when needed):
- `_<bitrate>k` — when colliding deliveries differ by bitrate, e.g. `mahmoud_khalil_al_husary_qdc_64k` vs `mahmoud_khalil_al_husary_qdc_128k`.
- `_v2`, `_v3`, … — fallback when bitrates match (different masters with same encoding).
- `_byayah` — when a delivery is `by_ayah`, appended **after** the channel: `ahmad_al_nufais_tarteel_byayah`. Treated as a category marker, not a within-tuple disambiguator. Stays at the end so the left-to-right ordering rule (reciter, riwayah, style, year, channel) holds for everything before it.
- `_v2`, `_v3`, `_v4`, … — extend the chain when 3+ deliveries collide on `(reciter, riwayah, style, year, channel, bitrate_kbps_nominal)` (rare). Bitrate suffix preferred when bitrates differ; numeric chain only as fallback.

**Worked examples:**

| Source manifest | Slug |
|---|---|
| `mp3quran/abdulbasit_abdulsamad.json` | `abdulbasit_abdulsamad_mp3quran` |
| `qul/abdulbasit_abdulsamad.json` (routes to tarteel) | `abdulbasit_abdulsamad_tarteel` |
| `qul/abdulbasit_abdulsamad_qdc.json` | `abdulbasit_abdulsamad_qdc` |
| `qul/abdulbasit_abdulsamad_mujawwad_qdc.json` | `abdulbasit_abdulsamad_mujawwad_qdc` |
| `mp3quran/abdelaziz_sheim_warsh.json` | `abdelaziz_sheim_warsh_mp3quran` |
| `surah-quran/abbadi_houssem_eddine.json` (routes to archive.org) | `abbadi_houssem_eddine_archive` |
| `by_ayah/qul/ahmad_al_nufais.json` (tarteel channel, sibling exists in `by_surah`) | `ahmad_al_nufais_tarteel_byayah` |

Renames are free (URLs are preserved per-delivery in the sidecar; nothing about the audio depends on the slug).

## 4. Schema

> **Authority**: the tables below are for human readers. The **runtime authority** is the pydantic models at **`scripts/lib/schemas/`** (cross-consumer location — read by Inspector, training pipeline, dataset builder, and GH Actions). Post-v2, a generator emits JSON Schema, TypeScript types, and rendered markdown from those pydantic models — single source of truth, CI drift gate. Until the generator lands, this doc and the pydantic models must be kept in manual sync; reviewers should check both whenever schema changes. See [`../planning/inspector-deploy/v2/inspector-cleanup-registry.md`](../planning/inspector-deploy/v2/inspector-cleanup-registry.md) §10.

> **Null convention**: any field marked `<type> \| null` accepts `null` to mean "missing / not yet identified". Do not use `""` or the string `"unknown"` as sentinels — use `null`. This applies to `name_ar`, `country`, `recording_context`, `recording_year`, `variant_label`, and all audio-metadata fields.

### `vocab.riwayat[]`

| Field | Type | Notes |
|---|---|---|
| `slug` | string | e.g. `hafs_an_asim`. Immutable. |
| `short` | string | Used in delivery slugs. e.g. `hafs`. |
| `name` | string | Display, e.g. `Hafs A'n Assem`. |

### `vocab.styles[]`

Same shape as riwayat. Values: `murattal` / `mujawwad` / `muallim` / `children_repeat` / `hadr`.

Note: legacy `taraweeh` style was migrated to `style: "murattal" + recording_context: "taraweeh"` at seed time. The `taraweeh` style slug is no longer in vocab — taraweeh recordings are murattal-paced. `hadr` is a fast-paced recitation style (less ornamented than murattal).

### `vocab.sources[]`

| Field | Type | Notes |
|---|---|---|
| `slug` | string | e.g. `mp3quran`, `qul`, `surah-quran` (hyphen allowed in source slug only). |
| `name` | string | Display. |
| `url` | string | Website root. |
| `audio_categories` | string[] | Subset of `["by_surah", "by_ayah"]`. |

### `vocab.channels[]`

| Field | Type | Notes |
|---|---|---|
| `slug` | string | e.g. `mp3quran`, `quranicaudio`, `archive_org`. |
| `short` | string | Used in delivery slugs. e.g. `qdc` for `quranicaudio`, `archive` for `archive_org`. |
| `name` | string | Display. |
| `host_patterns` | string[] | Glob patterns matched against URL hostnames during ingestion. |

### `vocab.recording_contexts[]`

Recording context (orthogonal to `style`, which captures pace/ornamentation).

| Field | Type | Notes |
|---|---|---|
| `slug` | string | One of: `studio`, `broadcast`, `prayer`, `taraweeh`, `mixed`. |
| `name` | string | Display, e.g. `Taraweeh prayers (Ramadan night)`. |

Semantics:
- **`studio`** — deliberate studio recording for distribution.
- **`broadcast`** — radio (iza'a) or TV broadcast.
- **`prayer`** — live prayer recording, non-Taraweeh (Fajr, Qiyam, etc.).
- **`taraweeh`** — Ramadan night prayers. Distinguished from `prayer` because of its volume and recurring annual cadence.
- **`mixed`** — a single delivery sourced from multiple contexts (e.g., partial broadcast + partial studio).

The row's `recording_context` field is **nullable** — `null` means "not yet identified" (default for seed entries that haven't been classified). No `"unknown"` sentinel in vocab.

### `reciters[]`

| Field | Type | Notes |
|---|---|---|
| `reciter_id` | string | Slug-form, e.g. `mahmoud_khalil_al_husary`. Immutable. |
| `name_en` | string | Canonical display. See §6 naming style guide. |
| `name_ar` | string \| null | Arabic. `null` if unknown. |
| `country` | string \| null | ISO-2 or `null`. |
| `notes` | string \| null | Free-form, ≤500 chars. |

### `deliveries[]`

| Field | Type | Notes |
|---|---|---|
| `slug` | string | Per §3. Primary key. |
| `reciter_id` | string | FK → `reciters[].reciter_id`. |
| `riwayah` | string | FK → `vocab.riwayat[].slug`. |
| `style` | string | FK → `vocab.styles[].slug`. Pace/ornamentation only (murattal/mujawwad/muallim/children_repeat/hadr). |
| `recording_context` | string \| null | FK → `vocab.recording_contexts[].slug`. `null` when not yet identified. Orthogonal to style. |
| `recording_year` | int \| null | 4-digit Hijri or CE; null when unknown. |
| `variant_label` | string \| null | Free token (e.g. `madinah`, `studio_2008`); rare. |
| `source` | string | FK → `vocab.sources[].slug`. |
| `channel` | string | FK → `vocab.channels[].slug`. |
| `audio_category` | string | `by_surah` \| `by_ayah`. |
| `chapter_count` | int | Number of chapter URLs present. Full mushaf = 114 (by_surah) or 6236 (by_ayah). Partial coverage = lower. |
| `codec` | string | `mp3` (for now). |
| `container` | string | `mp3` (for now). |
| `sample_rate_hz` | int \| null | Probed; null for unprobed by_ayah. |
| `channels` | int \| null | 1 (mono) or 2 (stereo). |
| `bitrate_mode` | string | `cbr` \| `vbr` \| `mixed` \| `unknown`. |
| `bitrate_kbps_nominal` | int \| null | CBR exact; VBR average. **`null` when `bitrate_mode == "mixed"`** (no single value can represent the row — open the sidecar for per-chapter truth). |
| `total_duration_sec` | int \| null | Whole-mushaf duration, rounded seconds. Derived from sidecar sum first; falls back to `.audio_durations.json` cache. |
| `added_at` | datetime | ISO-8601 UTC. |
| `added_by_hf_id` | string | HF user id of the maintainer who added the row. |

### `audio_manifest/<slug>.json` (sidecar)

```jsonc
{
  "schema_version": 1,
  "slug": "<delivery slug>",
  "_meta": {
    "checksum": "sha256:<hex>",          // sole storage; row does NOT carry a copy
    "source_meta_reciter": "<original>", // for migrations/audit
    "source_manifest_path": "data/...",  // original ingestion path
    "chapter_count": 114,
    "category": "by_surah"
  },
  "chapters": {
    "1":  { "url": "https://...", "size_bytes": 803456, "duration_sec": 50, "bitrate_kbps": 128 },
    "2":  { ... },
    ...
  }
}
```

Chapter keys are stringified surah numbers (`"1"`–`"114"`) for `by_surah`, or `"<surah>:<ayah>"` for `by_ayah`. Per-chapter metric fields are nullable when not yet probed.

**Checksum semantics** (`_meta.checksum`):
- Computed at catalog build time as `sha256(normalized_urls_sorted.joined_by_newline)`.
- URL normalization: lowercase hostname, strip trailing slashes, drop fragment. Query order preserved (some CDNs are query-sensitive). Path case preserved (case-sensitive on many CDNs).
- Lives **only in the sidecar `_meta` block**. Re-probe jobs compute and compare. Row schema does not carry a copy.

### `aliases[]`

Empty in seed. Reserved for future slug/reciter_id renames. Shape:

```jsonc
{ "kind": "slug" | "reciter_id", "old": "...", "new": "...", "ts": "..." }
```

### `derived` (computed indices, regenerated on every catalog build)

| Field | Type | Notes |
|---|---|---|
| `source_channels[]` | array | M:N materialization: `{source, channel, delivery_count}` per observed pair. Caches the relation that's authoritative on per-delivery rows so admin queries don't have to GROUP BY at read time. |

## 5. Audio metadata: row vs sidecar

| Field | Uniform across chapters? | Lives in |
|---|---|---|
| `codec`, `container`, `sample_rate_hz`, `channels`, `bitrate_mode` | yes (encoder settings) | row |
| `bitrate_kbps_nominal` (CBR: exact; VBR: avg) | yes (label) | row |
| `total_duration_sec` (whole mushaf) | yes (aggregate) | row |
| `bitrate_kbps` (actual measured per chapter) | no (varies for VBR) | sidecar |
| `duration_sec` (per chapter) | no | sidecar |
| `size_bytes` (per chapter) | no | sidecar |
| `url` (per chapter) | no | sidecar |

### CBR vs VBR

Row-level `bitrate_mode` is a four-value enum derived from per-chapter probe data:

| Row value | Meaning |
|---|---|
| `cbr` | All probed chapters CBR, all with the same rate. `bitrate_kbps_nominal` = exact bitrate. |
| `vbr` | All probed chapters VBR. `bitrate_kbps_nominal` = encoder target / observed average. |
| `mixed` | Chapters disagree — either some CBR and some VBR, or all CBR with different rates. Use the sidecar for the per-chapter truth. |
| `unknown` | No chapters probed yet (default for by_ayah deliveries). |

Detection: `mutagen.mp3.MP3.info.bitrate_mode` (Xing/Info/VBRI/LAME header) → authoritative when present. Frame-by-frame scan over the first 256 KB → fallback. Both are run; see `scripts/probe_audio_meta.py::classify`. Per-chapter results live in the sidecar; `build_catalog.py::rollup_bitrate_mode` collapses them to the row.

### Per-chapter duration

Read from Xing/VBRI header when present (mutagen `mp3.info.length` — works on the 256 KB buffer when TOC is in the first frame). Falls back to `null` for files without Xing — total file probing is out of scope for v1 probes; that work is deferred.

### `total_duration_sec`

Sourced from `data/.audio_durations.json` cache where present (legacy v1 cache, ~80% coverage). Otherwise null. The bucket layout drops `_meta.json` and `_durations.json` as separate files — durations live on the delivery row.

### Style vs recording_context

Seed-time migration: legacy `style: "taraweeh"` rows split to `style: "murattal"` + `recording_context: "taraweeh"`. After migration:

- **`style`** captures **pace/ornamentation**: `murattal`, `mujawwad`, `muallim`, `children_repeat`, `hadr`. Encodes how the recitation sounds — fast/slow, plain/melodic.
- **`recording_context`** captures **why the recording exists**: studio / broadcast / prayer / taraweeh / mixed. `null` when not yet identified.

Together they answer: "What kind of recitation is this, and where did it come from?" — without conflating the two axes.

The `taraweeh` style slug is **removed from vocab**. Existing taraweeh entries are migrated by the build script; new entries that would have used it must pick a style (typically `murattal`) and set `recording_context: "taraweeh"`.

## 6. Naming style guide

Applied during the seed pass; new entries must follow these.

| Axis | Rule |
|---|---|
| `Al-` prefix | `Al-<Surname>` (capital A, hyphen). Never `AlSurname`, `al-surname`, or `Al Surname`. |
| Egyptian `El-` | **Preserve** when source-attested (Ahmed El-Shafei, Hamza El-Far). Regional signal. |
| Sun-letter (`Az-`, `Ath-`, `As-`) | Preserve where attested. Don't retroactively introduce — `Al-Sudais` stays. |
| `Abdul-` / `Abdel-` | **Glued**: `Abdulrahman`, `Abdelaziz`. Never spaced or hyphenated. |
| First-name canonical spellings | `Mohammed` (not Muhammad/Mohamed/Mohammad), `Ahmed` (not Ahmad/Ahmet), `Yusuf` (not Yousef/Youssef/Yousif), `Mahmoud` (not Mahmood). Also: `Khalid` (← Khaled), `Mansour` (← Mansoor), `Mishary` (← Mishari/Meshari), `Adel` (← Adil), `Khalil` (← Khaleel), `Yasser` (← Yassir), `Mustafa` (← Mostafa), `Hisham` (← Hesham), `Saeed` (← Sayeed), `Tawfiq` (← Tawfeeq). **Maintainer-override** (preserved here for audit-trail): the earlier `naming_consistency_report.md` recommended against forcing Mohammed/Ahmed/Yusuf normalization to preserve regional signal; that was deliberately overridden. |
| `bin` patronymic | Lowercase between names: `Ahmed Talib bin Humaid`. |
| Honorifics | **Strip** (Sheikh, Sheik, Shaik, Qari, Hafiz). One exception in seed (`Ustaz Zamri`) where no further name was available. |
| Numbers in names | Allowed only for Madinah/Makkah Taraweeh series years (e.g. `1437H`). |
| Apostrophes | Straight ASCII `'` (U+0027). |
| Compound-word casing | Lowercase after first letter (`Abdulmajid`, never `AbdulMajid`). |
| Slug mirrors name | `Al-X` → `al_x` in slug (e.g., `mahmoud_khalil_al_husary`). |

`reciters[].name_ar` is **preserved as-source** — no Arabic normalization beyond emptying literal `"unknown"`.

## 7. How the seed catalog was built

Sequence of operations + which artifacts each produced. All artifacts live in `.local/dedup/` (gitignored — scratch).

1. **Inventory** — `.local/dedup/build_inventory.py` walks `data/audio/<cat>/<source>/<slug>.json` × 870 manifests, extracts `_meta`, infers channel from first URL host. Output: `.local/dedup/inventory.json`.
2. **Dual-agent dedup pass** — ran in parallel:
   - **Programmatic agent** (`programmatic_cluster.py`): 5-pass normalization + token-sorted equality + fuzzy ratio + name-Arabic corroboration + surname-anchor pull-in. Produced 467 clusters.
   - **Manual agent**: read all 870 names by eye, used Quran-reciter domain knowledge to merge spelling variants (Husari/Hossary/etc.). Produced 426 clusters.
3. **Reconciliation** — `reconcile.py` diffs the two cluster files. 374 fully agreed; 48 membership disagreements (44 manual-merged-more, 4 programmatic-merged-more); 275 same-cluster name-choice disagreements.
4. **Same-channel duplicate probe** — for clusters where >1 member shared `(reciter, riwayah, style, channel)`, `probe_qul_duplicates.py` ran ffprobe on common chapters from each side. 14 pairs probed: 2 byte-identical (drop), 1 broken manifest (drop), 11 different masters (keep both, disambiguate).
5. **Reciter-level decisions** — human reviewed:
   - 4 over-merge cases from programmatic-agent (G21/G32/G44/G48) — kept manual's split for G21/G32, merged for G44/G48.
   - 12 manual-flagged edge cases (Shahat Anwar 3-way, Yassin Al-Jazaery, name swaps, …) — resolved interactively.
   - 1 garbled tvquran slug — renamed manifest, cleaned `_meta`.
6. **Follow-up probe** — `probe_followup.py` re-checked 2 suspicious "different recording" pairs with 5 more chapters each (confirmed same-recording, dropped one side) and tested the Husary tempo hypothesis (confirmed: both are murattal at different bitrates, not mujawwad mislabel).
7. **Bake** — `bake_final.py` applies all decisions to the manual cluster output: drops, merges, style reclasses, slug overrides. Output: `.local/dedup/final_clusters.json` (864 deliveries, 422 clusters, 0 slug collisions).
8. **Naming consistency** — agent audited all 422 cluster names. Produced style guide (§6) + 41 specific corrections.
9. **Mohammed/Ahmed/Yusuf normalization** — `name_normalize_scan.py` identified 62 clusters touched by canonical-spelling normalization. Applied universally (including surname positions: `Al-Ahmad` → `Al-Ahmed`).
10. **Corrections applied** — `apply_corrections.py` rewrites reciter_ids, names, and delivery slugs. Output: `.local/dedup/final_clusters_corrected.json` (98 reciter_id changes, 100 name changes, 183 slug changes, 0 collisions).
11. **Bulk probe** — `bulk_probe.py` (extends `scripts/probe_audio_meta.py`): for every by_surah delivery, HTTP Range-fetches first 256 KB of every chapter URL, runs mutagen+frame-scan, parses Xing for duration, reads `Content-Range` for size. Output: `.local/dedup/bulk_probe.json` + extended `.local/dedup/probe_cache.json`. by_ayah deliveries are skipped (cost too high; row fields fall back to null + total duration from cache).
12. **Catalog assembly** — `build_catalog.py` joins corrected clusters + probe data + `.audio_durations.json` + vocab files → `reciter_catalog.json` and 864 `audio_manifest/<slug>.json` sidecars.

## 8. Adding a single reciter (manual)

When a maintainer wants to add one reciter:

1. **Verify reciter_id doesn't collide.** Search `reciters[]` for existing `name_en` and `name_ar` variants of the new reciter. If a cluster exists, you're adding a delivery to an existing reciter — skip to step 3.
2. **Add `reciters[]` row.** Pick a `reciter_id` per the regex + naming style guide (§6). Fill `name_en`, `name_ar`, `country`, optional `notes`.
3. **Decide the delivery shape** — riwayah, style, recording_year (if known), source (must exist in `vocab.sources[]`; add a new source entry first if not), channel (must exist in `vocab.channels[]`).
4. **Compute the slug** per §3. If it collides with an existing delivery, follow the disambiguator rules.
5. **Probe chapter 1.** Run `python scripts/probe_audio_meta.py --reciter <source_meta_reciter>` or call `bulk_probe.classify()` for one URL — get `bitrate_mode`, `bitrate_kbps_nominal`, `sample_rate_hz`, `channels`. Set `codec`/`container` from the URL extension (mp3).
6. **Add `deliveries[]` row** with the probe results, `total_duration_sec` (from sidecar-sum or `.audio_durations.json` cache, or null), `chapter_count`, `added_at`, `added_by_hf_id`. The `audio_manifest_checksum` does NOT live on the row — it goes into the sidecar `_meta.checksum` only.
7. **Generate the sidecar** at `audio_manifest/<slug>.json` with the URL map. Per-chapter probe fields can be null initially; a later probe job fills them in.
8. **Validate** — run `scripts/validate_reciter_catalog.py` (planned, see [`../planning/inspector-deploy/v2/inspector-state-management.md`](../planning/inspector-deploy/v2/inspector-state-management.md) §3). Confirms FK integrity, slug regex, no collisions.
9. **Commit + push** to the bucket via the Inspector admin endpoint (Phase 5+) or directly via `huggingface_hub` for v0 maintainer access.

## 9. Adding a batch from a new source

When ingesting a new website (e.g., a future `quran.com` API):

1. **Add a `vocab.sources[]` entry.** Hyphens are permitted in source slug only (e.g., `surah-quran`). Set `audio_categories` to what the site exposes.
2. **Discover the channel.** Sample a few URLs the new source serves. If they route to an existing channel (`mp3quran`, `archive_org`, etc.), reuse it. If new, add a `vocab.channels[]` entry — see §10.
3. **Scrape into temporary per-reciter manifests** following the existing `data/audio/<category>/<source>/<slug>.json` shape (`_meta` block + chapter→URL map). This isn't strictly required but keeps the build pipeline uniform.
4. **Run the dual-agent dedup pass** scoped to the new batch:
   - Programmatic clustering against the existing `reciters[]` (use the corrected catalog as the reference set).
   - Manual cross-check: for each new manifest, decide whether it maps to an existing `reciter_id` or needs a new one.
5. **Probe the new batch** with `bulk_probe.py` (or `probe_audio_meta.py` for per-source runs). Skip by_ayah unless really needed.
6. **Apply naming style guide** — new reciters must conform to §6 from day one.
7. **Merge into catalog** via `build_catalog.py` (re-run with the new clusters merged in).
8. **Validate + commit.**

## 9.1 Removing a delivery or a reciter

Maintenance pattern — not implemented as automation yet, must be done by hand + a re-bake. Use cases: copyright takedown, deceased reciter family request, accidental duplicate from a scrape error.

**Removing a single delivery:**
1. Delete the row from `deliveries[]`.
2. Delete the sidecar `audio_manifest/<slug>.json`.
3. If the reciter has no remaining deliveries, optionally remove the `reciters[]` row (or leave it — orphan reciter rows are harmless).
4. Rerun `build_catalog.py` to refresh `derived.source_channels[]`.
5. **Audit**: append a record to the audit log (`<bucket>/audit/<YYYY>-<MM>.jsonl`) noting reason + actor.

**Removing an entire reciter:**
1. Remove all of their `deliveries[]` rows and corresponding sidecars.
2. Remove the `reciters[]` row.
3. Optionally add the old `reciter_id` to `aliases[]` with `new: null` to mark it as retired (forward-compat — schema doesn't yet support this; do as a comment for now).
4. Same audit-log requirement.

**Don't** repurpose a `reciter_id`. Once retired, the slug stays burned forever — repurposing breaks URL stability for any external system that cached the old mapping.

Formal deletion/archival tooling + the row-level "archived" flag are deferred. Until then, deletion is a maintainer-only manual operation with mandatory audit.

## 10. Adding a new channel

A new `vocab.channels[]` entry is needed when audio bytes come from a host not currently registered. Steps:

1. **Identify the host pattern.** Inspect URL hostnames from sample manifests. Use the most specific glob that captures the channel without false positives (e.g., `download.example.com` not `*.example.com`).
2. **Choose a slug.** Lowercase ASCII + underscores, 2–40 chars. Common form is `<domain_root>` (e.g., `mp3quran`, `tarteel`) or `<host>_<role>` (e.g., `archive_org`).
3. **Choose a `short`.** Used in delivery slugs — keep ≤10 chars, mnemonic.
4. **Add to `vocab.channels[]`.**
5. **Re-route ingestion.** Verify `bulk_probe.py`'s host→channel mapping picks up the new pattern. Add a regex if needed (see `HOST_TO_CHANNEL` in `.local/dedup/build_inventory.py`).

### Channel host migration (when an existing channel moves to a new domain)

When the underlying CDN renames or relocates (e.g., `download.tvquran.com` → `cdn.tvquran.net`):

1. **Update `vocab.channels[].host_patterns`** to add the new pattern alongside the old (keep the old for backward-compat reads of historical sidecars).
2. **Re-scrape affected manifests** to capture the new URLs. The catalog row identity is stable — only sidecar URLs change.
3. **Rerun the bulk probe** for affected deliveries. The sidecar `_meta.checksum` will change (different URLs), invalidating downstream caches.
4. **Audit-log the migration** — note the date, the host shift, and the count of deliveries touched. Required because external consumers caching URLs need to be told to re-fetch.

If the migration is partial (old host still works for some content), keep both patterns and let host→channel routing pick the right one per URL.

## 11. Probing

### When

- **New delivery added** — probe chapter 1 minimum to populate row audio metadata.
- **New source ingested** — bulk probe by_surah deliveries.
- **Suspected stale URLs** — manifest checksum changes (= URL list changed) → re-probe that delivery's sidecar.
- **Periodic** — quarterly bulk pass to catch silent format/URL changes.

### What to use

| Job | Script | Scope |
|---|---|---|
| Single-reciter VBR/CBR + bitrate detection | `scripts/probe_audio_meta.py --reciter <slug>` | One manifest |
| Bulk delivery row fields | `scripts/probe_audio_meta.py --all` (or `.local/dedup/bulk_probe.py` for the new schema) | All inspector-tracked reciters |
| Full sidecar population (per-chapter duration, size, bitrate) | `.local/dedup/bulk_probe.py` | `by_surah` deliveries (~78k chapters, ~20 min) |
| Per-ayah probing | **Not yet run** — by_ayah deferred until a consumer needs per-ayah metrics. Real cost is bounded: ~287k URLs × 200 ms / 20 concurrent workers ≈ 3–6 h on a single prober. Not "prohibitive" — just lower-priority than the by_surah pass. Trigger to revisit: any consumer requesting per-ayah duration/size/bitrate, or a quarterly maintenance window. |

### How it works

- **256 KB HTTP Range fetch** per URL. No full-file downloads.
- **mutagen** reads Xing/Info/VBRI/LAME headers when present (authoritative bitrate mode + duration).
- **Frame-by-frame bitrate scan** as fallback (`scan_frame_bitrates`).
- **Content-Range response header** gives total file size for free — no separate HEAD round-trip.
- **Cache**: `.local/dedup/probe_cache.json` keyed by URL. Reruns short-circuit cached probes.
- **Concurrency**: 20 workers globally, 10 for `*.archive.org` (politeness cap).
- **Manifest checksum**: `sha256(sorted_urls_joined_by_newline)` — sidecar carries it in `_meta.checksum`; row carries the same value. Re-probe job compares: if checksum unchanged, skip.

### `data/.audio_durations.json` interaction

Legacy v1 total-duration cache (~80% coverage of seeded reciters). Used to populate `deliveries[].total_duration_sec` for the seed. Going forward:
- New deliveries: probe total duration via sum-of-chapter-durations from sidecar (when sidecar is full). Otherwise null.
- The cache file itself is deprecated and will be deleted in Phase 1 of v2 cleanup.

## 12. Maintenance & known limitations

- **by_ayah deliveries are unprobed.** 46 deliveries (~287k URLs) have row-level audio fields as `null` and URL-only sidecars. Probing them is bounded work (3–6 h on a single prober at 20 concurrent workers) — defer until a real consumer needs the per-ayah metrics, then run `bulk_probe.py` with the by_ayah exclusion lifted.
- **Per-chapter duration is null when no Xing TOC** is in the first 256 KB of the chapter file. Affects a minority of older encodes. Full-file probing for these is deferred.
- **`surah-quran` source slug carries a hyphen.** Tolerated in `vocab.sources[].slug` only. Never in `reciter_id`, delivery `slug`, or channel slug.
- **No aliases yet.** `aliases[]` is empty in the seed. Slug/reciter_id renames must be handled by hand — write the old→new mapping into `aliases[]`, update the delivery rows, leave the sidecar at the old name + add a copy at the new name (or move). Formal rename tooling is future work.
- **`added_at` and `added_by_hf_id` are `2026-05-12T00:00:00Z` / `system_seed`** for every seed row. Real maintainer attribution begins with the first post-seed addition via the Inspector admin endpoint.
- **No `recording_year` data in the seed.** The field exists; populating it requires per-reciter research and is deferred.
- **`context` is `unknown` for ~all seed entries** except the migrated `taraweeh` style rows. Backfill is deferred — adding `context` per reciter is a domain-research task.
- **12 edge cases flagged during the manual dedup pass** are noted in `.local/dedup/naming_consistency_report.md`. They were resolved interactively at seed time; if any prove wrong later, fix via a corrections script + re-bake.
- **Additional name normalizations beyond Mohammed/Ahmed/Yusuf/Mahmoud** (Saud/Khalid/Hassan/Ibrahim/Omar/Othman/etc.) are an open candidate set — see `.local/dedup/name_normalize_extra_proposed.json` if/when generated. Each variant family is a separate decision because some carry regional signal worth preserving.

## Appendix: artifact map

| Path | Purpose | Status |
|---|---|---|
| `.local/dedup/inventory.json` | Source manifest inventory + channel inference | scratch |
| `.local/dedup/programmatic_clusters.json` | Programmatic dedup output (467 clusters) | scratch |
| `.local/dedup/manual_clusters.json` | Manual dedup output (426 clusters) | scratch |
| `.local/dedup/reconciliation_report.{json,md}` | Diff of the two cluster files | scratch |
| `.local/dedup/qul_duplicate_probe.json` | ffprobe results for same-channel duplicate pairs | scratch |
| `.local/dedup/final_clusters.json` | Reconciled + decided cluster file (pre-naming) | scratch |
| `.local/dedup/naming_consistency_{report.md,corrections.json}` | Style guide + 41 corrections | scratch |
| `.local/dedup/name_normalize_proposed.json` | 62 Mohammed/Ahmed/Yusuf corrections | scratch |
| `.local/dedup/final_clusters_corrected.json` | After all naming corrections | scratch |
| `.local/dedup/bulk_probe.json` | Per-delivery + per-chapter probe results | scratch |
| `.local/dedup/probe_cache.json` | URL → probe-result cache | scratch |
| `.local/dedup/reciter_catalog.json` | Final seed catalog | **shipping** → `<bucket>/catalog/reciter_catalog.json` |
| `.local/dedup/audio_manifest/<slug>.json` | 864 sidecars | **shipping** → `<bucket>/catalog/audio_manifest/<slug>.json` |
