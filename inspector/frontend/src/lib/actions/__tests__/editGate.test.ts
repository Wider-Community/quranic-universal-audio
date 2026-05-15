/**
 * Asserts the gate's contract:
 *
 *   - `view` mode (non-unauthenticated): edit-affordance clicks are swallowed
 *     and the popover store is populated.
 *   - `view` mode (unauthenticated): edit-affordance clicks are swallowed and
 *     the sign-in modal opens (not the popover).
 *   - `editor` / `maintainer` / `owner` modes: clicks pass through.
 *   - `require: 'admin'`: contributor's editor mode does NOT pass through.
 */

import { get } from 'svelte/store';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { editPopover } from '../../stores/edit-popover';
import { editingMode, setEditingMode } from '../../stores/editing-mode';
import { signInModal } from '../../stores/sign-in-modal';
import { editGate } from '../editGate';

let button: HTMLButtonElement;
let inner: HTMLSpanElement;
let inlineHandler: ReturnType<typeof vi.fn>;
let containerHandler: ReturnType<typeof vi.fn>;
let teardown: { destroy: () => void } | null = null;

beforeEach(() => {
    document.body.innerHTML = '';
    setEditingMode({ kind: 'view', viewReason: 'wrong-assignee' });
    editPopover.set(null);
    signInModal.set({ open: false, returnPath: null, context: null });

    button = document.createElement('button');
    button.type = 'button';
    inner = document.createElement('span');
    button.appendChild(inner);
    document.body.appendChild(button);

    inlineHandler = vi.fn();
    containerHandler = vi.fn();
    button.addEventListener('click', inlineHandler);
    document.body.addEventListener('click', containerHandler);
});

afterEach(() => {
    teardown?.destroy();
    teardown = null;
    setEditingMode({ kind: 'view', viewReason: 'wrong-assignee' });
    editPopover.set(null);
    signInModal.set({ open: false, returnPath: null, context: null });
});

describe('editGate', () => {
    it('view mode (non-unauthenticated) swallows the click and surfaces the popover', () => {
        teardown = editGate(button);
        button.click();
        expect(inlineHandler).not.toHaveBeenCalled();
        expect(containerHandler).not.toHaveBeenCalled();
        const state = get(editPopover);
        expect(state).not.toBeNull();
        expect(state?.anchor).toBe(button);
        expect(state?.mode.kind).toBe('view');
        expect(state?.mode.viewReason).toBe('wrong-assignee');
        expect(get(signInModal).open).toBe(false);
    });

    it('view mode (unauthenticated) swallows the click and opens sign-in modal', () => {
        setEditingMode({ kind: 'view', viewReason: 'unauthenticated' });
        teardown = editGate(button);
        button.click();
        expect(inlineHandler).not.toHaveBeenCalled();
        expect(containerHandler).not.toHaveBeenCalled();
        expect(get(editPopover)).toBeNull();
        const modal = get(signInModal);
        expect(modal.open).toBe(true);
        expect(modal.context?.title).toBe('Sign in to edit');
    });

    it('editor mode passes the click through', () => {
        teardown = editGate(button);
        setEditingMode({ kind: 'editor' });
        button.click();
        expect(inlineHandler).toHaveBeenCalledTimes(1);
        expect(get(editPopover)).toBeNull();
    });

    it('maintainer mode passes through with default require', () => {
        teardown = editGate(button);
        setEditingMode({ kind: 'maintainer' });
        button.click();
        expect(inlineHandler).toHaveBeenCalledTimes(1);
    });

    it('owner mode passes through with default require', () => {
        teardown = editGate(button);
        setEditingMode({ kind: 'owner' });
        button.click();
        expect(inlineHandler).toHaveBeenCalledTimes(1);
    });

    it('require: admin blocks editor (contributor) clicks', () => {
        teardown = editGate(button, { require: 'admin' });
        setEditingMode({ kind: 'editor' });
        button.click();
        expect(inlineHandler).not.toHaveBeenCalled();
        expect(get(editPopover)).not.toBeNull();
    });

    it('require: admin passes maintainer clicks through', () => {
        teardown = editGate(button, { require: 'admin' });
        setEditingMode({ kind: 'maintainer' });
        button.click();
        expect(inlineHandler).toHaveBeenCalledTimes(1);
    });

    it('destroy() removes the listener so subsequent clicks pass through', () => {
        const handle = editGate(button);
        handle.destroy();
        button.click();
        expect(inlineHandler).toHaveBeenCalledTimes(1);
    });
});
