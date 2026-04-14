/**
 * UI-layer types shared between Svelte components and their consumers.
 *
 * Svelte 4 does not allow `export interface` inside `<script lang="ts">`
 * (see Wave-3 handoff §8). Consumer-facing types for shared components
 * therefore live here as pure `.ts` modules and are imported by both the
 * component source and callers.
 */

/** Option shape consumed by `lib/components/SearchableSelect.svelte`. */
export interface SelectOption {
    value: string;
    label: string;
    group?: string;
}
