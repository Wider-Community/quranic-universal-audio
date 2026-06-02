<script lang="ts">
    /**
     * ReciterChip — reusable identity chip with the prototype design:
     *
     *     ╭───╮   Name (en)   ·   اسم بالعربية
     *     │ 🇸🇦 │
     *     ╰───╯   Riwayah · Style · [state pill]
     *
     * Country flag sits in a rounded circle on the left, vertically
     * centered against two text rows. The top row carries English +
     * Arabic name side-by-side (both at body weight so they read on the
     * same visual level). The bottom row carries the delivery subline
     * with the state pill INLINE at its end — so the chip stays a
     * single self-contained block rather than spreading the pill out
     * to the row's far edge.
     *
     * Consumers wrap the chip in their own <button> or <div> depending
     * on whether the chip itself is the click target.
     */
    import type { PublicBucket } from '../types/public-state';
    import { normalizeCountry } from '../utils/countries';
    import { countryFlag, countryName } from '../utils/delivery-label';
    import StatePill from './StatePill.svelte';

    /** Reciter's English name. Required. */
    export let name: string;
    /** Arabic name. Falsy values hide the right-side text on the top line. */
    export let nameAr: string | null = null;
    /** ISO-3166-1 alpha-2 country code (e.g. "SA"). Falls back to a
     *  generic globe glyph when missing or invalid. */
    export let country: string | null = null;
    /** Secondary line below the name. Pass the formatted riwayah · style
     *  for single-delivery surfaces, or a summary string for the picker. */
    export let subline: string | null = null;
    /** Bucket for the right-side state pill. Hides the pill when null. */
    export let bucket: PublicBucket | null = null;
    /** Render a switch hint glyph on the trailing edge — used by interactive
     *  chips that open a picker dropup on click. */
    export let switchable = false;
    /** Visual variant. `default` is the full chip; `compact` shrinks the
     *  flag circle for use inside dense rows (the catalog table). */
    export let variant: 'default' | 'compact' = 'default';

    // Legacy catalog rows store the country as a full English name
    // ("Saudi Arabia") rather than the ISO-2 code the schema documents.
    // normalizeCountry resolves either shape to "SA"; countryFlag then
    // emits the regional-indicator emoji pair. Falls back to the raw
    // string when the country can't be normalised (rare).
    $: iso = country ? normalizeCountry(country) : '';
    $: flag = countryFlag(iso);
    $: flagTitle = country ? countryName(iso || country) : '';
    $: hasState = !!bucket;
    /** Pass through the caller's pre-formatted subline. */
    $: displaySubline = subline?.trim() ? subline : '';

    // Initials fallback when no country is on record — first letters of
    // up to two words in the reciter's name, uppercased. Mirrors the
    // convention used elsewhere in the app for circle avatars. */
    $: initials = name
        ? name.trim().split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? '').join('')
        : '';
</script>

<div class="chip" class:compact={variant === 'compact'}>
    <span class="flag" title={flagTitle}>
        {#if flag}
            <span class="flag-emoji" aria-hidden="true">{flag}</span>
        {:else if iso && iso.length === 2}
            <span class="flag-code" aria-hidden="true">{iso.toUpperCase()}</span>
        {:else if initials}
            <span class="flag-initials" aria-hidden="true">{initials}</span>
        {/if}
    </span>

    <div class="text">
        <div class="line line-top">
            <span class="name-en">{name}</span>
            {#if nameAr}
                <span class="dot" aria-hidden="true">·</span>
                <span class="name-ar" dir="rtl">{nameAr}</span>
            {/if}
        </div>
        {#if displaySubline || hasState}
            <div class="line line-bot">
                {#if displaySubline}
                    <span class="subline">{displaySubline}</span>
                {/if}
                {#if hasState && bucket}
                    {#if displaySubline}
                        <span class="dot" aria-hidden="true">·</span>
                    {/if}
                    <StatePill state={bucket} size="sm" />
                {/if}
            </div>
        {/if}
    </div>

    {#if switchable}
        <span class="switch" aria-hidden="true">⇄</span>
    {/if}
</div>

<style>
    .chip {
        display: inline-flex;
        align-items: center;
        gap: var(--s-3);
        min-width: 0;
        max-width: 100%;
    }

    /* ---------- Flag circle ---------- */
    .flag {
        flex: 0 0 auto;
        width: 38px;
        height: 38px;
        border-radius: 50%;
        background: var(--panel-2);
        border: 1px solid var(--border-quiet);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
    }
    .compact .flag {
        width: 30px;
        height: 30px;
    }
    .flag-emoji {
        /* Emoji flags render large by default — shrinking slightly keeps
         * them inside the circle without clipping the rounded corners. */
        font-size: 22px;
        line-height: 1;
    }
    .compact .flag-emoji { font-size: 18px; }
    .flag-code {
        font-family: var(--font-mono);
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.04em;
        color: var(--text-secondary);
    }
    /* Avatar-style initials fallback when no country is on record. */
    .flag-initials {
        font-family: var(--font-sans);
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.02em;
        color: var(--text-secondary);
    }
    .compact .flag-initials { font-size: 11px; }

    /* ---------- Text column ---------- */
    .text {
        min-width: 0;
        display: flex;
        flex-direction: column;
        gap: 2px;
        flex: 0 1 auto;
    }
    .line {
        display: flex;
        align-items: center;
        gap: 6px;
        min-width: 0;
    }
    /* Top row: English + Arabic name at matched size and `center`
       alignment (not baseline) so the two scripts read on the same
       visual midline. Arabic fonts often have a low baseline against
       Latin; centering corrects the optical mismatch. */
    .line-top {
        color: var(--text-primary);
        font-size: var(--fs-row);
        font-weight: 500;
        line-height: 1.2;
    }
    .name-en {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        min-width: 0;
    }
    .name-ar {
        color: var(--text-secondary);
        font-size: var(--fs-row);
        font-weight: 400;
        font-family: var(--font-arabic, inherit);
        line-height: 1.2;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        min-width: 0;
    }
    .dot {
        color: var(--text-faint);
        flex: 0 0 auto;
    }

    /* Bottom row: delivery subline followed by the state pill, all
       inline. The pill is the only non-text item and keeps its own
       background; the dot separator sits between text and pill when
       both are present. */
    .line-bot {
        color: var(--text-muted);
        font-size: var(--fs-meta);
        flex-wrap: wrap;
    }
    .line-bot .subline {
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        min-width: 0;
    }

    .compact .line-top { font-size: var(--fs-body); }
    .compact .name-ar  { font-size: var(--fs-body); }
    .compact .line-bot { font-size: 11px; }

    /* ---------- Switch hint ---------- */
    .switch {
        margin-inline-start: auto;
        padding-inline-start: var(--s-2);
        color: var(--text-faint);
        font-size: var(--fs-meta);
        transition: color var(--t-fast);
    }
    /* Hover styling is owned by the parent <button>; the chip itself is
     * presentation-only, so we expose a class hook instead. */
    .chip:hover .switch { color: var(--text-secondary); }

    @media (max-width: 540px) {
        .flag {
            display: none !important;
        }
        .line-bot {
            display: none !important;
        }
        .name-ar,
        .line-top .dot {
            display: none !important;
        }
        .line-top {
            font-size: 13px !important;
        }
        .chip {
            gap: 0 !important;
        }
    }
</style>
