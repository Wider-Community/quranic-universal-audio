# Extraction → bucket → inspector handoff

How audio + alignment artifacts go from a contributor's source links to a
reviewable `reciters/<slug>/` folder the inspector picks up. Two doors in:

- **ALIGN** — a slug already exists (catalogued delivery) and the offline
  pipeline aligns it.
- **INGEST** — a slugless intake request (new combo / new reciter) that the
  pipeline mints into a delivery, then aligns.

Both converge on the same reconciler: once `reciters/<slug>/` appears for a slug
in `AWAITING_ALIGNMENT`, `auto_detect` fires `reciter.alignment_completed` and
the row moves to `AWAITING_REVIEW`.

No audio/peaks/route logic here — that's `backend.md` / `peaks.md` / `prefetch.md`.

## The offline pipeline — sole writer of `reciters/<slug>/`

Katana extraction (`.local/extraction/`) is the only writer of per-reciter
content. For a given slug it fetches/probes source audio, runs VAD → CTC ASR →
DP alignment, and writes the full `reciters/<slug>/` set:

```
reciters/<slug>/
├── audio/<chapter>.mp3       # Xing TOC injected if VBR (audio_persist::_ensure_xing)
├── peaks/<chapter>.json.gz   # slim int8 packed gzip (schema v3)
├── detailed.json             # segments / timestamps / low_confidence / auto_split / pipeline_meta
├── segments.json
├── edit_history.jsonl
├── edit_history_peaks.jsonl
├── pipeline_meta.json
├── auto_split_v1.json
└── audio/_done.json          # written atomically LAST; offline audit/upload artifact only — NOT read by the inspector at runtime
```

Chapter keys: `"1"`..`"114"` for `by_surah`, `"<surah>:<ayah>"` for `by_ayah`.
The pipeline also writes the audio-manifest sidecar
`catalog/audio_manifest/<slug>.json` (per-chapter URL + bitrate + duration + size
+ mode) — single source of truth for chapter↔URL routing and VBR mode. See
`backend.md`.

The inspector at runtime only **reads** `reciters/<slug>/` — it never fetches
from a CDN to warm the bucket, and **nothing deletes it** (the hourly GC sweeper
was removed; content persists indefinitely). See `prefetch.md`.

### YouTube / yt-dlp sources *create* the encode (vs preserve it)

Every other source preserves the publisher's mp3 bytes verbatim and only injects
a Xing seek header (`-c:a copy`). A YouTube/playlist source is the exception:
the source is opus/m4a, so `segments/audio_io.py::_download_via_ytdlp` fetches
`bestaudio` and does ONE controlled encode → **128 kbps CBR / 44.1 kHz / mono**,
`-vn` (cover-art stripped — an APIC stream 0-byte-muxes on the static ffmpeg).
The watch URL can't be HTTP-frame-probed, so the audio-manifest sidecar + the
delivery rollup are authored from a **post-align reprobe** of the produced files
(`ingest_intake.py::reprobe_persisted_audio`), not from the source URL. These
deliveries are bucket-served only — the watch URL is provenance, never streamed
by the audio-proxy. See `catalog.md` §5 and the `segments-extraction` skill's
`references/playlist_intake.md`.

## The reconciler — `services/segments/auto_detect.py`

A single-worker background loop (`start_background_loop`, default 60 s; gated by
`INSPECTOR_AUTO_DETECT=1`, surfaced via `/healthz`). Each pass diffs the set of
slug folders under the `reciters/` content prefix against a process-local "seen"
set, and for every **new** slug:

