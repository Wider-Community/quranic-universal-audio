/**
 * Waqf (stop) signs lifted out of the reveal text so they can be styled on their
 * own — revealed after recitation passes them, and lit while a pause holds. A
 * waqf glyph is a combining mark, so it can't be recoloured in place (it shares
 * its base letter's shaped run); it is pulled out and re-rendered on an invisible
 * word joiner as its own styleable glyph. Non-combining symbols that must NOT
 * move (rub-el-hizb, sajdah) are handled the opposite way — left in the reveal
 * text as inert cells (see engine/build-structure), never repositioned.
 */

import { STOP_MARKS } from '../utils/waqf';

export type DecoratorRole = 'waqf';
export type DecoratorPlacement = 'leading' | 'trailing';

export interface DecoratorSpec {
    role: DecoratorRole;
    placement: DecoratorPlacement;
    /** Whether the mark lights with the highlight while a pause holds on its word. */
    litOnPause: boolean;
}

/** Codepoint -> how to render it as an isolated, styleable decorator. */
export const DECORATOR_MARKS: ReadonlyMap<number, DecoratorSpec> = new Map(
    [...STOP_MARKS].map(
        (cp): [number, DecoratorSpec] => [cp, { role: 'waqf', placement: 'trailing', litOnPause: true }],
    ),
);

export interface Decorator {
    glyph: string;
    role: DecoratorRole;
    placement: DecoratorPlacement;
}

export interface SplitDecorators {
    /** Text with every decorator mark removed - what the reveal actually animates. */
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
