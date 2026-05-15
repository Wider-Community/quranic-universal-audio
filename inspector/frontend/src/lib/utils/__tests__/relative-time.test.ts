import { describe, expect, it } from 'vitest';

import { relativeTime } from '../relative-time';

const NOW = new Date('2026-05-13T12:00:00Z');

function ago(seconds: number): string {
    return new Date(NOW.getTime() - seconds * 1000).toISOString();
}

describe('relativeTime', () => {
    it('returns "just now" for very recent timestamps', () => {
        expect(relativeTime(ago(5), NOW)).toBe('just now');
    });

    it('pluralizes minutes correctly', () => {
        expect(relativeTime(ago(60), NOW)).toBe('1 minute ago');
        expect(relativeTime(ago(60 * 5), NOW)).toBe('5 minutes ago');
    });

    it('formats hours', () => {
        expect(relativeTime(ago(60 * 60 * 3), NOW)).toBe('3 hours ago');
    });

    it('returns "yesterday" between 1d and 2d ago', () => {
        expect(relativeTime(ago(60 * 60 * 24 + 60), NOW)).toBe('yesterday');
    });

    it('formats days', () => {
        expect(relativeTime(ago(60 * 60 * 24 * 3), NOW)).toBe('3 days ago');
    });

    it('formats weeks', () => {
        expect(relativeTime(ago(60 * 60 * 24 * 14), NOW)).toBe('2 weeks ago');
    });

    it('formats months', () => {
        expect(relativeTime(ago(60 * 60 * 24 * 90), NOW)).toBe('3 months ago');
    });

    it('formats years', () => {
        expect(relativeTime(ago(60 * 60 * 24 * 365 * 2), NOW)).toBe('2 years ago');
    });

    it('returns the input string when given an unparseable date', () => {
        expect(relativeTime('not-a-date', NOW)).toBe('not-a-date');
    });
});
