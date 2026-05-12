<script lang="ts">
    /**
     * Secondary facet rail rendered to the left of the reciter list.
     * Axes come from the schema descriptor; no taxonomy literals here.
     * Counts come from a parent-computed perFacetCounts map (the same
     * shape `facets.ts::recomputeFacets` returns).
     */
    import { createEventDispatcher } from 'svelte';

    import FilterPill from '../FilterPill.svelte';
    import type { Axis } from '../../catalog/schema-descriptor';

    export let axes: Axis[];
    export let activeFilters: Record<string, Set<string>>;
    export let perFacetCounts: Record<string, Record<string, number>>;

    const dispatch = createEventDispatcher<{ toggle: { axis: string; tag: string } }>();
</script>

<aside class="rail" aria-label="Secondary filters">
    {#each axes as axis (axis.key)}
        {@const counts = perFacetCounts[axis.key] ?? {}}
        {@const active = activeFilters[axis.key]}
        <div class="facet">
            <span class="facet-label">{axis.label}</span>
            <div class="pills">
                {#each axis.options as option (option.key)}
                    {@const count = counts[option.key] ?? 0}
                    <FilterPill
                        label={option.label}
                        count={count}
                        active={active?.has(option.key) ?? false}
                        empty={count === 0}
                        on:click={() => dispatch('toggle', { axis: axis.key, tag: option.key })}
                    />
                {/each}
            </div>
        </div>
    {/each}
</aside>

<style>
    .rail {
        padding: var(--s-5) var(--s-4);
        border-right: 1px solid var(--border-quiet);
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: var(--s-5);
    }
    .facet { display: flex; flex-direction: column; gap: var(--s-2); }
    .facet-label {
        font-size: var(--fs-meta);
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: var(--s-1);
    }
    .pills {
        display: flex;
        flex-wrap: wrap;
        gap: var(--s-1);
    }
</style>
