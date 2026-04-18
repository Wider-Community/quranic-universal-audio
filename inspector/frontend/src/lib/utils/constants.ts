/**
 * Shared constants: localStorage keys and placeholder strings.
 */

export const LS_KEYS = {
    ACTIVE_TAB:      'insp_active_tab',
    TS_RECITER:      'insp_ts_reciter',
    TS_SPEED:        'insp_ts_speed',
    TS_VIEW_MODE:    'insp_ts_view_mode',
    TS_SHOW_LETTERS: 'insp_ts_show_letters',
    TS_SHOW_PHONEMES:'insp_ts_show_phonemes',
    TS_GRANULARITY:  'insp_ts_granularity',
    SEG_RECITER:     'insp_seg_reciter',
    SEG_SPEED:       'insp_seg_speed',
    SEG_AUTOPLAY:    'insp_seg_autoplay',
    AUD_RECITER:     'insp_aud_reciter',
} as const;

export const PLACEHOLDER_SELECT = '-- select --';
export const PLACEHOLDER_DASH   = '--';
export const PLACEHOLDER_RECITER = '-- Select reciter --';

// Audio buffer cache eviction limit
export const AUDIO_BUFFER_CACHE_SIZE = 5;

// Playhead color used in the edit-mode preview overlay (trim / split / play-range)
export const PREVIEW_PLAYHEAD_COLOR = '#f72585';
