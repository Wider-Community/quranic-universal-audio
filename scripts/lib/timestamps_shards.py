"""Shared sharding logic for the deployed Timestamps tab read-path.

Splits a `timestamps_full.json` document into per-chapter `.json.gz` shards
the frontend fetches on demand. Used by:

  - `.github/scripts/build_reciter.py --build-timestamps <slug>` — uploads
    shards to the HF dataset for the deployed read path.
  - `inspector/routes/timestamps.py` (local mode) — slices on demand and
    serves at `/api/ts/shard/<reciter>/<chapter>` so the frontend uses the
    same shard-fetch model in both modes.

Shard schema is documented in `docs/timestamps-tab-deployment-plan.md` §2.
"""

from __future__ import annotations

import gzip
import hashlib
from typing import Any

# Schema fields preserved from the source `_meta` block. New fields can be
# added without bumping the schema version as long as existing clients ignore
# unknown keys (they do — see ts_client in inspector frontend).
_PRESERVED_META_FIELDS = (
    "padding",
    "aligner_model",
    "method",
    "beam",
    "shared_cmvn",
    "audio_source",
    "audio_reciter",
    "created_at",
)

SCHEMA_VERSION = 1


def _filter_mfa_failures(failures: list[dict] | None, chapter: int) -> list[dict]:
    """Keep only `_meta.mfa_failures` entries belonging to this chapter."""
    if not failures:
        return []
    out: list[dict] = []
    for fail in failures:
        verse = str(fail.get("verse", ""))
        if not verse:
            continue
        try:
            ch = int(verse.split(":", 1)[0])
        except ValueError:
            continue
        if ch == chapter:
            out.append(fail)
    return out


def _slice_audio_urls(audio_urls_fallback: dict | None, chapter: int) -> dict:
    """Return only URL entries for `chapter` (verse keys like `1:1`).

    Per-surah audio manifests use chapter-numeric keys (`"1"`, `"2"`); per-ayah
    manifests use `"<surah>:<ayah>"`. Both shapes are scoped here.
    """
    if not audio_urls_fallback:
        return {}
    out: dict = {}
    str_chapter = str(chapter)
    for k, v in audio_urls_fallback.items():
        if k == "_meta":
            continue
        if k == str_chapter:
            # by_surah single-key entry — keep as-is.
            out[k] = v
            continue
        if ":" in k and k.startswith(f"{chapter}:"):
            out[k] = v
    return out


def split_to_shards(
    timestamps_full_doc: dict,
    *,
    reciter: str,
    audio_category: str,
    url_template: str,
    audio_urls_fallback: dict | None = None,
) -> dict[int, dict]:
    """Split a `timestamps_full.json` into per-chapter shard documents.

    Args:
        timestamps_full_doc: parsed `timestamps_full.json` (top-level
            `_meta` plus verse-keyed entries like `"1:1"`).
        reciter: slug stamped into each shard's `_meta`.
        audio_category: ``"by_surah"`` or ``"by_ayah"``.
        url_template: protocol-stripped template (e.g.
            ``everyayah.com/data/Saad_Al_Ghamdi_40kbps/{surah:03d}{ayah:03d}.mp3``).
            Empty string falls back to per-verse `audio_urls`.
        audio_urls_fallback: full `data/audio/<source>/<reciter>.json`
            content (with `_meta`) — only consulted when ``url_template`` is
            empty. The relevant slice is inlined into each shard's `_meta`.

    Returns:
        ``{chapter: shard_doc}`` mapping. Each shard_doc is a dict with a
        `_meta` block plus the chapter's verse rows in canonical sort order.
    """
    src_meta = timestamps_full_doc.get("_meta", {}) or {}
    chapters: dict[int, dict] = {}

    # Group verse rows by chapter.
    for key, val in timestamps_full_doc.items():
        if key.startswith("_"):
            continue
        # Compound keys ("37:151:3-37:152:2") are sorted into the
        # surah of the *start* verse. Their `_provenance` carries
        # the actual verse_keys for downstream rendering.
        first_part = key.split("-", 1)[0]
        try:
            chapter = int(first_part.split(":", 1)[0])
        except (ValueError, IndexError):
            continue
        chapters.setdefault(chapter, {})[key] = val

    # Build each shard with its own `_meta`.
    out: dict[int, dict] = {}
    for chapter, verses in chapters.items():
        meta: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "reciter": reciter,
            "chapter": chapter,
            "audio_category": audio_category,
            "url_template": url_template or "",
        }
        # Preserve aligner-side meta fields when present.
        for field in _PRESERVED_META_FIELDS:
            if field in src_meta:
                meta[field] = src_meta[field]

        # Per-chapter mfa_failures slice — keeps the existing validation
        # surface (boundary panel + failure list) reachable from a single
        # shard fetch.
        failures = _filter_mfa_failures(src_meta.get("mfa_failures"), chapter)
        if failures:
            meta["mfa_failures"] = failures

        # Audio URL fallback only when the template couldn't be derived.
        if not url_template:
            sliced = _slice_audio_urls(audio_urls_fallback, chapter)
            if sliced:
                meta["audio_urls"] = sliced

        # Sort verse keys for deterministic byte-output → stable hashes.
        shard = {"_meta": meta}
        for k in sorted(verses.keys(), key=_verse_key_sort):
            shard[k] = verses[k]
        out[chapter] = shard

    return out


