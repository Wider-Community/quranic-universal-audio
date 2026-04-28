/**
 * Shared keyboard-event guard helper.
 *
 * Both tab keyboard handlers had an identical preamble:
 *   1. Bail if the event target is an editable element.
 *   2. Bail if this tab is not the currently active tab.
 *
 * This helper centralises that logic. Note: the original handlers checked only
 * INPUT and TEXTAREA; this helper also checks isContentEditable (enhancement —
 * guards rich-text areas that may be added in future waves).
 */

import { getActiveTab } from './active-tab';
import type { TabName } from './constants';

/**
 * Returns true when a keyboard event should be handled by the given tab's
 * handler. Filters out:
 *   - Events originating from editable elements (INPUT, TEXTAREA, contenteditable)
 *   - Events when the given tab is not currently active
 *
 * Each tab's `handleKeydown` should bail early if this returns false.
 */
export function shouldHandleKey(e: KeyboardEvent, tab: TabName): boolean {
    const target = e.target as HTMLElement | null;
    if (target) {
        const tag = target.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable) {
            return false;
        }
    }
    if (getActiveTab() !== tab) {
        return false;
    }
    return true;
}
