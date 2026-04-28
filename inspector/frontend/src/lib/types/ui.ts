/**
 * UI-layer types shared between Svelte components and their consumers.
 *
 * Svelte 4 does not allow `export interface` inside `<script lang="ts">`,
 * so consumer-facing types for shared components live here as pure `.ts`
 * modules and are imported by both the component source and its callers.
 */

/** Option shape consumed by `lib/components/SearchableSelect.svelte`. */
export interface SelectOption {
    value: string;
    label: string;
    group?: string;
}
