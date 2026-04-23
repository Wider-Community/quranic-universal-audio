/** Hardcoded confidence coloring cutoffs (not user-adjustable). */
export const CONF_HIGH_THRESHOLD = 0.80;
export const CONF_MID_THRESHOLD = 0.60;

/** Virtualized list: extra rows rendered above/below the visible viewport. */
export const VIRT_BUFFER_ROWS = 8;

/** ValidationPanel: skip virtualization for category lists smaller than this —
 *  overhead not worth it, and virtualization also evicts mid-edit rows which
 *  breaks accordion-initiated editing flows. */
export const VAL_VIRTUALIZE_THRESHOLD = 40;

/** Snap grid resolution for trim/split drag (ms). */
export const EDIT_SNAP_MS = 10;
/** Minimum segment duration after trim/split (ms). */
export const EDIT_MIN_DURATION_MS = 50;
/** Step size for the trim-panel cursor nudge buttons (ms). One press of a
 *  start/end stepper moves the boundary by this amount (clamped to the trim
 *  window + EDIT_MIN_DURATION_MS against the opposite handle). Independent
 *  of EDIT_SNAP_MS — drag snaps because pixel→time is fuzzy; the steppers
 *  give a coarser-but-deterministic nudge. */
export const EDIT_NUDGE_MS = 50;
/** Hit radius for trim drag handles (px). */
export const TRIM_HANDLE_HIT_RADIUS_PX = 12;

/** Minimum visible window for trim-canvas mouse-wheel zoom (ms). At this
 *  width, further wheel-in is a no-op. 500 ms keeps even fast-recitation
 *  word-boundaries comfortably resolvable on the ~380 px-wide canvas
 *  (≈ 1.3 ms / px → ≈ 38× the precision of the un-zoomed view). */
export const TRIM_MIN_VIEW_MS = 500;

/** Multiplicative factor per wheel tick on the trim canvas. Wheel-in (deltaY < 0)
 *  multiplies the visible range by this, wheel-out divides — symmetric so a
 *  zoom-in followed by an equal zoom-out lands exactly back at the original
 *  width (modulo float). 0.85 → ~6 ticks to halve the view, which feels
 *  responsive without overshooting on a single mouse-wheel notch. */
export const TRIM_WHEEL_ZOOM_FACTOR = 0.85;

/** Canvas dimensions for segment row waveforms. */
export const SEG_ROW_CANVAS_WIDTH = 380;
export const SEG_ROW_CANVAS_HEIGHT = 60;

/** Segments below this duration trigger a warning highlight in the stats chart. */
export const SHORT_SEG_WARN_MS = 1000;

/** VAD min-silence fallback when server does not provide the value. */
export const VAD_MIN_SILENCE_FALLBACK_MS = 300;

/** ArrowLeft / ArrowRight audio seek delta, in seconds. */
export const KEY_SEEK_SECONDS = 3;

/** How long (ms) the .playing flash stays on a row after a jump completes. */
export const FLASH_DURATION_MS = 2000;

/** Autoplay inter-segment pause (ms). When continuous-play advances from one
 *  segment to the next on the same audio file, we pause the audio briefly,
 *  jump the highlight to the next row, then seek + resume at the next seg's
 *  time_start. This gives the user an audible + visual "advancing" cue and
 *  skips the inter-seg gap audio (trimmed-out region or naturally-silent
 *  boundary) that browsers would otherwise play straight through. */
export const AUTOPLAY_GAP_PAUSE_MS = 200;

/** Max passes for the split-group transitive closure walk. Bounds iteration on
 *  malformed history where a split op's before/after UIDs form a cycle. A
 *  single split adds at most one generation of children, so 8 passes covers
 *  any realistic chain depth (root → halves → halves → ...). */
export const SPLIT_GROUP_MAX_PASSES = 8;

export const EDIT_OP_LABELS: Record<string, string> = {
    trim_segment: 'Boundary adjustment', split_segment: 'Split',
    merge_segments: 'Merge', delete_segment: 'Deletion',
    edit_reference: 'Reference edit', confirm_reference: 'Reference confirmation',
    auto_fix_missing_word: 'Auto-fill missing word', ignore_issue: 'Ignored issue',
    waqf_sakt: 'Waqf sakt merge', remove_sadaqa: 'Remove Sadaqa',
};

export const ERROR_CAT_LABELS: Record<string, string> = {
    failed: 'Failed', low_confidence: 'Low confidence',
    boundary_adj: 'Boundary adj.',
    cross_verse: 'Cross-verse', missing_words: 'Missing words',
    audio_bleeding: 'Audio bleeding',
    repetitions: 'Repetitions',
    muqattaat: 'Muqattaat letters',
    qalqala: 'Qalqala',
};

export const SEG_FILTER_OPS: readonly string[] = ['>', '>=', '<', '<=', '='];

export const _VAL_SINGLE_INDEX_CATS: readonly string[] = [
    'failed', 'low_confidence', 'boundary_adj', 'cross_verse',
    'audio_bleeding', 'repetitions', 'muqattaat', 'qalqala',
];

export const _ARABIC_DIGITS: readonly string[] = ['\u0660','\u0661','\u0662','\u0663','\u0664','\u0665','\u0666','\u0667','\u0668','\u0669'];

export const _MN_RE = /[\u0300-\u036F\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7-\u06E8\u06EA-\u06ED\u08D3-\u08FF\uFE20-\uFE2F]/;
export const _STRIP_CHARS: ReadonlySet<string> = new Set(['\u0640', '\u06DE', '\u06E6', '\u06E9', '\u200F']);
export const _LETTER_RE = /\p{L}/u;
