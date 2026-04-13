/**
 * Small DOM helpers shared across tabs.
 */

/**
 * Look up an element by id and assert non-null. Throws a clear error if
 * the id is missing in the DOM — makes DOMContentLoaded init fail-fast
 * instead of silently producing a DOM ref that NPEs at first touch.
 */
export function mustGet<T extends HTMLElement>(id: string): T {
    const el = document.getElementById(id);
    if (!el) throw new Error(`DOM: missing #${id}`);
    return el as T;
}
