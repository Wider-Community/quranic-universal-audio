/**
 * Error card rendering for validation accordions.
 * STUB: Phase 8 will extract full implementation from segments.js.
 * Uses registration pattern so segments.js can inject real implementations.
 */

let _impl = {};

export function registerErrorCardHandlers(handlers) {
    _impl = { ..._impl, ...handlers };
}

export function _rebuildAccordionAfterSplit(...args) {
    _impl._rebuildAccordionAfterSplit?.(...args);
}
export function _refreshSiblingCardIndices(...args) {
    _impl._refreshSiblingCardIndices?.(...args);
}
export function _rebuildAccordionAfterMerge(...args) {
    _impl._rebuildAccordionAfterMerge?.(...args);
}
export function renderCategoryCards(...args) {
    _impl.renderCategoryCards?.(...args);
}
