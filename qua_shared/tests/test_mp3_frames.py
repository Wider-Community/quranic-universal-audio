"""Frame-index slicing: parser correctness + ffmpeg -c copy equivalence.

The publish job slices ~6,235 per-verse clips from each chapter MP3 in-process
via ``qua_shared.mp3_frames`` instead of one ffmpeg+ffprobe subprocess per clip.
These guard the two contracts that keep the public dataset audio faithful:

  1. The frame grid is parsed correctly (ID3 + Xing/Info skipped, per-frame
     duration from each header — so VBR is timed right), built from synthetic
     byte streams with no external dependency.
  2. A sliced clip's audio is byte-identical to ffmpeg ``-c copy`` over the
     same window's overlapping frames, the start snaps to <= clip_start, and
     the duration lands within +-1 frame — run against an ffmpeg-generated MP3
     when ffmpeg is on PATH (skipped otherwise).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from qua_shared.mp3_frames import build_frame_index, slice_frames, slice_frames_multi

# ---------------------------------------------------------------------------
# Synthetic MP3 byte-stream builders — no ffmpeg needed.
# ---------------------------------------------------------------------------

# MPEG-1 Layer III @ 44100 Hz, 1152 samples/frame -> 26.122 ms/frame.
_V1_FRAME_MS = 1152 * 1000.0 / 44100


def _frame_header(bitrate_idx: int, sr_idx: int = 0, padding: int = 0) -> bytes:
    """4-byte MPEG-1 Layer III header. ``bitrate_idx`` indexes the V1/L3 table."""
    h0 = 0xFF
    # 0xFB = 11111 011: sync + MPEG-1 (11) + Layer III (01) + no CRC (1).
    h1 = 0xFB
    h2 = (bitrate_idx << 4) | (sr_idx << 2) | (padding << 1)
    h3 = 0xC0  # stereo, no emphasis
    return bytes([h0, h1, h2, h3])


def _frame_len(bitrate_kbps: int, sr: int = 44100, padding: int = 0) -> int:
    return (1152 // 8 * bitrate_kbps * 1000) // sr + padding


def _make_frame(bitrate_idx: int, bitrate_kbps: int, padding: int = 0) -> bytes:
    """One synthetic frame: valid header + zero-filled body of the right length."""
    flen = _frame_len(bitrate_kbps, padding=padding)
    hdr = _frame_header(bitrate_idx, padding=padding)
    return hdr + b"\x00" * (flen - 4)


def _id3v2(payload_size: int) -> bytes:
    """Minimal ID3v2.4 header declaring ``payload_size`` bytes of (zeroed) tag."""
    sz = bytes(
        [
            (payload_size >> 21) & 0x7F,
            (payload_size >> 14) & 0x7F,
            (payload_size >> 7) & 0x7F,
            payload_size & 0x7F,
        ]
    )
    return b"ID3" + bytes([4, 0, 0]) + sz + b"\x00" * payload_size


def _cbr_stream(n_frames: int, *, with_id3: bool = True) -> bytes:
    """CBR 128 kbps stream of ``n_frames`` frames, optional leading ID3 tag."""
    frame = _make_frame(bitrate_idx=9, bitrate_kbps=128)  # idx 9 = 128 kbps
    body = frame * n_frames
    return (_id3v2(50) if with_id3 else b"") + body


def _vbr_stream(bitrates: list[int]) -> bytes:
    """VBR stream: a Xing header frame (must be skipped) then one frame per
    entry in ``bitrates`` (kbps). Each entry maps to its V1/L3 table index."""
    idx_for = {128: 9, 160: 10, 192: 11, 256: 13}
    # Xing header lives inside a normal frame; mark it by embedding b"Xing".
    xing_frame = bytearray(_make_frame(bitrate_idx=9, bitrate_kbps=128))
    xing_frame[36:40] = b"Xing"
    out = bytearray(bytes(xing_frame))
    for kbps in bitrates:
        out += _make_frame(bitrate_idx=idx_for[kbps], bitrate_kbps=kbps)
    return bytes(out)


# ---------------------------------------------------------------------------
# Parser correctness.
# ---------------------------------------------------------------------------


def test_cbr_index_counts_frames_and_skips_id3():
    data = _cbr_stream(100, with_id3=True)
    idx = build_frame_index(data)
    assert idx.n_frames == 100
    # First audio frame is past the 60-byte ID3 tag (10 header + 50 payload).
    assert idx.offsets[0] == 60
    # Duration = 100 frames * 26.122 ms.
    assert idx.duration_ms == pytest.approx(100 * _V1_FRAME_MS, abs=0.01)


def test_index_without_id3_starts_at_zero():
    data = _cbr_stream(10, with_id3=False)
    idx = build_frame_index(data)
    assert idx.n_frames == 10
    assert idx.offsets[0] == 0


def test_vbr_skips_xing_header_frame_and_times_each_frame():
    # 4 audio frames at mixed bitrates after the Xing frame.
    data = _vbr_stream([128, 256, 128, 192])
    idx = build_frame_index(data)
    # Xing frame excluded -> 4 audio frames.
    assert idx.n_frames == 4
    # Per-frame duration is constant for V1/L3 regardless of bitrate (1152
    # samples / 44100 Hz), so 4 frames is 4 * 26.122 ms — proves bitrate is
    # read per frame without desyncing the byte walk across varying frame sizes.
    assert idx.duration_ms == pytest.approx(4 * _V1_FRAME_MS, abs=0.01)
    # Frame byte offsets must be strictly increasing by each frame's own length.
    assert idx.offsets[1] - idx.offsets[0] == _frame_len(128)
    assert idx.offsets[2] - idx.offsets[1] == _frame_len(256)


# ---------------------------------------------------------------------------
# slice_frames contract.
# ---------------------------------------------------------------------------


def test_slice_snaps_start_to_frame_at_or_before():
    data = _cbr_stream(100, with_id3=False)
    idx = build_frame_index(data)
    # Window starting mid-frame-3 (3 * 26.122 = 78.4 ms -> request 85 ms).
    fs = slice_frames(data, idx, 85, 200)
    assert fs is not None
    # Snapped start is frame 3's boundary (<= 85 ms), not frame 4's.
    assert fs.actual_start_ms == int(round(3 * _V1_FRAME_MS))
    # Copied bytes are exactly the byte range from frame 3 onward (synthetic
    # frames are identical, so compare the range rather than search for it).
    assert fs.data == data[idx.offsets[3] : idx.offsets[3] + len(fs.data)]
    assert fs.data[:4] == _frame_header(9)


def test_slice_includes_frame_containing_end():
    data = _cbr_stream(100, with_id3=False)
    idx = build_frame_index(data)
    fs = slice_frames(data, idx, 0, 100)  # 100 ms ~ within frame 3
    assert fs is not None
    # End extends to cover the frame containing 100 ms -> >= 100 ms.
    assert fs.actual_end_ms >= 100


def test_slice_empty_window_returns_none():
    data = _cbr_stream(10, with_id3=False)
    idx = build_frame_index(data)
    assert slice_frames(data, idx, 100, 100) is None
    assert slice_frames(data, idx, 200, 100) is None


def test_slice_start_at_or_after_audio_end_returns_none():
    # A verse whose clip_start lands at/after the chapter audio's end (truncated
    # source audio vs longer timestamps) resolves the start frame to the grid
    # sentinel; the byte_end lookup then read one past ``offsets`` and raised
    # IndexError, aborting the whole reciter's publish. It must drop the verse.
    data = _cbr_stream(10, with_id3=False)  # 10 frames ~ 261 ms total
    idx = build_frame_index(data)
    assert idx.duration_ms == pytest.approx(10 * _V1_FRAME_MS, abs=0.01)
    # Start past the end, with a non-degenerate window — the crash case.
    assert slice_frames(data, idx, 300, 400) is None
    # Start at/after the total duration (the sentinel boundary) — also dropped.
    assert slice_frames(data, idx, int(idx.duration_ms) + 1, 99999) is None
    # A window that starts in-range but extends past the end still slices.
    tail = slice_frames(data, idx, 200, 99999)
    assert tail is not None and tail.data


def test_overlapping_windows_each_copy_their_own_frames():
    data = _cbr_stream(100, with_id3=False)
    idx = build_frame_index(data)
    a = slice_frames(data, idx, 500, 800)
    b = slice_frames(data, idx, 700, 1000)  # overlaps a
    assert a is not None and b is not None
    # The overlap region (frames covering ~700-800 ms) appears in both clips —
    # same source frames copied into two clips, byte-for-byte.
    overlap_off = idx.offsets[int(700 / _V1_FRAME_MS)]
    overlap_frame = data[overlap_off : overlap_off + _frame_len(128)]
    assert overlap_frame in a.data
    assert overlap_frame in b.data


# ---------------------------------------------------------------------------
# slice_frames_multi — stitch non-adjacent ranges (interior no-match excision).
# ---------------------------------------------------------------------------


def test_multi_single_range_equals_slice_frames():
    # One range must produce the exact same bytes as slice_frames (the common,
    # no-gap path stays a byte-for-byte no-op).
    data = _cbr_stream(100, with_id3=False)
    idx = build_frame_index(data)
    single = slice_frames(data, idx, 200, 800)
    ms = slice_frames_multi(data, idx, [(200, 800)])
    assert single is not None and ms is not None
    assert ms.data == single.data
    assert len(ms.runs) == 1
    assert ms.runs[0].actual_start_ms == single.actual_start_ms
    assert ms.runs[0].actual_end_ms == single.actual_end_ms
    assert ms.runs[0].cum_offset_ms == 0


def test_multi_excises_gap_and_concatenates_kept_runs():
    data = _cbr_stream(100, with_id3=False)
    idx = build_frame_index(data)
    # Keep [0,300) and [600,900); excise the [300,600) middle.
    run_a = slice_frames(data, idx, 0, 300)
    run_c = slice_frames(data, idx, 600, 900)
    ms = slice_frames_multi(data, idx, [(0, 300), (600, 900)])
    assert run_a is not None and run_c is not None and ms is not None
    # Concatenated bytes == run A bytes + run C bytes (gap dropped).
    assert ms.data == run_a.data + run_c.data
    # Two runs; second run's cum_offset == first run's snapped duration.
    assert len(ms.runs) == 2
    assert ms.runs[0].cum_offset_ms == 0
    assert ms.runs[1].cum_offset_ms == run_a.actual_end_ms - run_a.actual_start_ms
    # The gap is excised: the stitched clip is exactly the two kept runs (by
    # construction) and strictly shorter than a single contiguous [0,900] slice.
    # (Synthetic frames are byte-identical, so compare lengths, not contents.)
    full = slice_frames(data, idx, 0, 900)
    assert full is not None
    assert len(ms.data) == len(run_a.data) + len(run_c.data)
    assert len(ms.data) < len(full.data)


def test_multi_drops_degenerate_ranges():
    data = _cbr_stream(20, with_id3=False)
    idx = build_frame_index(data)
    # First range is degenerate (start>=end); only the second contributes.
    ms = slice_frames_multi(data, idx, [(100, 100), (200, 400)])
    only = slice_frames(data, idx, 200, 400)
    assert ms is not None and only is not None
    assert ms.data == only.data
    assert len(ms.runs) == 1
    # All-degenerate → None.
    assert slice_frames_multi(data, idx, [(100, 100), (300, 200)]) is None
    assert slice_frames_multi(data, idx, []) is None


# ---------------------------------------------------------------------------
# Equivalence vs ffmpeg -c copy (real codec, skipped without ffmpeg).
# ---------------------------------------------------------------------------

_HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _ffprobe_dur_ms(path: Path) -> int:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return int(round(float(out.stdout.strip()) * 1000))


def _pcm(path: Path) -> bytes:
    """Decode an MP3 to raw s16le mono PCM for sample-level comparison."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "-ar", "44100", "-"],
        capture_output=True,
    )
    return out.stdout


