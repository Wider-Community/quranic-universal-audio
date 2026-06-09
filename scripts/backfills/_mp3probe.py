"""Pure-Python MP3 source-URL prober for catalog metadata backfill.

Returns decoded duration + bitrate + a cbr/vbr verdict for an mp3 reachable by
URL, without mutagen.

The cbr/vbr verdict comes from the whole-file linear-seek metric
(``qua_shared.mp3_frames.classify_bitrate_mode``) — the only reliable signal.
Head-only bitrate uniformity misses VBR whose variation starts past the head,
and ``len(set(bitrates)) == 1`` is fooled by a stray frame in CBR audio. That
metric needs the full file, so ``probe_source(allow_full=True)`` downloads and
walks every frame; ``allow_full=False`` returns a head duration estimate with
the mode left unset (``needs_full``).

Duration is read off the frame grid (frames × samples_per_frame / sample_rate),
never bitrate-estimated on the wrong file size (the maher-ch76 phantom-tail
failure mode).

Handles MPEG-1/2/2.5 Layer III (archive.org / tvquran / mp3quran all differ).
"""

from __future__ import annotations

import re
import urllib.request as _u
from dataclasses import dataclass

PROBE_BYTES = 262144
TIMEOUT_S = 30

# archive.org stores per-item node hostnames (ia801506.us.archive.org/…) that go
# stale as items migrate between nodes. The canonical archive.org/download/<item>
# form 302-redirects to whatever node is currently live, so we always fetch (and
# can re-store) that durable form.
_ARCHIVE_NODE_RE = re.compile(r"^https?://(?:ia\d+\.us|dn\d+\.ca)\.archive\.org/\d+/items/(.+)$")


def canonical_archive_url(url: str) -> str:
    m = _ARCHIVE_NODE_RE.match(url)
    return f"https://archive.org/download/{m.group(1)}" if m else url


