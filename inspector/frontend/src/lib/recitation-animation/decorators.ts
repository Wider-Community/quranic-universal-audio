/**
 * Non-recited decorator marks for the recitation teleprompter.
 *
 * Some glyphs in the Quranic text are NOT recited — waqf (stop) signs, the
 * rub-el-hizb section marker (۞), the place-of-sajdah mark (۩). They must render
 * in the line but never take a per-letter highlight cell: they carry no MFA
 * timing, so a cell for them would fall back to whole-word timing and stay lit
 * for the entire word. This module is the single registry of those marks. Each
 * maps to a role, a placement (rendered before or after the word's letters), and
 * whether it lights while a pause holds on its word. `splitDecorators` pulls them
 * out of a word's text so only the recited `clean` text becomes highlight cells.
 * Adding a future non-recited mark is a one-line registry entry.
 *
 * Waqf codepoints are reused from `utils/waqf.ts` (the shared stop-sign source,
 * also consumed by the Timestamps tab); rub/sajdah are teleprompter-only.
 */

import { STOP_MARKS } from '../utils/waqf';

export type DecoratorRole = 'waqf' | 'rub' | 'sajdah';
export type DecoratorPlacement = 'leading' | 'trailing';

export interface DecoratorSpec {
    role: DecoratorRole;
    placement: DecoratorPlacement;
    /** Whether the mark lights with the highlight while a pause holds on its word. */
    litOnPause: boolean;
}

/** ARABIC START OF RUB EL HIZB (۞) — a quarter-hizb section marker at a verse head. */
const RUB_EL_HIZB = 0x06de;
/** ARABIC PLACE OF SAJDAH (۩) — a prostration marker at a verse tail. */
const SAJDAH = 0x06e9;

/** Codepoint → how to render it as an isolated, non-highlighting decorator. */
export const DECORATOR_MARKS: ReadonlyMap<number, DecoratorSpec> = new Map<number, DecoratorSpec>([
    ...[...STOP_MARKS].map(
        (cp): [number, DecoratorSpec] => [
            cp,
            { role: 'waqf', placement: 'trailing', litOnPause: true },
        ],
    ),
    [RUB_EL_HIZB, { role: 'rub', placement: 'leading', litOnPause: false }],
    [SAJDAH, { role: 'sajdah', placement: 'trailing', litOnPause: false }],
]);

export interface Decorator {
    glyph: string;
    role: DecoratorRole;
    placement: DecoratorPlacement;
}

export interface SplitDecorators {
    /** Text with every decorator mark removed — what the reveal actually animates. */
    clean: string;
    /** Decorators rendered before the word's letters, in source order. */
    leading: Decorator[];
    /** Decorators rendered after the word's letters, in source order. */
    trailing: Decorator[];
}

/**
 * Pull every registered decorator mark out of `text`, bucketing each by its
 * registry-declared placement. `clean` is the remaining recited text.
 */
export function splitDecorators(text: string): SplitDecorators {
    let clean = '';
    const leading: Decorator[] = [];
    const trailing: Decorator[] = [];
    for (const ch of text) {
        const cp = ch.codePointAt(0);
        const spec = cp !== undefined ? DECORATOR_MARKS.get(cp) : undefined;
        if (spec) {
            const deco: Decorator = { glyph: ch, role: spec.role, placement: spec.placement };
            (spec.placement === 'leading' ? leading : trailing).push(deco);
            continue;
        }
        clean += ch;
    }
    return { clean, leading, trailing };
}