def _verse_key_sort(key: str) -> tuple[int, int, int]:
    """Sort key for verse refs. Compound refs sort by their start tuple."""
    first = key.split("-", 1)[0]
    parts = first.split(":")
    try:
        return (
            int(parts[0]) if len(parts) > 0 else 0,
            int(parts[1]) if len(parts) > 1 else 0,
            int(parts[2]) if len(parts) > 2 else 0,
        )
    except ValueError:
        return (0, 0, 0)


def gzip_shard(shard_doc: dict) -> bytes:
    """Serialize and gzip a shard document deterministically.

    Uses orjson for speed/UTF-8 fidelity. `mtime=0` on the gzip header so
    re-running the build with unchanged input produces byte-identical
    output (load-bearing for the hash-diff cache).
    """
    import orjson

    payload = orjson.dumps(shard_doc)
    return gzip.compress(payload, compresslevel=6, mtime=0)


def sha256_hex(b: bytes) -> str:
    """SHA-256 hex digest of `b`. Used by the manifest's shard_hashes index."""
    return hashlib.sha256(b).hexdigest()


def derive_url_template(manifest_data: dict, audio_cat: str) -> str:
    """Derive a URL template from an audio manifest's verse/surah entries.

    Returns a template string with the protocol stripped (e.g.
    ``server8.mp3quran.net/afs/{surah:03d}.mp3``) or ``""`` when the
    manifest layout doesn't match a templatable pattern. The template is
    validated against a second entry to guard against false positives.

    Used by:
      - ``.github/scripts/build_reciter.py`` — inlined into shard ``_meta``
        and the manifest's per-reciter block.
      - ``inspector/services/ts_local.py`` — same template, served from
        the local-mode manifest endpoint.
    """
    entries = {k: v for k, v in manifest_data.items() if k != "_meta"}
    if not entries:
        return ""

    if audio_cat == "by_surah":
        if "1" in entries:
            url, surah_num = entries["1"], 1
        else:
            first_key = min(entries.keys(), key=int)
            url, surah_num = entries[first_key], int(first_key)

        base, _, filename = url.rpartition("/")
        if not base:
            return ""
        padded = f"{surah_num:03d}"
        if padded in filename:
            template = base + "/" + filename.replace(padded, "{surah:03d}", 1)
        else:
            s = str(surah_num)
            if s in filename:
                template = base + "/" + filename.replace(s, "{surah}", 1)
            else:
                return ""

        # Validate against another entry.
        val_key = "2" if "2" in entries else ("3" if "3" in entries else None)
        if val_key:
            expected = template.format(surah=int(val_key))
            if expected != entries[val_key]:
                return ""

    elif audio_cat == "by_ayah":
        url = entries.get("1:1")
        if not url:
            return ""
        base, _, filename = url.rpartition("/")
        if not base:
            return ""
        if "001001" in filename:
            template = base + "/" + filename.replace(
                "001001", "{surah:03d}{ayah:03d}", 1
            )
        else:
            return ""
        val = entries.get("2:1")
        if val:
            expected = template.format(surah=2, ayah=1)
            if expected != val:
                return ""
    else:
        return ""

    # Strip protocol so HF dataset viewer doesn't render as audio widget.
    for prefix in ("https://", "http://"):
        if template.startswith(prefix):
            template = template[len(prefix):]
            break
    return template
