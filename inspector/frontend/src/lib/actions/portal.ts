/**
 * Svelte action: relocates the node to `document.body` (or a given target) so
 * it escapes every ancestor stacking/clip context. Overlays (modal backdrops)
 * mount deep in the component tree — under sticky rails, transformed panels —
 * whose stacking contexts trap a high z-index below the fixed app chrome
 * (BottomPlayer, footers). Portaling to the body root makes the overlay's
 * z-index resolve against the viewport, so it paints above that chrome.
 */
export function portal(node: HTMLElement, target: HTMLElement | string = document.body) {
    function resolve(t: HTMLElement | string): HTMLElement {
        const host = typeof t === 'string' ? document.querySelector<HTMLElement>(t) : t;
        return host ?? document.body;
    }

    resolve(target).appendChild(node);

    return {
        update(t: HTMLElement | string): void {
            resolve(t).appendChild(node);
        },
        destroy(): void {
            node.parentNode?.removeChild(node);
        },
    };
}
