/**
 * Svelte action that gates an edit affordance on the global `editingMode`
 * store. Apply to any element whose click would mutate server state:
 *
 *     <button use:editGate on:click={doTrim}>Trim</button>
 *
 * For admin-only actions (Phase 7):
 *
 *     <button use:editGate={{ require: 'admin' }} on:click={forceRelease}>
 *         Force release
 *     </button>
 *
 * Behaviour
 *   - `editingMode.kind === 'editor' | 'maintainer' | 'owner'` (or `kind in
 *     {'maintainer', 'owner'}` when `require === 'admin'`) → click passes
 *     through.
 *   - Otherwise → swallow the click via `stopImmediatePropagation` +
 *     `preventDefault` and surface the global `EditAffordancePopover`.
 *
 * The button itself stays full-opacity — the popover does the explaining.
 *
 * Captures phase is used so the gate runs before any other handler the
 * component bound to the same element.
 */

import { get } from 'svelte/store';

import { showEditPopover } from '../stores/edit-popover';
import { editingMode } from '../stores/editing-mode';

export interface EditGateParams {
    require?: 'edit' | 'admin';
}

const _ALLOWED_FOR_ADMIN = new Set(['maintainer', 'owner']);
const _ALLOWED_FOR_EDIT = new Set(['editor', 'maintainer', 'owner']);

export function editGate(node: HTMLElement, params: EditGateParams = {}) {
    let current: EditGateParams = params;

    function handler(event: Event) {
        const mode = get(editingMode);
        const allowed =
            current.require === 'admin'
                ? _ALLOWED_FOR_ADMIN.has(mode.kind)
                : _ALLOWED_FOR_EDIT.has(mode.kind);
        if (allowed) return;

        event.stopImmediatePropagation();
        event.preventDefault();
        showEditPopover(node, mode);
    }

    // Capture-phase so we run before any inline `on:click` handler the
    // component bound to the same node.
    node.addEventListener('click', handler, { capture: true });
    // Trigger via keyboard (Enter/Space on a focused button) hits the
    // same code path through the click event in modern browsers, so we
    // don't need a separate keydown listener.

    return {
        update(next: EditGateParams) {
            current = next ?? {};
        },
        destroy() {
            node.removeEventListener('click', handler, { capture: true });
        },
    };
}
