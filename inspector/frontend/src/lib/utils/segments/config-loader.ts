import { fetchJsonOrNull } from '../../api';
import { segConfig } from '../../stores/segments/config';

type SegConfigApiResponse = {
    seg_font_size?: string;
    seg_word_spacing?: string;
    trim_pad_left?: number;
    trim_pad_right?: number;
    trim_dim_alpha?: number;
    show_boundary_phonemes?: boolean;
    validation_categories?: string[];
    low_conf_default_threshold?: number;
    muqattaat_verses?: Array<[number, number]>;
    qalqala_letters?: string[];
    standalone_refs?: Array<[number, number, number]>;
    standalone_words?: string[];
    accordion_context?: Record<string, string>;
};

/**
 * Fetch `/api/seg/config`, push parsed values to `segConfig` store,
 * and return CSS var strings `{ fontSize, wordSpacing }` so the tab can
 * apply them to its root element.
 */
export async function loadSegConfig(): Promise<{ fontSize: string; wordSpacing: string }> {
    try {
        const cfg = await fetchJsonOrNull<SegConfigApiResponse>('/api/seg/config');
        if (!cfg) return { fontSize: '', wordSpacing: '' };
        segConfig.set({
            validationCategories: cfg.validation_categories ?? null,
            muqattaatVerses: cfg.muqattaat_verses ? new Set(cfg.muqattaat_verses.map(([s, a]) => `${s}:${a}`)) : null,
            qalqalaLetters: cfg.qalqala_letters ? new Set(cfg.qalqala_letters) : null,
            standaloneRefs: cfg.standalone_refs ? new Set(cfg.standalone_refs.map(([s, a, w]) => `${s}:${a}:${w}`)) : null,
            standaloneWords: cfg.standalone_words ? new Set(cfg.standalone_words) : null,
            lcDefaultThreshold: cfg.low_conf_default_threshold ?? 80,
            showBoundaryPhonemes: cfg.show_boundary_phonemes ?? true,
            accordionContext: cfg.accordion_context ?? null,
            trimPadLeft: cfg.trim_pad_left ?? 500,
            trimPadRight: cfg.trim_pad_right ?? 500,
            trimDimAlpha: cfg.trim_dim_alpha ?? 0.45,
        });
        return {
            fontSize: cfg.seg_font_size ? String(cfg.seg_font_size) : '',
            wordSpacing: cfg.seg_word_spacing ? String(cfg.seg_word_spacing) : '',
        };
    } catch {
        return { fontSize: '', wordSpacing: '' };
    }
}
