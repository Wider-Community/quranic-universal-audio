/**
 * Bridge: push raw edit-history response to the history store.
 * SegmentsTab.svelte derives the external "History" button visibility
 * reactively from `$historyData`.
 */

import { setHistoryData } from '../../stores/segments/history';
import type { SegEditHistoryResponse } from '../../types/api';

export function renderEditHistoryPanel(data: SegEditHistoryResponse | null | undefined): void {
    if (!data || !data.batches || data.batches.length === 0) {
        setHistoryData(null);
        return;
    }
    setHistoryData(data);
}
