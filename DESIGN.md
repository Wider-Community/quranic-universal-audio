---
name: Quranic Universal Audio — Inspector
description: A quiet operator surface for a living archive of Quran recitations and their timestamps — dark by default, with a calm light peer.
colors:
  canvas: "oklch(0.186 0.042 285)"
  canvas-inset: "oklch(0.130 0.034 285)"
  panel: "oklch(0.236 0.055 270)"
  panel-2: "oklch(0.275 0.055 270)"
  elevated: "oklch(0.315 0.055 270)"
  border-quiet: "oklch(0.305 0.030 275)"
  border-default: "oklch(0.375 0.035 275)"
  border-strong: "oklch(0.490 0.040 275)"
  text-primary: "oklch(0.940 0.010 268)"
  text-secondary: "oklch(0.760 0.010 268)"
  text-muted: "oklch(0.560 0.010 268)"
  text-faint: "oklch(0.440 0.010 268)"
  accent: "oklch(0.785 0.130 220)"
  accent-strong: "oklch(0.840 0.135 220)"
  accent-fg: "oklch(0.140 0.020 220)"
  state-published: "oklch(0.840 0.135 150)"
  state-under-review: "oklch(0.860 0.130 220)"
  state-available: "oklch(0.840 0.110 300)"
  state-requested: "oklch(0.780 0.040 268)"
  state-discarded: "oklch(0.550 0.010 268)"
  state-error: "oklch(0.860 0.130 75)"
typography:
  display:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "32px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "22px"
    fontWeight: 600
    lineHeight: 1.2
  title:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "13.5px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "ui-monospace, 'SF Mono', 'JetBrains Mono', Menlo, Consolas, monospace"
    fontSize: "11.5px"
    fontWeight: 400
    lineHeight: 1.2
  arabic:
    fontFamily: "'DigitalKhatt', 'Traditional Arabic', 'Scheherazade New', 'Amiri', serif"
    fontSize: "1.84rem"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  sm: "3px"
  md: "5px"
  lg: "8px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "20px"
  s6: "24px"
  s8: "32px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.accent-fg}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  button-default:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  button-default-hover:
    backgroundColor: "{colors.panel-2}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.md}"
    padding: "8px 16px"
  state-pill:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.sm}"
    padding: "2px 8px"
  filter-chip:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.md}"
    padding: "4px 10px"
  input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "6px 10px"
  catalog-row:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.lg}"
    padding: "8px 12px"
  catalog-row-hover:
    backgroundColor: "{colors.panel-2}"
---

# Design System: Quranic Universal Audio — Inspector

## 1. Overview

**Creative North Star: "The Quiet Instrument"**

Inspector is a precision instrument that refuses to shout. Underneath it runs an enormous engine — a taxonomy of hundreds of reciters across many deliveries, a 60fps loop synchronizing thousands of word/letter/phoneme boundaries against a playhead, validation passes, audit trails, dataset releases. The visual system's entire job is to make none of that *feel* heavy. The surface is dark, still, and legible; the data is alive. Where most tools let complexity leak into chrome, this one holds it back so the recitation, the reciter's name, and the catalog itself are what the eye lands on.

One language, three moods. **Dashboard** orients and invites — let the scale speak through dense, confident data, never a hero metric. **Timestamps** calms and reveals — immense simultaneous computation surfaced as a single unified, distraction-free frame the listener rests inside. **Segments** equips and disappears — a workshop tuned for keyboard speed and trustworthy feedback. The vocabulary (surfaces, accent, pills, type) is identical across all three; only the density and stillness shift.

This system explicitly rejects the generic-SaaS-admin reflex (no hero-metric template, no identical icon-headline-text card grids, no blue-on-white modern-admin look), heavy bureaucratic density-for-its-own-sake (no six-toolbar Jira energy), religious-site cliché (no green-and-gold, no arabesque ornament, no calligraphic flourish as decoration — Arabic type is functional), and the media-player-that-shouts (no visualizer flash, no neon EQ, no motion competing with the audio).

