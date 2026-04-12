/**
 * Accordion helpers shared across panels that use <details> elements.
 *
 * These functions are deliberately narrow: they manage open/closed state of
 * sibling <details> and capture/restore of that state across re-renders.
 *
 * The validation-specific "half-state guard" (B07 — panel should only render
 * when at least one category has items after chapter filtering) lives in
 * `segments/validation/index.ts` because the list of categories and the
 * filtering contract are validation-local.
 */

/** Map of `<details>` identifier → persisted state (currently just open/closed). */
export type AccordionOpenState = Record<string, { open: boolean }>;

/**
 * Collapse every sibling `<details[data-category]>` under the same panel root
 * except `except`. Used by an accordion's `toggle` listener to enforce
 * "only one open at a time". Falls back to `exceptDetails.parentElement`
 * when none of the known panel-root selectors matches (useful for ad-hoc
 * panels that aren't under `#seg-validation` / `#seg-validation-global`).
 */
export function collapseSiblingDetails(
    exceptDetails: HTMLDetailsElement,
    panelRootSelector: string = '#seg-validation-global, #seg-validation',
): void {
    const panel: Element | null =
        exceptDetails.closest(panelRootSelector) ?? exceptDetails.parentElement;
    if (!panel) return;
    panel.querySelectorAll<HTMLDetailsElement>('details[data-category]').forEach((d) => {
        if (d === exceptDetails) return;
        if (d.open) d.open = false;
    });
}

/**
 * Capture the open/closed state of every `<details[data-category]>` under
 * `targetEl`, keyed by the `data-category` attribute. Used to preserve the
 * user's expanded panels across a full re-render of the accordion.
 */
export function capturePanelOpenState(targetEl: HTMLElement): AccordionOpenState {
    const out: AccordionOpenState = {};
    targetEl.querySelectorAll<HTMLDetailsElement>('details[data-category]').forEach((d) => {
        const key: string | null = d.getAttribute('data-category');
        if (key !== null) out[key] = { open: d.open };
    });
    return out;
}

/**
 * Reopen `<details[data-category]>` elements under `targetEl` whose key was
 * previously captured with `open: true`. Entries not present in `state` (or
 * whose `<details>` no longer exists in the DOM) are silently skipped —
 * categories that disappeared after filtering stay closed.
 */
export function restorePanelOpenState(targetEl: HTMLElement, state: AccordionOpenState): void {
    targetEl.querySelectorAll<HTMLDetailsElement>('details[data-category]').forEach((d) => {
        const key: string | null = d.getAttribute('data-category');
        if (key === null) return;
        const s = state[key];
        if (s?.open) d.open = true;
    });
}
