/**
 * Shortcut binding store — token resolution, override round-trip, conflict
 * refusal, and pretty-printing. The store is a localStorage-backed singleton;
 * each test resets to defaults so order does not matter.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import {
    hasCustomBindings,
    isCustom,
    keyFor,
    prettyKey,
    resetAll,
    resolve,
    setBinding,
    tokenFromEvent,
} from '../store.svelte';

beforeEach(() => {
    resetAll();
    localStorage.clear();
    resetAll();
});

afterEach(() => {
    resetAll();
    localStorage.clear();
});

describe('resolve', () => {
    it('maps default tokens to actions in the default pool', () => {
        expect(resolve('KeyA', 'default')).toBe('adjust');
        expect(resolve('KeyS', 'default')).toBe('split');
        expect(resolve('Ctrl+KeyS', 'default')).toBe('save');
        expect(resolve('Space', 'default')).toBe('play_pause');
    });

    it('exposes accordion-only actions only when an accordion is open', () => {
        expect(resolve('KeyG', 'default')).toBeNull();
        expect(resolve('KeyG', 'accordion')).toBe('goto');
        expect(resolve('KeyL', 'accordion')).toBe('ignore');
    });

    it('still resolves default-pool actions inside the accordion context', () => {
        expect(resolve('KeyA', 'accordion')).toBe('adjust');
    });

    it('resolves edit-pool keys only in edit context', () => {
        expect(resolve('Tab', 'edit')).toBe('edit_cycle');
        expect(resolve('Tab', 'default')).toBeNull();
    });
});

describe('setBinding', () => {
    it('round-trips a rebind through localStorage', () => {
        const res = setBinding('adjust', 'KeyQ');
        expect(res.ok).toBe(true);
        expect(keyFor('adjust')).toBe('KeyQ');
        expect(isCustom('adjust')).toBe(true);
        expect(hasCustomBindings()).toBe(true);
        expect(resolve('KeyQ', 'default')).toBe('adjust');
        expect(JSON.parse(localStorage.getItem('insp_seg_shortcuts') ?? '{}')).toMatchObject({ adjust: 'KeyQ' });
    });

    it('refuses a token already used by another action in the same group', () => {
        const res = setBinding('adjust', 'KeyS');
        expect(res.ok).toBe(false);
        expect(res.conflict?.id).toBe('split');
        expect(keyFor('adjust')).toBe('KeyA'); // unchanged
    });

    it('refuses rebinding a fixed (non-rebindable) action', () => {
        expect(setBinding('play_pause', 'KeyP').ok).toBe(false);
        expect(keyFor('play_pause')).toBe('Space');
    });

    it('clears the override when rebound back to the default key', () => {
        setBinding('adjust', 'KeyQ');
        const res = setBinding('adjust', 'KeyA');
        expect(res.ok).toBe(true);
        expect(isCustom('adjust')).toBe(false);
    });
});

describe('resetAll', () => {
    it('restores every binding to its default', () => {
        setBinding('adjust', 'KeyQ');
        resetAll();
        expect(keyFor('adjust')).toBe('KeyA');
        expect(hasCustomBindings()).toBe(false);
    });
});

describe('tokenFromEvent', () => {
    it('prefixes Ctrl/Meta and ignores bare modifiers', () => {
        expect(tokenFromEvent({ code: 'KeyS', ctrlKey: true } as KeyboardEvent)).toBe('Ctrl+KeyS');
        expect(tokenFromEvent({ code: 'KeyS', metaKey: true } as KeyboardEvent)).toBe('Ctrl+KeyS');
        expect(tokenFromEvent({ code: 'KeyA' } as KeyboardEvent)).toBe('KeyA');
        expect(tokenFromEvent({ code: 'ControlLeft' } as KeyboardEvent)).toBe('');
    });
});

describe('prettyKey', () => {
    it('renders friendly labels', () => {
        expect(prettyKey('KeyA')).toBe('A');
        expect(prettyKey('Ctrl+KeyS')).toBe('Ctrl S');
        expect(prettyKey('ArrowUp')).toBe('↑');
        expect(prettyKey('Comma')).toBe(',');
        expect(prettyKey('Space')).toBe('Space');
    });
});
