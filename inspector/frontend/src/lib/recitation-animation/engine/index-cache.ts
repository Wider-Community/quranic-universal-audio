/**
 * Per-frame highlight cache. Indexes the rendered `.ra-word` / `.ra-char`
 * spans by their `data-start` / `data-end` (seconds) + `data-group-id`,
 * so per-frame updates are O(1) DOM class/opacity writes against a cached
 * element list (no querySelectorAll per frame). Group members (cross-word
 * idgham/ghunna) are toggled together.
 */

export interface CacheItem {
    el: HTMLElement;
    start: number;
    end: number;
    groupId: string;
}

export interface HighlightCache {
    items: CacheItem[];
    groupIndex: Record<string, number[]>;
}

/** Build a cache from the rendered spans under `container` matching `selector`. */
export function indexCache(container: HTMLElement, selector: string): HighlightCache {
    const items: CacheItem[] = [];
    const groupIndex: Record<string, number[]> = {};
    container.querySelectorAll<HTMLElement>(selector).forEach((el, i) => {
        const start = parseFloat(el.dataset.start ?? '0');
        const end = parseFloat(el.dataset.end ?? '0');
        const groupId = el.dataset.groupId || '';
        items.push({ el, start, end, groupId });
        if (groupId) {
            if (!groupIndex[groupId]) groupIndex[groupId] = [];
            groupIndex[groupId]!.push(i);
        }
    });
    return { items, groupIndex };
}

/** Strip all active/reached classes + inline opacity from a container's spans. */
export function clearHighlights(container: HTMLElement): void {
    container
        .querySelectorAll<HTMLElement>('.ra-word, .ra-char')
        .forEach((el) => {
            el.classList.remove('active', 'reached');
            el.style.removeProperty('opacity');
        });
}
