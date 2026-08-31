import { describe, expect, it } from 'vitest';

import catalogue from '../../data/rules.json';
import {
    badgeForTag,
    DEFAULT_ENABLED,
    defineInspectorRule,
    LEGEND,
    LEGEND_KEYS,
    legendRows,
    silentTooltip,
    tagsForLegend,
    tajweedColorVar,
} from '../tajweed-rules';

describe('Inspector native rule policy', () => {
    it('classifies every producer rule and rejects unknown IDs', () => {
        expect(catalogue).toHaveLength(45);
        for (const rule of catalogue) expect(defineInspectorRule(rule.id).id).toBe(rule.id);
        expect(() => defineInspectorRule('future_rule')).toThrow('Unknown producer rule');
    });

    it('preserves the explicit Noon, Meem, Madd, and Other legend grouping', () => {
        expect(LEGEND.map((group) => group.category)).toEqual(['noon_meem', 'madd', 'other']);
        const noonMeem = LEGEND[0]!;
        expect(noonMeem.subgroups?.map((group) => group.title())).toEqual(['Noon', 'Meem']);
        expect(LEGEND[1]!.rows?.map((row) => row.legendKey)).toEqual([
            'madd_lazim', 'madd_wajib', 'madd_jaiz', 'madd_arid', 'madd_leen', 'madd_tabii',
        ]);
        expect(legendRows(LEGEND[2]!).filter((row) => row.legendKey === 'mutajanisayn'))
            .toHaveLength(1);
    });

    it('defaults only izhar, izhar shafawi, and madd tabii off', () => {
        const off = LEGEND_KEYS.filter((key) => !DEFAULT_ENABLED[key]).sort();
        expect(off).toEqual(['izhar', 'izhar_shafawi', 'madd_tabii']);
    });

    it('keeps hover-only rules out of underlines and legend toggles', () => {
        for (const id of ['madd_iwad', 'tarqeeq', 'lam_shamsiyyah', 'hamza_wasl_kasra',
            'iltiqa_haraka', 'waqf_diacritic_drop', 'variant_silence']) {
            expect(tajweedColorVar(id)).toBeNull();
            expect(badgeForTag(id)).toBeNull();
            expect(silentTooltip(id)).not.toBeNull();
        }
    });

    it('uses the kubra wrap treatment and shared toggle for qalqala akbar', () => {
        const definition = defineInspectorRule('qalqala_akbar');
        expect(definition).toMatchObject({ legend_key: 'qalqala', visual: 'wrap' });
        expect(tagsForLegend('qalqala')).toEqual(new Set([
            'qalqala_sughra', 'qalqala_kubra', 'qalqala_akbar',
        ]));
        expect(legendRows(LEGEND[2]!).filter((row) => row.legendKey === 'qalqala'))
            .toHaveLength(2);
    });

    it('combines special and naqis/kamil policies without changing native IDs', () => {
        for (const id of ['imala', 'tashil', 'ishmam', 'ibdal_hamza']) {
            expect(defineInspectorRule(id).legend_key).toBe('special');
        }
        expect(defineInspectorRule('idgham_mutajanisayn_kamil').legend_key).toBe('mutajanisayn');
        expect(defineInspectorRule('idgham_mutajanisayn_naqis').legend_key).toBe('mutajanisayn');
    });
});
