<script lang="ts">
    // External link rail (top-left of the header). Brand marks render muted
    // and reveal their true brand color + a sliding label on hover.
    // Order is deliberate: source -> builds -> published data -> community.
    //
    // Discord is a placeholder until the invite exists: an empty `href`
    // renders the icon non-navigating with a "coming soon" tooltip. Drop the
    // real URL into DISCORD_URL to light it up.
    const DISCORD_URL = '';

    type Brand = 'gh' | 'rel' | 'hf' | 'discord';
    type Link = { key: Brand; label: string; href: string };

    const links: Link[] = [
        { key: 'gh', label: 'GitHub', href: 'https://github.com/Wider-Community/quranic-universal-audio' },
        { key: 'rel', label: 'Releases', href: 'https://github.com/Wider-Community/quranic-universal-audio/releases' },
        { key: 'hf', label: 'Dataset', href: 'https://huggingface.co/datasets/hetchyy/quranic-universal-ayahs' },
        { key: 'discord', label: 'Discord', href: DISCORD_URL },
    ];
</script>

<nav class="link-rail" aria-label="Project links">
    {#each links as link (link.key)}
        {@const placeholder = link.href === ''}
        <a
            class="link"
            class:placeholder
            data-brand={link.key}
            href={placeholder ? undefined : link.href}
            target={placeholder ? undefined : '_blank'}
            rel={placeholder ? undefined : 'noopener noreferrer'}
            aria-label={placeholder ? `${link.label} (coming soon)` : link.label}
            aria-disabled={placeholder ? 'true' : undefined}
            title={placeholder ? `${link.label} — coming soon` : link.label}
        >
            {#if link.key === 'gh'}
                <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>
            {:else if link.key === 'rel'}
                <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M21.41 11.58l-9-9C12.05 2.22 11.55 2 11 2H4c-1.1 0-2 .9-2 2v7c0 .55.22 1.05.59 1.42l9 9c.36.36.86.58 1.41.58s1.05-.22 1.41-.59l7-7c.37-.36.59-.86.59-1.41s-.23-1.06-.59-1.42zM5.5 7C4.67 7 4 6.33 4 5.5S4.67 4 5.5 4 7 4.67 7 5.5 6.33 7 5.5 7z"/></svg>
            {:else if link.key === 'hf'}
                <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12.025 1.13c-5.77 0-10.449 4.647-10.449 10.378 0 1.112.178 2.181.503 3.185.064-.222.203-.444.416-.577a.96.96 0 0 1 .524-.15c.293 0 .584.124.84.284.278.173.48.408.71.694.226.282.458.611.684.951v-.014c.017-.324.106-.622.264-.874s.403-.487.762-.543c.3-.047.596.06.787.203s.31.313.4.467c.15.257.212.468.233.542.01.026.653 1.552 1.657 2.54.616.605 1.01 1.223 1.082 1.912.055.537-.096 1.059-.38 1.572.637.121 1.294.187 1.967.187.657 0 1.298-.063 1.921-.178-.287-.517-.44-1.041-.384-1.581.07-.69.465-1.307 1.081-1.913 1.004-.987 1.647-2.513 1.657-2.539.021-.074.083-.285.233-.542.09-.154.208-.323.4-.467a1.08 1.08 0 0 1 .787-.203c.359.056.604.29.762.543s.247.55.265.874v.015c.225-.34.457-.67.683-.952.23-.286.432-.52.71-.694.257-.16.547-.284.84-.285a.97.97 0 0 1 .524.151c.228.143.373.388.43.625l.006.04a10.3 10.3 0 0 0 .534-3.273c0-5.731-4.678-10.378-10.449-10.378M8.327 6.583a1.5 1.5 0 0 1 .713.174 1.487 1.487 0 0 1 .617 2.013c-.183.343-.762-.214-1.102-.094-.38.134-.532.914-.917.71a1.487 1.487 0 0 1 .69-2.803m7.486 0a1.487 1.487 0 0 1 .689 2.803c-.385.204-.536-.576-.916-.71-.34-.12-.92.437-1.103.094a1.487 1.487 0 0 1 .617-2.013 1.5 1.5 0 0 1 .713-.174m-10.68 1.55a.96.96 0 1 1 0 1.921.96.96 0 0 1 0-1.92m13.838 0a.96.96 0 1 1 0 1.92.96.96 0 0 1 0-1.92M8.489 11.458c.588.01 1.965 1.157 3.572 1.164 1.607-.007 2.984-1.155 3.572-1.164.196-.003.305.12.305.454 0 .886-.424 2.328-1.563 3.202-.22-.756-1.396-1.366-1.63-1.32q-.011.001-.02.006l-.044.026-.01.008-.03.024q-.018.017-.035.036l-.032.04a1 1 0 0 0-.058.09l-.014.025q-.049.088-.11.19a1 1 0 0 1-.083.116 1.2 1.2 0 0 1-.173.18q-.035.029-.075.058a1.3 1.3 0 0 1-.251-.243 1 1 0 0 1-.076-.107c-.124-.193-.177-.363-.337-.444-.034-.016-.104-.008-.2.022q-.094.03-.216.087-.06.028-.125.063l-.13.074q-.067.04-.136.086a3 3 0 0 0-.135.096 3 3 0 0 0-.26.219 2 2 0 0 0-.12.121 2 2 0 0 0-.106.128l-.002.002a2 2 0 0 0-.09.132l-.001.001a1.2 1.2 0 0 0-.105.212q-.013.036-.024.073c-1.139-.875-1.563-2.317-1.563-3.203 0-.334.109-.457.305-.454m.836 10.354c.824-1.19.766-2.082-.365-3.194-1.13-1.112-1.789-2.738-1.789-2.738s-.246-.945-.806-.858-.97 1.499.202 2.362c1.173.864-.233 1.45-.685.64-.45-.812-1.683-2.896-2.322-3.295s-1.089-.175-.938.647 2.822 2.813 2.562 3.244-1.176-.506-1.176-.506-2.866-2.567-3.49-1.898.473 1.23 2.037 2.16c1.564.932 1.686 1.178 1.464 1.53s-3.675-2.511-4-1.297c-.323 1.214 3.524 1.567 3.287 2.405-.238.839-2.71-1.587-3.216-.642-.506.946 3.49 2.056 3.522 2.064 1.29.33 4.568 1.028 5.713-.624m5.349 0c-.824-1.19-.766-2.082.365-3.194 1.13-1.112 1.789-2.738 1.789-2.738s.246-.945.806-.858.97 1.499-.202 2.362c-1.173.864.233 1.45.685.64.451-.812 1.683-2.896 2.322-3.295s1.089-.175.938.647-2.822 2.813-2.562 3.244 1.176-.506 1.176-.506 2.866-2.567 3.49-1.898-.473 1.23-2.037 2.16c-1.564.932-1.686 1.178-1.464 1.53s3.675-2.511 4-1.297c.323 1.214-3.524 1.567-3.287 2.405.238.839 2.71-1.587 3.216-.642.506.946-3.49 2.056-3.522 2.064-1.29.33-4.568 1.028-5.713-.624"/></svg>
            {:else}
                <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-.0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00.0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077 0 01-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 01.0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614 0a.0739.0739 0 01.0785.0095c.1202.099.246.1981.3728.2924a.077.077 0 01-.0066.1276 12.2986 12.2986 0 01-1.873.8914.0766.0766 0 00-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 00.0842.0286c1.961-.6067 3.9495-1.5219 6.0023-3.0294a.077.077 0 00.0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 00-.0312-.0286zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189Z"/></svg>
            {/if}
            <span class="lbl">{link.label}</span>
        </a>
    {/each}
</nav>

<style>
    .link-rail {
        grid-column: 1;
        justify-self: start;
        display: flex;
        align-items: center;
        gap: 2px;
    }
    .link {
        --c: #e6edf3; /* GitHub default; overridden per brand below */
        position: relative;
        display: inline-flex;
        align-items: center;
        gap: 6px;
        color: #7d869c;
        text-decoration: none;
        padding: 8px;
        border-radius: 7px;
        transition: color 0.18s cubic-bezier(0.22, 1, 0.36, 1),
            background 0.18s cubic-bezier(0.22, 1, 0.36, 1);
    }
    .link[data-brand='gh'] { --c: #e6edf3; }
    .link[data-brand='rel'] { --c: #f0a500; }
    .link[data-brand='hf'] { --c: #ffd21e; }
    .link[data-brand='discord'] { --c: #5865f2; }

    .link svg {
        width: 18px;
        height: 18px;
        display: block;
        flex-shrink: 0;
    }
    .lbl {
        font-size: 0.85rem;
        font-weight: 500;
        white-space: nowrap;
        max-width: 0;
        opacity: 0;
        overflow: hidden;
        transform: translateX(-4px);
        transition: max-width 0.26s cubic-bezier(0.22, 1, 0.36, 1),
            opacity 0.2s cubic-bezier(0.22, 1, 0.36, 1),
            transform 0.26s cubic-bezier(0.22, 1, 0.36, 1),
            color 0.18s cubic-bezier(0.22, 1, 0.36, 1);
    }

    .link:hover,
    .link:focus-visible {
        color: var(--c);
        background: #1a2a4e;
        outline: none;
    }
    .link:focus-visible {
        box-shadow: 0 0 0 2px var(--c);
    }
    .link:hover .lbl,
    .link:focus-visible .lbl {
        max-width: 120px;
        opacity: 1;
        transform: translateX(0);
        color: var(--c);
    }

    /* Discord placeholder: visible but inert until the invite exists. */
    .link.placeholder {
        cursor: default;
        opacity: 0.55;
    }
    .link.placeholder:hover {
        background: transparent;
        color: #7d869c;
    }
    .link.placeholder:hover .lbl {
        max-width: 120px;
        opacity: 1;
        transform: translateX(0);
        color: #7d869c;
    }

    @media (prefers-reduced-motion: reduce) {
        .link,
        .lbl {
            transition: none;
        }
    }
</style>
