"""Repository for the catalog tables → ``ReciterCatalog`` read model.

Assembles vocab + reciters + deliveries + aliases + persisted ``derived`` +
``generated_at`` so ``snapshot()`` round-trips byte-for-byte through the
migration parity gate (full ``model_dump(by_alias=True)`` diff). Edit helpers
mirror the catalog service mutation surface used by the accept flow.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scripts.lib.schemas import (
    Channel,
    Delivery,
    ReciterCatalog,
    ReciterEntry,
    Riwayah,
    RecordingContext,
    Source,
    Style,
    Vocab,
)
from scripts.lib.schemas.catalog import Alias, Derived

from . import _serde
from .connection import get_conn
from .errors import Duplicate

# reciter columns a caller may edit.
_RECITER_WRITABLE = ("name_en", "name_ar", "country", "notes")

# delivery columns a caller may edit, mapped to a serializer.
_DELIVERY_WRITABLE: dict[str, Any] = {
    "riwayah": lambda v: v,
    "style": lambda v: v,
    "recording_context": lambda v: v,
    "recording_year": lambda v: v,
    "variant_label": lambda v: v,
    "source": lambda v: v,
    "channel": lambda v: v,
    "audio_category": lambda v: v.value if hasattr(v, "value") else v,
    "chapter_count": lambda v: v,
    "codec": lambda v: v,
    "container": lambda v: v,
    "sample_rate_hz": lambda v: v,
    "channels": lambda v: v,
    "bitrate_mode": lambda v: v.value if hasattr(v, "value") else v,
    "bitrate_kbps_nominal": lambda v: v,
    "total_duration_sec": lambda v: v,
}


# ---- assembly ----


def _vocab(conn) -> Vocab:
    riwayat = [
        Riwayah(slug=r["slug"], short=r["short"], name=r["name"])
        for r in conn.execute("SELECT slug, short, name FROM riwayahs ORDER BY slug")
    ]
    styles = [
        Style(slug=r["slug"], short=r["short"], name=r["name"])
        for r in conn.execute("SELECT slug, short, name FROM styles ORDER BY slug")
    ]
    sources = [
        Source(
            slug=r["slug"], name=r["name"], url=r["url"],
            audio_categories=_serde.json_loads(r["audio_categories"]) or [],
        )
        for r in conn.execute(
            "SELECT slug, name, url, audio_categories FROM sources ORDER BY slug"
        )
    ]
    channels = [
        Channel(
            slug=r["slug"], short=r["short"], name=r["name"],
            host_patterns=_serde.json_loads(r["host_patterns"]) or [],
            gh_release_eligible=bool(r["gh_release_eligible"]),
        )
        for r in conn.execute(
            "SELECT slug, short, name, host_patterns, gh_release_eligible "
            "FROM channels ORDER BY slug"
        )
    ]
    contexts = [
        RecordingContext(slug=r["slug"], name=r["name"])
        for r in conn.execute(
            "SELECT slug, name FROM recording_contexts ORDER BY slug"
        )
    ]
    return Vocab(
        riwayat=riwayat, styles=styles, sources=sources, channels=channels,
        recording_contexts=contexts,
    )


def _delivery_from_row(r) -> Delivery:
    return Delivery(
        slug=r["slug"],
        reciter_id=r["reciter_id"],
        riwayah=r["riwayah"],
        style=r["style"],
        recording_context=r["recording_context"],
        recording_year=r["recording_year"],
        variant_label=r["variant_label"],
        source=r["source"],
        channel=r["channel"],
        audio_category=r["audio_category"],
        chapter_count=r["chapter_count"],
        codec=r["codec"],
        container=r["container"],
        sample_rate_hz=r["sample_rate_hz"],
        channels=r["channels"],
        bitrate_mode=r["bitrate_mode"],
        bitrate_kbps_nominal=r["bitrate_kbps_nominal"],
        total_duration_sec=r["total_duration_sec"],
        added_at=_serde.from_iso(r["added_at"]),
        added_by_hf_id=r["added_by_hf_id"],
    )


def snapshot() -> ReciterCatalog:
    conn = get_conn()
    meta = conn.execute(
        "SELECT schema_version, generated_at, derived FROM catalog_meta WHERE id = 1"
    ).fetchone()
    reciters = [
        ReciterEntry(
            reciter_id=r["reciter_id"], name_en=r["name_en"], name_ar=r["name_ar"],
            country=r["country"], notes=r["notes"],
        )
        for r in conn.execute(
            "SELECT reciter_id, name_en, name_ar, country, notes FROM reciters ORDER BY reciter_id"
        )
    ]
    deliveries = [
        _delivery_from_row(r)
        for r in conn.execute("SELECT * FROM deliveries ORDER BY slug")
    ]
    aliases = [
        Alias(kind=r["kind"], old=r["old"], new=r["new"], ts=_serde.from_iso(r["ts"]))
        for r in conn.execute(
            "SELECT kind, old, new, ts FROM catalog_aliases ORDER BY id"
        )
    ]
    derived = Derived.model_validate(_serde.json_loads(meta["derived"]) or {"source_channels": []})
    return ReciterCatalog(
        schema_version=meta["schema_version"],
        generated_at=_serde.from_iso(meta["generated_at"]),
        vocab=_vocab(conn),
        reciters=reciters,
        deliveries=deliveries,
        aliases=aliases,
        derived=derived,
    )


# ---- finds ----


def find_reciter(reciter_id: str) -> ReciterEntry | None:
    r = get_conn().execute(
        "SELECT reciter_id, name_en, name_ar, country, notes FROM reciters WHERE reciter_id = ?",
        (reciter_id,),
    ).fetchone()
    if r is None:
        return None
    return ReciterEntry(
        reciter_id=r["reciter_id"], name_en=r["name_en"], name_ar=r["name_ar"],
        country=r["country"], notes=r["notes"],
    )


def find_delivery(slug: str) -> Delivery | None:
    r = get_conn().execute("SELECT * FROM deliveries WHERE slug = ?", (slug,)).fetchone()
    return _delivery_from_row(r) if r else None


# ---- mutations (caller owns the transaction) ----


def edit_reciter(reciter_id: str, **fields) -> ReciterEntry | None:
    cols = {k: v for k, v in fields.items() if k in _RECITER_WRITABLE and v is not None}
    if cols:
        sets = ", ".join(f"{k} = ?" for k in cols)
        get_conn().execute(
            f"UPDATE reciters SET {sets} WHERE reciter_id = ?",
            [*cols.values(), reciter_id],
        )
    return find_reciter(reciter_id)


def edit_delivery(slug: str, **fields) -> Delivery | None:
    cols: dict[str, Any] = {}
    for k, v in fields.items():
        if k in _DELIVERY_WRITABLE and v is not None:
            cols[k] = _DELIVERY_WRITABLE[k](v)
    if cols:
        sets = ", ".join(f"{k} = ?" for k in cols)
        get_conn().execute(
            f"UPDATE deliveries SET {sets} WHERE slug = ?", [*cols.values(), slug]
        )
    return find_delivery(slug)


# ---- bulk inserts (migration + add endpoints) ----


def insert_reciter(entry: ReciterEntry) -> None:
    get_conn().execute(
        "INSERT INTO reciters(reciter_id, name_en, name_ar, country, notes) VALUES (?,?,?,?,?)",
        (entry.reciter_id, entry.name_en, entry.name_ar, entry.country, entry.notes),
    )


def insert_delivery(d: Delivery) -> None:
    get_conn().execute(
        "INSERT INTO deliveries(slug, reciter_id, riwayah, style, source, channel, "
        "recording_context, recording_year, variant_label, audio_category, chapter_count, "
        "codec, container, sample_rate_hz, channels, bitrate_mode, bitrate_kbps_nominal, "
        "total_duration_sec, added_at, added_by_hf_id) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            d.slug, d.reciter_id, d.riwayah, d.style, d.source, d.channel,
            d.recording_context, d.recording_year, d.variant_label,
            d.audio_category.value if hasattr(d.audio_category, "value") else d.audio_category,
            d.chapter_count, d.codec, d.container, d.sample_rate_hz, d.channels,
            d.bitrate_mode.value if hasattr(d.bitrate_mode, "value") else d.bitrate_mode,
            d.bitrate_kbps_nominal, d.total_duration_sec,
            _serde.to_iso(d.added_at), d.added_by_hf_id,
        ),
    )


def load_vocab(vocab: Vocab) -> None:
    conn = get_conn()
    for r in vocab.riwayat:
        conn.execute("INSERT OR IGNORE INTO riwayahs(slug,short,name) VALUES (?,?,?)",
                     (r.slug, r.short, r.name))
    for s in vocab.styles:
        conn.execute("INSERT OR IGNORE INTO styles(slug,short,name) VALUES (?,?,?)",
                     (s.slug, s.short, s.name))
    for s in vocab.sources:
        conn.execute(
            "INSERT OR IGNORE INTO sources(slug,name,url,audio_categories) VALUES (?,?,?,?)",
            (s.slug, s.name, s.url,
             _serde.json_dumps([c.value if hasattr(c, "value") else c for c in s.audio_categories])),
        )
    for c in vocab.channels:
        conn.execute(
            "INSERT OR IGNORE INTO channels(slug,short,name,host_patterns,gh_release_eligible) "
            "VALUES (?,?,?,?,?)",
            (
                c.slug, c.short, c.name,
                _serde.json_dumps(list(c.host_patterns)),
                int(c.gh_release_eligible),
            ),
        )
    for rc in vocab.recording_contexts:
        conn.execute("INSERT OR IGNORE INTO recording_contexts(slug,name) VALUES (?,?)",
                     (rc.slug, rc.name))


def add_reciter(entry: ReciterEntry) -> ReciterEntry:
    """Add a reciter, raising ``Duplicate`` on an existing id (vs the raw
    IntegrityError from ``insert_reciter``) to preserve the service's contract."""
    if find_reciter(entry.reciter_id) is not None:
        raise Duplicate(f"reciter_id {entry.reciter_id!r} already exists")
    insert_reciter(entry)
    return entry


