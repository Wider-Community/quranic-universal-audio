/** Find the card canvas that's currently in edit mode. */
export function _getEditCanvas(): HTMLCanvasElement | null {
    const row = document.querySelector<HTMLElement>('.seg-row.seg-edit-target');
    return row?.querySelector<HTMLCanvasElement>('canvas') || null;
}
