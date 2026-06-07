"""In-process MP3 frame-index slicing — stream-copy clips without ffmpeg.

The HF dataset publish job cuts ~6,235 per-verse clips from each reciter's
chapter MP3s. The previous shape spawned two subprocesses per clip
(``ffmpeg -ss -i -t -c copy`` + an ``ffprobe`` to measure the snap), which
dominated wall-clock (~92% of each reciter's publish) and scaled O(n²) with
byte-offset because MP3 has no cheap random seek.

This module replaces that with a single sequential read per chapter:

1. ``build_frame_index`` scans the chapter MP3 once, skipping any leading
   ID3v2 tag and any Xing/Info/VBRI header frame, and records every audio
   frame's byte ``offset`` and cumulative ``start_ms``. Pure Python, one
   linear pass — bound becomes chapter count (114), not clip count (6235).
2. ``slice_frames`` copies the exact frame byte-range covering a verse window
   ``[clip_start, clip_end]``, snapping the start back to the nearest frame
   boundary <= clip_start. This is byte-identical to what ffmpeg ``-c copy``
   copies (both copy whole frames), minus the subprocess and minus the snap
   probe — the snapped ``actual_start_ms`` is read straight off the frame grid.

Handles CBR and VBR (Xing-injected) MP3s: per-frame duration is derived from
each frame's own header (samples-per-frame / sample-rate), so a VBR stream
where bitrate/size varies frame to frame is timed correctly. Overlapping verse
windows (lookback re-recitations) each copy their own frame range, so the same
source frames can land in more than one clip.

The produced clip is raw frames with no Xing/ID3 header — same as ffmpeg's
``-c copy -f mp3`` audio payload (ffmpeg prepends a fresh ID3 metadata tag,
which carries no audio and is irrelevant to playback/duration).
"""

from __future__ import annotations

from dataclasses import dataclass

# MPEG version index (bits 19-20 of the header) -> sampling-rate table column /
# samples-per-frame class. Index 1 is reserved.
_MPEG_V2_5 = 0
_MPEG_RESERVED = 1
_MPEG_V2 = 2
_MPEG_V1 = 3

# Layer index (bits 17-18). Layer III is 1.
_LAYER_III = 1

# Bitrate tables (kbps) keyed by (mpeg_version, layer) -> 16-entry list.
# Index 0 = "free", index 15 = "bad" (both invalid for our streams).
_BITRATE_V1_L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_BITRATE_V2_L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]

# Sample-rate tables (Hz) keyed by mpeg version -> 4-entry list (index 3 reserved).
_SAMPLE_RATE = {
    _MPEG_V1: [44100, 48000, 32000, 0],
    _MPEG_V2: [22050, 24000, 16000, 0],
    _MPEG_V2_5: [11025, 12000, 8000, 0],
}

# Samples per Layer III frame: 1152 for MPEG-1, 576 for MPEG-2 / 2.5.
_SAMPLES_PER_FRAME = {_MPEG_V1: 1152, _MPEG_V2: 576, _MPEG_V2_5: 576}


@dataclass(frozen=True)
class _FrameHeader:
    version: int
    sample_rate: int
    frame_bytes: int
    samples: int


