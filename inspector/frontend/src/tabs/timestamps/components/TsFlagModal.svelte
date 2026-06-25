<script lang="ts">
    /**
     * TsFlagModal — read + add comments on a flagged Timestamps verse.
     *
     * Opened from the footer Report button for the verse that was playing when
     * the button was clicked (the parent snapshots `slug`/`verseKey`). Lists
     * every comment on the verse (globally viewable text); the caller can
     * add/edit/delete their own comment. Author logins are shown only when the
     * caller holds `timestamps.see_flagger_identity` (owners by default).
     *
     * Anonymous callers are keyed by a localStorage token so they can edit
     * their own comment across refreshes.
     */
    import Modal from '../../../lib/components/Modal.svelte';
    import { i18n } from '../../../lib/i18n/locale.svelte';
    import * as m from '../../../lib/paraglide/messages';
    import { can } from '../../../lib/stores/capabilities';
    import { currentUser } from '../../../lib/stores/current-user';
    import type { TsFlagComment } from '../../../lib/types/generated/schemas';
    import { getAnonToken } from '../../../lib/utils/anon-token';
    import { createTsFlag, deleteTsFlag, getVerseFlags } from '../services/flags-client';

    let {
        open,
        slug,
        verseKey,
        onclose,
        onchanged,
    }: {
        open: boolean;
        slug: string;
        verseKey: string;
        onclose: () => void;
        onchanged?: () => void;
    } = $props();

    const canSeeIdentity = can('timestamps.see_flagger_identity');

    let comments = $state<TsFlagComment[]>([]);
    let draft = $state('');
    let loading = $state(false);
    let saving = $state(false);
    let loadKey = $state('');

    const myComment = $derived(comments.find((c) => c.mine) ?? null);

    // Reading i18n.locale makes the modal re-render (and its m.*() calls
    // re-evaluate) when the locale switches.
    const title = $derived((i18n.locale, m.ts_flagmodal_title({ verse: verseKey })));
    const commentLabel = $derived(
        (i18n.locale,
        myComment ? m.ts_flagmodal_edit_comment_label() : m.ts_flagmodal_add_comment_label()),
    );
    const submitLabel = $derived(
        (i18n.locale,
        myComment ? m.common_action_save() : m.ts_flagmodal_submit_report()),
    );

    function anonTokenIfNeeded(): string | null {
        return $currentUser.hf_user_id === null ? getAnonToken() : null;
    }

    // Reload whenever the modal opens onto a (new) verse.
    $effect(() => {
        const key = open ? `${slug}|${verseKey}` : '';
        if (key && key !== loadKey) {
            loadKey = key;
            void reload();
        }
        if (!open) loadKey = '';
    });

    async function reload(): Promise<void> {
        loading = true;
        try {
            const doc = await getVerseFlags(slug, verseKey, anonTokenIfNeeded());
            comments = doc.comments ?? [];
            draft = comments.find((c) => c.mine)?.comment ?? '';
        } catch {
            comments = [];
        } finally {
            loading = false;
        }
    }

    async function submit(): Promise<void> {
        if (saving) return;
        saving = true;
        try {
            const res = await createTsFlag(slug, verseKey, draft.trim() || null, anonTokenIfNeeded());
            if (!('error' in res) || !res.error) {
                await reload();
                onchanged?.();
            }
        } finally {
            saving = false;
        }
    }

    async function removeMine(): Promise<void> {
        if (saving) return;
        saving = true;
        try {
            await deleteTsFlag(slug, verseKey, anonTokenIfNeeded());
            draft = '';
            await reload();
            onchanged?.();
        } finally {
            saving = false;
        }
    }

    function authorLabel(c: TsFlagComment): string {
        if (!c.author) return '';
        return c.author.login ?? m.ts_flagmodal_author_anonymous();
    }

    function fmtDate(iso: string): string {
        try {
            return new Date(iso).toLocaleDateString(undefined, {
                year: 'numeric',
                month: 'short',
                day: 'numeric',
            });
        } catch {
            return '';
        }
    }
</script>

