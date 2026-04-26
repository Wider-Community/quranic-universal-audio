<script lang="ts">
    /**
     * TimeEdit — one `hh:mm:ss.MMM` time with per-digit-group typed entry.
     *
     * Two modes:
     *   - `editing=false` — renders as a single clickable text span. Parent
     *     (TimeRange) handles the click by entering trim mode.
     *   - `editing=true`  — renders four digit-group spans; each clickable if
     *     the clamped range admits a different value. Clicking (or arrow-nav
     *     across the edge of) an editable group promotes it to a focused
     *     `<input>`. Non-editable groups stay as greyed, inert spans.
     *
     * **Multi-field composition.** Typed values accumulate in a local
     * `pendingParts` buffer across field moves (click / arrow-nav / Tab)
     * WITHOUT committing to `_trimWindow`. This lets the user type an
     * intermediate state that would be out-of-range in isolation (e.g.
     * type `mm=01` before `ss=05` when the final `01:05` is valid) without
     * the composed time's mid-edit invalidity blocking them. Only on the
     * explicit commit (Enter) does the composed `hh:mm:ss.MMM` get validated
     * against `bounds` and flushed via `onCommit`.
     *
     * Invalid commit → whole-widget red border (via `.seg-text-time.invalid`),
     * input stays open for further editing. Click-outside (blur-to-non-widget)
     * commits if valid, else reverts to `value` and closes.
     *
     * **Drag deselect.** The parent passes `value` from `$trimWindow` during
     * an active edit. Drag on the trim canvas updates `$trimWindow`, which
     * flows into `value`. When `value` changes AND doesn't match the user's
     * composed `pendingParts`, we reset `pendingParts` from the new value and
     * drop focus — so the drag-moved handle's new time appears live in the
     * display instead of being masked by a stale typed buffer.
     */

    import { tick } from 'svelte';

    import { formatHmsMs, composeHmsMs, splitHmsMs } from '../../utils/data/references';

    export let value: number;                     // ms
    export let bounds: { min: number; max: number } | null;
    export let editing: boolean;                  // row is in active-edit + this side was clicked
    export let autoFocusGroup: 'hh' | 'mm' | 'ss' | 'mmm' | null = null;
    /** Idle-click handler. `group` is the specific digit group the user
     *  clicked on, or null if the click landed on the wrapper / a separator.
     *  Parent uses it as `autoFocusGroup` so the user lands IN the group they
     *  aimed at — no longer always-default to ss. */
    export let onTimeClick: (group: 'hh' | 'mm' | 'ss' | 'mmm' | null) => void;
    export let onCommit: (newMs: number) => void; // fired on Enter/blur if composed value valid

    type Group = 'hh' | 'mm' | 'ss' | 'mmm';
    type Parts = { hh: number; mm: number; ss: number; mmm: number };
    const GROUPS: Group[] = ['hh', 'mm', 'ss', 'mmm'];

    let focusedGroup: Group | null = null;
    let buffer = '';
    let wholeInvalid = false;
    let inputEl: HTMLInputElement | undefined;
    let spanEl: HTMLSpanElement | undefined;
    /** True while `promoteGroup` is swapping focus from one group's input to
     *  another. Svelte tears down the old `<input>` synchronously when we
     *  reassign `focusedGroup`, which fires a spurious blur before the new
     *  input mounts. Without this guard, `onBlur` would call `commitAll` +
     *  reset state, nuking the group switch. Reset after the new input is
     *  focused. */
    let switchingGroup = false;
    /** Parts-in-progress. `null` when not editing. Each field edit mutates the
     *  matching entry; commit flushes the composed value. */
    let pendingParts: Parts | null = null;
    /** Last `value` the pending buffer was synced against. Lets us detect
     *  externally-driven `value` changes (drag) and reset. */
    let syncedValue: number = value;
    /** One-shot latch for our own local Enter-commit. While the parent prop
     *  is catching up to the just-committed value, ignore the temporary
     *  mismatch so we don't treat our own commit like an external drag. */
    let awaitingCommittedValue: number | null = null;
    /** Single-shot auto-focus latch (see `editing && autoFocusGroup` block). */
    let autoPromoted = false;

    // A group is "editable" iff the clamped range spans its boundary — some
    // change to that group, possibly together with others, yields a valid time.
    $: editable = computeEditable(bounds);

    function computeEditable(b: { min: number; max: number } | null): Record<Group, boolean> {
        if (!b) return { hh: false, mm: false, ss: false, mmm: false };
        const { min, max } = b;
        return {
            hh: Math.floor(min / 3600000) !== Math.floor(max / 3600000),
            mm: Math.floor(min / 60000)   !== Math.floor(max / 60000),
            ss: Math.floor(min / 1000)    !== Math.floor(max / 1000),
            mmm: min !== max,
        };
    }

    function maxLenFor(g: Group): number { return g === 'mmm' ? 3 : 2; }

    function formatGroupBuffer(g: Group, parts: Parts): string {
        const raw = parts[g];
        return g === 'mmm'
            ? raw.toString().padStart(3, '0')
            : raw.toString().padStart(2, '0');
    }

    // Session start: initialize pendingParts from value on first edit.
    $: if (editing && pendingParts === null) {
        pendingParts = splitHmsMs(value);
        syncedValue = value;
    }

    // Session end: drop all local state so the next click starts fresh.
    $: if (!editing) {
        pendingParts = null;
        focusedGroup = null;
        buffer = '';
        wholeInvalid = false;
        autoPromoted = false;
        syncedValue = value;
        awaitingCommittedValue = null;
    }

    // Drag interrupt: `value` changed externally (drag moved the handle).
    // `syncedValue` is only updated on our OWN commits and on session reset,
    // so a mismatch here uniquely identifies an external change. Reset the
    // pending buffer to the new value and drop focus so the live drag
    // position shows through the display.
    $: if (editing && pendingParts !== null) {
        if (awaitingCommittedValue !== null) {
            if (value === awaitingCommittedValue) {
                syncedValue = value;
                awaitingCommittedValue = null;
            }
        } else if (value !== syncedValue) {
            pendingParts = splitHmsMs(value);
            syncedValue = value;
            if (focusedGroup) { focusedGroup = null; buffer = ''; }
            wholeInvalid = false;
        }
    }

    // First-time auto-focus the clicked side's preferred group.
    $: if (editing && autoFocusGroup && !autoPromoted && !focusedGroup && pendingParts) {
        autoPromoted = true;
        const want = autoFocusGroup;
        const pick: Group | null = (editable[want] ? want
            : (GROUPS.find((g) => editable[g]) ?? null));
        if (pick) void promoteGroup(pick);
    }

    async function promoteGroup(g: Group): Promise<void> {
        switchingGroup = true;
        if (!pendingParts) pendingParts = splitHmsMs(value);
        focusedGroup = g;
        buffer = String(pendingParts[g]);
        await tick();
        inputEl?.focus();
        inputEl?.select();
        switchingGroup = false;
    }

    function onGroupClick(g: Group): void {
        if (!editing) return;
        if (!editable[g]) return;
        // If another group is focused, save its buffer into pendingParts
        // before promoting the new one (field-to-field move preserves state).
        saveBufferToPending();
        void promoteGroup(g);
    }

    function onWholeClick(e: MouseEvent): void {
        if (editing) return;
        e.stopPropagation();
        // Walk up from the actual event target to find a `.seg-time-group`
        // span with a data-group — that tells us which digit the user
        // aimed at. Clicks on separators / whitespace yield null, which
        // the parent interprets as "default to ss".
        let el = e.target as HTMLElement | null;
        let g: Group | null = null;
        while (el && el !== spanEl) {
            const d = el.dataset?.group as Group | undefined;
            if (d) { g = d; break; }
            el = el.parentElement;
        }
        onTimeClick(g);
    }

    /** Save the current input buffer into `pendingParts[focusedGroup]`, if
     *  the buffer parses to a valid non-negative integer. Empty or invalid
     *  buffers are ignored (user is mid-retype or typo — don't clobber). */
    function saveBufferToPending(): void {
        if (!focusedGroup || !pendingParts) return;
        const t = buffer.trim();
        if (t === '' || !/^\d+$/.test(t)) return;
        // Reassign instead of in-place mutate so Svelte sees the change and
        // re-runs `groupDisplay` (which gates the spans' rendered text).
        pendingParts = { ...pendingParts, [focusedGroup]: parseInt(t, 10) };
    }

    function onInput(): void {
        // Flush to pendingParts so arrow-nav or field-click preserves state.
        // No validation feedback here per spec — only on Enter.
        saveBufferToPending();
        wholeInvalid = false;
    }

    /** Attempt to commit the composed pending time. On valid, call onCommit
     *  and close the input. On invalid, set wholeInvalid + keep input open
     *  (user can continue typing / arrow-nav to fix). */
    function commitAll(opts: { stayOpen?: boolean } = {}): boolean {
        saveBufferToPending();
        if (!pendingParts || !bounds) return false;
        // Per-group sanity: clock digits (mm/ss/mmm) must be within their
        // natural ranges. hh is unbounded above (beyond bounds.max check).
        if (pendingParts.mm >= 60 || pendingParts.ss >= 60 || pendingParts.mmm >= 1000
            || pendingParts.mm < 0 || pendingParts.ss < 0 || pendingParts.mmm < 0
            || pendingParts.hh < 0) {
            wholeInvalid = true;
            return false;
        }
        const composed = composeHmsMs(pendingParts.hh, pendingParts.mm, pendingParts.ss, pendingParts.mmm);
        if (composed < bounds.min || composed > bounds.max) {
            wholeInvalid = true;
            return false;
        }
        wholeInvalid = false;
        const committedParts = { ...pendingParts };
        const committedGroup = focusedGroup;
        // Track what we're about to push so the value-watching reactive doesn't
        // treat our own commit as a drag.
        syncedValue = composed;
        awaitingCommittedValue = composed;
        onCommit(composed);
        if (opts.stayOpen && committedGroup) {
            buffer = formatGroupBuffer(committedGroup, committedParts);
            void tick().then(() => {
                if (!inputEl) return;
                inputEl.focus();
                const end = buffer.length;
                inputEl.setSelectionRange(end, end);
            });
        } else {
            focusedGroup = null;
            buffer = '';
        }
        return true;
    }

    /** Revert all pending state to the committed `value`, close the input. */
    function revertAll(): void {
        pendingParts = splitHmsMs(value);
        syncedValue = value;
        awaitingCommittedValue = null;
        focusedGroup = null;
        buffer = '';
        wholeInvalid = false;
    }

    /** Return the next editable group in `dir`, skipping greyed groups. */
    function neighborEditable(from: Group, dir: 1 | -1): Group | null {
        const i = GROUPS.indexOf(from);
        for (let j = i + dir; j >= 0 && j < GROUPS.length; j += dir) {
            const g = GROUPS[j];
            if (g && editable[g]) return g;
        }
        return null;
    }

    function onKeydown(e: KeyboardEvent): void {
        e.stopPropagation();
        if (e.key === 'Enter') {
            e.preventDefault();
            commitAll({ stayOpen: true });
        } else if (e.key === 'Escape') {
            e.preventDefault();
            revertAll();
        } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
            if (!focusedGroup) return;
            const atEdge = e.key === 'ArrowRight'
                ? (inputEl?.selectionStart === buffer.length && inputEl?.selectionEnd === buffer.length)
                : (inputEl?.selectionStart === 0 && inputEl?.selectionEnd === 0);
            if (!atEdge) return;
            const dir = e.key === 'ArrowRight' ? 1 : -1;
            const next = neighborEditable(focusedGroup, dir);
            if (!next) return;
            e.preventDefault();
            // Move to neighbor WITHOUT committing — pendingParts holds the
            // intermediate state so multi-field composition works.
            saveBufferToPending();
            void promoteGroup(next);
        }
    }

    function onBlur(e: FocusEvent): void {
        // Mid-swap between groups — the unmount blur is not user intent.
        if (switchingGroup) return;
        // If focus moved to another element within this TimeEdit widget (a
        // group span or another input), treat as internal nav — don't commit.
        // Only commit when leaving the widget entirely.
        const rel = e.relatedTarget as Node | null;
        if (rel && spanEl && spanEl.contains(rel)) return;
        // Clicking outside: try to commit. If invalid, just close the input
        // (clear focusedGroup/buffer) but KEEP pendingParts intact — do not
        // call revertAll(), which would wipe the user's in-progress typing
        // and snap the display back to the committed value. The user can
        // still see what they typed (with the red border carrying over),
        // and Apply will pull from canvas._trimWindow which still has the
        // last successfully-committed value.
        if (!commitAll()) {
            focusedGroup = null;
            buffer = '';
        }
    }

    function onInputClick(e: MouseEvent): void {
        e.stopPropagation();
    }

    // Per-group rendered string, surfaced as a reactive so the template can
    // depend on `groupDisplay[g]` directly. Svelte does NOT trace template
    // deps through helper-function calls — `{displayFor(g)}` in the markup
    // would render once and not re-run when `pendingParts` / `value` change
    // under it, which broke live stepper + drag updates to the editing
    // side's digits. Flow via a reactive makes those updates observable.
    $: groupDisplay = buildGroupDisplay(editing, pendingParts, value);

    function buildGroupDisplay(
        _editing: boolean,
        _pending: Parts | null,
        _value: number,
    ): Record<Group, string> {
        const parts = (_editing && _pending) ? _pending : splitHmsMs(_value);
        return {
            hh:  parts.hh.toString().padStart(2, '0'),
            mm:  parts.mm.toString().padStart(2, '0'),
            ss:  parts.ss.toString().padStart(2, '0'),
            mmm: parts.mmm.toString().padStart(3, '0'),
        };
    }
