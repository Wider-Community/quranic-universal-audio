/**
 * Deterministic segment_uid backfill helpers (IS-8).
 *
 * Mirrors Python ``inspector/domain/identity.py``.  The UUID5 derivation
 * MUST produce the same string for the same ``(chapter, originalIndex, startMs)``
 * triple as the Python implementation so that cross-process uid-backfill tests pass.
 *
 * Algorithm: uuid5(NAMESPACE_INSPECTOR, ``"{chapter}:{originalIndex}:{startMs}"``)
 * where NAMESPACE_INSPECTOR = ``00000000-0000-0000-0000-000000000001``.
 *
 * UUID v5 spec (RFC 4122):
 *   1. Concatenate namespace bytes (16) + UTF-8 name bytes.
 *   2. SHA-1 hash the result.
 *   3. Take the first 16 bytes; set version (byte 6 high nibble = 0x50) and
 *      variant (byte 8 high bits = 0b10xxxxxx).
 *   4. Format as ``xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx``.
 */

/** UUID namespace for inspector segment identity.  Frozen — changing it
 *  would invalidate all previously backfilled UIDs. */
const NAMESPACE_INSPECTOR = '00000000-0000-0000-0000-000000000001';

/** Parse a UUID string into a 16-byte Uint8Array. */
function _uuidToBytes(uuid: string): Uint8Array {
    const hex = uuid.replace(/-/g, '');
    const bytes = new Uint8Array(16);
    for (let i = 0; i < 16; i++) {
        bytes[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
    }
    return bytes;
}

/** Format a 16-byte Uint8Array as a UUID string. */
function _bytesToUuid(bytes: Uint8Array): string {
    const hex = Array.from(bytes)
        .map((b) => b.toString(16).padStart(2, '0'))
        .join('');
    return (
        hex.slice(0, 8) + '-' +
        hex.slice(8, 12) + '-' +
        hex.slice(12, 16) + '-' +
        hex.slice(16, 20) + '-' +
        hex.slice(20, 32)
    );
}

const _NS_BYTES = _uuidToBytes(NAMESPACE_INSPECTOR);

/**
 * Synchronous SHA-1 implementation (RFC 3174) used for uuid5 derivation.
 *
 * This is intentionally a plain JS implementation so that ``deriveUid`` can
 * be called synchronously — ``crypto.subtle.digest`` is async-only in browsers,
 * which makes it unsuitable for use in Svelte store initializers and vitest
 * synchronous tests.  The implementation is correct for uuid5 purposes; it is
 * NOT intended as a general-purpose cryptographic primitive.
 */
function _sha1(data: Uint8Array): Uint8Array {
    // Preprocess: append 0x80, pad to 64-byte boundary, append 64-bit big-endian length
    const bitLen = data.length * 8;
    const padLen = ((data.length + 9 + 63) & ~63);
    const msg = new Uint8Array(padLen);
    msg.set(data);
    msg[data.length] = 0x80;
    // Write 64-bit big-endian bit length into last 8 bytes
    const view = new DataView(msg.buffer);
    view.setUint32(padLen - 4, bitLen & 0xffffffff, false);
    // SHA-1 constants and initial hash values
    let h0 = 0x67452301;
    let h1 = 0xefcdab89;
    let h2 = 0x98badcfe;
    let h3 = 0x10325476;
    let h4 = 0xc3d2e1f0;

    const w = new Uint32Array(80);

    for (let chunk = 0; chunk < padLen; chunk += 64) {
        // Load chunk words big-endian
        for (let i = 0; i < 16; i++) {
            w[i] = view.getUint32(chunk + i * 4, false);
        }
        // Extend
        for (let i = 16; i < 80; i++) {
            const v = w[i - 3]! ^ w[i - 8]! ^ w[i - 14]! ^ w[i - 16]!;
            w[i] = (v << 1) | (v >>> 31);
        }
        let a = h0, b = h1, c = h2, d = h3, e = h4;
        for (let i = 0; i < 80; i++) {
            let f: number, k: number;
            if (i < 20) {
                f = (b & c) | (~b & d);
                k = 0x5a827999;
            } else if (i < 40) {
                f = b ^ c ^ d;
                k = 0x6ed9eba1;
            } else if (i < 60) {
                f = (b & c) | (b & d) | (c & d);
                k = 0x8f1bbcdc;
            } else {
                f = b ^ c ^ d;
                k = 0xca62c1d6;
            }
            const temp = (((a << 5) | (a >>> 27)) + f + e + k + w[i]!) >>> 0;
            e = d;
            d = c;
            c = ((b << 30) | (b >>> 2)) >>> 0;
            b = a;
            a = temp;
        }
        h0 = (h0 + a) >>> 0;
        h1 = (h1 + b) >>> 0;
        h2 = (h2 + c) >>> 0;
        h3 = (h3 + d) >>> 0;
        h4 = (h4 + e) >>> 0;
    }

    const digest = new Uint8Array(20);
    const dv = new DataView(digest.buffer);
    dv.setUint32(0, h0, false);
    dv.setUint32(4, h1, false);
    dv.setUint32(8, h2, false);
    dv.setUint32(12, h3, false);
    dv.setUint32(16, h4, false);
    return digest;
}

/** Derive a deterministic segment UID from the given coordinates.
 *
 * Produces the same string as Python's
 * ``str(uuid.uuid5(NAMESPACE_INSPECTOR, f"{chapter}:{originalIndex}:{startMs}"))``
 * for the same inputs.
 */
export function deriveUid(params: {
    chapter: number;
    originalIndex: number;
    startMs: number;
}): string {
    const { chapter, originalIndex, startMs } = params;
    const name = `${chapter}:${originalIndex}:${startMs}`;
    const nameBytes = new TextEncoder().encode(name);
    const combined = new Uint8Array(_NS_BYTES.length + nameBytes.length);
    combined.set(_NS_BYTES, 0);
    combined.set(nameBytes, _NS_BYTES.length);
    const hash = _sha1(combined);
    // Set version 5 (bits 4..7 of byte 6)
    hash[6] = (hash[6]! & 0x0f) | 0x50;
    // Set variant 10xx (bits 6..7 of byte 8)
    hash[8] = (hash[8]! & 0x3f) | 0x80;
    return _bytesToUuid(hash.slice(0, 16));
}

/** Backfill ``segment_uid`` on any segment in *segs* that lacks one.
 *
 * Mutates the segment objects in place.  ``chapter`` is the chapter number
 * for all segments in this call.  ``originalIndex`` is the position of the
 * segment within the chapter's ordered list (0-based).
 */
export function backfillSegmentUids(
    segs: Array<{ segment_uid?: string; time_start: number }>,
    chapter: number,
): void {
    for (let i = 0; i < segs.length; i++) {
        const seg = segs[i]!;
        if (!seg.segment_uid) {
            seg.segment_uid = deriveUid({
                chapter,
                originalIndex: i,
                startMs: seg.time_start,
            });
        }
    }
}
