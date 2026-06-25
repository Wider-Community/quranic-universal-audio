import { describe, expect, it } from 'vitest';
import {
    badgeForTag,
    badgesForTags,
    DEFAULT_ENABLED,
    isBridgeTag,
    LEGEND,
    LEGEND_KEYS,
    silentTooltip,
    tajweedColorVar,
    tjKubraColor,
    tjRuleNames,
    tjShadow,
    type TjBadge,
} from '../tajweed-rules';

const all = (_k: string): boolean => true;
const none = (_k: string): boolean => false;

describe('tajweed-rules — colour map', () => {
    it('keeps the existing tag → CSS-var mapping', () => {
        expect(tajweedColorVar('madd_wajib_muttasil')).toBe('var(--tj-madd-wajib)');
        expect(tajweedColorVar('idgham_ghunnah_tanween')).toBe('var(--tj-idgham-ghunnah)');
        expect(tajweedColorVar('noon_ghunnah')).toBe('var(--tj-ghunnah)');
        expect(tajweedColorVar('iqlab_tanween')).toBe('var(--tj-iqlab)');
        expect(tajweedColorVar('izhar_halqi')).toBe('var(--tj-izhar-halqi)');
    });

    it('now colours the rules promoted in this pass', () => {
        expect(tajweedColorVar('tafkheem')).toBe('var(--tj-tafkheem)');
        expect(tajweedColorVar('madd_tabii')).toBe('var(--tj-madd-tabii)');
        expect(tajweedColorVar('qalqala_sughra')).toBe('var(--tj-qalqala)');
        expect(tajweedColorVar('qalqala_kubra')).toBe('var(--tj-qalqala)');
        expect(tajweedColorVar('idgham_bila_ghunnah_noon')).toBe('var(--tj-idgham-bila)');
        expect(tajweedColorVar('idgham_mutajanisayn_kamil')).toBe('var(--tj-mutajanisayn)');
    });

    it('aliases allah-dagger-alef + madd-iwad to the madd-ṭabīʿī colour', () => {
        expect(tajweedColorVar('allah_dagger_alef')).toBe('var(--tj-madd-tabii)');
        expect(tajweedColorVar('madd_iwad')).toBe('var(--tj-madd-tabii)');
    });

    it('leaves the silent + structural rules uncoloured', () => {
        for (const t of ['vowel_silent', 'hamza_wasl_silent', 'lam_shamsiyah', 'silent_iltiqaa_sakinayn', 'hamza_wasl_vowel', 'iltiqaa_kasra']) {
            expect(tajweedColorVar(t)).toBeNull();
        }
        expect(tajweedColorVar(null)).toBeNull();
    });
});

describe('tajweed-rules — badge stacking', () => {
    it('orders a base rule below tafkheem (≤2 bars, tafkheem on top)', () => {
        const badges = badgesForTags(['qalqala_sughra', 'tafkheem']);
        expect(badges.map((b) => b.legendKey)).toEqual(['qalqala', 'tafkheem']);
        expect(badges[1]!.stack).toBe('top');
    });

    it('the first colourable base tag wins (own over propagated); order-independent for tafkheem', () => {
        // a cell carrying its own madd + a propagated idgham keeps the FIRST base
        expect(badgesForTags(['madd_arid_lissukun', 'idgham_bila_ghunnah_noon']).map((b) => b.legendKey)).toEqual(['madd_arid']);
        // tafkheem listed first still ends up on top
        expect(badgesForTags(['tafkheem', 'idgham_bila_ghunnah_noon']).map((b) => b.legendKey)).toEqual(['idgham_bila', 'tafkheem']);
    });

    it('marks qalqala kubrā for the taller fill', () => {
        expect(badgeForTag('qalqala_kubra')!.kubra).toBe(true);
        expect(badgeForTag('qalqala_sughra')!.kubra).toBe(false);
    });

    it('drops uncolourable + null tags', () => {
        expect(badgesForTags(['lam_shamsiyah', null, undefined])).toEqual([]);
    });
});

