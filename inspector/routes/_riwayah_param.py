"""One reading of the ``?riwayah=`` query parameter, shared by every route.

The HTTP boundary is deliberately strict about which vocabulary it accepts:
the wire carries the **Inspector** slug (``warsh_an_nafi``), the same value the
``riwayahs.slug`` column and the catalog hold, and it is resolved here to the
SDK slug the services speak. Readers of stored state may be tolerant of both
(see ``qua_shared.riwayat.resolve_sdk_slug``); a request may not, or the two
vocabularies quietly interleave and a mismatch stops being detectable.
"""

from __future__ import annotations

from flask import abort

from qua_shared.riwayat import DEFAULT_RIWAYAH, UnsupportedRiwayah, to_sdk_slug


def sdk_riwayah_param(value: str | None) -> str:
    """Resolve an Inspector riwayah slug to its SDK slug, or 400.

    An absent param means Hafs, which keeps every unparameterised request
    working unchanged. An unrecognised one is a 400 rather than a silent Hafs
    fallback — serving one edition's data under another's name renders
    plausible text against the wrong coordinates, which a reviewer would then
    save.
    """
    try:
        return to_sdk_slug(value or DEFAULT_RIWAYAH)
    except UnsupportedRiwayah as exc:
        abort(400, str(exc))
