import type { EditOp } from '../../../lib/types/domain';

/**
 * Canonical history-peaks record — the SAME shape the inspector uses
 * everywhere (``edit_history_peaks.jsonl`` and the FE `indexHistoryPeaksRecords`
 * consumer in `utils/waveform/utils.ts`): base64 of n×2 int8s at `bps` density.
 * No inflated float array — that drift is why the old synthetic examples never
 * rendered.
 */
export interface GuidePeakRecord {
    op_id: string;
    url: string;
    start_ms: number;
    end_ms: number;
    bps: number;
    peaks_b64: string;
}

/**
 * A read-only context group rendered as muted cards beside the op diff — e.g.
 * the untouched clean occurrence of a verse (failed-on-purpose examples) or the
 * ±1 neighbour that makes a single-word edit legible (low-confidence).
 * `segments` are history-snapshot dicts (`time_start`/`time_end`/`matched_ref`/
 * `audio_url`/`segment_uid`), same shape as an op's `targets_*`.
 */
export interface GuideContextGroup {
    label: string;
    position: 'before' | 'after';
    segments: Array<Record<string, unknown>>;
}

export interface GuideExample {
    id: string;
    title: string;
    description?: string;
    render: 'history_op' | 'edit_chain';
    chapter: number | null;
    /**
     * The clip's file-start in original ms. Playback rebases the AudioRange by
     * this so the short same-origin `/guide-audio/` clip plays correctly while
     * the cards still display the original absolute timestamps.
     */
    clip_base_ms?: number;
    operations: EditOp[];
    peaks?: GuidePeakRecord[];
    context?: GuideContextGroup[];
}

export type GuideBlock =
    | { type: 'heading'; level: 1 | 2; text: string }
    | { type: 'paragraph'; text: string }
    | { type: 'example'; id: string }
    | { type: 'missing'; message: string };
