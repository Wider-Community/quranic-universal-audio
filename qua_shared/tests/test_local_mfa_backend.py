"""LocalMfaBackend / _worker_align over the qua_sdk MfaLocalAligner seam.

Pins the cutover contract against a stubbed aligner: the (ref, path) zip
reaching ``align_items``, ``retry_beam`` pinned to ``beam`` (no implicit
retry — the SDK default would silently widen), the wb-allocation payload
resolved to the full per-rule dict, error envelopes raising, and dumped
rows staying consumable by ``_convert_word``.

qua_sdk-dependent (wire models + the patched aligner module); the whole
file skips when the SDK isn't installed.
"""

from __future__ import annotations

import pytest

wire = pytest.importorskip("qua_sdk.components.timing.wire", reason="qua_sdk not installed")

import qua_sdk.components.timing.runtimes.mfa_local as mfa_local_module
from qua_sdk.components.timing.lib import resolve_word_boundary_allocation
from qua_sdk.components.timing.wire import (
    BatchEnvelope,
    ResultRow,
    WordPhone,
    WordRow,
)
from qua_sdk.schemas.timing import LetterTiming

import qua_shared.timestamps_pipeline as tp
from qua_shared.timestamps_pipeline import LocalMfaBackend, _convert_word, _worker_align

# === Helpers ===


class _StubAligner:
    """Records align_items calls and returns a canned envelope."""

    def __init__(self, envelope: BatchEnvelope):
        self.envelope = envelope
        self.ctor_args: tuple | None = None
        self.ctor_kwargs: dict | None = None
        self.calls: list[dict] = []

    def align_items(self, refs_and_paths, **kwargs):
        self.calls.append({"items": list(refs_and_paths), **kwargs})
        return self.envelope


def _ok_envelope(refs) -> BatchEnvelope:
    rows = [
        ResultRow(
            ref=ref,
            status="ok",
            words=[
                WordRow(
                    location="1:1:1",
                    text="x",
                    start=0.0,
                    end=0.5,
                    phone_indices=[0],
                    letters=[LetterTiming(char="b", start=0.0, end=0.5)],
                    phones=[WordPhone(phone="B", start=0.0, end=0.5)],
                )
            ],
        )
        for ref in refs
    ]
    return BatchEnvelope(status="ok", count=len(rows), results=rows)


def _patched_backend(monkeypatch, envelope: BatchEnvelope, **backend_kwargs) -> LocalMfaBackend:
    """Build a LocalMfaBackend whose call-local MfaLocalAligner import yields
    a recording stub (ctor args captured on the instance)."""
    stub = _StubAligner(envelope)

    def _factory(*args, **kwargs):
        stub.ctor_args = args
        stub.ctor_kwargs = kwargs
        return stub

    monkeypatch.setattr(mfa_local_module, "MfaLocalAligner", _factory)
    return LocalMfaBackend("model.zip", "dict.txt", **backend_kwargs)


# === Tests ===


def test_align_batch_zips_refs_and_paths_into_align_items(monkeypatch):
    refs = ["1:1:1-1:1:4", "1:2:1-1:2:3"]
    backend = _patched_backend(monkeypatch, _ok_envelope(refs))
    backend.align_batch(
        refs,
        ["/tmp/a.wav", "/tmp/b.wav"],
        method="kalpy",
        beam=50,
        shared_cmvn=False,
        padding="forward",
    )
    assert isinstance(backend.aligner, _StubAligner)
    call = backend.aligner.calls[0]
    assert call["items"] == [("1:1:1-1:1:4", "/tmp/a.wav"), ("1:2:1-1:2:3", "/tmp/b.wav")]
    assert call["method"] == "kalpy"
    assert call["shared_cmvn"] is False
    assert call["padding"] == "forward"


def test_align_batch_pins_retry_beam_to_beam(monkeypatch):
    refs = ["1:1:1-1:1:4"]
    backend = _patched_backend(monkeypatch, _ok_envelope(refs))
    backend.align_batch(
        refs, ["/tmp/a.wav"], method="kalpy", beam=7, shared_cmvn=False, padding="forward"
    )
    assert isinstance(backend.aligner, _StubAligner)
    call = backend.aligner.calls[0]
    assert call["beam"] == 7
    assert call["retry_beam"] == 7


