/**
 * MP3 head sniffing — is this file safe to seek natively straight off its CDN?
 *
 * Why this exists: Chrome demuxes MP3 with ffmpeg under `AVFMT_FLAG_FAST_SEEK`.
 * ffmpeg's `mp3_seek` picks the strategy from the first frame's VBR tag:
 *   - `Info` tag (CBR marker)  → linear byte math, exact for CBR (~20 ms).
 *   - no tag                   → linear byte math too (fine for CBR files).
 *   - `Xing` tag (VBR marker)  → the 100-entry TOC, quantised to 1/256 of the
 *     file. On a 24-minute chapter that is ±3–12 s of landing error, while
 *     `currentTime` still reports the requested time — the audio runs seconds
 *     ahead of every verse highlight.
 * Our bucket remux (`-c:a copy -f mp3` + `_force_info_if_cbr`) rewrites the
 * tag as `Info`, which is why the audio-proxy path never showed the drift.
 * Some source CDNs (e.g. quranicaudio's abdurrashid_sufi set) ship a `Xing`
 * tag on what is otherwise CBR audio; those chapters must stay proxied.
 */

/** Bytes to request when sniffing — covers a ~9 KB ID3v2 tag plus the first
 *  frame with room to spare. Bigger cover-art tags simply fail the sniff and
 *  fall back to the proxy. */
export const MP3_SNIFF_BYTES = 64 * 1024;

const ID3_HEADER_BYTES = 10;
const SYNC_MASK_HI = 0xff;
const SYNC_MASK_LO = 0xe0;
const LAYER_III = 1;
const VERSION_RESERVED = 1;
const VERSION_MPEG1 = 3;
const BITRATE_INDEX_FREE = 0;
const BITRATE_INDEX_BAD = 15;
const SAMPLE_RATE_INDEX_BAD = 3;
const CHANNEL_MODE_MONO = 3;
/** Side-info length (bytes) after the 4-byte header: [mpeg1?][mono?]. */
const SIDE_INFO_BYTES = { mpeg1: { mono: 17, stereo: 32 }, mpeg2: { mono: 9, stereo: 17 } } as const;
const TAG_BYTES = 4;
const XING = 'Xing';
const INFO = 'Info';

export type Mp3VbrTag = typeof XING | typeof INFO | null;

function syncsafe(b: Uint8Array, at: number): number {
    return ((b[at]! & 0x7f) << 21) | ((b[at + 1]! & 0x7f) << 14) | ((b[at + 2]! & 0x7f) << 7) | (b[at + 3]! & 0x7f);
}

/** Offset of the first byte past an ID3v2 tag (0 when there is none). */
function skipId3v2(b: Uint8Array): number {
    if (b.length < ID3_HEADER_BYTES || b[0] !== 0x49 || b[1] !== 0x44 || b[2] !== 0x33) return 0;
    const footer = (b[5]! & 0x10) ? ID3_HEADER_BYTES : 0;
    return ID3_HEADER_BYTES + syncsafe(b, 6) + footer;
}

function isFrameHeader(b: Uint8Array, i: number): boolean {
    if (i + 4 > b.length) return false;
    if (b[i] !== SYNC_MASK_HI || (b[i + 1]! & SYNC_MASK_LO) !== SYNC_MASK_LO) return false;
    const version = (b[i + 1]! >> 3) & 3;
    const layer = (b[i + 1]! >> 1) & 3;
    const bitrateIdx = b[i + 2]! >> 4;
    const sampleRateIdx = (b[i + 2]! >> 2) & 3;
    return version !== VERSION_RESERVED
        && layer === LAYER_III
        && bitrateIdx !== BITRATE_INDEX_FREE
        && bitrateIdx !== BITRATE_INDEX_BAD
        && sampleRateIdx !== SAMPLE_RATE_INDEX_BAD;
}

function tagAt(b: Uint8Array, at: number): Mp3VbrTag {
    if (at + TAG_BYTES > b.length) return null;
    const s = String.fromCharCode(b[at]!, b[at + 1]!, b[at + 2]!, b[at + 3]!);
    return s === XING || s === INFO ? s : null;
}

/** The VBR tag on the first MPEG audio frame: `'Xing'`, `'Info'`, or null
 *  when the frame carries none. Returns `undefined` when no frame header is
 *  found inside `bytes` (tag too large for the sniff window, not an MP3). */
export function firstFrameVbrTag(bytes: Uint8Array): Mp3VbrTag | undefined {
    for (let i = skipId3v2(bytes); i + 4 <= bytes.length; i += 1) {
        if (!isFrameHeader(bytes, i)) continue;
        const mpeg1 = ((bytes[i + 1]! >> 3) & 3) === VERSION_MPEG1;
        const mono = (bytes[i + 3]! >> 6) === CHANNEL_MODE_MONO;
        const side = SIDE_INFO_BYTES[mpeg1 ? 'mpeg1' : 'mpeg2'][mono ? 'mono' : 'stereo'];
        return tagAt(bytes, i + 4 + side);
    }
    return undefined;
}

/** True when the browser can seek this file accurately without the proxy:
 *  the first frame is found and does not carry a `Xing` (TOC-seek) tag. */
export function isNativelySeekable(bytes: Uint8Array): boolean {
    const tag = firstFrameVbrTag(bytes);
    return tag !== undefined && tag !== XING;
}
