/**
 * Per-edition Quranic font loading.
 *
 * Each riwayah pairs with the exact font its script was typeset for. Rendering
 * Warsh's text in DigitalKhatt is not a cosmetic downgrade — the two disagree on
 * ligature and mark placement, so the words come out wrong.
 *
 * Hafs is not handled here. Its DigitalKhatt font ships inside the frontend
 * bundle as an inlined data URI, because HF Spaces do not smudge Git-LFS at
 * build time and the file would otherwise reach `dist/` as a 131-byte pointer.
 * The three edition fonts have no such problem: they are served by Flask out of
 * the packaged `qua_domain` wheel, so they load over the network like any other
 * asset. Inlining them too would add ~2.6 MB to every page load, including the
 * Hafs-only ones.
 *
 * The declared family name is the token `--font-quran`, set on the tab root, so
 * component CSS keeps naming a token rather than a font.
 */
import { DEFAULT_RIWAYAH, type InspectorRiwayah, isHafs } from '../riwayat';

/** Font family the Hafs path has always used; also the fallback chain's head. */
const HAFS_STACK = "'DigitalKhatt', 'Traditional Arabic', 'Scheherazade New', 'Amiri', serif";

const STYLE_ID = 'qua-edition-fonts';
const injected = new Set<InspectorRiwayah>();

const familyOf = (riwayah: InspectorRiwayah) => `QUAEdition-${riwayah}`;

/** The `--font-quran` value for an edition: its own face, then the shared fallbacks. */
export function editionFontStack(riwayah: InspectorRiwayah | null | undefined): string {
    if (!riwayah || isHafs(riwayah)) return HAFS_STACK;
    return `'${familyOf(riwayah)}', ${HAFS_STACK}`;
}

/**
 * Declare an `@font-face` for one edition, once per document.
 *
 * `font-display: swap` renders the fallback while the ~0.9 MB face downloads.
 * That briefly shows the right words in a near-enough script — acceptable — and
 * is why the stack still ends in the shared serif fallbacks rather than nothing.
 */
export function ensureEditionFont(riwayah: InspectorRiwayah | null | undefined): void {
    if (!riwayah || isHafs(riwayah) || injected.has(riwayah)) return;
    injected.add(riwayah);

    let style = document.getElementById(STYLE_ID) as HTMLStyleElement | null;
    if (!style) {
        style = document.createElement('style');
        style.id = STYLE_ID;
        document.head.appendChild(style);
    }
    const url = `/api/static/edition/${encodeURIComponent(riwayah)}/font`;
    style.textContent += `@font-face{font-family:'${familyOf(riwayah)}';`
        + `src:url('${url}');font-display:swap;}\n`;
}

/** Test-only: forget what has been injected so each case starts clean. */
export function _resetEditionFonts(): void {
    injected.clear();
    document.getElementById(STYLE_ID)?.remove();
}

export { DEFAULT_RIWAYAH, HAFS_STACK };
