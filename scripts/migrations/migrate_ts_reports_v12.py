#!/usr/bin/env python3
"""Map positional timestamp reports to exact native v12 targets."""

from __future__ import annotations

import argparse
import gzip
import json
import sqlite3
import sys
from pathlib import Path

import brotli
import orjson

ROOT = Path(__file__).resolve().parents[2]
INSPECTOR = ROOT / "inspector"
for path in (ROOT, INSPECTOR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from qua_shared.timestamps_codec import decode_document  # noqa: E402
from services.db.migrate import run_migrations  # noqa: E402
from services.ts_reports.ts_target_snapshot import resolve_target  # noqa: E402


class MappingError(ValueError):
    pass


_KINDS = {
    "verse": "verse",
    "word": "word",
    "cell": "column",
    "phoneme": "sound",
    "cell_group": "group",
    "gap": "boundary",
}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("legacy_root", type=Path, help="<root>/<slug>/<chapter>.json.gz")
    parser.add_argument("v12_root", type=Path, help="<root>/<slug>/<chapter>.json.br")
    parser.add_argument("mapping_out", type=Path)
    parser.add_argument("--slug", action="append", default=[])
    parser.add_argument(
        "--apply", action="store_true", help="write mappings and apply migration 0028"
    )
    return parser.parse_args()


def _load_legacy(root: Path, slug: str, chapter: int) -> dict:
    path = root / slug / f"{chapter}.json.gz"
    if not path.is_file():
        raise MappingError(f"missing shard: {path}")
    return orjson.loads(gzip.decompress(path.read_bytes()))


def _load_v12(root: Path, slug: str, chapter: int) -> dict:
    path = root / slug / f"{chapter}.json.br"
    if not path.is_file():
        raise MappingError(f"missing shard: {path}")
    return decode_document(orjson.loads(brotli.decompress(path.read_bytes())))


def _part_has(reading: dict, verse: str) -> bool:
    return any(part["ref"] == verse for part in reading["parts"])


def _word(reading: dict, ref: str) -> dict | None:
    return next((row for row in reading["analysis"]["result"]["words"] if row["ref"] == ref), None)


def _owner(reading: dict, word_id: int) -> dict:
    return next(row for row in reading["cells"]["cell_view"]["words"] if row["word_id"] == word_id)


def _written(text: str) -> str:
    return "".join(char for char in text if char not in "ـّۣ۪ۜ۫۬")


def _recut_units(reading: dict, word: dict, stored: list) -> list[set[int]]:
    units = [
        row
        for row in reading["source"]["source"]["units"]
        if row["word_id"] == word["id"] and row["kind"] == "letter"
    ]
    out: list[set[int]] = []
    at = 0
    for old in stored[3]:
        wanted, seen, ids = _written(old[0]), "", set()
        while seen != wanted and at < len(units):
            piece = _written(units[at]["text"])
            if not piece or not wanted.startswith(seen + piece):
                break
            seen += piece
            ids.add(int(units[at]["id"]))
            at += 1
        if seen != wanted:
            raise MappingError(f"letter recut failed at {word['ref']}")
        out.append(ids)
    if at != len(units):
        raise MappingError(f"letter recut left units at {word['ref']}")
    return out


def _column_sound_sets(owner: dict) -> dict[int, list[set[int]]]:
    out = {}
    for column in owner["columns"]:
        sets = [
            set(map(int, column["owned_sound_ids"])),
            set(map(int, column["presented_sound_ids"])),
        ]
        out[int(column["id"])] = [sound_set for sound_set in sets if sound_set]
    return out


def _mapped_column(reading: dict, word: dict, stored: list, cell_index: int) -> dict:
    cells = stored[5] if len(stored) > 5 else []
    if not 0 <= cell_index < len(cells):
        raise MappingError(f"cell {cell_index} absent at {word['ref']}")
    old = cells[cell_index]
    owner = _owner(reading, int(word["id"]))
    sounds = {int(word["sound_ids"][index]) for index in old[3]}
    unit_sets = _recut_units(reading, word, stored)
    letter_index = int(old[4])
    units = unit_sets[letter_index] if 0 <= letter_index < len(unit_sets) else set()
    by_column = _column_sound_sets(owner)
    role = str(old[1])
    allowed = {
        "base": {"letter"},
        "madd": {"letter", "carrier", "madd"},
        "haraka": {"letter", "haraka", "sukun"},
        "tanween": {"tanween"},
    }.get(role, {role})
    matches = []
    for column in owner["columns"]:
        column_id = int(column["id"])
        sound_match = bool(sounds) and sounds in by_column[column_id]
        unit_match = bool(units & set(map(int, column["source_unit_ids"])))
        text_match = not old[0] or _written(str(old[0])) in _written(str(column["text"]))
        if (sound_match or unit_match) and column["role"] in allowed and text_match:
            matches.append(column)
    if len(matches) != 1:
        raise MappingError(
            f"cell {word['ref']}:{cell_index} resolved {len(matches)} native columns"
        )
    return matches[0]


def _target_for(row: sqlite3.Row, reading: dict, word: dict | None, stored: list | None) -> dict:
    old_kind = str(row["target_kind"])
    kind = _KINDS.get(old_kind)
    if kind is None:
        raise MappingError(f"unsupported target kind {old_kind!r}")
    if kind == "verse":
        target_id = row["verse_key"]
    elif word is None:
        raise MappingError(f"{old_kind} target has no word")
    elif kind == "word":
        target_id = word["id"]
    elif kind == "boundary":
        target_id = word["after_boundary_id"]
    elif kind == "sound":
        index = int(row["phoneme_flat_index"])
        if not 0 <= index < len(word["sound_ids"]):
            raise MappingError(f"sound index {index} absent at {word['ref']}")
        target_id = word["sound_ids"][index]
    else:
        if stored is None:
            raise MappingError(f"{old_kind} target has no legacy word")
        column = _mapped_column(reading, word, stored, int(row["cell_index"]))
        if kind == "column":
            target_id = column["id"]
        else:
            groups = [
                g
                for g in _owner(reading, int(word["id"]))["groups"]
                if column["id"] in g["column_ids"]
            ]
            if len(groups) != 1:
                raise MappingError(f"column {column['id']} belongs to {len(groups)} groups")
            target_id = ":".join(map(str, groups[0]["column_ids"]))
    return {"reading_id": reading["id"], "kind": kind, "target_id": str(target_id)}


def _occasions(legacy: dict) -> list[list[dict]]:
    out: list[list[dict]] = []
    for segment in sorted(legacy["segments"], key=lambda row: row["t"][0]):
        if out and out[-1][-1]["ref"] == segment["ref"]:
            out[-1].append(segment)
        else:
            out.append([segment])
    return out


def _word_candidates(row: sqlite3.Row, legacy: dict, new: dict) -> list[tuple[dict, dict, list]]:
    position = int(row["word_index"])
    out = []
    for occasion in _occasions(legacy):
        if occasion[0]["ref"] != row["verse_key"]:
            continue
        flattened = [
            (segment, index, stored)
            for segment in occasion
            for index, stored in enumerate(segment["words"])
        ]
        if not 0 <= position < len(flattened):
            continue
        segment, index, stored = flattened[position]
        for reading in new["readings"]:
            part = next(
                (
                    one
                    for one in reading["parts"]
                    if one["ref"] == segment["ref"] and one["t"] == segment["t"]
                ),
                None,
            )
            if part is None or index >= len(part["word_ids"]):
                continue
            word_id = part["word_ids"][index]
            word = next(
                one for one in reading["analysis"]["result"]["words"] if one["id"] == word_id
            )
            out.append((reading, word, stored))
    return out


def _map_one(row: sqlite3.Row, legacy: dict, new: dict) -> dict:
    candidates = []
    if row["word_index"] is None:
        sources = [
            (reading, None, None)
            for reading in new["readings"]
            if _part_has(reading, row["verse_key"])
        ]
    else:
        sources = _word_candidates(row, legacy, new)
    for reading, word, stored in sources:
        try:
            target = _target_for(row, reading, word, stored)
            snapshot = resolve_target(new, row["verse_key"], target)
            if snapshot is not None:
                candidates.append((target, snapshot))
        except MappingError:
            continue
    timed = [candidate for candidate in candidates if _same_span(row, candidate[1])]
    if timed:
        candidates = timed
    if len(candidates) != 1:
        raise MappingError(f"report {row['id']} resolved {len(candidates)} native targets")
    target, snapshot = candidates[0]
    suffix = str(row["subtype"] or "") if row["category"] == "tajweed" else ""
    target_key = ":".join([target["reading_id"], target["kind"], target["target_id"], suffix])
    return {
        "report_id": row["id"],
        "target": target,
        "target_key": target_key,
        "snapshot": snapshot,
    }


def _ms(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int | str):
        return int(value)
    raise MappingError(f"invalid millisecond value {value!r}")


def _same_span(row: sqlite3.Row, snapshot: dict) -> bool:
    timing = snapshot.get("timing") or {}
    old_start, old_end = _ms(row["snap_onset_ms"]), _ms(row["snap_offset_ms"])
    new_start, new_end = _ms(timing.get("start_ms")), _ms(timing.get("end_ms"))
    if old_start is None or old_end is None or new_start is None or new_end is None:
        return False
    if old_start == old_end or new_start == new_end:
        return old_start == new_start and old_end == new_end
    return max(old_start, new_start) < min(old_end, new_end)


def _map_rows(
    conn: sqlite3.Connection, legacy_root: Path, v12_root: Path, slugs: set[str]
) -> tuple[list[dict], list[dict]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM ts_reports ORDER BY id").fetchall()
    if slugs:
        rows = [row for row in rows if row["slug"] in slugs]
    cache: dict[tuple[str, int], tuple[dict, dict]] = {}
    out, errors = [], []
    for row in rows:
        try:
            key = (row["slug"], int(row["chapter"]))
            if key not in cache:
                cache[key] = (_load_legacy(legacy_root, *key), _load_v12(v12_root, *key))
            out.append(_map_one(row, *cache[key]))
        except MappingError as error:
            errors.append({"report_id": row["id"], "error": str(error)})
    return out, errors


def _apply(conn: sqlite3.Connection, mappings: list[dict], expected: int) -> None:
    if len(mappings) != expected:
        raise MappingError(f"refusing partial apply: mapped {len(mappings)} of {expected}")
    conn.execute(
        "CREATE TABLE ts_report_v12_map (report_id INTEGER PRIMARY KEY, reading_id TEXT NOT NULL, "
        "target_kind TEXT NOT NULL, target_id TEXT NOT NULL, target_key TEXT NOT NULL, snapshot_json TEXT NOT NULL)"
    )
    conn.executemany(
        "INSERT INTO ts_report_v12_map VALUES (?,?,?,?,?,?)",
        [
            (
                m["report_id"],
                m["target"]["reading_id"],
                m["target"]["kind"],
                m["target"]["target_id"],
                m["target_key"],
                json.dumps(m["snapshot"], separators=(",", ":")),
            )
            for m in mappings
        ],
    )
    conn.commit()
    run_migrations(conn)


def main() -> int:
    args = _args()
    conn = sqlite3.connect(args.database)
    conn.row_factory = sqlite3.Row
    mappings, errors = _map_rows(conn, args.legacy_root, args.v12_root, set(args.slug))
    payload = {
        "status": "ok" if not errors else "blocked",
        "mapped": len(mappings),
        "unresolved": len(errors),
        "errors": errors,
        "mappings": mappings,
    }
    args.mapping_out.parent.mkdir(parents=True, exist_ok=True)
    args.mapping_out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if args.apply:
        if errors:
            raise MappingError(f"refusing apply with {len(errors)} unresolved reports")
        total = conn.execute("SELECT COUNT(*) FROM ts_reports").fetchone()[0]
        _apply(conn, mappings, int(total))
    print(
        json.dumps(
            {
                "status": payload["status"],
                "mapped": len(mappings),
                "unresolved": len(errors),
                "applied": args.apply,
            }
        )
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
