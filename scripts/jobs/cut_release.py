#!/usr/bin/env python3
"""HF Job entrypoint: cut a global GitHub release (v2 track).

Reads the inspector DB (read-only) to discover every recitation eligible for
GH releases (``channels.gh_release_eligible = 1`` + current
``per_recitation_releases(track='ts')`` row), builds the per-recitation tier
files + catalog + manifest + zip + content_hash, builds the dataset-level
``manifest.json`` + ``CHANGELOG.md``, computes the version, and uses the
GitHub REST API to create the release tag and upload every asset.

On success, POSTs the completion webhook with the per-recitation membership
payload; Inspector's ``services.admin.jobs.cut_release.complete()`` inserts
the ``gh_releases`` row + N ``gh_release_recitations`` rows and fires the
public ``released`` event.

The HF Job NEVER writes the inspector DB. Reads only.

Env:
  INSPECTOR_BUCKET_MOUNT    bucket mount root (default ``/data``)
  RELEASE_VERSION           (optional) operator-supplied vX.Y.Z; bypasses auto-bump
  OPERATOR_NOTE             (optional) global note rendered into CHANGELOG.md
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

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("cut_release")


SCHEMA_VERSION = 1
GH_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# Bucket + DB I/O.
# ---------------------------------------------------------------------------

def _bucket_root() -> Path:
    return Path(os.environ.get("INSPECTOR_BUCKET_MOUNT", "/data"))


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
    for every recitation eligible for GH release: channel ``gh_release_eligible=1``
    AND a current ``per_recitation_releases(track='ts')`` row.
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
          d.audio_category AS audio_category,
          d.recording_context AS recording_context,
          d.recording_year AS recording_year,
          d.variant_label AS variant_label,
          d.bitrate_mode AS bitrate_mode,
          d.bitrate_kbps_nominal AS bitrate_kbps_nominal,
          d.sample_rate_hz AS sample_rate_hz,
          d.channels AS channels,
          r.name_en AS name_en,
          r.name_ar AS name_ar,
          r.country AS country
        FROM per_recitation_releases prr
        JOIN deliveries d ON d.slug = prr.slug
        JOIN channels c   ON c.slug = d.channel
        JOIN reciters r   ON r.reciter_id = d.reciter_id
        WHERE prr.track = 'ts'
          AND prr.superseded_at IS NULL
          AND c.gh_release_eligible = 1
        ORDER BY prr.slug
    """).fetchall()
    return [dict(r) for r in rows]