<Modal {open} size="narrow" {title} on:close={onclose}>
    <div class="ts-flag-modal">
        <p class="lead">
            {m.ts_flagmodal_lead()}
        </p>

        {#if loading}
            <p class="muted">{m.common_state_loading()}</p>
        {:else if comments.length}
            <ul class="comments">
                {#each comments as c, i (i)}
                    <li class="comment" class:mine={c.mine}>
                        <div class="meta">
                            {#if $canSeeIdentity && authorLabel(c)}
                                <span class="author">{authorLabel(c)}</span>
                            {:else if c.mine}
                                <span class="author">{m.ts_flagmodal_author_you()}</span>
                            {:else}
                                <span class="author muted">{m.ts_flagmodal_author_listener()}</span>
                            {/if}
                            <span class="when">{fmtDate(c.updated_at)}</span>
                        </div>
                        {#if c.comment}
                            <p class="body">{c.comment}</p>
                        {:else}
                            <p class="body muted">{m.ts_flagmodal_no_comment()}</p>
                        {/if}
                    </li>
                {/each}
            </ul>
        {/if}

        <label class="field">
            <span class="label">{commentLabel}</span>
            <textarea
                bind:value={draft}
                rows="3"
                placeholder={m.ts_flagmodal_textarea_placeholder()}
            ></textarea>
        </label>
    </div>

    <svelte:fragment slot="footer">
        <div class="footer-row">
            {#if myComment}
                <button type="button" class="btn-text danger" onclick={removeMine} disabled={saving}>
                    {m.ts_flagmodal_remove_report()}
                </button>
            {:else}
                <span></span>
            {/if}
            <div class="footer-actions">
                <button type="button" class="btn-text" onclick={onclose} disabled={saving}>{m.common_action_cancel()}</button>
                <button type="button" class="btn-primary" onclick={submit} disabled={saving}>
                    {submitLabel}
                </button>
            </div>
        </div>
    </svelte:fragment>
</Modal>

<style>
    .ts-flag-modal {
        padding: var(--s-5) var(--s-6);
        display: flex;
        flex-direction: column;
        gap: var(--s-4);
    }
    .lead {
        margin: 0;
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        line-height: 1.5;
    }
    .muted { color: var(--text-faint); }
    .comments {
        list-style: none;
        margin: 0;
        padding: 0;
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
        max-height: 240px;
        overflow: auto;
    }
    .comment {
        padding: var(--s-2) var(--s-3);
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-2);
        background: var(--panel-2);
    }
    .comment.mine { border-color: var(--accent); background: var(--accent-tint-soft); }
    .meta {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: var(--s-2);
        margin-bottom: 3px;
    }
    .author { font-size: var(--fs-meta); font-weight: 500; color: var(--text-primary); }
    .when { font-size: 10.5px; color: var(--text-faint); font-family: var(--font-mono); }
    .body { margin: 0; font-size: var(--fs-meta); color: var(--text-secondary); line-height: 1.5; white-space: pre-wrap; }
    .field { display: flex; flex-direction: column; gap: var(--s-1); }
    .label { font-size: var(--fs-meta); color: var(--text-secondary); }
    textarea {
        width: 100%;
        resize: vertical;
        padding: var(--s-2);
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-2);
        color: var(--text-primary);
        font: inherit;
        font-size: var(--fs-meta);
    }
    textarea:focus { outline: none; border-color: var(--accent); }
    .footer-row { display: flex; align-items: center; justify-content: space-between; width: 100%; }
    .footer-actions { display: flex; gap: var(--s-2); }
    .btn-text {
        background: transparent;
        border: 1px solid transparent;
        color: var(--text-muted);
        padding: 5px 10px;
        border-radius: var(--r-2);
        cursor: pointer;
        font: inherit;
        font-size: var(--fs-meta);
    }
    .btn-text:hover:not(:disabled) { color: var(--text-primary); background: var(--panel); }
    .btn-text.danger:hover:not(:disabled) { color: var(--state-error-fg, #f87171); }
    .btn-primary {
        background: var(--accent);
        border: 1px solid var(--accent);
        color: var(--accent-fg, #fff);
        padding: 5px 14px;
        border-radius: var(--r-2);
        cursor: pointer;
        font: inherit;
        font-size: var(--fs-meta);
    }
    .btn-primary:hover:not(:disabled) { filter: brightness(1.08); }
    .btn-primary:disabled, .btn-text:disabled { opacity: 0.55; cursor: default; }
</style>
