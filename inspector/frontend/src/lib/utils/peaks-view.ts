/**
 * Tiny peaks-shape adapter.
 *
 * Peaks travel through the FE in two shapes today:
 *
 * 1. **Nested floats**: ``Array<[min, max]>`` (a.k.a. ``PeakBucket[]``). The
 *    per-segment ffmpeg fallback (``/segment-peaks``) emits this because those
 *    peaks are HD floats (30 bps) not quantizable to int8 without losing
 *    transient fidelity.
 *
 * 2. **Drawer-int8**: ``Int8Array`` of length ``n * 2``, with
 *    pairs interleaved ``[mn₀, mx₀, mn₁, mx₁, ...]``. Quantized to [-127, 127];
 *    dequant at read is ``v / 127``. The ``/peaks`` route emits the slim-packed
 *    int8 envelope verbatim; the FE decodes the b64 once into an ``Int8Array``
 *    (via ``peaks-decode.ts``) and every downstream read goes through this view.
 *
 * The view abstracts the per-sample read so the drawer hot path doesn't
 * branch on shape at every pixel — caller hits ``view.min(i)`` / ``view.max(i)``
 * and the right path is taken once at view construction. JIT inlines the
 * accessor when each call site is monomorphic (which they are in practice:
 * chapter overviews + history rows use the int8 shape; the per-segment ffmpeg
 * fallback uses the nested float shape).
 */
import type { PeakBucket } from '../types/peaks-transport';

/** Read-only random-access view over a peaks array, indexed in BUCKETS not bytes. */
export interface PeaksView {
    /** Number of [min, max] buckets. For Int8Array sources this is ``buf.length / 2``. */
    readonly length: number;
    /** Min component for bucket ``i``, in [-1, 1]. */
    min(i: number): number;
    /** Max component for bucket ``i``, in [-1, 1]. */
    max(i: number): number;
}

const _NESTED_DEFAULT: PeakBucket = [0, 0];

/**
 * Wrap a raw peaks payload in a uniform random-access view. The caller decides
 * the shape branch once (here), then the hot loop is shape-free.
 *
 * ``Int8Array`` is dequantized lazily per-sample (``v / 127``) — the alternative
 * was a one-time materialization to a Float32Array, but that costs ~3 MB per
 * husary-ch2-sized chapter and per-sample divide is sub-nanosecond in V8. If
 * profiling shows the divide matters, swap the int8 branch for a Float32Array
 * variant (variant B in the proposal).
 */
export function viewPeaks(peaks: PeakBucket[] | Int8Array | null | undefined): PeaksView | null {
    if (!peaks) return null;
    if (peaks instanceof Int8Array) {
        const buf = peaks;
        const n = buf.length >> 1;
        return {
            length: n,
            min(i: number): number {
                if (i < 0 || i >= n) return 0;
                return (buf[i * 2] ?? 0) / 127;
            },
            max(i: number): number {
                if (i < 0 || i >= n) return 0;
                return (buf[i * 2 + 1] ?? 0) / 127;
            },
        };
    }
    // Nested PeakBucket[] path.
    if (!Array.isArray(peaks) || peaks.length === 0) return null;
    const arr = peaks;
    return {
        length: arr.length,
        min(i: number): number {
            const bk = arr[i] ?? _NESTED_DEFAULT;
            return bk[0] ?? 0;
        },
        max(i: number): number {
            const bk = arr[i] ?? _NESTED_DEFAULT;
            return bk[1] ?? 0;
        },
    };
}

/** Cheap "is this shape int8" check without constructing a view. */
export function isInt8Peaks(peaks: PeakBucket[] | Int8Array | null | undefined): peaks is Int8Array {
    return peaks instanceof Int8Array;
}

function _q(v: number): number {
    const x = Math.round(v * 127);
    return x < -127 ? -127 : x > 127 ? 127 : x;
}

/**
 * Pack a peaks payload into base64 of ``n*2`` int8s — the canonical
 * ``edit_history_peaks.jsonl`` ``peaks_b64`` wire shape (inverse of
 * ``peaks-decode.ts::b64ToInt8``). An ``Int8Array`` is encoded as-is;
 * float buckets are quantized ``round(v*127)`` clamped to [-127, 127].
 * Used by the History on-play write-back to persist a freshly-computed
 * slice. History slices are small (≤ a few hundred buckets), so the
 * per-byte ``String.fromCharCode`` loop is the fastest portable path
 * (same rationale as ``b64ToInt8``).
 */
export function packPeaksB64(peaks: PeakBucket[] | Int8Array): string {
    let bytes: Int8Array;
    if (peaks instanceof Int8Array) {
        bytes = peaks;
    } else {
        bytes = new Int8Array(peaks.length * 2);
        for (let i = 0; i < peaks.length; i++) {
            const bk = peaks[i] ?? _NESTED_DEFAULT;
            bytes[i * 2] = _q(bk[0] ?? 0);
            bytes[i * 2 + 1] = _q(bk[1] ?? 0);
        }
    }
    const u8 = new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let bin = '';
    for (let i = 0; i < u8.length; i++) bin += String.fromCharCode(u8[i]!);
    return btoa(bin);
}
