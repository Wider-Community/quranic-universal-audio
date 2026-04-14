/**
 * Ad-hoc canvas extensions used by the segments waveform subsystem.
 *
 * Types have moved to lib/types/segments-waveform.ts (Wave 6b) so that
 * lib-layer components can reference them without importing from segments/.
 * This file re-exports everything so existing callers in segments/ are
 * unchanged.
 */

export type {
    MergeHighlight,
    SegCanvas,
    SplitData,
    SplitEls,
    SplitHighlight,
    TrimEls,
    TrimHighlight,
    TrimWindow,
} from '../../lib/types/segments-waveform';
