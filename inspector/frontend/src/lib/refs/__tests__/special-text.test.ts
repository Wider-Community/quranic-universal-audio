import { describe, expect, it } from 'vitest';

import { specialTextFor } from '../special-text';

describe('specialTextFor', () => {
    it('maps every special token, case-insensitively', () => {
        expect(specialTextFor('Basmala')).toBe('بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيم');
        expect(specialTextFor('sadaqa')).toBe('صَدَقَ ٱللَّهُ ٱلْعَظِيم');
    });

    it('joins fused tokens', () => {
        expect(specialTextFor("Isti'adha+Basmala")).toBe(
            'أَعُوذُ بِٱللَّهِ مِنَ الشَّيْطَانِ الرَّجِيم بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيم',
        );
    });

    it('is empty for Quran refs, unknown tokens and blanks', () => {
        expect(specialTextFor('2:1:1-2:1:4')).toBe('');
        expect(specialTextFor('Nope')).toBe('');
        expect(specialTextFor('Basmala+Nope')).toBe('');
        expect(specialTextFor('')).toBe('');
        expect(specialTextFor(null)).toBe('');
    });
});
