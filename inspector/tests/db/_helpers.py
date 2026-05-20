"""Seed helpers for SQLite-substrate tests."""

from __future__ import annotations

from services import db


def seed_user(hf: str, login: str | None = None) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(hf_user_id, login_cache) VALUES (?,?)",
            (hf, login),
        )


def _seed_vocab(conn) -> None:
    conn.execute("INSERT OR IGNORE INTO reciters(reciter_id,name_en) VALUES ('r','R')")
    conn.execute("INSERT OR IGNORE INTO riwayahs(slug,short,name) VALUES ('hafs','h','Hafs')")
    conn.execute("INSERT OR IGNORE INTO styles(slug,short,name) VALUES ('mur','m','Mur')")
    conn.execute("INSERT OR IGNORE INTO sources(slug,name) VALUES ('src','Src')")
    conn.execute("INSERT OR IGNORE INTO channels(slug,short,name) VALUES ('ch','c','Ch')")


def seed_delivery(slug: str = "d1", reciter_id: str = "r") -> None:
    with db.transaction() as conn:
        _seed_vocab(conn)
        conn.execute(
            "INSERT INTO deliveries(slug, reciter_id, riwayah, style, source, channel,"
            " audio_category, chapter_count, added_at, added_by_hf_id) VALUES "
            "(?,?,'hafs','mur','src','ch','by_surah',114,'2026-01-01T00:00:00Z','sys')",
            (slug, reciter_id),
        )
