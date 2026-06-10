"""``/api/seg/reciters`` lifecycle-literal parity.

``SegReciterState`` / ``SegReciterVisibility`` (wire) are hand-mirrored
``Literal``s of the canonical SQLite-backed ``ReciterState`` / ``Visibility``
enums. The Segments tab lists WIP reciters, so the route emits every state's
``.value``; if the wire Literal is narrower than the enum, ``SegRecitersResponse``
raises and the reciter list 500s (regression seen on the dev Space for
``catalogued`` / ``awaiting_alignment`` rows). These tests fail the moment the
mirror drifts from the enum in either direction.
"""

from __future__ import annotations

from typing import get_args

from qua_shared.schemas.config.state import ReciterState, Visibility
from qua_shared.schemas.wire.seg import SegReciterState, SegReciterVisibility


def test_seg_reciter_state_literal_matches_canonical_enum():
    assert set(get_args(SegReciterState)) == {s.value for s in ReciterState}


def test_seg_reciter_visibility_literal_matches_canonical_enum():
    assert set(get_args(SegReciterVisibility)) == {v.value for v in Visibility}