1. `state.get_row(slug)` — if the row is `None` or its state is not
   `AWAITING_ALIGNMENT`, skip (the slug is marked seen so it isn't retried).
2. Else `state.transition(slug, "reciter.alignment_completed", actor=SYSTEM_ACTOR)`
   → row moves `AWAITING_ALIGNMENT → AWAITING_REVIEW` ("Available for review").

`SYSTEM_ACTOR = Actor(hf_user_id="system", login_at_time="system", role=OWNER)`
— owner role is required because the same transition applies the pending
catalog edits via `pending_requests.apply_and_archive_completed`.

`hydrate_initial_seen()` runs at boot: it snapshots current slug folders into the
seen set **and** catch-up fires `alignment_completed` for any slug already in
`AWAITING_ALIGNMENT` with content on the bucket (covers an upload that completed
while the server was down). Idempotent.

> **Gate, not a folder scan for "done".** The reconciler keys on the *state row*,
> not on `_done.json` — and at runtime **nothing** consults `_done.json` (it's an
> offline audit/upload artifact only; the old TTL/sweeper that read it is gone).
> A slug whose folder appears **without** a state row in
> `AWAITING_ALIGNMENT` is silently ignored — it is marked seen and never fires.
> This is why intake content must seed `AWAITING_ALIGNMENT` (below) before the
> folder lands, not after.

## The three request kinds

All requests live in one `requests` table, discriminated by the `kind` column.
The state machine, audit log, and per-reciter content are identical across kinds
— they differ only in how the slug comes to exist.

| `kind` | Slug at submit | Path |
|---|---|---|
| `existing_combo_edit` | a real catalogued slug | Slug-based edit request. `reciter.requested` seeds `AWAITING_ALIGNMENT` + a pending entry; the offline pipeline aligns the slug; `auto_detect` flips it to `AWAITING_REVIEW`. End-to-end working — `routes/claims/requests.py::submit_request`. |
| `existing_reciter_new_combo` | `NULL` (slugless) | Reciter exists; the (riwayah, style) combo does not. Owner accepts (`accepted`, slug stays `NULL`); ingest mints the delivery. |
| `new_reciter` | `NULL` (slugless) | Neither reciter nor delivery exists. Owner accepts, stamping a canonical `reciter_id` into the payload; ingest mints reciter + delivery. |

Slugless intake submission shape (`qua_shared/schemas/intake_requests.py`,
`routes/claims/requests.py::submit_intake` → `services/admin/intake.py::submit`):
the row carries `kind`, `reciter_id` (combo only), `proposed_edits`
(`ProposedEdits` — riwayah/style/identity/recording fields), `source`
(`IntakeSource`: direct per-chapter `links` or a `playlist` URL), and
`attestations` (distribution / links-verified / storage rights — all required).
Everything not a first-class column lands in the row's `payload` JSON.

**Owner accept** (`services/admin/intake.py::accept`,
`POST /api/admin/requests/<rid>/accept`) is a lightweight approval — it does
**not** write the catalog. It stamps the owner-confirmed `reciter_id` (new
reciter only) and flips `status` to `accepted` with `slug` still `NULL`. The
delivery's `source`/`channel`/`slug`/bitrate are deferred to ingest because they
can only be validly determined by probing the actual audio.

## Two offline work queues

The offline pipeline discovers its work from the DB (source of truth). Two
disjoint queries:

| Queue | Discovery query | What runs |
|---|---|---|
| **ALIGN** | `delivery_states.state == 'awaiting_alignment'` | Slug already minted (any kind, post-accept). Fetch/probe/align, write `reciters/<slug>/`. |
| **INGEST** | `requests` where `status='accepted' AND slug IS NULL AND kind IN ('existing_reciter_new_combo','new_reciter')` | Slugless accepted intake. Probe/extract, then POST the ingest endpoint to mint the delivery — which seeds `AWAITING_ALIGNMENT`, putting it on the ALIGN queue. |

INGEST feeds ALIGN: ingest's job is to turn a slugless accepted request into a
catalogued slug in `AWAITING_ALIGNMENT`; the regular ALIGN pass then aligns it
and `auto_detect` advances it to `AWAITING_REVIEW`.

## The intake-ingest endpoint

The offline ingest worker probes/extracts an accepted slugless request, presents
the proposed delivery to a human, and on approval POSTs the ingest endpoint
authenticated by an HF token. The endpoint mints reciter + delivery + slug,
writes the audio-manifest sidecar, seeds `AWAITING_ALIGNMENT`, and back-fills
`requests.slug`. From there the slug is on the ALIGN queue.

### Contract

`POST /api/admin/intake/<request_id>/ingest`

**Auth** — header `Authorization: Bearer <HF_TOKEN>` **or** the
`inspector_session` owner cookie, resolved in `services/auth/token_auth.py`
(`resolve_owner_from_token`, with a 5-minute id-only TTL cache). The bearer is
validated via `huggingface_hub.whoami(token)` → `user["id"]` (fallback
`user["_id"]`) → `access.resolve_role(id)` which must be `Role.OWNER`. The OAuth
identity stored as `hf_user_id` is the userinfo `sub`, which the HF user API
returns as that same `id`/`_id`, so the bearer-derived id resolves the same role
row as the cookie path. Fail **closed**: any `whoami` error rejects, never
bypasses. The bearer path is CSRF-exempt (server-to-server); the cookie path is
same-origin-checked.

| Condition | Status |
|---|---|
| neither bearer nor owner cookie | `401` |
| authenticated but non-owner | `403` |
| unknown `request_id` | `404` |
| invalid body / not an accepted intake / wrong kind | `400` |
| slug collision | `409` |
| vocab FK still missing after `vocab_additions` | `422` |
| ok | `200` |

**Request body**

```jsonc
{
  "reciter": {                              // required when kind=new_reciter; null otherwise
    "reciter_id": "string",
    "name_en": "string",
    "name_ar": "string|null",
    "country": "string|null"
  } | null,
  "delivery": {
    "slug": "string",
    "reciter_id": "string",
    "riwayah": "string",
    "style": "string",
    "source": "string",
    "channel": "string",
    "audio_category": "by_surah" | "by_ayah",
    "recording_year": "int|null",
    "recording_context": "string|null"
  },
  "vocab_additions": {                      // only when delivery.source/channel not yet in Vocab
    "sources":  [{"slug": "string", "name": "string"}],
    "channels": [{"slug": "string", "name": "string", "short": "string", "host_patterns": ["string"]}]
  } | null,
  "audio_manifest": {
    "chapters": {
      "<key>": {
        "url": "string",
        "bitrate_kbps": "int|null",
        "bitrate_mode": "cbr" | "vbr" | null,
        "duration_sec": "float|null",
        "size_bytes": "int|null"
      }
    }
  },
  "reason": "string|null"
}
```

`<key>` follows the manifest convention: `"1"`..`"114"` for `by_surah`,
`"<surah>:<ayah>"` for `by_ayah`.

**Pre-flight** (before any DB write): validate the body; reject an unknown
`request_id` (`404`) or a non-accepted / non-slugless / wrong-kind row (`400`);
reject a slug that already has a delivery (`409`) — checked up front so the
response is a clean `409`, not a rolled-back integrity error. Then build and
write the `catalog/audio_manifest/<slug>.json` sidecar via the storage backend
(`storage_paths.audio_manifest_path`). The sidecar is written **before** the DB
transaction: the bucket is not part of the SQLite transaction, so writing it
inside would orphan it on rollback, and writing it after commit would leave a
committed delivery with no manifest (the idempotent re-ingest no-op never repairs
it). A pre-write orphan is harmless — keyed by a slug with no delivery,
overwritten verbatim on retry — and it keeps slow bucket I/O off the serialized
write lock.

**Commit** — one `services/db/sync.py::durable_transaction()`:

1. Apply `vocab_additions` (idempotent `add_source` / `add_channel`) so the
   delivery's `source`/`channel` FKs resolve. Still unresolved → `422`.
2. `catalog.add_reciter(...)` when `"reciter"` is provided and new — idempotent
   on `reciter_id`.
3. `catalog.add_delivery(Delivery(**delivery))`.
4. `state.transition(slug, "reciter.requested", actor, payload={"proposed_edits": {}, "comments": null, "auto_claim": false})`
   — seeds `AWAITING_ALIGNMENT` + its pending entry (same handler the
   `existing_combo_edit` flow uses).
5. `repo_requests.resolve_by_id(request_id, status='accepted', transitioned_by=actor, slug=slug)`
   — back-fills `requests.slug` to link the freshly-minted delivery.

`actor = Actor(hf_user_id=<whoami id>, login_at_time=<whoami name>, role=OWNER)`.

**Response 200** — `{"ok": true, "slug": "<slug>", "state": "awaiting_alignment"}`.

**Idempotent** — if the request row already has a non-null `slug` (already
ingested), return `200` no-op with the existing slug; do not re-mint.

After ingest the slug sits in `AWAITING_ALIGNMENT` with no `reciters/<slug>/`
folder yet. The ALIGN pass writes the folder; `auto_detect` then advances the row
to `AWAITING_REVIEW`. The sequencing matters: the state row exists **before** the
folder lands, so the reconciler's gate is satisfied.

## Discovery queries (offline pipeline)

```sql
-- ALIGN queue: slugs whose audio/alignment the pipeline must produce.
SELECT slug FROM delivery_states WHERE state = 'awaiting_alignment';

-- INGEST queue: accepted slugless intake awaiting delivery minting.
SELECT id, kind, payload
FROM requests
WHERE status = 'accepted'
  AND slug IS NULL
  AND kind IN ('existing_reciter_new_combo', 'new_reciter');
```

The DB (`db/inspector.db`, synced to the bucket) is the sole source of truth for
state / catalog / requests. Bucket JSON under `requests/`, `state/`, `catalog/`
(other than the per-reciter manifest sidecar) are dead backups — never read or
write them.

## Where to look

| File | Role |
|---|---|
| `services/segments/auto_detect.py` | reconciler loop, `SYSTEM_ACTOR`, catch-up firing |
| `services/admin/intake.py` | slugless submit / owner-accept / probe / resolve |
| `qua_shared/schemas/intake_requests.py` | `IntakeSubmission`, `IntakeSource`, `IntakeAttestations` |
| `services/db/repo_requests.py` | `requests` table — `submit`, `resolve_by_id` (slug back-fill), `set_payload` |
| `services/state/catalog.py` | `add_reciter`, `add_delivery`, `add_source`, `add_channel` (the ingest mint calls) |
| `qua_shared/schemas/catalog.py` | `Delivery`, `ReciterEntry`, `Source`, `Channel`, `Vocab`, `AudioManifestSidecar` |
| `qua_shared/schemas/state.py` | `ReciterState` (catalogued → … → released) |
| `routes/claims/requests.py` | submit / accept / probe / return / discard / **ingest** routes |
| `services/auth/token_auth.py` | bearer-token OWNER auth (`resolve_owner_from_token`, id-only cache) |
| `services/auth/access.py` | `resolve_role(hf_user_id)` for bearer + cookie auth |
| `services/auth/hf_users.py` | HF id resolution shape (`id` / `_id`) |
