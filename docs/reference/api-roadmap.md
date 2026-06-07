# Public Data API — roadmap & design reference

> **Status: forward-looking. Not built yet.** Unlike the other reference docs (which
> describe what *is*), this captures the agreed *target shape* and the *why*, so future
> work doesn't re-derive it. When the API starts shipping, split the built parts into a
> normal what-is reference and keep the unbuilt parts here.

## Why this exists (the problem)

QUA already ships its data three ways, all **adapters over the canonical bucket** (see
[`dataset-and-releases.md`](dataset-and-releases.md)):

- **GitHub Releases** — versioned JSON tiers + per-reciter zips + `manifest.json` + checksums.
- **HF dataset** — parquet, queryable via `datasets` / the HF datasets-server.
- **Inspector app** — the editor/admin surface.

The data is available; the **barrier is format-literacy**. To use it a developer must learn
the zip layout, the three timestamp tiers, the manifest schema, the 42-token letter vocab,
the dedup semantics, and then stitch things together themselves (pair audio URLs to timings,
do per-ayah/per-surah lookups, poll for updates). That's a lot of reading for "play ayah
2:255 with word highlighting."

**The API's job is to erase that barrier**: call functions, not file formats.

## End-goal vision

> **A typed Python/JS client for the QUA dataset — call functions, not file formats.** It
> fetches only the slice you ask for and caches it, serves the latest data by default (no
> manual update checks) while letting you pin a version or vendor a full offline snapshot,
> and encodes the schemas as type hints so you never reverse-engineer the release layout.