def _parse_frame_header(b: bytes, off: int) -> _FrameHeader | None:
    """Decode the 4-byte MPEG audio frame header at ``b[off:off+4]``.

    Returns ``None`` when the bytes aren't a valid MPEG-1/2/2.5 Layer III
    frame header (no 11-bit sync, reserved version/bitrate/samplerate, or a
    non-Layer-III layer) — the caller resyncs from the next byte.
    """
    if off + 4 > len(b):
        return None
    h0, h1, h2 = b[off], b[off + 1], b[off + 2]
    # 11-bit frame sync: all of h0 and the top 3 bits of h1.
    if h0 != 0xFF or (h1 & 0xE0) != 0xE0:
        return None
    version = (h1 >> 3) & 0x03
    layer = (h1 >> 1) & 0x03
    if version == _MPEG_RESERVED or layer != _LAYER_III:
        return None
    bitrate_idx = (h2 >> 4) & 0x0F
    sr_idx = (h2 >> 2) & 0x03
    padding = (h2 >> 1) & 0x01
    if bitrate_idx == 0 or bitrate_idx == 15 or sr_idx == 3:
        return None
    sample_rate = _SAMPLE_RATE[version][sr_idx]
    if sample_rate == 0:
        return None
    bitrate = (_BITRATE_V1_L3 if version == _MPEG_V1 else _BITRATE_V2_L3)[bitrate_idx] * 1000
    if bitrate == 0:
        return None
    samples = _SAMPLES_PER_FRAME[version]
    # Layer III frame length: floor(samples/8 * bitrate / sample_rate) + padding.
    frame_bytes = (samples // 8 * bitrate) // sample_rate + padding
    if frame_bytes <= 4:
        return None
    return _FrameHeader(
        version=version,
        sample_rate=sample_rate,
        frame_bytes=frame_bytes,
        samples=samples,
    )


def _skip_id3v2(data: bytes) -> int:
    """Return the byte offset of the first audio frame past any leading ID3v2 tag."""
    if data[:3] != b"ID3":
        return 0
    if len(data) < 10:
        return 0
    sz = data[6:10]
    # 28-bit syncsafe size (7 bits per byte).
    tag_size = (sz[0] << 21) | (sz[1] << 14) | (sz[2] << 7) | sz[3]
    # Bit 4 of the flags byte = footer present (+10 bytes).
    footer = 10 if (data[5] & 0x10) else 0
    return 10 + tag_size + footer


def _is_xing_or_vbri(data: bytes, frame_off: int, frame_bytes: int) -> bool:
    """True when the frame at ``frame_off`` is a Xing/Info/VBRI metadata frame.

    These carry no audio — they're the VBR seek TOC (``Xing``/``Info``, after
    the side-info gap) or Fraunhofer ``VBRI`` (fixed offset 36). They must be
    excluded from the timed audio grid so frame durations stay accurate.
    """
    frame = data[frame_off : frame_off + frame_bytes]
    if b"Xing" in frame[:40] or b"Info" in frame[:40]:
        return True
    if len(frame) >= 40 and frame[36:40] == b"VBRI":
        return True
    return False


@dataclass(frozen=True)
class FrameIndex:
    """Frame grid for one MP3: parallel offset/start arrays + sample rate.

    ``offsets[i]`` is the byte position of audio frame ``i``; ``starts_ms[i]``
    is its cumulative start time. ``offsets[-1]`` is the byte position just past
    the last audio frame (the audio EOF), and ``starts_ms[-1]`` the total audio
    duration — so ``offsets``/``starts_ms`` each have ``n_frames + 1`` entries.
    """

    offsets: list[int]
    starts_ms: list[float]

    @property
    def n_frames(self) -> int:
        return len(self.offsets) - 1

    @property
    def duration_ms(self) -> float:
        return self.starts_ms[-1] if self.starts_ms else 0.0


def build_frame_index(data: bytes) -> FrameIndex:
    """Scan an MP3's bytes once and build its audio-frame grid.

    Skips a leading ID3v2 tag and a Xing/Info/VBRI header frame. Resyncs over
    occasional garbage between frames (rare in clean streams) by advancing one
    byte at a time until the next valid header. Trailing ID3v1/APE tags after
    the last frame are naturally excluded (no valid sync follows).
    """
    offsets: list[int] = []
    starts_ms: list[float] = []
    pos = _skip_id3v2(data)
    n = len(data)
    cum_ms = 0.0
    first_audio_seen = False
    while pos + 4 <= n:
        fh = _parse_frame_header(data, pos)
        if fh is None:
            pos += 1
            continue
        # Drop the Xing/Info/VBRI header frame (first valid frame only) — it
        # carries no audio and would skew the timing grid.
        if not first_audio_seen and _is_xing_or_vbri(data, pos, fh.frame_bytes):
            pos += fh.frame_bytes
            continue
        first_audio_seen = True
        offsets.append(pos)
        starts_ms.append(cum_ms)
        cum_ms += fh.samples * 1000.0 / fh.sample_rate
        pos += fh.frame_bytes
    # Sentinel: byte just past the last audio frame + total duration.
    offsets.append(pos if offsets else _skip_id3v2(data))
    starts_ms.append(cum_ms)
    return FrameIndex(offsets=offsets, starts_ms=starts_ms)


@dataclass(frozen=True)
class FrameSlice:
    """One sliced clip: raw frame bytes + the snapped source window it covers.

    ``actual_start_ms`` is the start of the first copied frame (<= the requested
    ``clip_start``); callers rebase clip-relative timestamps by
    ``clip_start - actual_start_ms``. ``actual_end_ms`` is the end of the last
    copied frame.
    """

    data: bytes
    actual_start_ms: int
    actual_end_ms: int


def _frame_at_or_before(starts_ms: list[float], t_ms: float) -> int:
    """Largest frame index ``i`` with ``starts_ms[i] <= t_ms`` (>= 0)."""
    import bisect

    # bisect_right gives the first index > t_ms; step back one for <=.
    i = bisect.bisect_right(starts_ms, t_ms) - 1
    return max(0, i)


def slice_frames(data: bytes, index: FrameIndex, start_ms: int, end_ms: int) -> FrameSlice | None:
    """Copy the frame byte-range covering ``[start_ms, end_ms]`` from ``data``.

    The start snaps back to the frame boundary <= ``start_ms`` (matching
    ffmpeg ``-ss`` input-seek stream-copy); the end extends to include the
    frame containing ``end_ms``. Returns ``None`` for an empty/degenerate
    window or when the index has no frames.
    """
    if index.n_frames <= 0 or end_ms <= start_ms:
        return None
    starts = index.starts_ms
    offsets = index.offsets
    i0 = _frame_at_or_before(starts, float(start_ms))
    # ``start_ms`` at/after the last frame's start resolves i0 to the sentinel
    # index (``n_frames``) — there is no real frame to copy and ``offsets[i1+1]``
    # below would read past the array. This happens when a verse's clip_start
    # lands beyond the chapter audio's end (truncated/short source audio vs
    # longer timestamps). Drop the verse rather than crash the whole publish.
    if i0 >= index.n_frames:
        return None
    # End frame: the last frame that starts strictly before end_ms (so the
    # frame containing end_ms is included). Clip to the last real frame.
    import bisect

    i1 = bisect.bisect_left(starts, float(end_ms), lo=i0, hi=index.n_frames) - 1
    if i1 < i0:
        i1 = i0
    byte_start = offsets[i0]
    byte_end = offsets[i1 + 1]
    if byte_end <= byte_start:
        return None
    return FrameSlice(
        data=data[byte_start:byte_end],
        actual_start_ms=int(round(starts[i0])),
        actual_end_ms=int(round(starts[i1 + 1])),
    )


@dataclass(frozen=True)
class RunMap:
    """One kept run inside a stitched (gap-excised) clip.

    ``actual_start_ms`` / ``actual_end_ms`` are the snapped source-ms window the
    run's frames cover (same semantics as ``FrameSlice``). ``cum_offset_ms`` is
    the run's start position along the CONCATENATED clip's timeline (sum of all
    prior runs' snapped durations) — so a source time ``t`` inside this run maps
    to clip-relative ``(t - actual_start_ms) + cum_offset_ms``.
    """

    actual_start_ms: int
    actual_end_ms: int
    cum_offset_ms: int


@dataclass(frozen=True)
class MultiFrameSlice:
    """A clip stitched from several non-adjacent frame ranges of one MP3.

    ``data`` is the concatenated raw frames (headerless, same shape as
    ``FrameSlice.data`` — a valid MP3 audio payload). ``runs`` carries one
    ``RunMap`` per kept range, in clip order, for rebasing timestamps onto the
    gap-excised timeline.
    """

    data: bytes
    runs: list[RunMap]


def slice_frames_multi(
    data: bytes, index: FrameIndex, ranges: list[tuple[int, int]]
) -> MultiFrameSlice | None:
    """Slice several source-ms ranges and concatenate their frames into one clip.

    Each ``(start_ms, end_ms)`` range is cut with ``slice_frames`` (independent
    frame-boundary snap per range) and the raw frame bytes are concatenated in
    order — excising whatever audio falls between the ranges (e.g. a no-match
    gap). Ranges that slice to nothing are skipped; returns ``None`` if every
    range drops or ``ranges`` is empty.

    A single range yields the same bytes as ``slice_frames`` (the common,
    no-gap case stays a no-op). Concatenating whole frames is byte-equivalent to
    ffmpeg ``-c copy`` of each range appended; the only artifact is a brief
    bit-reservoir discontinuity at each splice (acceptable — the same ~26 ms
    frame snap already applies at every clip head).
    """
    if not ranges:
        return None
    parts: list[bytes] = []
    runs: list[RunMap] = []
    cum = 0
    for start_ms, end_ms in ranges:
        fs = slice_frames(data, index, start_ms, end_ms)
        if fs is None:
            continue
        parts.append(fs.data)
        runs.append(
            RunMap(
                actual_start_ms=fs.actual_start_ms,
                actual_end_ms=fs.actual_end_ms,
                cum_offset_ms=cum,
            )
        )
        cum += fs.actual_end_ms - fs.actual_start_ms
    if not parts:
        return None
    return MultiFrameSlice(data=b"".join(parts), runs=runs)
