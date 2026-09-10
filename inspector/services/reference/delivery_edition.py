"""Which edition a delivery is recited in — the one answer everything asks.

Validation, save, stamping, the Segments payload and the Timestamps producer all
need the same fact: for delivery ``<slug>``, whose script, coordinates, verse
counts and stop signs apply? Resolving it in one place keeps them from
disagreeing, which would show up as a segment saved against one edition's refs
and validated against another's.

**The catalog is the authority.** ``deliveries.riwayah`` is what an admin sets at
intake and what every downstream consumer (releases, the HF dataset, the request
form) keys on. ``detailed.json``'s ``_meta.riwayah`` is the offline pipeline's
record of what it *aligned* against — evidence, not authority. When the two
disagree the delivery is genuinely broken (a row edited after alignment, or a
file copied between deliveries), so :func:`sdk_riwayah_for` raises rather than
picking a side.
"""

from __future__ import annotations

import logging

from qua_shared.riwayat import DEFAULT_RIWAYAH, UnsupportedRiwayah, resolve_sdk_slug

log = logging.getLogger("inspector")


class RiwayahMismatch(ValueError):
    """The catalog row and ``detailed.json`` name different riwayat."""


def inspector_riwayah_for(slug: str) -> str:
    """The delivery's Inspector riwayah slug.

    Falls back to Hafs only when the catalog has no row for ``slug`` at all —
    a fixture, a test double, or a bucket folder with no delivery — because
    everything predating multi-riwayah support is Hafs by construction.
    """
    from services.state import catalog as catalog_service

    delivery = catalog_service.find_delivery(slug)
    return delivery.riwayah if delivery is not None else DEFAULT_RIWAYAH


def sdk_riwayah_for(slug: str) -> str:
    """The delivery's SDK riwayah slug, cross-checked against ``detailed.json``.

    Raises :class:`UnsupportedRiwayah` for a riwayah outside the supported four
    and :class:`RiwayahMismatch` when the alignment on disk was made against a
    different edition than the catalog now claims. Both are loud on purpose:
    rendering or timing a delivery under the wrong edition silently produces
    text that looks plausible and refs that are wrong.
    """
    # ``resolve_sdk_slug`` rather than the strict ``to_sdk_slug``: the column is
    # free text with an FK to ``riwayahs.slug``, and while the deployed
    # vocabulary uses the long form (``hafs_an_asim``), fixtures and older rows
    # carry the short one. This is a read of existing state, not an HTTP
    # boundary, so accepting both is right; a writer stays strict.
    catalog_slug = inspector_riwayah_for(slug)
    sdk_slug = resolve_sdk_slug(catalog_slug)

    # Via ``data_loader`` rather than the cache: a direct cache read answers
    # "no meta" on a cold process and would skip the cross-check entirely.
    from services.storage import data_loader

    aligned = (data_loader.seg_meta(slug) or {}).get("riwayah")
    if aligned:
        try:
            aligned_sdk = resolve_sdk_slug(aligned)
        except UnsupportedRiwayah:
            raise RiwayahMismatch(
                f"{slug}: detailed.json was aligned against unsupported riwayah {aligned!r}"
            ) from None
        if aligned_sdk != sdk_slug:
            raise RiwayahMismatch(
                f"{slug}: catalog says {catalog_slug!r} but detailed.json was "
                f"aligned against {aligned!r}"
            )
    return sdk_slug
