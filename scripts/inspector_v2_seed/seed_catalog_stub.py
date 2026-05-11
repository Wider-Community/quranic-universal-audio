"""Upload a vocab-only stub catalog to ``<bucket>/catalog/reciter_catalog.json``.

Real ``reciters[]`` / ``deliveries[]`` arrive once the bulk audio probe in
``.local/dedup/`` finishes — Phase 1 only seeds the vocab so the catalog
service has a valid file to hydrate from.

Vocab is composed from:
- ``data/riwayat.json`` — riwayat (with ``short`` derived from the slug head)
- ``data/styles.json`` — styles, excluding legacy ``taraweeh`` (migrated to
  ``style=murattal + recording_context=taraweeh``)
- ``data/sources.json`` — sources
- channels: hard-coded canonical six (mp3quran, everyayah, quranicaudio,
  tarteel, archive_org, tvquran) per docs/reference/reciter-catalog.md §2
- recording_contexts: hard-coded canonical five (studio, broadcast, prayer,
  taraweeh, mixed) per reciter-catalog.md §4

Idempotent: overwrites the catalog file each run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ._env import load_repo_env, repo_root

load_repo_env()

from scripts.lib.schemas import (
    AudioCategory,
    Channel,
    ReciterCatalog,
    RecordingContext,
    Riwayah,
    Source,
    Style,
    Vocab,
)
from inspector.services import storage_paths
from inspector.services.hf_bucket import get_backend

# Short forms for styles (used in delivery slugs). Source: reciter-catalog.md §3.
STYLE_SHORTS = {
    "murattal": "murattal",
    "mujawwad": "mujawwad",
    "muallim": "muallim",
    "children_repeat": "children",
    "hadr": "hadr",
}

# Canonical channels (delivery slug + host inference). reciter-catalog.md §2/§3.
CHANNELS = [
    Channel(slug="mp3quran", short="mp3quran", name="mp3quran CDN",
            host_patterns=["server*.mp3quran.net"]),
    Channel(slug="everyayah", short="everyayah", name="everyayah CDN",
            host_patterns=["everyayah.com", "www.everyayah.com"]),
    Channel(slug="quranicaudio", short="qdc", name="quranicaudio / QDC CDN",
            host_patterns=["download.quranicaudio.com",
                           "audio.qurancdn.com",
                           "audio-cdn.tarteel.ai"]),
    Channel(slug="tarteel", short="tarteel", name="tarteel CDN",
            host_patterns=["audio-cdn.tarteel.ai"]),
    Channel(slug="archive_org", short="archive", name="archive.org",
            host_patterns=["*.archive.org"]),
    Channel(slug="tvquran", short="tvquran", name="tvquran",
            host_patterns=["download.tvquran.com", "www.tvquran.com"]),
]

RECORDING_CONTEXTS = [
    RecordingContext(slug="studio", name="Studio recording"),
    RecordingContext(slug="broadcast", name="Radio / TV broadcast"),
    RecordingContext(slug="prayer", name="Live prayer (non-Taraweeh)"),
    RecordingContext(slug="taraweeh", name="Taraweeh prayers (Ramadan night)"),
    RecordingContext(slug="mixed", name="Mixed contexts within one delivery"),
]


def build_vocab() -> Vocab:
    root = repo_root()

    riwayat_raw = json.loads((root / "data" / "riwayat.json").read_text(encoding="utf-8"))
    riwayat = [
        Riwayah(slug=r["slug"], short=r["slug"].split("_", 1)[0], name=r["name"])
        for r in riwayat_raw
    ]

    styles_raw = json.loads((root / "data" / "styles.json").read_text(encoding="utf-8"))
    # Drop the legacy `taraweeh` style — v2 migrates it to murattal + recording_context.
    styles = [
        Style(slug=s["slug"], short=STYLE_SHORTS.get(s["slug"], s["slug"]),
              name=s["name"])
        for s in styles_raw
        if s["slug"] != "taraweeh"
    ]

    sources_raw = json.loads((root / "data" / "sources.json").read_text(encoding="utf-8"))
    sources = [
        Source(
            slug=s["slug"],
            name=s["name"],
            url=s.get("url"),
            audio_categories=[AudioCategory(c) for c in s.get("audio_categories", [])],
        )
        for s in sources_raw
    ]

    return Vocab(
        riwayat=riwayat,
        styles=styles,
        sources=sources,
        channels=CHANNELS,
        recording_contexts=RECORDING_CONTEXTS,
    )


def main() -> int:
    vocab = build_vocab()
    catalog = ReciterCatalog(vocab=vocab)
    # Round-trip validate.
    ReciterCatalog.model_validate(catalog.model_dump(mode="json"))

    backend = get_backend()
    path = storage_paths.catalog_path()
    backend.write_json_atomic(path, catalog.model_dump(mode="json"))
    print(
        f"ok  uploaded vocab-only catalog stub to {path} "
        f"(riwayat={len(vocab.riwayat)}, styles={len(vocab.styles)}, "
        f"sources={len(vocab.sources)}, channels={len(vocab.channels)}, "
        f"recording_contexts={len(vocab.recording_contexts)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
