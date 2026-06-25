---
name: i18n
description: Use when localizing the Inspector frontend — extracting UI strings into Paraglide messages, adding/wiring `m.*()` calls in Svelte components, authoring en/ar message JSON, translating chrome to Arabic (MSA), or verifying i18n coverage. Trigger phrases include "internationalize", "localize", "translate to Arabic", "extract strings", "i18n", "add a message key", "wire up the locale switcher".
---

# i18n

The canonical, self-contained playbook for localizing the Inspector SPA. Every downstream i18n agent (string-finder, translator, wiring agent, browser-tester) reads this and follows it. **Read the reference subfile that matches your task — don't preload all of them.**

The stack is **Paraglide JS 2.x** (inlang message-format). English (`en`) is the source locale; Arabic (`ar`, Modern Standard) is the first target. It is already installed and wired — you add keys + wire components, you do **not** re-scaffold.

## Scope & order (LOCKED)

This is **workflow 1: strings only.** Arabic strings ship into chrome that **stays LTR-positioned** — the full RTL layout flip is a **separate, later workflow** (it updates PRODUCT.md's "don't flip the whole component" principle). Your job here is *accurate strings that don't visually mangle the still-LTR layout*, achieved via bidi isolation (see `arabic-conventions.md` §8) — **not** a flipped layout.

**Coverage order (don't get ahead of it):**
1. **Public surfaces first** — Dashboard (`dashboard_*`) + Timestamps (`ts_*`). These are the priority.
2. **User approves** the public pass → **then** Segments (`segments_*`).
3. **Admin is English-default, lowest priority** — do it last, only when asked.

## Golden rules

1. **Hand-author the message JSON. NEVER round-trip through the inlang editor / Sherlock VS Code extension** — they collapse the split `pathPattern` array into the *last* file and silently blank the others, and it still passes `build`. Edit `{en,ar}.json` with the Write/Edit tools only. → `paraglide.md`, `project-conventions.md` §2.
2. **Keys are flat, `snake_case`, area-prefixed** (`common_` / `errors_` / `dashboard_` / `ts_` / `segments_`). Paraglide flattens everything into one `m.*()` namespace; the prefix is the only thing stopping a `title` in one tab clobbering a `title` in another (duplicate ids resolve **last-wins, silently**). → `project-conventions.md` §1.
3. **en ↔ ar files stay key-for-key identical** (same id set, same order). A missing key in one locale silently drops it. Author the en key, then the ar key in the same position in the sibling file.
4. **Translate chrome, never data.** Reciter names, surah names (use API `name_ar`/`name_en`), Quran text/tokens/shard letters are data — never keyed. → §"don't-translate" below + `arabic-conventions.md` §6.
5. **A Svelte file is fully runes OR fully legacy — never mix.** Wire each per its mode (below). Do not introduce a single rune into a legacy file.
6. **Arabic follows the LOCKED conventions** — MSA formal-neutral, no tashkeel in chrome, Western digits, Arabic punctuation, ICU plurals with all 6 categories, bidi-isolate mixed runs. → `arabic-conventions.md` (authoritative; apply without re-deciding).
7. **Verify after every batch:** `npm run check` + `npm run build` green, en/ar keys synced. **Do NOT run `npm run lint`** (pre-commit hook owns it; a manual pass fails on native-binding in fresh worktrees). → `project-conventions.md` §9.

## The loop: extract → key → translate → verify

1. **Extract** — find the hardcoded chrome string (text node, or `aria-label`/`title`/`placeholder`/`alt`). Start at the **seams** where copy already lives centralized: `lib/errors/friendly.ts`, `lib/sign-in-messages.ts`, the `*_LABELS` enum→display maps. → `project-conventions.md` §7.
2. **Key** — invent `area_component_purpose` (snake_case, area-prefixed). **Grep the whole `messages/` tree for the id first** — collisions are the silent last-wins bug. Add it to the area's `en.json` **and** `ar.json` in the same position.
3. **Translate** — author the `ar` value per `arabic-conventions.md`. Counts → ICU plural with all 6 Arabic categories. Mixed Arabic+Latin/number → bidi-isolate the foreign run.
4. **Wire** — replace the literal with `m.<key>()` using the correct per-mode pattern (below).
5. **Verify** — `npm run check` && `npm run build` green; en/ar key parity (`diff` of sorted keys).

## Translate vs. don't-translate

| Translate (UI chrome the app authored) | Do NOT translate (data the API owns) |
|---|---|
| Button / label / heading / tab / menu text | Reciter names (catalog data) |
| `aria-label`, `title`, `placeholder`, `alt` | Surah / chapter names → pick API `name_ar` / `name_en` by locale |
| Validation card **titles + descriptions** (at render site — see registry caveat) | Quran text, tokens, ayah glyphs, waveform shard letters |
| Error copy (`friendly.ts`), toasts, confirmations, sign-in prompts | Enum **values** sent to the backend (state/role/severity codes) |
| Keyboard-shortcut **labels/descriptions** (not the bindings) | Slugs, file paths, job IDs, SHAs, version tags, capability keys |
| Enum-derived **pills/badges** (the *display* string) | IDs, timestamps, bitrates, `surah:ayah` codes, units |
| Domain *labels* — "Surah", "Ayah 5", "Riwayah:" (key the label) | Product name ("Quranic Universal Audio", "Inspector"), brands (Hugging Face, GitHub, OAuth) |

The nuance: **ayah / surah / riwayah as a UI *label* is translatable chrome** (key it); the **entity value** it points at is Arabic data (leave it). See `arabic-conventions.md` §5–6 for the full glossary + do-not-translate list.

## Wiring patterns (Svelte5 runes vs legacy Svelte4)

Both rest on one fact: **`m.*()` reads the *ambient* locale** set by Paraglide's `setLocale()`. The per-mode question is only *how the component re-renders when the locale flips.* The single switch entry point is `switchLocale()` in `src/lib/i18n/locale-store.ts` (it updates the Paraglide ambient locale + the legacy store + the rune cell + `<html dir/lang>` together).

**(a) Runes files** — `import * as m`, call `m.x()` inline. Reactivity comes from reading the `i18n` rune (`src/lib/i18n/locale.svelte.ts`):

```svelte
<script lang="ts">
  import * as m from '$lib/paraglide/messages';
  import { i18n } from '$lib/i18n/locale.svelte';
  // Reading i18n.locale makes this $derived re-run on switch.
  const heading = $derived((i18n.locale, m.dashboard_catalog_heading()));
</script>
<h1>{heading}</h1>
<input placeholder={m.dashboard_catalog_search_placeholder()} />
```
A top-level read of `i18n.locale` is enough to re-render the whole component; when in doubt gate a `$derived` on it.

**(b) Legacy Svelte-4 files** (e.g. `App.svelte`) — never add a rune. Subscribe to the `localeStore` mirror and reference `$localeStore` in a reactive block so Svelte-4 reactivity re-evaluates the message calls. The `(dep, m.x())` comma-sequence is the load-bearing trick — it makes the statement *depend* on the store while still evaluating to the string (a `tr<T>(dep, value)` helper in `locale-store.ts` does the same):

```svelte
<script lang="ts">
  import * as m from '$lib/paraglide/messages';
  import { localeStore } from '$lib/i18n/locale-store';
  $: lang = $localeStore;
  $: saveLabel = (lang, m.common_action_save());
</script>
<button on:click={onSave}>{saveLabel}</button>
```
If a legacy file is too tangled to thread `$localeStore` through every call, you have **exactly two** sanctioned options: migrate the file to runes first, **or** keep it legacy with the `$localeStore` idiom. Never a third.

**Attributes** take the function call directly: `placeholder={m.x()}`, `aria-label={m.x()}`, `title={m.x()}`, `alt={m.x()}`. In **legacy** files bind them to a reactive `$: label = ($localeStore, m.x())` value or they go stale after a switch.

## Interpolation & ICU plurals

Pass data through **message params**, never concatenation that splices chrome + data:
```jsonc
"dashboard_catalog_result_count": "Showing {shown} of {total} reciters"
```
```svelte
{m.dashboard_catalog_result_count({ shown, total })}
```
Counts use **ICU plural variants**. English has 2 forms; **Arabic has all 6** (`zero`, `one`, `two`, `few`, `many`, `other`) — author every one in `ar.json` or it falls through to `other` and reads wrong. FORBIDDEN: `{n === 1 ? '' : 's'}` and sentence-from-fragments concatenation. Full ICU shapes + Arabic category boundaries are in `project-conventions.md` §5 and `arabic-conventions.md` §10.

## Bundle note: per-message deep imports

The compiler emits `outputStructure: 'message-modules'` — **one module per message** under `src/lib/paraglide/messages/<key>.js`. The barrel `import * as m from '$lib/paraglide/messages'` is the normal call style and tree-shakes. For a **thin-slice seam** that must stay lazy (e.g. `sign-in-messages.ts` backing object-keyed getters), deep-import the single message: `$lib/paraglide/messages/common_signin_edit_title`. Mind inlang issue **#668** (barrel vs deep-import) — details in `paraglide.md`.

## Reference subfiles

| File | Read it when |
|---|---|
| `paraglide.md` | Library specifics — `project.inlang` location, array `pathPattern`, generated output dir, compile/build-order rule, the locale rune + `setLocale(reload:false)`, switching locale in dev, deep-import vs barrel (#668), hand-author-only constraint. |
| `arabic-conventions.md` | **Authoritative** Arabic (MSA) chrome style — register, numerals, tashkeel, punctuation, the binding glossary, do-not-translate, interim bidi, gender/formality, ICU plurals, length/overflow. Apply verbatim. |
| `project-conventions.md` | Engineering contract — key naming/prefixes, file layout, hand-author rule, what to translate, per-mode wiring, interpolation/plurals, the **seams**, the **registry parity caveat**, deferred guides, verification commands. |
