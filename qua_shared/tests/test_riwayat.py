"""The supported-riwayah table and its two slug spaces."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from qua_shared.riwayat import (
    DEFAULT_RIWAYAH,
    DEFAULT_SDK_RIWAYAH,
    SUPPORTED_RIWAYAT,
    UnsupportedRiwayah,
    from_sdk_slug,
    is_hafs,
    is_supported,
    to_sdk_slug,
)
from qua_shared.schemas.config.riwayat import riwayat_config

REPO = Path(__file__).resolve().parents[2]
FE_RIWAYAT = REPO / "inspector" / "frontend" / "src" / "lib" / "riwayat.ts"


def test_table_is_the_four_supported_riwayat():
    assert SUPPORTED_RIWAYAT == {
        "hafs_an_asim": "hafs",
        "warsh_an_nafi": "warsh",
        "qalon_an_nafi": "qalun",
        "shubah_an_asim": "shuba",
    }
    assert DEFAULT_RIWAYAH in SUPPORTED_RIWAYAT
    assert SUPPORTED_RIWAYAT[DEFAULT_RIWAYAH] == DEFAULT_SDK_RIWAYAH


def test_round_trip_both_directions():
    for inspector, sdk in SUPPORTED_RIWAYAT.items():
        assert to_sdk_slug(inspector) == sdk
        assert from_sdk_slug(sdk) == inspector


@pytest.mark.parametrize("bad", [None, "", "duri_abu_amr", "qalun", "shuba", "HAFS_AN_ASIM"])
def test_unsupported_raises_rather_than_defaulting(bad):
    """Never silently fall back to Hafs — that renders one edition under another's script."""
    with pytest.raises(UnsupportedRiwayah):
        to_sdk_slug(bad)
    assert not is_supported(bad)


def test_is_hafs_only_for_hafs():
    assert is_hafs("hafs_an_asim")
    assert not is_hafs("warsh_an_nafi")
    assert not is_hafs(None)
    # The SDK spelling is a different slug space and must not match.
    assert not is_hafs("hafs")


def test_config_projection_matches_the_table():
    config = riwayat_config()
    assert [(r.inspector_slug, r.sdk_slug) for r in config.supported] == list(
        SUPPORTED_RIWAYAT.items()
    )
    assert config.default_inspector_slug == DEFAULT_RIWAYAH
    assert config.default_sdk_slug == DEFAULT_SDK_RIWAYAH


def test_frontend_mirror_matches_the_backend_table():
    """`lib/riwayat.ts` mirrors the table at runtime; TS only enforces the keys.

    `Record<InspectorRiwayah, SdkRiwayah>` makes a missing or extra key a
    compile error, but a *wrong value* (``qalon_an_nafi: 'shuba'``) still
    typechecks. This closes that hole.
    """
    source = FE_RIWAYAT.read_text(encoding="utf-8")
    body = re.search(
        r"SUPPORTED_RIWAYAT:\s*Record<InspectorRiwayah,\s*SdkRiwayah>\s*=\s*\{(.*?)\};",
        source,
        re.DOTALL,
    )
    assert body, "could not locate SUPPORTED_RIWAYAT in lib/riwayat.ts"
    mirrored = dict(re.findall(r"(\w+):\s*'([a-z]+)'", body.group(1)))
    assert mirrored == SUPPORTED_RIWAYAT

    assert f"DEFAULT_RIWAYAH: InspectorRiwayah = '{DEFAULT_RIWAYAH}'" in source
    assert f"DEFAULT_SDK_RIWAYAH: SdkRiwayah = '{DEFAULT_SDK_RIWAYAH}'" in source


def test_agrees_with_qua_domain_when_installed():
    """The explicit table exists because ``normalize_riwayah`` rejects two of our
    slugs today (``qalon_an_nafi``, ``shubah_an_asim``). Once the upstream alias
    fix lands, the two must agree — this test is what catches a later divergence.
    """
    qua_domain = pytest.importorskip("qua_domain")
    normalize = qua_domain.normalize_riwayah
    for inspector, sdk in SUPPORTED_RIWAYAT.items():
        try:
            resolved = normalize(inspector)
        except ValueError:  # pragma: no cover - upstream alias fix not yet released
            pytest.skip(f"qua_domain does not yet alias {inspector!r}")
        assert resolved == sdk


def test_generated_fe_types_carry_both_slug_unions():
    """The FE type aliases are derived from `RiwayahSupport`; codegen must emit it."""
    generated = (
        REPO / "inspector" / "frontend" / "src" / "lib" / "types" / "generated" / "schemas.ts"
    ).read_text(encoding="utf-8")
    assert "export interface RiwayahSupport {" in generated
    for inspector, sdk in SUPPORTED_RIWAYAT.items():
        assert json.dumps(inspector) in generated
        assert json.dumps(sdk) in generated
