"""HF dataset catalog projection and card upload.

The Inspector SQLite catalog is the source of truth. The HF dataset exposes a
parquet projection as config ``mushafs`` / split ``all`` so dataset consumers
can query the catalog without calling the Inspector app.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from qua_shared.schemas.bucket.catalog import ReciterCatalog

CATALOG_CONFIG_NAME = "mushafs"
CATALOG_SPLIT_NAME = "all"

# Each mushaf is its own config with a single split under this name. The HF
# dataset-viewer caps a config at 30 splits, so mushafs cannot share one config.
VERSE_SPLIT_NAME = "train"

CATALOG_COLUMNS = (
    "slug",
    "reciter_id",
    "name_en",
    "name_ar",
    "country",
    "riwayah",
    "style",
    "recording_context",
    "recording_year",
    "channel",
    "audio_category",
    "chapter_count",
    "codec",
    "container",
    "sample_rate_hz",
    "channels",
    "bitrate_mode",
    "bitrate_kbps_nominal",
    "total_duration_hours",
    "published_at",
    "updated_at",
)


class HfDatasetCatalogStats(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamped_recitations: int = Field(..., ge=0)
    timestamped_riwayat: int = Field(..., ge=0)
    timestamped_seconds: int = Field(..., ge=0)


@dataclass(frozen=True)
class CatalogProjection:
    catalog: ReciterCatalog
    rows: list[dict[str, Any]]
    stats: HfDatasetCatalogStats


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    return json.loads(value)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def load_catalog_from_sqlite(db_path: Path) -> ReciterCatalog:
    """Assemble ``ReciterCatalog`` v2 directly from an Inspector SQLite DB."""
    conn = _connect(db_path)
    try:
        meta = conn.execute(
            "SELECT schema_version, generated_at, derived FROM catalog_meta WHERE id = 1"
        ).fetchone()
        if meta is None:
            raise RuntimeError(f"{db_path}: catalog_meta row missing")

        catalog = {
            "schema_version": meta["schema_version"],
            "generated_at": meta["generated_at"],
            "vocab": {
                "riwayat": [
                    dict(r)
                    for r in conn.execute("SELECT slug, short, name FROM riwayahs ORDER BY slug")
                ],
                "styles": [
                    dict(r)
                    for r in conn.execute("SELECT slug, short, name FROM styles ORDER BY slug")
                ],
                "sources": [
                    {
                        "slug": r["slug"],
                        "name": r["name"],
                        "url": r["url"],
                        "audio_categories": _json_loads(r["audio_categories"], []),
                    }
                    for r in conn.execute(
                        "SELECT slug, name, url, audio_categories FROM sources ORDER BY slug"
                    )
                ],
                "channels": [
                    {
                        "slug": r["slug"],
                        "short": r["short"],
                        "name": r["name"],
                        "host_patterns": _json_loads(r["host_patterns"], []),
                        "gh_release_eligible": bool(r["gh_release_eligible"]),
                    }
                    for r in conn.execute(
                        "SELECT slug, short, name, host_patterns, gh_release_eligible "
                        "FROM channels ORDER BY slug"
                    )
                ],
                "recording_contexts": [
                    dict(r)
                    for r in conn.execute("SELECT slug, name FROM recording_contexts ORDER BY slug")
                ],
            },
            "reciters": [
                dict(r)
                for r in conn.execute(
                    "SELECT reciter_id, name_en, name_ar, country, notes "
                    "FROM reciters ORDER BY reciter_id"
                )
            ],
            "deliveries": [dict(r) for r in conn.execute("SELECT * FROM deliveries ORDER BY slug")],
            "aliases": [
                dict(r)
                for r in conn.execute("SELECT kind, old, new, ts FROM catalog_aliases ORDER BY id")
            ],
            "derived": _json_loads(meta["derived"], {"source_channels": []}),
        }
        return ReciterCatalog.model_validate(catalog)
    finally:
        conn.close()


def _current_release_rows(db_path: Path, track: str) -> dict[str, sqlite3.Row]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT slug, version, stale_since FROM per_recitation_releases "
            "WHERE track = ? AND superseded_at IS NULL",
            (track,),
        ).fetchall()
        return {r["slug"]: r for r in rows}
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()


def _hf_release_meta(db_path: Path) -> dict[str, dict[str, Any]]:
    """Per-slug HF publish metadata: first publish (``published_at``) and latest
    publish/refresh (``updated_at``), plus ``version``/``stale_since``.

    ``updated_at`` is the current (non-superseded) row's ``produced_at`` — it
    advances on every republish. ``published_at`` is the earliest ``produced_at``
    across all rows for the slug. Both ``produced_at`` values are ``to_iso`` UTC
    strings (Z-suffixed), so a lexicographic ``MIN`` is the earliest instant.
    """
    conn = _connect(db_path)
    try:
        current = conn.execute(
            "SELECT slug, version, stale_since, produced_at FROM per_recitation_releases "
            "WHERE track = 'hf' AND superseded_at IS NULL"
        ).fetchall()
        firsts = conn.execute(
            "SELECT slug, MIN(produced_at) AS first_at FROM per_recitation_releases "
            "WHERE track = 'hf' GROUP BY slug"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()
    first_by = {r["slug"]: r["first_at"] for r in firsts}
    return {
        r["slug"]: {
            "version": r["version"],
            "stale_since": r["stale_since"],
            "published_at": first_by.get(r["slug"], r["produced_at"]),
            "updated_at": r["produced_at"],
        }
        for r in current
    }


def project_catalog_rows(
    catalog: ReciterCatalog,
    *,
    ts_releases: dict[str, Any] | None = None,
    hf_releases: dict[str, Any] | None = None,
    published_slugs: set[str] | None = None,
    now_iso: str | None = None,
) -> list[dict[str, Any]]:
    """Flatten ``ReciterCatalog`` v2 to the HF dataset catalog row shape.

    ``now_iso`` stamps ``published_at``/``updated_at`` for any published row that
    has no ``hf`` ledger row yet. The catalog is built inside the publish job,
    but the ledger row is written afterwards by ``hf_publish.complete()`` — so
    without this the just-published reciter's timestamps would be ``null``.
    """
    reciters = {r.reciter_id: r for r in catalog.reciters}
    riwayat = {r.slug: r for r in catalog.vocab.riwayat}
    styles = {s.slug: s for s in catalog.vocab.styles}
    channels = {c.slug: c for c in catalog.vocab.channels}
    contexts = {c.slug: c for c in catalog.vocab.recording_contexts}
    ts_releases = ts_releases or {}
    hf_releases = hf_releases or {}

    rows: list[dict[str, Any]] = []
    matched_published = (
        _catalog_slugs_for_published_splits(catalog, published_slugs) if published_slugs else set()
    )
    delivered_slugs = matched_published or set(hf_releases) or set(ts_releases)

    for delivery in sorted(catalog.deliveries, key=lambda d: d.slug):
        if delivered_slugs and delivery.slug not in delivered_slugs:
            continue
        reciter = reciters.get(delivery.reciter_id)
        channel = channels.get(delivery.channel)
        context = contexts.get(delivery.recording_context or "")
        hf_meta = hf_releases.get(delivery.slug) or {}

        rows.append(
            {
                "slug": delivery.slug,
                "reciter_id": delivery.reciter_id,
                "name_en": reciter.name_en if reciter else "",
                "name_ar": reciter.name_ar if reciter else None,
                "country": reciter.country if reciter else None,
                "riwayah": riwayat[delivery.riwayah].name
                if delivery.riwayah in riwayat
                else delivery.riwayah,
                "style": styles[delivery.style].name
                if delivery.style in styles
                else delivery.style,
                "recording_context": context.name if context else delivery.recording_context,
                "recording_year": delivery.recording_year,
                "channel": channel.name if channel else delivery.channel,
                "audio_category": str(delivery.audio_category.value),
                "chapter_count": delivery.chapter_count,
                "codec": delivery.codec,
                "container": delivery.container,
                "sample_rate_hz": delivery.sample_rate_hz,
                "channels": delivery.channels,
                "bitrate_mode": str(delivery.bitrate_mode.value),
                "bitrate_kbps_nominal": delivery.bitrate_kbps_nominal,
                "total_duration_hours": round(delivery.total_duration_sec / 3600, 1)
                if delivery.total_duration_sec is not None
                else None,
                "published_at": hf_meta.get("published_at") or now_iso,
                "updated_at": hf_meta.get("updated_at") or now_iso,
            }
        )
    return rows


def _stats_from_rows(rows: list[dict[str, Any]]) -> HfDatasetCatalogStats:
    return HfDatasetCatalogStats(
        timestamped_recitations=len(rows),
        timestamped_riwayat=len({r["riwayah"] for r in rows}),
        timestamped_seconds=int(round(sum((r["total_duration_hours"] or 0) for r in rows) * 3600)),
    )


def _norm_slug(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _catalog_slugs_for_published_splits(
    catalog: ReciterCatalog,
    published_slugs: set[str] | None,
) -> set[str]:
    if not published_slugs:
        return set()
    return {
        delivery.slug
        for split in published_slugs
        if (delivery := _delivery_for_published_split(catalog, split)) is not None
    }


def _delivery_for_published_split(catalog: ReciterCatalog, split: str):
    by_slug = {d.slug: d for d in catalog.deliveries}
    if split in by_slug:
        return by_slug[split]

    by_reciter: dict[str, list[Any]] = {}
    for delivery in catalog.deliveries:
        by_reciter.setdefault(delivery.reciter_id, []).append(delivery)
    if split in by_reciter:
        return _preferred_delivery(by_reciter[split])

    split_norm = _norm_slug(split)
    best_reciter = None
    best_score = 0.0
    for reciter in catalog.reciters:
        score = SequenceMatcher(None, split_norm, _norm_slug(reciter.reciter_id)).ratio()
        if score > best_score:
            best_reciter = reciter.reciter_id
            best_score = score
    if best_reciter is not None and best_score >= 0.78:
        return _preferred_delivery(by_reciter.get(best_reciter, []))
    return None


def _preferred_delivery(deliveries: list[Any]):
    candidates = [d for d in deliveries if d.total_duration_sec and d.chapter_count >= 100]
    if not candidates:
        candidates = [d for d in deliveries if d.total_duration_sec]
    if not candidates:
        return deliveries[0] if deliveries else None

    def score(delivery: Any) -> tuple[int, int, str]:
        style_penalty = 1 if delivery.style in {"muallim", "mujawwad"} else 0
        return (style_penalty, int(delivery.total_duration_sec or 0), delivery.slug)

    return min(candidates, key=score)


def _stats_from_published_splits(
    catalog: ReciterCatalog,
    published_slugs: set[str],
) -> HfDatasetCatalogStats:
    riwayat: set[str] = set()
    seconds = 0
    for split in published_slugs:
        delivery = _delivery_for_published_split(catalog, split)
        if delivery is None:
            continue
        riwayat.add(delivery.riwayah)
        seconds += int(delivery.total_duration_sec or 0)
    return HfDatasetCatalogStats(
        timestamped_recitations=len(published_slugs),
        timestamped_riwayat=len(riwayat),
        timestamped_seconds=seconds,
    )


def build_projection_from_sqlite(
    db_path: Path,
    *,
    published_slugs: set[str] | None = None,
    now_iso: str | None = None,
) -> CatalogProjection:
    catalog = load_catalog_from_sqlite(db_path)
    rows = project_catalog_rows(
        catalog,
        ts_releases=_current_release_rows(db_path, "ts"),
        hf_releases=_hf_release_meta(db_path),
        published_slugs=published_slugs,
        now_iso=now_iso,
    )
    stats = (
        _stats_from_published_splits(catalog, published_slugs)
        if published_slugs is not None
        else _stats_from_rows(rows)
    )
    return CatalogProjection(catalog=catalog, rows=rows, stats=stats)


def catalog_data_dict(rows: list[dict[str, Any]]) -> dict[str, list[Any]]:
    return {column: [row.get(column) for row in rows] for column in CATALOG_COLUMNS}


def catalog_features():
    from datasets import Features, Value

    return Features(
        {
            "slug": Value("string"),
            "reciter_id": Value("string"),
            "name_en": Value("string"),
            "name_ar": Value("string"),
            "country": Value("string"),
            "riwayah": Value("string"),
            "style": Value("string"),
            "recording_context": Value("string"),
            "recording_year": Value("int32"),
            "channel": Value("string"),
            "audio_category": Value("string"),
            "chapter_count": Value("int32"),
            "codec": Value("string"),
            "container": Value("string"),
            "sample_rate_hz": Value("int32"),
            "channels": Value("int32"),
            "bitrate_mode": Value("string"),
            "bitrate_kbps_nominal": Value("int32"),
            # float64, not float32: the value is round(sec/3600, 1) (e.g. 31.4),
            # which float32 cannot represent exactly — widening it back in a
            # viewer shows 31.399999…/31.40000…. float64 displays the 1-decimal
            # value cleanly.
            "total_duration_hours": Value("float64"),
            "published_at": Value("string"),
            "updated_at": Value("string"),
        }
    )


def build_catalog_dataset(rows: list[dict[str, Any]]):
    from datasets import Dataset

    return Dataset.from_dict(catalog_data_dict(rows), features=catalog_features())


def push_catalog_dataset(
    *,
    repo_id: str,
    db_path: Path,
    token: str | None,
    published_slugs: set[str] | None = None,
    now_iso: str | None = None,
) -> HfDatasetCatalogStats:
    if published_slugs is None:
        published_slugs = hub_published_split_slugs(repo_id=repo_id, token=token)
    projection = build_projection_from_sqlite(
        db_path, published_slugs=published_slugs, now_iso=now_iso
    )
    ds = build_catalog_dataset(projection.rows)
    ds.push_to_hub(
        repo_id,
        config_name=CATALOG_CONFIG_NAME,
        split=CATALOG_SPLIT_NAME,
        token=token,
        commit_message="update mushafs catalog",
    )
    return projection.stats


def hub_published_splits_by_config(
    *, repo_id: str, token: str | None = None
) -> dict[str, list[str]]:
    """Map each verse-level config (riwayah) to its sorted parquet split slugs.

    Excludes the catalog/auxiliary configs (``mushafs``/``segments``/``timestamps``).
    This is the single enumeration path the release-time dataset card frontmatter and
    the published-slug stats both derive from.
    """
    from huggingface_hub import HfApi

    ignored = {CATALOG_CONFIG_NAME, "segments", "timestamps"}
    by_config: dict[str, set[str]] = {}
    for item in HfApi(token=token).list_repo_tree(
        repo_id=repo_id,
        repo_type="dataset",
        recursive=True,
    ):
        path = getattr(item, "rfilename", None) or getattr(item, "path", "")
        if not path.endswith(".parquet") or path.count("/") != 1:
            continue
        config, filename = path.split("/", 1)
        if config in ignored:
            continue
        split = filename.split("-", 1)[0]
        if split:
            by_config.setdefault(config, set()).add(split)
    return {config: sorted(splits) for config, splits in sorted(by_config.items())}


def hub_published_split_slugs(*, repo_id: str, token: str | None = None) -> set[str]:
    """Return delivery slugs with verse-level parquet splits on the HF dataset."""
    by_config = hub_published_splits_by_config(repo_id=repo_id, token=token)
    return {slug for slugs in by_config.values() for slug in slugs}


def format_hours(seconds: int) -> str:
    """Badge-friendly hours, floored to 50h blocks (e.g. ``100h+``).

    Shared with ``scripts/codegen/update_readme_badges.py`` so the GitHub README
    and the HF dataset card render hours identically.
    """
    hours = int(seconds // 3600)
    floored = (hours // 50) * 50
    return f"{floored:,}h+"


def badge_url(label: str, value: str, color: str) -> str:
    from urllib.parse import quote

    return f"https://img.shields.io/badge/{quote(label, safe='')}-{quote(value, safe='')}-{color}"


def _render_configs_block(splits_by_config: dict[str, list[str]]) -> str:
    """Build the dataset-card ``configs:`` YAML from published parquet splits.

    One ``config_name`` per mushaf slug, each with a single ``train`` split, then
    the ``mushafs``/``all`` catalog config last. ``splits_by_config`` maps the
    riwayah folder to its slugs; the folder is used only for the file ``path`` —
    parquet stays under ``<riwayah_folder>/<slug>-*``. Mushafs get their own
    configs (not shared splits) because the HF viewer caps a config at 30 splits.
    Indentation matches the hand-authored card exactly.
    """
    lines = ["configs:"]
    for folder in sorted(splits_by_config):
        for slug in splits_by_config[folder]:
            lines.append(f"- config_name: {slug}")
            lines.append("  data_files:")
            lines.append(f"  - split: {VERSE_SPLIT_NAME}")
            lines.append(f"    path: {folder}/{slug}-*")
    lines.append(f"- config_name: {CATALOG_CONFIG_NAME}")
    lines.append("  data_files:")
    lines.append(f"  - split: {CATALOG_SPLIT_NAME}")
    lines.append(f"    path: {CATALOG_CONFIG_NAME}/{CATALOG_SPLIT_NAME}-*")
    return "\n".join(lines)


def render_dataset_card(
    *,
    template_path: Path,
    splits_by_config: dict[str, list[str]],
    stats: HfDatasetCatalogStats,
) -> str:
    """Render the release-time dataset card from the template.

    Substitutes ``{{configs}}`` (frontmatter), ``{{recitations}}``, ``{{riwayat}}``,
    and ``{{hours}}`` (header badges) so the published README always reflects the
    actual hub splits + catalog stats.
    """
    from urllib.parse import quote

    template = template_path.read_text(encoding="utf-8")
    rendered = (
        template.replace("{{configs}}", _render_configs_block(splits_by_config))
        .replace("{{recitations}}", str(stats.timestamped_recitations))
        .replace("{{riwayat}}", str(stats.timestamped_riwayat))
        .replace("{{hours}}", quote(format_hours(stats.timestamped_seconds), safe=""))
    )
    if "{{" in rendered:
        raise RuntimeError(f"unrendered placeholder in dataset card: {template_path}")
    return rendered


def upload_dataset_card(*, repo_id: str, content: str, token: str | None) -> None:
    """Commit the rendered card as the HF dataset ``README.md``."""
    from huggingface_hub import CommitOperationAdd, HfApi

    HfApi(token=token).create_commit(
        repo_id=repo_id,
        repo_type="dataset",
        operations=[
            CommitOperationAdd(
                path_in_repo="README.md",
                path_or_fileobj=content.encode("utf-8"),
            ),
        ],
        commit_message="update dataset card",
    )


def sync_dataset_assets(
    *,
    repo_id: str,
    assets: dict[str, bytes],
    remove: tuple[str, ...] = (),
    token: str | None,
) -> None:
    """Commit public presentation assets and remove superseded files."""
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

    api = HfApi(token=token)
    existing = set(api.list_repo_files(repo_id=repo_id, repo_type="dataset"))
    operations: list[CommitOperationAdd | CommitOperationDelete] = [
        CommitOperationAdd(path_in_repo=filename, path_or_fileobj=content)
        for filename, content in sorted(assets.items())
    ]
    operations.extend(
        CommitOperationDelete(path_in_repo=filename) for filename in remove if filename in existing
    )
    api.create_commit(
        repo_id=repo_id,
        repo_type="dataset",
        operations=operations,
        commit_message="update DigitalKhatt release assets",
    )