**Key Characteristics:**
- Dark by default — built for multi-hour review sittings and relaxed listening, no flash-of-theme on load. A calm, cool light theme is a fully-supported opt-in peer (header toggle, persisted); it keeps the same blue-violet identity on paper rather than reaching for warm cream. Both themes flow from one token set — see [`docs/reference/theming.md`](docs/reference/theming.md).
- Flat tonal layering in dark, zero decorative shadow — depth is a five-step surface ramp, not elevation. Near white the light theme has no lightness headroom for that, so it adds a single soft shadow on floating surfaces (the one theme-conditional exception).
- One restrained cyan accent. Rarity is the point.
- OKLCH throughout, system fonts for chrome, one embedded Arabic face for the Quranic text.
- Calm scales with complexity: the busier the engine, the stiller the surface.

## 2. Colors

A cold, deep blue-violet darkness with a single cyan accent and a small, disciplined set of semantic state hues. Everything is OKLCH; the surface ramp is the backbone.

### Primary
- **Cyan Accent** (`oklch(0.785 0.130 220)`): the one interactive voice — links, primary actions, focus rings, the active playhead, current-selection highlights. Restrained chroma so it reads as a tool, not a glow. `accent-strong` (`oklch(0.840 0.135 220)`) is the hover/lift; `accent-fg` (`oklch(0.140 0.020 220)`) is the near-black text that sits *on* the accent for primary buttons.

### Secondary — Surface Ramp (the neutral spine)
A five-step blue-violet ramp carries all depth. Lighter = closer to the user.
- **Canvas** (`oklch(0.186 0.042 285)`): the page. Everything floats on this.
- **Canvas-inset** (`oklch(0.130 0.034 285)`): wells, scrollbar tracks, the recessed darkest layer.
- **Panel** (`oklch(0.236 0.055 270)`): filter rails, table headers, modal chrome, resting cards and rows.
- **Panel-2** (`oklch(0.275 0.055 270)`): hovered rows, expanded deliveries — the response to pointer.
- **Elevated** (`oklch(0.315 0.055 270)`): active pills and the topmost surfaces above panel.

### Tertiary — State Semantics
Each lifecycle state has a foreground hue used at full chroma for text/icon and the *same* hue at ~0.14 alpha for its pill background. Hue is never the sole signal — pair with label and shape.
- **Published** (`oklch(0.840 0.135 150)`, green): released to the dataset.
- **Under review** (`oklch(0.860 0.130 220)`, cyan): claimed and being worked.
- **Available** (`oklch(0.840 0.110 300)`, violet): claimable now.
- **Requested** (`oklch(0.780 0.040 268)`, grey): pending intake.
- **Discarded** (`oklch(0.550 0.010 268)`, muted grey): admin-only, reads as *demoted*, never as *error*.
- **Error** (`oklch(0.860 0.130 75)`, amber): loading/failure text only, kept separate so component CSS never reaches for a bucket color.

### Neutral — Text & Borders
Text is a four-step grey ramp on the dark surface; borders a three-step ramp.
- **Text** — primary `oklch(0.940 0.010 268)` (body, names), secondary `oklch(0.760 0.010 268)` (metadata), muted `oklch(0.560 0.010 268)` (de-emphasis), faint `oklch(0.440 0.010 268)` (dulled/disabled). Primary must clear 4.5:1 on canvas; never drop body text below `text-muted`.
- **Borders** — quiet `oklch(0.305 0.030 275)` (hairlines), default `oklch(0.375 0.035 275)` (resting separation), strong `oklch(0.490 0.040 275)` (emphasis, scrollbar thumb hover).

### Named Rules
**The One Accent Rule.** There is exactly one accent: cyan. It marks what is interactive or current. If a second saturated hue appears that is not a defined *state* color, it is a bug. Buttons do not get their own colors.

**The Hue-Plus-Label Rule.** State is never communicated by color alone. Every state hue ships with a text label and is safe to lose to color-blindness or grayscale.

## 3. Typography

**Body / UI Font:** system sans — `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`
**Label / Technical Font:** system mono — `ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, "Liberation Mono", monospace`
**Quranic Text Font:** `DigitalKhatt` (embedded as a base64 `@font-face` so Docker/LFS builds never lose it), falling back to `Traditional Arabic, Scheherazade New, Amiri, serif`.

