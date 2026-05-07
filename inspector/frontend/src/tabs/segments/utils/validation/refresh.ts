import { get } from 'svelte/store';

import { fetchJson } from '../../../../lib/api';
import type { SegValidateResponse } from '../../../../lib/types/api';
import { selectedReciter } from '../../stores/chapter';
import { segListElement } from '../../stores/playback';
import { savedPreviewScroll } from '../../stores/save';
import { segValidation } from '../../stores/validation';
import { applyFiltersAndRender } from '../data/filters-apply';

export async function refreshValidation(): Promise<void> {
    const reciter = get(selectedReciter);
    if (!reciter) return;
    try {
        const valData = await fetchJson<SegValidateResponse>(`/api/seg/validate/${reciter}`);
        segValidation.set(valData);
        applyFiltersAndRender();
        const scrollTop = get(savedPreviewScroll);
        if (scrollTop !== null) {
            savedPreviewScroll.set(null);
            requestAnimationFrame(() => {
                const listEl = get(segListElement);
                if (listEl) listEl.scrollTop = scrollTop;
            });
        }
    } catch (e) {
        console.error('Error refreshing validation:', e);
    }
}
