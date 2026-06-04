from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / ".github" / "scripts" / "update_readme_badges.py"
)
SPEC = importlib.util.spec_from_file_location("update_readme_badges", SCRIPT_PATH)
badges = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = badges
SPEC.loader.exec_module(badges)


def test_format_hours_floors_to_50_with_plus():
    assert badges.format_hours(0) == "0h+"
    assert badges.format_hours(49 * 3600) == "0h+"
    assert badges.format_hours(50 * 3600) == "50h+"
    assert badges.format_hours(99 * 3600) == "50h+"
    assert badges.format_hours(1249 * 3600) == "1,200h+"


def test_replace_badges_replaces_legacy_commented_block():
    readme = """<p align="center">
  <!-- <br> -->
  <!-- <a href="data/RECITERS.md"><img src="https://img.shields.io/badge/Unsegmented-832%20reciters%20%C2%B7%2014,320h-d4842a" alt="Unsegmented"></a> -->
  <!-- <a href="data/RECITERS.md"><img src="https://img.shields.io/badge/Riwayat-16%20%2F%2020-f0ad4e" alt="Riwayat"></a> -->
  <!-- <a href="data/RECITERS.md"><img src="https://img.shields.io/badge/Segmented-14%20reciters%20%C2%B7%20336h-d4842a" alt="Segmented"></a> -->
  <br>
</p>
"""
    rendered = badges.render_badges(
        badges.BadgeStats(recitations=12, riwayat=7, seconds=123 * 3600)
    )

    updated = badges.replace_badges(readme, rendered)

    assert "<!-- stats-badges:start -->" in updated
    assert "Recitations-12" in updated
    assert "Riwayat-7" in updated
    assert "Hours-100h%2B" in updated
    assert "Unsegmented" not in updated


def test_replace_badges_updates_existing_marked_block():
    old = "\n".join(
        [
            "before",
            badges.START_MARKER,
            "  stale",
            badges.END_MARKER,
            "after",
        ]
    )
    new_block = badges.render_badges(badges.BadgeStats(recitations=1, riwayat=2, seconds=50 * 3600))

    updated = badges.replace_badges(old, new_block)

    assert "stale" not in updated
    assert updated.count(badges.START_MARKER) == 1
    assert "Recitations-1" in updated


def test_collect_stats_filters_public_released_and_uses_manifest_fallback(tmp_path):
    db_path = tmp_path / "inspector.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE deliveries (
                slug TEXT PRIMARY KEY,
                riwayah TEXT NOT NULL,
                total_duration_sec INTEGER
            );
            CREATE TABLE delivery_states (
                slug TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                visibility TEXT NOT NULL
            );
            INSERT INTO deliveries VALUES
                ('pub_a', 'hafs_an_asim', 3600),
                ('pub_b', 'warsh_an_nafi', NULL),
                ('wip', 'hafs_an_asim', 7200),
                ('discarded', 'qalun_an_nafi', 7200);
            INSERT INTO delivery_states VALUES
                ('pub_a', 'released', 'public'),
                ('pub_b', 'released', 'public'),
                ('wip', 'under_review', 'public'),
                ('discarded', 'released', 'discarded');
            """
        )
        conn.commit()
    finally:
        conn.close()

    def manifest_reader(slug: str) -> dict:
        assert slug == "pub_b"
        return {
            "chapters": {
                "1": {"duration_sec": 10},
                "2": {"duration_sec": 20.8},
            }
        }

    stats = badges.collect_stats(db_path, manifest_reader=manifest_reader)

    assert stats.recitations == 2
    assert stats.riwayat == 3
    assert stats.seconds == 3630