</script>

{#if !editing}
    <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
    <span class="seg-text-time clickable" on:click={onWholeClick}
        bind:this={spanEl}
        title="Click to adjust boundaries">{#each GROUPS as g, i}<span class="seg-time-group" data-group={g}>{groupDisplay[g]}</span>{#if i < GROUPS.length - 1}<span class="seg-time-sep">{i === 2 ? '.' : ':'}</span>{/if}{/each}</span>
{:else}
    <span class="seg-text-time seg-text-time-editing" class:invalid={wholeInvalid}
        bind:this={spanEl}>
        {#each GROUPS as g, i}
            {#if focusedGroup === g}
                <input
                    bind:this={inputEl}
                    class="seg-time-group-input"
                    type="text"
                    inputmode="numeric"
                    maxlength={maxLenFor(g)}
                    bind:value={buffer}
                    on:input={onInput}
                    on:keydown={onKeydown}
                    on:blur={onBlur}
                    on:click={onInputClick}
                    style="width: {maxLenFor(g) === 3 ? '2.2em' : '1.6em'}"
                />
            {:else}
                <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
                <span class="seg-time-group"
                    class:editable={editable[g]}
                    class:greyed={!editable[g]}
                    on:click={() => onGroupClick(g)}>{groupDisplay[g]}</span>
            {/if}
            {#if i < GROUPS.length - 1}
                <span class="seg-time-sep">{i === 2 ? '.' : ':'}</span>
            {/if}
        {/each}
    </span>
{/if}
