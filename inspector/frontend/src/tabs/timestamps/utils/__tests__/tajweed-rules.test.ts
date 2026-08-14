import { describe, expect, it } from 'vitest';
import {
    badgeForTag,
    badgesForTags,
    bridgeCellTag,
    DEFAULT_ENABLED,
    isBridgeTag,
    LEGEND,
    LEGEND_KEYS,
    legendRows,
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
        expect(tajweedColorVar('idgham_bi_ghunnah')).toBe('var(--tj-idgham-ghunnah)');
        expect(tajweedColorVar('ghunnah')).toBe('var(--tj-ghunnah)');
        expect(tajweedColorVar('iqlab')).toBe('var(--tj-iqlab)');
        expect(tajweedColorVar('izhar')).toBe('var(--tj-izhar-halqi)');
    });

    it('now colours the rules promoted in this pass', () => {
        expect(tajweedColorVar('tafkheem')).toBe('var(--tj-tafkheem)');
        expect(tajweedColorVar('madd_tabii')).toBe('var(--tj-madd-tabii)');
        expect(tajweedColorVar('qalqala_sughra')).toBe('var(--tj-qalqala)');
        expect(tajweedColorVar('qalqala_kubra')).toBe('var(--tj-qalqala)');
        expect(tajweedColorVar('idgham_bila_ghunnah')).toBe('var(--tj-idgham-bila)');
        expect(tajweedColorVar('idgham_mutajanisayn_kamil')).toBe('var(--tj-mutajanisayn)');
    });

    it('aliases allah-dagger-alef + madd-iwad to the madd-ṭabīʿī colour', () => {
        expect(tajweedColorVar('allah_dagger_alef')).toBe('var(--tj-madd-tabii)');
        expect(tajweedColorVar('madd_iwad')).toBe('var(--tj-madd-tabii)');
    });

    it('leaves the silent + structural rules uncoloured', () => {
        for (const t of ['hamza_wasl_elision', 'lam_shamsiyyah', 'pausal_sukun', 'hamza_wasl_kasra', 'iltiqaa_kasra']) {
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
        expect(badgesForTags(['madd_arid_lil_sukun', 'idgham_bila_ghunnah']).map((b) => b.legendKey)).toEqual(['madd_arid']);
        // tafkheem listed first still ends up on top
        expect(badgesForTags(['tafkheem', 'idgham_bila_ghunnah']).map((b) => b.legendKey)).toEqual(['idgham_bila', 'tafkheem']);
    });

    it('stacks base < merge < tafkheem (a consonant idgham rides ON the target rule)', () => {
        // ٱرْكَب مَّعَنَا: the receiving mīm sounds ghunnah (base) AND is the mutajānisayn
        // target (merge) — the merge bar sits above ghunnah, tafkheem above that.
        const b = badgesForTags(['ghunnah', 'idgham_mutajanisayn_kamil', 'tafkheem']);
        expect(b.map((x) => x.legendKey)).toEqual(['ghunnah', 'mutajanisayn', 'tafkheem']);
        expect(b.map((x) => x.stack)).toEqual(['base', 'merge', 'top']);
        expect(tjShadow(b, all)).toBe(
            'inset 0 -2px 0 var(--tj-ghunnah), inset 0 -4px 0 var(--tj-mutajanisayn), inset 0 -6px 0 var(--tj-tafkheem)',
        );
    });

    it('marks qalqala kubrā for the taller fill', () => {
        expect(badgeForTag('qalqala_kubra')!.kubra).toBe(true);
        expect(badgeForTag('qalqala_sughra')!.kubra).toBe(false);
    });

    it('drops uncolourable + null tags', () => {
        expect(badgesForTags(['lam_shamsiyyah', null, undefined])).toEqual([]);
    });
});

