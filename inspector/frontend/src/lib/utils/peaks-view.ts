/**
 * Tiny peaks-shape adapter.
 *
 * Peaks travel through the FE in two shapes today:
 *
 * 1. **Legacy nested**: ``Array<[min, max]>`` (a.k.a. ``PeakBucket[]``). Server
 *    emits this when the client doesn't request the int8 shape, and the
 *    per-segment ffmpeg fallback (``/segment-peaks``) always emits it because
 *    those peaks are HD floats (30 bps) not quantizable to int8 without losing
 *    transient fidelity. History-peaks JSONL on the bucket also stores
 *    nested-list — backfilling that file is a separate proposal.
 *
 * 2. **Drawer-int8** (new, flag-gated): ``Int8Array`` of length ``n * 2``, with
 *    pairs interleaved ``[mn₀, mx₀, mn₁, mx₁, ...]``. Quantized to [-127, 127];
 *    dequant at read is ``v / 127``. The route now passes the slim-packed
 *    bytes verbatim under ``?shape=i8``, FE decodes once into ``Int8Array``,
 *    every downstream read goes through this view.
 *
 * The view abstracts the per-sample read so the drawer hot path doesn't
 * branch on shape at every pixel — caller hits ``view.min(i)`` / ``view.max(i)``
 * and the right path is taken once at view construction. JIT inlines the
 * accessor when each call site is monomorphic (which they are in practice:
 * chapter overviews always use one shape, history rows always use the other).
 */
import type { PeakBucket } from '../types/domain';

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