**Character:** No display typeface, by design. Hierarchy comes from a tight size-and-weight scale in one well-tuned sans, with mono reserved for technical detail (IDs, counts, timing, codes) and the embedded Arabic face carrying every glyph of Quranic text. Warmth lives in line height and Arabic/Latin pairing, not in font choice.

### Hierarchy
- **Display** (600, 32px, lh 1.2, tracking −0.01em): page-level titles. The ceiling — nothing larger in chrome.
- **Headline** (600, 22px, lh 1.2): section and modal headers.
- **Title** (600, 16px, lh 1.5): card/row headers, group labels.
- **Body** (400, 13.5px / row 14px, lh 1.5): the workhorse — table rows, descriptions, controls. Prose caps at 65–75ch; dense tables may run wider.
- **Label** (400, 11.5px, mono): metadata, counts, timing readouts, technical chips. Use `font-variant-numeric: tabular-nums` for any aligned figures.
- **Arabic** (400, ~1.84rem, lh 1.6, RTL): Quranic text and reciter names. Sized larger than surrounding chrome — it is the subject, not an annotation.

### Named Rules
**The Fixed-Scale Rule.** Type sizes are a fixed rem/px ladder (11.5 · 13.5 · 14 · 16 · 22 · 32), not fluid clamps. Users view at consistent DPI in panels and sidebars; a shrinking heading looks worse, not better.

## 4. Elevation

This system is **flat. There are no decorative shadows.** Depth is conveyed entirely by the five-step surface ramp: a resting card sits on `panel`, lifts to `panel-2` on hover, and an active surface reaches `elevated`; wells recede to `canvas-inset`. Stacking is communicated by lightness, not by cast shadow. If a surface looks like it's floating on a blurred drop-shadow, it's wrong for this system.

The only `box-shadow` permitted is a **focus ring** — a tight `0 0 0` spread of `accent-tint`, used to indicate keyboard focus or an active control, never to fake elevation.

The **light theme** is the one exception: near white there is no lightness headroom to float a surface by ramp alone, so floating surfaces (dropdowns, drop-ups, modals) carry a single soft `--shadow-*` token. That shadow is `none` in dark — the flat rule still holds there. Elevation is the same idea in both, expressed differently: ramp in dark, ramp-plus-soft-shadow in light.

### Named Rules
**The Flat-By-Default Rule.** In dark, surfaces are flat at rest and flat on hover; the single allowed shadow is the accent focus ring, and ambient/structural drop-shadows are forbidden (reach for the next step up the surface ramp instead). In light, a soft `--shadow-*` is permitted on genuinely floating surfaces only.

## 5. Components

One vocabulary across all three tabs. Lead with the token primitives; new work consumes `var(--token)`, never raw values.

### Buttons
- **Shape:** gently rounded, `5px` (`--r-2`). Padding `8px 16px` (`--s-2 --s-4`); large variant `12px 20px`.
- **Primary:** `accent` background with `accent-fg` (near-black) text. The only colored button. Reserved for the single most important action in a context.
- **Default:** `panel` background, `text-primary`, `border-default` hairline; hover lifts to `panel-2`. The everyday button.
- **Ghost:** transparent, `text-secondary`, no border; hover raises text to `text-primary`. For low-emphasis and inline actions.
- **States:** every button ships default / hover / focus-visible (accent ring) / active / disabled (`text-faint`, no pointer). Transitions `120–200ms`.

### Chips / Pills
- **State pill:** label + hue, hue at full chroma for text on the same hue at ~0.14 alpha, `3px` radius, `2px 8px` padding. Always carries a word, never color alone.
- **Filter chip:** transparent resting, `text-secondary`, `5px` radius; selected fills `accent-tint` with `accent` text; empty/zero-count chips dull to `text-faint` (still ≥ AA) and show their count, so the user sees what's possible without clicking.

