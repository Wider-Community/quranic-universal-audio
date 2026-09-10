import { afterEach, describe, expect, it } from 'vitest';

import {
    _resetEditionFonts,
    editionFontStack,
    ensureEditionFont,
    HAFS_STACK,
} from '../edition-font';

const injectedCss = () => document.getElementById('qua-edition-fonts')?.textContent ?? '';

describe('edition fonts', () => {
    afterEach(_resetEditionFonts);

    it('leaves Hafs on the bundled DigitalKhatt stack', () => {
        // DigitalKhatt is inlined in the bundle because HF Spaces do not smudge
        // Git-LFS at build time; it must not be re-fetched over the network.
        expect(editionFontStack('hafs_an_asim')).toBe(HAFS_STACK);
        ensureEditionFont('hafs_an_asim');
        expect(document.getElementById('qua-edition-fonts')).toBeNull();
    });

    it('falls back to the Hafs stack before a delivery is known', () => {
        expect(editionFontStack(null)).toBe(HAFS_STACK);
        expect(editionFontStack(undefined)).toBe(HAFS_STACK);
    });

    it('puts the edition face ahead of the shared fallbacks', () => {
        // The fallbacks stay so `font-display: swap` has something to paint
        // during the ~0.9 MB download.
        expect(editionFontStack('warsh_an_nafi')).toBe(`'QUAEdition-warsh_an_nafi', ${HAFS_STACK}`);
    });

    it('declares one @font-face per edition pointing at the Flask route', () => {
        ensureEditionFont('warsh_an_nafi');
        const css = injectedCss();
        expect(css).toContain("font-family:'QUAEdition-warsh_an_nafi'");
        expect(css).toContain("url('/api/static/edition/warsh_an_nafi/font')");
        expect(css).toContain('font-display:swap');
    });

    it('never declares the same edition twice', () => {
        ensureEditionFont('warsh_an_nafi');
        ensureEditionFont('warsh_an_nafi');
        expect(injectedCss().match(/@font-face/g)).toHaveLength(1);
    });

    it('keeps two editions apart in one document', () => {
        ensureEditionFont('warsh_an_nafi');
        ensureEditionFont('qalon_an_nafi');
        const css = injectedCss();
        expect(css.match(/@font-face/g)).toHaveLength(2);
        // Warsh and Qalun share a script but not a font file.
        expect(css).toContain('/api/static/edition/qalon_an_nafi/font');
    });
});
