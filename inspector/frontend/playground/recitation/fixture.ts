/**
 * Offline demo fixture — lets the playground (and its animation) run without
 * the Flask backend / bucket. Synthetic Al-Fatihah timings; a virtual clock in
 * Playground.svelte drives playback. Throwaway, like the rest of the
 * playground.
 */
import type { AnimUnit, ChapterRecitation } from '../../src/lib/recitation-animation';

type Row = [ayah: number, text: string, startSec: number, endSec: number];

// [ayah, display text, start, end] — gaps between words/ayahs are intentional
// (silence the animation plays through). Ayah 5 is long to force an overflow
// re-page; ayah changes exercise the ayah-end clear.
const ROWS: Row[] = [
    [1, 'بِسْمِ', 0.0, 0.9],
    [1, 'ٱللَّهِ', 0.9, 1.8],
    [1, 'ٱلرَّحْمَٰنِ', 1.8, 3.0],
    [1, 'ٱلرَّحِيمِ', 3.0, 4.2],
    [2, 'ٱلْحَمْدُ', 4.6, 5.6],
    [2, 'لِلَّهِ', 5.6, 6.4],
    [2, 'رَبِّ', 6.4, 7.1],
    [2, 'ٱلْعَٰلَمِينَ', 7.1, 8.6],
    [3, 'ٱلرَّحْمَٰنِ', 9.0, 10.2],
    [3, 'ٱلرَّحِيمِ', 10.2, 11.4],
    [4, 'مَٰلِكِ', 11.8, 12.7],
    [4, 'يَوْمِ', 12.7, 13.6],
    [4, 'ٱلدِّينِ', 13.6, 14.8],
    [5, 'إِيَّاكَ', 15.2, 16.2],
    [5, 'نَعْبُدُ', 16.2, 17.2],
    [5, 'وَإِيَّاكَ', 17.2, 18.4],
    [5, 'نَسْتَعِينُ', 18.4, 19.8],
];

export function demoRecitation(): ChapterRecitation {
    const units: AnimUnit[] = [];
    const wordByAyah = new Map<number, number>();
    for (const [ayah, text, start, end] of ROWS) {
        const word = (wordByAyah.get(ayah) ?? 0) + 1;
        wordByAyah.set(ayah, word);
        units.push({
            location: `1:${ayah}:${word}`,
            ayahKey: `1:${ayah}`,
            surah: 1,
            ayah,
            word,
            text,
            start,
            end,
            intervals: [{ start, end }],
            letters: [],
        });
    }
    const ayahs = [...new Set(units.map((u) => u.ayahKey))].map((key) => {
        const us = units.filter((u) => u.ayahKey === key);
        return {
            ayahKey: key,
            surah: 1,
            ayah: us[0]!.ayah,
            startMs: Math.round(us[0]!.start * 1000),
            endMs: Math.round(us[us.length - 1]!.end * 1000),
        };
    });
    const contentEndMs = Math.round(Math.max(...units.map((u) => u.end)) * 1000);
    return { reciter: 'demo', chapter: 1, units, ayahs, contentEndMs };
}
