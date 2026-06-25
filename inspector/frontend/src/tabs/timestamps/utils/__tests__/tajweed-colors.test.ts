import { describe, expect, it } from 'vitest';

import { isBridgeTag, KNOWN_UNCOLORED_TAGS, tajweedColorVar } from '../tajweed-colors';

describe('tajweed-colors', () => {
    it('maps each coloured rule to its --tj custom prop', () => {
        expect(tajweedColorVar('madd_wajib_muttasil')).toBe('var(--tj-madd-wajib)');
        expect(tajweedColorVar('madd_jaiz_munfasil')).toBe('var(--tj-madd-jaiz)');
        expect(tajweedColorVar('madd_lazim')).toBe('var(--tj-madd-lazim)');
        expect(tajweedColorVar('madd_arid_lissukun')).toBe('var(--tj-madd-arid)');
        expect(tajweedColorVar('madd_leen')).toBe('var(--tj-madd-leen)');
        expect(tajweedColorVar('idgham_ghunnah_noon')).toBe('var(--tj-idgham-ghunnah)');
        expect(tajweedColorVar('idgham_ghunnah_tanween')).toBe('var(--tj-idgham-ghunnah)');
        expect(tajweedColorVar('idgham_shafawi')).toBe('var(--tj-idgham-shafawi)');
        expect(tajweedColorVar('noon_ghunnah')).toBe('var(--tj-ghunnah)');
        expect(tajweedColorVar('meem_ghunnah')).toBe('var(--tj-ghunnah)');
        expect(tajweedColorVar('ikhfaa_noon')).toBe('var(--tj-ikhfaa)');
        expect(tajweedColorVar('iqlab_tanween')).toBe('var(--tj-iqlab)');
        expect(tajweedColorVar('ikhfaa_shafawi')).toBe('var(--tj-ikhfaa-shafawi)');
        expect(tajweedColorVar('izhar_halqi')).toBe('var(--tj-izhar-halqi)');
        expect(tajweedColorVar('izhar_shafawi')).toBe('var(--tj-izhar-shafawi)');
    });

    it('recognises shard-tagged uncoloured rules without colouring them', () => {
        for (const t of ['qalqala_sughra', 'qalqala_kubra', 'tafkheem', 'madd_tabii',
            'lam_shamsiyah', 'hamza_wasl_silent', 'silent_iltiqaa_sakinayn']) {
            expect(KNOWN_UNCOLORED_TAGS.has(t)).toBe(true);
            expect(tajweedColorVar(t)).toBeNull();
        }
    });

    it('returns null for uncoloured, structural, and absent tags', () => {
        for (const t of [
            'madd_tabii', 'idgham_bila_ghunnah_tanween', 'idgham_bila_ghunnah_noon',
            'idgham_mutamathilayn', 'madd_iwad', 'allah_dagger_alef', 'hamza_wasl_vowel',
            'iltiqaa', 'iltiqaa_kasra', 'qalqala', null, undefined,
        ]) {
            expect(tajweedColorVar(t)).toBeNull();
        }
    });

    it('flags cross-word idgham (bridge) tags', () => {
        expect(isBridgeTag('idgham_shafawi')).toBe(true);
        expect(isBridgeTag('idgham_ghunnah_noon')).toBe(true);
        expect(isBridgeTag('idgham_bila_ghunnah_tanween')).toBe(true);
        expect(isBridgeTag('madd_wajib_muttasil')).toBe(false);
        expect(isBridgeTag('noon_ghunnah')).toBe(false);
        expect(isBridgeTag(null)).toBe(false);
    });
});