@pytest.mark.skipif(not _HAVE_FFMPEG, reason="ffmpeg/ffprobe not on PATH")
def test_slice_audio_matches_ffmpeg_copy(tmp_path):
    # Synthesize a 60 s CBR MP3 (a sine tone) with ffmpeg.
    src = tmp_path / "tone.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=60",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(src),
        ],
        check=True,
    )
    data = src.read_bytes()
    idx = build_frame_index(data)
    frame_ms = idx.starts_ms[1] - idx.starts_ms[0]

    for start_ms, end_ms in [(5_000, 12_000), (20_500, 41_250), (47_123, 58_999)]:
        fs = slice_frames(data, idx, start_ms, end_ms)
        assert fs is not None
        # Snapped start must be <= requested (frame boundary at-or-before).
        assert fs.actual_start_ms <= start_ms

        ff = tmp_path / "ff.mp3"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-ss",
                f"{start_ms / 1000:.6f}",
                "-i",
                str(src),
                "-t",
                f"{(end_ms - start_ms) / 1000:.6f}",
                "-c",
                "copy",
                "-f",
                "mp3",
                str(ff),
            ],
            check=True,
        )
        ff_dur = _ffprobe_dur_ms(ff)
        new_dur = fs.actual_end_ms - fs.actual_start_ms
        # Duration within +-1 frame of ffmpeg's clip.
        assert abs(new_dur - ff_dur) <= round(frame_ms) + 1

        # Our clip is itself a decodable MP3.
        nd = tmp_path / "new.mp3"
        nd.write_bytes(fs.data)
        assert _ffprobe_dur_ms(nd) > 0

        # Sample-level equivalence: ffmpeg's clip overshoots the start by 1-2
        # frames (its -ss lands at-or-after the seek point), so its decoded
        # PCM is a contiguous bit-identical run INSIDE our (start-<=, end->=)
        # clip's PCM. Same source frames, just a wider correct window.
        ours_pcm = _pcm(nd)
        ff_pcm = _pcm(ff)
        # Probe a chunk from the stable middle of ffmpeg's clip (skip decoder
        # warmup at both ends).
        probe = ff_pcm[len(ff_pcm) // 3 : len(ff_pcm) // 3 + 8000]
        assert probe and probe in ours_pcm
