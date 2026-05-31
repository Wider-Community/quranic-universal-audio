/**
 * Per-frame highlight cache — extracted from the timestamps-tab
 * `AnimationDisplay`. Indexes the rendered `.ra-word` / `.ra-char` spans by
 * their `data-start` / `data-end` (seconds) + `data-group-id`, so per-frame
 * updates are O(1) DOM class/opacity writes against a cached element list
 * (no querySelectorAll per frame). Group members (cross-word idgham/ghunna)
 * are toggled together.
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

export function applyClass(
    cache: HighlightCache,
    idx: number,
    className: string,
    add: boolean,
): void {
    const item = cache.items[idx];
    if (!item) return;
    if (add) item.el.classList.add(className);
    else item.el.classList.remove(className);
    const members = item.groupId ? cache.groupIndex[item.groupId] : undefined;
    if (!members) return;
    for (const mi of members) {
        if (mi === idx) continue;
        const other = cache.items[mi];
        if (!other) continue;
        if (add) other.el.classList.add(className);
        else other.el.classList.remove(className);
    }
}

export function applyOpacity(
    cache: HighlightCache,
    idx: number,
    opacity: string | null,
): void {
    const item = cache.items[idx];
    if (!item) return;
    if (opacity === null) item.el.style.removeProperty('opacity');
    else item.el.style.opacity = opacity;
    const members = item.groupId ? cache.groupIndex[item.groupId] : undefined;
    if (!members) return;
    for (const mi of members) {
        if (mi === idx) continue;
        const other = cache.items[mi];
        if (!other) continue;
        if (opacity === null) other.el.style.removeProperty('opacity');
        else other.el.style.opacity = opacity;
    }
}

/**
 * Reveal opacity: units before `newIdx` are fully revealed (opacity cleared so
 * the CSS "reached" rule wins), the active unit's opacity is cleared (CSS
 * "active" wins), units after are pushed to opacity 0. Fast-path for advancing
 * by exactly one. Group opacities are reconciled so co-timed members agree.
 */
export function applyRevealOpacity(
    cache: HighlightCache,
    newIdx: number,
    prevIdx: number,
): void {
    if (cache.items.length === 0) return;

    // Fast path: advancing by 1.
    if (prevIdx >= 0 && newIdx === prevIdx + 1) {
        applyOpacity(cache, prevIdx, '1');
        applyOpacity(cache, newIdx, null);
        return;
    }

    for (let i = 0; i < cache.items.length; i++) {
        if (i < newIdx) applyOpacity(cache, i, '1');
        else if (i === newIdx) applyOpacity(cache, i, null);
        else applyOpacity(cache, i, '0');
    }

    // Reconcile group opacities.
    for (const gid of Object.keys(cache.groupIndex)) {
        const members = cache.groupIndex[gid];
        if (!members || members.length <= 1) continue;
        let anyActive = false;
        let maxOp = -1;
        for (const mi of members) {
            const m = cache.items[mi];
            if (!m) continue;
            if (m.el.classList.contains('active')) {
                anyActive = true;
                break;
            }
            const op = m.el.style.opacity;
            if (op !== '') {
                const val = parseFloat(op);
                if (!isNaN(val) && val > maxOp) maxOp = val;
            }
        }
        if (anyActive) {
            for (const mi of members) {
                const m = cache.items[mi];
                if (m) m.el.style.opacity = '1';
            }
        } else if (maxOp > 0) {
            const s = String(maxOp);
            for (const mi of members) {
                const m = cache.items[mi];
                if (m) m.el.style.opacity = s;
            }
        }
    }
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