def test_align_batch_resolves_wb_payload_to_full_rule_dict(monkeypatch):
    refs = ["1:1:1-1:1:4"]
    backend = _patched_backend(monkeypatch, _ok_envelope(refs))
    backend.align_batch(
        refs,
        ["/tmp/a.wav"],
        method="kalpy",
        beam=50,
        shared_cmvn=False,
        padding="forward",
        word_boundary_allocation={"idgham_shafawi": "second"},
    )
    assert isinstance(backend.aligner, _StubAligner)
    resolved = backend.aligner.calls[0]["wb_allocation_resolved"]
    expected = dict(resolve_word_boundary_allocation(None))
    expected["idgham_shafawi"] = "second"
    assert resolved == expected
    assert len(resolved) == 8


def test_align_batch_none_wb_payload_resolves_to_system_defaults(monkeypatch):
    refs = ["1:1:1-1:1:4"]
    backend = _patched_backend(monkeypatch, _ok_envelope(refs))
    backend.align_batch(
        refs, ["/tmp/a.wav"], method="kalpy", beam=50, shared_cmvn=False, padding="forward"
    )
    assert isinstance(backend.aligner, _StubAligner)
    resolved = backend.aligner.calls[0]["wb_allocation_resolved"]
    assert resolved == resolve_word_boundary_allocation(None)


def test_align_batch_error_envelope_raises_with_error_message(monkeypatch):
    envelope = BatchEnvelope(status="error", error="kalpy exploded")
    backend = _patched_backend(monkeypatch, envelope)
    with pytest.raises(RuntimeError, match="kalpy exploded"):
        backend.align_batch(
            ["1:1:1-1:1:4"],
            ["/tmp/a.wav"],
            method="kalpy",
            beam=50,
            shared_cmvn=False,
            padding="forward",
        )


def test_align_batch_rows_feed_convert_word(monkeypatch):
    refs = ["1:1:1-1:1:4"]
    backend = _patched_backend(monkeypatch, _ok_envelope(refs))
    rows = backend.align_batch(
        refs, ["/tmp/a.wav"], method="kalpy", beam=50, shared_cmvn=False, padding="forward"
    )
    assert rows is not None
    assert rows[0]["status"] == "ok"
    converted = _convert_word(rows[0]["words"][0], 100)
    assert converted == [1, 100, 600, [["b", 100, 600]], [["B", 100, 600]]]


def test_backend_ctor_builds_serial_aligner_with_mfa_threads(monkeypatch):
    backend = _patched_backend(monkeypatch, _ok_envelope([]), mfa_threads=3)
    assert isinstance(backend.aligner, _StubAligner)
    assert backend.aligner.ctor_args == ("model.zip", "dict.txt")
    assert backend.aligner.ctor_kwargs == {"num_threads": 3, "use_pool": False}


def test_worker_align_uses_module_global_aligner(monkeypatch):
    refs = ["1:1:1-1:1:4"]
    stub = _StubAligner(_ok_envelope(refs))
    monkeypatch.setitem(tp._WORKER, "aligner", stub)
    # Six positional args — the probe / auto-split call shape.
    rows = _worker_align(refs, ["/tmp/a.wav"], "kalpy", 2, False, "none")
    call = stub.calls[0]
    assert call["items"] == [("1:1:1-1:1:4", "/tmp/a.wav")]
    assert call["beam"] == 2
    assert call["retry_beam"] == 2
    assert call["padding"] == "none"
    assert rows[0]["status"] == "ok"


def test_worker_align_raises_when_worker_not_initialized(monkeypatch):
    monkeypatch.setitem(tp._WORKER, "aligner", None)
    with pytest.raises(RuntimeError, match="not initialized"):
        _worker_align(["1:1:1-1:1:4"], ["/tmp/a.wav"], "kalpy", 50, False, "forward")