def add_delivery(d: Delivery) -> Delivery:
    """Add a delivery, raising ``Duplicate`` on an existing slug, and refresh
    the persisted ``derived.source_channels`` rollup."""
    if find_delivery(d.slug) is not None:
        raise Duplicate(f"delivery slug {d.slug!r} already exists")
    insert_delivery(d)
    refresh_derived()
    return d


def find_source(slug: str) -> Source | None:
    r = get_conn().execute(
        "SELECT slug, name, url, audio_categories FROM sources WHERE slug = ?", (slug,)
    ).fetchone()
    if r is None:
        return None
    return Source(
        slug=r["slug"], name=r["name"], url=r["url"],
        audio_categories=_serde.json_loads(r["audio_categories"]) or [],
    )


def add_source(source: Source) -> Source:
    """Append a vocab source, raising ``Duplicate`` on an existing slug."""
    if find_source(source.slug) is not None:
        raise Duplicate(f"source {source.slug!r} already exists")
    get_conn().execute(
        "INSERT INTO sources(slug, name, url, audio_categories) VALUES (?,?,?,?)",
        (
            source.slug, source.name, source.url,
            _serde.json_dumps(
                [c.value if hasattr(c, "value") else c for c in source.audio_categories]
            ),
        ),
    )
    return source