describe('tajweed-rules — tjShadow', () => {
    const badges: TjBadge[] = badgesForTags(['idgham_bila_ghunnah_noon', 'tafkheem']);

    it('stacks inset bars bottom→top, accumulating the offset', () => {
        const shadow = tjShadow(badges, all);
        expect(shadow).toBe('inset 0 -2px 0 var(--tj-idgham-bila), inset 0 -4px 0 var(--tj-tafkheem)');
    });

    it('draws qalqala kubrā as a side-bleeding ::after, not an inset bar', () => {
        const k = badgesForTags(['qalqala_kubra']);
        expect(tjShadow(k, all)).toBe(''); // no inset bar — the ::after draws it
        expect(tjKubraColor(k, all)).toBe('var(--tj-qalqala)');
        // ṣughrā is a normal inset bar with no kubrā ::after
        const s = badgesForTags(['qalqala_sughra']);
        expect(tjShadow(s, all)).toBe('inset 0 -2px 0 var(--tj-qalqala)');
        expect(tjKubraColor(s, all)).toBe('');
    });

    it('a disabled qalqala drops both its kubrā bleed and the inset', () => {
        const k = badgesForTags(['qalqala_kubra']);
        expect(tjKubraColor(k, none)).toBe('');
    });

    it('stacks tafkheem above a kubrā bleed — kubrā reserves its height, tafkheem insets', () => {
        const kt = badgesForTags(['qalqala_kubra', 'tafkheem']);
        expect(tjShadow(kt, all)).toBe('inset 0 -4px 0 var(--tj-tafkheem)');
        expect(tjKubraColor(kt, all)).toBe('var(--tj-qalqala)');
    });

    it('filters by the enabled set (a disabled rule drops its bar)', () => {
        const onlyTafkheem = tjShadow(badges, (k) => k === 'tafkheem');
        // with the base dropped, tafkheem becomes the lone (bottom) bar
        expect(onlyTafkheem).toBe('inset 0 -2px 0 var(--tj-tafkheem)');
        expect(tjShadow(badges, none)).toBe('');
    });
});

describe('tajweed-rules — tooltip names', () => {
    it('joins enabled coloured names + silent names by newline', () => {
        const badges = badgesForTags(['qalqala_kubra', 'tafkheem']);
        expect(tjRuleNames(badges, [], all)).toBe('Qalqala Kubra\nTafkheem');
        expect(tjRuleNames(badges, ['Iltiqa\' \'as-sakinayn'], (k) => k === 'qalqala'))
            .toBe('Qalqala Kubra\nIltiqa\' \'as-sakinayn');
    });

    it('maps the silent rules to display names', () => {
        expect(silentTooltip('lam_shamsiyah')).toBe('Lam Shamsiyyah');
        expect(silentTooltip('silent_iltiqaa_sakinayn')).toBe("Iltiqa' 'as-sakinayn");
        expect(silentTooltip('iltiqaa_kasra')).toBe("Iltiqa' 'as-sakinayn");
        expect(silentTooltip('madd_lazim')).toBeNull(); // coloured, not silent-only
    });
});

describe('tajweed-rules — legend + defaults', () => {
    it('every legend row resolves to a colour var, no duplicate keys', () => {
        const keys = LEGEND.flatMap((g) => g.rows.map((r) => r.legendKey));
        expect(new Set(keys).size).toBe(keys.length);
        for (const g of LEGEND) for (const r of g.rows) expect(r.colorVar).toMatch(/^--tj-/);
    });

    it('defaults everything on except iẓhar and madd ṭabīʿī', () => {
        const off = LEGEND_KEYS.filter((k) => !DEFAULT_ENABLED[k]);
        expect(off.sort()).toEqual(['izhar', 'izhar_shafawi', 'madd_tabii'].sort());
    });
});

describe('tajweed-rules — bridge tags', () => {
    it('recognises the cross-word idgham mergers', () => {
        expect(isBridgeTag('idgham_shafawi')).toBe(true);
        expect(isBridgeTag('idgham_bila_ghunnah_tanween')).toBe(true);
        expect(isBridgeTag('idgham_mutajanisayn_naqis')).toBe(true);
        expect(isBridgeTag('noon_ghunnah')).toBe(false);
        expect(isBridgeTag(null)).toBe(false);
    });
});
