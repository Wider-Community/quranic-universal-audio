from __future__ import annotations

import sqlite3
from pathlib import Path

from qua_shared.hf_dataset_catalog import (
    CATALOG_COLUMNS,
    CATALOG_CONFIG_NAME,
    HfDatasetCatalogStats,
    _hf_release_meta,
    build_catalog_dataset,
    hub_published_splits_by_config,
    project_catalog_rows,
    render_dataset_card,
)
from qua_shared.schemas.catalog import ReciterCatalog

_CARD_TEMPLATE = Path(__file__).resolve().parents[2] / "docs" / "hf_dataset_card.md"


def _catalog() -> ReciterCatalog:
    return ReciterCatalog.model_validate(
        {
            "schema_version": 2,
            "generated_at": "2026-06-05T00:00:00Z",
            "vocab": {
                "riwayat": [{"slug": "hafs_an_asim", "short": "hafs", "name": "Hafs"}],
                "styles": [{"slug": "murattal", "short": "mur", "name": "Murattal"}],
                "sources": [
                    {
                        "slug": "mp3quran",
                        "name": "MP3Quran",
                        "url": "https://mp3quran.net",
                        "audio_categories": ["by_surah"],
                    }
                ],
                "channels": [
                    {
                        "slug": "mp3quran",
                        "short": "mp3q",
                        "name": "MP3Quran",
                        "host_patterns": ["mp3quran.net"],
                        "gh_release_eligible": True,
                    }
                ],
                "recording_contexts": [
                    {"slug": "studio", "name": "Studio"},
                ],
            },
            "reciters": [
                {
                    "reciter_id": "maher_al_muaiqly",
                    "name_en": "Maher Al-Muaiqly",
                    "name_ar": "Maher Al-Muaiqly",
                    "country": "SA",
                }
            ],
            "deliveries": [
                {
                    "slug": "maher_al_muaiqly_mp3quran",
                    "reciter_id": "maher_al_muaiqly",
                    "riwayah": "hafs_an_asim",
                    "style": "murattal",
                    "recording_context": "studio",
                    "recording_year": 2020,
                    "variant_label": None,
                    "source": "mp3quran",
                    "channel": "mp3quran",
                    "source_url": None,
                    "audio_category": "by_surah",
                    "chapter_count": 114,
                    "codec": "mp3",
                    "container": "mp3",
                    "sample_rate_hz": 44100,
                    "channels": 2,
                    "bitrate_mode": "cbr",
                    "bitrate_kbps_nominal": 128,
                    "total_duration_sec": 81000,
                    "added_at": "2026-06-05T00:00:00Z",
                    "added_by_hf_id": "system",
                }
            ],
            "aliases": [],
            "derived": {"source_channels": []},
        }
    )


def test_project_catalog_rows_joins_vocab_and_publish_state():
    rows = project_catalog_rows(
        _catalog(),
        ts_releases={"maher_al_muaiqly_mp3quran": {"version": "ts-1"}},
        hf_releases={
            "maher_al_muaiqly_mp3quran": {
                "version": "sha-1",
                "stale_since": None,
                "published_at": "2026-06-01T00:00:00Z",
                "updated_at": "2026-06-04T00:00:00Z",
            }
        },
        published_slugs={"maher_al_meaqli"},
    )

    assert rows == [
        {
            "slug": "maher_al_muaiqly_mp3quran",
            "reciter_id": "maher_al_muaiqly",
            "name_en": "Maher Al-Muaiqly",
            "name_ar": "Maher Al-Muaiqly",
            "country": "SA",
            "riwayah": "Hafs",
            "style": "Murattal",
            "recording_context": "Studio",
            "recording_year": 2020,
            "channel": "MP3Quran",
            "audio_category": "by_surah",
            "chapter_count": 114,
            "codec": "mp3",
            "container": "mp3",
            "sample_rate_hz": 44100,
            "channels": 2,
            "bitrate_mode": "cbr",
            "bitrate_kbps_nominal": 128,
            "total_duration_hours": 22.5,
            "published_at": "2026-06-01T00:00:00Z",
            "updated_at": "2026-06-04T00:00:00Z",
        }
    ]


def test_catalog_dataset_features_match_pushed_schema():
    rows = project_catalog_rows(_catalog(), published_slugs={"maher_al_meaqli"})
    ds = build_catalog_dataset(rows)
    feature_names = list(ds.features.keys())

    assert CATALOG_CONFIG_NAME == "mushafs"
    assert feature_names == list(CATALOG_COLUMNS)
    assert "slug" in feature_names
    assert "delivery_slug" not in feature_names


