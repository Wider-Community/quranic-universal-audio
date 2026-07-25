<!--
  AutoBadge — a small "following the device" monitor glyph pinned to the corner
  of a header toggle (ThemeToggle / LocaleSwitcher). Signals that the control is
  in its auto/system state: the button shows the RESOLVED value (sun/moon, or the
  active language) and this badge marks it as device-driven, rather than swapping
  the whole icon for a monitor.

  Colour is inherited (`currentColor`), so it tracks the parent button's
  hover/focus accent for free. The parent must be `position: relative`.
-->
<script lang="ts"></script>

<span class="auto-badge" aria-hidden="true">
    <svg viewBox="0 0 24 24" width="9" height="9" fill="none" stroke="currentColor"
         stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2" />
        <path d="M8 21h8M12 17v4" />
    </svg>
</span>

<style>
    .auto-badge {
        position: absolute;
        top: -4px;
        inset-inline-end: -4px;
        display: grid;
        place-items: center;
        width: 13px;
        height: 13px;
        border-radius: 4px;
        /* Sits ON the control — a contrasting well against the button surface so
           it reads as a distinct badge, not part of the glyph. Inherits the
           button's text colour so it follows hover/focus accent. */
        background: var(--canvas);
        border: 1px solid var(--border-default);
        color: inherit;
        pointer-events: none;
        animation: badge-in 180ms var(--ease-out-quart, ease-out) both;
    }
    @keyframes badge-in {
        from { opacity: 0; transform: scale(0.6); }
        to { opacity: 1; transform: none; }
    }
    @media (prefers-reduced-motion: reduce) {
        .auto-badge { animation: none; }
    }
</style>
