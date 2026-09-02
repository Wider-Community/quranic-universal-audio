/**
 * Display text for special (non-Quran-ref) segments — `matched_ref` tokens
 * like `Basmala` or the fused `Isti'adha+Basmala`. Mirrors the SDK's
 * `SPECIAL_TEXT` / `TRANSITION_TEXT` tables. Reciter deliveries have these
 * stripped by the post-pass; uploaded samples keep them.
 */

const SPECIAL_TEXT: Readonly<Record<string, string>> = {
    "Isti'adha": 'أَعُوذُ بِٱللَّهِ مِنَ الشَّيْطَانِ الرَّجِيم',
    Basmala: 'بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيم',
    Amin: 'آمِين',
    Takbir: 'اللَّهُ أَكْبَر',
    Tahmeed: 'سَمِعَ اللَّهُ لِمَنْ حَمِدَه',
    Tasleem: 'ٱلسَّلَامُ عَلَيْكُمْ وَرَحْمَةُ ٱللَّه',
    Sadaqa: 'صَدَقَ ٱللَّهُ ٱلْعَظِيم',
};

const LOWER = new Map(Object.entries(SPECIAL_TEXT).map(([k, v]) => [k.toLowerCase(), v]));

/** Text for a special ref (case-insensitive, `+`-fused tokens joined), or
 *  `''` when any part is not a known special. */
export function specialTextFor(ref: string | null | undefined): string {
    if (!ref || ref.includes(':')) return '';
    const parts = ref.split('+').map((p) => LOWER.get(p.trim().toLowerCase()));
    return parts.every((p): p is string => !!p) ? parts.join(' ') : '';
}
