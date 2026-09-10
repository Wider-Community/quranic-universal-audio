"""FE-facing projection of the supported-riwayah vocabulary.

The data itself lives in :mod:`qua_shared.riwayat` — this module only gives the
TypeScript codegen a model to walk, so the FE gets the slug unions as *types*
rather than hand-copied string literals. The runtime values are mirrored once in
``inspector/frontend/src/lib/riwayat.ts``, and a parity test asserts the mirror
matches this table (a fifth riwayah therefore fails typecheck, not review).

Not SQLite-backed despite living under ``config/`` — it is configuration in the
same sense ``capabilities.py`` is: a registry the app reads, not a row it writes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Inspector vocabulary slugs (``riwayahs.slug``) for the supported four.
InspectorRiwayah = Literal[
    "hafs_an_asim",
    "warsh_an_nafi",
    "qalon_an_nafi",
    "shubah_an_asim",
]

#: The matching ``qua_domain`` / ``qua_sdk`` slugs.
SdkRiwayah = Literal["hafs", "warsh", "qalun", "shuba"]


class RiwayahSupport(BaseModel):
    """One supported riwayah and its two slug spellings."""

    model_config = ConfigDict(extra="forbid")

    inspector_slug: InspectorRiwayah
    sdk_slug: SdkRiwayah


class RiwayatConfig(BaseModel):
    """The supported-riwayah vocabulary as the FE sees it.

    ``supported`` is ordered product order (the order the aligner app offers).
    Everything outside it is a riwayah the request form still accepts but the
    pipeline cannot yet align.
    """

    model_config = ConfigDict(extra="forbid")

    supported: list[RiwayahSupport] = Field(min_length=1)
    default_inspector_slug: InspectorRiwayah
    default_sdk_slug: SdkRiwayah


def riwayat_config() -> RiwayatConfig:
    """Build the config from the single source of truth in ``qua_shared.riwayat``."""
    from qua_shared.riwayat import (
        DEFAULT_RIWAYAH,
        DEFAULT_SDK_RIWAYAH,
        SUPPORTED_RIWAYAT,
    )

    return RiwayatConfig(
        supported=[
            RiwayahSupport(inspector_slug=inspector, sdk_slug=sdk)  # type: ignore[arg-type]
            for inspector, sdk in SUPPORTED_RIWAYAT.items()
        ],
        default_inspector_slug=DEFAULT_RIWAYAH,  # type: ignore[arg-type]
        default_sdk_slug=DEFAULT_SDK_RIWAYAH,  # type: ignore[arg-type]
    )


__all__ = [
    "InspectorRiwayah",
    "RiwayahSupport",
    "RiwayatConfig",
    "SdkRiwayah",
    "riwayat_config",
]
