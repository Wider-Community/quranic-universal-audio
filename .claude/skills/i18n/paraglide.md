# Paraglide — our installed setup

Library specifics for **this repo's actual installation**, not generic Paraglide docs. Everything below was verified against the live bootstrap (`npm run check` / `build` / `test` all green). Use exactly these names and paths.

## Installed versions (exact, pinned)

- `@inlang/paraglide-js` → **2.20.1** (compiler + `paraglideVitePlugin` + `paraglide-js` CLI + runtime). Pinned exact (no caret), `devDependencies`.
- `@inlang/plugin-message-format` → **4.4.0**. Pinned exact, `devDependencies`.

Node ≥ 24 in the dev env (requirement is ≥ 18).

## Where things live

| Thing | Path (under `inspector/frontend/`) |
|---|---|
| inlang project settings | `project.inlang/settings.json` |
| Message JSON (split by area) | `src/lib/i18n/messages/common/{en,ar}.json`, `src/lib/i18n/messages/errors/{en,ar}.json`, `src/tabs/{dashboard,timestamps,segments}/messages/{en,ar}.json` |
| **Generated output** (gitignored) | `src/lib/paraglide/` |
| Locale rune (runes-facing) | `src/lib/i18n/locale.svelte.ts` |
| Locale store mirror (legacy-facing) | `src/lib/i18n/locale-store.ts` |
| Locale switcher component | `src/lib/components/LocaleSwitcher.svelte` |
| Compile wiring | `vite.config.ts` (plugin) + `package.json` (`paraglide:compile` script) |

The `$lib` alias resolves to `src/lib` (added to `vite.config.ts`, `tsconfig.json`, **and** `vitest.config.ts` — vitest has its own config and needs its own alias or `$lib/paraglide/*` imports fail to resolve in tests). So `$lib/paraglide/messages` and `$lib/i18n/...` are the canonical import prefixes.

## `project.inlang/settings.json` — the array `pathPattern`

`baseLocale: "en"`, `locales: ["en", "ar"]`, message-format module pinned `@4.4.0`. The plugin's `pathPattern` is an **array**, merged into the flat namespace at compile time. **`common` is LAST** so that if the inlang editor ever does write back (it must not — see below), exports land in `common` rather than scattering — but the real defense is hand-authoring.

```jsonc
"plugin.inlang.messageFormat": {
  "pathPattern": [
    "./src/tabs/dashboard/messages/{locale}.json",
    "./src/tabs/timestamps/messages/{locale}.json",
    "./src/tabs/segments/messages/{locale}.json",
    "./src/lib/i18n/messages/errors/{locale}.json",
    "./src/lib/i18n/messages/common/{locale}.json"
  ]
}
```

**Invariant:** every file in the array must exist for **every** locale. A missing `ar.json` for one area silently drops those keys. A new area = **two** files (en + ar) + **one** `pathPattern` line.

## Generated output

Output dir: **`src/lib/paraglide/`** — `runtime.js` + `.d.ts`, `messages.js` (the barrel), per-message `messages/<key>.js` + `.d.ts`, `registry.js`, `server.js`. The compiler emits its own `.gitignore` (`*`) inside the dir, plus belt-and-braces exclusions at: `.gitignore`, `eslint.config.js` ignores, `lint-staged.config.mjs` skip, and `vitest.config.ts` coverage.exclude. **Never edit, stage, or commit anything under `src/lib/paraglide/`** — it's regenerated on every compile.

