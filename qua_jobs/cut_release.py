#!/usr/bin/env python3
"""HF Job entrypoint: cut a global GitHub release (v2 track).

Reads the inspector DB (read-only) to discover every recitation eligible for
GH releases (a current ``per_recitation_releases(track='ts')`` row), builds the
per-recitation tier
files + ``catalog.json`` + zip + content_hash, builds the dataset-level
``manifest.json`` + ``CHANGELOG.md``, computes the version, and uses the
GitHub REST API to create the release tag and upload every asset.

On success, POSTs the completion webhook with the per-recitation membership
payload; Inspector's ``services.admin.jobs.cut_release.complete()`` inserts
the ``gh_releases`` row + N ``gh_release_recitations`` rows and fires the
public ``released`` event.

The HF Job NEVER writes the inspector DB. Reads only.

Env:
  INSPECTOR_BUCKET_MOUNT    bucket mount root (default ``/data``)
  INSPECTOR_CODE_DIR        staged-code root (default: the script's repo root,
                            i.e. ``/aux/code`` in the Job); set for local sim
  RELEASE_VERSION           (optional) operator-supplied vX.Y.Z; bypasses auto-bump
  LAUNCHED_BY               (optional) hf_user_id of the operator
  JOB_ID                    HF-injected job id
  HF_TOKEN                  HF auth (for repo_config lookup)
  GH_RELEASE_TOKEN          fine-grained GH app token (scoped to releases on the public repo)
  INSPECTOR_WEBHOOK_URL     completion endpoint
  INSPECTOR_WEBHOOK_SECRET  HMAC shared secret
"""

from __future__ import annotations

