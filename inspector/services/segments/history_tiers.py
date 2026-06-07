"""Timestamp-generation boundary timeline for the Segments history "tier" view.

The history panel partitions edit batches into tiers split by each TS
generation: initial edits, edits after generation #1, after #2, …, and the
current tier (edits since the latest generation — the ones a regeneration would
fold in). This module returns the boundary list; the FE assigns each batch to a
tier by comparing its ``saved_at_utc`` to the boundaries and highlights the
current-tier batches that are timestamp-affecting (see
``qua_shared.segment_edit_ops``).

A generation is marked ``published`` when an HF publish landed in its interval
(at/after it, before the next generation) — a marker overlaid on the timeline.
"""

from __future__ import annotations

from services.db import repo_releases


def generation_timeline(slug: str) -> list[dict]:
    """Ascending TS-generation boundaries for ``slug``.

    Each entry: ``{version, produced_at, published, published_at}``. Empty when
    the reciter has never had timestamps generated.
    """
    gens = repo_releases.all_releases_for_track_slug("ts", slug)
    publishes = [
        r["produced_at"]
        for r in repo_releases.all_releases_for_track_slug("hf", slug)
        if r.get("produced_at")
    ]

    out: list[dict] = []
    for i, g in enumerate(gens):
        start = g.get("produced_at")
        end = gens[i + 1].get("produced_at") if i + 1 < len(gens) else None
        published_at: str | None = None
        for p in publishes:
            if start and p >= start and (end is None or p < end):
                published_at = p if published_at is None else min(published_at, p)
        out.append(
            {
                "version": g.get("version"),
                "produced_at": start,
                "published": published_at is not None,
                "published_at": published_at,
            }
        )
    return out