describe('tajweed-rules — tjShadow', () => {
    const badges: TjBadge[] = badgesForTags(['idgham_bila_ghunnah', 'tafkheem']);

    it('stacks inset bars bottom→top, accumulating the offset', () => {
        const shadow = tjShadow(badges, all);
        expect(shadow).toBe('inset 0 -2px 0 var(--tj-idgham-bila), inset 0 -4px 0 var(--tj-tafkheem)');
    });

    it('draws qalqala kubrā bottom bar identical to ṣughrā, plus a side-wrap colour', () => {
        const k = badgesForTags(['qalqala_kubra']);
        // kubrā's bottom bar is the SAME inset bar as ṣughrā; the ::after only wraps the edges
        expect(tjShadow(k, all)).toBe('inset 0 -2px 0 var(--tj-qalqala)');
        expect(tjKubraColor(k, all)).toBe('var(--tj-qalqala)');
        // ṣughrā draws the same bar but has no kubrā side-wrap
        const s = badgesForTags(['qalqala_sughra']);
        expect(tjShadow(s, all)).toBe('inset 0 -2px 0 var(--tj-qalqala)');
        expect(tjKubraColor(s, all)).toBe('');
    });

    it('a disabled qalqala drops both its kubrā bleed and the inset', () => {
        const k = badgesForTags(['qalqala_kubra']);
        expect(tjKubraColor(k, none)).toBe('');
    });

    it('stacks tafkheem above the kubrā bottom bar (both inset, side-wrap colour set)', () => {
        const kt = badgesForTags(['qalqala_kubra', 'tafkheem']);
        expect(tjShadow(kt, all)).toBe('inset 0 -2px 0 var(--tj-qalqala), inset 0 -4px 0 var(--tj-tafkheem)');
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

    it('dedups a name carried by both a badge and a silent name (the iwaḍ alef)', () => {
        const b = badgesForTags(['madd_iwad']); // badge tooltip "Madd 'Iwad"
        // even with madd-ṭabīʿī enabled, the badge + the always-on silent name collapse
        expect(tjRuleNames(b, ["Madd 'Iwad"], all)).toBe("Madd 'Iwad");
    });

    it('maps the silent rules to display names', () => {
        expect(silentTooltip('lam_shamsiyyah')).toBe('Lam Shamsiyyah');
        expect(silentTooltip('iltiqaa')).toBe("Iltiqa' 'as-sakinayn");
        expect(silentTooltip('iltiqaa_kasra')).toBe("Iltiqa' 'as-sakinayn");
        expect(silentTooltip('iqlab_silent_noon')).toBe('Iqlab'); // the iqlab silent ن
        expect(silentTooltip('madd_lazim')).toBeNull(); // coloured, not silent-only
    });

    it('uses the full second-pass tooltip spellings', () => {
        expect(badgeForTag('madd_jaiz_munfasil')!.tooltip()).toBe("Madd Ja'iz Munfassil");
        expect(badgeForTag('madd_wajib_muttasil')!.tooltip()).toBe('Madd Wajib Muttassil');
        expect(badgeForTag('madd_arid_lil_sukun')!.tooltip()).toBe("Madd 'Arid-lissukun");
        expect(badgeForTag('madd_tabii')!.tooltip()).toBe("Madd Tabi'i");
        expect(badgeForTag('izhar')!.tooltip()).toBe('Izhar Halqi');
        expect(badgeForTag('idgham_mutamathilayn')!.tooltip()).toBe('Idgham Mutamathilayn');
        expect(badgeForTag('idgham_mutajanisayn_naqis')!.tooltip()).toBe('Idgham Mutajanisayn Naqis');
    });

    it('legend labels use the full rule name in the Madd column', () => {
        const label = (k: string): string | undefined =>
            LEGEND.flatMap((g) => legendRows(g)).find((r) => r.legendKey === k)?.label();
        expect(label('madd_jaiz')).toBe("Madd Ja'iz Munfassil");
        expect(label('madd_wajib')).toBe('Madd Wajib Muttassil');
        expect(label('madd_arid')).toBe("Madd 'Arid-lissukun");
        expect(label('izhar')).toBe('Izhar Halqi');
    });

    it('groups into Noon / Meem, Madd, Other rules with idgham bila under Noon', () => {
        expect(LEGEND.map((g) => g.title())).toEqual(['Noon / Meem', 'Madd', 'Other rules']);
        const noonMeem = LEGEND.find((g) => g.category === 'noon_meem')!;
        const rows = legendRows(noonMeem);
        const bilaIdx = rows.findIndex((r) => r.legendKey === 'idgham_bila');
        const izharIdx = rows.findIndex((r) => r.legendKey === 'izhar');
        expect(bilaIdx).toBeGreaterThanOrEqual(0);
        expect(bilaIdx).toBe(izharIdx - 1); // idgham bila ghunnah sits just above izhar halqi
    });

    it('Noon / Meem splits into a Noon sub-section and a Meem (shafawi) sub-section', () => {
        const noonMeem = LEGEND.find((g) => g.category === 'noon_meem')!;
        expect(noonMeem.subgroups?.map((s) => s.title())).toEqual(['Noon', 'Meem']);
        const meem = noonMeem.subgroups!.find((s) => s.title() === 'Meem')!;
        expect(meem.rows.map((r) => r.legendKey)).toEqual([
            'ghunnah',
            'ikhfaa_shafawi',
            'idgham_shafawi',
            'izhar_shafawi',
        ]);
    });

    it('qalqala is two coupled rows sharing the qalqala key (one kubrā)', () => {
        const other = LEGEND.find((g) => g.category === 'other')!;
        const qalqala = legendRows(other).filter((r) => r.legendKey === 'qalqala');
        expect(qalqala.map((r) => r.label())).toEqual(['Qalqala Sughra', 'Qalqala Kubra']);
        expect(qalqala.filter((r) => r.kubra)).toHaveLength(1);
    });
});

describe('tajweed-rules — legend + defaults', () => {
    it('ghunnah + qalqala are the mirrored/repeated legendKeys; LEGEND_KEYS dedups them', () => {
        const keys = LEGEND.flatMap((g) => legendRows(g).map((r) => r.legendKey));
        const dups = keys.filter((k, i) => keys.indexOf(k) !== i);
        expect(dups).toEqual(['ghunnah', 'qalqala']);
        expect(new Set(LEGEND_KEYS).size).toBe(LEGEND_KEYS.length);
        for (const g of LEGEND) for (const r of legendRows(g)) expect(r.colorVar).toMatch(/^--tj-/);
    });

    it('defaults everything on except iẓhar and madd ṭabīʿī', () => {
        const off = LEGEND_KEYS.filter((k) => !DEFAULT_ENABLED[k]);
        expect(off.sort()).toEqual(['izhar', 'izhar_shafawi', 'madd_tabii'].sort());
    });
});

describe('tajweed-rules — bridge tags', () => {
    it('recognises the cross-word idgham mergers', () => {
        expect(isBridgeTag('idgham_shafawi')).toBe(true);
        expect(isBridgeTag('idgham_bila_ghunnah')).toBe(true);
        expect(isBridgeTag('idgham_mutajanisayn_naqis')).toBe(true);
        expect(isBridgeTag('ghunnah')).toBe(false);
        expect(isBridgeTag(null)).toBe(false);
    });

    it('folds the bridge vocabulary\'s noon/tanwīn split back onto one cell tag', () => {
        // A merger phone still names the origin; a cell tag does not.
        expect(bridgeCellTag('idgham_ghunnah_noon')).toBe('idgham_bi_ghunnah');
        expect(bridgeCellTag('idgham_ghunnah_tanween')).toBe('idgham_bi_ghunnah');
        expect(bridgeCellTag('idgham_bila_ghunnah_tanween')).toBe('idgham_bila_ghunnah');
        // the six spelt the same in both vocabularies pass straight through
        expect(bridgeCellTag('idgham_shafawi')).toBe('idgham_shafawi');
        expect(bridgeCellTag('idgham_mutajanisayn_kamil')).toBe('idgham_mutajanisayn_kamil');
        expect(bridgeCellTag(null)).toBeNull();
        // and every folded name resolves to a badge
        for (const b of ['idgham_ghunnah_noon', 'idgham_bila_ghunnah_noon', 'idgham_shafawi']) {
            expect(badgeForTag(bridgeCellTag(b))).not.toBeNull();
        }
    });
});

describe('tajweed-rules — special rules (the border channel)', () => {
    it('draws a full inset ring, and leaves the bar offsets alone', () => {
        const b = badgesForTags(['ghunnah', 'imala', 'tafkheem']);
        expect(b.map((x) => x.legendKey)).toEqual(['ghunnah', 'tafkheem', 'special']);
        expect(b.map((x) => x.stack)).toEqual(['base', 'top', 'border']);
        // the ring is drawn last (so the bars paint over it) and does NOT shift the
        // 2px/4px bar offsets a ghunnah+tafkheem cell would draw on its own.
        expect(tjShadow(b, all)).toBe(
            'inset 0 -2px 0 var(--tj-ghunnah), inset 0 -4px 0 var(--tj-tafkheem), inset 0 0 0 2px var(--tj-special)',
        );
        expect(tjShadow(badgesForTags(['ghunnah', 'tafkheem']), all)).toBe(
            'inset 0 -2px 0 var(--tj-ghunnah), inset 0 -4px 0 var(--tj-tafkheem)',
        );
    });

    it('shares one legend row + toggle across the four rules, each keeping its name', () => {
        for (const t of ['imala', 'ishmam', 'tashil', 'ibdal_hamza']) {
            expect(badgeForTag(t)!.legendKey).toBe('special');
            expect(badgeForTag(t)!.colorVar).toBe('--tj-special');
        }
        expect(badgeForTag('imala')!.tooltip()).toBe('Imala');
        expect(badgeForTag('ibdal_hamza')!.tooltip()).toBe('Ibdal al-Hamzah');
        // one row, under Other rules, and it is on by default
        const other = LEGEND.find((g) => g.category === 'other')!;
        const rows = legendRows(other).filter((r) => r.legendKey === 'special');
        expect(rows).toHaveLength(1);
        expect(rows[0]!.label()).toBe('Special rules');
        expect(rows[0]!.border).toBe(true);
        expect(DEFAULT_ENABLED.special).toBe(true);
        // the toggle gates the ring like any other bar
        expect(tjShadow(badgesForTags(['tashil']), (k) => k !== 'special')).toBe('');
    });
});

describe('tajweed-rules — the silent rules the producer now names', () => {
    it('names the waqf sukūn, the ʿiwaḍ madd and the orthographic silences', () => {
        expect(silentTooltip('pausal_sukun')).toBe('Waqf');
        expect(silentTooltip('orthographic_silence')).toBe("Silent Letter");
        expect(silentTooltip('madd_iwad')).toBe("Madd 'Iwad");
        expect(silentTooltip('pausal_alif')).toBe('Alif (waqf)');
        expect(silentTooltip('taa_marbuta_pausal')).toBe("Ta' Marbutah (waqf)");
        expect(silentTooltip('hamza_wasl_elision')).toBe('Hamzat-al-wasl (silent)');
    });

    it('keeps the ʿiwaḍ madd nameable while its bar is toggled off', () => {
        const b = badgesForTags(['madd_iwad']);
        expect(tjShadow(b, none)).toBe('');
        expect(tjRuleNames(b, [silentTooltip('madd_iwad')!], none)).toBe("Madd 'Iwad");
    });
});
