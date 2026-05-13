/**
 * Svelte action: invokes the callback when a pointerdown (or touch
 * equivalent) occurs outside the element. Used for dismissing popovers
 * and dropups.
 */
export function clickOutside(node: HTMLElement, callback: () => void) {
    function onPointerDown(ev: PointerEvent): void {
        const target = ev.target as Node | null;
        if (target && !node.contains(target)) callback();
    }
    document.addEventListener('pointerdown', onPointerDown, true);
    return {
        destroy(): void {
            document.removeEventListener('pointerdown', onPointerDown, true);
        },
        update(newCallback: () => void): void {
            callback = newCallback;
        },
    };
}
