/**
 * Bridge: push raw edit-history response to the history store and toggle
 * the external "History" button visibility. HistoryPanel.svelte renders
 * the panel contents reactively from the store.
 */

import { dom } from '../../../segments/state';
import type { SegEditHistoryResponse } from '../../../types/api';
import { setHistoryData } from '../../stores/segments/history';

export function renderEditHistoryPanel(data: SegEditHistoryResponse | null | undefined): void {
    if (!data || !data.batches || data.batches.length === 0) {
        dom.segHistoryBtn.hidden = true;
        setHistoryData(null);
        return;
    }
    dom.segHistoryBtn.hidden = false;
    setHistoryData(data);
}
