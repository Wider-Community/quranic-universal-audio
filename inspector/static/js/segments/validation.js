/**
 * Validation panel rendering and index fixup helpers.
 * STUB: Phase 8 will extract full implementation from segments.js.
 * Uses registration pattern so segments.js can inject real implementations.
 */

let _impl = {};

export function registerValidationHandlers(handlers) {
    _impl = { ..._impl, ...handlers };
}

export function _fixupValIndicesForSplit(chapter, splitIndex) {
    _impl._fixupValIndicesForSplit?.(chapter, splitIndex);
}
export function _fixupValIndicesForMerge(chapter, keptIndex, consumedIndex) {
    _impl._fixupValIndicesForMerge?.(chapter, keptIndex, consumedIndex);
}
export function _fixupValIndicesForDelete(chapter, deletedIndex) {
    _impl._fixupValIndicesForDelete?.(chapter, deletedIndex);
}
export function refreshOpenAccordionCards() {
    _impl.refreshOpenAccordionCards?.();
}
export function refreshValidation() {
    return _impl.refreshValidation?.();
}
export function renderValidationPanel(...args) {
    return _impl.renderValidationPanel?.(...args);
}
export function captureValPanelState(...args) {
    return _impl.captureValPanelState?.(...args) ?? {};
}
export function restoreValPanelState(...args) {
    _impl.restoreValPanelState?.(...args);
}
export function _collapseAccordionExcept(...args) {
    _impl._collapseAccordionExcept?.(...args);
}
export function invalidateLoadedErrorCards() {
    _impl.invalidateLoadedErrorCards?.();
}
