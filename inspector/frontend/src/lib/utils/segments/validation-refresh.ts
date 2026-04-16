import { applyFiltersAndRender } from '../../../segments/filters';
import { dom, state } from '../../../segments/state';
import type { SegValidateResponse } from '../../../types/api';
import { fetchJson } from '../../api';
import { segValidation } from '../../stores/segments/validation';

export async function refreshValidation(): Promise<void> {
    const reciter = dom.segReciterSelect.value;
    if (!reciter) return;
    try {
        const valData = await fetchJson<SegValidateResponse>(`/api/seg/validate/${reciter}`);
        segValidation.set(valData);
        state.segValidation = valData;
        applyFiltersAndRender();
        if (state._segSavedPreviewState) {
            const saved = state._segSavedPreviewState;
            state._segSavedPreviewState = null;
            requestAnimationFrame(() => { dom.segListEl.scrollTop = saved.scrollTop; });
        }
    } catch (e) {
        console.error('Error refreshing validation:', e);
    }
}