Pillars (the honest value prop — see [Non-claims](#non-claims--pitfalls) for what NOT to overstate):

- **One interface, not formats** — abstracts GH releases / HF dataset; call `reciter().ayah()`
  instead of learning zips, tiers, manifests, the char vocab.
- **Typed** — IDE autocomplete + models generated from the same schemas the data ships with.
- **Fetch-what-you-need + cached** — granular slices, instant on repeat.
- **Fresh by default, reproducible on demand** — always-latest automatically; pin a version
  when you need stability.
- **Online or offline, same API** — lazy remote by default; vendor a snapshot for air-gapped / CI / bulk.
- **Correct by construction** — the dedup, tokenization, and audio pairing we use, not a
  consumer reimplementation.

## Architecture — three layers

```
A. Canonical static data on existing free hosting   ← the "backend" (no server to run)
       (HF dataset repo + GitHub Releases = the CDN; produced by the bucket→adapter pipeline)
                         ▲ HTTP GET (granular, versioned, cacheable)
B. SDKs (pip + npm)  ← THE product surface
       typed methods · lazy fetch + cache · latest-by-default + pin + vendor · reuse dedup/tokenization
                         ▲ only for global/compute ops
C. Optional compute/query service (HF Space)  ← built ONLY if demand appears
       cross-reciter queries · search · aggregations · on-the-fly audio clipping
```

### Layer A — canonical static data (the backend is just files)

The bucket→adapter pipeline already emits versioned data to **public, free hosting**. Make the
layout **granular** (per-reciter, and per-surah shards — formalize the `shard.py` idea into the
on-disk layout) so a client fetches a small slice, not a whole archive. Add a small `latest`
pointer + an index/`openapi.json` for discovery.

### Layer B — the SDKs (this is the product)

Rich, ergonomic, typed methods. The "cool functionality" (ayah/surah lookup) is **client-side
indexing over fetched slices**, not server compute — so it needs no server. Illustrative surface
(not final):

```
qua.reciters(riwayah="hafs", style="murattal")        # filter the catalog (local)
qua.reciter("mishary_...").surah(36).words             # fetch+index a surah shard
qua.reciter("...").ayah(2, 255).letters                # ayah lookup (local)
ayah.audio_url   /   ayah.clip()                        # CDN url / byte-range (never proxied bytes)
qua.check_updates(...)                                  # folds in check_updates.py logic
Qua(data_version="v0.3.0")  /  Qua(data_dir="./snap")  # pin / vendor
```

### Layer C — optional compute service (the HF Space)

Stand up a *server* **only** for what a client genuinely can't do locally without downloading
everything: cross-reciter / global queries, search, aggregations, dynamic audio clipping. The
SDK routes *only those* methods to it and does everything else local-static — the dev never
knows which. ⚠️ Free HF Spaces **sleep / cold-start** and have limited concurrency: **never
route bulk static reads through the Space**, or simple lookups become slow/flaky. Static reads
stay on the CDN; the Space handles compute only. (The HF datasets-server already gives a free
REST + DuckDB query API over the parquet — may cover much of the query use case for free.)

## Why this shape (rationale)

- **Data is static + immutable per version** → a stateful API server is the *wrong default*
  (cost, latency, SPOF, scaling) for data a CDN serves free at infinite scale.
- **Rich per-ayah/surah functionality is client-side indexing**, not server compute → no server
  needed for the things that feel like "a powerful API".
- **Audio bytes never flow through your API** (bandwidth trap) → the API returns CDN *URLs*;
  bytes come from the CDN; clips via edge/byte-range.
- **One interface over many formats** kills the real barrier (format-literacy) and prevents
  buggy reimplementations of dedup/tokenization.

## Hosting & cost

You **don't pay for or stand up new infra** for Layers A/B. Your existing **public** surfaces
*are* the CDN: HF hosts public datasets free (Xet-backed), GitHub hosts release assets free —
both over their CDNs. The SDK does HTTP GETs against those. The **private pipeline bucket is the
canonical *source*, NOT the public read surface**; the HF dataset + GH releases are the published
read replicas. A dedicated CDN (Cloudflare R2/Pages, etc.) is only needed if you outgrow HF/GH.

## Caching model

The cache lives **wherever the SDK process runs**:

| Runtime | Cache location | Whose disk |
|---|---|---|
| pip in a notebook/script | `~/.cache/qua/` | the dev's machine |
| pip / npm(Node) in a backend | server filesystem (shared across requests) | the dev's server |
| CI / training cluster | runner disk (ephemeral unless persisted) | the dev's infra |
| npm in the browser | browser HTTP cache / IndexedDB | the **end-user's** device |

**Who controls policy — three layers, the real lever is yours:**

1. **You — HTTP cache headers (the lever).** Versioned/pinned URLs are immutable → serve
   `Cache-Control: immutable, max-age=1y`. The only mutable thing is the tiny `latest` pointer →
   short TTL + `ETag`. This governs freshness everywhere for free, even with zero SDK cache code.
2. **The dev — local persistence + size.** SDK defaults (cache dir, max size, eviction, TTL,
   on/off), overridable (`QUA_CACHE_DIR`, constructor args). Tuned per environment.
3. **The end-user — nothing** beyond clearing their browser cache.

**How much:** lazy mode caches only *accessed* slices (a few MB typical; per-surah shard ≈ KB–tens
of KB, a full reciter's letters ≈ a few MB gz), bounded by a default cap + LRU. Immutable/pinned
entries live forever; `latest` entries are `ETag`-revalidated, not re-downloaded. Vendored mode =
whatever snapshot the dev pulled (full corpus ≈ low hundreds of MB) — an explicit choice. Safe to
cache hard because versioned data is content-addressed & immutable.

## Versioning model — two decoupled axes

| Axis | Versions | Bumps when |
|---|---|---|
| **Package version** (pip/npm semver) | the **code** — methods, fixes, features | `pip install --upgrade qua` |
| **Data version** (release tags / HF revisions) | the **data** — new/refreshed reciters | every cut; **no package upgrade** |

- **Latest data by default** — SDK resolves the `latest` pointer, so devs get current data without
  upgrading the package. Data updates ≠ package releases.
- **Pin for reproducibility** — `Qua(data_version="v0.3.0")` locks an immutable snapshot (GH tags /
  HF revisions). "Latest" and "pin" aren't contradictory: latest is default, pin is opt-in (researchers
  will want it).
- **Compatibility guard** — the package declares which data `schema_version`s it understands → old
  package + new data fails *loud*, never mis-parses.
- **`check_updates`** folds into `qua.check_updates()` — tells a dev whether their pinned/used reciters
  changed upstream.

## Data access modes (online/offline parity)

`remote-lazy` (default) · `vendored/offline` (`data_dir` / env) · `pre-warm snapshot`. **Same API
across all** — the dev chooses the source; the methods are identical. Offline mode is a first-class
feature (reproducible ML, air-gapped clusters, CI), not a fallback.

## Non-claims & pitfalls

Things to *not* overstate or get wrong:

- ❌ "lower latency than a fetch" — a **cold** first call ≈ a normal download. The wins are
  **granularity** (fetch a slice, not a whole archive) + **caching** (instant repeat). Say that.
- ❌ don't serve **audio bytes** through your API — return CDN URLs; clips via edge/range.
- ❌ don't route **bulk static reads** through the HF Space (cold-start/concurrency) — Space = compute only.
- ❌ don't republish the **package** on every **data** change — the axes are decoupled.
- ❌ don't let an **old package mis-parse new data** — the `schema_version` compatibility guard is mandatory.
- ❌ the API must stay an **adapter over the canonical bucket**, never a 4th source of truth — same
  generation path as `cut_release` / `publish_hf`.

## What this builds on (already in place)

- **bucket-as-canonical + adapter pipeline** (`qua_jobs/cut_release.py`, `qua_jobs/publish_hf.py`).
- **versioned releases + `manifest.json` + per-reciter `content_hash`** — the primitives for
  pinning, "latest" resolution, and update detection.
- **Pydantic schemas → TS codegen** (`qua_shared/schemas/` → `scripts/codegen/regen_fe_types.py`) —
  free typed models for *both* SDKs.
- **canonical dedup + tokenization in `qua_shared`** (`timestamps_dedup.py`, `letter_vocab.py`) —
  reuse for correct-by-construction reads; do not reimplement client-side.
- **`check_updates.py`** logic — folds into the SDK.

## Roadmap / sequencing

1. **Formalize Layer A** on the existing HF/GH surfaces: granular per-reciter/per-surah layout, a
   versioned URL scheme, a `latest` pointer, immutable cache headers, and an index/`openapi.json`.
   (Largely a layout + headers exercise over data you already publish.)
2. **Python SDK (pip)** — richest leverage from existing schemas; serves the research/HF audience.
   Methods over static, lazy + cache, pin/vendor, `check_updates`, typed models.
3. **JS SDK (npm)** — the web playback/highlighting audience; reuse the codegen'd TS types.
4. **Layer C compute service (HF Space)** — *only if* demand: global queries/search/aggregations/
   dynamic clips. SDK routes those transparently. (Re-evaluate against the free HF datasets-server first.)
5. **Dedicated CDN** — only if HF/GH limits are hit.

### Positioning recommendation

Lead with one path so newcomers aren't paralyzed, then progressively disclose the rest:

| On-ramp          | Recommend it when…                                                                                 |
|------------------|---------------------------------------------------------------------------------------------------|
| **SDK (pip/npm) ← default**   | Building an app/tooling in Python or JS; want ergonomics, types, caching, auto-updates.       |
| **HF dataset**   | ML training/data pipelines, bulk/SQL analytics, audio-embedded, zero-install exploration.          |
| **GitHub Releases** | Any other language, zero-dependency, offline/vendored, auditable, citable, simple one-offs.        |

## Open decisions (defer until building)

- Sharding granularity (per-surah vs per-reciter) + exact URL scheme.
- Whether to expose `tokenize(text)` in the SDK (the earlier "tokenizer helper" question) — if shipped,
  source it from `qua_shared/letter_vocab.py` so it can't drift; ship on demand, not speculatively.
- REST vs GraphQL for Layer C (only relevant if Layer C is built).
- Audio clip strategy: edge function + byte-range vs precomputed.
- Auth / rate-limiting — only if a public compute service is exposed.

## Related

- [`dataset-and-releases.md`](dataset-and-releases.md) — the adapter model + release/dataset formats this reads from.
- [`data-migrations.md`](data-migrations.md) — schema codegen rationale (writer/reader drift).
- `qua_shared/letter_vocab.py` — the letter-tier tokenization the SDK should reuse, not reimplement.
