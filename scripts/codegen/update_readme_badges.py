#!/usr/bin/env python3
"""Refresh README stats badges from the production Inspector bucket."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

PROD_BUCKET_ID = "hetchyy/quranic-inspector-bucket"
DB_BUCKET_PATH = "db/inspector.db"
DEFAULT_README = Path(__file__).resolve().parents[2] / "README.md"

START_MARKER = "  <!-- stats-badges:start -->"
END_MARKER = "  <!-- stats-badges:end -->"


@dataclass(frozen=True)
class BadgeStats:
    recitations: int
    riwayat: int
    seconds: int


def format_hours(seconds: int) -> str:
    hours = max(0, int(seconds // 3600))
    floored = (hours // 50) * 50
    return f"{floored:,}h+"


def badge_url(label: str, value: str, color: str) -> str:
    return f"https://img.shields.io/badge/{quote(label, safe='')}-{quote(value, safe='')}-{color}"


def _bucket_uri(bucket_id: str, path: str) -> str:
    return f"buckets/{bucket_id}/{path}"


def read_bucket_bytes(bucket_id: str, path: str, *, token: str | None = None) -> bytes:
    if token:
        os.environ.setdefault("HF_TOKEN", token)
    from huggingface_hub import hffs  # type: ignore[import-not-found]

    return hffs.cat_file(_bucket_uri(bucket_id, path))


def download_db(bucket_id: str, *, token: str | None = None) -> Path:
    data = read_bucket_bytes(bucket_id, DB_BUCKET_PATH, token=token)
    fd, tmp = tempfile.mkstemp(prefix="inspector-badges-", suffix=".db")
    os.close(fd)
    path = Path(tmp)
    path.write_bytes(data)
    return path


def _duration_from_manifest(doc: dict, slug: str) -> int:
    chapters = doc.get("chapters")
    if not isinstance(chapters, dict) or not chapters:
        raise RuntimeError(f"{slug}: audio manifest has no chapters")

    total = 0.0
    missing: list[str] = []
    for chapter, entry in chapters.items():
        if not isinstance(entry, dict):
            missing.append(str(chapter))
            continue
        value = entry.get("duration_sec")
        if value is None:
            missing.append(str(chapter))
            continue
        total += float(value)

    if missing:
        sample = ", ".join(missing[:8])
        suffix = "..." if len(missing) > 8 else ""
        raise RuntimeError(
            f"{slug}: missing duration_sec for {len(missing)} chapter(s): {sample}{suffix}"
        )
    return int(total)


def collect_stats(
    db_path: Path,
    *,
    manifest_reader: Callable[[str], dict] | None = None,
) -> BadgeStats:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        published = conn.execute(
            """
            SELECT d.slug, d.total_duration_sec, d.riwayah
            FROM deliveries d
            JOIN delivery_states s ON s.slug = d.slug
            WHERE s.state = 'released'
              AND s.visibility = 'public'
            ORDER BY d.slug
            """
        ).fetchall()
    finally:
        conn.close()

    # Riwayat counts only what's actually available (the released/public set),
    # not every riwayah in the catalog vocab — keeps the README consistent with
    # the HF dataset card, which counts riwayat across its published splits.
    riwayat = len({row["riwayah"] for row in published})

    seconds = 0
    missing_duration: list[str] = []
    for row in published:
        duration = row["total_duration_sec"]
        if duration is not None:
            seconds += int(duration)
            continue
        if manifest_reader is None:
            missing_duration.append(row["slug"])
            continue
        seconds += _duration_from_manifest(manifest_reader(row["slug"]), row["slug"])

    if missing_duration:
        raise RuntimeError(
            "missing total_duration_sec for published recitation(s): " + ", ".join(missing_duration)
        )

    return BadgeStats(recitations=len(published), riwayat=int(riwayat or 0), seconds=seconds)


def render_badges(stats: BadgeStats) -> str:
    recitations = f"{stats.recitations:,}"
    riwayat = f"{stats.riwayat:,}"
    hours = format_hours(stats.seconds)
    lines = [
        START_MARKER,
        "  <br>",
        (
            '  <a href="data/RECITERS.md"><img src="'
            f'{badge_url("Recitations", recitations, "d4842a")}" '
            'alt="Published recitations"></a>'
        ),
        (
            '  <a href="data/RECITERS.md"><img src="'
            f'{badge_url("Riwayat", riwayat, "f0ad4e")}" '
            'alt="Published riwayat"></a>'
        ),
        (
            '  <a href="data/RECITERS.md"><img src="'
            f'{badge_url("Hours", hours, "d4842a")}" '
            'alt="Published audio hours"></a>'
        ),
        END_MARKER,
    ]
    return "\n".join(lines)


def replace_badges(readme: str, badges: str) -> str:
    if START_MARKER in readme and END_MARKER in readme:
        before, rest = readme.split(START_MARKER, 1)
        _, after = rest.split(END_MARKER, 1)
        return before + badges + after

    old_block = """  <!-- <br> -->
  <!-- <a href="data/RECITERS.md"><img src="https://img.shields.io/badge/Unsegmented-832%20reciters%20%C2%B7%2014,320h-d4842a" alt="Unsegmented"></a> -->
  <!-- <a href="data/RECITERS.md"><img src="https://img.shields.io/badge/Riwayat-16%20%2F%2020-f0ad4e" alt="Riwayat"></a> -->
  <!-- <a href="data/RECITERS.md"><img src="https://img.shields.io/badge/Segmented-14%20reciters%20%C2%B7%20336h-d4842a" alt="Segmented"></a> -->"""
    if old_block in readme:
        return readme.replace(old_block, badges)

    raise RuntimeError("README badge block not found")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--bucket-id", default=PROD_BUCKET_ID)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("HF_TOKEN")
    temp_db: Path | None = None
    try:
        db_path = args.db_path
        if db_path is None:
            temp_db = download_db(args.bucket_id, token=token)
            db_path = temp_db

        def manifest_reader(slug: str) -> dict:
            raw = read_bucket_bytes(
                args.bucket_id, f"catalog/audio_manifest/{slug}.json", token=token
            )
            return json.loads(raw)

        stats = collect_stats(db_path, manifest_reader=manifest_reader)
        badges = render_badges(stats)
        print(
            f"recitations={stats.recitations} riwayat={stats.riwayat} "
            f"hours={format_hours(stats.seconds)}"
        )
        print(badges)

        if args.dry_run:
            return 0

        readme = args.readme.read_text(encoding="utf-8")
        updated = replace_badges(readme, badges)
        args.readme.write_text(updated, encoding="utf-8")
        return 0
    finally:
        if temp_db is not None:
            try:
                temp_db.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