### Cards / Rows
- **Corner:** `8px` (`--r-3`) for catalog rows and primary cards.
- **Background:** `panel` at rest, `panel-2` on hover; a 2px transparent border that becomes `accent` when the row is the active/playing one.
- **Border / depth:** hairline `border-default`; never a left/right colored stripe, never nested.
- **Padding:** `8px 12px` typical (`--s-2 --s-3`).

### Inputs / Selects
- **Style:** `panel` background, `border-default` hairline, `3px` radius, `6px 10px` padding, `text-primary`.
- **Focus:** accent ring (`0 0 0` spread of `accent-tint`) plus border shift toward `accent`. No glow beyond the ring.
- **Disabled / empty:** `text-faint`, dulled border.

### Navigation (tabs)
- Top tab bar on `panel`; active tab carries the `canvas` background (reads as "you are here, recessed into the page") with `text-primary`; inactive tabs `text-secondary`, hover to `text-primary`. The bottom player and its analysis controls are app-shell-owned and persist across tab switches so audio, animation, and the waveform cursor never reset.

### Signature: The Unified Timestamps Display
The defining custom surface. A waveform (server-rendered peaks, boundary markers gated by the active tier) sits above a "mega" analysis frame that stacks words → letters → phonemes → translations for the focus verse. Structure is declarative; per-frame highlights (`.active` / `.past` on the current word/letter/phoneme) are applied imperatively from a 60fps loop, never via reactive re-render. Tier hues are consistent between the waveform bands and the display rows so the eye links them. The whole frame must read as *one calm object* — the listener witnesses the alignment, the controls (loop, tier toggles, speed, translations globe) recede into the shared footer until summoned.

## 6. Do's and Don'ts

### Do:
- **Do** consume tokens via `var(--token)` for every new surface — colors, `--s-*` spacing, `--r-1/2/3` radii, `--fs-*` sizes, `--t-*`/`--ease-*` motion. The token file is the system.
- **Do** keep exactly one accent (cyan). Mark interactive and current state with it and nothing else.
- **Do** convey depth with the surface ramp: `canvas` → `panel` → `panel-2` → `elevated`, wells to `canvas-inset`.
- **Do** pair every state hue with a text label and verify it survives grayscale and color-blindness.
- **Do** render reciter names and Quranic text in the DigitalKhatt Arabic face, larger than chrome, with correct RTL/bidi, transliteration paired alongside.
- **Do** hold transitions to `120–200ms` and degrade them to instant under `prefers-reduced-motion: reduce` — including the Timestamps animation chrome.
- **Do** let the busier surfaces get *quieter*: on Timestamps, every pixel of motion or color must serve comprehension or calm.

### Don't:
- **Don't** introduce Material-Design button colors (`#4361ee` primary, `#2e7d32` green, `#6d1a1a` red, `#6a1b9a` purple, etc.) or any per-button palette. There is one accent; buttons use `panel` / `accent` / transparent. *(The live app still carries a legacy Material button palette in older CSS — it is drift, not the system. New work must not extend it.)*
- **Don't** hardcode hex, off-scale radii (`4px`, `6px`, `10px`, `12px`), or ad-hoc rem font sizes. Snap to the token scales (`3/5/8px` radii, the `--fs-*` ladder). *(Older components drift to `4`/`6px` and ad-hoc rem; do not copy them.)*
- **Don't** add decorative shadows or glassmorphism. Dark surfaces are flat; the only dark shadow is the accent focus ring. (Light adds a single soft `--shadow-*` on floating surfaces only — see Elevation.)
- **Don't** use a `border-left`/`border-right` colored stripe on cards, rows, or callouts. Use full hairline borders, surface tint, or the active-row accent border.
- **Don't** ship a hero-metric block (big number, small label, gradient accent) or an identical icon-headline-text card grid. Let the catalog data carry the scale.
- **Don't** decorate the religious content: no green-and-gold, no arabesque borders, no mosque silhouettes, no calligraphic flourish as ornament. Arabic type is functional.
- **Don't** let the Timestamps surface shout — no visualizer flash, neon EQ bars, or motion that competes with the recitation.
- **Don't** drop body text below `text-muted`, or use color as the only state signal.
