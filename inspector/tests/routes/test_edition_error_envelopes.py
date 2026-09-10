"""Edition failures must reach the client as a conflict, not a crash.

Only `seg_all` and `seg_config` caught these; `/api/seg/data`, `/api/seg/validate`,
`/api/seg/save` and `/api/seg/undo` all resolve the delivery's edition too and
were returning 500 + an HTML error page, which the FE cannot tell from a fault.
"""

from __future__ import annotations

import pytest

from qua_shared.riwayat import UnsupportedRiwayah
from services.reference.delivery_edition import RiwayahMismatch
from services.reference.editions import EditionsUnavailable


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (RiwayahMismatch("catalog says warsh, disk says qalun"), 409, "RIWAYAH_MISMATCH"),
        (UnsupportedRiwayah("unsupported riwayah: 'duri'"), 409, "UNSUPPORTED_RIWAYAH"),
        (EditionsUnavailable("qua_domain is not installed"), 503, "EDITIONS_UNAVAILABLE"),
    ],
)
def test_an_edition_failure_anywhere_carries_its_code(
    flask_client, tmp_reciter_dir, monkeypatch, exc, status, code
):
    from services.segments import segments_query

    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas")

    def _raise(*_args, **_kwargs):
        raise exc

    monkeypatch.setattr(segments_query, "sdk_riwayah_for", _raise)

    res = flask_client.get(f"/api/seg/data/{reciter}/112")

    assert res.status_code == status
    assert res.get_json()["code"] == code
