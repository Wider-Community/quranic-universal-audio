/**
 * Shared slim-peaks decoder (cross-tab).
 *
 * Chapter peaks travel the wire in the slim envelope
 * ``{q:'int8', n, peaks_b64, bps, duration_ms}`` per audio URL. Both the
 * Segments tab (`utils/waveform/utils.ts::_fetchPeaks`) and the Timestamps tab
 * (`lib/utils/peaks-fetch.ts::ensureChapterPeaks`) decode through THIS one
 * function so the byte-level interpretation can never drift between tabs.
 */

/**
 * Decode a base64-encoded int8 buffer into a fresh ``Int8Array(n * 2)``.
 *
 * Why ``atob`` + ``charCodeAt``: fastest browser-portable path at chapter
 * scale (≤ 144 KB per chapter). ``Uint8Array.from`` with a callback pays a
 * function call per byte; ``Response.arrayBuffer`` has higher fixed overhead
 * than the loop saves below ~1 MB.
 */
export function b64ToInt8(b64: string, n: number): Int8Array {
    const bin = atob(b64);
    const len = Math.min(bin.length, n * 2);
    const out = new Int8Array(len);
    for (let i = 0; i < len; i++) {
        // charCodeAt returns 0-255; reinterpret as signed int8.
        out[i] = (bin.charCodeAt(i) << 24) >> 24;
    }
    return out;
}
