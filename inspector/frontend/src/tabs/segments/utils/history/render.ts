/**
 * Bridge: push raw edit-history response to the history store.
 * SegmentsTab.svelte derives the external "History" button visibility
 * reactively from `$historyData`.
 */

import type { SegEditHistoryResponse } from '../../../../lib/types/api';
import { setHistoryData } from '../../stores/history';

export function renderEditHistoryPanel(data: SegEditHistoryResponse | null | undefined): void {
    if (!data || !data.batches || data.batches.length === 0) {
        setHistoryData(null);
        return;
    }
    setHistoryData(data);
}
