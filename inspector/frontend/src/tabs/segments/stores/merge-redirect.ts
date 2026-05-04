/**
 * Merge redirect map — tracks consumed → kept UID mappings.
 *
 * When a merge operation consumes a segment (removes its UID from the live
 * store), validation items and accordion cards that were pinned to that
 * consumed UID need to follow the redirect to the surviving (kept) UID.
 *
 * Without this, two things break:
 * 1. `filterStaleIssues` drops the issue because its `segment_uid` is no
 *    longer in the live set → the entire accordion card vanishes.
 * 2. `resolveIssueSeg` returns null for `_boundUid` → the card body hides
 *    via the `{#if resolvedSeg}` gate.
 *
 * The map is cleared on chapter switch / reciter switch / full data reload.
 * Chains are supported: if A was merged into B, then B into C, looking up
 * A resolves transitively to C.
 */

/** consumed-uid → kept-uid redirect map. */
const _mergeRedirects = new Map<string, string>();

/**
 * Record a merge redirect: `consumedUid` was merged into `keptUid`.
 *
 * Also forwards any prior redirects that pointed at `consumedUid` so that
 * transitive chains resolve in a single hop.
 */
export function recordMergeRedirect(consumedUid: string, keptUid: string): void {
    if (!consumedUid || !keptUid || consumedUid === keptUid) return;
    _mergeRedirects.set(consumedUid, keptUid);
    // Flatten chains: if X → consumedUid already existed, update X → keptUid.
    for (const [src, dst] of _mergeRedirects.entries()) {
        if (dst === consumedUid) {
            _mergeRedirects.set(src, keptUid);
        }
    }
}

/**
 * Resolve a UID through the merge redirect map.
 * Returns the final kept UID, or the input itself if no redirect exists.
 *
 * Follows transitive chains (at most 100 hops to avoid infinite loops from
 * corrupt data).
 */
export function resolveMergeRedirect(uid: string): string {
    let current = uid;
    let hops = 0;
    while (_mergeRedirects.has(current) && hops < 100) {
        current = _mergeRedirects.get(current)!;
        hops++;
    }
    return current;
}

/**
 * Check whether a UID was consumed by a merge and has a redirect.
 */
export function hasMergeRedirect(uid: string): boolean {
    return _mergeRedirects.has(uid);
}

/**
 * Clear all merge redirects. Called on chapter switch, reciter switch,
 * or full data reload — at those points the validation panel is refreshed
 * from the server with up-to-date UIDs anyway.
 */
export function clearMergeRedirects(): void {
    _mergeRedirects.clear();
}