import datetime
import gzip
import hashlib
import io
import json
import logging
import os
import sqlite3
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from qua_shared.letter_vocab import VOCAB_FILENAME, to_external_char, vocab_csv_bytes  # noqa: E402
from qua_shared.ts_shard_letters import iter_letters  # noqa: E402
from qua_shared.schemas import (  # noqa: E402
    FileDigest,
    LetterTimestampsDoc,
    QpcHafsDoc,
    ReleaseCatalog,
    ReleaseCatalogAudio,
    ReleaseCoverage,
    ReleaseManifest,
    ReleaseManifestRecitation,
    ReleaseRecitationCatalog,
    VerseTimestampsDoc,
    WordTimestampsDoc,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("cut_release")


SCHEMA_VERSION = 1
GH_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# Bucket + DB I/O.
# ---------------------------------------------------------------------------


def _bucket_root() -> Path:
    return Path(os.environ.get("INSPECTOR_BUCKET_MOUNT", "/data"))


def _code_root() -> Path:
    """Staged-code root. In the HF Job this is ``/aux/code`` (aligner-bucket
    mounted RO), which equals ``_REPO_ROOT`` since the script lives at
    ``<root>/qua_jobs/cut_release.py``. ``INSPECTOR_CODE_DIR`` overrides it
    for local runs / the cut-sim harness; unset → the script's own repo root,
    so a plain local invocation reads ``data/``, ``LICENSE`` etc. from the
    checkout."""
    override = os.environ.get("INSPECTOR_CODE_DIR", "").strip()
    return Path(override) if override else _REPO_ROOT


def _open_inspector_db_readonly() -> sqlite3.Connection:
    """Open the bucket's inspector.db read-only. The Inspector is the single
    writer; this reader takes no locks and is safe against concurrent writes.
    """
    db_path = _bucket_root() / "db" / "inspector.db"
    if not db_path.exists():
        raise FileNotFoundError(f"inspector DB not found at {db_path}")
    uri = f"file:{db_path}?mode=ro&immutable=0"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _eligible_recitations(conn: sqlite3.Connection) -> list[dict]:
    """Return ``[{slug, ts_version, delivery_meta, channel_meta, reciter_meta}, ...]``
    for every recitation eligible for GH release: a current
    ``per_recitation_releases(track='ts')`` row. Every channel is releasable.

    Selects both the FK slugs (``riwayah``/``style``/``channel`` — kept so
    ``catalog.json`` keeps its stable consumer schema) AND the vocab display names
    (``*_name``) used by the human-facing changelog.
    """
    rows = conn.execute("""
        SELECT
          prr.id AS prr_id,
          prr.slug AS slug,
          prr.version AS ts_version,
          prr.produced_at AS ts_produced_at,
          d.reciter_id AS reciter_id,
          d.riwayah AS riwayah,
          d.style AS style,
          d.channel AS channel,
          rw.name AS riwayah_name,
          st.name AS style_name,
          ch.name AS channel_name,
          d.audio_category AS audio_category,
          d.recording_context AS recording_context,
          d.recording_year AS recording_year,
          d.variant_label AS variant_label,
          d.chapter_count AS chapter_count,
          d.bitrate_mode AS bitrate_mode,
          d.bitrate_kbps_nominal AS bitrate_kbps_nominal,
          d.sample_rate_hz AS sample_rate_hz,
          d.channels AS channels,
          r.name_en AS name_en,
          r.name_ar AS name_ar,
          r.country AS country
        FROM per_recitation_releases prr
        JOIN deliveries d ON d.slug = prr.slug
        JOIN riwayahs rw  ON rw.slug = d.riwayah
        JOIN styles st    ON st.slug = d.style
        JOIN channels ch  ON ch.slug = d.channel
        JOIN reciters r   ON r.reciter_id = d.reciter_id
        WHERE prr.track = 'ts'
          AND prr.superseded_at IS NULL
        ORDER BY prr.slug
    """).fetchall()
    return [dict(r) for r in rows]


def _prior_release_members(conn: sqlite3.Connection) -> tuple[str | None, dict[str, dict]]:
    """Return ``(prior_version, {slug: member_row})`` for the most-recent
    non-superseded ``gh_releases``. Empty dict if there's no prior release.
    """
    rel = conn.execute(
        "SELECT id, version FROM gh_releases WHERE superseded_at IS NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not rel:
        return None, {}
    members = conn.execute(
        "SELECT * FROM gh_release_recitations WHERE release_id = ? ORDER BY slug",
        (rel["id"],),
    ).fetchall()
    return rel["version"], {m["slug"]: dict(m) for m in members}


# ---------------------------------------------------------------------------
# Tier-file projection — top-down (letter → word → verse).
# Shared per-verse positions are byte-equal across tiers (CI assertion).
# ---------------------------------------------------------------------------


def _load_canonical_verses(slug: str) -> dict[str, dict]:
    """Read every ``reciters/<slug>/timestamps/<ch>.json.gz`` segment-array shard,
    project each to the canonical verse map (completion-based occasion dedup, the
    EARLIEST completing occasion), and merge.
    """
    from qua_shared.timestamps_dedup import project_segment_shard

    ts_dir = _bucket_root() / "reciters" / slug / "timestamps"
    if not ts_dir.exists():
        return {}
    out: dict[str, dict] = {}
    for path in sorted(
        ts_dir.iterdir(),
        key=lambda p: int(p.name.split(".", 1)[0]) if p.name.split(".", 1)[0].isdigit() else 0,
    ):
        name = path.name
        if not (name.endswith(".json") or name.endswith(".json.gz")):
            continue
        raw = path.read_bytes()
        if name.endswith(".gz"):
            raw = gzip.decompress(raw)
        shard = json.loads(raw)
        out.update(project_segment_shard(shard))
    return out


def _build_tier_files(
    slug: str, verses: dict[str, dict], *, delivery_meta: dict
) -> dict[str, bytes]:
    """Build the three tier files (letter → word → verse, top-down projection).

    Returns ``{"verse_timestamps.json.gz": bytes,
               "word_timestamps.json.gz":  bytes,
               "letter_timestamps.json.gz": bytes}``.

    All times are source-relative milliseconds. Positional arrays for
    compactness. ``_meta`` describes the layout.
    """
    sorted_keys = sorted(verses.keys(), key=_verse_sort_key)

    letter_body: dict = {}
    word_body: dict = {}
    verse_body: dict = {}
    for key in sorted_keys:
        v = verses[key]
        words = v.get("words") if isinstance(v, dict) else v
        if not words:
            continue
        vs = v.get("verse_start_ms") if isinstance(v, dict) else None
        ve = v.get("verse_end_ms") if isinstance(v, dict) else None
        if vs is None or ve is None:
            vs = int(words[0][1])
            ve = max(int(w[2]) for w in words)
        verse_pos = [int(vs), int(ve)]

        word_array: list[list[int]] = []
        letter_array: list[list] = []
        for w in words:
            widx = int(w[0])
            ws = int(w[1])
            we = int(w[2])
            word_array.append([widx, ws, we])
            letters = w[3] if len(w) > 3 else []
            # Read letters by name; the accessor ignores the shard's trailing
            # ``silent`` flag (and any future slot), which the GH letter tier
            # doesn't expose.
            for lt in iter_letters(letters):
                # Map the internal 57-token alphabet to the published 42-token
                # external set (drops the maddah mark; fail-loud on unknown).
                letter_array.append([widx, to_external_char(lt.char), int(lt.start_ms), int(lt.end_ms)])

        verse_body[key] = verse_pos
        word_body[key] = [verse_pos, word_array]
        letter_body[key] = [verse_pos, word_array, letter_array]

    meta_common = {
        "schema_version": SCHEMA_VERSION,
        "slug": slug,
        "audio_category": delivery_meta.get("audio_category"),
        "verse_count": len(verse_body),
    }
    letter_doc = {
        "_meta": {
            **meta_common,
            "tier": "letter",
            "layout": "[[start,end], words, letters]; "
            "words=[[widx,start,end],...]; "
            "letters=[[widx,char,start,end],...]",
        },
        **letter_body,
    }
    word_doc = {
        "_meta": {
            **meta_common,
            "tier": "word",
            "layout": "[[start,end], words]; words=[[widx,start,end],...]",
        },
        **word_body,
    }
    verse_doc = {"_meta": {**meta_common, "tier": "verse", "layout": "[start,end]"}, **verse_body}

    VerseTimestampsDoc.model_validate(verse_doc)
    WordTimestampsDoc.model_validate(word_doc)
    LetterTimestampsDoc.model_validate(letter_doc)

    return {
        "letter_timestamps.json.gz": _gzip_deterministic(letter_doc),
        "word_timestamps.json.gz": _gzip_deterministic(word_doc),
        "verse_timestamps.json.gz": _gzip_deterministic(verse_doc),
    }


def _verse_for_validate(v: dict, segments: list) -> dict:
    """Project one canonical verse to the boundary-validator's input shape.

    ``verse_start_ms`` / ``verse_end_ms`` fall back to the word bounds when the
    verse doesn't carry them (the common projection case). ``duration_ms`` is
    derived from the SAME resolved bounds — so the duration-arithmetic check
    (``duration == end - start``) can't fire spuriously on the fallback path.
    """
    words = v.get("words") or []
    vs = v.get("verse_start_ms")
    vs = int(vs if vs is not None else (words[0][1] if words else 0))
    ve = v.get("verse_end_ms")
    ve = int(ve if ve is not None else (max(w[2] for w in words) if words else 0))
    return {
        "verse_start_ms": vs,
        "verse_end_ms": ve,
        "duration_ms": ve - vs,
        "words": [(int(w[0]), int(w[1]), int(w[2])) for w in words],
        "segments": segments,
    }


def _verse_sort_key(key: str) -> tuple[int, int]:
    parts = key.split(":")
    try:
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return 0, 0


def _gzip_deterministic(doc: dict) -> bytes:
    """Serialize JSON preserving insertion order + gzip at level 6, mtime=0."""
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(payload, compresslevel=6, mtime=0)


def _json_model_bytes(model) -> bytes:
    """Serialize a Pydantic model as deterministic compact JSON bytes."""
    body = model.model_dump(mode="json", by_alias=True)
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


# ---------------------------------------------------------------------------
# Catalog + manifest + zip per recitation.
# ---------------------------------------------------------------------------


def _audio_sources_from_manifest(
    slug: str, audio_manifest: dict | None
) -> tuple[dict[str, str], dict[str, int]]:
    """Return ``(chapter_urls, chapter_offsets_ms)`` from
    ``catalog/audio_manifest/<slug>.json``.

    ``chapter_urls`` is the NATIVE source URL per chapter — for a combined-file
    intake (one YouTube/Drive source serving several chapters) the manifest
    stores a per-chapter bucket path in ``url`` and the real source in
    ``source_url``; we surface ``source_url`` so the release points consumers at
    the original, not the internal bucket. ``chapter_offsets_ms`` is the
    chapter's start offset *inside* that source (``source_offset_ms``), included
    only when > 0 (combined files, or a single file with a trimmed lead-in).
    Mirrors ``publish_hf.publish_slug``'s per-row resolution so the two adapters
    agree on provenance + offset.
    """
    if not audio_manifest:
        return {}, {}
    chapters = audio_manifest.get("chapters")
    if isinstance(chapters, dict):
        urls: dict[str, str] = {}
        offsets: dict[str, int] = {}
        for key, chapter in sorted(chapters.items()):
            if not (key.isdigit() or ":" in key) or not isinstance(chapter, dict):
                continue
            url = chapter.get("source_url") or chapter.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            urls[key] = url.strip()
            offset = int(chapter.get("source_offset_ms") or 0)
            if offset > 0:
                offsets[key] = offset
        if urls:
            return urls, offsets

    # Legacy flat maps are kept as a defensive fallback for old fixtures.
    flat = {
        key: value.strip()
        for key, value in sorted(audio_manifest.items())
        if (key.isdigit() or ":" in key) and isinstance(value, str) and value.strip()
    }
    return flat, {}


def _build_catalog_json(
    rec: dict,
    audio_manifest: dict | None,
    verses: dict,
    *,
    missing_surahs: str = "",
    missing_verses: str = "",
) -> bytes:
    """Per-recitation catalog.json bytes (orjson-equivalent serialisation).

    ``chapter_urls`` is keyed by chapter string (``"1"``) for by_surah and by
    ``"surah:ayah"`` for by_ayah — consumers interpret based on the recitation's
    ``audio_category``. Plan §"GH release `catalog.json` schema": "fully
    populated for every chapter the recitation covers" — both shapes are
    "what the source audio actually serves" so this is the consumer-actionable
    URL set without contraction.
    """
    audio_urls, audio_offsets = _audio_sources_from_manifest(rec["slug"], audio_manifest)
    if not audio_urls:
        raise RuntimeError(f"{rec['slug']}: audio_manifest has no usable audio URLs")
    surahs = {key.split(":", 1)[0] for key in verses if not key.startswith("_")}
    coverage_ayahs = sum(1 for k in verses if not k.startswith("_"))
    catalog = ReleaseRecitationCatalog(
        schema_version=SCHEMA_VERSION,
        slug=rec["slug"],
        reciter_id=rec.get("reciter_id"),
        name_en=rec.get("name_en"),
        name_ar=rec.get("name_ar"),
        riwayah=rec.get("riwayah"),
        style=rec.get("style"),
        country=rec.get("country"),
        channel=rec.get("channel"),
        audio_category=rec.get("audio_category"),
        recording_context=rec.get("recording_context"),
        recording_year=rec.get("recording_year"),
        variant_label=rec.get("variant_label"),
        audio=ReleaseCatalogAudio(
            chapter_urls=audio_urls,
            chapter_offsets_ms=audio_offsets,
            sample_rate_hz=rec.get("sample_rate_hz"),
            channels=rec.get("channels"),
            bitrate_mode=rec.get("bitrate_mode"),
            bitrate_kbps_nominal=rec.get("bitrate_kbps_nominal"),
        ),
        coverage=ReleaseCoverage(
            surahs=len(surahs),
            ayahs=coverage_ayahs,
            missing_surahs=missing_surahs,
            missing_verses=missing_verses,
        ),
    )
    return _json_model_bytes(catalog)


def _pack_recitation_zip(slug: str, files: dict[str, bytes]) -> bytes:
    """Pack the recitation's files (tier files + ``catalog.json``) into a
    deterministic zip.

    .gz entries: store (already compressed). .json/.md/.py: deflate level 9.
    mtime=0 on every entry header for byte stability.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", allowZip64=True) as zf:
        for name in sorted(files):
            data = files[name]
            method = zipfile.ZIP_STORED if name.endswith(".gz") else zipfile.ZIP_DEFLATED
            info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = method
            # Force deterministic external_attr (file mode 644) so the zip is
            # byte-stable across runs.
            info.external_attr = 0o644 << 16
            if method == zipfile.ZIP_DEFLATED:
                zf.writestr(info, data, compress_type=method, compresslevel=9)
            else:
                zf.writestr(info, data, compress_type=method)
    return buf.getvalue()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Dataset-level manifest + CHANGELOG.md + versioning.
# ---------------------------------------------------------------------------


def _classify_change_kind(rec: dict, prior_members: dict[str, dict], content_hash: str) -> str:
    """``added`` if no prior; ``unchanged`` if content_hash matches; else ``refresh``."""
    prior = prior_members.get(rec["slug"])
    if prior is None:
        return "added"
    if prior.get("content_hash") == content_hash:
        return "unchanged"
    return "refresh"


def _compute_version(
    prior_version: str | None, members: list[dict], static_refs_changed: bool, override: str | None
) -> str:
    """Auto-bump per plan §Versioning. Override always wins (operator declares MAJOR).
    No-op (every member 'unchanged' AND static refs unchanged) raises.
    """
    if override:
        return override
    if not prior_version:
        # First release → MINOR over v0.0.0 when there's any content.
        return "v0.1.0" if members else "v0.0.0"
    parts = prior_version.lstrip("v").split(".")
    try:
        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    except (ValueError, IndexError) as e:
        raise RuntimeError(f"unparseable prior version {prior_version!r}") from e
    has_added = any(m["change_kind"] == "added" for m in members)
    has_refresh = any(m["change_kind"] == "refresh" for m in members)
    if has_added:
        return f"v{major}.{minor + 1}.0"
    if has_refresh or static_refs_changed:
        return f"v{major}.{minor}.{patch + 1}"
    raise RuntimeError("nothing changed since last release — set RELEASE_VERSION to force-cut")


def _build_dataset_manifest(
    version: str,
    prior_version: str | None,
    members: list[dict],
    static_refs: dict,
    owner: str,
    repo: str,
    created_at: str,
) -> bytes:
    """Dataset-level ``manifest.json``."""
    recitations: dict[str, ReleaseManifestRecitation] = {}
    for m in members:
        slug = m["slug"]
        recitations[slug] = ReleaseManifestRecitation(
            zip=f"{slug}.zip",
            zip_url=_release_asset_url(owner, repo, version, f"{slug}.zip"),
            sha256=m["zip_sha256"],
            bytes=m["zip_bytes"],
            coverage_ayahs=m["coverage_ayahs"],
            content_hash=m["content_hash"],
            change_kind=m["change_kind"],
            ts_version=m["ts_version"],
        )
    manifest = ReleaseManifest(
        schema_version=SCHEMA_VERSION,
        release_version=version,
        created_at=created_at,
        previous_version=prior_version,
        recitation_count=len(members),
        static_refs={k: FileDigest.model_validate(v) for k, v in static_refs.items()},
        recitations=recitations,
        license="CC-BY-4.0",
    )
    return _json_model_bytes(manifest)


def _release_asset_url(owner: str, repo: str, version: str, name: str) -> str:
    return f"https://github.com/{owner}/{repo}/releases/download/{version}/{name}"


def _build_changelog(
    version: str,
    prior_version: str | None,
    members: list[dict],
    static_refs_changed_keys: list[str],
    owner: str,
    repo: str,
    created_at_date: str,
    hf_dataset: str,
) -> bytes:
    """The release body — delegates to the shared renderer so the modal preview and
    the shipped release stay byte-identical (modulo coverage, which the preview shows
    in surahs and the cut shows in exact ayahs). Maps the cut-side rich member dict
    onto the renderer's display-name contract."""
    from qua_shared.release_changelog import render_changelog

    render_members = [
        {
            "name_en": m.get("name_en"),
            "name_ar": m.get("name_ar"),
            "riwayah": m.get("riwayah_name") or m.get("riwayah"),
            "style": m.get("style_name") or m.get("style"),
            "channel": m.get("channel_name") or m.get("channel"),
            "change_kind": m.get("change_kind"),
            "coverage_surahs": m.get("coverage_surahs"),
            "coverage_ayahs": m.get("coverage_ayahs"),
            "missing_surahs": m.get("missing_surahs"),
            "missing_verses": m.get("missing_verses"),
        }
        for m in members
    ]

    md = render_changelog(
        version=version,
        previous_version=prior_version,
        release_date=created_at_date,
        members=render_members,
        static_refs_changed_keys=tuple(static_refs_changed_keys),
        owner=owner,
        repo=repo,
        hf_dataset=hf_dataset,
    )
    return md.encode("utf-8")


# ---------------------------------------------------------------------------
# GitHub REST API (stdlib only).
# ---------------------------------------------------------------------------


def _gh_request(
    method: str,
    path: str,
    token: str,
    *,
    json_body: dict | None = None,
    raw_body: bytes | None = None,
    content_type: str | None = None,
    accept: str = "application/vnd.github+json",
) -> dict:
    """One GH REST call. Body is either JSON (json_body) or raw (raw_body).
    Returns the parsed JSON response on 2xx; raises with body text on failure.
    """
    url = path if path.startswith("http") else GH_API + path
    headers = {
        "Accept": accept,
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "quranic-universal-audio-cut-release",
    }
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif raw_body is not None:
        data = raw_body
        if content_type:
            headers["Content-Type"] = content_type
    else:
        data = None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            body = resp.read()
            if not body:
                return {}
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"_raw": body.decode("utf-8", "replace")}
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")
        # On a 403, GitHub returns the permission the token lacks here — surface
        # it so an under-scoped GH_RELEASE_TOKEN is self-diagnosing instead of an
        # opaque "Resource not accessible by personal access token".
        needed = e.headers.get("X-Accepted-GitHub-Permissions")
        hint = f" [token needs GitHub permissions: {needed}]" if needed else ""
        raise RuntimeError(f"GH API {method} {url} → {e.code}: {msg[:500]}{hint}") from e


def _gh_create_release(owner: str, repo: str, version: str, body: str, token: str) -> dict:
    """Create a draft-less release tag. Returns the release dict (with upload_url)."""
    return _gh_request(
        "POST",
        f"/repos/{owner}/{repo}/releases",
        token,
        json_body={
            "tag_name": version,
            "name": version,
            "body": body,
            "draft": False,
            "prerelease": False,
        },
    )


def _gh_upload_asset(
    upload_url_template: str, name: str, data: bytes, token: str, content_type: str
) -> dict:
    """Upload one asset. upload_url_template ends with ``{?name,label}``."""
    base = upload_url_template.split("{", 1)[0]
    from urllib.parse import quote

    url = f"{base}?name={quote(name)}"
    return _gh_request(
        "POST",
        url,
        token,
        raw_body=data,
        content_type=content_type,
        accept="application/vnd.github+json",
    )


# ---------------------------------------------------------------------------
# Completion callback.
# ---------------------------------------------------------------------------


def _post_webhook(
    *,
    version: str,
    job_id: str,
    external_uri: str,
    members: list[dict],
    launched_by: str | None,
    status: str = "succeeded",
    validation_summary: dict | None = None,
) -> bool:
    url = os.environ.get("INSPECTOR_WEBHOOK_URL", "").strip()
    secret = os.environ.get("INSPECTOR_WEBHOOK_SECRET", "").strip()
    if not url or not secret:
        log.info("webhook URL/secret unset — skipping callback (poll fallback applies)")
        return False
    body = {
        "kind": "cut_release",
        "job_id": job_id,
        "status": status,
        "version": version,
        "external_uri": external_uri,
        "launched_by": launched_by,
        "members": members,
    }
    if validation_summary:
        body["validation_summary"] = validation_summary
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "X-Inspector-Job-Secret": secret},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            log.info("webhook %s → %s", url, resp.status)
            return 200 <= resp.status < 300
    except Exception as exc:
        log.warning("webhook POST failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# qpc_hafs byte resolution + static refs hash.
# ---------------------------------------------------------------------------

# Bucket-relative location of the canonical gzipped qpc_hafs (Xet-backed — no
# LFS pointer problem, unlike the image-staged ``data/qpc_hafs.json.gz``).
QPC_BUCKET_REL = "reference/qpc_hafs.json.gz"


def _gunzip_or_none(raw: bytes) -> bytes | None:
    """Decompress gzip bytes, or ``None`` if ``raw`` isn't valid gzip (e.g. an
    LFS pointer ``version https://...`` masquerading as the file)."""
    try:
        return gzip.decompress(raw)
    except (OSError, gzip.BadGzipFile):
        return None


def _load_qpc_bytes(refs_dir: Path) -> bytes | None:
    """Decompressed ``qpc_hafs.json`` bytes, resolved across runtimes.

    HF auto-LFS-promotes ``*.gz`` **by extension**, so the job image's staged
    ``data/qpc_hafs.json.gz`` is a git-lfs pointer (``version https://...``),
    not gzip — ``gzip.decompress`` on it raises ``BadGzipFile``. Resolve the
    real bytes: local uncompressed (dev checkout) → local valid gzip (CI
    staging with real bytes) → bucket ``reference/qpc_hafs.json.gz`` (the job
    case, where only the Xet-backed bucket carries real bytes). Returns
    ``None`` if unavailable everywhere. Mirrors the Inspector's
    ``services.storage.static_refs.load_qpc_bytes``.
    """
    plain = refs_dir / "qpc_hafs.json"
    if plain.exists():
        return plain.read_bytes()
    gz = refs_dir / "qpc_hafs.json.gz"
    if gz.exists():
        dec = _gunzip_or_none(gz.read_bytes())
        if dec is not None:
            return dec
        log.warning("staged %s is not gzip (LFS pointer?) — falling back to bucket", gz)
    bucket_gz = _bucket_root() / QPC_BUCKET_REL
    if bucket_gz.exists():
        dec = _gunzip_or_none(bucket_gz.read_bytes())
        if dec is not None:
            return dec
        log.error("bucket %s is not valid gzip", bucket_gz)
    return None


def _validate_qpc_bytes(qpc_bytes: bytes) -> None:
    """Fail before upload if qpc_hafs.json is not real JSON in the expected shape."""
    try:
        QpcHafsDoc.model_validate(json.loads(qpc_bytes))
    except Exception as exc:
        raise RuntimeError("qpc_hafs.json is not valid QPC JSON") from exc


def _hash_static_refs(refs_dir: Path, qpc_bytes: bytes | None) -> dict[str, dict]:
    """SHA-256 + byte size for each static ref. ``qpc_bytes`` is the already
    resolved, *decompressed* qpc_hafs.json (see ``_load_qpc_bytes``); hashing
    the decompressed bytes keeps the manifest hash stable across the
    gzip-vs-plain transport choice and matches what a consumer who downloads
    the .gz and decompresses sees.
    """
    out: dict[str, dict] = {}
    plain = refs_dir / "surah_info.json"
    if plain.exists():
        body = plain.read_bytes()
        out["surah_info.json"] = {"sha256": _sha256_hex(body), "bytes": len(body)}
    if qpc_bytes is not None:
        out["qpc_hafs.json"] = {"sha256": _sha256_hex(qpc_bytes), "bytes": len(qpc_bytes)}
    return out


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------


def _repo_owner_name() -> tuple[str, str, str]:
    """Resolve (owner, repo, hf_dataset_id) from config_loader."""
    from qua_shared.config_loader import repo_config

    cfg = repo_config()
    return cfg["repo_owner"], cfg["repo_name"], cfg["hf_dataset"]


def _preflight() -> int:
    """Verify env + bucket + staged code dir. Returns 0 on go, non-zero exit
    code on first failure (each code maps to one cause)."""
    if not os.environ.get("HF_TOKEN", "").strip():
        log.error("HF_TOKEN secret is required")
        return 10
    if not os.environ.get("GH_RELEASE_TOKEN", "").strip():
        log.error("GH_RELEASE_TOKEN secret is required")
        return 2
    bucket = _bucket_root()
    if not bucket.exists():
        log.error("bucket mount missing at %s", bucket)
        return 12
    db_path = bucket / "db" / "inspector.db"
    if not db_path.exists():
        log.error("inspector.db missing at %s", db_path)
        return 13
    code_dir = _code_root()
    for rel in (
        "data/surah_info.json",
        ".github/config/repo.yml",
        "docs/templates/release_body.md",
        "LICENSE",
        "qua_jobs/shard.py",
        "qua_jobs/check_updates.py",
        "qua_jobs/download_audio.py",
    ):
        if not (code_dir / rel).exists():
            log.error("staged file missing: %s", code_dir / rel)
            return 14
    if not (
        (code_dir / "data/qpc_hafs.json.gz").exists() or (code_dir / "data/qpc_hafs.json").exists()
    ):
        log.error("staged file missing: %s/data/qpc_hafs.json[.gz]", code_dir)
        return 14
    return 0


def main() -> int:
    job_id = os.environ.get("JOB_ID", "").strip() or "unknown"
    launched_by = os.environ.get("LAUNCHED_BY") or None
    version_override = os.environ.get("RELEASE_VERSION", "").strip() or None

    rc = _preflight()
    if rc != 0:
        return rc
    gh_token = os.environ.get("GH_RELEASE_TOKEN", "").strip()

    owner, repo, hf_dataset = _repo_owner_name()
    log.info("cut_release: owner=%s repo=%s job=%s", owner, repo, job_id)

    # 1. Discover eligible recitations + prior release members.
    with _open_inspector_db_readonly() as conn:
        eligible = _eligible_recitations(conn)
        prior_version, prior_members = _prior_release_members(conn)
    log.info(
        "found %d eligible recitations; prior release: %s", len(eligible), prior_version or "<none>"
    )

    if not eligible:
        log.error("no eligible recitations — aborting")
        return 3

    # 2. Build per-recitation artifacts and accumulate member rows.
    refs_dir = _code_root() / "data"
    surah_info = json.loads((refs_dir / "surah_info.json").read_bytes())
    from qua_shared.coverage import missing_coverage, verse_counts_from_surah_info
    from qua_shared.surah_words import word_counts_from_surah_info
    from qua_shared.timestamps_dedup import select_complete_verses

    word_counts = word_counts_from_surah_info(surah_info)
    surah_verse_counts = verse_counts_from_surah_info(surah_info)

    # qpc_hafs is a consumer-facing release asset. The staged image .gz is an
    # LFS pointer (HF auto-LFS by extension), so resolve the real decompressed
    # bytes via the bucket fallback and abort early if unavailable everywhere —
    # never ship a release missing qpc_hafs.json / a stale manifest hash.
    qpc_bytes = _load_qpc_bytes(refs_dir)
    if qpc_bytes is None:
        log.error(
            "qpc_hafs.json unavailable (image .gz is an LFS pointer and "
            "bucket %s missing/corrupt) — cannot cut release",
            QPC_BUCKET_REL,
        )
        return 14
    try:
        _validate_qpc_bytes(qpc_bytes)
    except RuntimeError as exc:
        log.error("%s", exc)
        return 14
    from qua_shared.dataset_validation import (
        fatal_violations,
        validate_dataset,
    )

    now = datetime.datetime.now(datetime.UTC)
    created_at_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    created_at_date = now.strftime("%d-%m-%Y")

    members: list[dict] = []
    validation_summary_total = {"violation_count": 0, "by_kind": {}, "violations": []}
    zip_bytes_by_slug: dict[str, bytes] = {}

    for rec in eligible:
        slug = rec["slug"]
        log.info("  building %s...", slug)
        verses = _load_canonical_verses(slug)
        if not verses:
            log.warning("  %s: no timestamps shards — skipping", slug)
            continue

        # Gate incomplete verses: any verse missing a reference word index (never
        # recited) is dropped from the release — absent from the tier JSON and
        # excluded from coverage_ayahs. The editor/TS tab still shows them.
        verses, dropped_incomplete = select_complete_verses(verses, word_counts)
        if dropped_incomplete:
            log.info(
                "  %s: gated %d incomplete verse(s) (missing words): %s",
                slug,
                len(dropped_incomplete),
                dropped_incomplete,
            )

        # Load detailed.json so the intra-segment gapless check has segments
        # to validate (plan §"Boundary enforcement" — the four checks include
        # intra-segment gapless, which needs segment word-ranges).
        detailed_segments = _segments_per_verse_from_detailed(slug)

        # Boundary validate (source-relative ms — verses dict already in that frame).
        for_validate = {
            k: _verse_for_validate(v, detailed_segments.get(k, []))
            for k, v in verses.items()
            if not k.startswith("_") and isinstance(v, dict)
        }
        rec_summary = validate_dataset(for_validate, surah_info=surah_info)
        fatal = fatal_violations(rec_summary["violations"])
        if fatal:
            log.error("  %s: %d fatal boundary violations — aborting cut", slug, len(fatal))
            for v in fatal[:5]:
                log.error("    %s", v)
            _post_webhook(
                version=version_override or "",
                job_id=job_id,
                external_uri="",
                members=[],
                launched_by=launched_by,
                status="failed",
                validation_summary={"slug": slug, "summary": rec_summary},
            )
            return 4
        validation_summary_total["violation_count"] += rec_summary["violation_count"]
        for k, c in rec_summary.get("by_kind", {}).items():
            validation_summary_total["by_kind"][k] = (
                validation_summary_total["by_kind"].get(k, 0) + c
            )

        # Tier files.
        tier_files = _build_tier_files(slug, verses, delivery_meta=rec)

        # catalog.json.
        audio_manifest_path = _bucket_root() / "catalog" / "audio_manifest" / f"{slug}.json"
        audio_manifest = None
        if audio_manifest_path.exists():
            try:
                audio_manifest = json.loads(audio_manifest_path.read_bytes())
            except (json.JSONDecodeError, OSError):
                audio_manifest = None
        # Concise coverage-gap notation (vs the full mushaf) for catalog.json +
        # the changelog Missing column — whole missing surahs vs within-surah
        # verse gaps, split so even a partial recitation stays short.
        present_refs = {
            (int(k.split(":")[0]), int(k.split(":")[1]))
            for k in verses
            if not k.startswith("_")
        }
        missing_surahs, missing_verses = missing_coverage(present_refs, surah_verse_counts)
        catalog_bytes = _build_catalog_json(
            rec,
            audio_manifest,
            verses,
            missing_surahs=missing_surahs,
            missing_verses=missing_verses,
        )

        # content_hash — over letter tier + catalog bytes.
        content_hash = _sha256_hex(tier_files["letter_timestamps.json.gz"] + catalog_bytes)

        files = dict(tier_files)
        files["catalog.json"] = catalog_bytes

        coverage_ayahs = sum(1 for k in verses if not k.startswith("_"))
        change_kind = _classify_change_kind(rec, prior_members, content_hash)

        # Build the catalog_snapshot (frozen at cut time, what the row stores).
        catalog_snapshot = json.loads(catalog_bytes.decode("utf-8"))

        members.append(
            {
                "slug": slug,
                "name_en": rec.get("name_en"),
                "name_ar": rec.get("name_ar"),
                "riwayah": rec.get("riwayah"),
                "style": rec.get("style"),
                "channel": rec.get("channel"),
                "riwayah_name": rec.get("riwayah_name"),
                "style_name": rec.get("style_name"),
                "channel_name": rec.get("channel_name"),
                "ts_version": str(rec["ts_version"]),
                "coverage_ayahs": coverage_ayahs,
                "coverage_surahs": rec.get("chapter_count"),
                "missing_surahs": missing_surahs,
                "missing_verses": missing_verses,
                "content_hash": content_hash,
                "change_kind": change_kind,
                "catalog_snapshot": catalog_snapshot,
                "_files": files,
                "_zip_bytes": None,  # filled after version is known
                "zip_sha256": "",
                "zip_bytes": 0,
            }
        )

    if not members:
        log.error("no members built — aborting")
        return 5

    # 3. Static refs hashes.
    prior_static = {}
    # Pull prior static_refs from prior dataset manifest. Simpler approach:
    # compare hashes against the live HEAD on GH releases. Best-effort.
    static_refs = _hash_static_refs(refs_dir, qpc_bytes)
    static_refs_changed_keys: list[str] = []
    if prior_version:
        try:
            prior_manifest_url = _release_asset_url(owner, repo, prior_version, "manifest.json")
            prior_manifest = _fetch_url_json(prior_manifest_url)
            prior_static = (prior_manifest or {}).get("static_refs", {}) or {}
        except Exception as exc:
            log.warning("could not fetch prior manifest: %s", exc)
    for name, meta in static_refs.items():
        prior_meta = prior_static.get(name) or {}
        if prior_meta.get("sha256") != meta["sha256"]:
            static_refs_changed_keys.append(name)

    # 4. Compute version.
    try:
        version = _compute_version(
            prior_version, members, bool(static_refs_changed_keys), version_override
        )
    except RuntimeError as exc:
        log.error("version compute: %s", exc)
        _post_webhook(
            version="",
            job_id=job_id,
            external_uri="",
            members=[],
            launched_by=launched_by,
            status="failed",
        )
        return 6
    log.info("computed version: %s", version)

    # 5. Pack each recitation's zip (tier files + catalog.json — the zip
    # content is version-independent, so a single pass suffices).
    for m in members:
        zip_data = _pack_recitation_zip(m["slug"], m["_files"])
        m["_zip_bytes"] = zip_data
        m["zip_sha256"] = _sha256_hex(zip_data)
        m["zip_bytes"] = len(zip_data)
        zip_bytes_by_slug[m["slug"]] = zip_data

    # 6. Dataset-level manifest + CHANGELOG.
    dataset_manifest = _build_dataset_manifest(
        version,
        prior_version,
        members,
        {k: v for k, v in static_refs.items()},
        owner,
        repo,
        created_at_iso,
    )
    changelog_md = _build_changelog(
        version,
        prior_version,
        members,
        static_refs_changed_keys,
        owner,
        repo,
        created_at_date,
        hf_dataset,
    )

    # 7. Read static refs + license + shard.py for upload. qpc_hafs lives
    # gzipped on the bucket (HF Space LFS workaround) but the GH release asset
    # is the consumer-facing decompressed JSON.
    license_path = _code_root() / "LICENSE"
    license_bytes = license_path.read_bytes() if license_path.exists() else b""
    shard_py = (_code_root() / "qua_jobs" / "shard.py").read_bytes()
    check_updates_py = (_code_root() / "qua_jobs" / "check_updates.py").read_bytes()
    download_audio_py = (_code_root() / "qua_jobs" / "download_audio.py").read_bytes()
    static_files: dict[str, bytes] = {}
    si_path = refs_dir / "surah_info.json"
    if si_path.exists():
        static_files["surah_info.json"] = si_path.read_bytes()
    # qpc_bytes was resolved (and validated non-None) at the top of main().
    static_files["qpc_hafs.json"] = qpc_bytes

    # 8. Create the GH release + upload all assets.
    log.info("creating GH release %s on %s/%s ...", version, owner, repo)
    rel = _gh_create_release(owner, repo, version, changelog_md.decode("utf-8"), token=gh_token)
    upload_url = rel["upload_url"]
    release_html_url = rel.get("html_url", "")

    # Upload order: small assets first, then zips.
    uploads: list[tuple[str, bytes, str]] = []
    uploads.append(("manifest.json", dataset_manifest, "application/json"))
    uploads.append(("CHANGELOG.md", changelog_md, "text/markdown"))
    if license_bytes:
        uploads.append(("LICENSE", license_bytes, "text/plain"))
    catalog_all = _build_dataset_level_catalog(members)
    uploads.append(("catalog.json", catalog_all, "application/json"))
    uploads.append(("shard.py", shard_py, "text/x-python"))
    uploads.append(("check_updates.py", check_updates_py, "text/x-python"))
    uploads.append(("download_audio.py", download_audio_py, "text/x-python"))
    # Letter-tier character vocabulary (the 42-token external alphabet that the
    # letter_timestamps.json.gz `char` field draws from). Generated from the
    # canonical mapping module so it can never drift from the emitted data.
    uploads.append((VOCAB_FILENAME, vocab_csv_bytes(), "text/csv"))
    for name, body in static_files.items():
        uploads.append((name, body, "application/json"))
    for m in members:
        uploads.append((f"{m['slug']}.zip", m["_zip_bytes"], "application/zip"))

    for name, data, ctype in uploads:
        log.info("  upload %s (%d bytes)...", name, len(data))
        _gh_upload_asset(upload_url, name, data, gh_token, ctype)

    # 9. Build the members payload for the webhook (drop heavy fields).
    webhook_members = [
        {
            "slug": m["slug"],
            "catalog_snapshot": m["catalog_snapshot"],
            "zip_sha256": m["zip_sha256"],
            "zip_bytes": m["zip_bytes"],
            "coverage_ayahs": m["coverage_ayahs"],
            "content_hash": m["content_hash"],
            "ts_version": m["ts_version"],
            "change_kind": m["change_kind"],
        }
        for m in members
    ]

    _post_webhook(
        version=version,
        job_id=job_id,
        external_uri=release_html_url,
        members=webhook_members,
        launched_by=launched_by,
        validation_summary={
            "violation_count": validation_summary_total["violation_count"],
            "by_kind": validation_summary_total["by_kind"],
        },
    )

    log.info("cut_release: done version=%s recitations=%d", version, len(members))
    return 0


def _build_dataset_level_catalog(members: list[dict]) -> bytes:
    """Dataset-level ``catalog.json`` — array of every recitation's catalog row."""
    catalog = ReleaseCatalog(
        schema_version=SCHEMA_VERSION,
        recitations=[
            ReleaseRecitationCatalog.model_validate(m["catalog_snapshot"]) for m in members
        ],
    )
    return _json_model_bytes(catalog)


def _fetch_url_json(url: str) -> dict | None:
    """Best-effort fetch of a public URL as JSON."""
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        # Legitimate when there's no prior release (first cut) — but a real
        # network/JSON error should be loud enough to investigate later.
        log.warning("could not fetch %s: %s", url, exc)
        return None


def _segments_per_verse_from_detailed(slug: str) -> dict[str, list]:
    """Return ``{"surah:ayah": [(word_from, word_to, time_start, time_end), ...]}``
    extracted from the slug's ``detailed.json``.

    Used to feed the boundary validator's intra-segment gapless check at cut
    time. Returns an empty dict if detailed.json is missing/malformed —
    publish_hf already enforced the invariants upstream and we don't want a
    missing detailed.json to block the cut.
    """
    path = _bucket_root() / "reciters" / slug / "detailed.json"
    if not path.exists():
        log.warning("  %s: detailed.json missing — intra-segment check degraded", slug)
        return {}
    try:
        doc = json.loads(path.read_bytes())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("  %s: detailed.json unparseable (%s)", slug, exc)
        return {}
    out: dict[str, list] = {}
    for entry in doc.get("entries", []):
        ref = entry.get("ref")
        if not ref:
            continue
        # by_ayah → ref is "surah:ayah"; by_surah → ref is chapter number.
        # Fan-out via segments' matched_ref to align with the timestamps shape.
        for seg in entry.get("segments", []) or []:
            mref = seg.get("matched_ref", "")
            if not mref:
                continue
            sp = mref.split("-", 1)[0].split(":")
            ep = mref.split("-", 1)[1].split(":") if "-" in mref else sp
            try:
                s_surah = int(sp[0])
                s_ayah = int(sp[1])
                e_ayah = int(ep[1])
            except (ValueError, IndexError):
                continue
            w_from = seg.get("word_from", seg.get("start_word", 1))
            w_to = seg.get("word_to", seg.get("end_word", w_from))
            t_start = int(seg.get("time_start", 0))
            t_end = int(seg.get("time_end", 0))
            for a in range(s_ayah, e_ayah + 1):
                vref = f"{s_surah}:{a}"
                out.setdefault(vref, []).append((int(w_from), int(w_to), t_start, t_end))
    return out


if __name__ == "__main__":
    sys.exit(main())
