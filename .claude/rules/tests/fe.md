---
description: FE vitest discipline — component vs unit, mocking, runes, fakes
globs:
  - "inspector/frontend/src/**/*.test.ts"
  - "inspector/frontend/src/**/*.spec.ts"
  - "inspector/frontend/vitest.setup.ts"
---

# Tests — FE vitest

- Component tests colocated: `Foo.svelte` → `Foo.test.ts` next to it. Util/domain tests under `<dir>/__tests__/<feature>.test.ts`.
- `@testing-library/svelte` for components: `render`, `fireEvent`, `waitFor`. No raw DOM construction.
- Globals on. Don't `import { describe, it, expect } from 'vitest'`.
- `import { describe, expect, it }` (space after comma — ESLint enforces).
- Real imports + props-driven state for FE modules. `vi.mock(...)` only for ambient/external modules at module top.
- For audio fake elements use `audio._fireEvent('canplay')` — the stub method exposed by `makeAudioStub`. Not `audio._fire`, `audio.fire`, `audio.dispatchEvent`.
- For fetch: `vi.spyOn(window, 'fetch')` per test with a specific response. The `vitest.setup.ts` blanket-200 mock is a fallback only.
- For stores: import real store, call `.set()`, restore in `afterEach`. Don't `vi.mock` a store.
- Imperative scalars hidden behind setters (`_activeTab`, etc.) — reset via the setter (`setActiveTab(...)`), not the bare store `.set(...)`.

## Anti-patterns

- `.only` / `it.only` / `describe.only` / `test.only` committed → drop coverage of every sibling silently.
- `audio._fire(...)` → does not exist; the stub method is `_fireEvent`.
- `as any` cast on a typed command literal → use the discriminated-union member.
- `loadOptional<X>('path')` for a module that ships in main → static `import { X } from '../path'`. Phase gates outlive their reason fast.
- `describe.skipIf(!module)` after the gated module has landed → static import + drop the gate.
- Asserting `getAudioGraph(el).toBeNull()` on a suspended ctx → the graph is created; `_ctxResume` is the only observable. Verify what's actually observable.
- Wrong-arity spy (`_spying_set(url, peaks)` against `set_peaks_for_url(reciter, url, peaks)`) → grep the real signature first.
