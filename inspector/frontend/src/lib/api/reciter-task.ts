/**
 * Reciter-task readable store: polls `/api/reciter-task/<slug>` on a
 * 30-second cadence while a subscriber is attached.
 *
 * The polling lifecycle is tied to the store's subscribe/unsubscribe count
 * (Svelte's `readable` start/stop semantics):
 * - First subscriber attaches → immediate fetch + start interval.
 * - Last subscriber detaches → clear interval (idle).
 *
 * One store instance per slug. The cache lives module-level so swapping
 * back to a previously-viewed reciter resumes from its last value while a
 * fresh fetch runs.
 */

import { type Readable,readable } from 'svelte/store';

import { fetchJsonOrNull } from './index';

export type ReciterTaskState =
    | 'catalogued'
    | 'awaiting_alignment'
    | 'awaiting_review'
    | 'under_review'
    | 'awaiting_timestamps'
    | 'released'
    | 'completed';

export type Visibility = 'public' | 'discarded';

export interface ReciterRow {
    slug: string;
    /**
     * Display name resolved server-side from the catalog
     * (`services/catalog.display_name`). Null when the slug isn't yet in the
     * catalog; user-facing surfaces fall back to slug only as a last resort.
     * Never expose slug directly to users — see `inspector/CLAUDE.md`.
     */
    name: string | null;
    state: ReciterTaskState;
    state_since: string;
    assignee_hf_id: string | null;
    assignee_login: string | null;
    assignee_since: string | null;
    marked_ready: boolean;
    visibility: Visibility;
    // Other fields exist on the backend row but the frontend doesn't need them.
    [k: string]: unknown;
}

export interface Predicates {
    can_claim: boolean;
    can_edit: boolean;
    can_edit_as_admin: boolean;
    can_edit_as_owner: boolean;
    can_mark_ready: boolean;
    can_unmark_ready: boolean;
    can_release: boolean;
}

export interface ReciterTask {
    row: ReciterRow;
    predicates: Predicates;
}

export const POLL_INTERVAL_MS = 30_000;

const _stores = new Map<string, Readable<ReciterTask | null>>();

export function getReciterTaskStore(slug: string): Readable<ReciterTask | null> {
    let existing = _stores.get(slug);
    if (existing) return existing;

    const store = readable<ReciterTask | null>(null, (set) => {
        let cancelled = false;

        async function tick() {
            const data = await fetchJsonOrNull<ReciterTask>(
                `/api/reciter-task/${encodeURIComponent(slug)}`,
            );
            if (!cancelled) set(data);
        }

        void tick();
        const handle = setInterval(() => void tick(), POLL_INTERVAL_MS);

        return () => {
            cancelled = true;
            clearInterval(handle);
            // Drop the cached store when no one's listening so a future
            // subscribe on the same slug runs a fresh initial fetch.
            _stores.delete(slug);
        };
    });

    _stores.set(slug, store);
    existing = store;
    return existing;
}

/** Force a one-shot refresh; useful right after a state-mutating action. */
export async function refreshReciterTask(slug: string): Promise<ReciterTask | null> {
    return fetchJsonOrNull<ReciterTask>(
        `/api/reciter-task/${encodeURIComponent(slug)}`,
    );
}