def test_internal_columns_excluded_from_public_projection():
    rows = project_catalog_rows(_catalog(), published_slugs={"maher_al_meaqli"})

    assert "gh_release_eligible" not in CATALOG_COLUMNS
    assert "variant_label" not in CATALOG_COLUMNS
    assert "gh_release_eligible" not in rows[0]
    assert "variant_label" not in rows[0]


def test_hf_release_meta_first_publish_and_latest_refresh(tmp_path):
    db = tmp_path / "inspector.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE per_recitation_releases ("
        " id INTEGER PRIMARY KEY, track TEXT, slug TEXT, version TEXT,"
        " produced_at TEXT, superseded_at TEXT, stale_since TEXT)"
    )
    # Reciter republished twice: first row superseded, latest is current.
    conn.executemany(
        "INSERT INTO per_recitation_releases"
        "(track, slug, version, produced_at, superseded_at) VALUES (?,?,?,?,?)",
        [
            ("hf", "reciter_a", "v1", "2026-06-01T00:00:00Z", "2026-06-04T00:00:00Z"),
            ("hf", "reciter_a", "v2", "2026-06-04T00:00:00Z", None),
            ("ts", "reciter_a", "ts1", "2026-05-01T00:00:00Z", None),
        ],
    )
    conn.commit()
    conn.close()

    meta = _hf_release_meta(db)

    assert meta == {
        "reciter_a": {
            "version": "v2",
            "stale_since": None,
            "published_at": "2026-06-01T00:00:00Z",  # first publish, from superseded row
            "updated_at": "2026-06-04T00:00:00Z",  # current row, advances on republish
        }
    }


class _TreeItem:
    def __init__(self, rfilename: str) -> None:
        self.rfilename = rfilename


def test_hub_published_splits_by_config_groups_and_excludes(monkeypatch):
    tree = [
        _TreeItem("hafs_an_asim/maher_al_meaqli-00000-of-00001.parquet"),
        _TreeItem("hafs_an_asim/saad_al_ghamdi-00000-of-00001.parquet"),
        _TreeItem("warsh_an_nafi/some_reciter-00000-of-00001.parquet"),
        _TreeItem("mushafs/all-00000-of-00001.parquet"),
        _TreeItem("segments/all-00000-of-00001.parquet"),
        _TreeItem("README.md"),
        _TreeItem("hafs_an_asim/nested/dir-00000.parquet"),
    ]

    class _FakeApi:
        def __init__(self, token=None):
            pass

        def list_repo_tree(self, *, repo_id, repo_type, recursive):
            return list(tree)

    monkeypatch.setattr("huggingface_hub.HfApi", _FakeApi)

    by_config = hub_published_splits_by_config(repo_id="owner/ds", token=None)

    assert by_config == {
        "hafs_an_asim": ["maher_al_meaqli", "saad_al_ghamdi"],
        "warsh_an_nafi": ["some_reciter"],
    }


def test_render_dataset_card_substitutes_configs_and_badges():
    card = render_dataset_card(
        template_path=_CARD_TEMPLATE,
        splits_by_config={"hafs_an_asim": ["alpha", "beta"]},
        stats=HfDatasetCatalogStats(
            timestamped_recitations=2,
            timestamped_riwayat=1,
            timestamped_seconds=360_000,  # 100h
        ),
    )

    # No placeholder survives.
    assert "{{" not in card

    # Frontmatter configs: both verse splits + mushafs/all last, in order.
    assert "- config_name: hafs_an_asim" in card
    assert "  - split: alpha\n    path: hafs_an_asim/alpha-*" in card
    assert "  - split: beta\n    path: hafs_an_asim/beta-*" in card
    mushafs_idx = card.index("- config_name: mushafs")
    riwayah_idx = card.index("- config_name: hafs_an_asim")
    assert riwayah_idx < mushafs_idx  # mushafs is last
    assert "  - split: all\n    path: mushafs/all-*" in card

    # Header badges reflect the stats (hours floored to 50h blocks, URL-encoded).
    assert "Recitations-2-d4842a" in card
    assert "Riwayat-1-f0ad4e" in card
    assert "Hours-100h%2B-d4842a" in card