def find_channel(slug: str) -> Channel | None:
    r = get_conn().execute(
        "SELECT slug, short, name, host_patterns, gh_release_eligible "
        "FROM channels WHERE slug = ?", (slug,)
    ).fetchone()
    if r is None:
        return None
    return Channel(
        slug=r["slug"], short=r["short"], name=r["name"],
        host_patterns=_serde.json_loads(r["host_patterns"]) or [],
        gh_release_eligible=bool(r["gh_release_eligible"]),
    )


def add_channel(channel: Channel) -> Channel:
    """Append a vocab channel, raising ``Duplicate`` on an existing slug."""
    if find_channel(channel.slug) is not None:
        raise Duplicate(f"channel {channel.slug!r} already exists")
    get_conn().execute(
        "INSERT INTO channels(slug, short, name, host_patterns, gh_release_eligible) "
        "VALUES (?,?,?,?,?)",
        (
            channel.slug, channel.short, channel.name,
            _serde.json_dumps(list(channel.host_patterns)),
            int(channel.gh_release_eligible),
        ),
    )
    return channel


def refresh_derived() -> None:
    """Recompute + persist ``derived.source_channels`` from the deliveries.

    Called whenever the delivery set changes. The migration persists the
    source catalog's derived verbatim (parity); this keeps it correct after
    inspector-side adds. Deterministic order (source, channel)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT source, channel, COUNT(*) AS c FROM deliveries "
        "GROUP BY source, channel ORDER BY source, channel"
    ).fetchall()
    derived = {
        "source_channels": [
            {"source": r["source"], "channel": r["channel"], "delivery_count": r["c"]}
            for r in rows
        ]
    }
    conn.execute(
        "UPDATE catalog_meta SET derived = ? WHERE id = 1", (_serde.json_dumps(derived),)
    )


def insert_alias(alias: Alias) -> None:
    get_conn().execute(
        "INSERT INTO catalog_aliases(kind, old, new, ts) VALUES (?,?,?,?)",
        (alias.kind, alias.old, alias.new, _serde.to_iso(alias.ts)),
    )


def set_meta(*, generated_at: datetime | None, derived: Derived | dict | None) -> None:
    if derived is None:
        derived_json = '{"source_channels": []}'
    elif hasattr(derived, "model_dump"):
        derived_json = _serde.json_dumps(derived.model_dump(mode="json"))
    else:
        derived_json = _serde.json_dumps(derived)
    get_conn().execute(
        "UPDATE catalog_meta SET generated_at = ?, derived = ? WHERE id = 1",
        (_serde.to_iso(generated_at), derived_json),
    )
