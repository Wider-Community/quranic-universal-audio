/**
 * Keyboard edit paths must honour the same gate as the `editGate` action.
 * `E` (begin ref-edit) is the live bypass: it would start an edit the gated
 * buttons block. With `editingMode` in `guides_unread`, pressing E must open
 * the guide gate instead of beginning an edit; in an editable mode it proceeds.
 */
import { readable, get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { editingMode } from '../../../../lib/stores/editing-mode';
import { closeGuidesGate, guidesGate } from '../../../../lib/stores/guides-gate';
import { setActiveTab } from '../../../../lib/utils/active-tab';
import { TAB_NAMES } from '../../../../lib/utils/constants';
import { segCurrentIdx } from '../../stores/chapter';

// beginRefEdit runs real edit machinery — stub it so we can assert it is (not) called.
const beginRefEdit = vi.fn();
vi.mock('../edit/reference', () => ({ beginRefEdit: (...args: unknown[]) => beginRefEdit(...args) }));

// displayedSegments is a derived (read-only) store; override just it with a
// one-segment list so KeyE resolves a target. Spread the original so every
// other export keeps working for the rest of the import graph.
vi.mock('../../stores/filters', async (importOriginal) => ({
    ...(await importOriginal<typeof import('../../stores/filters')>()),
    displayedSegments: readable([{ index: 0, chapter: 1 }]),
}));

import { handleSegmentsKey } from '../keyboard';

function pressE(): boolean {
    return handleSegmentsKey({ code: 'KeyE', target: document.body } as unknown as KeyboardEvent);
}

beforeEach(() => {
    setActiveTab(TAB_NAMES.SEGMENTS);
    segCurrentIdx.set(0);   // editMode defaults to null (no active edit) — leave it
    closeGuidesGate();
    beginRefEdit.mockClear();
});

afterEach(() => {
    setActiveTab('dashboard');
    editingMode.set({ kind: 'view', viewReason: 'unauthenticated' });
    closeGuidesGate();
});

describe('keyboard edit gate (E)', () => {
    it('opens the guide gate and does NOT begin an edit when guides are unread', () => {
        editingMode.set({ kind: 'view', viewReason: 'guides_unread' });
        const handled = pressE();
        expect(handled).toBe(true);
        expect(beginRefEdit).not.toHaveBeenCalled();
        expect(get(guidesGate).open).toBe(true);
    });

    it('begins the ref-edit when the user is in an editable mode', () => {
        editingMode.set({ kind: 'editor' });
        const handled = pressE();
        expect(handled).toBe(true);
        expect(beginRefEdit).toHaveBeenCalledTimes(1);
        expect(get(guidesGate).open).toBe(false);
    });
});
