import { get } from 'svelte/store';

import type { SegValidateResponse } from '../../../types/api';
import { fetchJson } from '../../api';
import { selectedReciter } from '../../stores/segments/chapter';
import { segListElement } from '../../stores/segments/playback';
import { savedPreviewScroll } from '../../stores/segments/save';
import { segValidation } from '../../stores/segments/validation';
import { applyFiltersAndRender } from './filters-apply';

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