# [version_id][bitrate_index] kbps. version_id: 3=MPEG1, 2=MPEG2, 0=MPEG2.5
_BR_V1 = [None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, None]
_BR_V2 = [None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, None]
_SR = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def _frame(b: bytes) -> dict | None:
    if len(b) < 4 or b[0] != 0xFF or (b[1] & 0xE0) != 0xE0:
        return None
    ver = (b[1] >> 3) & 0x03  # 3=MPEG1 2=MPEG2 0=MPEG2.5 (1=reserved)
    layer = (b[1] >> 1) & 0x03  # 1=LayerIII
    br_i = (b[2] >> 4) & 0x0F
    sr_i = (b[2] >> 2) & 0x03
    pad = (b[2] >> 1) & 0x01
    chan = (b[3] >> 6) & 0x03
    if ver == 1 or layer != 1 or br_i in (0, 15) or sr_i == 3:
        return None
    kbps = (_BR_V1 if ver == 3 else _BR_V2)[br_i]
    sr = _SR[ver][sr_i]
    if kbps is None:
        return None
    spf = 1152 if ver == 3 else 576
    fsize = (spf // 8) * (kbps * 1000) // sr + pad
    if fsize < 24:
        return None
    return {"ver": ver, "kbps": kbps, "sr": sr, "spf": spf, "chan": chan, "fsize": fsize}


def _skip_id3(data: bytes) -> int:
    if data[:3] == b"ID3" and len(data) >= 10:
        s = data[6:10]
        return 10 + ((s[0] << 21) | (s[1] << 14) | (s[2] << 7) | s[3])
    return 0


def _first_frame(data: bytes, start: int) -> tuple[int, dict | None]:
    pos = start
    n = len(data)
    while pos + 4 <= n:
        h = _frame(data[pos : pos + 4])
        if h is not None:
            return pos, h
        nxt = data.find(b"\xff", pos + 1)
        if nxt < 0:
            break
        pos = nxt
    return -1, None


def _xing_frames(data: bytes, foff: int, h: dict) -> int | None:
    """Xing/Info frame count, or None if no header / no count flag."""
    if h["ver"] == 3:
        side = 17 if h["chan"] == 3 else 32
    else:
        side = 9 if h["chan"] == 3 else 17
    p = foff + 4 + side
    if data[p : p + 4] not in (b"Xing", b"Info"):
        return None
    flags = int.from_bytes(data[p + 4 : p + 8], "big")
    if not (flags & 1):
        return None
    return int.from_bytes(data[p + 8 : p + 12], "big") or None


def _range(url: str, start: int, end: int) -> tuple[bytes, int | None, int]:
    """Fetch bytes [start,end]; return (data, total_size, status)."""
    req = _u.Request(
        url,
        headers={"Range": f"bytes={start}-{end}", "User-Agent": "qua-meta-backfill"},
    )
    with _u.urlopen(req, timeout=TIMEOUT_S) as r:
        cr = r.headers.get("Content-Range")
        total = None
        if cr and "/" in cr and cr.split("/")[-1] != "*":
            total = int(cr.split("/")[-1])
        elif r.headers.get("Content-Length") and r.status == 200:
            total = int(r.headers["Content-Length"])
        return r.read(), total, r.status


def _id3_size(url: str) -> int:
    """ID3v2 tag byte length (0 if absent). Archive.org/tvquran embed cover art
    in tags up to ~1.5 MB, so the first audio frame can sit far past byte 0."""
    head, _, _ = _range(url, 0, 9)
    if len(head) >= 10 and head[:3] == b"ID3":
        s = head[6:10]
        return 10 + ((s[0] << 21) | (s[1] << 14) | (s[2] << 7) | s[3])
    return 0


def _fetch(url: str, n: int) -> tuple[bytes, int | None, int]:
    """Fetch ~n bytes of *audio* (skipping any ID3v2 tag) + total size + tag size."""
    tag = _id3_size(url)
    buf, total, status = _range(url, tag, tag + n - 1)
    if status == 200:  # server ignored Range — buf is the whole file from 0
        buf = buf[tag:]
    return buf, total, tag


def _fetch_full(url: str) -> bytes:
    req = _u.Request(url, headers={"User-Agent": "qua-meta-backfill"})
    with _u.urlopen(req, timeout=TIMEOUT_S * 3) as r:
        return r.read()


@dataclass
class SourceProbe:
    duration_sec: int | None = None
    bitrate_kbps: int | None = None
    bitrate_mode: str | None = None  # 'cbr' | 'vbr'
    sample_rate: int | None = None
    method: str = ""  # xing | cbr_size | full_walk
    resolved_url: str | None = None  # canonical url actually fetched (may differ from input)
    error: str | None = None


def probe_source(url: str, *, allow_full: bool = True) -> SourceProbe:
    """Probe a source-URL mp3 for duration + bitrate + a cbr/vbr verdict.

    The cbr/vbr verdict is ALWAYS from the whole-file linear-seek metric
    (``qua_shared.mp3_frames.classify_bitrate_mode``) — head bitrate-uniformity
    misses VBR whose variation starts past the head, and ``len(set(bitrates))``
    is fooled by a single stray frame in otherwise-CBR audio. That metric needs
    the whole file, so a trustworthy verdict requires ``allow_full=True``. With
    ``allow_full=False`` the head still yields a duration estimate but the mode
    is left unset (``needs_full``) for the caller to resolve later.
    """
    fetch_url = canonical_archive_url(url)
    rewritten = fetch_url if fetch_url != url else None

    if not allow_full:
        try:
            buf, _total, _tag = _fetch(fetch_url, PROBE_BYTES)
        except Exception as e:  # noqa: BLE001
            return SourceProbe(resolved_url=rewritten, error=f"fetch:{type(e).__name__}:{e}")
        off = _skip_id3(buf)
        foff, h = _first_frame(buf, off)
        if h is None:
            return SourceProbe(resolved_url=rewritten, error="no_frame_in_head")
        xf = _xing_frames(buf, foff, h)
        dur = int(round(xf * h["spf"] / h["sr"])) if xf else None
        return SourceProbe(dur, h["kbps"], None, h["sr"], "needs_full", rewritten)

    # Full download → authoritative verdict via the canonical whole-file metric
    # (shared with the extraction bitrate audit).
    from qua_shared.mp3_frames import build_frame_index, classify_bitrate_mode

    try:
        data = _fetch_full(fetch_url)
    except Exception as e:  # noqa: BLE001
        return SourceProbe(resolved_url=rewritten, error=f"full:{type(e).__name__}:{e}")
    idx = build_frame_index(data)
    if idx.n_frames <= 0:
        return SourceProbe(resolved_url=rewritten, error="no_frames_full")
    off = _skip_id3(data)
    _foff, h = _first_frame(data, off)
    sr = h["sr"] if h else None
    dur = idx.duration_ms / 1000.0
    audio_bytes = idx.offsets[idx.n_frames] - idx.offsets[0]
    avg_kbps = int(round(audio_bytes * 8 / dur / 1000)) if dur else (h["kbps"] if h else None)
    mode = classify_bitrate_mode(data)
    return SourceProbe(int(round(dur)), avg_kbps, mode, sr, "full_walk", rewritten)