def _prior_release_members(conn: sqlite3.Connection) -> tuple[str | None, dict[str, dict]]:
    """Return ``(prior_version, {slug: member_row})`` for the most-recent
    non-superseded ``gh_releases``. Empty dict if there's no prior release.
    """
    rel = conn.execute(
        "SELECT id, version FROM gh_releases "
        "WHERE superseded_at IS NULL ORDER BY id DESC LIMIT 1"
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
    """Read every ``reciters/<slug>/timestamps/<ch>.json.gz`` shard, project
    to canonical verse map, merge. Same as publish_hf — kept inline here to
    avoid a cross-script import (HF Job container has /aux/code/scripts/lib
    on PYTHONPATH but a stable import is cheaper than a relative one).
    """
    from scripts.lib.timestamps_dedup import project_chapter_shard

    ts_dir = _bucket_root() / "reciters" / slug / "timestamps"
    if not ts_dir.exists():
        return {}
    out: dict[str, dict] = {}
    for path in sorted(ts_dir.iterdir(),
                       key=lambda p: int(p.name.split(".", 1)[0])
                       if p.name.split(".", 1)[0].isdigit() else 0):
        name = path.name
        if not (name.endswith(".json") or name.endswith(".json.gz")):
            continue
        raw = path.read_bytes()
        if name.endswith(".gz"):
            raw = gzip.decompress(raw)
        shard = json.loads(raw)
        canonical = project_chapter_shard(shard, full=False)
        for k, v in canonical.items():
            if k == "_meta":
                continue
            out[k] = v
    return out


def _build_tier_files(slug: str, verses: dict[str, dict], *,
                      delivery_meta: dict) -> dict[str, bytes]:
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
            for ch, ls, le in letters:
                letter_array.append([widx, ch, int(ls), int(le)])

        verse_body[key] = verse_pos
        word_body[key] = [verse_pos, word_array]
        letter_body[key] = [verse_pos, word_array, letter_array]

    meta_common = {
        "schema_version": SCHEMA_VERSION,
        "slug": slug,
        "audio_category": delivery_meta.get("audio_category"),
        "verse_count": len(verse_body),
    }
    letter_doc = {"_meta": {**meta_common, "tier": "letter",
                            "layout": "[[start,end], words, letters]; "
                                      "words=[[widx,start,end],...]; "
                                      "letters=[[widx,char,start,end],...]"},
                  **letter_body}
    word_doc = {"_meta": {**meta_common, "tier": "word",
                          "layout": "[[start,end], words]; "
                                    "words=[[widx,start,end],...]"},
                **word_body}
    verse_doc = {"_meta": {**meta_common, "tier": "verse",
                           "layout": "[start,end]"},
                 **verse_body}

    return {
        "letter_timestamps.json.gz": _gzip_deterministic(letter_doc),
        "word_timestamps.json.gz":   _gzip_deterministic(word_doc),
        "verse_timestamps.json.gz":  _gzip_deterministic(verse_doc),
    }


def _verse_sort_key(key: str) -> tuple[int, int]:
    parts = key.split(":")
    try:
        return int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return 0, 0


def _gzip_deterministic(doc: dict) -> bytes:
    """Serialize JSON with sorted keys + gzip at level 6, mtime=0."""
    payload = json.dumps(doc, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return gzip.compress(payload, compresslevel=6, mtime=0)


# ---------------------------------------------------------------------------
# Catalog + manifest + zip per recitation.
# ---------------------------------------------------------------------------

def _build_catalog_json(rec: dict, audio_manifest: dict | None,
                        verses: dict) -> bytes:
    """Per-recitation catalog.json bytes (orjson-equivalent serialisation).

    ``chapter_urls`` is keyed by chapter string (``"1"``) for by_surah and by
    ``"surah:ayah"`` for by_ayah — consumers interpret based on the recitation's
    ``audio_category``. Plan §"GH release `catalog.json` schema": "fully
    populated for every chapter the recitation covers" — both shapes are
    "what the source audio actually serves" so this is the consumer-actionable
    URL set without contraction.
    """
    audio_urls: dict[str, str] = {}
    if audio_manifest:
        for k, v in audio_manifest.items():
            if k == "_meta" or not isinstance(v, str):
                continue
            audio_urls[k] = v
    surahs = {key.split(":", 1)[0] for key in verses if not key.startswith("_")}
    coverage_ayahs = sum(1 for k in verses if not k.startswith("_"))
    catalog = {
        "schema_version": SCHEMA_VERSION,
        "slug": rec["slug"],
        "reciter_id": rec.get("reciter_id"),
        "name_en": rec.get("name_en"),
        "name_ar": rec.get("name_ar"),
        "riwayah": rec.get("riwayah"),
        "style": rec.get("style"),
        "country": rec.get("country"),
        "channel": rec.get("channel"),
        "audio_category": rec.get("audio_category"),
        "recording_context": rec.get("recording_context"),
        "recording_year": rec.get("recording_year"),
        "variant_label": rec.get("variant_label"),
        "audio": {
            "chapter_urls": audio_urls,
            "sample_rate_hz": rec.get("sample_rate_hz"),
            "channels": rec.get("channels"),
            "bitrate_mode": rec.get("bitrate_mode"),
            "bitrate_kbps_nominal": rec.get("bitrate_kbps_nominal"),
        },
        "coverage": {"surahs": len(surahs), "ayahs": coverage_ayahs},
    }
    return json.dumps(catalog, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _build_per_recitation_manifest(slug: str, version: str,
                                   files: dict[str, bytes],
                                   created_at: str) -> bytes:
    """``manifest.json`` inside each ``<slug>.zip``."""
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "release_version": version,
        "slug": slug,
        "created_at": created_at,
        "files": {
            name: {"sha256": _sha256_hex(body), "bytes": len(body)}
            for name, body in sorted(files.items())
        },
    }
    return json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _pack_recitation_zip(slug: str, files: dict[str, bytes]) -> bytes:
    """Pack the recitation's files into a deterministic zip.

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

def _classify_change_kind(rec: dict, prior_members: dict[str, dict],
                          content_hash: str) -> str:
    """``added`` if no prior; ``unchanged`` if content_hash matches; else ``refresh``."""
    prior = prior_members.get(rec["slug"])
    if prior is None:
        return "added"
    if prior.get("content_hash") == content_hash:
        return "unchanged"
    return "refresh"


def _compute_version(prior_version: str | None, members: list[dict],
                     static_refs_changed: bool,
                     override: str | None) -> str:
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
    except (ValueError, IndexError):
        raise RuntimeError(f"unparseable prior version {prior_version!r}")
    has_added = any(m["change_kind"] == "added" for m in members)
    has_refresh = any(m["change_kind"] == "refresh" for m in members)
    if has_added:
        return f"v{major}.{minor + 1}.0"
    if has_refresh or static_refs_changed:
        return f"v{major}.{minor}.{patch + 1}"
    raise RuntimeError(
        "nothing changed since last release — set RELEASE_VERSION to force-cut"
    )


def _build_dataset_manifest(version: str, prior_version: str | None,
                            members: list[dict], static_refs: dict,
                            owner: str, repo: str, created_at: str) -> bytes:
    """Dataset-level ``manifest.json``."""
    recitations = {}
    for m in members:
        slug = m["slug"]
        recitations[slug] = {
            "zip": f"{slug}.zip",
            "zip_url": _release_asset_url(owner, repo, version, f"{slug}.zip"),
            "sha256": m["zip_sha256"],
            "bytes": m["zip_bytes"],
            "coverage_ayahs": m["coverage_ayahs"],
            "content_hash": m["content_hash"],
            "change_kind": m["change_kind"],
            "ts_version": m["ts_version"],
        }
    body = {
        "schema_version": SCHEMA_VERSION,
        "release_version": version,
        "created_at": created_at,
        "previous_version": prior_version,
        "recitation_count": len(members),
        "static_refs": static_refs,
        "recitations": recitations,
        "license": "CC-BY-4.0",
    }
    return json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def _release_asset_url(owner: str, repo: str, version: str, name: str) -> str:
    return (f"https://github.com/{owner}/{repo}"
            f"/releases/download/{version}/{name}")


def _build_changelog(version: str, prior_version: str | None,
                     members: list[dict], static_refs_changed_keys: list[str],
                     operator_note: str | None,
                     owner: str, repo: str, created_at_date: str,
                     hf_dataset: str) -> bytes:
    """Auto-generated CHANGELOG.md — also the release description."""
    out: list[str] = []
    out.append(f"# Changelog — {version} ({created_at_date})\n")
    if prior_version:
        out.append(
            f"Compared to [{prior_version}]"
            f"(https://github.com/{owner}/{repo}/releases/tag/{prior_version}).\n"
        )
    if operator_note:
        out.append("## Notes\n")
        for line in operator_note.strip().splitlines():
            out.append(f"> {line}")
        out.append("")

    added = [m for m in members if m["change_kind"] == "added"]
    if added:
        out.append(f"## Added recitations ({len(added)})\n")
        out.append("| Slug | Name | Riwayah | Style | Channel | Coverage |")
        out.append("|---|---|---|---|---|---|")
        for m in added:
            out.append(
                f"| `{m['slug']}` | {m.get('name_en', '')} "
                f"| {m.get('riwayah', '')} | {m.get('style', '')} "
                f"| {m.get('channel', '')} "
                f"| {m['coverage_ayahs']:,} ayahs |"
            )
        out.append("")

    refreshed = [m for m in members if m["change_kind"] == "refresh"]
    if refreshed:
        out.append(f"## Refreshed recitations ({len(refreshed)})\n")
        out.append("| Slug | Name |")
        out.append("|---|---|")
        for m in refreshed:
            out.append(f"| `{m['slug']}` | {m.get('name_en', '')} |")
        out.append("")

    out.append("## Static references\n")
    for key in ("surah_info.json", "qpc_hafs.json"):
        marker = "refreshed" if key in static_refs_changed_keys else "unchanged"
        out.append(f"- `{key}` — {marker}")
    out.append("")

    out.append("## Schemas\n")
    out.append("<details><summary>verse_timestamps.json.gz</summary>\n")
    out.append('Tier 1. Positional: `"surah:ayah": [start_ms, end_ms]`. '
               'Times are source-relative milliseconds.\n</details>\n')
    out.append("<details><summary>word_timestamps.json.gz</summary>\n")
    out.append('Tier 2. Positional: `"surah:ayah": [[start, end], '
               '[[widx, start, end], ...]]`. Source-relative ms.\n</details>\n')
    out.append("<details><summary>letter_timestamps.json.gz</summary>\n")
    out.append('Tier 3. Positional: `"surah:ayah": [[start, end], [words], '
               '[[widx, char, start, end], ...]]`. Source-relative ms.\n</details>\n')

    out.append("## Links\n")
    out.append(f"- HF dataset: https://huggingface.co/datasets/{hf_dataset}")
    out.append(f"- Repository: https://github.com/{owner}/{repo}\n")

    return "\n".join(out).encode("utf-8")


# ---------------------------------------------------------------------------
# GitHub REST API (stdlib only).
# ---------------------------------------------------------------------------

def _gh_request(method: str, path: str, token: str, *,
                json_body: dict | None = None,
                raw_body: bytes | None = None,
                content_type: str | None = None,
                accept: str = "application/vnd.github+json") -> dict:
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
        raise RuntimeError(f"GH API {method} {url} → {e.code}: {msg[:500]}") from e


def _gh_create_release(owner: str, repo: str, version: str, body: str,
                       token: str) -> dict:
    """Create a draft-less release tag. Returns the release dict (with upload_url)."""
    return _gh_request("POST", f"/repos/{owner}/{repo}/releases", token,
                       json_body={
                           "tag_name": version,
                           "name": version,
                           "body": body,
                           "draft": False,
                           "prerelease": False,
                       })


def _gh_upload_asset(upload_url_template: str, name: str, data: bytes,
                     token: str, content_type: str) -> dict:
    """Upload one asset. upload_url_template ends with ``{?name,label}``."""
    base = upload_url_template.split("{", 1)[0]
    from urllib.parse import quote
    url = f"{base}?name={quote(name)}"
    return _gh_request("POST", url, token, raw_body=data,
                       content_type=content_type,
                       accept="application/vnd.github+json")


# ---------------------------------------------------------------------------
# Completion callback.
# ---------------------------------------------------------------------------

def _post_webhook(*, version: str, job_id: str, external_uri: str,
                  members: list[dict], operator_note: str | None,
                  launched_by: str | None,
                  status: str = "succeeded",
                  validation_summary: dict | None = None) -> bool:
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
        "operator_note": operator_note,
        "launched_by": launched_by,
        "members": members,
    }
    if validation_summary:
        body["validation_summary"] = validation_summary
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "X-Inspector-Job-Secret": secret},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            log.info("webhook %s → %s", url, resp.status)
            return 200 <= resp.status < 300
    except Exception as exc:
        log.warning("webhook POST failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Static refs hash.
# ---------------------------------------------------------------------------

def _hash_static_refs(refs_dir: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for name in ("surah_info.json", "qpc_hafs.json"):
        path = refs_dir / name
        if not path.exists():
            continue
        body = path.read_bytes()
        out[name] = {"sha256": _sha256_hex(body), "bytes": len(body)}
    return out


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------

def _repo_owner_name() -> tuple[str, str, str]:
    """Resolve (owner, repo, hf_dataset_id) from config_loader."""
    from scripts.lib.config_loader import repo_config
    cfg = repo_config()
    return cfg["repo_owner"], cfg["repo_name"], cfg["hf_dataset"]


def main() -> int:
    job_id = os.environ.get("JOB_ID", "").strip() or "unknown"
    operator_note = os.environ.get("OPERATOR_NOTE") or None
    launched_by = os.environ.get("LAUNCHED_BY") or None
    version_override = os.environ.get("RELEASE_VERSION", "").strip() or None
    gh_token = os.environ.get("GH_RELEASE_TOKEN", "").strip()
    if not gh_token:
        log.error("GH_RELEASE_TOKEN is required")
        return 2

    owner, repo, hf_dataset = _repo_owner_name()
    log.info("cut_release: owner=%s repo=%s job=%s", owner, repo, job_id)

    # 1. Discover eligible recitations + prior release members.
    with _open_inspector_db_readonly() as conn:
        eligible = _eligible_recitations(conn)
        prior_version, prior_members = _prior_release_members(conn)
    log.info("found %d eligible recitations; prior release: %s",
             len(eligible), prior_version or "<none>")

    if not eligible:
        log.error("no eligible recitations — aborting")
        return 3

    # 2. Build per-recitation artifacts and accumulate member rows.
    refs_dir = Path("/aux/code/data")
    surah_info = json.loads((refs_dir / "surah_info.json").read_bytes())
    from scripts.lib.dataset_validation import (
        fatal_violations, validate_dataset,
    )

    now = datetime.datetime.now(datetime.timezone.utc)
    created_at_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    created_at_date = now.strftime("%Y-%m-%d")

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

        # Load detailed.json so the intra-segment gapless check has segments
        # to validate (plan §"Boundary enforcement" — the four checks include
        # intra-segment gapless, which needs segment word-ranges).
        detailed_segments = _segments_per_verse_from_detailed(slug)

        # Boundary validate (source-relative ms — verses dict already in that frame).
        for_validate = {
            k: {
                "verse_start_ms": int(v.get("verse_start_ms")
                                      or (v["words"][0][1] if v.get("words") else 0)),
                "verse_end_ms": int(v.get("verse_end_ms")
                                    or (max(w[2] for w in v["words"])
                                        if v.get("words") else 0)),
                "duration_ms": int(v.get("verse_end_ms", 0) - v.get("verse_start_ms", 0)
                                   if isinstance(v, dict) else 0),
                "words": [(int(w[0]), int(w[1]), int(w[2]))
                          for w in (v.get("words") or [])],
                "segments": detailed_segments.get(k, []),
            }
            for k, v in verses.items() if not k.startswith("_") and isinstance(v, dict)
        }
        rec_summary = validate_dataset(for_validate, surah_info=surah_info)
        fatal = fatal_violations(rec_summary["violations"])
        if fatal:
            log.error("  %s: %d fatal boundary violations — aborting cut",
                      slug, len(fatal))
            for v in fatal[:5]:
                log.error("    %s", v)
            _post_webhook(version=version_override or "",
                          job_id=job_id, external_uri="",
                          members=[], operator_note=operator_note,
                          launched_by=launched_by, status="failed",
                          validation_summary={"slug": slug, "summary": rec_summary})
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
        catalog_bytes = _build_catalog_json(rec, audio_manifest, verses)

        # content_hash — over letter tier + catalog bytes.
        content_hash = _sha256_hex(tier_files["letter_timestamps.json.gz"]
                                   + catalog_bytes)

        # Per-recitation manifest.json (carries the version it was packed for —
        # auto-version is computed below from the candidate members list, so we
        # patch the version into per-rec manifests in a second pass).
        files = dict(tier_files)
        files["catalog.json"] = catalog_bytes
        files["manifest.json"] = b"__PENDING_VERSION__"  # placeholder; patched below

        coverage_ayahs = sum(1 for k in verses if not k.startswith("_"))
        change_kind = _classify_change_kind(rec, prior_members, content_hash)

        # Build the catalog_snapshot (frozen at cut time, what the row stores).
        catalog_snapshot = json.loads(catalog_bytes.decode("utf-8"))

        members.append({
            "slug": slug,
            "name_en": rec.get("name_en"),
            "riwayah": rec.get("riwayah"),
            "style": rec.get("style"),
            "channel": rec.get("channel"),
            "ts_version": str(rec["ts_version"]),
            "coverage_ayahs": coverage_ayahs,
            "content_hash": content_hash,
            "change_kind": change_kind,
            "catalog_snapshot": catalog_snapshot,
            "_files": files,
            "_zip_bytes": None,  # filled after version is known
            "zip_sha256": "",
            "zip_bytes": 0,
        })

    if not members:
        log.error("no members built — aborting")
        return 5

    # 3. Static refs hashes.
    prior_static = {}
    # Pull prior static_refs from prior dataset manifest. Simpler approach:
    # compare hashes against the live HEAD on GH releases. Best-effort.
    static_refs = _hash_static_refs(refs_dir)
    static_refs_changed_keys: list[str] = []
    if prior_version:
        try:
            prior_manifest_url = _release_asset_url(
                owner, repo, prior_version, "manifest.json")
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
        version = _compute_version(prior_version, members,
                                   bool(static_refs_changed_keys),
                                   version_override)
    except RuntimeError as exc:
        log.error("version compute: %s", exc)
        _post_webhook(version="", job_id=job_id, external_uri="",
                      members=[], operator_note=operator_note,
                      launched_by=launched_by, status="failed")
        return 6
    log.info("computed version: %s", version)

    # 5. Patch per-recitation manifests with the version + pack zips.
    for m in members:
        files = m["_files"]
        files["manifest.json"] = _build_per_recitation_manifest(
            m["slug"], version, {k: v for k, v in files.items()
                                 if k != "manifest.json"},
            created_at_iso,
        )
        zip_data = _pack_recitation_zip(m["slug"], files)
        m["_zip_bytes"] = zip_data
        m["zip_sha256"] = _sha256_hex(zip_data)
        m["zip_bytes"] = len(zip_data)
        zip_bytes_by_slug[m["slug"]] = zip_data

    # 6. Dataset-level manifest + CHANGELOG.
    dataset_manifest = _build_dataset_manifest(
        version, prior_version, members,
        {k: v for k, v in static_refs.items()},
        owner, repo, created_at_iso,
    )
    changelog_md = _build_changelog(
        version, prior_version, members, static_refs_changed_keys,
        operator_note, owner, repo, created_at_date, hf_dataset,
    )

    # 7. Read static refs + license + shard.py for upload.
    license_bytes = (_REPO_ROOT / "LICENSE").read_bytes() if (_REPO_ROOT / "LICENSE").exists() else b""
    shard_py = (Path("/aux/code/scripts/jobs/shard.py")).read_bytes()
    static_files = {}
    for name in ("surah_info.json", "qpc_hafs.json"):
        path = refs_dir / name
        if path.exists():
            static_files[name] = path.read_bytes()

    # 8. Create the GH release + upload all assets.
    log.info("creating GH release %s on %s/%s ...", version, owner, repo)
    rel = _gh_create_release(owner, repo, version,
                             changelog_md.decode("utf-8"),
                             token=gh_token)
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
        version=version, job_id=job_id,
        external_uri=release_html_url,
        members=webhook_members, operator_note=operator_note,
        launched_by=launched_by,
        validation_summary={
            "violation_count": validation_summary_total["violation_count"],
            "by_kind": validation_summary_total["by_kind"],
        },
    )

    log.info("cut_release: done version=%s recitations=%d",
             version, len(members))
    return 0


def _build_dataset_level_catalog(members: list[dict]) -> bytes:
    """Dataset-level ``catalog.json`` — array of every recitation's catalog row."""
    body = {
        "schema_version": SCHEMA_VERSION,
        "recitations": [m["catalog_snapshot"] for m in members],
    }
    return json.dumps(body, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


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
                s_surah = int(sp[0]); s_ayah = int(sp[1]); e_ayah = int(ep[1])
            except (ValueError, IndexError):
                continue
            w_from = seg.get("word_from", seg.get("start_word", 1))
            w_to = seg.get("word_to", seg.get("end_word", w_from))
            t_start = int(seg.get("time_start", 0))
            t_end = int(seg.get("time_end", 0))
            for a in range(s_ayah, e_ayah + 1):
                vref = f"{s_surah}:{a}"
                out.setdefault(vref, []).append(
                    (int(w_from), int(w_to), t_start, t_end))
    return out


if __name__ == "__main__":
    sys.exit(main())