`outputStructure` is **`message-modules`** → one module per message. The barrel `import * as m from '$lib/paraglide/messages'` is the normal call style and tree-shakes. A thin seam can deep-import a single message (see #668 below).

## Compile / build-order rule (critical)

The repo's `check`/`build` run `svelte-check`/`tsc` **before** Vite, so the generated dir must **pre-exist** or every `$lib/paraglide/*` import is an "implicitly any" error. A reusable `paraglide:compile` script handles this and is chained into the lifecycle scripts in `package.json`:

```jsonc
"paraglide:compile": "npx --no-install @inlang/paraglide-js compile --project ./project.inlang --outdir ./src/lib/paraglide --strategy localStorage preferredLanguage baseLocale --output-structure message-modules --emit-ts-declarations",
"postinstall": "npm run paraglide:compile",
"dev":   "npm run paraglide:compile && vite",
"build": "npm run paraglide:compile && tsc ... && vite build",
"check": "npm run paraglide:compile && svelte-check ...",
"typecheck": "npm run paraglide:compile && ..."
```

`postinstall` ensures fresh `npm ci` / CI / new worktrees have the dir. **If you ever see "Could not find a declaration file for `$lib/paraglide/*`", the generated dir is missing or stale — run `npm run paraglide:compile`.**

### Two CLI/plugin facts that bit the bootstrap (not guesses)

1. **The 2.20.1 CLI has no `--localStorageKey` flag**, and `--strategy` takes **space-separated** items (not repeated flags). The localStorage key `insp_locale` is set on the **Vite plugin only** (verified stamped into the production bundle). The CLI pass exists only to make the dir exist for `tsc`; the Vite plugin re-stamps the runtime strategy/key on `dev`/`build`.
2. **`--emit-ts-declarations` (CLI) + `emitTsDeclarations: true` (plugin) are required.** The runtime is `.js` with JSDoc; under this repo's strict `allowJs: false` tsconfig, bare `.js` imports don't type-check. Emitting `.d.ts` companions gives real types, including `export type Locale = (typeof locales)[number]`.

The Vite plugin config (in `vite.config.ts`):
```ts
paraglideVitePlugin({
  project: './project.inlang',
  outdir: './src/lib/paraglide',
  strategy: ['localStorage', 'preferredLanguage', 'baseLocale'],
  localStorageKey: 'insp_locale',
  outputStructure: 'message-modules',
  emitTsDeclarations: true,
})
```

## The locale rune + store mirror

Two views of one ambient locale, kept in lockstep by a single switch entry point. Runes files read the rune; legacy files subscribe to the store; **`switchLocale()` updates Paraglide's ambient locale + the store + the rune cell + `<html dir/lang>` in one call.**

- `src/lib/i18n/locale.svelte.ts` — the **`i18n` rune**: reactive `locale` getter, `set()`, `locales`, `baseLocale`, `initLocale()`. `Locale` is `(typeof locales)[number]`. Runes components read `i18n.locale` to register reactivity.
- `src/lib/i18n/locale-store.ts` — the legacy `writable` mirror **`localeStore`**, the single **`switchLocale()`** entry point, `registerRuneSetter()` (lets the store trip the rune cell), and a **`tr<T>(dep, value)`** reactivity-bridge helper for legacy `$:` blocks.

`setLocale(next, { reload: false })` is used everywhere — this is an SPA, so **no full page reload** on switch; the rune/store reactivity re-renders message calls in place.

`initLocale()` runs in `src/main.ts` **before mount** (mirrors `installAudioWarmup`), so the persisted `insp_locale` choice is applied on first paint.

## Switching locale in dev

- The mounted **`LocaleSwitcher.svelte`** (Svelte 5 runes, EN/ع toggle in the App header `auth-controls`) calls `i18n.set()`; active state reads `i18n.locale`. Click it to flip in-place — no reload, persists to `localStorage['insp_locale']`, flips `<html dir>` to `rtl` for Arabic.
- To force a locale without the UI: set `localStorage.setItem('insp_locale', 'ar')` in the browser console and reload, or call `switchLocale('ar')` from the console if exposed.
- The strategy chain is `localStorage → preferredLanguage → baseLocale`: an explicit `insp_locale` wins; otherwise the browser language; otherwise `en`.

## Deep-import vs barrel (#668)

- **Default:** `import * as m from '$lib/paraglide/messages'`, call `m.dashboard_x()`. Tree-shakes under `message-modules`.
- **Deep-import** a single message when a module needs the message **lazily** without pulling the barrel — e.g. `sign-in-messages.ts` backs object-keyed getters via `import { common_signin_edit_title } from '$lib/paraglide/messages/common_signin_edit_title'`. This keeps the seam's object-key contract intact while making each value a live message function.
- **inlang #668** is the known barrel-vs-deep-import gotcha: under some configs the barrel re-export and the per-message module can diverge. Our setup is verified working with both styles, but prefer the **barrel in components** and reserve **deep-imports for thin seams** that have a structural reason (preserving a `Record<...>` shape, lazy getters). Don't deep-import en masse "for performance" — the barrel already tree-shakes.

## Hand-author only — no inlang editor round-trip

**Author the `{en,ar}.json` by hand (Write/Edit tools).** The inlang web editor and the **Sherlock VS Code extension** do not understand the split `pathPattern` array on **write-back**: any save collapses all messages into the **last** file in the array and blanks the others. That destroys the per-area split, produces an unreviewable diff, and **still passes `npm run build`** (ids stay valid) — so the regression ships silently. Do not open the inlang editor, do not install/trigger Sherlock to write, do not let any "extract message" tooling write into these files. JSON shape is plain `{ "$schema": "...", "id": "text", ... }`.
