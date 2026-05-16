/**
 * Minimal toast queue.
 *
 * Toasts surface ephemeral feedback (claim conflicts, session expiry,
 * etc.). The host component (`ToastHost.svelte`) is mounted once at the
 * app root and renders the current queue.
 */

import { writable } from 'svelte/store';

export type ToastKind = 'info' | 'warn' | 'error' | 'success';

export interface Toast {
    id: number;
    kind: ToastKind;
    text: string;
    /** Auto-dismiss in ms; 0 = persist until clicked. */
    ttl: number;
}

export const toasts = writable<Toast[]>([]);

let _nextId = 1;

export function pushToast(opts: { kind?: ToastKind; text: string; ttl?: number }): number {
    const id = _nextId++;
    const t: Toast = {
        id,
        kind: opts.kind ?? 'info',
        text: opts.text,
        ttl: opts.ttl ?? 4000,
    };
    toasts.update((q) => [...q, t]);
    if (t.ttl > 0 && typeof window !== 'undefined') {
        window.setTimeout(() => dismissToast(id), t.ttl);
    }
    return id;
}

export function dismissToast(id: number): void {
    toasts.update((q) => q.filter((t) => t.id !== id));
}
