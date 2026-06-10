/**
 * Peaks / waveform transport types — FE-only.
 *
 * The Int8Array drawer branch of `AudioPeaks` has no wire model (the server
 * emits nested `[[min, max], ...]` lists; the int8 envelope is assembled
 * client-side under the flag-gated drawer path), so these stay real FE
 * definitions rather than codegen'd aliases.
 */

/** A single peak bucket: [min, max] pair. Server rounds to 4 decimal places. */
export type PeakBucket = [number, number];

/** Pre-computed waveform peaks for an audio URL (full-file).
 *  Server emits `peaks: [[min, max], ...]` — see `services/peaks.py`. B19.
 *
 *  Under the flag-gated drawer-int8 path (``localStorage.peaksInt8Drawer === '1'``)
 *  ``peaks`` is an ``Int8Array(n * 2)`` instead — interleaved min/max bytes
 *  in [-127, 127]. The hot-path drawer reads it via ``peaks-view.ts``
 *  (one branch at view construction, then shape-free per-pixel reads).
 *  Per-segment peaks (ffmpeg fallback) and history-peaks JSONL stay nested
 *  list — see ``docs/proposals/peaks-int8-drawer.md``. */
export interface AudioPeaks {
    peaks: PeakBucket[] | Int8Array;
    duration_ms: number;
    /** Start offset of this chunk within the audio file (ms). Present on per-segment peaks;
     *  absent/0 for full-file peaks. Drawing must subtract this from seg.time_start/time_end
     *  before slicing into the peaks array. */
    start_ms?: number;
}

/** Peaks for a segment sub-range fetched via HTTP Range. */
export interface SegmentPeaks {
    peaks: PeakBucket[];
    start_ms: number;
    end_ms: number;
    duration_ms: number;
}
